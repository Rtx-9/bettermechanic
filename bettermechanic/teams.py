"""Players panel: two teams side by side, every player a clickable photo tile. Click tags or untags the selection."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from .avatars import draw_avatar
from .config import players
from .picker import _check_badge
from .theme import qc


class TeamGrid(QWidget):
    """Flow of player tiles, painted directly (fast with a few hundred players)."""
    clicked = Signal(str)
    TILE = QSize(80, 94)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.entries, self.have, self.n = [], {}, 0
        self.hover = -1
        self.setMouseTracking(True)
        self.name_font = QFont()
        self.name_font.setPixelSize(11)
        self.num_font = QFont()
        self.num_font.setPixelSize(11)
        self.num_font.setWeight(QFont.DemiBold)
        store.ready.connect(lambda _src: self.update())

    def set_entries(self, entries):
        self.entries = entries
        self.hover = -1
        self._fit()
        self.update()

    def set_state(self, have, n):
        self.have, self.n = have, n
        self.update()

    # ---- layout
    def cols(self):
        return max(1, self.width() // self.TILE.width())

    def tile_rect(self, i):
        cols = self.cols()
        pad = (self.width() - cols * self.TILE.width()) / 2
        return QRectF(pad + (i % cols) * self.TILE.width(), (i // cols) * self.TILE.height(),
                      self.TILE.width(), self.TILE.height())

    def index_at(self, pos):
        for i in range(len(self.entries)):
            if self.tile_rect(i).contains(QPointF(pos)):
                return i
        return -1

    def _fit(self):
        rows = -(-len(self.entries) // self.cols()) if self.entries else 0
        h = rows * self.TILE.height() + 4
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)

    # ---- mouse
    def mouseMoveEvent(self, e):
        i = self.index_at(e.position().toPoint())
        if i != self.hover:
            self.hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            if i >= 0:
                en = self.entries[i]
                self.setToolTip(en['name'] + (f'  #{en["number"]}' if en.get('number') else ''))
            else:
                self.setToolTip('')
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            i = self.index_at(e.position().toPoint())
            if i >= 0:
                self.clicked.emit(self.entries[i]['name'])

    # ---- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QRectF(e.rect())
        fm_num, fm_name = QFontMetrics(self.num_font), QFontMetrics(self.name_font)
        for i, en in enumerate(self.entries):
            r = self.tile_rect(i)
            if not r.intersects(clip):
                continue
            have = self.have.get(en['name'], 0)
            full = bool(self.n) and have == self.n
            box = r.adjusted(3, 3, -3, -3)
            if full:
                p.setPen(Qt.NoPen)
                p.setBrush(qc('accent_soft'))
                p.drawRoundedRect(box, 10, 10)
            elif i == self.hover:
                p.setPen(Qt.NoPen)
                p.setBrush(qc('hover'))
                p.drawRoundedRect(box, 10, 10)
            av = QRectF(r.center().x() - 25, r.top() + 8, 50, 50)
            draw_avatar(p, av, en['name'], self.store.get(en.get('image')))
            if full:
                p.setPen(QPen(qc('accent'), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(av.adjusted(-2, -2, 2, 2))
            if en.get('number'):
                t = en['number']
                w = max(22, fm_num.horizontalAdvance(t) + 10)
                pill = QRectF(av.left() - 6, av.bottom() - 15, w, 17)
                p.setPen(QPen(QColor(255, 255, 255), 1.2))
                p.setBrush(QColor(20, 20, 22, 235))
                p.drawRoundedRect(pill, 8.5, 8.5)
                p.setFont(self.num_font)
                p.setPen(QColor(255, 255, 255))
                p.drawText(pill, Qt.AlignCenter, t)
            if full:
                _check_badge(p, QPointF(av.right() - 3, av.bottom() - 5), 8)
            elif have:
                _check_badge(p, QPointF(av.right() - 3, av.bottom() - 5), 8, str(have))
            p.setFont(self.name_font)
            p.setPen(qc('label') if full or i == self.hover else qc('secondary'))
            parts = en['name'].split()
            label = parts[-1] if len(parts) > 1 else en['name']
            p.drawText(QRectF(r.left() + 4, av.bottom() + 4, r.width() - 8, 16), Qt.AlignHCenter | Qt.AlignTop,
                       fm_name.elidedText(label, Qt.ElideRight, int(r.width() - 8)))
        p.end()


class TeamColumn(QWidget):
    def __init__(self, panel, side):
        super().__init__()
        self.panel, self.side = panel, side
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.combo = QComboBox()
        self.combo.setToolTip('Team shown here: any tag preset')
        self.combo.activated.connect(self._pick)
        top.addWidget(self.combo, 1)
        self.count = QLabel()
        self.count.setObjectName('hint')
        top.addWidget(self.count)
        lay.addLayout(top)
        self.grid = TeamGrid(panel.win.avatars)
        self.grid.clicked.connect(lambda name: panel.win.toggle_name(name, self.preset()))
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.grid)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)

    def preset(self):
        pid = self.panel.ids[self.side]
        return next((p for p in self.panel.win.cfg.tag_presets if p['id'] == pid), None)

    def _pick(self, i):
        self.panel.ids[self.side] = self.combo.itemData(i) or ''
        self.panel.remember()
        self.load()
        self.panel.refresh()

    def load(self):
        presets = self.panel.win.cfg.tag_presets
        self.combo.blockSignals(True)
        self.combo.clear()
        if self.side == 1:
            self.combo.addItem('No second team', '')
        for p in presets:
            self.combo.addItem(p['name'] or 'Untitled', p['id'])
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.panel.ids[self.side])))
        self.combo.blockSignals(False)
        p = self.preset()
        ents = players(p) if p else []
        self.grid.set_entries(ents)
        self.count.setText(f'{len(ents)} players' if p else '')
        self.scroll.setVisible(p is not None)


class TeamsPanel(QFrame):
    """Home and away (or any two presets) next to each other under the photos."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName('teams')
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(0)
        self.ids = ['', '']
        self.cols = [TeamColumn(self, 0), TeamColumn(self, 1)]
        swap = QToolButton()
        swap.setText('⇄')
        swap.setToolTip('Swap the two teams')
        swap.setFocusPolicy(Qt.NoFocus)
        swap.clicked.connect(self.swap)
        lay.addWidget(self.cols[0], 1)
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 8, 0, 0)
        mid.addWidget(swap)
        mid.addStretch()
        lay.addLayout(mid)
        lay.addWidget(self.cols[1], 1)       # filled by reload() once the window is built

    def remember(self):
        self.win.cfg.settings['team_panel'] = list(self.ids)

    def reload(self):
        """Presets were added, removed or renamed: keep the chosen teams if they still exist."""
        cfg = self.win.cfg
        ids = [p['id'] for p in cfg.tag_presets]
        saved = cfg.settings.get('team_panel')
        if saved:
            a, b = [x if x in ids else '' for x in (list(saved) + ['', ''])[:2]]
            a, b = (a, b) if a else (b or cfg.tag['id'], '')       # a deleted team: the other one moves up
            self.ids = [a, '' if b == a else b]
        else:                                   # first time: the active preset and the next one
            a = cfg.tag['id']
            self.ids = [a, ids[(ids.index(a) + 1) % len(ids)] if len(ids) > 1 else '']
        for c in self.cols:
            c.load()
        self.refresh()

    def swap(self):
        self.ids.reverse()
        if not self.ids[0]:
            self.ids = [self.ids[1], '']
        self.remember()
        for c in self.cols:
            c.load()
        self.refresh()

    def refresh(self, targets=None):
        ts = self.win.targets() if targets is None else targets
        have = {}
        for it in ts:
            if it.meta_loaded:
                for name in it.meta['people']:
                    have[name] = have.get(name, 0) + 1
        for c in self.cols:
            c.grid.set_state(have, len(ts))
