"""Dialogs: tag preset board, metadata presets, ingest/copy, settings, help."""
from __future__ import annotations

import copy
import json
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from . import core
from .config import key_label, new_id, tag_preset


def _hdr(text):
    lab = QLabel(text)
    lab.setObjectName('section')
    return lab


# --------------------------------------------------------- tag preset board

class PresetColumn(QFrame):
    def __init__(self, board, p):
        super().__init__()
        self.board, self.p = board, p
        cfg = board.cfg
        self.setObjectName('pcol')
        active = p['id'] == cfg.tag['id']
        self.setProperty('active', active)
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setSpacing(3)
        top = QHBoxLayout()
        title = QLineEdit(p['name'])
        title.setObjectName('ptitle')
        title.textEdited.connect(lambda t: (p.__setitem__('name', t), board.changed()))
        top.addWidget(title, 1)
        if active:
            a = QLabel('ACTIVE')
            a.setObjectName('pill')
            top.addWidget(a)
        else:
            use = QPushButton('Use')
            use.setObjectName('mini')
            use.clicked.connect(lambda: board.activate(p))
            top.addWidget(use)
        lay.addLayout(top)
        for i in range(20):
            if i in (0, 10):
                g = QLabel('Keys 1 – 0' if i == 0 else 'Shift + 1 – 0')
                g.setObjectName('group')
                lay.addWidget(g)
            row = QHBoxLayout()
            k = QLabel(key_label(i))
            k.setObjectName('kbd')
            k.setFixedWidth(30)
            k.setAlignment(Qt.AlignCenter)
            e = QLineEdit(p['slots'][i])
            e.setPlaceholderText('—')
            e.textEdited.connect(lambda t, i=i: (p['slots'].__setitem__(i, t), board.changed()))
            row.addWidget(k)
            row.addWidget(e, 1)
            lay.addLayout(row)
        lay.addSpacing(6)
        kw = QLineEdit(p.get('keywords', ''))
        kw.setPlaceholderText('Extra keywords, e.g. Ice hockey, Liiga')
        kw.setToolTip('Added to a photo whenever you tag a player from this preset')
        kw.textEdited.connect(lambda t: (p.__setitem__('keywords', t), board.changed()))
        lay.addWidget(QLabel('Keywords added when tagging'))
        lay.addWidget(kw)
        cap = QPlainTextEdit(p.get('caption_tpl', ''))
        cap.setPlaceholderText('{people} of HIFK in action against Tappara at Helsinki Ice Hall, {longdate}.')
        cap.setFixedHeight(64)
        cap.textChanged.connect(lambda: (p.__setitem__('caption_tpl', cap.toPlainText()), board.changed()))
        lay.addWidget(QLabel('Caption template'))
        lay.addWidget(cap)
        auto = QCheckBox('Rewrite caption when players change')
        auto.setChecked(bool(p.get('auto_caption')))
        auto.toggled.connect(lambda v: (p.__setitem__('auto_caption', v), board.changed()))
        lay.addWidget(auto)
        btns = QHBoxLayout()
        n = len(p.get('roster') or [])
        roster = QPushButton(f'Roster ({n} players)…' if n else 'Roster: add players with photos…')
        roster.setToolTip('Unlimited players with numbers and photos, for the player picker (F)')
        roster.clicked.connect(lambda: board.win.open_roster(p) and board.render())
        lay.addWidget(roster)
        for text, fn in (('Paste Keys', lambda: board.paste(p)), ('Duplicate', lambda: board.duplicate(p)),
                         ('Delete', lambda: board.delete(p))):
            b = QPushButton(text)
            b.setObjectName('mini')
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        lay.addStretch()


