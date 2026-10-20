"""Main window: wires the views, the background workers and every action together."""
from __future__ import annotations

import os
import sys
from collections import Counter, OrderedDict

from PySide6.QtCore import QEvent, QItemSelectionModel, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTextEdit,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

from . import core, icons, theme
from .avatars import AvatarStore
from .config import key_label
from .picker import PlayerPicker, RosterEditor
from .dialogs import CopyDialog, HelpDialog, MetaPresets, PresetBoard, SettingsDialog
from .views import Filmstrip, GridView, InfoPanel, KeysPanel, Loupe, PhotoModel, PixCache, ThumbDelegate
from .workers import Bus, CopyJob, Loader, Saver

K = lambda name: getattr(Qt.Key, name).value          # noqa: E731
MAC_DIGITS = {29: 0, 18: 1, 19: 2, 20: 3, 21: 4, 23: 5, 22: 6, 26: 7, 28: 8, 25: 9}

FILTERS = [
    ('all', 'All photos', lambda it: True),
    ('tagged', 'Tagged', lambda it: it.meta['tagged']),
    ('untagged', 'Untagged', lambda it: not it.meta['tagged']),
    ('not_rejected', 'Not rejected', lambda it: it.meta['rating'] != -1),
    ('rejected', 'Rejected', lambda it: it.meta['rating'] == -1),
    ('rated', '★ 1 or more', lambda it: it.meta['rating'] >= 1),
    ('rated3', '★ 3 or more', lambda it: it.meta['rating'] >= 3),
    ('people', 'Has players', lambda it: bool(it.meta['people'])),
    ('nopeople', 'No players yet', lambda it: not it.meta['people']),
    ('labeled', 'Has color label', lambda it: bool(it.meta['label'])),
]
SORTS = [('name', 'File name'), ('time', 'Capture time'), ('time_desc', 'Newest first')]


