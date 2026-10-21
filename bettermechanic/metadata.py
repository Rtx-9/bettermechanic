"""Read, merge and write photo metadata: XMP (sidecar or embedded) and IPTC-IIM.

Existing XMP is merged, not replaced, so Lightroom/Capture One edits that live
in the same sidecar survive. JPEGs get XMP + IPTC-IIM written into their
header; the image data itself is never re-encoded.
"""
from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET

NS = {
    'x': 'adobe:ns:meta/',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'photoshop': 'http://ns.adobe.com/photoshop/1.0/',
    'Iptc4xmpCore': 'http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/',
    'Iptc4xmpExt': 'http://iptc.org/std/Iptc4xmpExt/2008-02-29/',
    'photomechanic': 'http://ns.camerabits.com/photomechanic/1.0/',
    'xmpNote': 'http://ns.adobe.com/xmp/note/',
    'bettermechanic': 'http://ns.bettermechanic.app/1.0/',
}
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
RDF = '{%s}' % NS['rdf']

# key, prefix, property, kind  (kind: text|int|bool|alt|bag|seq1)
FIELDS = [
    ('rating', 'xmp', 'Rating', 'int'),
    ('label', 'xmp', 'Label', 'text'),
    ('tagged', 'photomechanic', 'Tagged', 'bool'),
    ('title', 'dc', 'title', 'alt'),
    ('caption', 'dc', 'description', 'alt'),
    ('keywords', 'dc', 'subject', 'bag'),
    ('byline', 'dc', 'creator', 'seq1'),
    ('copyright', 'dc', 'rights', 'alt'),
    ('headline', 'photoshop', 'Headline', 'text'),
    ('credit', 'photoshop', 'Credit', 'text'),
    ('source', 'photoshop', 'Source', 'text'),
    ('instructions', 'photoshop', 'Instructions', 'text'),
    ('city', 'photoshop', 'City', 'text'),
    ('state', 'photoshop', 'State', 'text'),
    ('country', 'photoshop', 'Country', 'text'),
    ('bylineTitle', 'photoshop', 'AuthorsPosition', 'text'),
    ('jobId', 'photoshop', 'TransmissionReference', 'text'),
    ('sublocation', 'Iptc4xmpCore', 'Location', 'text'),
    ('countryCode', 'Iptc4xmpCore', 'CountryCode', 'text'),
    ('people', 'Iptc4xmpExt', 'PersonInImage', 'bag'),
    ('event', 'Iptc4xmpExt', 'Event', 'alt'),
]
TEXT_KEYS = ['title', 'headline', 'caption', 'event', 'byline', 'bylineTitle', 'credit', 'source',
             'copyright', 'instructions', 'city', 'sublocation', 'state', 'country', 'countryCode', 'jobId']

IIM = {'title': 5, 'keywords': 25, 'instructions': 40, 'byline': 80, 'bylineTitle': 85, 'city': 90,
       'sublocation': 92, 'state': 95, 'countryCode': 100, 'country': 101, 'jobId': 103,
       'headline': 105, 'credit': 110, 'source': 115, 'copyright': 116, 'caption': 120}
IIM_BY_DS = {v: k for k, v in IIM.items()}

XMP_HDR = b'http://ns.adobe.com/xap/1.0/\0'
XMP_EXT_HDR = b'http://ns.adobe.com/xmp/extension/\0'
PS_HDR = b'Photoshop 3.0\0'


def blank():
    m = {k: '' for k in TEXT_KEYS}
    m.update(rating=0, label='', tagged=False, people=[], keywords=[])
    return m


def copy_meta(m):
    c = dict(m)
    c['people'] = list(m.get('people', []))
    c['keywords'] = list(m.get('keywords', []))
    return c


def uniq(seq):
    out, seen = [], set()
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ------------------------------------------------------------------- XMP

for _p, _u in NS.items():
    ET.register_namespace(_p, _u)


def _load(text):
    """Parse an XMP packet; returns (root, namespace declarations) or (None, {})."""
    if not text:
        return None, {}
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    text = text.replace('\0', '').lstrip('﻿')
    i = text.find('<')
    if i < 0:
        return None, {}
    data = text[i:].encode('utf-8')
    decls = {}
    try:
        it = ET.iterparse(io.BytesIO(data), events=('start-ns',))
        for _, (pfx, uri) in it:
            decls.setdefault(pfx, uri)
        return it.root, decls
    except ET.ParseError:
        return None, {}


