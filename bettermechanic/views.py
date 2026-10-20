"""Widgets: contact sheet, filmstrip, loupe, tag-key sidebar, inspector."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QScrollArea, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from . import core, theme
from .config import key_label
from .theme import qc

ItemRole = Qt.UserRole + 1
HUD = QColor(22, 22, 24, 200)


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


def _check(p, r: QRectF, fill: QColor, ring: QColor | None = None):
    """Round check badge (filled) or empty ring."""
    if ring is not None:
        p.setPen(QPen(ring, 1.5))
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(r)
        return
    p.setPen(QPen(QColor(255, 255, 255), 1.5))
    p.setBrush(fill)
    p.drawEllipse(r)
    p.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    c = r.center()
    s = r.width() / 18
    p.drawPolyline([QPointF(c.x() - 4.2 * s, c.y() + 0.2 * s), QPointF(c.x() - 1.2 * s, c.y() + 3.2 * s),
                    QPointF(c.x() + 4.4 * s, c.y() - 3 * s)])


class ThumbDelegate(QStyledItemDelegate):
    CAP = 24

    def __init__(self, win, compact=False):
        super().__init__()
        self.win, self.compact = win, compact
        self.small = QFont()
        self.small.setPointSizeF(max(7.5, QFont().pointSizeF() - 1.5))

    def sizeHint(self, opt, idx):
        return self.win.strip_cell if self.compact else self.win.cell

    def frame_rect(self, r):
        r = QRect(r).adjusted(4, 4, -4, -4)
        if not self.compact:
            r.setBottom(r.bottom() - self.CAP)
        return r

    def tag_rect(self, r):
        f = self.frame_rect(r)
        return QRect(f.left() + 8, f.top() + 8, 20, 20)

    def paint(self, p: QPainter, opt, idx):
        it = idx.data(ItemRole)
        if it is None:
            return
        view = opt.widget
        m = it.meta
        frame = self.frame_rect(opt.rect)
        sel = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        cur = view is not None and view.currentIndex() == idx
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        if sel or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qc('accent_soft') if sel else qc('hover'))
            p.drawRoundedRect(QRectF(opt.rect).adjusted(2, 2, -2, -2), 9, 9)

        img = frame.adjusted(6, 6, -6, -6)
        pm = self.win.pix.get(it)
        if pm and not pm.isNull():
            s = min(img.width() / pm.width(), img.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            tgt = QRectF(img.x() + (img.width() - w) / 2, img.y() + (img.height() - h) / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(tgt, 4, 4)
            p.save()
            p.setClipPath(clip)
            if m['rating'] == -1:
                p.setOpacity(0.32)
            p.drawPixmap(tgt, pm, QRectF(pm.rect()))
            p.restore()
            if sel:
                p.setPen(QPen(qc('accent'), 3 if cur else 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(tgt.adjusted(-2.5, -2.5, 2.5, 2.5), 6, 6)
            elif cur:
                p.setPen(QPen(qc('secondary'), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(tgt.adjusted(-2.5, -2.5, 2.5, 2.5), 6, 6)
        else:
            if it.tstate == 0:
                self.win.thumbs_wanted()
            p.setPen(Qt.NoPen)
            p.setBrush(qc('cell'))
            p.drawRoundedRect(QRectF(img), 6, 6)
            p.setPen(qc('tertiary'))
            p.setFont(self.small)
            p.drawText(img, Qt.AlignCenter, 'No Preview' if it.tstate == -1 else '')

        if m['rating'] == -1:
            c, d = QPointF(img.center()), min(img.width(), img.height()) / 7
            p.setPen(QPen(qc('red'), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))

        if self.compact:
            if m['tagged']:
                _check(p, QRectF(frame.left() + 4, frame.top() + 4, 13, 13), qc('orange'))
            p.restore()
            return

        p.setFont(self.small)
        fm = QFontMetrics(self.small)
        # tag check (Photos-style round badge), shown on hover when untagged
        tr = QRectF(self.tag_rect(opt.rect))
        if m['tagged']:
            _check(p, tr, qc('orange'))
        elif hover:
            _check(p, tr, None, QColor(255, 255, 255, 200))
        # format badge (+ "Edited" when it has develop settings)
        badge = 'RAW+JPEG' if it.is_pair else it.primary.ext.upper()
        if it.looks_edited:
            badge = 'Edited · ' + badge
        bw = fm.horizontalAdvance(badge) + 10
        br = QRectF(frame.right() - bw - 8, frame.top() + 9, bw, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(br, 8, 8)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(br, Qt.AlignCenter, badge)
        # players
        x, y = img.left() + 4, img.bottom() - 21
        ppl = m['people']
        for i, n in enumerate(ppl):
            txt = n if i < 3 else f'+{len(ppl) - 3}'
            cw = fm.horizontalAdvance(txt) + 14
            if x + cw > img.right() - 4:
                txt, cw = '…', 20
            cr = QRectF(x, y, cw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(HUD)
            p.drawRoundedRect(cr, 9, 9)
            p.setPen(QColor(255, 255, 255))
            p.drawText(cr, Qt.AlignCenter, txt)
            x += cw + 4
            if i >= 3 or txt == '…':
                break
        # caption: label dot · file name · stars
        cap = QRect(opt.rect.left() + 8, frame.bottom() + 2, opt.rect.width() - 16, self.CAP - 4)
        stars = '★' * m['rating'] if m['rating'] > 0 else ''
        lc = theme.label_colors().get((m['label'] or '').lower())
        sw = fm.horizontalAdvance(' ' + stars) if stars else 0
        dot = 12 if lc else 0
        name = fm.elidedText(it.name, Qt.ElideMiddle, cap.width() - sw - dot)
        total = dot + fm.horizontalAdvance(name) + sw
        x0 = cap.left() + (cap.width() - total) / 2
        cy = cap.center().y()
        if lc:
            p.setPen(Qt.NoPen)
            p.setBrush(lc)
            p.drawEllipse(QPointF(x0 + 4, cy + 1), 4, 4)
        p.setPen(qc('label') if sel else qc('secondary'))
        p.drawText(QRectF(x0 + dot, cap.top(), fm.horizontalAdvance(name) + 2, cap.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, name)
        if stars:
            p.setPen(qc('orange'))
            p.drawText(QRectF(x0 + dot + fm.horizontalAdvance(name), cap.top(), sw + 2, cap.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, ' ' + stars)
        p.restore()


class GridView(QListView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName('grid')
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSpacing(0)
        self.setWrapping(True)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setViewportMargins(8, 8, 0, 0)
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
        self.setObjectName('strip')
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setFixedHeight(win.strip_cell.height() + 16)
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
        self.hud = QFont()
        self.hud_bold = QFont()
        self.hud_bold.setWeight(QFont.DemiBold)

    def set_item(self, item):
        if item is not self.item:
            self.item, self.pix, self.level = item, None, 0
        self.update()

    def force(self, item, pix, level):
        if item is self.item and pix is not None and not pix.isNull():
            self.pix, self.level = pix, level
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
        p.fillRect(self.rect(), QColor('#0e0e10'))
        it, pm = self.item, self.pix
        if it is None:
            return
        W, H = self.width(), self.height()
        p.setRenderHint(QPainter.Antialiasing)
        if pm is not None and not pm.isNull():
            dpr = self.devicePixelRatioF()
            sw, sh = pm.width(), pm.height()
            full_w = max(it.w or 0, sw)
            full_h = full_w * sh / sw
            if not self.zoom:
                pad = 16
                s = min((W - 2 * pad) / sw, (H - 2 * pad) / sh, full_w / sw / dpr)
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
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(self.rect(), Qt.AlignCenter, 'Loading…' if it.tstate != -1 else 'No Preview Available')
        self._overlay(p, it, W, H)

    def _hud(self, p, r, radius=10):
        p.setPen(Qt.NoPen)
        p.setBrush(HUD)
        p.drawRoundedRect(r, radius, radius)

    def _overlay(self, p, it, W, H):
        m = it.meta
        fm, fb = QFontMetrics(self.hud), QFontMetrics(self.hud_bold)
        row = self.win.current_row()
        title = it.name
        sub = f'{row + 1} of {self.win.model.rowCount()}'
        info = core.fmt_exposure(it.exif)
        if info:
            sub += '   ·   ' + info
        w = max(fb.horizontalAdvance(title), fm.horizontalAdvance(sub)) + 28
        r = QRectF(14, 14, w, 46)
        self._hud(p, r)
        p.setFont(self.hud_bold)
        p.setPen(QColor(255, 255, 255))
        p.drawText(r.adjusted(14, 6, 0, -22), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setFont(self.hud)
        p.setPen(QColor(255, 255, 255, 160))
        p.drawText(r.adjusted(14, 23, 0, -5), Qt.AlignLeft | Qt.AlignVCenter, sub)

        flags = []
        if getattr(self.win, 'before_after', False) and it.looks_edited:
            flags.append(('Before', QColor('#8e8e93')))
        if m['tagged']:
            flags.append(('Tagged', qc('orange')))
        if m['rating'] == -1:
            flags.append(('Rejected', qc('red')))
        elif m['rating'] > 0:
            flags.append(('★' * m['rating'], qc('orange')))
        if m['label']:
            flags.append((m['label'], theme.label_colors().get(m['label'].lower(), QColor('#999'))))
        x = W - 14
        p.setFont(self.hud_bold)
        for txt, col in flags:
            bw = fb.horizontalAdvance(txt) + 26
            x -= bw
            br = QRectF(x, 14, bw, 28)
            self._hud(p, br, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(br.left() + 11, br.center().y()), 4, 4)
            p.setPen(QColor(255, 255, 255))
            p.drawText(br.adjusted(19, 0, -4, 0), Qt.AlignCenter, txt)
            x -= 8

        ppl = m['people']
        if ppl:
            widths = [fb.horizontalAdvance(n) + 28 for n in ppl]
            total = sum(widths) + 8 * (len(ppl) - 1)
            x = max(14, (W - total) / 2)
            for n, bw in zip(ppl, widths):
                br = QRectF(x, H - 50, bw, 34)
                self._hud(p, br, 17)
                p.setPen(QColor(255, 255, 255))
                p.drawText(br, Qt.AlignCenter, n)
                x += bw + 8
        if self.zoom:
            br = QRectF(W - 72, H - 46, 58, 28)
            self._hud(p, br, 14)
            p.setPen(QColor(255, 255, 255))
            p.setFont(self.hud_bold)
            p.drawText(br, Qt.AlignCenter, '100%')

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

    def wheelEvent(self, e):
        if not self.zoom:
            self.navigate.emit(-1 if e.angleDelta().y() > 0 else 1)


# ----------------------------------------------------------------- sidebar

def section(text, link=None, fn=None):
    """Section header row; optional trailing text button."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(text)
    lab.setObjectName('section')
    lay.addWidget(lab)
    lay.addStretch()
    if link:
        b = QPushButton(link)
        b.setObjectName('plain')
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        lay.addWidget(b)
    return w


