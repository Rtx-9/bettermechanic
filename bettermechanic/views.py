"""Widgets: contact sheet, filmstrip, loupe, tag-key panel, info panel."""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QStyle,
                               QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from . import core
from .config import key_label

ItemRole = Qt.UserRole + 1
ACCENT = QColor('#f5a524')
SEL = QColor('#2f6fd6')
LABEL_COLORS = {n.lower(): QColor(c) for n, c in core.LABELS}


class PhotoModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items, self.row_of = [], {}

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.row_of = {it.id: r for r, it in enumerate(self.items)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == ItemRole:
            return it
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return it.name
        return None

    def changed(self, item):
        r = self.row_of.get(item.id)
        if r is not None:
            ix = self.index(r)
            self.dataChanged.emit(ix, ix)


class PixCache:
    """Thumbnails are kept as small JPEG bytes; decoded pixmaps live in an LRU."""

    def __init__(self, limit=1500):
        self.d, self.limit = OrderedDict(), limit

    def get(self, item):
        if not item.thumb:
            return None
        hit = self.d.get(item.id)
        if hit and hit[0] is item.thumb:
            self.d.move_to_end(item.id)
            return hit[1]
        pm = QPixmap()
        pm.loadFromData(item.thumb)
        self.d[item.id] = (item.thumb, pm)
        if len(self.d) > self.limit:
            self.d.popitem(last=False)
        return pm

    def clear(self):
        self.d.clear()


class ThumbDelegate(QStyledItemDelegate):
    CAP = 22

    def __init__(self, win, compact=False):
        super().__init__()
        self.win, self.compact = win, compact
        self.small = QFont()
        self.small.setPointSizeF(8)

    def sizeHint(self, opt, idx):
        return self.win.strip_cell if self.compact else self.win.cell

    def frame_rect(self, r):
        r = r.adjusted(3, 3, -3, -3)
        return r

    def tag_rect(self, r):
        r = self.frame_rect(r)
        return QRect(r.left() + 6, r.bottom() - self.CAP + 5, 13, 13)

    def paint(self, p: QPainter, opt, idx):
        it = idx.data(ItemRole)
        if it is None:
            return
        view = opt.widget
        m = it.meta
        r = self.frame_rect(opt.rect)
        sel = bool(opt.state & QStyle.State_Selected)
        cur = view is not None and view.currentIndex() == idx
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#24364f') if sel else QColor('#1c1e22'))
        p.drawRoundedRect(r, 6, 6)
        cap = 0 if self.compact else self.CAP
        img = r.adjusted(5, 5, -5, -5 - cap)
        pm = self.win.pix.get(it)
        if pm and not pm.isNull():
            s = min(img.width() / pm.width(), img.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            tgt = QRectF(img.x() + (img.width() - w) / 2, img.y() + (img.height() - h) / 2, w, h)
            if m['rating'] == -1:
                p.setOpacity(0.3)
            p.drawPixmap(tgt, pm, QRectF(pm.rect()))
            p.setOpacity(1)
        else:
            if it.tstate == 0:
                self.win.thumbs_wanted()
            p.setPen(QColor('#666'))
            p.setFont(self.small)
            p.drawText(img, Qt.AlignCenter, 'No preview' if it.tstate == -1 else '')
        if m['rating'] == -1:
            p.setPen(QPen(QColor('#e5484d'), 3))
            c = img.center()
            d = min(img.width(), img.height()) // 6
            p.drawLine(c.x() - d, c.y() - d, c.x() + d, c.y() + d)
            p.drawLine(c.x() - d, c.y() + d, c.x() + d, c.y() - d)
        lc = LABEL_COLORS.get((m['label'] or '').lower())
        if lc:
            p.setPen(Qt.NoPen)
            p.setBrush(lc)
            p.drawEllipse(QRect(img.left() + 3, img.top() + 3, 10, 10))
        if self.compact:
            if m['tagged']:
                p.setPen(Qt.NoPen)
                p.setBrush(ACCENT)
                p.drawRect(QRect(r.left() + 4, r.bottom() - 6, r.width() - 8, 3))
        else:
            p.setFont(self.small)
            fm = QFontMetrics(self.small)
            badge = 'RAW+JPG' if it.is_pair else it.primary.ext.upper()
            bw = fm.horizontalAdvance(badge) + 8
            br = QRect(img.right() - bw - 2, img.top() + 2, bw, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(br, 3, 3)
            p.setPen(QColor('#ddd'))
            p.drawText(br, Qt.AlignCenter, badge)
            # player chips
            x, y = img.left() + 3, img.bottom() - 17
            for i, n in enumerate(m['people']):
                txt = n if i < 4 else f'+{len(m["people"]) - 4}'
                cw = fm.horizontalAdvance(txt) + 10
                if x + cw > img.right() - 2:
                    txt, cw = '…', 16
                cr = QRect(x, y, cw, 15)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(15, 15, 18, 215))
                p.drawRoundedRect(cr, 7, 7)
                p.setPen(QColor('#ffd28a'))
                p.drawText(cr, Qt.AlignCenter, txt)
                x += cw + 3
                if i >= 4 or txt == '…':
                    break
            # caption line: tag box, name, stars
            tb = self.tag_rect(opt.rect)
            p.setPen(QPen(ACCENT if m['tagged'] else QColor('#666'), 1.5))
            p.setBrush(ACCENT if m['tagged'] else Qt.NoBrush)
            p.drawRoundedRect(tb, 3, 3)
            if m['tagged']:
                p.setPen(QPen(QColor('#111'), 2))
                p.drawLine(tb.left() + 3, tb.center().y(), tb.center().x() - 1, tb.bottom() - 3)
                p.drawLine(tb.center().x() - 1, tb.bottom() - 3, tb.right() - 2, tb.top() + 3)
            stars = '★' * m['rating'] if m['rating'] > 0 else ''
            sw = fm.horizontalAdvance(stars) + 4 if stars else 0
            name_r = QRect(tb.right() + 6, tb.top() - 3, r.right() - tb.right() - 12 - sw, 18)
            p.setPen(QColor('#cfd3da'))
            p.drawText(name_r, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(it.name, Qt.ElideMiddle, name_r.width()))
            if stars:
                p.setPen(ACCENT)
                p.drawText(QRect(r.right() - sw - 4, tb.top() - 3, sw, 18), Qt.AlignVCenter | Qt.AlignRight, stars)
        if cur:
            p.setPen(QPen(QColor('#ffffff') if not self.compact else ACCENT, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        elif sel:
            p.setPen(QPen(SEL, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        p.restore()


class GridView(QListView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSpacing(0)
        self.setWrapping(True)
        self.setFrameShape(QFrame.NoFrame)
        self.verticalScrollBar().setSingleStep(40)
        self.verticalScrollBar().valueChanged.connect(lambda _: win.thumbs_wanted())
        self.doubleClicked.connect(lambda _: win.enter_loupe())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.win.relayout()

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and e.button() == Qt.LeftButton:
            if self.itemDelegate().tag_rect(self.visualRect(idx)).adjusted(-3, -3, 3, 3).contains(e.position().toPoint()):
                self.win.toggle_tagged([idx.data(ItemRole)])
                return
        super().mousePressEvent(e)

    def visible_rows(self):
        n = self.model().rowCount() if self.model() else 0
        if not n:
            return range(0)
        vp = self.viewport().rect()
        cw, ch = self.win.cell.width(), self.win.cell.height()
        first = self.indexAt(QPoint(cw // 2, ch // 2))
        last = self.indexAt(QPoint(vp.width() - cw // 2, vp.height() - ch // 2))
        cols = max(1, vp.width() // max(1, cw))
        a = first.row() if first.isValid() else 0
        b = last.row() if last.isValid() else min(n - 1, a + cols * (vp.height() // max(1, ch) + 1))
        return range(max(0, a - cols), min(n, b + 1 + cols * 2))


class Filmstrip(QListView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setFixedHeight(win.strip_cell.height() + 18)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - e.angleDelta().y())


class Loupe(QWidget):
    navigate = Signal(int)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item, self.pix, self.level = None, None, 0
        self.zoom, self.cx, self.cy = False, 0.5, 0.5
        self.drag, self.target = None, None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.big = QFont()
        self.big.setPointSize(11)

    def set_item(self, item):
        if item is not self.item:
            self.item, self.pix, self.level = item, None, 0
        self.update()

    def offer(self, item, pix, level):
        if item is self.item and pix is not None and not pix.isNull() and level > self.level:
            self.pix, self.level = pix, level
            self.update()

    def set_zoom(self, z, at=None):
        if z and at is not None and self.target:
            t = self.target
            self.cx = min(1, max(0, (at.x() - t.x()) / t.width()))
            self.cy = min(1, max(0, (at.y() - t.y()) / t.height()))
        self.zoom = z
        self.setCursor(Qt.OpenHandCursor if z else Qt.CrossCursor)
        self.win.loupe_zoom_changed()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#0b0c0e'))
        it, pm = self.item, self.pix
        if it is None:
            return
        W, H = self.width(), self.height()
        if pm is not None and not pm.isNull():
            dpr = self.devicePixelRatioF()
            sw, sh = pm.width(), pm.height()
            full_w = max(it.w or 0, sw)
            full_h = full_w * sh / sw
            if not self.zoom:
                s = min(W / sw, H / sh, full_w / sw / dpr)
                dw, dh = sw * s, sh * s
                x, y = (W - dw) / 2, (H - dh) / 2
            else:
                dw, dh = full_w / dpr, full_h / dpr
                x, y = W / 2 - self.cx * dw, H / 2 - self.cy * dh
                x = (W - dw) / 2 if dw <= W else min(0, max(W - dw, x))
                y = (H - dh) / 2 if dh <= H else min(0, max(H - dh, y))
                self.cx, self.cy = (W / 2 - x) / dw, (H / 2 - y) / dh
            self.target = QRectF(x, y, dw, dh)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(self.target, pm, QRectF(pm.rect()))
        else:
            p.setPen(QColor('#777'))
            p.drawText(self.rect(), Qt.AlignCenter, 'Loading…' if it.tstate != -1 else 'No preview available')
        self._overlay(p, it, W, H)

    def _overlay(self, p, it, W, H):
        m = it.meta
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.big)
        fm = QFontMetrics(self.big)
        row = self.win.current_row()
        left = f'{row + 1} / {self.win.model.rowCount()}    {it.name}'
        info = core.fmt_exposure(it.exif)
        bar = QRect(0, 0, W, 30)
        p.fillRect(bar, QColor(0, 0, 0, 120))
        p.setPen(QColor('#e8e8e8'))
        p.drawText(bar.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, left + ('     ' + info if info else ''))
        flags = []
        if m['tagged']:
            flags.append(('TAGGED', ACCENT))
        if m['rating'] == -1:
            flags.append(('REJECT', QColor('#e5484d')))
        elif m['rating'] > 0:
            flags.append(('★' * m['rating'], ACCENT))
        if m['label']:
            flags.append((m['label'], LABEL_COLORS.get(m['label'].lower(), QColor('#aaa'))))
        x = W - 12
        for txt, col in flags:
            w = fm.horizontalAdvance(txt) + 14
            x -= w
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRect(x, 5, w, 20), 4, 4)
            p.setPen(QColor('#111'))
            p.drawText(QRect(x, 5, w, 20), Qt.AlignCenter, txt)
            x -= 6
        # players
        x, y = 12, H - 40
        for n in m['people']:
            w = fm.horizontalAdvance(n) + 22
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(15, 15, 18, 220))
            p.drawRoundedRect(QRect(x, y, w, 28), 14, 14)
            p.setPen(QColor('#ffd28a'))
            p.drawText(QRect(x, y, w, 28), Qt.AlignCenter, n)
            x += w + 6
        if self.zoom:
            p.setPen(QColor('#bbb'))
            p.drawText(QRect(0, H - 34, W - 14, 24), Qt.AlignRight | Qt.AlignVCenter, '100%')

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = (e.position(), self.cx, self.cy, False)
            if self.zoom:
                self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self.drag:
            return
        start, cx, cy, moved = self.drag
        d = e.position() - start
        if abs(d.x()) + abs(d.y()) > 3:
            self.drag = (start, cx, cy, True)
        if self.zoom and self.target:
            self.cx = cx - d.x() / self.target.width()
            self.cy = cy - d.y() / self.target.height()
            self.update()

    def mouseReleaseEvent(self, e):
        drag, self.drag = self.drag, None
        if self.zoom:
            self.setCursor(Qt.OpenHandCursor)
        if drag and not drag[3] and e.button() == Qt.LeftButton:
            self.set_zoom(not self.zoom, e.position())

    def mouseDoubleClickEvent(self, e):
        pass

    def wheelEvent(self, e):
        if not self.zoom:
            self.navigate.emit(-1 if e.angleDelta().y() > 0 else 1)


# ------------------------------------------------------------------ panels

class SlotRow(QFrame):
    clicked = Signal(int)
    edit = Signal(int)

    def __init__(self, i):
        super().__init__()
        self.i = i
        self.setObjectName('slot')
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 4, 2)
        lay.setSpacing(6)
        self.key = QLabel(key_label(i))
        self.key.setObjectName('kbd')
        self.key.setAlignment(Qt.AlignCenter)
        self.key.setFixedWidth(30)
        self.name = QLabel()
        self.count = QLabel()
        self.count.setObjectName('dim')
        self.btn = QToolButton()
        self.btn.setText('✎')
        self.btn.setObjectName('editslot')
        self.btn.setToolTip('Rename this key')
        self.btn.clicked.connect(lambda: self.edit.emit(self.i))
        lay.addWidget(self.key)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.count)
        lay.addWidget(self.btn)
        self._state = None

    def set(self, name, state, count):
        self.name.setText(name or '—')
        self.count.setText(str(count) if count else '')
        st = state if name else 'empty'
        if st != self._state:
            self._state = st
            self.setProperty('state', st)
            self.style().unpolish(self)
            self.style().polish(self)
            for w in (self.name, self.key, self.count):
                w.style().unpolish(w)
                w.style().polish(w)

    def flash(self):
        self.setProperty('state', 'flash')
        self.style().unpolish(self)
        self.style().polish(self)
        self._state = 'flash'

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.i)


class KeysPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        t = QLabel('TAG KEYS')
        t.setObjectName('h')
        head.addWidget(t)
        head.addStretch()
        edit = QPushButton('Edit presets…')
        edit.setObjectName('mini')
        edit.clicked.connect(win.open_presets)
        head.addWidget(edit)
        lay.addLayout(head)
        sw = QHBoxLayout()
        self.prev = QToolButton()
        self.prev.setText('‹')
        self.next = QToolButton()
        self.next.setText('›')
        self.combo = QComboBox()
        self.prev.clicked.connect(lambda: win.cycle_preset(-1))
        self.next.clicked.connect(lambda: win.cycle_preset(1))
        self.combo.activated.connect(self._pick)
        sw.addWidget(self.prev)
        sw.addWidget(self.combo, 1)
        sw.addWidget(self.next)
        lay.addLayout(sw)
        hint = QLabel('P / Shift+P switches preset')
        hint.setObjectName('dim')
        lay.addWidget(hint)
        self.rows = []
        for i in range(20):
            if i in (0, 10):
                g = QLabel('Keys 1 – 0' if i == 0 else 'Shift + 1 – 0')
                g.setObjectName('group')
                lay.addWidget(g)
            r = SlotRow(i)
            r.clicked.connect(win.toggle_slot)
            r.edit.connect(win.rename_slot)
            self.rows.append(r)
            lay.addWidget(r)
        clear = QPushButton('Clear players  (Backspace)')
        clear.clicked.connect(lambda: win.clear_people())
        lay.addSpacing(6)
        lay.addWidget(clear)
        lay.addSpacing(10)
        mh = QHBoxLayout()
        t2 = QLabel('METADATA PRESETS')
        t2.setObjectName('h')
        mh.addWidget(t2)
        mh.addStretch()
        me = QPushButton('Edit…')
        me.setObjectName('mini')
        me.clicked.connect(win.open_meta_presets)
        mh.addWidget(me)
        lay.addLayout(mh)
        self.meta_box = QVBoxLayout()
        lay.addLayout(self.meta_box)
        lay.addStretch()

    def _pick(self, i):
        self.win.cfg.active_tag = self.win.cfg.tag_presets[i]['id']
        self.win.preset_changed()

    def refresh_presets(self):
        cfg = self.win.cfg
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in cfg.tag_presets:
            self.combo.addItem(p['name'] or 'Untitled')
        self.combo.setCurrentIndex(next(i for i, p in enumerate(cfg.tag_presets) if p['id'] == cfg.tag['id']))
        self.combo.blockSignals(False)
        while self.meta_box.count():
            w = self.meta_box.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for mp in cfg.meta_presets:
            b = QPushButton('Apply  ' + mp['name'])
            b.setObjectName('apply')
            b.setToolTip('Apply this metadata preset to the selected photos')
            b.clicked.connect(lambda _=False, pid=mp['id']: self.win.apply_meta_preset(pid))
            self.meta_box.addWidget(b)

    def refresh(self, targets, counts):
        slots = self.win.cfg.tag['slots']
        n = len(targets)
        for i, r in enumerate(self.rows):
            name = slots[i].strip()
            have = sum(1 for it in targets if name in it.meta['people']) if name and n <= 2000 else 0
            state = 'on' if n and have == n else 'part' if have else 'off'
            r.set(name, state, counts.get(name, 0))


class EditBox(QPlainTextEdit):
    committed = Signal()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self.document().isModified():
            self.document().setModified(False)
            self.committed.emit()


class InfoPanel(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 12)
        self.file = QLabel()
        self.file.setWordWrap(True)
        self.file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.file.setObjectName('fileinfo')
        lay.addWidget(self.file)

        fl = QHBoxLayout()
        self.stars = []
        for n in range(1, 6):
            b = QToolButton()
            b.setText('★')
            b.setObjectName('star')
            b.setToolTip(f'{n} star{"s" if n > 1 else ""}  (Alt+{n})')
            b.clicked.connect(lambda _=False, n=n: win.set_rating(n))
            self.stars.append(b)
            fl.addWidget(b)
        fl.addStretch()
        self.rej = QToolButton()
        self.rej.setText('✕ Reject')
        self.rej.setCheckable(True)
        self.rej.setToolTip('Reject (X)')
        self.rej.clicked.connect(lambda: win.set_rating(-1))
        fl.addWidget(self.rej)
        lay.addLayout(fl)

        ll = QHBoxLayout()
        self.labels = {}
        for i, (name, col) in enumerate(core.LABELS):
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(f'{name} label' + (f'  (Alt+{i + 6})' if i < 4 else ''))
            b.setStyleSheet(f'QToolButton{{background:{col};border-radius:9px;min-width:18px;max-width:18px;'
                            f'min-height:18px;max-height:18px;border:2px solid transparent}}'
                            f'QToolButton:checked{{border:2px solid white}}')
            b.clicked.connect(lambda _=False, n=name: win.set_label(n))
            self.labels[name] = b
            ll.addWidget(b)
        ll.addStretch()
        self.tag = QCheckBox('Tagged  (T)')
        self.tag.clicked.connect(lambda: win.toggle_tagged())
        ll.addWidget(self.tag)
        lay.addLayout(ll)

        ph = QLabel('PLAYERS / PEOPLE')
        ph.setObjectName('h')
        lay.addSpacing(6)
        lay.addWidget(ph)
        self.people = QListWidget()
        self.people.setObjectName('people')
        self.people.setMaximumHeight(110)
        self.people.setToolTip('Double-click a name to remove it from the selected photos')
        self.people.itemDoubleClicked.connect(lambda it: win.remove_person(it.data(Qt.UserRole)))
        lay.addWidget(self.people)
        self.add_person = QLineEdit()
        self.add_person.setPlaceholderText('Add a name and press Enter')
        self.add_person.returnPressed.connect(self._add_person)
        lay.addWidget(self.add_person)

        lay.addSpacing(6)
        h = QLabel('IPTC / CAPTION')
        h.setObjectName('h')
        lay.addWidget(h)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(5)
        self.fields = {}
        for key, label, multi in core.META_FORM:
            if multi:
                w = EditBox()
                w.setFixedHeight(84 if key == 'caption' else 54)
                w.committed.connect(lambda k=key, w=w: win.set_field(k, w.toPlainText()))
            else:
                w = QLineEdit()
                w.editingFinished.connect(lambda k=key, w=w: w.isModified() and win.set_field(k, w.text()))
            self.fields[key] = w
            form.addRow(label, w)
        lay.addLayout(form)
        lay.addStretch()

    def _add_person(self):
        name = self.add_person.text().strip()
        if name:
            self.win.add_person(name)
        self.add_person.clear()

    def refresh(self, targets):
        n = len(targets)
        it = targets[0] if targets else None
        if not it:
            self.file.setText('<span style="color:#888">No photo selected</span>')
        elif n > 1:
            self.file.setText(f'<b>{n} photos selected</b><br><span style="color:#888">'
                              f'{core.fmt_bytes(sum(t.size for t in targets))}</span>')
        else:
            from datetime import datetime
            when = datetime.fromtimestamp(it.time).strftime('%Y-%m-%d  %H:%M:%S') if it.time else ''
            sub = it.exif.get('subsec')
            if sub and when:
                when += f'.{str(sub).strip()[:2]}'
            files = ' + '.join(f.name for f in it.files)
            cam = ' '.join(str(x) for x in (it.exif.get('make', ''), it.exif.get('model', '')) if x)
            lines = [f'<b>{files}</b>',
                     f'{it.w} × {it.h}   ·   {core.fmt_bytes(it.size)}' if it.w else core.fmt_bytes(it.size),
                     when, cam, str(it.exif.get('lens') or ''), core.fmt_exposure(it.exif),
                     f'<span style="color:#888">{it.dir}</span>']
            if it.save_error:
                lines.append(f'<span style="color:#e5484d">Save failed: {it.save_error}</span>')
            self.file.setText('<br>'.join(x for x in lines if x))
        metas = [t.meta for t in targets]
        common = lambda k: (metas[0][k] if metas and all(m[k] == metas[0][k] for m in metas) else None)
        r = common('rating')
        for i, b in enumerate(self.stars):
            b.setProperty('on', bool(r and r > 0 and i < r))
            b.style().unpolish(b)
            b.style().polish(b)
        self.rej.setChecked(r == -1)
        lab = common('label')
        for name, b in self.labels.items():
            b.setChecked(lab == name)
        tg = common('tagged')
        self.tag.setCheckState(Qt.Checked if tg else Qt.Unchecked if tg is False or not metas else Qt.PartiallyChecked)
        counts = {}
        for m in metas:
            for p in m['people']:
                counts[p] = counts.get(p, 0) + 1
        self.people.clear()
        for p, c in counts.items():
            from PySide6.QtWidgets import QListWidgetItem
            li = QListWidgetItem(p if c == n else f'{p}   ({c}/{n})')
            li.setData(Qt.UserRole, p)
            self.people.addItem(li)
        for key, w in self.fields.items():
            if w.hasFocus():
                continue
            if key == 'keywords':
                vals = [', '.join(m['keywords']) for m in metas]
            else:
                vals = [m[key] for m in metas]
            same = bool(vals) and all(v == vals[0] for v in vals)
            text = vals[0] if same else ''
            w.setPlaceholderText('' if same or not vals else '‹multiple values›')
            if isinstance(w, QLineEdit):
                if w.text() != text:
                    w.setText(text)
                w.setModified(False)
            else:
                if w.toPlainText() != text:
                    w.setPlainText(text)
                w.document().setModified(False)
            w.setEnabled(bool(vals))
