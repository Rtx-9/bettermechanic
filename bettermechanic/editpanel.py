"""The Edit tab: Lightroom preset browser and develop sliders."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import develop
from .develop import BASIC, COLORS
from .views import card, section

PRESET_ROLE = Qt.UserRole + 11
MIXER_COLORS = {'Red': '#e5484d', 'Orange': '#f76b15', 'Yellow': '#f5c400', 'Green': '#30a46c', 'Aqua': '#12a594',
                'Blue': '#3e86f5', 'Purple': '#8e4ec6', 'Magenta': '#d6409f'}


class DevSlider(QWidget):
    """Label + value + slider. Emits (key, value, final); double-click the label to reset."""
    changed = Signal(str, float, bool)

    def __init__(self, key, label, lo, hi, step, color=None):
        super().__init__()
        self.key, self.step, self.neutral = key, step, develop.DEFAULTS.get(key, 0)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(0)
        self.name = QLabel(label)
        self.name.setObjectName('formlabel')
        self.name.setToolTip('Double-click to reset')
        if color:
            self.name.setText(f'<span style="color:{color}">●</span>  {label}')
        self.value = QLabel()
        self.value.setObjectName('slidervalue')
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName('devslider')
        self.slider.setRange(round(lo / step), round(hi / step))
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.valueChanged.connect(self._moved)
        self.slider.sliderReleased.connect(lambda: self._emit(True))
        lay.addWidget(self.name, 0, 0)
        lay.addWidget(self.value, 0, 1)
        lay.addWidget(self.slider, 1, 0, 1, 2)
        self._quiet = False
        self._final = QTimer(self, singleShot=True, interval=350, timeout=lambda: self._emit(True))
        self.set_value(self.neutral)

    def mouseDoubleClickEvent(self, e):
        self.set_value(self.neutral)
        self._emit(True)

    def val(self):
        v = self.slider.value() * self.step
        return round(v, 2) if self.step < 1 else int(round(v))

    def _show(self):
        v = self.val()
        if self.step < 1:
            self.value.setText(f'{v:+.2f}' if v else '0.00')
        else:
            self.value.setText(f'{v:+d}' if v and self.neutral == 0 else str(v))

    def set_value(self, v):
        self._quiet = True
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = self.neutral
        self.slider.setValue(round(v / self.step))
        self._show()
        self._quiet = False

    def _moved(self, _):
        self._show()
        if self._quiet:
            return
        self.changed.emit(self.key, self.val(), False)
        if not self.slider.isSliderDown():
            self._final.start()          # keyboard / wheel: commit shortly after

    def _emit(self, final):
        self._final.stop()
        self.changed.emit(self.key, self.val(), final)


class EditPanel(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName('inspector')
        body.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 6, 12, 14)
        lay.setSpacing(4)
        self.sliders = {}

        # --- presets
        head = QHBoxLayout()
        head.addWidget(section('Presets'), 1)
        imp = QToolButton()
        imp.setText('Import ▾')
        imp.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(imp)
        menu.addAction('Import Preset Files…  (.xmp, .lrtemplate, .zip)', self.import_files)
        menu.addAction('Import a Folder of Presets…', self.import_folder)
        menu.addSeparator()
        menu.addAction('Save Current Settings as Preset…', self.save_current)
        imp.setMenu(menu)
        head.addWidget(imp)
        lay.addLayout(head)
        c, cl = card()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search presets')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill_tree)
        cl.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName('presettree')
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(220)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemExpanded.connect(self._remember_groups)
        self.tree.itemCollapsed.connect(self._remember_groups)
        self.tree.setToolTip('Click a preset to apply it to the selected photos')
        cl.addWidget(self.tree)
        self.empty = QLabel('No presets yet. Use Import to add Lightroom presets: single files, whole folders or '
                            'the .zip packs presets usually come in.')
        self.empty.setWordWrap(True)
        self.empty.setObjectName('hint')
        cl.addWidget(self.empty)
        self.amount = DevSlider('__amount', 'Amount', 0, 200, 1)
        self.amount.neutral = 100
        self.amount.set_value(100)
        self.amount.changed.connect(lambda k, v, f: win.set_preset_amount(v / 100, f))
        self.amount.setEnabled(False)
        self.amount.setToolTip('Strength of the last applied preset')
        cl.addWidget(self.amount)
        lay.addWidget(c)

        # --- basic sliders
        for title, rows in BASIC:
            lay.addWidget(section(title))
            c, cl = card()
            if title == 'White Balance':
                note = QLabel('Relative to the white balance as shot')
                note.setObjectName('hint')
                cl.addWidget(note)
            for key, label, lo, hi, step in rows:
                s = DevSlider(key, label, lo, hi, step)
                s.changed.connect(win.set_develop)
                self.sliders[key] = s
                cl.addWidget(s)
            lay.addWidget(c)

        # --- colour mixer
        mh = QHBoxLayout()
        mh.addWidget(section('Color Mixer'), 1)
        lay.addLayout(mh)
        c, cl = card()
        seg = QFrame()
        seg.setObjectName('segmented')
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(2)
        self.mix_btns = {}
        for mode in ('Hue', 'Saturation', 'Luminance'):
            b = QToolButton()
            b.setText(mode)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, m=mode: self.set_mix_mode(m))
            self.mix_btns[mode] = b
            sl.addWidget(b)
        cl.addWidget(seg)
        self.bw = QCheckBox('Black & White')
        self.bw.setToolTip('Convert to black and white; the sliders then mix how light each colour becomes')
        self.bw.clicked.connect(lambda v: win.set_develop('ConvertToGrayscale', bool(v), True))
        cl.addWidget(self.bw)
        self.mixer = []
        for color in COLORS:
            s = DevSlider(f'HueAdjustment{color}', color, -100, 100, 1, MIXER_COLORS[color])
            s.changed.connect(win.set_develop)
            self.mixer.append((color, s))
            cl.addWidget(s)
        lay.addWidget(c)
        self.mix_mode = 'Hue'

        # --- actions
        row = QHBoxLayout()
        self.before = QPushButton('Before / After')
        self.before.setCheckable(True)
        self.before.setToolTip('Show the photo without edits (Y)')
        self.before.clicked.connect(lambda v: win.set_before_after(v))
        row.addWidget(self.before)
        lay.addSpacing(6)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        for text, fn, tip in (('Copy', win.copy_develop, 'Copy edit settings (Ctrl+Shift+C)'),
                              ('Paste', win.paste_develop, 'Paste edit settings onto the selection (Ctrl+Shift+V)'),
                              ('Reset', win.reset_develop, 'Remove all edits from the selection (Ctrl+Shift+R)')):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row2.addWidget(b)
        lay.addLayout(row2)
        note = QLabel('Edits are saved as Lightroom / Camera Raw settings, so Lightroom applies them to the RAW. '
                      'BetterMechanic shows an approximation on the camera\'s embedded JPEG.')
        note.setWordWrap(True)
        note.setObjectName('hint')
        lay.addWidget(note)
        lay.addStretch()
        self.set_mix_mode('Hue')
        self.fill_tree()

    # ---- presets
    def fill_tree(self, *_):
        q = self.search.text().strip().lower()
        lib = self.win.dev_presets
        self.tree.clear()
        open_groups = set(self.win.cfg.settings.get('open_preset_groups') or [])
        for group, items in sorted(lib.groups().items(), key=lambda kv: kv[0].lower()):
            shown = [p for p in items if not q or q in p['name'].lower() or q in group.lower()]
            if not shown:
                continue
            g = QTreeWidgetItem([f'{group}   ({len(shown)})'])
            f = QFont()
            f.setWeight(QFont.DemiBold)
            g.setFont(0, f)
            g.setData(0, PRESET_ROLE, ('group', group))
            for p in sorted(shown, key=lambda p: p['name'].lower()):
                ch = QTreeWidgetItem([p['name']])
                ch.setData(0, PRESET_ROLE, ('preset', p['id']))
                g.addChild(ch)
            self.tree.addTopLevelItem(g)
            g.setExpanded(bool(q) or group in open_groups)
        has = bool(lib.presets)
        self.empty.setVisible(not has)
        self.tree.setVisible(has)

    def _remember_groups(self, *_):
        groups = []
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            if g.isExpanded():
                groups.append(g.data(0, PRESET_ROLE)[1])
        if not self.search.text().strip():
            self.win.cfg.settings['open_preset_groups'] = groups

    def _clicked(self, item, _col):
        kind, val = item.data(0, PRESET_ROLE) or (None, None)
        if kind == 'preset':
            self.win.apply_develop_preset(val)
            self.amount.setEnabled(True)
            self.amount.set_value(100)
        elif kind == 'group':
            item.setExpanded(not item.isExpanded())

    def _tree_menu(self, pos):
        items = self.tree.selectedItems() or ([self.tree.itemAt(pos)] if self.tree.itemAt(pos) else [])
        if not items:
            return
        menu = QMenu(self)
        ids = []
        for it in items:
            kind, val = it.data(0, PRESET_ROLE)
            if kind == 'preset':
                ids.append(val)
            else:
                ids += [p['id'] for p in self.win.dev_presets.groups().get(val, [])]
        act = QAction(f'Delete {len(ids)} Preset{"s" if len(ids) != 1 else ""}', menu)
        act.triggered.connect(lambda: self._delete(ids))
        menu.addAction(act)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete(self, ids):
        if QMessageBox.question(self, 'Delete Presets', f'Delete {len(ids)} preset(s) from BetterMechanic? '
                                'Your photos keep their edits.') == QMessageBox.Yes:
            self.win.dev_presets.remove(ids)
            self.fill_tree()

    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import Lightroom Presets', '',
                                                'Lightroom presets (*.xmp *.lrtemplate *.zip);;All files (*)')
        if paths:
            self.win.import_develop_presets(paths)

    def import_folder(self):
        d = QFileDialog.getExistingDirectory(self, 'Import a Folder of Presets')
        if d:
            self.win.import_develop_presets([d])

    def save_current(self):
        it = (self.win.targets() or [None])[0]
        if it is None or not develop.is_active(it.develop):
            QMessageBox.information(self, 'Save Preset', 'Edit a photo first, then save its settings as a preset.')
            return
        name, ok = QInputDialog.getText(self, 'Save Preset', 'Preset name:')
        if ok and name.strip():
            self.win.dev_presets.add_user(name.strip(), 'User Presets', self.win.settings_to_copy(it))
            self.fill_tree()
            self.win.toast(f'Saved preset “{name.strip()}”')

    # ---- sliders
    def set_mix_mode(self, mode):
        self.mix_mode = mode
        for m, b in self.mix_btns.items():
            b.setChecked(m == mode)
        self.refresh(self.win.targets())

    def refresh(self, targets):
        it = targets[0] if targets else None
        dev = develop.clean(it.develop) if it else {}
        for key, s in self.sliders.items():
            s.set_value(dev.get(key, s.neutral))
            s.setEnabled(it is not None)
        gray = dev.get('ConvertToGrayscale') in (True, 'True', 'true')
        self.bw.setChecked(gray)
        self.bw.setEnabled(it is not None)
        for color, s in self.mixer:
            key = f'GrayMixer{color}' if gray else f'{self.mix_mode}Adjustment{color}'
            s.key = key
            s.set_value(dev.get(key, 0))
            s.setEnabled(it is not None)
        for b in self.mix_btns.values():
            b.setEnabled(not gray)
        self.amount.setEnabled(self.win.preset_ctx is not None and it is not None
                               and it.id in self.win.preset_ctx.get('before', {}))
