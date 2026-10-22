"""Players panel: two teams side by side plus the referees, everyone a clickable photo tile.

Click tags or untags the selection. Teams are split into players and staff; the referees column puts the
officials of the game the photo is from first (matched by date and the two teams shown).
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from . import liiga
from .avatars import draw_avatar
from .config import players
from .picker import _check_badge
from .theme import qc


class TeamGrid(QWidget):
    """Sections of player tiles, painted directly (fast with a few hundred people)."""
    clicked = Signal(str)
    TILE = QSize(80, 94)
    HEAD = 22

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.sections, self.tiles, self.heads = [], [], []
        self.have, self.n = {}, 0
        self.hover = -1
        self.setMouseTracking(True)
        self.name_font = QFont()
        self.name_font.setPixelSize(11)
        self.num_font = QFont()
        self.num_font.setPixelSize(11)
        self.num_font.setWeight(QFont.DemiBold)
        self.head_font = QFont()
        self.head_font.setPixelSize(11)
        self.head_font.setWeight(QFont.DemiBold)
        store.ready.connect(lambda _src: self.update())

    @property
    def entries(self):
        return [e for _, ents in self.sections for e in ents]

    def set_sections(self, sections):
        """[(title, entries)]; empty sections are skipped, a single section gets no header."""
        self.sections = [(t, ents) for t, ents in sections if ents]
        self.hover = -1
        self._layout()
        self.update()

    def set_entries(self, entries):
        self.set_sections([('', entries)])

    def set_state(self, have, n):
        self.have, self.n = have, n
        self.update()

    # ---- layout
    def cols(self):
        return max(1, self.width() // self.TILE.width())

    def _layout(self):
        cols, tw, th = self.cols(), self.TILE.width(), self.TILE.height()
        pad = (self.width() - cols * tw) / 2
        self.tiles, self.heads, y = [], [], 0
        titled = len(self.sections) > 1
        for title, ents in self.sections:
            if titled and title:
                self.heads.append((QRectF(pad + 6, y, self.width() - 2 * pad - 12, self.HEAD), title, len(ents)))
                y += self.HEAD
            for i, e in enumerate(ents):
                self.tiles.append((QRectF(pad + (i % cols) * tw, y + (i // cols) * th, tw, th), e))
            y += -(-len(ents) // cols) * th
        h = int(y) + 4
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)

    def tile_rect(self, i):
        return self.tiles[i][0]

    def index_at(self, pos):
        p = QPointF(pos)
        return next((i for i, (r, _) in enumerate(self.tiles) if r.contains(p)), -1)

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    # ---- mouse
    def mouseMoveEvent(self, e):
        i = self.index_at(e.position().toPoint())
        if i != self.hover:
            self.hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            if i >= 0:
                en = self.tiles[i][1]
                extra = [f'#{en["number"]}'] if en.get('number') else []
                extra += [en['role']] if en.get('role') else []
                self.setToolTip(en['name'] + ('  ·  ' + '  ·  '.join(extra) if extra else ''))
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
                self.clicked.emit(self.tiles[i][1]['name'])

    # ---- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QRectF(e.rect())
        fm_num, fm_name = QFontMetrics(self.num_font), QFontMetrics(self.name_font)
        p.setFont(self.head_font)
        for r, title, n in self.heads:
            if r.intersects(clip):
                p.setPen(qc('secondary'))
                p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, title.upper())
                p.setPen(qc('tertiary'))
                p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, str(n))
        for i, (r, en) in enumerate(self.tiles):
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


def _scroll(widget):
    s = QScrollArea()
    s.setWidget(widget)
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return s


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
        self.scroll = _scroll(self.grid)
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
        self.grid.set_sections([('Players', [e for e in ents if not e.get('role')]),
                                ('Staff', [e for e in ents if e.get('role')])])
        self.count.setText(f'{len(ents)} people' if p else '')
        self.scroll.setVisible(p is not None)


class RefereeColumn(QWidget):
    """The Liiga Referees preset; the officials of the current photo's game come first."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.game_key = None
        self.setFixedWidth(2 * TeamGrid.TILE.width() + 34)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 6, 0)
        lay.setSpacing(4)
        self.title = QLabel('Referees')
        self.title.setObjectName('section')
        self.title.setFixedHeight(26)
        lay.addWidget(self.title)
        self.grid = TeamGrid(panel.win.avatars)
        self.grid.clicked.connect(lambda name: panel.win.toggle_name(name, self.preset()))
        lay.addWidget(_scroll(self.grid), 1)

    def preset(self):
        return next((p for p in self.panel.win.cfg.tag_presets if p.get('liiga') == liiga.REFEREES), None)

    def load(self, game=None):
        p = self.preset()
        ents = players(p) if p else []
        here = set(game['refs']) if game else set()
        first = [e for e in ents if e['name'] in here]
        rest = [e for e in ents if e['name'] not in here]
        self.grid.set_sections([('This game', first),
                                ('Referees', [e for e in rest if e.get('role') != 'Linesman']),
                                ('Linesmen', [e for e in rest if e.get('role') == 'Linesman'])])
        self.game_key = id(game) if game else None


