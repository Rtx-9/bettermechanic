"""Player picker (type / scroll + Enter to tag) and the roster editor."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from . import theme
from .avatars import draw_avatar
from .config import key_label, parse_roster, players
from .theme import qc

ROLE = Qt.UserRole + 7


def _check_badge(p, c: QPointF, r, partial_text=None):
    if partial_text:
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(qc('accent'))
        p.drawEllipse(c, r, r)
        f = QFont()
        f.setPixelSize(int(r * 0.9))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, partial_text)
        return
    p.setPen(QPen(QColor(255, 255, 255), 2))
    p.setBrush(qc('orange'))
    p.drawEllipse(c, r, r)
    p.setPen(QPen(QColor(255, 255, 255), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    s = r / 9
    p.drawPolyline([QPointF(c.x() - 4 * s, c.y()), QPointF(c.x() - 1.2 * s, c.y() + 3 * s),
                    QPointF(c.x() + 4.2 * s, c.y() - 3 * s)])


class CardDelegate(QStyledItemDelegate):
    SIZE = QSize(128, 156)

    def __init__(self, picker):
        super().__init__()
        self.picker = picker
        self.name_font = QFont()
        self.name_font.setWeight(QFont.DemiBold)
        self.small = QFont()
        self.small.setPointSizeF(max(7.5, QFont().pointSizeF() - 1.5))

    def sizeHint(self, opt, idx):
        return self.SIZE

    def paint(self, p, opt, idx):
        e = idx.data(ROLE)
        if not e:
            return
        r = QRectF(opt.rect).adjusted(4, 4, -4, -4)
        sel = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if sel:
            p.setPen(QPen(qc('accent'), 2))
            p.setBrush(qc('accent_soft'))
            p.drawRoundedRect(r, 12, 12)
        elif hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qc('hover'))
            p.drawRoundedRect(r, 12, 12)
        av = QRectF(r.center().x() - 39, r.top() + 12, 78, 78)
        if e.get('add'):
            p.setPen(QPen(qc('accent'), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(av)
            p.setPen(QPen(qc('accent'), 3, Qt.SolidLine, Qt.RoundCap))
            c = av.center()
            p.drawLine(QPointF(c.x() - 12, c.y()), QPointF(c.x() + 12, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - 12), QPointF(c.x(), c.y() + 12))
        else:
            draw_avatar(p, av, e['name'], self.picker.store.get(e.get('image')))
        if e.get('number'):
            p.setFont(self.small)
            fm = QFontMetrics(self.small)
            t = '#' + e['number']
            w = fm.horizontalAdvance(t) + 12
            pill = QRectF(av.left() - 4, av.bottom() - 20, w, 20)
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(QColor(20, 20, 22, 230))
            p.drawRoundedRect(pill, 10, 10)
            p.setPen(QColor(255, 255, 255))
            p.drawText(pill, Qt.AlignCenter, t)
        have, n = self.picker.have.get(e['name'], 0), self.picker.n
        if n and have == n:
            _check_badge(p, QPointF(av.right() - 8, av.bottom() - 8), 11)
        elif have:
            _check_badge(p, QPointF(av.right() - 8, av.bottom() - 8), 11, str(have))
        if e.get('key') is not None:
            p.setFont(self.small)
            fm = QFontMetrics(self.small)
            t = key_label(e['key'])
            kr = QRectF(r.left() + 8, r.top() + 8, fm.horizontalAdvance(t) + 10, 18)
            p.setPen(QPen(qc('field_border'), 1))
            p.setBrush(qc('control'))
            p.drawRoundedRect(kr, 5, 5)
            p.setPen(qc('secondary'))
            p.drawText(kr, Qt.AlignCenter, t)
        p.setFont(self.name_font)
        p.setPen(qc('label'))
        text_r = QRectF(r.left() + 6, av.bottom() + 6, r.width() - 12, 36)
        name = f'Add “{e["name"]}”' if e.get('add') else e['name']
        fm = QFontMetrics(self.name_font)
        lines = fm.elidedText(name, Qt.ElideRight, int(text_r.width() * 2 - 10))
        p.drawText(text_r, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, lines)
        if self.picker.all_teams and e.get('team') and not e.get('add'):
            p.setFont(self.small)
            p.setPen(qc('secondary'))
            p.drawText(QRectF(r.left() + 4, r.bottom() - 18, r.width() - 8, 16), Qt.AlignCenter,
                       QFontMetrics(self.small).elidedText(e['team'], Qt.ElideRight, int(r.width() - 8)))
        p.restore()


class PlayerPicker(QDialog):
    """Spotlight-style chooser: type a name or number, arrows / scroll, Enter tags."""

    def __init__(self, win):
        super().__init__(win, Qt.Dialog | Qt.FramelessWindowHint)
        self.win, self.cfg, self.store = win, win.cfg, win.avatars
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.all_teams = bool(self.cfg.settings.get('picker_all_teams'))
        self.targets = win.targets()
        self.n = len(self.targets)
        self.have = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName('picker')
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName('pickersearch')
        self.search.setPlaceholderText('Type a name or number')
        self.search.addAction(win.icon('search'), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.refilter)
        self.search.installEventFilter(self)
        top.addWidget(self.search, 1)
        seg = QFrame()
        seg.setObjectName('segmented')
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(2)
        self.b_team, self.b_all = QToolButton(), QToolButton()
        for b, text in ((self.b_team, self.cfg.tag['name'] or 'This Preset'), (self.b_all, 'All Presets')):
            b.setText(text)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            sl.addWidget(b)
        self.b_team.clicked.connect(lambda: self.set_scope(False))
        self.b_all.clicked.connect(lambda: self.set_scope(True))
        top.addWidget(seg)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setObjectName('cards')
        self.list.setViewMode(QListView.IconMode)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setUniformItemSizes(True)
        self.list.setGridSize(CardDelegate.SIZE)
        self.list.setSpacing(0)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setItemDelegate(CardDelegate(self))
        self.list.itemDoubleClicked.connect(lambda _: self.activate())
        self.list.itemClicked.connect(lambda _: self.search.setFocus())
        lay.addWidget(self.list, 1)
        self.hint = QLabel()
        self.hint.setObjectName('hint')
        lay.addWidget(self.hint)
        self.store.ready.connect(self._avatar_ready)
        self.set_scope(self.all_teams, refilter=False)
        self.recount()
        self.refilter()
        geo = win.geometry()
        w, h = min(860, geo.width() - 80), min(600, geo.height() - 80)
        self.setGeometry(geo.x() + (geo.width() - w) // 2, geo.y() + max(40, (geo.height() - h) // 3), w, h)
        self.search.setFocus()

    # ---- data
    def entries(self):
        presets = self.cfg.tag_presets if self.all_teams else [self.cfg.tag]
        out, seen = [], set()
        for pr in ([self.cfg.tag] + [x for x in presets if x is not self.cfg.tag]) if self.all_teams else presets:
            for e in players(pr):
                if e['name'] not in seen:
                    seen.add(e['name'])
                    if pr is not self.cfg.tag:
                        e['key'] = None
                    out.append(e)
        return out

    def recount(self):
        self.have = {}
        for it in self.targets:
            for name in it.meta['people']:
                self.have[name] = self.have.get(name, 0) + 1

    def set_scope(self, all_teams, refilter=True):
        self.all_teams = all_teams
        self.b_all.setChecked(all_teams)
        self.b_team.setChecked(not all_teams)
        self.cfg.settings['picker_all_teams'] = all_teams
        if refilter:
            self.refilter()

    def refilter(self):
        q = self.search.text().strip()
        ql = q.lower().lstrip('#')
        ents = self.entries()
        if ql:
            tokens = ql.split()

            def score(e):
                name, num = e['name'].lower(), str(e.get('number') or '')
                if ql.isdigit() and num == ql:
                    return 0
                if all(t in name or (t.isdigit() and num.startswith(t)) for t in tokens):
                    if name.startswith(ql) or any(w.startswith(tokens[0]) for w in name.split()):
                        return 1
                    return 2
                return None
            scored = [(score(e), i, e) for i, e in enumerate(ents)]
            ents = [e for s, i, e in sorted(x for x in scored if x[0] is not None)]
            if not any(e['name'].lower() == q.lower() for e in ents) and not ql.isdigit():
                ents.append({'name': q, 'number': '', 'image': '', 'add': True, 'key': None})
        self.list.clear()
        for e in ents:
            li = QListWidgetItem()
            li.setData(ROLE, e)
            li.setToolTip(e['name'] + (f'  #{e["number"]}' if e.get('number') else ''))
            self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)
        n_real = sum(1 for e in ents if not e.get('add'))
        target = f'{self.n} photo{"s" if self.n != 1 else ""}' if self.n else 'no photo selected'
        self.hint.setText(f'{n_real} players  ·  tagging {target}  ·  Enter tags  ·  Shift+Enter tags and keeps '
                          f'this open  ·  Tab switches presets  ·  Esc closes')

    def _avatar_ready(self, _src):
        self.list.viewport().update()

    # ---- actions
    def activate(self, keep_open=False):
        li = self.list.currentItem()
        if li is None:
            return
        e = li.data(ROLE)
        name = e['name'].strip()
        if not name:
            return
        if e.get('add'):
            self.cfg.tag.setdefault('roster', []).append({'name': name, 'number': '', 'image': ''})
            self.cfg.save()
            self.win.preset_changed(quiet=True)
        self.win.toggle_name(name)
        self.recount()
        if keep_open:
            self.search.selectAll()
            self.refilter() if e.get('add') else self.list.viewport().update()
        else:
            self.accept()

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.KeyPress:
            k = ev.key()
            nav = {Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown}
            if k in nav or (k in (Qt.Key_Left, Qt.Key_Right) and not self.search.text()) \
                    or (k in (Qt.Key_Left, Qt.Key_Right) and ev.modifiers() & Qt.AltModifier):
                QListWidget.keyPressEvent(self.list, ev)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.activate(keep_open=bool(ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)))
                return True
            if k in (Qt.Key_Tab, Qt.Key_Backtab):
                self.set_scope(not self.all_teams)
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(ev)

    def done(self, r):
        try:
            self.store.ready.disconnect(self._avatar_ready)
        except (RuntimeError, TypeError):
            pass
        self.cfg.save()
        super().done(r)


# ------------------------------------------------------------------ roster

KEY_CHOICES = ['—'] + [key_label(i) for i in range(20)]


def avatar_icon(store, name, src, size=36):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw_avatar(p, QRectF(1, 1, size - 2, size - 2), name or '?', store.get(src))
    p.end()
    return QIcon(pm)


class RosterEditor(QDialog):
    COLS = ['', '#', 'Name', 'Photo link or file', 'Key']

    def __init__(self, win, preset):
        super().__init__(win)
        self.win, self.p, self.store = win, preset, win.avatars
        self.setWindowTitle(f'Roster — {preset["name"]}')
        self.resize(min(980, win.width() - 60), min(720, win.height() - 60))
        lay = QVBoxLayout(self)
        intro = QLabel('Everyone you might tag for this preset: as many players as you like. Give your most-tagged '
                       'players a quick key (1–0, Shift + 1–0); find everyone else with the player picker (F).')
        intro.setWordWrap(True)
        intro.setObjectName('dim')
        lay.addWidget(intro)
        bar = QHBoxLayout()
        for text, fn in (('Add Player', self.add_row), ('Remove', self.remove_rows), ('Paste List…', self.paste),
                         ('Choose Photo File…', self.choose_file), ('Reload Photo', self.reload_photo),
                         ('Sort by Number', self.sort_number)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setIconSize(QSize(36, 36))
        self.table.verticalHeader().setDefaultSectionSize(44)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 56)
        self.table.setColumnWidth(4, 90)
        self.table.itemChanged.connect(self._changed)
        lay.addWidget(self.table, 1)
        tip = QLabel('Paste lines like  9, Gustav Forsling, https://example.com/9.jpg   or   #9 Gustav Forsling. '
                     'Photo links can be web addresses or files on this computer.')
        tip.setWordWrap(True)
        tip.setObjectName('hint')
        lay.addWidget(tip)
        foot = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName('dim')
        foot.addWidget(self.count)
        foot.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        done = QPushButton('Done')
        done.setObjectName('primary')
        done.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(done)
        lay.addLayout(foot)
        self._loading = True
        for e in players(preset):
            self._append(e)
        self._loading = False
        self._update_count()
        self.store.ready.connect(self._avatar_ready)

    # ---- rows
    def _append(self, e):
        self._loading, was = True, self._loading
        r = self.table.rowCount()
        self.table.insertRow(r)
        icon = QTableWidgetItem()
        icon.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 0, icon)
        self.table.setItem(r, 1, QTableWidgetItem(str(e.get('number') or '')))
        self.table.setItem(r, 2, QTableWidgetItem(e.get('name', '')))
        self.table.setItem(r, 3, QTableWidgetItem(e.get('image', '')))
        combo = QComboBox()
        combo.addItems(KEY_CHOICES)
        combo.setCurrentIndex(0 if e.get('key') is None else e['key'] + 1)
        combo.currentIndexChanged.connect(lambda i, c=combo: self._key_changed(c, i))
        self.table.setCellWidget(r, 4, combo)
        self._loading = was
        self._refresh_icon(r)
        return r

    def _row_values(self, r):
        get = lambda c: (self.table.item(r, c).text().strip() if self.table.item(r, c) else '')  # noqa: E731
        combo = self.table.cellWidget(r, 4)
        k = combo.currentIndex() - 1 if combo else -1
        return {'number': get(1).lstrip('#'), 'name': get(2), 'image': get(3), 'key': k if k >= 0 else None}

    def _refresh_icon(self, r):
        v = self._row_values(r)
        it = self.table.item(r, 0)
        if it is None:
            return
        it.setIcon(avatar_icon(self.store, v['name'], v['image']))
        err = self.store.error(v['image']) if v['image'] else None
        src_item = self.table.item(r, 3)
        if src_item is not None:
            src_item.setForeground(qc('red') if err else qc('label'))
            src_item.setToolTip(f'Could not load this photo: {err}' if err else v['image'])

    def _avatar_ready(self, src):
        for r in range(self.table.rowCount()):
            if self._row_values(r)['image'] == src.strip():
                self._refresh_icon(r)

    def _changed(self, item):
        if self._loading:
            return
        if item.column() in (2, 3):
            self._refresh_icon(item.row())
        self._update_count()

    def _key_changed(self, combo, i):
        if self._loading or i <= 0:
            return
        for r in range(self.table.rowCount()):
            other = self.table.cellWidget(r, 4)
            if other is not combo and other.currentIndex() == i:
                other.blockSignals(True)
                other.setCurrentIndex(0)
                other.blockSignals(False)

    def _update_count(self):
        n = sum(1 for r in range(self.table.rowCount()) if self._row_values(r)['name'])
        k = sum(1 for r in range(self.table.rowCount()) if self._row_values(r)['key'] is not None)
        self.count.setText(f'{n} players  ·  {k} on quick keys')

    # ---- buttons
    def add_row(self):
        r = self._append({'name': '', 'number': '', 'image': ''})
        self.table.scrollToBottom()
        self.table.setCurrentCell(r, 2)
        self.table.editItem(self.table.item(r, 2))
        self._update_count()

    def remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._update_count()

    def paste(self):
        d = QDialog(self)
        d.setWindowTitle('Paste Players')
        dl = QVBoxLayout(d)
        dl.addWidget(QLabel('One player per line: number, name and an optional photo link, separated by commas or tabs.\n'
                            'You can copy straight from a spreadsheet or a team page.'))
        t = QPlainTextEdit()
        t.setPlaceholderText('9, Gustav Forsling, https://example.com/players/9.jpg\n12\tJohn Smith\n#91 Mark Lee')
        dl.addWidget(t, 1)
        row = QHBoxLayout()
        row.addStretch()
        c = QPushButton('Cancel')
        c.clicked.connect(d.reject)
        ok = QPushButton('Add Players')
        ok.setObjectName('primary')
        ok.clicked.connect(d.accept)
        row.addWidget(c)
        row.addWidget(ok)
        dl.addLayout(row)
        d.resize(620, 440)
        if not d.exec():
            return
        existing = {self._row_values(r)['name'].lower(): r for r in range(self.table.rowCount())}
        added = 0
        for e in parse_roster(t.toPlainText()):
            r = existing.get(e['name'].lower())
            if r is None:
                existing[e['name'].lower()] = self._append(e)
                added += 1
            else:
                self._loading = True
                if e['number']:
                    self.table.item(r, 1).setText(e['number'])
                if e['image']:
                    self.table.item(r, 3).setText(e['image'])
                self._loading = False
                self._refresh_icon(r)
        self._update_count()
        self.win.toast(f'Added {added} player(s)')

    def _current_row(self):
        r = self.table.currentRow()
        return r if r >= 0 else None

    def choose_file(self):
        r = self._current_row()
        if r is None:
            QMessageBox.information(self, 'Choose Photo', 'Select a player first.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a photo', '', 'Images (*.jpg *.jpeg *.png *.webp *.bmp *.gif)')
        if path:
            self.table.item(r, 3).setText(path)

    def reload_photo(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}):
            src = self._row_values(r)['image']
            if src:
                self.store.reload(src)
                self._refresh_icon(r)

    def sort_number(self):
        rows = [self._row_values(r) for r in range(self.table.rowCount())]
        rows.sort(key=lambda v: (not v['number'].isdigit(), int(v['number']) if v['number'].isdigit() else 0,
                                 v['name'].lower()))
        self.table.setRowCount(0)
        for v in rows:
            self._append(v)

    def accept(self):
        roster, slots, seen = [], [''] * 20, set()
        for r in range(self.table.rowCount()):
            v = self._row_values(r)
            if not v['name'] or v['name'] in seen:
                continue
            seen.add(v['name'])
            roster.append({'name': v['name'], 'number': v['number'], 'image': v['image']})
            if v['key'] is not None:
                slots[v['key']] = v['name']
        self.p['roster'], self.p['slots'] = roster, slots
        super().accept()

    def done(self, r):
        try:
            self.store.ready.disconnect(self._avatar_ready)
        except (RuntimeError, TypeError):
            pass
        super().done(r)