class PresetBoard(QDialog):
    """All tagging presets side by side, one column per sport/team."""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle('Tag Presets')
        self.resize(min(1280, win.width() - 60), min(860, win.height() - 40))
        lay = QVBoxLayout(self)
        intro = QLabel('Each column is a preset. Keys 1–0 tag the first ten names, Shift + 1–0 the next ten. '
                       'Put everyone else in the roster and find them with the player picker (F). '
                       'Switch presets with P / Shift+P, or click players in the panel under the photos.')
        intro.setWordWrap(True)
        intro.setObjectName('dim')
        lay.addWidget(intro)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        for text, fn in (('Import…', self.import_), ('Export…', self.export)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            foot.addWidget(b)
        self.liiga_btn = QPushButton('Update Liiga Rosters')
        self.liiga_btn.setToolTip('Get every Liiga team’s current players, numbers and photos from liiga.fi. '
                                  'Adds missing teams; your quick keys, keywords and captions stay as they are.')
        self.liiga_btn.clicked.connect(self.update_liiga)
        foot.addWidget(self.liiga_btn)
        self.liiga_msg = QLabel()
        self.liiga_msg.setObjectName('dim')
        foot.addWidget(self.liiga_msg)
        foot.addStretch()
        close = QPushButton('Done')
        close.setObjectName('primary')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        lay.addLayout(foot)
        self.render()

    def render(self):
        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        for p in self.cfg.tag_presets:
            row.addWidget(PresetColumn(self, p), 0, Qt.AlignTop)
        add = QPushButton('+  New Preset')
        add.setObjectName('addcol')
        add.setFixedSize(180, 120)
        add.clicked.connect(self.add)
        row.addWidget(add, 0, Qt.AlignTop)
        self.scroll.setWidget(inner)

    def changed(self):
        self.cfg.save()
        self.win.preset_changed(quiet=True)

    def update_liiga(self):
        self.liiga_btn.setEnabled(False)
        self.liiga_msg.setText('Getting rosters from liiga.fi…')
        self.win.update_liiga(done=self.liiga_done)

    def liiga_done(self, msg):
        self.liiga_btn.setEnabled(True)
        self.liiga_msg.setText(msg)

    def activate(self, p):
        self.cfg.active_tag = p['id']
        self.changed()
        self.render()

    def add(self):
        p = tag_preset('New preset')
        self.cfg.tag_presets.append(p)
        self.changed()
        self.render()
        self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum())

    def duplicate(self, p):
        q = copy.deepcopy(p)
        q['id'], q['name'], q['liiga'] = new_id(), p['name'] + ' copy', ''
        self.cfg.tag_presets.insert(self.cfg.tag_presets.index(p) + 1, q)
        self.changed()
        self.render()

    def delete(self, p):
        if len(self.cfg.tag_presets) < 2:
            QMessageBox.information(self, 'Tag presets', 'Keep at least one preset.')
            return
        if QMessageBox.question(self, 'Delete preset', f'Delete the preset “{p["name"]}”?') != QMessageBox.Yes:
            return
        self.cfg.tag_presets.remove(p)
        if self.cfg.active_tag == p['id']:
            self.cfg.active_tag = self.cfg.tag_presets[0]['id']
        self.changed()
        self.render()

    def paste(self, p):
        d = QDialog(self)
        d.setWindowTitle(f'Paste roster into “{p["name"]}”')
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel('One name per line (up to 20). Line 1 → key 1, line 11 → Shift+1.'))
        t = QPlainTextEdit('\n'.join(s for s in p['slots']).rstrip())
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setObjectName('primary')
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.resize(380, 460)
        if d.exec():
            lines = [ln.strip() for ln in t.toPlainText().splitlines()]
            p['slots'] = (lines + [''] * 20)[:20]
            self.changed()
            self.render()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export presets', 'bettermechanic-presets.json', 'JSON (*.json)')
        if path:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(self.cfg.export_presets(), fh, indent=2, ensure_ascii=False)

    def import_(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import presets', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as fh:
                n = self.cfg.import_presets(json.load(fh))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, 'Import failed', str(e))
            return
        self.changed()
        self.render()
        self.win.toast(f'Imported {n} preset(s)')


# --------------------------------------------------------- metadata presets