def _read_prop(desc, uri, prop, kind):
    attr = '{%s}%s' % (uri, prop)
    if attr in desc.attrib:
        return desc.attrib[attr]
    for c in desc:
        if c.tag == attr:
            lis = list(c.iter(RDF + 'li'))
            if not lis:
                return (c.text or '').strip()
            if kind == 'alt':
                for li in lis:
                    if li.get(XML_LANG) == 'x-default':
                        return (li.text or '').strip()
                return (lis[0].text or '').strip()
            return [(li.text or '').strip() for li in lis if (li.text or '').strip()]
    return None


def _conv(kind, v):
    if kind == 'int':
        try:
            return max(-1, min(5, round(float(v))))
        except (TypeError, ValueError):
            return 0
    if kind == 'bool':
        return str(v).strip().lower() in ('true', '1', 'yes')
    if kind == 'bag':
        items = v if isinstance(v, list) else re.split(r'[;,]', str(v))
        return [s.strip() for s in items if s.strip()]
    return ', '.join(v) if isinstance(v, list) else str(v)


# ------------------------------------------------- Lightroom mark for tagged photos
#
# Lightroom doesn't read Photo Mechanic's "Tagged" flag, so tagged photos can also get something it does read:
# a colour label, a star rating or a keyword. The mark is added only when files are written (never stored in
# the app's own metadata), and the file remembers what it replaced, so untagging removes it and reading the
# file back doesn't turn it into a "real" label / rating / keyword.

MARK_PROPS = ('LightroomMark', 'MarkValue', 'MarkBefore')
MARK_CHOICES = [('none', 'Nothing (Photo Mechanic tag only)')] + \
    [(f'label:{c}', f'{c} color label') for c in ('Green', 'Red', 'Yellow', 'Blue', 'Purple')] + \
    [(f'stars:{n}', f'{n} star{"s" if n > 1 else ""} (if rated lower)') for n in range(1, 6)] + \
    [('keyword:Tagged', 'Keyword “Tagged”')]


def parse_mark(spec):
    """'label:Green' / 'stars:1' / 'keyword:Tagged' -> (mode, value), or None."""
    if not spec or spec == 'none' or ':' not in str(spec):
        return None
    mode, value = str(spec).split(':', 1)
    if mode == 'stars':
        try:
            return mode, max(1, min(5, int(value)))
        except ValueError:
            return None
    return (mode, value) if mode in ('label', 'keyword') and value else None


def apply_mark(meta, spec):
    """Meta as written for Lightroom, plus the mark record ({prop: text}) or None."""
    mark = parse_mark(spec)
    if not mark or not meta.get('tagged'):
        return meta, None
    mode, value = mark
    out = dict(meta)
    if mode == 'label' and not meta.get('label'):
        out['label'] = value
        before = ''
    elif mode == 'stars' and 0 <= int(meta.get('rating') or 0) < value:
        out['rating'] = value
        before = str(int(meta.get('rating') or 0))
    elif mode == 'keyword' and value not in (meta.get('keywords') or []):
        out['keywords'] = list(meta.get('keywords') or []) + [value]
        before = ''
    else:
        return meta, None                      # the user's own value wins: nothing to add
    return out, {'LightroomMark': mode, 'MarkValue': str(value), 'MarkBefore': before}


def _undo_mark(out, descs):
    bm = '{%s}' % NS['bettermechanic']
    for d in descs:
        mode = d.attrib.get(bm + 'LightroomMark')
        if not mode:
            continue
        value, before = d.attrib.get(bm + 'MarkValue', ''), d.attrib.get(bm + 'MarkBefore', '')
        if mode == 'label' and out.get('label') == value:
            out['label'] = before
        elif mode == 'stars' and str(out.get('rating')) == value:
            out['rating'] = int(before) if before.lstrip('-').isdigit() else 0
        elif mode == 'keyword' and 'keywords' in out:
            out['keywords'] = [k for k in out['keywords'] if k != value]
        return


def parse_xmp(text):
    """Return only the fields present in the packet."""
    root, _ = _load(text)
    out = {}
    if root is None:
        return out
    descs = list(root.iter(RDF + 'Description'))
    for key, p, prop, kind in FIELDS:
        for d in descs:
            v = _read_prop(d, NS[p], prop, kind)
            if v is not None:
                out[key] = _conv(kind, v)
                break
    _undo_mark(out, descs)
    return out


