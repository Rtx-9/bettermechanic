"""Photo items, folder scanning, metadata loading/saving and filename templates."""
from __future__ import annotations

import itertools
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime

from . import metadata as M
from . import previews

RAW_EXT = set('cr2 cr3 crw nef nrw arw srf sr2 dng raf orf rw2 pef srw x3f 3fr iiq erf kdc mef mos mrw rwl'.split())
JPEG_EXT = {'jpg', 'jpeg', 'jpe'}
RASTER_EXT = {'png', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic', 'heif'}
LABELS = [('Red', '#e5484d'), ('Yellow', '#f5c400'), ('Green', '#30a46c'), ('Blue', '#3e86f5'), ('Purple', '#8e4ec6')]

_ids = itertools.count(1)


@dataclass
class FileRef:
    path: str
    name: str
    base: str
    ext: str          # as written on disk (case kept)
    kind: str         # raw | jpeg | raster
    size: int = 0
    mtime: float = 0.0


@dataclass
class Item:
    files: list
    sidecar: str | None = None
    id: int = field(default_factory=lambda: next(_ids))
    meta: dict = field(default_factory=M.blank)
    meta_loaded: bool = False
    analysis: object = None
    exif: dict = field(default_factory=dict)
    orient: int = 1
    w: int = 0
    h: int = 0
    time: float = 0.0
    tstate: int = 0           # 0 none, 1 fast thumb, 2 sharp thumb, -1 no preview
    tbusy: bool = False
    tq: int = 0
    thumb: bytes | None = None
    edited: bool = False
    save_error: str = ''
    overlay: dict | None = None    # culling saved by the app for read-only cards
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.primary = self.files[0]
        self.pv = next((f for f in self.files if f.kind == 'jpeg'), self.files[0])
        self.time = self.primary.mtime

    @property
    def name(self):
        return self.primary.name

    @property
    def base(self):
        return self.primary.base

    @property
    def dir(self):
        return os.path.dirname(self.primary.path)

    @property
    def is_pair(self):
        return len(self.files) > 1

    @property
    def size(self):
        return sum(f.size for f in self.files)


def kind_of(ext):
    e = ext.lower()
    return 'jpeg' if e in JPEG_EXT else 'raw' if e in RAW_EXT else 'raster' if e in RASTER_EXT else None


def scan_folder(root, recursive=False, progress=None, cancel=None):
    """Return (FileRefs, {dir/base(lower): sidecar path})."""
    files, sidecars = [], {}
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if cancel and cancel():
                return files, sidecars
            name = e.name
            if name.startswith('.') or name.startswith('$'):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if recursive and depth < 8 and name.lower() != 'system volume information':
                        stack.append((e.path, depth + 1))
                    continue
            except OSError:
                continue
            base, dot, ext = name.rpartition('.')
            if not dot or not base:
                continue
            if ext.lower() == 'xmp':
                sidecars[os.path.join(d, base).lower()] = e.path
                continue
            k = kind_of(ext)
            if not k:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            files.append(FileRef(e.path, name, base, ext, k, st.st_size, st.st_mtime))
            if progress and len(files) % 250 == 0:
                progress(len(files))
    return files, sidecars


def build_items(files, sidecars, pair=True):
    groups = {}
    for f in files:
        groups.setdefault(os.path.join(os.path.dirname(f.path), f.base).lower(), []).append(f)
    items = []
    for key, g in groups.items():
        sc = sidecars.get(key)
        raws = [f for f in g if f.kind == 'raw']
        jpgs = [f for f in g if f.kind == 'jpeg']
        if pair and len(raws) == 1 and len(jpgs) == 1:
            items.append(Item([raws[0], jpgs[0]], sc))
            continue
        for f in g:
            items.append(Item([f], sc if f.kind != 'jpeg' or len(g) == 1 else None))
    return items


# ------------------------------------------------------------ metadata I/O

def parse_exif_date(s, sub=None):
    m = re.match(r'(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)', str(s or ''))
    if not m:
        return 0.0
    try:
        t = datetime(*map(int, m.groups())).timestamp()
    except ValueError:
        return 0.0
    if sub and str(sub).strip().isdigit():
        t += float('0.' + str(sub).strip())
    return t


def absorb(item, a):
    item.analysis = a
    item.orient = a.orient or 1
    item.exif = a.exif or {}
    if a.ow:
        item.w, item.h = a.ow, a.oh
    t = parse_exif_date(item.exif.get('date'), item.exif.get('subsec'))
    if t:
        item.time = t


def ensure_meta(item, settings):
    """Load embedded/sidecar metadata once (thread safe). Returns the item."""
    if item.meta_loaded:
        return item
    with item.lock:
        if item.meta_loaded:
            return item
        a = item.analysis
        if a is None:
            try:
                a = previews.analyze(item.pv.path)
                absorb(item, a)
            except OSError:
                a = None
        m = M.blank()
        if a is not None:
            m.update(M.read_jpeg_meta(a.xmp, a.app13))
        use_sidecar = item.sidecar and (item.pv.kind != 'jpeg' or item.is_pair or settings.get('jpeg_mode') == 'sidecar')
        if use_sidecar:
            try:
                with open(item.sidecar, 'r', encoding='utf-8', errors='replace') as fh:
                    m.update(M.parse_xmp(fh.read()))
            except OSError:
                pass
        if item.overlay:            # only known fields (0.4.x also stored edit settings here)
            m.update({k: (list(v) if isinstance(v, list) else v) for k, v in item.overlay.items() if k in m})
        m['people'] = M.uniq(m.get('people') or [])
        m['keywords'] = [k for k in M.uniq(m.get('keywords') or []) if k not in m['people']]
        item.meta = m
        item.meta_loaded = True
    return item


def _atomic_write(path, data: bytes):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix='.bm-', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_item_meta(item, meta, settings):
    """Write `meta` (a snapshot) to the item's files. Called off the UI thread."""
    p2k, iim = settings.get('people_to_keywords', True), settings.get('write_iim', True)
    embed = settings.get('jpeg_mode', 'embed') == 'embed'
    need_sidecar = False
    for f in item.files:
        if f.kind == 'jpeg' and embed:
            with open(f.path, 'rb') as fh:
                data = fh.read()
            _atomic_write(f.path, M.rewrite_jpeg(data, meta, p2k, iim))
            st = os.stat(f.path)
            f.size, f.mtime = st.st_size, st.st_mtime
            if f is item.pv:
                item.analysis = None if item.analysis is None else _reanalyze(item)
        else:
            need_sidecar = True
    if need_sidecar:
        path = item.sidecar or os.path.join(item.dir, item.base + '.xmp')
        existing = None
        if item.sidecar:
            try:
                with open(item.sidecar, 'r', encoding='utf-8', errors='replace') as fh:
                    existing = fh.read()
            except OSError:
                pass
        _atomic_write(path, M.build_xmp(meta, existing, p2k).encode('utf-8'))
        item.sidecar = path


def _reanalyze(item):
    try:
        a = previews.analyze(item.pv.path)
        absorb(item, a)
        return a
    except OSError:
        return None


# ------------------------------------------------------------ memory cards

def is_card(path):
    """A camera card (or a copy of one): has, or is inside, a DCIM folder."""
    p = os.path.abspath(path)
    parts = [x.lower() for x in p.replace('\\', '/').split('/') if x]
    return 'dcim' in parts or os.path.isdir(os.path.join(p, 'DCIM'))


def card_scan_root(path):
    d = os.path.join(os.path.abspath(path), 'DCIM')
    return d if os.path.isdir(d) else path


def session_key(item):
    f = item.primary
    return f'{f.name}|{f.size}|{int(f.mtime)}'


class CullStore:
    """Culling done on a read-only card, kept by the app until the photos are ingested."""
    KEEP = 100_000

    def __init__(self, path):
        self.path, self.data, self.changed = str(path), {}, False
        try:
            with open(self.path, encoding='utf-8') as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, item):
        return self.data.get(session_key(item))

    def put(self, item):
        blank = M.blank()
        diff = {k: v for k, v in item.meta.items() if v != blank.get(k)}
        key = session_key(item)
        if diff:
            self.data.pop(key, None)         # re-insert: newest last
            self.data[key] = diff
        else:
            self.data.pop(key, None)
        self.changed = True

    def save(self):
        if not self.changed:
            return
        if len(self.data) > self.KEEP:
            self.data = dict(list(self.data.items())[-self.KEEP:])
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(self.data, fh, ensure_ascii=False)
        os.replace(tmp, self.path)
        self.changed = False


