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
AGENT = 'BetterMechanic/1.0 (https://github.com/Rtx-9/bettermechanic)'   # Wikimedia asks for a contact link
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


def find_face(im):
    """(x, y, w, h) of the largest face, from Windows' built-in face detector; None when there's none or no
    detector (other systems)."""
    try:
        import asyncio

        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.faceanalysis import FaceDetector
        from winrt.windows.storage.streams import Buffer
    except Exception:
        return None
    scale = min(1.0, 1000 / max(im.size))
    gray = im.convert('L').resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))))
    data = gray.tobytes()

    async def detect():
        buf = Buffer(len(data))
        buf.length = len(data)
        view = memoryview(buf)
        view[:] = data
        view.release()
        bitmap = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.GRAY8, gray.width, gray.height)
        detector = await FaceDetector.create_async()       # keep it referenced while it works
        found = await detector.detect_faces_async(bitmap)
        return [(f.face_box.x, f.face_box.y, f.face_box.width, f.face_box.height) for f in found]
    try:
        with _face_lock:
            faces = asyncio.run(detect())
    except Exception:
        return None
    if not faces:
        return None
    return tuple(v / scale for v in max(faces, key=lambda b: b[2] * b[3]))


_face_lock = threading.Lock()


def face_detection_available():
    try:
        from winrt.windows.media.faceanalysis import FaceDetector
        return bool(FaceDetector.is_supported)
    except Exception:
        return False


def _square(im):
    w, h = im.size
    face = find_face(im)
    if face:                                     # head and shoulders around the face
        fx, fy, fw, fh = face
        side = int(min(w, h, max(fw * 3.0, fh * 2.6)))
        left = max(0, min(w - side, int(fx + fw / 2 - side / 2)))
        top = max(0, min(h - side, int(fy + fh / 2 - side * 0.42)))
        return im.crop((left, top, left + side, top + side))
    if h > w:                       # portrait headshot: keep the top, where the face is
        top = int((h - w) * 0.15)
        return im.crop((0, top, w, top + w))
    left = (w - h) // 2
    return im.crop((left, 0, left + h, h))


def _cutout(im):
    """Cut-out headshot on a transparent background (like liiga.fi's): frame the head, fill the background."""
    alpha = im.getchannel('A')
    w, h = im.size
    head = alpha.crop((0, 0, w, int(h * 0.33))).point(lambda a: 255 if a > 128 else 0).getbbox()
    if head:
        cx, side = (head[0] + head[2]) // 2, min(w, h, max(int((head[2] - head[0]) * 2.3), int(h * 0.3)))
        left = max(0, min(w - side, cx - side // 2))
        top = max(0, min(h - side, head[1] - side // 12))
        im = im.crop((left, top, left + side, top + side))
    bg = Image.new('RGBA', im.size, (229, 229, 234, 255))
    return Image.alpha_composite(bg, im).convert('RGB')


def read_source(src):
    if src.lower().startswith(('http://', 'https://', 'file://')):
        req = urllib.request.Request(src, headers={'User-Agent': AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(MAX_BYTES + 1)
    else:
        with open(os.path.expanduser(src), 'rb') as fh:
            data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('image is too large')
    return data


def is_placeholder(im):
    """A silhouette, logo or blank card rather than a photo: real photos have far more distinct colours."""
    return len(im.convert('RGB').resize((64, 64)).getcolors(5000) or []) < 700


def make_avatar_file(src, dest):
    im = Image.open(BytesIO(read_source(src)))
    im = ImageOps.exif_transpose(im)
    if im.mode in ('RGBA', 'LA', 'P') and im.convert('RGBA').getchannel('A').getextrema()[0] < 255:
        im = _cutout(im.convert('RGBA'))
    if is_placeholder(im):
        raise ValueError('this is a placeholder picture, not a photo')
    im = _square(im.convert('RGB')).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
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
