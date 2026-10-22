"""Coaches and other staff from the Liiga clubs' own websites, with their photos.

liiga.fi only lists a head coach, CEO and chairman. The clubs publish their whole staff, but every site is
built differently (tables, photo captions, cards), so instead of one scraper per club this reads any page the
same way: find each text that is a staff role ("Päävalmentaja", "Huoltaja", …), then the smallest part of the
page around it that holds exactly one name: that's the person, and a picture in that part is their photo.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'

# Liiga team slug (the part after ':' in liiga.fi team ids) -> the club's staff page(s)
PAGES = {
    'hifk': ['https://hifk.fi/joukkue/'],
    'hpk': ['https://hpk.fi/joukkueet/liiga-joukkue/'],
    'ilves': ['https://www.ilves.com/valmennus-johto/'],
    'jokerit': ['https://www.jokerit.fi/joukkue'],
    'jukurit': ['https://jukurit.fi/fi-fi/joukkue/2026-2027/484/'],
    'jyp': ['https://www.jypliiga.fi/joukkue/'],
    'k-espoo': ['https://kiekko-espoo.fi/joukkue/valmennus/'],
    'kalpa': ['https://kalpa.fi/fi-fi/article/pelaajat/pelaajat/22/'],
    'kookoo': ['https://www.kookoo.fi/joukkue/'],
    'kärpät': ['https://www.karpat.fi/joukkueet/liiga'],
    'lukko': ['https://www.raumanlukko.fi/joukkue'],
    'pelicans': ['https://pelicans.fi/fi-fi/article/pelaajat/joukkue-2022-2023/5414/'],
    'saipa': ['https://saipa.fi/joukkue/'],
    'sport': ['https://vaasansport.fi/liiga-joukkue/'],
    'tappara': ['https://www.tappara.fi/joukkue_26-27/'],
    'tps': ['https://hc.tps.fi/joukkue/'],
    'ässät': ['https://assat.com/joukkueet/'],
}

# A role is a short text containing a word that ends like a job title: "Päävalmentaja", "mv-valmentaja",
# "Huoltopäällikkö", "Naprapaatti", "Fysioterapeutti & osteopaatti", ", vastuuvalmentaja" …
ROLE_END = (r'valmentaja|huoltaja|terapeutti|fysio|lääkäri|hieroja|johtaja|päällikkö|analyytikko|paatti|'
            r'praktikko|kuljettaja|videointi|vastaava|koordinaattori|manager|coach|physio\w*|materiaali\w*')
ROLE_WORD = re.compile(rf'(?i)\w*(?:{ROLE_END})\b')
ROLE_IN = re.compile(rf'(?i)^\s*([\w\- /&]*(?:{ROLE_END})[\w\- /&]*?)\s*[:–-]\s*(.+?)\s*$')
LOWER = "a-zåäöüéèáíóúëïçš'’\\-"
NAME_WORD = rf"[A-ZÅÄÖÜÉ][{LOWER}]+(?:[A-Z][{LOWER}]+)?"              # also McLean, MacEachern
PARTICLE = r'(?:af|von|van|de|der|den|da|di|du|la|le|el|al)'
NAME = re.compile(rf'^{NAME_WORD}(?:[ -](?:{PARTICLE} )?{NAME_WORD}){{1,3}}$')
WORD = re.compile(rf'^{NAME_WORD}$')


def is_role(text):
    t = text.strip(' ,:–-')
    return 0 < len(t) <= 60 and len(t.split()) <= 6 and not re.search(r'\d', t) and bool(ROLE_WORD.search(t))
NOT_NAMES = re.compile(r'(?i)\b(like|tweet|share|jaa|valmennus|staff|joukkue|pelaajat|yhteystiedot|liiga|lue lisää|kausi|sopimus|'
                       r'maalivahdit|puolustajat|hyökkääjät|toimihenkil|urheilujohto|huolto)\b')
HEADING = re.compile(r'(?i)^(valmennus\b.*|valmentajat|toimihenkilöt|huolto\b.*|staff|johto(ryhmä)?|'
                     r'valmennus ja huolto|coaches|coaching staff)$')
HEAD_ROLE = {'valmentajat': 'Valmentaja', 'valmennus': 'Valmentaja', 'coaches': 'Coach', 'huolto': 'Huoltaja'}
SKIP = {'script', 'style', 'noscript', 'svg', 'head', 'template', 'button', 'nav', 'footer', 'header'}
VOID = {'img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'col', 'area', 'base', 'embed', 'param', 'track'}


class Node:
    __slots__ = ('tag', 'attrs', 'kids', 'parent', 'text')

    def __init__(self, tag, attrs=None, parent=None, text=None):
        self.tag, self.attrs, self.parent, self.text, self.kids = tag, dict(attrs or ()), parent, text, []

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node('root')
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if self.skip or tag in SKIP:
            self.skip += tag not in VOID
            return
        n = Node(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= tag in SKIP or self.skip > 1
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        data = data.replace('\u00ad', '').replace('\u200b', '')         # soft hyphens and zero-width spaces: 'Pää\u00advalmentaja'
        if not self.skip and data.strip():
            self.cur.kids.append(Node('#text', parent=self.cur, text=' '.join(data.split())))


def _texts(node):
    return [n for n in node.walk() if n.tag == '#text']


def _names(texts, role_nodes):
    """Person names among the texts; a first name and a last name in separate elements count as one."""
    out, pending = [], None
    for t in texts:
        if t in role_nodes:
            pending = None
            continue
        s = t.text.strip(' ,')
        if NAME.match(s) and not NOT_NAMES.search(s):
            out.append(f'{pending} {s}' if pending else s)      # "Ari" + "af Hällström"
            pending = None
        elif pending and re.match(rf'^{PARTICLE} {NAME_WORD}$', s, re.I):
            out.append(f'{pending} {s}')
            pending = None
        elif WORD.match(s) and not NOT_NAMES.search(s):
            if pending:
                out.append(f'{pending} {s}')
                pending = None
            else:
                pending = s
        else:
            pending = None
    return out


def _image(node, base):
    """The best picture in `node`: a linked full-size image, else the largest srcset entry, else src."""
    best = ''
    for n in node.walk():
        if n.tag == 'a' and re.search(r'(googleusercontent\.com/|\.(jpe?g|png|webp)(\?|$))', n.attrs.get('href') or '', re.I):
            return urllib.parse.urljoin(base, n.attrs['href'])
        if n.tag in ('img', 'source'):
            a = n.attrs
            srcset = a.get('srcset') or a.get('data-srcset') or ''
            if srcset:
                cands = []
                for part in srcset.split(','):
                    bits = part.strip().split()
                    if bits:
                        w = int(re.sub(r'\D', '', bits[1]) or 0) if len(bits) > 1 else 0
                        cands.append((w, bits[0]))
                if cands:
                    best = best or max(cands)[1]
            src = a.get('data-src') or a.get('data-lazy-src') or a.get('data-image') or a.get('src') or ''
            if not best and src and not src.startswith('data:'):
                best = src
        style = n.attrs.get('style') or '' if n.tag != '#text' else ''
        m = re.search(r"background-image:\s*url\(['\"]?([^'\")]+)", style)
        if not best and m and m.group(1).strip():
            best = m.group(1)
    return urllib.parse.urljoin(base, html.unescape(best)) if best else ''


def _link(node, base):
    """A link in `node` to another page on the same site (the person's own page), or ''."""
    host = urllib.parse.urlparse(base).netloc.removeprefix('www.')
    for n in node.walk():
        href = n.attrs.get('href') if n.tag == 'a' else None
        if href and not href.startswith(('#', 'mailto:', 'tel:')):
            url = urllib.parse.urljoin(base, href)
            if urllib.parse.urlparse(url).netloc.removeprefix('www.') == host and not re.search(r'\.(jpe?g|png|webp)', url, re.I):
                return url
    return ''


def page_photo(url, timeout=20):
    """The page's share picture (og:image), at full size when it's a resizable Google-hosted image."""
    page = fetch_page(url, timeout)
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', page)
    if not m or re.search(r'(?i)logo|default|placeholder', m.group(1)):
        return ''
    img = html.unescape(m.group(1))
    return re.sub(r'=w\d+-h\d+(-[a-z]+)*$', '=s1200', img) if 'googleusercontent.com' in img else img


def _role_text(s):
    s = s.strip(' ,:–-')
    s = s[:1].upper() + s[1:].lower() if s.isupper() else s
    return s[:1].upper() + s[1:]


def staff_from_html(page, base=''):
    """[{'name', 'role', 'image'}] found on a club page."""
    return read_page(page, base)[0]


def read_page(page, base=''):
    """(staff, photos) from a club page: staff as in staff_from_html, photos {name: image} of everyone shown
    with a picture (players too)."""
    tree = _Tree()
    try:
        tree.feed(page)
    except Exception:
        return [], {}
    texts = _texts(tree.root)
    roles = {t for t in texts if is_role(t.text)}
    out, seen = [], set()
    for t in texts:                                   # "Päävalmentaja: Jani Allenius" in one text
        m = ROLE_IN.match(t.text)
        if m and len(t.text) <= 80 and NAME.match(m.group(2)) and m.group(2) not in seen:
            seen.add(m.group(2))
            out.append({'name': m.group(2), 'role': _role_text(m.group(1)), 'image': ''})
    for r in texts:
        if r not in roles:
            continue
        node, card = r.parent, None
        for _ in range(7):                            # climb to the smallest part with exactly one name
            if node is None:
                break
            sub = _texts(node)
            names = _names(sub, roles)
            if len([x for x in sub if x in roles]) > 1 or len(names) > 1:
                break
            if names:
                card = (node, names[0])
            node = node.parent
        if not card:                                  # "Jyrki Aho, vastuuvalmentaja<br>Kurtis McLean, valmentaja"
            i = texts.index(r)
            prev = texts[i - 1].text.strip(' ,') if i else ''
            if prev and NAME.match(prev) and not NOT_NAMES.search(prev):
                card = (None, prev)
        if not card or card[1] in seen:
            continue
        seen.add(card[1])
        out.append({'name': card[1], 'role': _role_text(r.text), 'image': _image(card[0], base) if card[0] else '',
                    'link': _link(card[0], base) if card[0] else ''})
    for p in _heading_people(tree.root, roles, base):
        if p['name'] not in seen:
            seen.add(p['name'])
            out.append(p)
    photos = {}
    for card, name in _cards(tree.root, roles):
        img = _image(card, base)
        if img:
            photos.setdefault(name, img)
    return out, photos


def _cards(node, roles):
    """Top-down: the largest parts of `node` that each hold exactly one name -> [(part, name)]."""
    names = _names(_texts(node), roles)
    if not names:
        return []
    if len(names) == 1:
        return [(node, names[0])]
    return [c for k in node.kids for c in _cards(k, roles)]


def _heading_people(root, roles, base):
    """People listed under a staff heading ("Valmennus", "Toimihenkilöt") without a role of their own."""
    out = []
    for h in root.walk():
        if h.tag not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or h.parent is None:
            continue
        title = ' '.join(t.text for t in _texts(h)).strip()
        if len(title) > 40 or not HEADING.match(title):
            continue
        role = HEAD_ROLE.get(title.split()[0].lower(), '')
        sibs = h.parent.kids
        for k in sibs[sibs.index(h) + 1:]:
            if k.tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') or any(n.tag in ('h1', 'h2') for n in k.walk()):
                break
            for card, name in _cards(k, roles):
                out.append({'name': name, 'role': role, 'image': _image(card, base), 'link': _link(card, base),
                            'generic': True})
    return out


def fetch_page(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000).decode('utf-8', 'replace')


def club_staff(slug, timeout=20):
    """Staff of one club (by liiga.fi team slug), [] when its page is unknown or can't be read."""
    return club(slug, timeout)[0]


def club(slug, timeout=20):
    """(staff, photos) of one club (by liiga.fi team slug); empty when its page is unknown or can't be read."""
    out, seen, photos = [], set(), {}
    for url in PAGES.get(slug, []):
        try:
            people, pics = read_page(fetch_page(url, timeout), url)
        except Exception:
            continue
        for p in people:
            if p['name'] not in seen:
                seen.add(p['name'])
                out.append(p)
        for k, v in pics.items():
            photos.setdefault(k, v)
    people = {}                                       # picture -> the names it's shown for
    for name, img in list(photos.items()) + [(p['name'], p['image']) for p in out]:
        people.setdefault(img, set()).add(name)
    used = {img: len(names) for img, names in people.items()}
    photos = {k: v for k, v in photos.items() if not is_placeholder_url(v, used)}
    for p in out:
        p['image'] = '' if is_placeholder_url(p['image'], used) else p['image']
        p['image'] = p['image'] or photos.get(p['name'], '')
    todo = [p for p in out if not p['image'] and p.get('link')][:30]
    if todo:                                          # their own page may have a picture
        with ThreadPoolExecutor(max_workers=6) as pool:
            pics = list(pool.map(lambda p: _quiet(page_photo, p['link'], timeout), todo))
        shared = {u for u in pics if u and pics.count(u) > 1}      # the site's default picture, not a person
        for p, u in zip(todo, pics):
            if u and u not in shared:
                p['image'] = u
    for p in out:
        p.pop('link', None)
    return out, photos


PLACEHOLDER = re.compile(r'(?i)(^|[/_\-])(ph-\w+|blank[\w\-]*|placeholder[\w\-]*|default[\w\-]*|silhouette[\w\-]*|'
                         r'no-?image[\w\-]*|dummy[\w\-]*|pelaaja|player|avatar)\.(png|jpe?g|webp|gif|svg)')


def is_placeholder_url(url, used=None):
    """A stand-in picture: a telling file name, or the same picture on several people."""
    if not url:
        return False
    path = urllib.parse.urlparse(url).path
    return bool(PLACEHOLDER.search(path)) or bool(used and used.get(url, 0) > 1)


def _quiet(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return ''


# ------------------------------------------------------------------- Wikipedia

WIKI = 'https://{lang}.wikipedia.org/w/api.php'
HOCKEY = re.compile(r'(?i)jääkiekko|ice hockey|ishockey|erotuomari|referee|linjatuomari')


def wikipedia_photos(names, timeout=20):
    """{name: photo} for people whose Wikipedia article (Finnish, then English) is about ice hockey.

    Only articles that say so are used, so a namesake's portrait isn't picked up.
    """
    found, left = {}, list(dict.fromkeys(n for n in names if n))
    for lang in ('fi', 'en'):
        for i in range(0, len(left), 40):
            batch = left[i:i + 40]
            q = urllib.parse.urlencode({'action': 'query', 'format': 'json', 'redirects': 1, 'titles': '|'.join(batch),
                                        'prop': 'pageimages|extracts', 'piprop': 'thumbnail', 'pithumbsize': 800,
                                        'exintro': 1, 'explaintext': 1, 'exsentences': 3, 'exlimit': 'max'})
            try:
                req = urllib.request.Request(WIKI.format(lang=lang) + '?' + q,
                                             headers={'User-Agent': 'BetterMechanic/1.0 (https://github.com/Rtx-9/bettermechanic)'})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read().decode('utf-8'))
            except Exception:
                continue
            q = data.get('query') or {}
            back = {}
            for m in (q.get('normalized') or []) + (q.get('redirects') or []):
                back[m['to']] = back.get(m['from'], m['from'])
            for page in (q.get('pages') or {}).values():
                thumb = (page.get('thumbnail') or {}).get('source')
                if thumb and HOCKEY.search(page.get('extract') or ''):
                    found.setdefault(back.get(page.get('title'), page.get('title')), thumb)
        left = [n for n in left if n not in found]
    return found
