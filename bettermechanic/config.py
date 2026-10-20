"""Persistent settings and presets (JSON in the user's app-data folder)."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

SLOTS = 20


def app_dir() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'BetterMechanic'


def new_id():
    return uuid.uuid4().hex[:10]


def tag_preset(name, names=()):
    slots = [''] * SLOTS
    for i, n in enumerate(list(names)[:SLOTS]):
        slots[i] = n
    return {'id': new_id(), 'name': name, 'slots': slots, 'caption_tpl': '', 'auto_caption': False, 'keywords': ''}


DEFAULT_SETTINGS = {
    'appearance': 'system',    # system | light | dark
    'thumb_size': 190,
    'thumb_hq': True,
    'group_pairs': True,
    'recursive': False,
    'ingest_recursive': True,
    'auto_save': True,
    'jpeg_mode': 'embed',          # embed | sidecar
    'write_iim': True,
    'people_to_keywords': True,
    'auto_advance': False,
    'seq': 1,
    'seq_digits': 4,
    'date_locale': 'en',
}

DEFAULT_COPY = {
    'dest': '',
    'backup': '',
    'use_backup': False,
    'sub': '{yyyy}-{mm}-{dd}',
    'rename': '{orig}',
    'which': 'not_rejected',
    'fmt': 'original',             # original | jpeg
    'long_edge': 2500,
    'quality': 90,
    'meta_preset': '',
    'preset_mode': 'replace',      # replace | fill
    'exists': 'skip',              # skip | rename | overwrite
    'write_meta': True,
    'open_after': True,
    'skip_ingested': True,
}


def default_meta_presets():
    return [{
        'id': new_id(), 'name': 'Game day',
        'fields': {'caption': '{people} in action during {event}, {city}, {longdate}.',
                   'copyright': '© {yyyy}', 'event': '', 'city': '', 'country': '', 'byline': '',
                   'credit': '', 'keywords': ''},
    }]


class Config:
    def __init__(self, path: Path | None = None):
        env = os.environ.get('BETTERMECHANIC_CONFIG')
        self.path = Path(path) if path else Path(env) if env else app_dir() / 'config.json'
        self.tag_presets = [tag_preset('Hockey', ['Gustav', 'John', 'Mark']),
                            tag_preset('Soccer', ['Stan', 'Joe', 'Shawn'])]
        self.active_tag = self.tag_presets[0]['id']
        self.meta_presets = default_meta_presets()
        self.settings = dict(DEFAULT_SETTINGS)
        self.copy = dict(DEFAULT_COPY)
        self.recent = []            # [{'path': str, 'ingest': bool}]
        self.window = {}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text('utf-8'))
        except (OSError, ValueError):
            return
        if data.get('tag_presets'):
            self.tag_presets = [self._norm_tag(p) for p in data['tag_presets']]
        self.active_tag = data.get('active_tag') or self.tag_presets[0]['id']
        if isinstance(data.get('meta_presets'), list):
            self.meta_presets = data['meta_presets']
        self.settings.update(data.get('settings') or {})
        self.copy.update(data.get('copy') or {})
        self.recent = data.get('recent') or []
        self.window = data.get('window') or {}

    @staticmethod
    def _norm_tag(p):
        q = tag_preset(p.get('name') or 'Preset')
        q.update({k: v for k, v in p.items() if k in q})
        q['slots'] = (list(q['slots']) + [''] * SLOTS)[:SLOTS]
        return q

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {'tag_presets': self.tag_presets, 'active_tag': self.active_tag,
                'meta_presets': self.meta_presets, 'settings': self.settings,
                'copy': self.copy, 'recent': self.recent[:10], 'window': self.window}
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), 'utf-8')
        os.replace(tmp, self.path)

    # -- helpers
    @property
    def tag(self):
        for p in self.tag_presets:
            if p['id'] == self.active_tag:
                return p
        return self.tag_presets[0]

    def cycle_tag(self, step):
        ids = [p['id'] for p in self.tag_presets]
        i = ids.index(self.tag['id'])
        self.active_tag = ids[(i + step) % len(ids)]
        return self.tag

    def meta_preset(self, pid):
        return next((p for p in self.meta_presets if p['id'] == pid), None)

    def add_recent(self, path, ingest=False):
        path = str(path)
        self.recent = [{'path': path, 'ingest': ingest}] + [r for r in self.recent if r.get('path') != path]
        self.recent = self.recent[:10]

    def export_presets(self):
        return {'tag_presets': self.tag_presets, 'meta_presets': self.meta_presets}

    def import_presets(self, data):
        n = 0
        for p in data.get('tag_presets') or []:
            q = self._norm_tag(p)
            q['id'] = new_id()
            self.tag_presets.append(q)
            n += 1
        for p in data.get('meta_presets') or []:
            if isinstance(p, dict) and 'fields' in p:
                self.meta_presets.append({'id': new_id(), 'name': p.get('name', 'Imported'), 'fields': dict(p['fields'])})
                n += 1
        return n


def key_label(i):
    d = str((i % 10 + 1) % 10)
    return ('⇧' + d) if i >= 10 else d