# ---------------------------------------------------------- ingest history

def _history_path():
    from .config import app_dir
    return app_dir() / 'ingested.json'


def history_key(item):
    f = item.primary
    return f'{f.name}|{f.size}|{int(item.time)}'


def load_history(path=None):
    import json
    try:
        with open(path or _history_path(), encoding='utf-8') as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return set()


def save_history(keys, path=None):
    import json
    path = path or _history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = sorted(keys)[-200000:]
    with open(str(path) + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(keys, fh)
    os.replace(str(path) + '.tmp', path)


# --------------------------------------------------------------- templates

def natural_join(names):
    names = list(names)
    if len(names) < 2:
        return names[0] if names else ''
    return ', '.join(names[:-1]) + ' and ' + names[-1]


MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December']
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

TEMPLATE_HELP = [
    ('{people}', 'Tagged players: "Gustav, John and Mark"'),
    ('{people_list}', 'Tagged players: "Gustav, John, Mark"'),
    ('{person}', 'First tagged player'),
    ('{preset}', 'Active tag preset name (e.g. Hockey)'),
    ('{event} {city} {headline} {credit} {byline} {caption}', 'Current field values'),
    ('{orig} {filename}', 'Original file name (without / with extension)'),
    ('{yyyy} {yy} {mm} {dd} {hh} {min} {ss}', 'Capture date & time parts'),
    ('{date} {time} {longdate} {month} {weekday}', '20261021, 193005, October 21, 2026, …'),
    ('{camera}', 'Camera model'),
    ('{seq} {seq:3}', 'Running sequence number (copy / ingest)'),
]


def expand(tpl, item, meta=None, seq=None, seq_digits=4, preset_name=''):
    if not tpl:
        return ''
    meta = meta if meta is not None else item.meta
    d = datetime.fromtimestamp(item.time or item.primary.mtime or 0)
    ppl = list(meta.get('people') or [])
    v = {
        'orig': item.base, 'name': item.base, 'filename': item.name,
        'yyyy': f'{d.year:04d}', 'yy': f'{d.year % 100:02d}', 'mm': f'{d.month:02d}', 'dd': f'{d.day:02d}',
        'hh': f'{d.hour:02d}', 'min': f'{d.minute:02d}', 'ss': f'{d.second:02d}',
        'date': d.strftime('%Y%m%d'), 'time': d.strftime('%H%M%S'),
        'longdate': f'{MONTHS[d.month - 1]} {d.day}, {d.year}', 'month': MONTHS[d.month - 1],
        'weekday': WEEKDAYS[d.weekday()],
        'camera': str(item.exif.get('model') or ''),
        'people': natural_join(ppl), 'people_list': ', '.join(ppl), 'person': ppl[0] if ppl else '',
        'preset': preset_name, 'jobid': meta.get('jobId', ''),
    }
    for k in ('event', 'city', 'state', 'country', 'headline', 'credit', 'byline', 'caption', 'title', 'source'):
        v[k] = meta.get(k) or ''

    def rep(m):
        key, n = m.group(1).lower(), m.group(2)
        if key == 'seq':
            return str(seq if seq is not None else 1).zfill(int(n) if n else seq_digits)
        return v.get(key, m.group(0))

    return re.sub(r'\{(\w+)(?::(\d+))?\}', rep, tpl)


def sanitize(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(s))
    return re.sub(r'\s+', ' ', s).strip().rstrip('. ')


def sanitize_path(s):
    return '/'.join(p for p in (sanitize(x) for x in str(s).replace('\\', '/').split('/')) if p)


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s.lower())]


