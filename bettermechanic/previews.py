"""Fast metadata + embedded-preview discovery for JPEG and camera RAW files.

Only the bytes that are needed are read (JPEG headers, TIFF IFDs, ISO-BMFF box
tables). Every RAW format carries one or more ready-made JPEGs inside it, and
using those instead of demosaicing the sensor data is what makes browsing a
memory card fast.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

DECODABLE_SOF = {0xC0, 0xC1, 0xC2}          # baseline / extended / progressive
TSIZE = [0, 1, 1, 2, 4, 8, 1, 1, 2, 4, 8, 4, 8, 4]
TCODE = {1: 'B', 3: 'H', 4: 'I', 6: 'b', 7: 'B', 8: 'h', 9: 'i', 13: 'I'}
CANON_UUID = bytes.fromhex('85c0b687820f11e08111f4ce462b6a48')
CR3_XMP_UUID = bytes.fromhex('be7acfcb97a942e89c71999491e3afac')


@dataclass
class Cand:
    """An embedded JPEG: byte range plus pixel size (stored orientation)."""
    off: int
    length: int
    w: int = 0
    h: int = 0
    whole: bool = False      # the file itself (length follows the file size)


@dataclass
class Analysis:
    format: str = 'unknown'
    orient: int = 1
    exif: dict = field(default_factory=dict)
    cands: list = field(default_factory=list)   # sorted small -> large
    xmp: str | None = None
    app13: bytes | None = None
    ow: int = 0                                  # oriented size of the largest image
    oh: int = 0
    _orient_set: bool = False


class Src:
    """Random-access file reader with a small block cache."""
    B = 1 << 16

    def __init__(self, f, size):
        self.f, self.size, self.blocks = f, size, {}

    def read(self, off, n):
        if off < 0 or off >= self.size or n <= 0:
            return b''
        n = min(n, self.size - off)
        if n > self.B * 4:
            self.f.seek(off)
            return self.f.read(n)
        b0, b1 = off // self.B, (off + n - 1) // self.B
        data = b''.join(self._block(i) for i in range(b0, b1 + 1))
        s = off - b0 * self.B
        return data[s:s + n]

    def _block(self, i):
        b = self.blocks.get(i)
        if b is None:
            self.f.seek(i * self.B)
            b = self.blocks[i] = self.f.read(self.B)
        return b


class Mem:
    def __init__(self, buf):
        self.buf, self.size = buf, len(buf)

    def read(self, off, n):
        if off < 0 or off >= self.size or n <= 0:
            return b''
        return self.buf[off:off + n]


# ---------------------------------------------------------------- TIFF / EXIF

class Tiff:
    def __init__(self, src, base, e):
        self.src, self.base, self.e, self.ifds = src, base, e, []

    def find(self, tag):
        for _, tags in self.ifds:
            if tag in tags:
                return tags[tag]
        return None

    def val(self, ent, maxb=4096):
        typ, cnt, sz, inl, off = ent
        b = inl if inl is not None else self.src.read(self.base + off, min(sz, maxb))
        if typ == 2:
            return b.split(b'\0', 1)[0].decode('utf-8', 'replace').strip()
        if typ in (5, 10):
            n = min(cnt, len(b) // 8, 1024)
            raw = struct.unpack_from(f'{self.e}{2 * n}{"I" if typ == 5 else "i"}', b)
            vals = [raw[i] / raw[i + 1] if raw[i + 1] else 0 for i in range(0, 2 * n, 2)]
        else:
            size = TSIZE[typ] if typ < len(TSIZE) else 1
            code = TCODE.get(typ, 'B')
            n = min(cnt, len(b) // size, 1024)
            vals = list(struct.unpack_from(f'{self.e}{n}{code}', b)) if n else []
        if cnt == 1:
            return vals[0] if vals else None
        return vals


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def parse_tiff(src, base):
    h = src.read(base, 8)
    if len(h) < 8 or h[:2] not in (b'II', b'MM'):
        return None
    e = '<' if h[:2] == b'II' else '>'
    t = Tiff(src, base, e)
    seen = set()

    def walk(off, kind, follow):
        if not off or off in seen or len(seen) > 48 or base + off >= src.size:
            return
        seen.add(off)
        cb = src.read(base + off, 2)
        if len(cb) < 2:
            return
        n = struct.unpack(e + 'H', cb)[0]
        if not n or n > 1024:
            return
        eb = src.read(base + off + 2, n * 12 + 4)
        if len(eb) < n * 12:
            return
        tags = {}
        for i in range(n):
            tag, typ, cnt = struct.unpack_from(e + 'HHI', eb, i * 12)
            sz = (TSIZE[typ] if typ < len(TSIZE) else 1) * cnt
            if sz <= 4:
                tags[tag] = (typ, cnt, sz, eb[i * 12 + 8:i * 12 + 12], -1)
            else:
                tags[tag] = (typ, cnt, sz, None, struct.unpack_from(e + 'I', eb, i * 12 + 8)[0])
        t.ifds.append((kind, tags))
        nxt = struct.unpack_from(e + 'I', eb, n * 12)[0] if len(eb) >= n * 12 + 4 else 0
        if 0x14A in tags:
            for o in _as_list(t.val(tags[0x14A])):
                walk(o, 'sub', False)
        if 0x8769 in tags:
            walk(t.val(tags[0x8769]), 'exif', False)
        if follow and nxt:
            walk(nxt, 'ifd', True)

    walk(struct.unpack(e + 'I', h[4:8])[0], 'ifd0', True)
    return t


EXIF_TAGS = [('make', 0x10F), ('model', 0x110), ('date', 0x9003), ('subsec', 0x9291),
             ('exposure', 0x829A), ('fnumber', 0x829D), ('iso', 0x8827), ('focal', 0x920A),
             ('lens', 0xA434), ('artist', 0x13B), ('copyright', 0x8298), ('pw', 0xA002), ('ph', 0xA003)]


def absorb_tiff(t, a: Analysis):
    ex = a.exif
    if not a._orient_set:
        ent = t.find(0x112)
        o = t.val(ent) if ent else None
        if isinstance(o, int) and 1 <= o <= 8:
            a.orient, a._orient_set = o, True
    for key, tag in EXIF_TAGS:
        if ex.get(key) in (None, ''):
            ent = t.find(tag)
            if ent:
                v = t.val(ent)
                if isinstance(v, list):
                    v = v[0] if v else None
                if v not in (None, ''):
                    ex[key] = v
    if not ex.get('date'):
        ent = t.find(0x132)
        if ent:
            ex['date'] = t.val(ent)
    for _, tags in t.ifds:
        jo, jl = tags.get(0x201), tags.get(0x202)
        if jo and jl:
            o, n = t.val(jo), t.val(jl)
            if isinstance(o, int) and isinstance(n, int):
                a.cands.append(Cand(t.base + o, n))
        comp = t.val(tags[0x103]) if 0x103 in tags else 0
        so, sc = tags.get(0x111), tags.get(0x117)
        if comp in (6, 7) and so and sc and so[1] == 1:
            a.cands.append(Cand(t.base + t.val(so), t.val(sc)))
        jr = tags.get(0x2E)                       # Panasonic JpgFromRaw
        if jr and jr[4] > 0:
            a.cands.append(Cand(t.base + jr[4], jr[1]))
        xp = tags.get(0x2BC)                      # XMP packet (DNG etc.)
        if xp and a.xmp is None and xp[4] > 0 and xp[1] < 2_000_000:
            a.xmp = t.src.read(t.base + xp[4], xp[1]).decode('utf-8', 'replace')


# ---------------------------------------------------------------------- JPEG

@dataclass
class JpegInfo:
    w: int = 0
    h: int = 0
    sof: int = 0
    sos: int = 0
    apps: list = field(default_factory=list)   # (marker, data_offset, data_length)


def jpeg_info(src, off, length):
    end = min(src.size, off + length)
    if src.read(off, 2) != b'\xff\xd8':
        return None
    info = JpegInfo()
    p = off + 2
    for _ in range(400):
        if p + 4 > end:
            break
        b = src.read(p, 4)
        if len(b) < 4 or b[0] != 0xFF:
            return info if info.sof else None
        m = b[1]
        if m == 0xFF:
            p += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            p += 2
            continue
        if m == 0xD9:
            break
        if m == 0xDA:
            info.sos = p
            break
        seg_len = (b[2] << 8) | b[3]
        if seg_len < 2:
            return None
        if 0xE0 <= m <= 0xEF:
            info.apps.append((m, p + 4, seg_len - 2))
        elif 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            s = src.read(p + 4, 5)
            if len(s) == 5:
                info.sof, info.h, info.w = m, (s[1] << 8) | s[2], (s[3] << 8) | s[4]
        p += 2 + seg_len
    return info


def analyze_jpeg(src, off, length, a: Analysis, is_file):
    info = jpeg_info(src, off, length)
    if not info:
        return
    c = Cand(off, length, whole=is_file)
    c._info = info
    a.cands.append(c)
    for m, d, n in info.apps:
        if m == 0xE1:
            hd = src.read(d, 29)
            if hd[:4] == b'Exif':
                t = parse_tiff(src, d + 6)
                if t:
                    absorb_tiff(t, a)
            elif is_file and hd == b'http://ns.adobe.com/xap/1.0/\0':
                a.xmp = src.read(d + 29, n - 29).decode('utf-8', 'replace')
        elif m == 0xE2 and src.read(d, 4) == b'MPF\0':
            absorb_mpf(src, d + 4, a)
        elif m == 0xED and is_file and src.read(d, 14) == b'Photoshop 3.0\0':
            a.app13 = src.read(d + 14, n - 14)


def absorb_mpf(src, base, a):
    """Multi-Picture Format: camera JPEGs often carry a ~2 MP preview here."""
    t = parse_tiff(src, base)
    ent = t and t.find(0xB002)
    if not ent:
        return
    b = ent[3] if ent[3] is not None else src.read(base + ent[4], min(ent[2], 1600))
    for i in range(1, len(b) // 16):
        size, off = struct.unpack_from(t.e + 'II', b, i * 16 + 4)
        if size and off:
            a.cands.append(Cand(base + off, size))


# ---------------------------------------------------------------------- CR3

def boxes(src, start, end):
    p = start
    for _ in range(512):
        if p + 8 > end:
            return
        h = src.read(p, 16)
        if len(h) < 8:
            return
        size, typ, hdr = struct.unpack('>I', h[:4])[0], h[4:8], 8
        if size == 1 and len(h) >= 16:
            size, hdr = struct.unpack('>Q', h[8:16])[0], 16
        elif size == 0:
            size = end - p
        if size < hdr:
            return
        yield typ, p + hdr, min(end, p + size)
        p += size


def _box_path(src, start, end, names):
    rng = (start, end)
    for nm in names:
        for typ, d, e in boxes(src, *rng):
            if typ == nm:
                rng = (d, e)
                break
        else:
            return None
    return rng


def analyze_cr3(src, a: Analysis):
    trak = 0
    for typ, d, e in boxes(src, 0, src.size):
        if typ == b'moov':
            for t2, d2, e2 in boxes(src, d, e):
                if t2 == b'uuid' and src.read(d2, 16) == CANON_UUID:
                    for t3, d3, e3 in boxes(src, d2 + 16, e2):
                        if t3 in (b'CMT1', b'CMT2'):
                            t = parse_tiff(src, d3)
                            if t:
                                absorb_tiff(t, a)
                        elif t3 == b'THMB':
                            k = src.read(d3, 48).find(b'\xff\xd8\xff')
                            if k >= 0:
                                a.cands.append(Cand(d3 + k, e3 - d3 - k))
                elif t2 == b'trak':
                    trak += 1
                    if trak != 1:
                        continue
                    stbl = _box_path(src, d2, e2, [b'mdia', b'minf', b'stbl'])
                    if not stbl:
                        continue
                    size = off = 0
                    for t4, d4, _ in boxes(src, *stbl):
                        b = src.read(d4, 20)
                        if t4 == b'stsz' and len(b) >= 16:
                            size = struct.unpack_from('>I', b, 4)[0] or struct.unpack_from('>I', b, 12)[0]
                        elif t4 == b'co64' and len(b) >= 16:
                            off = struct.unpack_from('>Q', b, 8)[0]
                        elif t4 == b'stco' and len(b) >= 12:
                            off = struct.unpack_from('>I', b, 8)[0]
                    if size and off:
                        a.cands.append(Cand(off, size))
        elif typ == b'uuid' and e - d < 16_000_000:
            uid = src.read(d, 16)
            if uid == CR3_XMP_UUID:
                a.xmp = src.read(d + 16, e - d - 16).decode('utf-8', 'replace')
                continue
            b = src.read(d, 256)
            i = b.find(b'PRVW')
            if i >= 4:
                box_end = d + i - 4 + struct.unpack_from('>I', b, i - 4)[0]
                k = b.find(b'\xff\xd8\xff', i)
                if k >= 0:
                    a.cands.append(Cand(d + k, box_end - (d + k)))
        elif typ == b'mdat':
            break


# ------------------------------------------------------------- brute force

def scan_jpegs(f, size, a: Analysis):
    """Fallback for formats without a parser: find embedded JPEGs by markers."""
    f.seek(0)
    buf = f.read(min(size, 150_000_000))
    m = Mem(buf)
    i = buf.find(b'\xff\xd8\xff')
    while i >= 0:
        info = jpeg_info(m, i, len(buf) - i)
        nxt = i + 3
        if info and info.sos and info.sof in DECODABLE_SOF and info.w >= 64:
            j = buf.find(b'\xff\xd9', info.sos + 2)
            if j < 0:
                j = len(buf) - 2
            c = Cand(i, j + 2 - i)
            c._info = info
            a.cands.append(c)
            nxt = j + 2
        i = buf.find(b'\xff\xd8\xff', nxt)


# ------------------------------------------------------------------- public

RASTER_MAGIC = (b'\x89PNG', b'GIF8', b'BM')


def analyze(path) -> Analysis:
    a = Analysis()
    with open(path, 'rb') as f:
        size = os.fstat(f.fileno()).st_size
        src = Src(f, size)
        head = src.read(0, 96)
        if head[:2] == b'\xff\xd8':
            a.format = 'jpeg'
            analyze_jpeg(src, 0, size, a, True)
        elif head.startswith(b'FUJIFILMCCD-RAW'):
            a.format = 'raf'
            off, n = struct.unpack_from('>II', head, 84)
            analyze_jpeg(src, off, n, a, False)
        elif head[4:8] == b'ftyp':
            a.format = 'cr3' if head[8:12] == b'crx ' else 'bmff'
            if a.format == 'cr3':
                analyze_cr3(src, a)
        elif head[:2] in (b'II', b'MM'):
            a.format = 'tiff'
            t = parse_tiff(src, 0)
            if t:
                absorb_tiff(t, a)
        elif head.startswith(RASTER_MAGIC) or (head[:4] == b'RIFF' and head[8:12] == b'WEBP'):
            a.format = 'raster'

        cands, seen = [], set()

        def measure(lst):
            for c in lst:
                if c.length <= 0 or c.off < 0 or c.off >= size or c.off in seen:
                    continue
                seen.add(c.off)
                info = getattr(c, '_info', None) or jpeg_info(src, c.off, c.length)
                if info and info.w and info.h and info.sof in DECODABLE_SOF:
                    cands.append(Cand(c.off, min(c.length, size - c.off), info.w, info.h, c.whole))

        measure(a.cands)
        longest = max((max(c.w, c.h) for c in cands), default=0)
        if a.format not in ('raster', 'bmff', 'jpeg') and longest < 1000:
            a.cands = []
            scan_jpegs(f, size, a)
            measure(a.cands)

    cands.sort(key=lambda c: c.w * c.h)
    a.cands = cands
    if cands:
        w, h = cands[-1].w, cands[-1].h
    else:
        w, h = int(a.exif.get('pw') or 0), int(a.exif.get('ph') or 0)
    if a.orient >= 5:
        w, h = h, w
    a.ow, a.oh = w, h
    return a


def read_cand(path, c: Cand) -> bytes:
    with open(path, 'rb') as f:
        if c.whole:
            return f.read()
        f.seek(c.off)
        return f.read(c.length)