class SlotRow(QFrame):
    clicked = Signal(int)
    edit = Signal(int)

    def __init__(self, i):
        super().__init__()
        self.i = i
        self.setObjectName('slot')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(8)
        self.key = QLabel(key_label(i))
        self.key.setObjectName('kbd')
        self.key.setAlignment(Qt.AlignCenter)
        self.key.setFixedSize(30, 20)
        self.name = QLabel()
        self.count = QLabel()
        self.count.setObjectName('dim')
        self.btn = QToolButton()
        self.btn.setText('Edit')
        self.btn.setObjectName('editslot')
        self.btn.setToolTip('Rename this key')
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(lambda: self.edit.emit(self.i))
        self.btn.hide()
        lay.addWidget(self.key)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.count)
        lay.addWidget(self.btn)
        self._state = None

    def enterEvent(self, e):
        self.btn.show()
        self.count.hide()

    def leaveEvent(self, e):
        self.btn.hide()
        self.count.show()

    def set(self, name, state, count):
        self.name.setText(name or 'Empty')
        self.count.setText(str(count) if count else '')
        st = state if name else 'empty'
        if st != self._state:
            self._state = st
            self.setProperty('state', st)
            for w in (self, self.name, self.key, self.count, self.btn):
                w.style().unpolish(w)
                w.style().polish(w)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.i)


class KeysPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName('sidebar')
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 14)
        lay.setSpacing(2)
        lay.addWidget(section('Tag Preset', 'Edit', win.open_presets))
        sw = QHBoxLayout()
        sw.setSpacing(6)
        self.combo = QComboBox()
        self.combo.activated.connect(self._pick)
        self.combo.setToolTip('Active tag preset — P / Shift+P to switch')
        sw.addWidget(self.combo, 1)
        lay.addLayout(sw)
        hint = QLabel('Press P to switch presets')
        hint.setObjectName('hint')
        lay.addWidget(hint)
        self.find_btn = QPushButton('Find Player…')
        self.find_btn.setObjectName('row')
        self.find_btn.setToolTip('Search the whole roster by name or number and tag with Enter (F)')
        self.find_btn.clicked.connect(win.open_picker)
        self.roster_btn = QPushButton('Edit Roster…')
        self.roster_btn.setObjectName('row')
        self.roster_btn.setToolTip('All players of this preset, with numbers and photos')
        self.roster_btn.clicked.connect(lambda: win.open_roster())
        lay.addSpacing(4)
        lay.addWidget(self.find_btn)
        lay.addWidget(self.roster_btn)
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
        clear = QPushButton('Clear Players')
        clear.setObjectName('plain')
        clear.setToolTip('Remove every player from the selected photos (Backspace)')
        clear.clicked.connect(lambda: win.clear_people())
        lay.addWidget(clear)
        lay.addWidget(section('Metadata Presets', 'Edit', win.open_meta_presets))
        self.meta_box = QVBoxLayout()
        self.meta_box.setSpacing(0)
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
        self.find_btn.setIcon(self.win.icon('search'))
        self.roster_btn.setIcon(self.win.icon('tag'))
        n = len([r for r in cfg.tag.get('roster') or []])
        self.find_btn.setText('Find Player…' + ('' if not n else f'   ({n} in roster)'))
        while self.meta_box.count():
            w = self.meta_box.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for mp in cfg.meta_presets:
            b = QPushButton(mp['name'])
            b.setObjectName('row')
            b.setIcon(self.win.icon('text'))
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