class TeamsPanel(QFrame):
    """Home and away (or any two presets) next to each other under the photos, plus the referees."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.games = {}
        self.setObjectName('teams')
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(0)
        self.ids = ['', '']
        self.cols = [TeamColumn(self, 0), TeamColumn(self, 1)]
        self.refs = RefereeColumn(self)
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 8, 0, 0)
        mid.setSpacing(4)
        swap = QToolButton()
        swap.setText('⇄')
        swap.setToolTip('Swap the two teams')
        swap.setFocusPolicy(Qt.NoFocus)
        swap.clicked.connect(self.swap)
        mid.addWidget(swap)
        mid.addStretch()
        self.ref_btn = QToolButton()
        self.ref_btn.setText('Refs')
        self.ref_btn.setCheckable(True)
        self.ref_btn.setToolTip('Show or hide the referees')
        self.ref_btn.setFocusPolicy(Qt.NoFocus)
        self.ref_btn.clicked.connect(self.toggle_refs)
        lay.addWidget(self.cols[0], 1)
        lay.addLayout(mid)
        lay.addWidget(self.cols[1], 1)
        lay.addWidget(self.refs)
        mid.addWidget(self.ref_btn)
        # filled by reload() once the window is built

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
        self.games = liiga.load_games(cfg)
        for c in self.cols:
            c.load()
        show = bool(cfg.settings.get('teams_refs', True)) and self.refs.preset() is not None
        self.ref_btn.setChecked(show)
        self.ref_btn.setVisible(self.refs.preset() is not None)
        self.refs.setVisible(show)
        self.refs.game_key = -1
        self.refresh()

    def toggle_refs(self):
        self.win.cfg.settings['teams_refs'] = not self.win.cfg.settings.get('teams_refs', True)
        self.reload()

    def swap(self):
        self.ids.reverse()
        if not self.ids[0]:
            self.ids = [self.ids[1], '']
        self.remember()
        for c in self.cols:
            c.load()
        self.refresh()

    def current_game(self, ts):
        it = self.win.current_item() or (ts[0] if ts else None)
        if it is None or not it.time:
            return None
        teams = [(c.preset() or {}).get('liiga') for c in self.cols]
        return liiga.game_on(self.games, datetime.date.fromtimestamp(it.time), teams)

    def refresh(self, targets=None):
        ts = self.win.targets() if targets is None else targets
        have = {}
        for it in ts:
            if it.meta_loaded:
                for name in it.meta['people']:
                    have[name] = have.get(name, 0) + 1
        if self.refs.isVisibleTo(self):
            game = self.current_game(ts)
            if (id(game) if game else None) != self.refs.game_key:
                self.refs.load(game)
        for g in [c.grid for c in self.cols] + [self.refs.grid]:
            g.set_state(have, len(ts))