def build_xmp(meta, existing=None, people_to_keywords=True, lr_mark=None):
    root, decls = _load(existing)
    rdf = None if root is None else (root if root.tag == RDF + 'RDF' else root.find('.//' + RDF + 'RDF'))
    if rdf is None:
        root = ET.Element('{adobe:ns:meta/}xmpmeta', {'{adobe:ns:meta/}xmptk': 'BetterMechanic'})
        rdf = ET.SubElement(root, RDF + 'RDF')
    for pfx, uri in decls.items():
        if pfx and not re.fullmatch(r'ns\d+', pfx) and uri not in NS.values():
            try:
                ET.register_namespace(pfx, uri)
            except ValueError:
                pass
    descs = list(rdf.iter(RDF + 'Description'))
    if not descs:
        descs = [ET.SubElement(rdf, RDF + 'Description', {RDF + 'about': ''})]
    ours = {'{%s}%s' % (NS[p], prop) for _, p, prop, _ in FIELDS}
    ours.add('{%s}HasExtendedXMP' % NS['xmpNote'])
    ours.update('{%s}%s' % (NS['bettermechanic'], p) for p in MARK_PROPS)
    for d in descs:
        for a in [a for a in d.attrib if a in ours]:
            del d.attrib[a]
        for c in [c for c in d if c.tag in ours]:
            d.remove(c)
    desc = descs[0]
    meta, mark = apply_mark(meta, lr_mark)
    if mark:
        for prop, text in mark.items():
            desc.set('{%s}%s' % (NS['bettermechanic'], prop), text)

    values = dict(meta)
    kws = list(meta.get('keywords') or [])
    if people_to_keywords:
        kws += meta.get('people') or []
    values['keywords'] = uniq(kws)

    def container(parent, typ, vals, lang=False):
        c = ET.SubElement(parent, RDF + typ)
        for v in vals:
            li = ET.SubElement(c, RDF + 'li')
            if lang:
                li.set(XML_LANG, 'x-default')
            li.text = v

    for key, p, prop, kind in FIELDS:
        v = values.get(key)
        if not v:
            continue
        e = ET.SubElement(desc, '{%s}%s' % (NS[p], prop))
        if kind == 'int':
            e.text = str(int(v))
        elif kind == 'bool':
            e.text = 'True'
        elif kind == 'bag':
            container(e, 'Bag', v)
        elif kind == 'alt':
            container(e, 'Alt', [v], True)
        elif kind == 'seq1':
            container(e, 'Seq', [v])
        else:
            e.text = v
    body = ET.tostring(root, encoding='unicode')
    return '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + body + '\n<?xpacket end="w"?>'


# ------------------------------------------------------------- IPTC-IIM

def parse_iim(b):
    out, kws, recs, p, utf = {}, [], [], 0, False
    while p + 5 <= len(b) and b[p] == 0x1C:
        rec, ds, n = b[p + 1], b[p + 2], (b[p + 3] << 8) | b[p + 4]
        p += 5
        if n & 0x8000:
            k = n & 0x7FFF
            n = int.from_bytes(b[p:p + k], 'big')
            p += k
        recs.append((rec, ds, b[p:p + n]))
        p += n
    for rec, ds, d in recs:
        if rec == 1 and ds == 90 and d[:3] == b'\x1b%G':
            utf = True
    for rec, ds, d in recs:
        key = IIM_BY_DS.get(ds) if rec == 2 else None
        if not key:
            continue
        s = d.decode('utf-8' if utf else 'cp1252', 'replace').rstrip('\0').strip()
        if not s:
            continue
        if key == 'keywords':
            kws.append(s)
        else:
            out.setdefault(key, s)
    if kws:
        out['keywords'] = kws
    return out


def build_iim(meta, people_to_keywords=True):
    parts = []

    def ds(rec, n, data):
        data = data[:32767]
        parts.append(bytes([0x1C, rec, n, len(data) >> 8, len(data) & 255]) + data)

    ds(1, 90, b'\x1b%G')
    ds(2, 0, b'\x00\x04')
    kws = list(meta.get('keywords') or [])
    if people_to_keywords:
        kws += meta.get('people') or []
    for key, n in sorted(IIM.items(), key=lambda kv: kv[1]):
        if key == 'keywords':
            for k in uniq(kws):
                ds(2, n, k.encode('utf-8'))
        elif meta.get(key):
            ds(2, n, str(meta[key]).encode('utf-8'))
    return b''.join(parts)