class MetaPresets(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle('Metadata Presets')
        self.resize(900, 680)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName('presetlist')
        self.list.currentRowChanged.connect(self.show_preset)
        left.addWidget(self.list, 1)
        for text, fn in (('New', self.new), ('Duplicate', self.dup), ('Delete', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            left.addWidget(b)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.textEdited.connect(self._rename)
        form.addRow('Preset name', self.name)
        self.fields = {}
        for key, label, multi in core.META_FORM:
            w = QPlainTextEdit() if multi else QLineEdit()
            if multi:
                w.setFixedHeight(60)
                w.textChanged.connect(lambda k=key, w=w: self._set(k, w.toPlainText()))
            else:
                w.textEdited.connect(lambda t, k=key: self._set(k, t))
            if key == 'keywords':
                w.setPlaceholderText('comma separated — added to existing keywords')
            self.fields[key] = w
            form.addRow(label, w)
        right.addLayout(form)
        help_ = QLabel('Variables: ' + '   '.join(v for v, _ in core.TEMPLATE_HELP))
        help_.setWordWrap(True)
        help_.setObjectName('dim')
        help_.setToolTip('\n'.join(f'{v}  —  {d}' for v, d in core.TEMPLATE_HELP))
        right.addWidget(help_)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem('Replace fields filled in the preset', 'replace')
        self.mode.addItem('Only fill empty fields', 'fill')
        row.addWidget(self.mode, 1)
        cap = QPushButton('Fill from Selected Photo')
        cap.clicked.connect(self.capture)
        row.addWidget(cap)
        ap = QPushButton('Apply to Selection')
        ap.setObjectName('primary')
        ap.clicked.connect(self.apply)
        row.addWidget(ap)
        right.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        right.addWidget(close)
        lay.addLayout(right, 3)
        self._loading = False
        self.reload()

    def reload(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.cfg.meta_presets:
            self.list.addItem(p['name'])
        self.list.blockSignals(False)
        if self.cfg.meta_presets:
            self.list.setCurrentRow(min(select, len(self.cfg.meta_presets) - 1))
        else:
            self.show_preset(-1)

    @property
    def cur(self):
        i = self.list.currentRow()
        return self.cfg.meta_presets[i] if 0 <= i < len(self.cfg.meta_presets) else None

    def show_preset(self, _):
        p = self.cur
        self._loading = True
        self.name.setText(p['name'] if p else '')
        for k, w in self.fields.items():
            v = (p or {}).get('fields', {}).get(k, '')
            w.setPlainText(v) if isinstance(w, QPlainTextEdit) else w.setText(v)
            w.setEnabled(bool(p))
        self._loading = False

    def _set(self, key, val):
        if self._loading or not self.cur:
            return
        self.cur['fields'][key] = val
        self._save()

    def _rename(self, t):
        if self.cur:
            self.cur['name'] = t
            self.list.currentItem().setText(t)
            self._save()

    def _save(self):
        self.cfg.save()
        self.win.keys.refresh_presets()

    def new(self):
        self.cfg.meta_presets.append({'id': new_id(), 'name': 'New preset', 'fields': {}})
        self._save()
        self.reload(len(self.cfg.meta_presets) - 1)

    def dup(self):
        if self.cur:
            q = copy.deepcopy(self.cur)
            q['id'], q['name'] = new_id(), q['name'] + ' copy'
            self.cfg.meta_presets.append(q)
            self._save()
            self.reload(len(self.cfg.meta_presets) - 1)

    def delete(self):
        p = self.cur
        if p and QMessageBox.question(self, 'Delete', f'Delete “{p["name"]}”?') == QMessageBox.Yes:
            self.cfg.meta_presets.remove(p)
            self._save()
            self.reload()

    def capture(self):
        p, ts = self.cur, self.win.targets()
        if not p or not ts:
            return
        it = self.win.loaded(ts)[0]
        for k, _, _ in core.META_FORM:
            v = ', '.join(it.meta['keywords']) if k == 'keywords' else it.meta.get(k, '')
            if v:
                p['fields'][k] = v
        self._save()
        self.show_preset(0)

    def apply(self):
        if self.cur:
            self.win.apply_meta_preset(self.cur['id'], self.mode.currentData())


# ----------------------------------------------------------- ingest / copy

WHICH = [('not_rejected', 'All except rejected'), ('all', 'All photos'), ('tagged', 'Tagged only'),
         ('rated', 'Rated 1★ or more'), ('people', 'Photos with players tagged'), ('selected', 'Selected photos')]


class CopyDialog(QDialog):
    def __init__(self, win, ingest=False, which=None):
        super().__init__(win)
        self.win, self.cfg, self.ingest = win, win.cfg, ingest
        o = self.o = dict(win.cfg.copy)
        if which:
            o['which'] = which
        self.job = None
        self.setWindowTitle('Ingest' if ingest else 'Copy & Export')
        self.resize(720, 640)
        outer = QVBoxLayout(self)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        page = QWidget()
        lay = QVBoxLayout(page)
        items = win.all_items()
        lay.addWidget(QLabel(f'<b>From:</b> {win.root_name}  —  {len(items)} photos in view'))
        g = QGridLayout()
        g.setColumnStretch(1, 1)
        r = 0

        def row(label, w, extra=None):
            nonlocal r
            g.addWidget(QLabel(label), r, 0, Qt.AlignRight)
            g.addWidget(w, r, 1)
            if extra:
                g.addWidget(extra, r, 2)
            r += 1

        self.which = QComboBox()
        for k, t in WHICH:
            self.which.addItem(t, k)
        self.which.setCurrentIndex(max(0, self.which.findData(o['which'])))
        row('Copy', self.which)
        self.dest = QLineEdit(o['dest'])
        b = QPushButton('Choose…')
        b.clicked.connect(lambda: self._pick(self.dest))
        row('Destination', self.dest, b)
        self.use_backup = QCheckBox('Also copy to a backup drive')
        self.use_backup.setChecked(bool(o['use_backup']))
        row('', self.use_backup)
        self.backup = QLineEdit(o['backup'])
        b2 = QPushButton('Choose…')
        b2.clicked.connect(lambda: self._pick(self.backup))
        row('Backup', self.backup, b2)
        self.sub = QLineEdit(o['sub'])
        row('Subfolder', self.sub)
        self.rename = QLineEdit(o['rename'])
        row('File name', self.rename)
        self.seq = QSpinBox()
        self.seq.setRange(0, 9_999_999)
        self.seq.setValue(int(self.cfg.settings.get('seq', 1)))
        row('Next {seq}', self.seq)
        self.example = QLabel()
        self.example.setObjectName('dim')
        row('Example', self.example)
        self.fmt = QComboBox()
        self.fmt.addItem('Original files (RAW + JPEG as shot)', 'original')
        self.fmt.addItem('JPEG, resized (for sending)', 'jpeg')
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(o['fmt'])))
        row('Format', self.fmt)
        jrow = QWidget()
        jl = QHBoxLayout(jrow)
        jl.setContentsMargins(0, 0, 0, 0)
        self.long_edge = QSpinBox()
        self.long_edge.setRange(0, 20000)
        self.long_edge.setSuffix(' px long edge')
        self.long_edge.setSpecialValueText('full size')
        self.long_edge.setValue(int(o['long_edge']))
        self.quality = QSpinBox()
        self.quality.setRange(30, 100)
        self.quality.setPrefix('quality ')
        self.quality.setValue(int(o['quality']))
        jl.addWidget(self.long_edge)
        jl.addWidget(self.quality)
        row('JPEG', jrow)
        self.preset = QComboBox()
        self.preset.addItem('None', '')
        for p in self.cfg.meta_presets:
            self.preset.addItem(p['name'], p['id'])
        self.preset.setCurrentIndex(max(0, self.preset.findData(o['meta_preset'])))
        self.pmode = QComboBox()
        self.pmode.addItem('replace', 'replace')
        self.pmode.addItem('fill empty', 'fill')
        self.pmode.setCurrentIndex(max(0, self.pmode.findData(o['preset_mode'])))
        row('Metadata preset', self.preset, self.pmode)
        self.write_meta = QCheckBox('Write tags, players, ratings and captions into the copies')
        self.write_meta.setChecked(bool(o['write_meta']))
        row('', self.write_meta)
        self.exists = QComboBox()
        for k, t in (('skip', 'Skip it'), ('rename', 'Keep both (add -1)'), ('overwrite', 'Overwrite')):
            self.exists.addItem(t, k)
        self.exists.setCurrentIndex(max(0, self.exists.findData(o['exists'])))
        row('If file exists', self.exists)
        self.skip_ingested = QCheckBox('Skip photos that were ingested before (ingest history)')
        self.skip_ingested.setChecked(bool(o.get('skip_ingested', True)))
        if ingest:
            row('', self.skip_ingested)
        self.open_after = QCheckBox('Open the destination when done')
        self.open_after.setChecked(bool(o['open_after']))
        row('', self.open_after)
        lay.addLayout(g)
        vars_ = QLabel('Variables: ' + '   '.join(v for v, _ in core.TEMPLATE_HELP))
        vars_.setWordWrap(True)
        vars_.setObjectName('dim')
        vars_.setToolTip('\n'.join(f'{v}  —  {d}' for v, d in core.TEMPLATE_HELP))
        lay.addWidget(vars_)
        lay.addStretch()
        bb = QHBoxLayout()
        bb.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        self.go = QPushButton('Start Ingest' if ingest else 'Start Copy')
        self.go.setObjectName('primary')
        self.go.setDefault(True)
        self.go.clicked.connect(self.start)
        bb.addWidget(cancel)
        bb.addWidget(self.go)
        lay.addLayout(bb)
        self.stack.addWidget(page)

        prog = QWidget()
        pl = QVBoxLayout(prog)
        self.phase = QLabel('Starting…')
        self.phase.setObjectName('big')
        self.bar = QProgressBar()
        self.detail = QLabel()
        self.detail.setObjectName('dim')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.hide()
        pl.addWidget(self.phase)
        pl.addWidget(self.bar)
        pl.addWidget(self.detail)
        pl.addWidget(self.log, 1)
        pl.addStretch()
        pb = QHBoxLayout()
        pb.addStretch()
        self.stop = QPushButton('Cancel')
        self.stop.clicked.connect(self.cancel)
        self.open_btn = QPushButton('Open Destination')
        self.open_btn.hide()
        self.done_btn = QPushButton('Close')
        self.done_btn.hide()
        self.done_btn.clicked.connect(self.accept)
        pb.addWidget(self.stop)
        pb.addWidget(self.open_btn)
        pb.addWidget(self.done_btn)
        pl.addLayout(pb)
        self.stack.addWidget(prog)

        for w in (self.sub, self.rename):
            w.textChanged.connect(self.update_example)
        self.seq.valueChanged.connect(self.update_example)
        self.fmt.currentIndexChanged.connect(self.update_example)
        self.update_example()
        win.bus.copy_progress.connect(self.on_progress)
        win.bus.copy_done.connect(self.on_done)

    def _pick(self, edit):
        d = QFileDialog.getExistingDirectory(self, 'Choose folder', edit.text())
        if d:
            edit.setText(d)

    def update_example(self):
        its = self.win.all_items()
        if not its:
            self.example.setText('')
            return
        it = its[0]
        s = self.cfg.settings
        sub = core.sanitize_path(core.expand(self.sub.text(), it, None, self.seq.value(), s.get('seq_digits', 4)))
        name = core.sanitize(core.expand(self.rename.text(), it, None, self.seq.value(), s.get('seq_digits', 4))) or it.base
        ext = 'jpg' if self.fmt.currentData() == 'jpeg' else it.primary.ext
        self.example.setText(f'{sub + "/" if sub else ""}{name}.{ext}')

    def collect(self):
        return {'dest': self.dest.text().strip(), 'backup': self.backup.text().strip(),
                'use_backup': self.use_backup.isChecked(), 'sub': self.sub.text(), 'rename': self.rename.text(),
                'which': self.which.currentData(), 'fmt': self.fmt.currentData(),
                'long_edge': self.long_edge.value(), 'quality': self.quality.value(),
                'meta_preset': self.preset.currentData(), 'preset_mode': self.pmode.currentData(),
                'exists': self.exists.currentData(), 'write_meta': self.write_meta.isChecked(),
                'open_after': self.open_after.isChecked(), 'ingest': self.ingest,
                'skip_ingested': self.skip_ingested.isChecked()}

    def start(self):
        import os
        o = self.collect()
        if not o['dest'] or not os.path.isdir(o['dest']):
            QMessageBox.warning(self, 'Destination', 'Choose an existing destination folder.')
            return
        if o['use_backup'] and o['backup'] and not os.path.isdir(o['backup']):
            QMessageBox.warning(self, 'Backup', 'The backup folder does not exist.')
            return
        self.cfg.copy.update(o)
        self.cfg.settings['seq'] = self.seq.value()
        self.cfg.save()
        self.o = o
        self.stack.setCurrentIndex(1)
        self.t0 = time.time()
        self.job = self.win.start_copy(o)

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.phase.setText('Cancelling…')

    def on_progress(self, d):
        if d.get('phase') != 'Copying':
            self.phase.setText(d.get('phase', ''))
            self.bar.setRange(0, 0)
            return
        i, n = d['i'], d['n']
        self.bar.setRange(0, max(1, n))
        self.bar.setValue(i)
        self.phase.setText(f'Copying {i + 1} of {n}')
        el = max(0.001, time.time() - d['t0'])
        mbs = d['bytes'] / el / 1e6
        txt = f'{d["name"]}    {mbs:.0f} MB/s'
        if d['total'] and d['bytes']:
            rem = (d['total'] - d['bytes']) / max(1, d['bytes'] / el)
            txt += f'    about {int(rem // 60)}:{int(rem % 60):02d} left'
        self.detail.setText(txt)

    def on_done(self, res):
        self.job = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        head = 'Cancelled' if res.get('cancelled') else 'Done'
        self.phase.setText(f'{head}: {res["copied"]} copied, {res["skipped"]} skipped, {res["failed"]} failed')
        self.detail.setText(f'Took {time.time() - self.t0:.0f} s')
        if res['errors']:
            self.log.show()
            self.log.setPlainText('\n'.join(res['errors']))
        self.cfg.settings['seq'] = res.get('seq', self.cfg.settings.get('seq', 1))
        self.cfg.save()
        self.stop.hide()
        self.done_btn.show()
        dirs = res.get('dirs') or []
        if dirs:
            target = dirs[0] if len(dirs) == 1 else self.o['dest']
            self.open_btn.show()
            self.open_btn.clicked.connect(lambda: (self.accept(), self.win.open_folder(target, recursive=len(dirs) > 1)))
            if self.o.get('open_after') and not res.get('cancelled') and not res['failed']:
                self.accept()
                self.win.open_folder(target, recursive=len(dirs) > 1)

    def reject(self):
        if self.job:
            self.cancel()
            return
        super().reject()

    def done(self, r):
        try:
            self.win.bus.copy_progress.disconnect(self.on_progress)
            self.win.bus.copy_done.disconnect(self.on_done)
        except (RuntimeError, TypeError):
            pass
        super().done(r)


# ----------------------------------------------------------------- settings

class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, s = win, win.cfg.settings
        self.setWindowTitle('Settings')
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.w = {}

        def chk(key, text):
            c = QCheckBox(text)
            c.setChecked(bool(s.get(key)))
            self.w[key] = c
            f.addRow('', c)

        f.addRow(_hdr('Appearance'))
        self.appearance = QComboBox()
        for k, t in (('system', 'Match System'), ('light', 'Light'), ('dark', 'Dark')):
            self.appearance.addItem(t, k)
        self.appearance.setCurrentIndex(max(0, self.appearance.findData(s.get('appearance', 'system'))))
        f.addRow('Appearance', self.appearance)
        f.addRow(_hdr('Browsing'))
        chk('thumb_hq', 'Sharp thumbnails (decode a larger preview after the fast embedded thumbnail)')
        chk('group_pairs', 'Show RAW + JPEG pairs as one photo')
        chk('recursive', 'Include subfolders when opening a folder')
        chk('ingest_recursive', 'Include subfolders when ingesting (memory cards use DCIM/…)')
        chk('auto_advance', 'Move to the next photo after T / X / stars')
        chk('liiga_auto_update', 'Keep Liiga rosters up to date (checks liiga.fi once a day)')
        f.addRow(_hdr('Metadata'))
        chk('auto_save', 'Save metadata automatically')
        self.jpeg_mode = QComboBox()
        self.jpeg_mode.addItem('Write into the JPEG file (like Photo Mechanic)', 'embed')
        self.jpeg_mode.addItem('Write an .xmp sidecar next to the JPEG', 'sidecar')
        self.jpeg_mode.setCurrentIndex(max(0, self.jpeg_mode.findData(s.get('jpeg_mode'))))
        f.addRow('JPEG files', self.jpeg_mode)
        f.addRow('RAW files', QLabel('Always an .xmp sidecar (Lightroom / Capture One compatible)'))
        chk('write_iim', 'Also write legacy IPTC-IIM into JPEGs (newsroom systems need it)')
        chk('people_to_keywords', 'Add tagged players to keywords as well as “Person shown”')
        from .metadata import MARK_CHOICES
        self.lr_mark = QComboBox()
        for key, text in MARK_CHOICES:
            self.lr_mark.addItem(text, key)
        self.lr_mark.setCurrentIndex(max(0, self.lr_mark.findData(s.get('lr_tag_mark', 'none'))))
        self.lr_mark.setToolTip('Lightroom doesn\'t read the Tagged flag. Tagged photos can also get a label, rating '
                                'or keyword that Lightroom shows after import. Your own labels and higher ratings '
                                'are never replaced, and untagging removes the mark.')
        f.addRow('Tagged in Lightroom', self.lr_mark)
        f.addRow(_hdr('Copy'))
        self.digits = QSpinBox()
        self.digits.setRange(1, 8)
        self.digits.setValue(int(s.get('seq_digits', 4)))
        f.addRow('{seq} digits', self.digits)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setObjectName('primary')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        s = self.win.cfg.settings
        old_pairs = s.get('group_pairs')
        old_look = s.get('appearance', 'system')
        s['appearance'] = self.appearance.currentData()
        for k, c in self.w.items():
            s[k] = c.isChecked()
        s['jpeg_mode'] = self.jpeg_mode.currentData()
        s['lr_tag_mark'] = self.lr_mark.currentData()
        s['seq_digits'] = self.digits.value()
        self.win.cfg.save()
        super().accept()
        if old_pairs != s['group_pairs'] and self.win.root:
            self.win.toast('Reopen the folder to apply RAW+JPEG grouping')
        self.win.loader.wake()
        if s['appearance'] != old_look:
            self.win.apply_appearance()


HELP = """
<h2>BetterMechanic shortcuts</h2>
<table cellspacing=6>
<tr><td><b>1 … 0</b></td><td>Toggle the player on keys 1–10 of the active tag preset</td></tr>
<tr><td><b>Shift + 1 … 0</b></td><td>Toggle players 11–20</td></tr>
<tr><td><b>P / Shift+P</b></td><td>Next / previous tag preset (e.g. Hockey ↔ Soccer)</td></tr>
<tr><td><b>F</b> (or <b>/</b>)</td><td>Player picker: type a name or number, arrows or scroll to choose, <b>Enter</b> tags
(<b>Shift+Enter</b> tags and keeps it open, <b>Tab</b> searches all presets)</td></tr>
<tr><td><b>B</b></td><td>Show or hide the players panel: two teams side by side, click a player to tag or untag
the selected photos</td></tr>
<tr><td><b>Backspace</b></td><td>Remove all players from the selected photos</td></tr>
<tr><td><b>T</b></td><td>Tag / untag (pick)</td></tr>
<tr><td><b>X</b></td><td>Reject / unreject</td></tr>
<tr><td><b>Alt + 1 … 5</b></td><td>Star rating, <b>Alt + 0</b> clears it</td></tr>
<tr><td><b>Alt + 6 7 8 9</b></td><td>Red, yellow, green, blue label</td></tr>
<tr><td><b>Enter / Space</b></td><td>Open the large preview (and back)</td></tr>
<tr><td><b>Z</b> or click</td><td>Zoom to 100% in the preview; drag to pan</td></tr>
<tr><td><b>← → ↑ ↓</b></td><td>Move; Shift extends the selection in the contact sheet</td></tr>
<tr><td><b>Ctrl + A / Ctrl + D</b></td><td>Select all / none</td></tr>
<tr><td><b>Ctrl + O</b></td><td>Open folder</td></tr>
<tr><td><b>Ctrl + I</b></td><td>Ingest from a memory card</td></tr>
<tr><td><b>Ctrl + E</b></td><td>Copy &amp; export</td></tr>
<tr><td><b>Ctrl + S</b></td><td>Save metadata now</td></tr>
<tr><td><b>Ctrl + F</b></td><td>Search (names, players, keywords, captions)</td></tr>
<tr><td><b>F1 / ?</b></td><td>This help</td></tr>
</table>
<p>Keys act on every selected photo in the contact sheet, or on the photo shown in the preview.
Pressing a player key again removes that player.</p>
<h3>Ingest workflow</h3>
<p>Ingest opens the card read-only. Cull and tag right there (nothing is written to the card), then press
<b>Start ingest</b> to copy only what you want, renamed, with the tags, players and metadata preset written into the copies.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle('Keyboard Shortcuts')
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        t = QTextBrowser()
        t.setHtml(HELP)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