def split_list(s):
    return [x.strip() for x in re.split(r'[,;\n]', s or '') if x.strip()]


META_FORM = [
    ('caption', 'Caption', True), ('headline', 'Headline', False), ('title', 'Title', False),
    ('keywords', 'Keywords', False), ('event', 'Event', False), ('byline', 'Photographer', False),
    ('bylineTitle', 'Photographer title', False), ('credit', 'Credit', False), ('source', 'Source', False),
    ('copyright', 'Copyright', False), ('city', 'City', False), ('sublocation', 'Venue', False),
    ('state', 'State / province', False), ('country', 'Country', False), ('countryCode', 'Country code', False),
    ('jobId', 'Job ID', False), ('instructions', 'Instructions', True),
]


def apply_meta_preset(meta, preset, item, mode='replace', preset_name=''):
    """Fill `meta` from a metadata preset. Keywords are always appended."""
    snapshot = M.copy_meta(meta)
    for key, _, _ in META_FORM:
        tpl = (preset.get('fields', {}).get(key) or '').strip()
        if not tpl:
            continue
        val = expand(tpl, item, snapshot, preset_name=preset_name)
        if key == 'keywords':
            meta['keywords'] = M.uniq(list(meta['keywords']) + split_list(val))
        elif mode == 'fill' and meta.get(key):
            continue
        else:
            meta[key] = val


def fmt_exposure(ex):
    parts = []
    t = ex.get('exposure')
    if isinstance(t, (int, float)) and t > 0:
        parts.append(f'1/{round(1 / t)}s' if t < 1 else f'{t:g}s')
    fn = ex.get('fnumber')
    if isinstance(fn, (int, float)) and fn > 0:
        parts.append(f'f/{fn:.1f}'.replace('.0', ''))
    if ex.get('iso'):
        parts.append(f'ISO {ex["iso"]}')
    fl = ex.get('focal')
    if isinstance(fl, (int, float)) and fl > 0:
        parts.append(f'{fl:.0f}mm')
    return '  '.join(parts)


def fmt_bytes(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
