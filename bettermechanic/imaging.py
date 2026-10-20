"""Decoding embedded JPEGs into thumbnails / previews (runs in worker threads).

Pillow is used here rather than Qt: it releases the GIL while decoding, so
several threads really decode in parallel, and `draft()` lets libjpeg decode
straight to 1/2, 1/4 or 1/8 size, which makes thumbnails of big previews cheap.
(Qt's image readers are only used on the UI thread.)
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from . import previews

Image.MAX_IMAGE_PIXELS = None
T = Image.Transpose
ORIENT = {2: T.FLIP_LEFT_RIGHT, 3: T.ROTATE_180, 4: T.FLIP_TOP_BOTTOM, 5: T.TRANSPOSE,
          6: T.ROTATE_270, 7: T.TRANSVERSE, 8: T.ROTATE_90}


def _fit(w, h, box):
    s = min(1.0, box / max(w, h, 1))
    return max(1, round(w * s)), max(1, round(h * s)), s


def _decode(data: bytes, full_w, target=None, clip=None) -> Image.Image:
    """Decode JPEG bytes; `target` (w, h) is the wanted output size, `clip` a crop box in full-size pixels."""
    im = Image.open(BytesIO(data))
    if target:
        need = target
        if clip:
            cw, ch = clip[2] - clip[0], clip[3] - clip[1]
            need = (max(1, round(target[0] * im.size[0] / cw)), max(1, round(target[1] * im.size[1] / ch)))
        im.draft('RGB', need)
    im = im.convert('RGB')
    if clip:
        s = im.size[0] / full_w
        im = im.crop(tuple(round(v * s) for v in clip))
    if target and (im.size[0] > target[0] or im.size[1] > target[1]):
        im = im.resize(target, Image.Resampling.LANCZOS, reducing_gap=2.0)
    return im


def orient(im: Image.Image, o: int) -> Image.Image:
    t = ORIENT.get(o or 1)
    return im.transpose(t) if t is not None else im


def _raster(path, box=None):
    with Image.open(path) as im:
        im.seek(0)
        if box:
            im.draft('RGB', (box, box))
        im = im.convert('RGB')
    if box:
        im.thumbnail((box, box), Image.Resampling.LANCZOS)
    return im


def to_jpeg(im: Image.Image, quality=85) -> bytes:
    buf = BytesIO()
    im.save(buf, 'JPEG', quality=quality, optimize=False)
    return buf.getvalue()


def make_thumb(path, a, size, hq):
    """Return (jpeg bytes | None, long edge in px)."""
    cands = a.cands
    im = None
    if cands:
        big = cands[-1]
        if hq:
            pick = next((c for c in cands if max(c.w, c.h) >= size), big)
        else:
            pick = next((c for c in cands if max(c.w, c.h) >= 120), big)
        for c in ((pick, big) if pick is not big else (big,)):
            clip = None
            sw, sh = c.w, c.h
            if c is not big and big.h and c.h:
                # EXIF thumbnails are often 4:3 with black bars: crop them off
                ar, car = big.w / big.h, c.w / c.h
                if abs(car - ar) / ar > 0.03:
                    if car > ar:
                        sw = round(c.h * ar)
                        clip = ((c.w - sw) // 2, 0, (c.w - sw) // 2 + sw, c.h)
                    else:
                        sh = round(c.w / ar)
                        clip = (0, (c.h - sh) // 2, c.w, (c.h - sh) // 2 + sh)
            w, h, s = _fit(sw, sh, size)
            try:
                im = _decode(previews.read_cand(path, c), c.w, (w, h) if s < 0.95 else None, clip)
                break
            except (OSError, ValueError, SyntaxError):
                im = None
    elif a.format in ('raster', 'tiff', 'unknown'):
        try:
            im = _raster(path, size)
        except (OSError, ValueError, SyntaxError):
            im = None
    if im is None:
        return None, 0
    im = orient(im, a.orient)
    if max(im.size) > size * 1.05:
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
    return to_jpeg(im), max(im.size)


def make_preview(path, a, max_w=0, max_h=0):
    """Fit-to-screen preview (max_w/max_h) or full size (0). Returns a PIL RGB image or None."""
    cands = a.cands
    if not cands:
        if a.format in ('raster', 'tiff', 'unknown'):
            try:
                return _raster(path, max(max_w, max_h) or None)
            except (OSError, ValueError, SyntaxError):
                return None
        return None
    rot = a.orient >= 5
    start = len(cands) - 1
    if max_w:
        for i, c in enumerate(cands):
            w, h = (c.h, c.w) if rot else (c.w, c.h)
            if w >= max_w or h >= max_h:
                start = i
                break
    for c in cands[start:] + cands[:start][::-1]:
        target = None
        if max_w:
            w, h = (c.h, c.w) if rot else (c.w, c.h)
            s = min(max_w / w, max_h / h)
            if s < 0.9:
                target = (max(1, round(c.w * s)), max(1, round(c.h * s)))
        try:
            return orient(_decode(previews.read_cand(path, c), c.w, target), a.orient)
        except (OSError, ValueError, SyntaxError):
            continue
    return None


def render_jpeg(path, a, long_edge=0, quality=90) -> bytes:
    im = make_preview(path, a, long_edge, long_edge)
    if im is None:
        raise OSError('no decodable image')
    if long_edge and max(im.size) > long_edge:
        im.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    return to_jpeg(im, quality)
