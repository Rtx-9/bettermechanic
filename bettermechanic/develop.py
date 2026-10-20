"""Develop settings: Lightroom preset import, and an image pipeline that renders them.

Settings use Adobe Camera Raw names (crs:Exposure2012, crs:HueAdjustmentRed …),
so they round-trip through XMP: Lightroom / Camera Raw apply them to the raw
data, while BetterMechanic renders a close approximation on the camera's
embedded JPEG (it cannot reproduce Adobe's colour science or profiles).
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image

CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'
RDF = '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
COLORS = ['Red', 'Orange', 'Yellow', 'Green', 'Aqua', 'Blue', 'Purple', 'Magenta']
HUE_CENTERS = [0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0]

# Settings whose neutral value is 0: scaled by a preset's Amount and shown as sliders.
DELTA_KEYS = (['Exposure2012', 'Contrast2012', 'Highlights2012', 'Shadows2012', 'Whites2012', 'Blacks2012',
               'Texture', 'Clarity2012', 'Dehaze', 'Vibrance', 'Saturation', 'IncrementalTemperature',
               'IncrementalTint', 'ParametricShadows', 'ParametricDarks', 'ParametricLights', 'ParametricHighlights',
               'PostCropVignetteAmount', 'GrainAmount', 'SplitToningShadowSaturation',
               'SplitToningHighlightSaturation', 'ColorGradeMidtoneSat', 'ColorGradeShadowLum',
               'ColorGradeMidtoneLum', 'ColorGradeHighlightLum', 'ColorGradeGlobalSat', 'ColorGradeGlobalLum']
              + [f'{k}Adjustment{c}' for k in ('Hue', 'Saturation', 'Luminance') for c in COLORS]
              + [f'GrayMixer{c}' for c in COLORS])
CURVE_KEYS = ['ToneCurvePV2012', 'ToneCurvePV2012Red', 'ToneCurvePV2012Green', 'ToneCurvePV2012Blue']
DEFAULTS = {'Sharpness': 40, 'SharpenRadius': 1.0, 'PostCropVignetteMidpoint': 50, 'PostCropVignetteFeather': 50,
            'PostCropVignetteRoundness': 0, 'GrainSize': 25, 'ParametricShadowSplit': 25,
            'ParametricMidtoneSplit': 50, 'ParametricHighlightSplit': 75, 'SplitToningBalance': 0,
            'ColorGradeBlending': 50}
# Sliders in the Edit panel: (key, label, min, max, step)
BASIC = [
    ('White Balance', [('IncrementalTemperature', 'Temp', -100, 100, 1), ('IncrementalTint', 'Tint', -100, 100, 1)]),
    ('Tone', [('Exposure2012', 'Exposure', -5, 5, 0.05), ('Contrast2012', 'Contrast', -100, 100, 1),
              ('Highlights2012', 'Highlights', -100, 100, 1), ('Shadows2012', 'Shadows', -100, 100, 1),
              ('Whites2012', 'Whites', -100, 100, 1), ('Blacks2012', 'Blacks', -100, 100, 1)]),
    ('Presence', [('Texture', 'Texture', -100, 100, 1), ('Clarity2012', 'Clarity', -100, 100, 1),
                  ('Dehaze', 'Dehaze', -100, 100, 1), ('Vibrance', 'Vibrance', -100, 100, 1),
                  ('Saturation', 'Saturation', -100, 100, 1)]),
    ('Effects', [('PostCropVignetteAmount', 'Vignette', -100, 100, 1), ('GrainAmount', 'Grain', 0, 100, 1)]),
    ('Detail', [('Sharpness', 'Sharpening', 0, 150, 1)]),
]


HUE_KEYS = ['SplitToningShadowHue', 'SplitToningHighlightHue', 'ColorGradeMidtoneHue', 'ColorGradeGlobalHue',
            'ColorGradeShadowHue', 'ColorGradeHighlightHue']
NUMERIC = set(DELTA_KEYS) | set(DEFAULTS) | set(HUE_KEYS) | {
    'Temperature', 'Tint', 'Exposure', 'Contrast', 'ConvertToGrayscale', 'SharpenDetail', 'SharpenEdgeMasking',
    'LuminanceSmoothing', 'ColorNoiseReduction', 'GrainFrequency', 'ColorGradeShadowSat', 'ColorGradeHighlightSat'}


def clean(settings):
    """Drop deletion markers (None)."""
    return {k: v for k, v in (settings or {}).items() if v is not None}


def num(s, k, default=0.0):
    v = s.get(k)
    if v is None:
        return DEFAULTS.get(k, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return DEFAULTS.get(k, default)


def is_active(settings):
    """True when the settings change how the picture looks."""
    s = clean(settings)
    if any(abs(num(s, k)) > 1e-6 for k in DELTA_KEYS):
        return True
    if s.get('ConvertToGrayscale') in (True, 'True', 'true'):
        return True
    if any(_curve_points(s.get(k)) not in (None, [(0, 0), (255, 255)]) for k in CURVE_KEYS):
        return True
    if num(s, 'Sharpness') > 40.5:
        return True
    if s.get('WhiteBalance') not in (None, 'As Shot') and ('Temperature' in s or 'Tint' in s):
        return True
    return False


# ------------------------------------------------------------- presets

def _typed(v):
    if isinstance(v, str):
        t = v.strip()
        if t in ('True', 'true'):
            return True
        if t in ('False', 'false'):
            return False
        try:
            return float(t) if re.search(r'[.eE]', t) else int(t.lstrip('+'))
        except ValueError:
            return t
    return v


def parse_crs(root):
    """crs:* settings from an XMP element tree (attributes, Seq lists, Alt texts)."""
    out = {}
    for d in root.iter(RDF + 'Description'):
        for k, v in d.attrib.items():
            if k.startswith('{' + CRS + '}'):
                key = k[len(CRS) + 2:]
                out[key] = _typed(v) if key in NUMERIC else v
        for c in d:
            if not c.tag.startswith('{' + CRS + '}'):
                continue
            key = c.tag[len(CRS) + 2:]
            seq = c.find(RDF + 'Seq')
            alt = c.find(RDF + 'Alt')
            if seq is not None:
                out[key] = [(li.text or '').strip() for li in seq.findall(RDF + 'li')]
            elif alt is not None:
                li = alt.find(RDF + 'li')
                out[key] = (li.text or '').strip() if li is not None else ''
            elif len(c) == 0 and (c.text or '').strip():
                out[key] = _typed(c.text) if key in NUMERIC else c.text.strip()
    return out


def parse_xmp_preset(data: bytes):
    root = ET.fromstring(data)
    s = parse_crs(root)
    if not s:
        return None
    name = s.pop('Name', '') or ''
    group = s.pop('Group', '') or ''
    for k in ('UUID', 'SupportsAmount', 'SupportsColor', 'SupportsMonochrome', 'SupportsHighDynamicRange',
              'SupportsNormalDynamicRange', 'SupportsSceneReferred', 'SupportsOutputReferred', 'CameraModelRestriction',
              'Copyright', 'ContactInfo', 'Version', 'Cluster', 'SortName', 'ShortName', 'Description'):
        s.pop(k, None)
    kind = s.pop('PresetType', 'Normal')
    if kind == 'Look':                 # a profile, not a develop preset
        return None
    return {'name': name, 'group': group, 'settings': s}


def _lua_table(text, start):
    """Parse a Lua table literal beginning at text[start] == '{'. Returns (value, end)."""
    i, n = start + 1, len(text)
    items, keyed = [], {}

    def skip(i):
        while i < n:
            if text[i].isspace() or text[i] == ',':
                i += 1
            elif text.startswith('--', i):
                j = text.find('\n', i)
                i = n if j < 0 else j + 1
            else:
                break
        return i

    while True:
        i = skip(i)
        if i >= n or text[i] == '}':
            return (keyed if keyed or not items else items), i + 1
        m = re.match(r'([A-Za-z_]\w*)\s*=\s*', text[i:])
        key = None
        if m:
            key, i = m.group(1), i + m.end()
        elif text[i] == '[':
            m = re.match(r'\[\s*"([^"]*)"\s*\]\s*=\s*', text[i:])
            if m:
                key, i = m.group(1), i + m.end()
        val, i = _lua_value(text, i)
        if key is None:
            items.append(val)
        else:
            keyed[key] = val


def _lua_value(text, i):
    if text[i] == '{':
        return _lua_table(text, i)
    if text[i] == '"':
        j = i + 1
        buf = []
        while j < len(text) and text[j] != '"':
            if text[j] == '\\' and j + 1 < len(text):
                j += 1
            buf.append(text[j])
            j += 1
        return ''.join(buf), j + 1
    m = re.match(r'ZSTR\s*"([^"]*)"', text[i:])
    if m:
        s = m.group(1)
        return (s.split('=', 1)[1] if '=' in s else s), i + m.end()
    m = re.match(r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|nil|[A-Za-z_][\w.]*', text[i:])
    if not m:
        return None, i + 1
    t = m.group(0)
    v = {'true': True, 'false': False, 'nil': None}.get(t, t)
    if isinstance(v, str):
        try:
            v = float(t) if re.search(r'[.eE]', t) else int(t)
        except ValueError:
            pass
    return v, i + m.end()


def parse_lrtemplate(text: str):
    i = text.find('{')
    if i < 0:
        return None
    root, _ = _lua_table(text, i)
    if not isinstance(root, dict):
        return None
    value = root.get('value') if isinstance(root.get('value'), dict) else root
    settings = value.get('settings') if isinstance(value, dict) else None
    if not isinstance(settings, dict) or root.get('type', 'Develop') not in ('Develop', None):
        return None
    s = {}
    for k, v in settings.items():
        if k in CURVE_KEYS and isinstance(v, list):
            pts = [int(round(float(x))) for x in v]
            s[k] = [f'{pts[j]}, {pts[j + 1]}' for j in range(0, len(pts) - 1, 2)]
        elif isinstance(v, (int, float, bool, str)):
            s[k] = v
    name = root.get('title') or root.get('internalName') or ''
    return {'name': str(name), 'group': '', 'settings': s}


def _from_bytes(name, data):
    lower = name.lower()
    try:
        if lower.endswith('.xmp'):
            return parse_xmp_preset(data)
        if lower.endswith('.lrtemplate'):
            return parse_lrtemplate(data.decode('utf-8', 'replace'))
    except (ET.ParseError, ValueError, IndexError):
        return None
    return None


GENERIC_FOLDERS = {'', 'downloads', 'desktop', 'documents', 'settings', 'presets', 'develop presets', 'temp', 'tmp',
                   'user presets', 'lightroom', 'camera raw'}


def _group_name(folder):
    name = os.path.basename(folder.rstrip('/\\'))
    low = name.lower()
    if low in GENERIC_FOLDERS or low.startswith('tmp') or re.fullmatch(r'[0-9a-f-]{8,}', low):
        return ''
    return name


def read_presets(paths):
    """Presets from files, folders (recursive) and .zip packs. Returns (presets, skipped)."""
    found, skipped = [], 0

    def add(name, data, group_hint):
        nonlocal skipped
        p = _from_bytes(name, data)
        if not p or not p['settings']:
            skipped += 1
            return
        p['name'] = p['name'] or os.path.splitext(os.path.basename(name))[0]
        p['group'] = p['group'] or group_hint or 'Imported'
        found.append(p)

    def add_zip(zf, hint):
        for info in zf.infolist():
            if info.is_dir() or info.file_size > 5_000_000:
                continue
            n = info.filename
            if n.lower().endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(zf.read(info))) as inner:
                    add_zip(inner, os.path.splitext(os.path.basename(n))[0])
            elif n.lower().endswith(('.xmp', '.lrtemplate')) and '__MACOSX' not in n:
                parent = _group_name(os.path.dirname(n.rstrip('/'))) or hint
                add(n, zf.read(info), parent)

    for path in paths:
        if os.path.isdir(path):
            for d, _, files in os.walk(path):
                for f in sorted(files):
                    full = os.path.join(d, f)
                    if f.lower().endswith('.zip'):
                        with zipfile.ZipFile(full) as zf:
                            add_zip(zf, os.path.splitext(f)[0])
                    elif f.lower().endswith(('.xmp', '.lrtemplate')):
                        with open(full, 'rb') as fh:
                            add(f, fh.read(), _group_name(d) or _group_name(path))
        elif path.lower().endswith('.zip'):
            with zipfile.ZipFile(path) as zf:
                add_zip(zf, os.path.splitext(os.path.basename(path))[0])
        elif os.path.isfile(path):
            with open(path, 'rb') as fh:
                add(os.path.basename(path), fh.read(), _group_name(os.path.dirname(path)))
    return found, skipped


class PresetLibrary:
    """Imported develop presets, saved as JSON in the app folder."""

    def __init__(self, path):
        self.path = str(path)
        self.presets = []
        try:
            with open(self.path, encoding='utf-8') as fh:
                self.presets = json.load(fh)
        except (OSError, ValueError):
            self.presets = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(self.presets, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    def groups(self):
        out = {}
        for p in self.presets:
            out.setdefault(p['group'], []).append(p)
        return out

    def get(self, pid):
        return next((p for p in self.presets if p['id'] == pid), None)

    def add_many(self, presets):
        have = {(p['group'], p['name']) for p in self.presets}
        added = 0
        for p in presets:
            if (p['group'], p['name']) in have:
                for q in self.presets:          # same preset imported again: refresh its settings
                    if (q['group'], q['name']) == (p['group'], p['name']):
                        q['settings'] = p['settings']
                continue
            self.presets.append({'id': uuid.uuid4().hex[:12], **p})
            have.add((p['group'], p['name']))
            added += 1
        self.save()
        return added

    def add_user(self, name, group, settings):
        p = {'id': uuid.uuid4().hex[:12], 'name': name, 'group': group or 'User Presets', 'settings': dict(settings)}
        self.presets.append(p)
        self.save()
        return p

    def remove(self, ids):
        ids = set(ids)
        self.presets = [p for p in self.presets if p['id'] not in ids]
        self.save()


def _curve_points(v):
    if not v:
        return None
    pts = []
    for e in v:
        try:
            x, y = [float(t) for t in str(e).replace(';', ',').split(',')[:2]]
            pts.append((x, y))
        except ValueError:
            continue
    return pts or None


def scale_settings(settings, amount):
    """Apply a preset at `amount` (1.0 = as made): neutral-zero values and curves are scaled."""
    if abs(amount - 1) < 1e-6:
        return dict(settings)
    out = {}
    for k, v in settings.items():
        if k in DELTA_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(v * amount, 3) if k == 'Exposure2012' else round(v * amount)
        elif k in CURVE_KEYS and isinstance(v, list):
            pts = _curve_points(v) or []
            out[k] = [f'{round(x)}, {round(x + (y - x) * amount)}' for x, y in pts]
        elif k == 'Sharpness' and isinstance(v, (int, float)):
            out[k] = round(40 + (v - 40) * amount)
        else:
            out[k] = v
    return out


# ------------------------------------------------------------- rendering

def _smooth(e0, e1, x):
    t = np.clip((x - e0) / max(1e-6, (e1 - e0)), 0, 1)
    return t * t * (3 - 2 * t)


def _binomial(a, passes):
    """Separable [1 4 6 4 1]/16 filter (sigma 1 px per pass), edges clamped."""
    for _ in range(passes):
        for axis in (0, 1):
            p = np.pad(a, [(2, 2) if ax == axis else (0, 0) for ax in range(2)], mode='edge')
            n = a.shape[axis]
            sl = lambda o: p[o:o + n] if axis == 0 else p[:, o:o + n]   # noqa: E731
            a = (sl(0) + sl(4)) * 0.0625 + (sl(1) + sl(3)) * 0.25 + sl(2) * 0.375
    return a


def blur(a, sigma):
    """Fast approximate Gaussian blur of a 2-D float32 array (sigma in pixels)."""
    h, w = a.shape
    if sigma < 0.5:
        return a
    f = max(1.0, sigma / 1.5)                    # work on a copy small enough for a few cheap passes
    if f > 1.2:
        sw, sh = max(4, int(round(w / f))), max(4, int(round(h / f)))
        small = np.asarray(Image.fromarray(a, 'F').resize((sw, sh), Image.BOX))
        small = _binomial(small, max(1, round((sigma / f) ** 2)))
        return np.asarray(Image.fromarray(small, 'F').resize((w, h), Image.BILINEAR))
    return _binomial(a, max(1, round(sigma ** 2)))


def _curve_lut(pts, size=1024):
    """Monotone cubic (Fritsch-Carlson) curve through 0-255 points -> LUT on 0..1."""
    pts = sorted(set((min(255.0, max(0.0, x)), min(255.0, max(0.0, y))) for x, y in pts))
    xs = np.array([p[0] for p in pts], np.float64) / 255
    ys = np.array([p[1] for p in pts], np.float64) / 255
    grid = np.linspace(0, 1, size)
    if len(xs) < 2:
        return grid.astype(np.float32)
    d = np.diff(ys) / np.maximum(np.diff(xs), 1e-9)
    m = np.concatenate([[d[0]], (d[:-1] + d[1:]) / 2, [d[-1]]])
    for k in range(len(d)):
        if d[k] == 0:
            m[k] = m[k + 1] = 0
        else:
            a, b = m[k] / d[k], m[k + 1] / d[k]
            s = a * a + b * b
            if s > 9:
                t = 3 / math.sqrt(s)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    idx = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    hseg = xs[idx + 1] - xs[idx]
    t = np.where(hseg > 0, (grid - xs[idx]) / np.maximum(hseg, 1e-9), 0)
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    out = h00 * ys[idx] + h10 * hseg * m[idx] + h01 * ys[idx + 1] + h11 * hseg * m[idx + 1]
    out = np.where(grid < xs[0], ys[0], np.where(grid > xs[-1], ys[-1], out))
    return np.clip(out, 0, 1).astype(np.float32)


def _apply_lut(x, lut):
    idx = (np.clip(x, 0, 1) * (len(lut) - 1) + 0.5).astype(np.int32)
    return lut[idx]


def _band_lut(values):
    """Per-degree blend of 8 per-band values (Lightroom's colour mixer bands, triangular weights)."""
    hue = np.arange(360, dtype=np.float32)
    out = np.zeros(360, np.float32)
    n = len(HUE_CENTERS)
    for i, c in enumerate(HUE_CENTERS):
        if not values[i]:
            continue
        nxt = (HUE_CENTERS[(i + 1) % n] - c) % 360
        prv = (c - HUE_CENTERS[(i - 1) % n]) % 360
        delta = (hue - c + 180) % 360 - 180
        span = np.where(delta >= 0, nxt, prv)
        out += values[i] * np.clip(1 - np.abs(delta) / span, 0, 1)
    return out


def render(rgb8: np.ndarray, settings) -> np.ndarray:
    """Apply develop settings to an sRGB uint8 HxWx3 image. Returns uint8."""
    s = clean(settings)
    if not is_active(s):
        return rgb8
    img = rgb8.astype(np.float32) * (1 / 255)
    h, w = img.shape[:2]
    size = max(h, w)

    # white balance + exposure (exact in gamma space for a power-law gamma)
    mired = 0.0
    tint = num(s, 'IncrementalTint') * 0.9
    mired += num(s, 'IncrementalTemperature') * 0.9
    if s.get('WhiteBalance') not in (None, 'As Shot'):
        if 'Temperature' in s:
            mired += 1e6 / 5500 - 1e6 / max(2000.0, num(s, 'Temperature', 5500))
        tint += num(s, 'Tint') * 0.6
    ev = num(s, 'Exposure2012') or num(s, 'Exposure')
    if ev or mired or tint:
        k = np.array([2 ** (mired / 110), 2 ** (-tint / 160), 2 ** (-mired / 110)], np.float32)
        k *= 2 ** ev / (0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2])
        img *= k ** (1 / 2.2)
        if ev > 0:                       # soft roll-off instead of a hard clip
            kn = 0.82
            over = img > kn
            img[over] = kn + (1 - kn) * (1 - np.exp(-(img[over] - kn) / (1 - kn)))

    # split into brightness + two opponent colour axes
    m = img.mean(axis=2)
    c1 = img[..., 0] - 0.5 * (img[..., 1] + img[..., 2])
    c2 = 0.8660254 * (img[..., 1] - img[..., 2])
    m0 = m.copy()

    # tone
    hi, sh, wh, bl = (num(s, k) / 100 for k in ('Highlights2012', 'Shadows2012', 'Whites2012', 'Blacks2012'))
    if hi or sh:
        base = 0.6 * blur(m, size * 0.02) + 0.4 * m
        if hi:
            mk = _smooth(0.5, 1.0, base)
            m = m + hi * 0.22 * mk * (m if hi < 0 else (1 - m))
        if sh:
            mk = 1 - _smooth(0.0, 0.55, base)
            m = m + sh * 0.38 * mk * ((1 - m) if sh > 0 else m)
    if wh:
        m = m + wh * 0.18 * _smooth(0.55, 1.0, m)
    if bl:
        m = m + bl * 0.12 * (1 - _smooth(0.0, 0.35, m))
    con = num(s, 'Contrast2012') / 100
    if con:
        mc = np.clip(m, 0, 1)
        m = m + con * 0.38 * (mc - 0.5) * 4 * mc * (1 - mc)
    par = [num(s, k) / 100 for k in ('ParametricShadows', 'ParametricDarks', 'ParametricLights', 'ParametricHighlights')]
    if any(par):
        s1, s2, s3 = (num(s, k) / 100 for k in ('ParametricShadowSplit', 'ParametricMidtoneSplit',
                                                  'ParametricHighlightSplit'))
        centers = [s1 / 2, (s1 + s2) / 2, (s2 + s3) / 2, (s3 + 1) / 2]
        widths = [max(0.08, s1), max(0.08, s2 - s1), max(0.08, s3 - s2), max(0.08, 1 - s3)]
        mc = np.clip(m, 0, 1)
        for a, c, wd in zip(par, centers, widths):
            if a:
                m = m + a * 0.12 * np.exp(-((mc - c) / wd) ** 2) * 4 * np.clip(mc * (1 - mc) + 0.06, 0, 1)
    pts = _curve_points(s.get('ToneCurvePV2012'))
    if pts and pts != [(0, 0), (255, 255)]:
        m = _apply_lut(np.clip(m, 0, 1), _curve_lut(pts))

    # presence
    tex, cla, deh = (num(s, k) / 100 for k in ('Texture', 'Clarity2012', 'Dehaze'))
    if cla:
        m = m + cla * 0.9 * (m - blur(m, size * 0.012)) * (0.3 + 2.8 * np.clip(m * (1 - m), 0, 0.25))
    if tex:
        m = m + tex * 0.7 * (m - blur(m, max(1.0, size * 0.0015)))
    sharp = max(0.0, num(s, 'Sharpness') - 40) / 110
    if sharp:
        rad = max(0.5, num(s, 'SharpenRadius', 1.0)) * size / 4000
        m = m + sharp * 1.1 * (m - blur(m, max(0.7, rad)))
    chroma_k = np.ones_like(m)
    if deh > 0:
        m = (m - deh * 0.13) / (1 - deh * 0.13)
        chroma_k *= 1 + 0.35 * deh
    elif deh < 0:
        m = m * (1 + deh * 0.3) - deh * 0.3 * 0.82
        chroma_k *= 1 + 0.45 * deh

    # keep colours proportional to the brightness change
    chroma_k *= np.clip((np.clip(m, 0, 1.2) + 0.04) / (m0 + 0.04), 0.3, 3.0)

    # colour
    vib, sat = num(s, 'Vibrance') / 100, num(s, 'Saturation') / 100
    hsl = {k: num(s, k) for k in DELTA_KEYS if 'Adjustment' in k}
    gray = s.get('ConvertToGrayscale') in (True, 'True', 'true')
    grade = any(num(s, k) for k in ('SplitToningShadowSaturation', 'SplitToningHighlightSaturation',
                                    'ColorGradeMidtoneSat', 'ColorGradeGlobalSat', 'ColorGradeShadowLum',
                                    'ColorGradeMidtoneLum', 'ColorGradeHighlightLum', 'ColorGradeGlobalLum'))
    c1 *= chroma_k
    c2 *= chroma_k
    if any(hsl.values()) or gray:
        hue_idx = (np.degrees(np.arctan2(c2, c1)).astype(np.int32)) % 360
        cn = np.clip(np.hypot(c1, c2) * 2.5, 0, 1)
        if gray:
            gm = _band_lut([num(s, f'GrayMixer{c}') for c in COLORS])
            if np.any(gm):
                m = m + gm[hue_idx] * (0.35 / 100) * cn
        else:
            hv, sv, lv = ([hsl[f'{k}Adjustment{c}'] for c in COLORS] for k in ('Hue', 'Saturation', 'Luminance'))
            if any(hv):
                ang = _band_lut(hv)[hue_idx] * (math.radians(0.3))
                ca, sa = np.cos(ang), np.sin(ang)
                c1, c2 = c1 * ca - c2 * sa, c1 * sa + c2 * ca
            if any(sv):
                f = np.clip(1 + _band_lut(sv)[hue_idx] / 100, 0, 2.5)
                c1, c2 = c1 * f, c2 * f
            if any(lv):
                m = m + _band_lut(lv)[hue_idx] * (0.3 / 100) * cn
    if gray:
        c1 = c2 = np.zeros_like(m)
    else:
        if vib or sat:
            cn = np.clip(np.hypot(c1, c2) * 2.2, 0, 1)
            f = np.clip((1 + sat) * (1 + vib * (1 - cn) * (1.2 if vib > 0 else 1)), 0, 3)
            c1, c2 = c1 * f, c2 * f
        if grade:
            mc = np.clip(m, 0, 1)
            bal = (num(s, 'SplitToningBalance') + 0) / 100
            sh_mask = 1 - _smooth(0.0, 0.6 + 0.25 * bal, mc)
            hi_mask = _smooth(0.4 + 0.25 * bal, 1.0, mc)
            mid_mask = np.clip(1 - sh_mask - hi_mask, 0, 1)

            def tint_by(hue_key, sat_key, mask, strength=0.16):
                sv = num(s, sat_key) / 100
                if not sv:
                    return 0, 0
                a = math.radians(num(s, hue_key))
                return sv * strength * math.cos(a) * mask, sv * strength * math.sin(a) * mask

            for hk, sk, mk in (('SplitToningShadowHue', 'SplitToningShadowSaturation', sh_mask),
                               ('SplitToningHighlightHue', 'SplitToningHighlightSaturation', hi_mask),
                               ('ColorGradeMidtoneHue', 'ColorGradeMidtoneSat', mid_mask),
                               ('ColorGradeGlobalHue', 'ColorGradeGlobalSat', np.ones_like(mc))):
                a1, a2 = tint_by(hk, sk, mk)
                c1, c2 = c1 + a1, c2 + a2
            m = m + 0.15 * (num(s, 'ColorGradeShadowLum') / 100 * sh_mask + num(s, 'ColorGradeMidtoneLum') / 100
                            * mid_mask + num(s, 'ColorGradeHighlightLum') / 100 * hi_mask
                            + num(s, 'ColorGradeGlobalLum') / 100)

    # back to RGB
    out = np.empty_like(img)
    out[..., 0] = m + (2 / 3) * c1
    out[..., 1] = m - c1 / 3 + c2 / 1.7320508
    out[..., 2] = m - c1 / 3 - c2 / 1.7320508

    for ch, key in enumerate(CURVE_KEYS[1:]):
        pts = _curve_points(s.get(key))
        if pts and pts != [(0, 0), (255, 255)]:
            out[..., ch] = _apply_lut(np.clip(out[..., ch], 0, 1), _curve_lut(pts))

    # effects
    vig = num(s, 'PostCropVignetteAmount') / 100
    if vig:
        xx = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        yy = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        rnd = (num(s, 'PostCropVignetteRoundness') + 100) / 200
        aspect = w / h
        ax, ay = max(1.0, aspect), max(1.0, 1 / aspect)
        ell = np.sqrt(xx * xx + yy * yy) * (1 / math.sqrt(2))
        circ = np.sqrt((xx * ax) ** 2 + (yy * ay) ** 2) * (1 / math.sqrt(ax * ax + ay * ay))
        d = ell * (1 - rnd) + circ * rnd
        mid = 0.25 + 0.6 * num(s, 'PostCropVignetteMidpoint') / 100
        feather = 0.08 + 0.7 * num(s, 'PostCropVignetteFeather') / 100
        mk = _smooth(mid - feather / 2, mid + feather / 2, d)[..., None]
        if vig < 0:
            out *= 1 + vig * 0.85 * mk
        else:
            out += (1 - out) * vig * 0.85 * mk
    grain = num(s, 'GrainAmount') / 100
    if grain:
        gs = 1 + num(s, 'GrainSize') / 100 * 3 * size / 2000
        rng = np.random.default_rng(1234)
        gh, gw = max(2, int(h / gs)), max(2, int(w / gs))
        noise = rng.standard_normal((gh, gw)).astype(np.float32)
        noise = np.asarray(Image.fromarray(noise, 'F').resize((w, h), Image.BILINEAR))
        mc = np.clip(out.mean(axis=2), 0, 1)
        out += (noise * grain * 0.09 * (0.35 + 2.6 * mc * (1 - mc)))[..., None]

    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def render_pil(im: Image.Image, settings) -> Image.Image:
    if not is_active(settings):
        return im
    return Image.fromarray(render(np.asarray(im.convert('RGB')), settings), 'RGB')