def digit_of(ev):
    """Physical number key 0-9 regardless of Shift / keyboard layout, else None."""
    k = ev.key()
    if K('Key_0') <= k <= K('Key_9'):
        return k - K('Key_0')
    if sys.platform == 'win32':
        vk = ev.nativeVirtualKey()
        if 0x30 <= vk <= 0x39:
            return vk - 0x30
        if 0x60 <= vk <= 0x69:
            return vk - 0x60
    elif sys.platform == 'darwin':
        return MAC_DIGITS.get(ev.nativeVirtualKey())
    else:
        sc = ev.nativeScanCode()
        if 10 <= sc <= 19:
            return (sc - 9) % 10
    return None


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.bus = Bus()
        self.loader = Loader(self.bus, cfg.settings)
        self.saver = Saver(self.bus, cfg.settings)
        self.pix = PixCache()
        self.avatars = AvatarStore(os.path.join(os.path.dirname(str(cfg.path)), 'avatars'))
        self.cell = QSize(190, 174)
        self.strip_cell = QSize(96, 76)
        self.items, self.root, self.root_name = [], None, ''
        self.ingest = self.readonly = False
        self.mode = 'grid'
        self.dirty = {}
        self.pv_cache, self.pv_inflight = OrderedDict(), set()
        self.model = PhotoModel()
        self.setWindowTitle('BetterMechanic')
        self.setAcceptDrops(True)
        self._build()
        self._timers()
        b = self.bus
        b.thumb_ready.connect(self.on_thumb)
        b.meta_ready.connect(self.on_meta)
        b.preview_ready.connect(self.on_preview)
        b.saved.connect(self.on_saved)
        QApplication.instance().installEventFilter(self)
        self.keys.refresh_presets()
        self.refresh_panels()
        self.update_status()
        geo = cfg.window.get('geometry')
        if geo:
            self.restoreGeometry(bytes.fromhex(geo))
        else:
            self.resize(1500, 920)

    # ================================================================ UI
    def icon(self, name):
        return icons.icon(name, theme.qc('accent') if name == 'text' else theme.qc('label'))

    def _tool(self, tb, name, text, fn, tip, label=True, checkable=False):
        b = QToolButton()
        b._icon = name
        b.setIcon(self.icon(name))
        b.setIconSize(QSize(18, 18))
        b.setText(text)
        b.setToolTip(tip)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if label else Qt.ToolButtonIconOnly)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCheckable(checkable)
        if fn:
            b.clicked.connect(fn)
        tb.addWidget(b)
        self._tools.append(b)
        return b

    def _build(self):
        self._tools = []
        tb = QToolBar()
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(tb)
        self.tb_sidebar = self._tool(tb, 'sidebar_left', 'Sidebar', self.toggle_sidebar,
                                     'Show or hide the tag keys sidebar', label=False, checkable=True)
        titles = QWidget()
        tl = QVBoxLayout(titles)
        tl.setContentsMargins(8, 0, 14, 0)
        tl.setSpacing(0)
        self.title = QLabel('BetterMechanic')
        self.title.setObjectName('title')
        self.subtitle = QLabel('No folder open')
        self.subtitle.setObjectName('subtitle')
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        titles.setMinimumWidth(170)
        tb.addWidget(titles)
        self.open_btn = self._tool(tb, 'folder', 'Open', lambda: self.choose_folder(False), 'Open a folder (Ctrl+O)')
        self.recent_menu = QMenu(self)
        self.open_btn.setMenu(self.recent_menu)
        self.open_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self._tool(tb, 'card', 'Ingest', lambda: self.choose_folder(True), 'Ingest from a memory card (Ctrl+I)')
        self._tool(tb, 'export', 'Export', self.open_copy, 'Copy & export (Ctrl+E)')
        tb.addWidget(self._spacer())
        seg = QFrame()
        seg.setObjectName('segmented')
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(2)
        self.seg_grid, self.seg_loupe = QToolButton(), QToolButton()
        group = QButtonGroup(self)
        for b, name, tip, fn in ((self.seg_grid, 'grid', 'Contact sheet', self.exit_loupe),
                                 (self.seg_loupe, 'photo', 'Large preview (Enter)', self.enter_loupe)):
            b._icon = name
            b.setIcon(self.icon(name))
            b.setIconSize(QSize(16, 16))
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            group.addButton(b)
            sl.addWidget(b)
            self._tools.append(b)
        self.seg_grid.setChecked(True)
        tb.addWidget(seg)
        tb.addWidget(self._spacer())
        self.filter = QComboBox()
        for k, t, _ in FILTERS:
            self.filter.addItem(t, k)
        self.filter.setToolTip('Show')
        self.filter.currentIndexChanged.connect(lambda _: (self.apply_view(), self.grid.setFocus()))
        tb.addWidget(self.filter)
        self.sort = QComboBox()
        for k, t in SORTS:
            self.sort.addItem(t, k)
        self.sort.setToolTip('Sort by')
        self.sort.currentIndexChanged.connect(lambda _: (self.apply_view(), self.grid.setFocus()))
        tb.addWidget(self.sort)
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(110, 460)
        self.size.setValue(int(self.cfg.settings['thumb_size']))
        self.size.setFixedWidth(96)
        self.size.setToolTip('Thumbnail size')
        self.size.setFocusPolicy(Qt.NoFocus)
        self.size.valueChanged.connect(self._resize_thumbs)
        tb.addWidget(self.size)
        self.search = QLineEdit()
        self.search.setObjectName('search')
        self.search.setPlaceholderText('Search')
        self.search.setToolTip('Search file names, players, keywords and captions (Ctrl+F)')
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search_icon = self.search.addAction(self.icon('search'), QLineEdit.LeadingPosition)
        self._search_timer = QTimer(self, singleShot=True, interval=250, timeout=self.apply_view)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        tb.addWidget(self.search)
        self._tool(tb, 'tag', 'Tag Presets', self.open_presets, 'Tag presets: player keys', label=False)
        self._tool(tb, 'text', 'Metadata Presets', self.open_meta_presets, 'Metadata presets (Ctrl+M)', label=False)
        self._tool(tb, 'gear', 'Settings', lambda: SettingsDialog(self).exec(), 'Settings (Ctrl+,)', label=False)
        self._tool(tb, 'help', 'Help', lambda: HelpDialog(self).exec(), 'Keyboard shortcuts (F1)', label=False)
        self.tb_inspector = self._tool(tb, 'sidebar_right', 'Inspector', self.toggle_inspector,
                                       'Show or hide the inspector (I)', label=False, checkable=True)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        self.keys = KeysPanel(self)
        self.left = QScrollArea()
        self.left.setWidget(self.keys)
        self.left.setWidgetResizable(True)
        self.left.setFrameShape(QFrame.NoFrame)
        self.left.setMinimumWidth(240)
        split.addWidget(self.left)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.banner = QFrame()
        self.banner.setObjectName('banner')
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 10, 8)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        ib = QPushButton('Start Ingest…')
        ib.setObjectName('primary')
        ib.clicked.connect(self.open_copy)
        bl.addWidget(ib)
        self.banner.hide()
        cl.addWidget(self.banner)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)

        self.empty = self._empty_page()
        self.stack.addWidget(self.empty)
        self.grid = GridView(self)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(ThumbDelegate(self))
        self.grid.setGridSize(self.cell)
        self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.stack.addWidget(self.grid)
        lp = QWidget()
        ll = QVBoxLayout(lp)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        self.loupe = Loupe(self)
        self.loupe.navigate.connect(self.move)
        ll.addWidget(self.loupe, 1)
        self.strip = Filmstrip(self)
        self.strip.setModel(self.model)
        self.strip.setItemDelegate(ThumbDelegate(self, compact=True))
        self.strip.setSelectionModel(self.grid.selectionModel())
        self.strip.horizontalScrollBar().valueChanged.connect(lambda _: self.thumbs_wanted())
        ll.addWidget(self.strip)
        self.loupe_page = lp
        self.stack.addWidget(lp)
        split.addWidget(center)

        self.info = InfoPanel(self)
        self.info.setMinimumWidth(300)
        split.addWidget(self.info)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1000, 340])
        self.setCentralWidget(split)
        self.tb_sidebar.setChecked(True)
        self.tb_inspector.setChecked(True)

        sm = self.grid.selectionModel()
        sm.currentChanged.connect(self.on_current)
        sm.selectionChanged.connect(lambda *_: self.panels_later())

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_count, self.st_thumbs, self.st_preset, self.st_save = QLabel(), QLabel(), QLabel(), QLabel()
        sb.addWidget(self.st_thumbs)
        sb.addPermanentWidget(self.st_preset)
        sb.addPermanentWidget(self.st_save)

        for seq, fn in (('Ctrl+O', lambda: self.choose_folder(False)), ('Ctrl+I', lambda: self.choose_folder(True)),
                        ('Ctrl+E', self.open_copy), ('Ctrl+S', self.flush_saves), ('Ctrl+D', self.select_none),
                        ('Ctrl+A', self.select_all), ('Ctrl+F', lambda: (self.search.setFocus(), self.search.selectAll())),
                        ('Ctrl+M', self.open_meta_presets), ('Ctrl+,', lambda: SettingsDialog(self).exec())):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.rebuild_recent()
        hints = QApplication.styleHints()
        if hasattr(hints, 'colorSchemeChanged'):
            hints.colorSchemeChanged.connect(self._system_scheme_changed)

    def _system_scheme_changed(self, *_):
        if self.cfg.settings.get('appearance', 'system') == 'system':
            self.apply_appearance()

    @staticmethod
    def _spacer():
        s = QWidget()
        s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return s

    def apply_appearance(self):
        theme.apply(QApplication.instance(), self.cfg.settings.get('appearance', 'system'))
        for b in self._tools:
            b.setIcon(self.icon(b._icon))
        self.search_icon.setIcon(self.icon('search'))
        self.info.restyle()
        self.keys.refresh_presets()
        for v in (self.grid.viewport(), self.strip.viewport(), self.loupe):
            v.update()

    def toggle_sidebar(self):
        self.left.setVisible(not self.left.isVisible())
        self.tb_sidebar.setChecked(self.left.isVisible())

    def toggle_inspector(self):
        self.info.setVisible(not self.info.isVisible())
        self.tb_inspector.setChecked(self.info.isVisible())

    def _empty_page(self):
        w = QWidget()
        w.setObjectName('empty')
        w.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(w)
        lay.addStretch()
        t = QLabel('BetterMechanic')
        t.setObjectName('hero')
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        s = QLabel('Open a folder or a memory card, or drop a folder here.\n'
                   'Number keys tag players from your preset; Shift + number tags players 11–20.')
        s.setAlignment(Qt.AlignCenter)
        s.setObjectName('herosub')
        lay.addWidget(s)
        row = QHBoxLayout()
        row.addStretch()
        for text, fn, prim in (('Ingest from Card…', lambda: self.choose_folder(True), False),
                               ('Open Folder…', lambda: self.choose_folder(False), True)):
            b = QPushButton(text)
            if prim:
                b.setObjectName('primary')
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addSpacing(16)
        lay.addLayout(row)
        rl = QLabel('Recent')
        rl.setObjectName('section')
        rl.setAlignment(Qt.AlignCenter)
        self.empty_recent_label = rl
        lay.addSpacing(18)
        lay.addWidget(rl)
        self.empty_recent = QVBoxLayout()
        self.empty_recent.setSpacing(0)
        lay.addLayout(self.empty_recent)
        lay.addStretch()
        return w

    def _timers(self):
        self.save_timer = QTimer(self, singleShot=True, interval=700, timeout=self.flush_saves)
        self.vis_timer = QTimer(self, singleShot=True, interval=40, timeout=self.update_visible)
        self.panel_timer = QTimer(self, singleShot=True, interval=40, timeout=self.refresh_panels)
        self.status_timer = QTimer(self, interval=500, timeout=self.update_status)
        self.status_timer.start()
        self.toast_timer = QTimer(self, singleShot=True, interval=2600, timeout=lambda: self.statusBar().clearMessage())

    # ============================================================ helpers
    def toast(self, msg, ms=2600):
        self.statusBar().showMessage('   ' + msg, ms)

    def all_items(self):
        return self.model.items

    def current_row(self):
        ix = self.grid.selectionModel().currentIndex()
        return ix.row() if ix.isValid() else -1

    def current_item(self):
        r = self.current_row()
        return self.model.items[r] if 0 <= r < len(self.model.items) else None

    def targets(self):
        if self.mode == 'loupe':
            it = self.current_item()
            return [it] if it else []
        rows = sorted({ix.row() for ix in self.grid.selectionModel().selectedIndexes()})
        if rows:
            return [self.model.items[r] for r in rows]
        it = self.current_item()
        return [it] if it else []

    def loaded(self, items):
        pending = [it for it in items if not it.meta_loaded]
        if pending:
            if len(pending) > 20:
                QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for i, it in enumerate(pending):
                    core.ensure_meta(it, self.cfg.settings)
                    if i % 50 == 49:
                        QApplication.processEvents()
            finally:
                if len(pending) > 20:
                    QApplication.restoreOverrideCursor()
        return items

    def thumbs_wanted(self):
        if not self.vis_timer.isActive():
            self.vis_timer.start()

    def panels_later(self):
        if not self.panel_timer.isActive():
            self.panel_timer.start()

    def relayout(self):
        vw = self.grid.viewport().width() - 6
        target = int(self.cfg.settings['thumb_size'])
        cols = max(1, vw // target)
        cw = max(80, vw // cols)
        cell = QSize(cw, int(cw * 0.78) + 22)
        if cell != self.cell:
            self.cell = cell
            self.grid.setGridSize(cell)
            self.thumbs_wanted()

    def _resize_thumbs(self, v):
        self.cfg.settings['thumb_size'] = v
        self.relayout()
        self.grid.doItemsLayout()
        self.cfg_save_later()

    def cfg_save_later(self):
        if not hasattr(self, '_cfg_timer'):
            self._cfg_timer = QTimer(self, singleShot=True, interval=800, timeout=self.cfg.save)
        self._cfg_timer.start()

    def update_visible(self):
        if self.mode == 'grid':
            rows = self.grid.visible_rows()
        else:
            r = max(0, self.current_row())
            rows = range(max(0, r - 10), min(len(self.model.items), r + 14))
        items = [self.model.items[i] for i in rows if i < len(self.model.items)]
        size = max(160, min(640, round(max(self.cell.width(), self.cell.height()) * self.devicePixelRatioF())))
        for it in items:
            if it.tstate == 2 and it.tq and it.tq < size * 0.8:
                it.tstate = 1
        self.loader.set_visible(items, size)

    # ========================================================== folders
    def choose_folder(self, ingest=False):
        start = self.root or os.path.expanduser('~')
        d = QFileDialog.getExistingDirectory(self, 'Choose the memory card (or a folder) to ingest from' if ingest
                                             else 'Open folder', start)
        if d:
            self.open_folder(d, ingest=ingest)

    def confirm_leave(self):
        if self.ingest and any(it.edited for it in self.items):
            r = QMessageBox.question(self, 'Leave ingest?', 'You tagged or culled photos on this card but have not '
                                     'ingested them yet. Those choices will be lost. Continue?')
            return r == QMessageBox.Yes
        return True

    def open_folder(self, path, ingest=False, recursive=None):
        if not os.path.isdir(path):
            self.toast(f'Folder not found: {path}')
            return
        if not self.confirm_leave():
            return
        self.flush_saves()
        rec = recursive if recursive is not None else self.cfg.settings['ingest_recursive' if ingest else 'recursive']
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            def prog(n):
                self.statusBar().showMessage(f'   Scanning {os.path.basename(path)}… {n} photos')
                QApplication.processEvents()
            files, sidecars = core.scan_folder(path, rec, prog)
            items = core.build_items(files, sidecars, self.cfg.settings['group_pairs'])
        finally:
            QApplication.restoreOverrideCursor()
        self.exit_loupe()
        self.items, self.root, self.root_name = items, path, os.path.basename(os.path.normpath(path)) or path
        self.ingest = ingest
        self.readonly = ingest or not os.access(path, os.W_OK)
        self.dirty.clear()
        self.pix.clear()
        self.pv_cache.clear()
        self.pv_inflight.clear()
        self.cfg.add_recent(path, ingest)
        self.cfg.save()
        self.rebuild_recent()
        self.setWindowTitle(f'{self.root_name} — BetterMechanic' + ('  [INGEST]' if ingest else ''))
        if ingest:
            self.banner_text.setText(f'<b>INGEST</b> — <b>{self.root_name}</b> is open read-only. Cull and tag here '
                                     f'(nothing is written to the card), then start the ingest to copy what you keep.')
        elif self.readonly:
            self.banner_text.setText('This folder is read-only: changes stay in memory. Use Copy & export to save copies.')
        self.banner.setVisible(self.readonly)
        self.banner.findChild(QPushButton).setVisible(ingest)
        self.apply_view(reset=True)
        self.toast(f'{len(items)} photos' + (' — nothing to show here' if not items else ''))
        self.grid.setFocus()

    def rebuild_recent(self):
        self.recent_menu.clear()
        while self.empty_recent.count():
            w = self.empty_recent.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for r in self.cfg.recent:
            p, ing = r.get('path', ''), r.get('ingest', False)
            label = p + ('   (ingest)' if ing else '')
            self.recent_menu.addAction(label, lambda p=p, ing=ing: self.open_folder(p, ingest=ing))
            if self.empty_recent.count() < 6:
                b = QPushButton(label)
                b.setObjectName('plain')
                b.clicked.connect(lambda _=False, p=p, ing=ing: self.open_folder(p, ingest=ing))
                self.empty_recent.addWidget(b, 0, Qt.AlignHCenter)
        if not self.cfg.recent:
            self.recent_menu.addAction('No Recent Folders').setEnabled(False)
        self.empty_recent_label.setVisible(bool(self.cfg.recent))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(os.path.isdir(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if os.path.isdir(u.toLocalFile()):
                self.open_folder(u.toLocalFile())
                break

    def apply_view(self, reset=False):
        cur = None if reset else self.current_item()
        q = self.search.text().strip().lower()
        fkey = self.filter.currentData()
        skey = self.sort.currentData()
        if fkey != 'all' or skey != 'name' or q:
            self.loaded(self.items)
        f = next(fn for k, _, fn in FILTERS if k == fkey)

        def hay(it):
            m = it.meta
            return ' '.join([it.name, *m['people'], *m['keywords'], m['caption'], m['headline']]).lower()

        lst = [it for it in self.items if f(it) and (not q or q in hay(it))]
        name_key = lambda it: (it.dir.lower(), core.natural_key(it.name))
        if skey == 'time':
            lst.sort(key=lambda it: (it.time, name_key(it)))
        elif skey == 'time_desc':
            lst.sort(key=lambda it: (-it.time, name_key(it)))
        else:
            lst.sort(key=name_key)
        self.model.set_items(lst)
        self.loader.set_items(lst)
        self.stack.setCurrentWidget(self.grid if self.items else self.empty)
        if lst:
            row = self.model.row_of.get(cur.id, 0) if cur else 0
            ix = self.model.index(row)
            self.grid.selectionModel().setCurrentIndex(ix, QItemSelectionModel.ClearAndSelect)
            self.grid.scrollTo(ix)
        self.relayout()
        self.thumbs_wanted()
        self.panels_later()

    # ============================================================ loupe
    def enter_loupe(self):
        if not self.current_item():
            return
        self.mode = 'loupe'
        self.seg_loupe.setChecked(True)
        self.stack.setCurrentWidget(self.loupe_page)
        self.show_current()
        self.strip.scrollTo(self.grid.selectionModel().currentIndex(), QAbstractItemView.PositionAtCenter)
        self.loupe.setFocus()
        self.thumbs_wanted()
        self.panels_later()

    def exit_loupe(self):
        self.seg_grid.setChecked(True)
        if self.mode != 'loupe':
            return
        self.mode = 'grid'
        self.loupe.zoom = False
        self.stack.setCurrentWidget(self.grid if self.items else self.empty)
        ix = self.grid.selectionModel().currentIndex()
        if ix.isValid():
            self.grid.scrollTo(ix)
        self.grid.setFocus()
        self.thumbs_wanted()
        self.panels_later()

    def on_current(self, cur, _prev):
        if self.mode == 'loupe':
            self.show_current()
            self.strip.scrollTo(cur, QAbstractItemView.PositionAtCenter)
            self.thumbs_wanted()
        self.panels_later()

    def move(self, step):
        n = len(self.model.items)
        if not n:
            return
        r = min(n - 1, max(0, self.current_row() + step))
        self.grid.selectionModel().setCurrentIndex(self.model.index(r), QItemSelectionModel.ClearAndSelect)

    def screen_box(self):
        scr = self.screen() or QApplication.primaryScreen()
        g, d = scr.size(), scr.devicePixelRatio()
        return round(g.width() * d), round(g.height() * d)

    def request_preview(self, it, full, urgent=True):
        key = (it.id, full)
        if key in self.pv_cache or key in self.pv_inflight:
            return
        self.pv_inflight.add(key)
        self.loader.preview(it, full, None if full else self.screen_box(), urgent)

    def show_current(self):
        it = self.current_item()
        self.loupe.set_item(it)
        if not it:
            return
        full, fit = self.pv_cache.get((it.id, True)), self.pv_cache.get((it.id, False))
        if full:
            self.loupe.offer(it, full, 3)
        elif fit:
            self.loupe.offer(it, fit, 2)
        else:
            pm = self.pix.get(it)
            if pm:
                self.loupe.offer(it, pm, 1)
        if not fit and not full:
            self.request_preview(it, False)
        if self.loupe.zoom and not full:
            self.request_preview(it, True)
        r = self.current_row()
        for d in (1, 2, -1, 3):
            j = r + d
            if 0 <= j < len(self.model.items):
                self.request_preview(self.model.items[j], False, urgent=False)

    def loupe_zoom_changed(self):
        it = self.loupe.item
        if it and self.loupe.zoom:
            self.request_preview(it, True)

    def on_preview(self, it, full, img):
        self.pv_inflight.discard((it.id, full))
        if img is None:
            if self.loupe.item is it:
                self.loupe.update()
            return
        w, h, data = img
        if not it.w:
            it.w, it.h = w, h
        pm = QPixmap.fromImage(QImage(data, w, h, 3 * w, QImage.Format_RGB888))
        self.pv_cache[(it.id, full)] = pm
        cur = self.loupe.item.id if self.loupe.item else None
        fits = [k for k in self.pv_cache if not k[1] and k[0] != cur]
        fulls = [k for k in self.pv_cache if k[1] and k[0] != cur]
        for k in fits[:-12] + fulls[:-2]:
            self.pv_cache.pop(k, None)
        if self.loupe.item is it:
            self.loupe.offer(it, pm, 3 if full else 2)

    # ===================================================== worker events
    def on_thumb(self, it):
        self.model.changed(it)
        if self.mode == 'loupe' and self.loupe.item is it and self.loupe.level == 0:
            pm = self.pix.get(it)
            if pm:
                self.loupe.offer(it, pm, 1)

    def on_meta(self, it):
        self.model.changed(it)
        if self.mode == 'loupe' and self.loupe.item is it:
            self.loupe.update()
        self.panels_later()

    def on_saved(self, it, err):
        it.save_error = err
        if err:
            self.toast(f'Could not save {it.name}: {err}', 6000)
        self.model.changed(it)
        self.update_status()

    # ========================================================== editing
    def edit(self, fn, lst=None):
        ts = lst if lst is not None else self.targets()
        if not ts:
            self.toast('Select a photo first')
            return None
        self.loaded(ts)
        fn(ts)
        for it in ts:
            it.edited = True
            if not self.readonly:
                self.dirty[it.id] = it
            self.model.changed(it)
        if not self.readonly and self.cfg.settings.get('auto_save', True):
            self.save_timer.start()
        self.loupe.update()
        self.panels_later()
        self.update_status()
        return ts

    def flush_saves(self):
        if self.readonly:
            return
        for it in self.dirty.values():
            self.saver.put(it)
        self.dirty.clear()
        self.update_status()

    def advance(self, ts):
        if ts and self.cfg.settings.get('auto_advance') and len(ts) == 1:
            self.move(1)

    def after_people(self, it, added):
        p = self.cfg.tag
        if added and p.get('keywords'):
            it.meta['keywords'] = core.M.uniq(it.meta['keywords'] + core.split_list(p['keywords']))
        if p.get('auto_caption') and p.get('caption_tpl'):
            it.meta['caption'] = core.expand(p['caption_tpl'], it, preset_name=p['name'])

    def toggle_slot(self, i):
        p = self.cfg.tag
        name = p['slots'][i].strip()
        if not name:
            self.toast(f'Key {key_label(i)} is empty in “{p["name"]}”. Hover it and click Edit, or press F to pick a player')
            return
        self.toggle_name(name)

    def toggle_name(self, name):
        """Add `name` to the target photos, or remove it if every target already has it."""
        state = {}

        def fn(ts):
            state['rm'] = all(name in it.meta['people'] for it in ts)
            for it in ts:
                ppl = it.meta['people']
                if state['rm']:
                    if name in ppl:
                        ppl.remove(name)
                elif name not in ppl:
                    ppl.append(name)
                self.after_people(it, not state['rm'])

        ts = self.edit(fn)
        if ts:
            n = len(ts)
            self.toast(f'{"Removed" if state["rm"] else "Tagged"} {name} {"from" if state["rm"] else "on"} '
                       f'{n} photo{"s" if n > 1 else ""}')
        return ts

    def open_picker(self):
        if not self.items:
            self.toast('Open a folder or card first')
            return
        if not self.targets():
            self.toast('Select a photo first')
            return
        PlayerPicker(self).exec()
        self.panels_later()

    def open_roster(self, preset=None):
        p = preset or self.cfg.tag
        if RosterEditor(self, p).exec():
            self.cfg.save()
            self.preset_changed(quiet=True)
            return True
        return False

    def add_person(self, name):
        def fn(ts):
            for it in ts:
                if name not in it.meta['people']:
                    it.meta['people'].append(name)
                    self.after_people(it, True)
        self.edit(fn)

    def remove_person(self, name):
        def fn(ts):
            for it in ts:
                if name in it.meta['people']:
                    it.meta['people'].remove(name)
                    self.after_people(it, False)
        self.edit(fn)

    def clear_people(self):
        def fn(ts):
            for it in ts:
                it.meta['people'] = []
                self.after_people(it, False)
        if self.edit(fn):
            self.toast('Cleared players')

    def toggle_tagged(self, lst=None):
        def fn(ts):
            v = not all(it.meta['tagged'] for it in ts)
            for it in ts:
                it.meta['tagged'] = v
        self.advance(self.edit(fn, lst))

    def set_rating(self, n):
        def fn(ts):
            if n == -1:
                v = 0 if all(it.meta['rating'] == -1 for it in ts) else -1
            else:
                v = n
            for it in ts:
                it.meta['rating'] = v
        self.advance(self.edit(fn))

    def set_label(self, name):
        def fn(ts):
            v = '' if all(it.meta['label'] == name for it in ts) else name
            for it in ts:
                it.meta['label'] = v
        self.edit(fn)

    def set_field(self, key, value):
        def fn(ts):
            for it in ts:
                it.meta[key] = core.split_list(value) if key == 'keywords' else value
        self.edit(fn)

    def apply_meta_preset(self, pid, mode='replace'):
        p = self.cfg.meta_preset(pid)
        if not p:
            return
        ts = self.edit(lambda ts: [core.apply_meta_preset(it.meta, p, it, mode, self.cfg.tag['name']) for it in ts])
        if ts:
            self.toast(f'Applied “{p["name"]}” to {len(ts)} photo(s)')

    def select_all(self):
        if self.focusWidget() in (self.search,):
            self.search.selectAll()
            return
        self.grid.selectAll()

    def select_none(self):
        self.grid.selectionModel().clearSelection()

    # ========================================================== presets
    def cycle_preset(self, step):
        self.cfg.cycle_tag(step)
        self.preset_changed()

    def preset_changed(self, quiet=False):
        self.cfg.save()
        self.keys.refresh_presets()
        self.panels_later()
        self.update_status()
        if not quiet:
            self.toast(f'Tag preset: {self.cfg.tag["name"]}')

    def rename_slot(self, i):
        p = self.cfg.tag
        text, ok = QInputDialog.getText(self, 'Name for key ' + key_label(i),
                                        f'Player for key {key_label(i)} in “{p["name"]}”:', text=p['slots'][i])
        if ok:
            p['slots'][i] = text.strip()
            self.preset_changed(quiet=True)

    def open_presets(self):
        PresetBoard(self).exec()
        self.preset_changed(quiet=True)

    def open_meta_presets(self):
        MetaPresets(self).exec()
        self.keys.refresh_presets()

    # ============================================================= copy
    def open_copy(self):
        if not self.items:
            self.toast('Open a folder or card first')
            return
        self.flush_saves()
        CopyDialog(self, ingest=self.ingest).exec()

    def start_copy(self, o):
        job = CopyJob(self.bus, list(self.model.items), [it.id for it in self.targets()], o, self.cfg.settings,
                      self.cfg.meta_preset(o.get('meta_preset')), self.cfg.tag['name'])
        job.start()
        return job

    # ========================================================= painting
    def refresh_panels(self):
        ts = self.targets()
        if len(ts) <= 300:
            self.loaded(ts)
        counts = Counter(p for it in self.items if it.meta_loaded for p in it.meta['people'])
        self.keys.refresh(ts, counts)
        self.info.refresh(ts[:300])

    def update_status(self):
        n, shown = len(self.items), len(self.model.items)
        sel = len(self.grid.selectionModel().selectedIndexes()) if n else 0
        self.title.setText(self.root_name or 'BetterMechanic')
        if n:
            sub = f'{shown} of {n} photos' if shown != n else f'{n} photos'
            if sel > 1:
                sub += f', {sel} selected'
            if self.ingest:
                sub += '  ·  Ingest'
        else:
            sub = 'No folder open'
        self.subtitle.setText(sub)
        done = sum(1 for it in self.items if it.tstate != 0)
        self.st_thumbs.setText(f'Previews {done}/{n}' if n and done < n else '')
        self.st_preset.setText(f'Tag preset: {self.cfg.tag["name"]}')
        if self.ingest:
            s = 'Ingest mode — changes go into the copies'
        elif self.readonly and self.items:
            s = 'Read-only'
        elif self.saver.pending:
            s = f'Saving {self.saver.pending}…'
        elif self.dirty:
            s = f'{len(self.dirty)} unsaved (Ctrl+S)'
        else:
            s = 'All changes saved' if self.items else ''
        self.st_save.setText(s + '  ')

    # =========================================================== keys
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and isinstance(obj, QWidget) and obj.window() is self:
            fw = QApplication.focusWidget()
            if isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
                if ev.key() == K('Key_Escape'):
                    fw.clearFocus()
                    (self.loupe if self.mode == 'loupe' else self.grid).setFocus()
                    return True
                return False
            if self.handle_key(ev):
                return True
        return False

    def handle_key(self, ev):
        mods = ev.modifiers()
        ctrl = bool(mods & (Qt.ControlModifier | Qt.MetaModifier))
        alt, shift = bool(mods & Qt.AltModifier), bool(mods & Qt.ShiftModifier)
        d = digit_of(ev)
        if d is not None and not ctrl:
            if not self.items:
                return True
            if alt:
                if 1 <= d <= 5:
                    self.set_rating(d)
                elif 6 <= d <= 9:
                    self.set_label(core.LABELS[d - 6][0])
                else:
                    self.set_rating(0)
            else:
                self.toggle_slot((9 if d == 0 else d - 1) + (10 if shift else 0))
            return True
        if ctrl:
            return False
        k = ev.key()
        if k in (K('Key_Return'), K('Key_Enter'), K('Key_Space')):
            self.exit_loupe() if self.mode == 'loupe' else self.enter_loupe()
        elif k == K('Key_Escape'):
            if self.mode == 'loupe':
                self.exit_loupe()
            else:
                return False
        elif k == K('Key_T'):
            self.toggle_tagged()
        elif k == K('Key_X'):
            self.set_rating(-1)
        elif k == K('Key_Z'):
            if self.mode == 'loupe':
                self.loupe.set_zoom(not self.loupe.zoom)
            else:
                self.enter_loupe()
                self.loupe.set_zoom(True)
        elif k == K('Key_P'):
            self.cycle_preset(-1 if shift else 1)
        elif k in (K('Key_F'), K('Key_Slash')):
            self.open_picker()
        elif k in (K('Key_Backspace'), K('Key_Delete')):
            self.clear_people()
        elif k in (K('Key_F1'), K('Key_Question')):
            HelpDialog(self).exec()
        elif k == K('Key_I'):
            self.toggle_inspector()
        elif k == K('Key_G'):
            self.exit_loupe() if self.mode == 'loupe' else self.enter_loupe()
        elif k in (K('Key_Left'), K('Key_Right'), K('Key_Up'), K('Key_Down'), K('Key_Home'), K('Key_End'),
                   K('Key_PageUp'), K('Key_PageDown')):
            if self.mode == 'loupe':
                step = {K('Key_Left'): -1, K('Key_Up'): -1, K('Key_Right'): 1, K('Key_Down'): 1,
                        K('Key_PageUp'): -10, K('Key_PageDown'): 10, K('Key_Home'): -10 ** 9,
                        K('Key_End'): 10 ** 9}[k]
                self.move(step)
                return True
            if QApplication.focusWidget() is not self.grid:
                self.grid.setFocus()
                self.grid.keyPressEvent(ev)
                return True
            return False
        else:
            return False
        return True

    # ============================================================ close
    def closeEvent(self, e):
        if not self.confirm_leave():
            e.ignore()
            return
        self.flush_saves()
        if self.saver.pending:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            import time
            t0 = time.time()
            while self.saver.pending and time.time() - t0 < 20:
                QApplication.processEvents()
                time.sleep(0.05)
            QApplication.restoreOverrideCursor()
        self.cfg.window['geometry'] = bytes(self.saveGeometry().data()).hex()
        self.cfg.save()
        e.accept()
