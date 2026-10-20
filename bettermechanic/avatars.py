"""Player photos: fetched from an image link or a local file, cropped square, cached on disk.

Downloading and decoding happen on background threads with Pillow; the UI
thread only loads the small cached JPEG into a QPixmap.
"""
from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap

from . import theme

MAX_BYTES = 15 * 1024 * 1024
SIZE = 256
PALETTE = ['blue', 'orange', 'green', 'purple', 'red', 'yellow']


def initials(name):
    parts = [p for p in name.replace('-', ' ').split() if p[:1].isalnum()]
    if not parts:
        return '?'
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper()


def placeholder_color(name):
    return theme.qc(PALETTE[int(hashlib.md5(name.encode('utf-8')).hexdigest(), 16) % len(PALETTE)])


def draw_avatar(p: QPainter, r: QRectF, name, pix: QPixmap | None):
    """Circular photo, or coloured initials when there is no photo."""
    path = QPainterPath()
    path.addEllipse(r)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if pix is not None and not pix.isNull():
        p.setClipPath(path)
        p.drawPixmap(r, pix, QRectF(pix.rect()))
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(placeholder_color(name))
        p.drawPath(path)
        f = QFont()
        f.setPixelSize(max(9, int(r.height() * 0.38)))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(r, Qt.AlignCenter, initials(name))
    p.restore()


def _square(im):
    w, h = im.size
    if h > w:                       # portrait headshot: keep the top, where the face is
        top = int((h - w) * 0.15)
        return im.crop((0, top, w, top + w))
    left = (w - h) // 2
    return im.crop((left, 0, left + h, h))


def read_source(src):
    if src.lower().startswith(('http://', 'https://', 'file://')):
        req = urllib.request.Request(src, headers={'User-Agent': 'BetterMechanic/1.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(MAX_BYTES + 1)
    else:
        with open(os.path.expanduser(src), 'rb') as fh:
            data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('image is too large')
    return data


def make_avatar_file(src, dest):
    im = Image.open(BytesIO(read_source(src)))
    im = ImageOps.exif_transpose(im).convert('RGB')
    im = _square(im).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    tmp = dest + '.part'
    im.save(tmp, 'JPEG', quality=90)
    os.replace(tmp, dest)


class AvatarStore(QObject):
    ready = Signal(str)          # source string whose image finished (or failed)

    def __init__(self, cache_dir):
        super().__init__()
        self.dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.pix, self.pending, self.failed = {}, set(), {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='avatar')

    def path_for(self, src):
        return os.path.join(self.dir, hashlib.sha1(src.strip().encode('utf-8')).hexdigest() + '.jpg')

    def get(self, src):
        """QPixmap if ready, else None (and starts loading it)."""
        src = (src or '').strip()
        if not src:
            return None
        pm = self.pix.get(src)
        if pm is not None:
            return pm
        path = self.path_for(src)
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self.pix[src] = pm
                return pm
        with self.lock:
            if src not in self.pending and src not in self.failed:
                self.pending.add(src)
                self.pool.submit(self._fetch, src, path)
        return None

    def error(self, src):
        return self.failed.get((src or '').strip())

    def reload(self, src):
        src = (src or '').strip()
        self.pix.pop(src, None)
        self.failed.pop(src, None)
        try:
            os.remove(self.path_for(src))
        except OSError:
            pass
        return self.get(src)

    def _fetch(self, src, path):
        try:
            make_avatar_file(src, path)
        except Exception as e:      # network, missing file, not an image …
            self.failed[src] = f'{type(e).__name__}: {e}'
        finally:
            with self.lock:
                self.pending.discard(src)
            self.ready.emit(src)