def _parse_8bim(pl):
    res, p = [], 0
    while p + 12 <= len(pl) and pl[p:p + 4] == b'8BIM':
        rid = (pl[p + 4] << 8) | pl[p + 5]
        nl = pl[p + 6]
        name_len = 1 + nl + ((1 + nl) & 1)
        q = p + 6 + name_len
        if q + 4 > len(pl):
            break
        size = struct.unpack_from('>I', pl, q)[0]
        res.append((rid, pl[p + 6:q], pl[q + 4:q + 4 + size]))
        p = q + 4 + size + (size & 1)
    return res


def parse_app13(pl):
    for rid, _, data in _parse_8bim(pl or b''):
        if rid == 0x0404:
            return parse_iim(data)
    return {}


def build_app13(meta, old=None, people_to_keywords=True):
    keep = [r for r in _parse_8bim(old or b'') if r[0] not in (0x0404, 0x0425)]
    keep.append((0x0404, b'\0\0', build_iim(meta, people_to_keywords)))
    out = bytearray()
    for rid, name, data in keep:
        out += b'8BIM' + struct.pack('>H', rid) + name + struct.pack('>I', len(data)) + data
        if len(data) & 1:
            out += b'\0'
    return bytes(out)


# ------------------------------------------------------------------ JPEG

def _seg(marker, payload):
    return bytes([0xFF, marker]) + struct.pack('>H', len(payload) + 2) + payload


def rewrite_jpeg(data: bytes, meta, people_to_keywords=True, write_iim=True, lr_mark=None):
    """Return JPEG bytes with fresh XMP (+ IPTC) segments. Pixels are untouched."""
    if data[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG file')
    segs, p, n = [], 2, len(data)
    while p + 4 <= n:
        if data[p] != 0xFF:
            raise ValueError('corrupt JPEG header')
        m = data[p + 1]
        if m == 0xFF:
            p += 1
            continue
        if m in (0xDA, 0xD9):
            break
        if m == 0x01 or 0xD0 <= m <= 0xD7:
            segs.append((m, p, p + 2))
            p += 2
            continue
        seg_len = (data[p + 2] << 8) | data[p + 3]
        segs.append((m, p, p + 2 + seg_len))
        p += 2 + seg_len
    tail = data[p:]

    xmp_old = app13_old = None
    keep = []
    for m, s, e in segs:
        body = data[s + 4:e]
        if m == 0xE1 and body.startswith(XMP_HDR):
            xmp_old = body[len(XMP_HDR):].decode('utf-8', 'replace')
        elif m == 0xE1 and body.startswith(XMP_EXT_HDR):
            continue
        elif m == 0xED and body.startswith(PS_HDR):
            app13_old = body[len(PS_HDR):]
        else:
            keep.append((m, data[s:e]))

    new = []
    xmp = build_xmp(meta, xmp_old, people_to_keywords, lr_mark).encode('utf-8')
    meta = apply_mark(meta, lr_mark)[0]          # IPTC-IIM gets the same keywords
    if len(XMP_HDR) + len(xmp) + 2 <= 65535:
        new.append((0xE1, _seg(0xE1, XMP_HDR + xmp)))
    if write_iim:
        pl = build_app13(meta, app13_old, people_to_keywords)
        if len(PS_HDR) + len(pl) + 2 <= 65535:
            new.append((0xED, _seg(0xED, PS_HDR + pl)))
    elif app13_old is not None:
        new.append((0xED, _seg(0xED, PS_HDR + app13_old)))

    k = 0
    while k < len(keep) and keep[k][0] in (0xE0, 0xE1):
        k += 1
    out = [b'\xff\xd8'] + [b for _, b in keep[:k]] + [b for _, b in new] + [b for _, b in keep[k:]] + [tail]
    return b''.join(out)


def read_jpeg_meta(xmp_text, app13):
    """Merge embedded IPTC then XMP (XMP wins)."""
    m = {}
    if app13:
        m.update(parse_app13(app13))
    if xmp_text:
        m.update(parse_xmp(xmp_text))
    return m
