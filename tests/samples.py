"""Generate small synthetic camera files for tests and demos.

    python tests/samples.py <folder>      # writes a demo "memory card"

Each image has a red square in its *stored* top-left corner, so tests can
check that orientation is applied correctly.
"""
import os
import random
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

CANON_UUID = bytes.fromhex('85c0b687820f11e08111f4ce462b6a48')
PRVW_UUID = bytes.fromhex('eaf42b5e1c984b88b9fbb7dc406e4d16')


def jpeg(w, h, label='', hue=200, quality=88):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor.fromHsv(hue % 360, 90, 140))
    p = QPainter(img)
    for i in range(0, w, max(8, w // 12)):
        p.fillRect(i, 0, max(2, w // 60), h, QColor.fromHsv((hue + 30) % 360, 110, 170))
    p.fillRect(QRect(0, 0, max(8, w // 6), max(8, h // 6)), QColor(255, 0, 0))
    if label:
        f = QFont()
        f.setPixelSize(max(10, h // 6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, label)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'JPG', quality)
    return bytes(ba.data())


def build_tiff(ifds, blobs=None, le=True, magic=42):
    """ifds: ordered list of (name, tags, next_name). tags: {tag: (type, value)}.
    value may be ('ifd', name) / ('blob', name) / ('blobsize', name) or a list of them."""
    E = '<' if le else '>'
    blobs = blobs or {}

    def encode(typ, v, res):
        vals = v if isinstance(v, list) else [v]
        vals = [res(x) if isinstance(x, tuple) and x and x[0] in ('ifd', 'blob', 'blobsize') else x for x in vals]
        if typ == 2:
            b = vals[0].encode() + b'\0'
            return b, len(b)
        if typ == 7:
            return vals[0], len(vals[0])
        if typ == 5:
            return b''.join(struct.pack(E + 'II', n, d) for n, d in vals), len(vals)
        code = {3: 'H', 4: 'I', 13: 'I'}[typ]
        return struct.pack(E + f'{len(vals)}{code}', *vals), len(vals)

    def layout(res):
        offs, pos = {}, 8
        for name, tags, _ in ifds:
            offs[name] = pos
            pos += 2 + 12 * len(tags) + 4
            for t, (typ, v) in tags.items():
                b, _ = encode(typ, v, res)
                if len(b) > 4:
                    pos += len(b) + (len(b) & 1)
        boffs = {}
        for name, data in blobs.items():
            boffs[name] = pos
            pos += len(data)
        return offs, boffs

    zero = lambda x: 0 if x[0] != 'blobsize' else len(blobs[x[1]])
    offs, boffs = layout(zero)
    res = lambda x: offs[x[1]] if x[0] == 'ifd' else boffs[x[1]] if x[0] == 'blob' else len(blobs[x[1]])
    out = bytearray(struct.pack(E + '2sHI', b'II' if le else b'MM', magic, 8))
    for name, tags, nxt in ifds:
        assert len(out) == offs[name]
        data_pos = offs[name] + 2 + 12 * len(tags) + 4
        entries, data = b'', b''
        for t in sorted(tags):
            typ, v = tags[t]
            b, cnt = encode(typ, v, res)
            if len(b) <= 4:
                val = b + b'\0' * (4 - len(b))
            else:
                val = struct.pack(E + 'I', data_pos + len(data))
                data += b + (b'\0' if len(b) & 1 else b'')
            entries += struct.pack(E + 'HHI', t, typ, cnt) + val
        out += struct.pack(E + 'H', len(tags)) + entries + struct.pack(E + 'I', offs[nxt] if nxt else 0) + data
    for name, data in blobs.items():
        assert len(out) == boffs[name]
        out += data
    return bytes(out)


def exif_tags(date, model='Test Cam R1', orient=1):
    ifd0 = {0x10F: (2, 'TestMaker'), 0x110: (2, model), 0x112: (3, orient), 0x8769: (4, ('ifd', 'exif'))}
    exif = {0x9003: (2, date), 0x9291: (2, '42'), 0x829A: (5, (1, 1000)), 0x829D: (5, (28, 10)),
            0x8827: (3, 3200), 0x920A: (5, (200, 1))}
    return ifd0, exif


def jpeg_with_exif(w, h, date, orient=1, label='', hue=200, thumb=True):
    main = jpeg(w, h, label, hue)
    ifd0, exif = exif_tags(date, orient=orient)
    ifds = [('ifd0', ifd0, 'ifd1' if thumb else None), ('exif', exif, None)]
    blobs = {}
    if thumb:
        # 4:3 thumbnail with black bars, like real Canon/Nikon EXIF thumbnails
        tw, th = 160, 120
        img = QImage.fromData(jpeg(w, h, label, hue)).scaled(160, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QImage(tw, th, QImage.Format_RGB32)
        canvas.fill(QColor(0, 0, 0))
        p = QPainter(canvas)
        p.drawImage((tw - img.width()) // 2, (th - img.height()) // 2, img)
        p.end()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        canvas.save(buf, 'JPG', 80)
        blobs['thumb'] = bytes(ba.data())
        ifds.append(('ifd1', {0x103: (3, 6), 0x201: (4, ('blob', 'thumb')), 0x202: (4, ('blobsize', 'thumb'))}, None))
    tiff = build_tiff(ifds, blobs)
    app1 = b'Exif\0\0' + tiff
    seg = b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1
    return main[:2] + seg + main[2:]


def fake_nef(w, h, date, orient=6, label='NEF', hue=20):
    big = jpeg(w, h, label, hue)
    small = jpeg(w // 4, h // 4, label, hue)
    raw = random.Random(1).randbytes(20000)
    ifd0, exif = exif_tags(date, 'Fake Z9', orient)
    ifd0[0x14A] = (4, [('ifd', 'sub1'), ('ifd', 'sub2')])
    ifd0[0x201] = (4, ('blob', 'small'))
    ifd0[0x202] = (4, ('blobsize', 'small'))
    sub1 = {0xFE: (4, 1), 0x103: (3, 6), 0x201: (4, ('blob', 'big')), 0x202: (4, ('blobsize', 'big'))}
    sub2 = {0xFE: (4, 0), 0x103: (3, 34713), 0x111: (4, ('blob', 'raw')), 0x117: (4, ('blobsize', 'raw'))}
    return build_tiff([('ifd0', ifd0, None), ('exif', exif, None), ('sub1', sub1, None), ('sub2', sub2, None)],
                      {'small': small, 'big': big, 'raw': raw})


def box(t, payload):
    return struct.pack('>I', 8 + len(payload)) + t + payload


def fake_cr3(w, h, date, orient=8, label='CR3', hue=280):
    big = jpeg(w, h, label, hue)
    prv = jpeg(w // 2, h // 2, label, hue)
    th = jpeg(160, 107, label, hue)
    cmt1 = box(b'CMT1', build_tiff([('ifd0', {0x10F: (2, 'Canon'), 0x110: (2, 'Fake R3'), 0x112: (3, orient)}, None)]))
    cmt2 = box(b'CMT2', build_tiff([('ifd0', {0x9003: (2, date), 0x8827: (3, 6400), 0x829A: (5, (1, 2000))}, None)]))
    thmb = box(b'THMB', b'\0\0\0\0' + struct.pack('>HHI', 160, 107, len(th)) + b'\0\0\0\0' + th)
    ftyp = box(b'ftyp', b'crx \0\0\0\x01crx isom')
    prvw = box(b'uuid', PRVW_UUID + b'\0' * 8 + box(b'PRVW', b'\0' * 6 + struct.pack('>HHI', w // 2, h // 2, len(prv)) + prv))

    def moov(off):
        stsz = box(b'stsz', b'\0' * 4 + struct.pack('>III', 0, 1, len(big)))
        co64 = box(b'co64', b'\0' * 4 + struct.pack('>IQ', 1, off))
        trak = box(b'trak', box(b'mdia', box(b'minf', box(b'stbl', stsz + co64))))
        return box(b'moov', box(b'uuid', CANON_UUID + cmt1 + cmt2 + thmb) + trak)

    off = len(ftyp) + len(moov(0)) + len(prvw) + 8
    return ftyp + moov(off) + prvw + box(b'mdat', big)


def fake_orf(w, h, date, label='ORF', hue=120):
    """No parsable preview pointers: exercises the marker-scanning fallback."""
    big = jpeg(w, h, label, hue)
    head = build_tiff([('ifd0', {0x10F: (2, 'OM'), 0x110: (2, 'Fake OM-1'), 0x112: (3, 1)}, None)], magic=0x4F52)
    junk = random.Random(2).randbytes(5000).replace(b'\xff', b'\x00')
    return head + junk + big + junk


def write_card(folder, n_jpeg=8):
    """A small fake memory card: DCIM/100TEST with mixed formats + a RAW+JPEG pair."""
    d = os.path.join(folder, 'DCIM', '100TEST')
    os.makedirs(d, exist_ok=True)
    files = {}
    for i in range(n_jpeg):
        o = 6 if i == 2 else 1
        files[f'IMG_{i + 1:04d}.JPG'] = jpeg_with_exif(900, 600, f'2026:10:21 19:30:{i:02d}', o, f'#{i + 1}', 30 * i)
    files['DSC_0100.NEF'] = fake_nef(1200, 800, '2026:10:21 19:31:00')
    files['IMG_0200.CR3'] = fake_cr3(1200, 800, '2026:10:21 19:31:10')
    files['P_0300.ORF'] = fake_orf(1200, 800, '2026:10:21 19:31:20')
    files['DSC_0101.NEF'] = fake_nef(1200, 800, '2026:10:21 19:31:30', orient=1, label='PAIR')
    files['DSC_0101.JPG'] = jpeg_with_exif(1200, 800, '2026:10:21 19:31:30', 1, 'PAIR', 10)
    for name, data in files.items():
        with open(os.path.join(d, name), 'wb') as fh:
            fh.write(data)
    return d


if __name__ == '__main__':
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1] + ['-platform', 'offscreen'])
    out = sys.argv[1] if len(sys.argv) > 1 else 'sample_card'
    print(write_card(out, 24))