# --------------------------------------------------------------- inspector

class EditBox(QPlainTextEdit):
    committed = Signal()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self.document().isModified():
            self.document().setModified(False)
            self.committed.emit()


def card():
    f = QFrame()
    f.setObjectName('card')
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    return f, lay


class InfoPanel(QScrollArea):
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

        lay.addWidget(section('Info'))
        c, cl = card()
        self.filename = QLabel()
        self.filename.setObjectName('filename')
        self.filename.setWordWrap(True)
        self.file = QLabel()
        self.file.setWordWrap(True)
        self.file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.file.setObjectName('fileinfo')
        cl.addWidget(self.filename)
        cl.addWidget(self.file)
        lay.addWidget(c)

        lay.addWidget(section('Rating & Labels'))
        c, cl = card()
        fl = QHBoxLayout()
        fl.setSpacing(0)
        self.stars = []
        for n in range(1, 6):
            b = QToolButton()
            b.setText('★')
            b.setObjectName('star')
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f'{n} star{"s" if n > 1 else ""}  (Alt+{n})')
            b.clicked.connect(lambda _=False, n=n: win.set_rating(n))
            self.stars.append(b)
            fl.addWidget(b)
        fl.addStretch()
        self.rej = QToolButton()
        self.rej.setObjectName('reject')
        self.rej.setText('Reject')
        self.rej.setCheckable(True)
        self.rej.setToolTip('Reject (X)')
        self.rej.clicked.connect(lambda: win.set_rating(-1))
        fl.addWidget(self.rej)
        cl.addLayout(fl)
        ll = QHBoxLayout()
        ll.setSpacing(8)
        self.labels = {}
        for i, (name, _) in enumerate(core.LABELS):
            b = QToolButton()
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f'{name} label' + (f'  (Alt+{i + 6})' if i < 4 else ''))
            b.clicked.connect(lambda _=False, n=name: win.set_label(n))
            self.labels[name] = b
            ll.addWidget(b)
        ll.addStretch()
        self.tag = QCheckBox('Tagged')
        self.tag.setToolTip('Tag / pick (T)')
        self.tag.clicked.connect(lambda: win.toggle_tagged())
        ll.addWidget(self.tag)
        cl.addLayout(ll)
        lay.addWidget(c)

        lay.addWidget(section('Players'))
        c, cl = card()
        self.people = QListWidget()
        self.people.setObjectName('people')
        self.people.setMaximumHeight(104)
        self.people.setToolTip('Double-click a name to remove it from the selected photos')
        self.people.itemDoubleClicked.connect(lambda it: win.remove_person(it.data(Qt.UserRole)))
        cl.addWidget(self.people)
        self.add_person = QLineEdit()
        self.add_person.setPlaceholderText('Add Player')
        self.add_person.returnPressed.connect(self._add_person)
        cl.addWidget(self.add_person)
        lay.addWidget(c)

        lay.addWidget(section('Caption & IPTC'))
        c, cl = card()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(7)
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
            lab = QLabel(label)
            lab.setObjectName('formlabel')
            form.addRow(lab, w)
        cl.addLayout(form)
        lay.addWidget(c)
        lay.addStretch()
        self.restyle()

    def restyle(self):
        cols = theme.label_colors()
        for name, b in self.labels.items():
            col = cols[name.lower()].name()
            b.setStyleSheet(f'QToolButton{{background:{col};border-radius:9px;min-width:18px;max-width:18px;'
                            f'min-height:18px;max-height:18px;border:2px solid transparent;padding:0}}'
                            f'QToolButton:checked{{border:2px solid {theme.C["label"]}}}')

    def _short(self, path):
        fm = QFontMetrics(self.file.font())
        return fm.elidedText(path, Qt.ElideMiddle, max(120, self.viewport().width() - 60))

    def _add_person(self):
        name = self.add_person.text().strip()
        if name:
            self.win.add_person(name)
        self.add_person.clear()

    def refresh(self, targets):
        n = len(targets)
        it = targets[0] if targets else None
        if not it:
            self.filename.setText('No Selection')
            self.file.setText('')
        elif n > 1:
            self.filename.setText(f'{n} Photos Selected')
            self.file.setText(core.fmt_bytes(sum(t.size for t in targets)))
        else:
            when = datetime.fromtimestamp(it.time).strftime('%d %b %Y  %H:%M:%S') if it.time else ''
            sub = it.exif.get('subsec')
            if sub and when:
                when += f'.{str(sub).strip()[:2]}'
            cam = ' '.join(str(x) for x in (it.exif.get('make', ''), it.exif.get('model', '')) if x)
            sec = theme.C['secondary']
            lines = [
                ' + '.join(f.name for f in it.files[1:]) and f'with {" + ".join(f.name for f in it.files[1:])}',
                f'{it.w} × {it.h}   ·   {core.fmt_bytes(it.size)}' if it.w else core.fmt_bytes(it.size),
                when, cam, str(it.exif.get('lens') or ''), core.fmt_exposure(it.exif),
                f'<span style="color:{sec}">{self._short(it.dir)}</span>']
            if it.save_error:
                lines.append(f'<span style="color:{theme.C["red"]}">Save failed: {it.save_error}</span>')
            self.filename.setText(it.name)
            self.file.setText('<br>'.join(x for x in lines if x))
        metas = [t.meta for t in targets]

        def common(k):
            return metas[0][k] if metas and all(m[k] == metas[0][k] for m in metas) else None

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
            li = QListWidgetItem(p if c == n else f'{p}   ({c} of {n})')
            li.setData(Qt.UserRole, p)
            self.people.addItem(li)
        for key, w in self.fields.items():
            if w.hasFocus():
                continue
            vals = [', '.join(m['keywords']) for m in metas] if key == 'keywords' else [m[key] for m in metas]
            same = bool(vals) and all(v == vals[0] for v in vals)
            text = vals[0] if same else ''
            w.setPlaceholderText('' if same or not vals else 'Multiple Values')
            if isinstance(w, QLineEdit):
                if w.text() != text:
                    w.setText(text)
                w.setModified(False)
            else:
                if w.toPlainText() != text:
                    w.setPlainText(text)
                w.document().setModified(False)
            w.setEnabled(bool(vals))
