"""Lightroom Classic plugin: install it, and give it the teams, people, photos and games to show.

The plugin (assets/BetterMechanic.lrplugin, Lua) is a floating window in Lightroom with two teams and the
referees; clicking someone tags the photos selected in Lightroom. It reads what this module writes to
<app folder>/lightroom: players.txt (one tab-separated record per line) and ready-made round photos with the
jersey number on them, so the plugin needs no network, image or JSON code of its own.

Send to Lightroom: the app writes the photos' paths to <app folder>/lightroom/send and the plugin, which watches
that folder while Lightroom runs, adds them to the catalog.
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from . import avatars, liiga
from .config import players

# Finnish forms for news captions: "Kärppien Henrik Törnqvist (11) ... Oulussa"
GENITIVE = {'hifk': 'HIFK:n', 'hpk': 'HPK:n', 'ilves': 'Ilveksen', 'jyp': 'JYP:n', 'jokerit': 'Jokereiden',
            'jukurit': 'Jukureiden', 'k-espoo': 'K-Espoon', 'kalpa': 'KalPan', 'kookoo': 'KooKoon',
            'kärpät': 'Kärppien', 'lukko': 'Lukon', 'pelicans': 'Pelicansin', 'saipa': 'SaiPan', 'sport': 'Sportin',
            'tps': 'TPS:n', 'tappara': 'Tapparan', 'ässät': 'Ässien',
            'pardubice': 'Pardubicen'}                                          # CHL clubs (chl.CLUBS)
LOCATIVE = {'Espoo': 'Espoossa', 'Helsinki': 'Helsingissä', 'Hämeenlinna': 'Hämeenlinnassa', 'Jyväskylä': 'Jyväskylässä',
            'Kouvola': 'Kouvolassa', 'Kuopio': 'Kuopiossa', 'Lahti': 'Lahdessa', 'Lappeenranta': 'Lappeenrannassa',
            'Mikkeli': 'Mikkelissä', 'Oulu': 'Oulussa', 'Pori': 'Porissa', 'Rauma': 'Raumalla', 'Tampere': 'Tampereella',
            'Turku': 'Turussa', 'Vaasa': 'Vaasassa', 'Vantaa': 'Vantaalla', 'Seinäjoki': 'Seinäjoella',
            'Joensuu': 'Joensuussa', 'Kotka': 'Kotkassa', 'Savonlinna': 'Savonlinnassa', 'Pardubice': 'Pardubicessa'}
# where a game is played, as the end of a caption says it ("… 11.11.2026 Lappeenrannan Kisapuistossa"): by home
# team where the arena goes by another name than liiga.fi's, else made from liiga.fi's (arena_in)
ARENA_IN = {'saipa': 'Lappeenrannan Kisapuistossa', 'lukko': 'Rauman Äijänsuo Areenalla',
            'pardubice': 'Pardubicen Enteria Arenalla'}
ARENA_ENDS = (('halli', 'hallissa'), ('areena', 'areenalla'), ('Areena', 'Areenalla'), ('Arena', 'Arenalla'))


def arena_in(rink, home):
    """'Kuopion jäähalli' -> 'Kuopion jäähallissa'; '' when there's no telling (the caption then leaves it out)."""
    slug = (home or '').split(':', 1)[-1]
    if slug in ARENA_IN:
        return ARENA_IN[slug]
    name = re.sub(r'\s+(?:I+|Oy)$', '', (rink or '').split(' / ')[0].strip())
    for end, form in ARENA_ENDS:
        if name.endswith(end):
            return name[:-len(end)] + form
    return ''

SIZE = 72                       # avatar size in the Lightroom window (pixels)
RENDER = 2                      # render version: bump to redraw every picture
PLUGIN = 'BetterMechanic.lrplugin'
PALETTE = [(10, 132, 255), (255, 159, 10), (48, 209, 88), (191, 90, 242), (255, 69, 58), (255, 214, 10)]


def plugin_source():
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    if hasattr(sys, '_MEIPASS'):
        base = os.path.join(base, 'bettermechanic')
    return os.path.join(base, 'assets', PLUGIN)


def modules_dir():
    """Lightroom Classic loads every plugin in this folder at start."""
    if sys.platform == 'win32':
        return os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~/AppData/Roaming'), 'Adobe', 'Lightroom',
                            'Modules')
    return os.path.expanduser('~/Library/Application Support/Adobe/Lightroom/Modules')


def installed():
    return os.path.isdir(os.path.join(modules_dir(), PLUGIN))


def install():
    """Copy the plugin into Lightroom's Modules folder (replacing an older copy). Returns its path."""
    dest = os.path.join(modules_dir(), PLUGIN)
    os.makedirs(modules_dir(), exist_ok=True)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(plugin_source(), dest)
    return dest


def up_to_date():
    """The installed plugin is the same as the one in this version of the app."""
    a, b = os.path.join(plugin_source(), 'Info.lua'), os.path.join(modules_dir(), PLUGIN, 'Info.lua')
    try:
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def executable():
    """Lightroom Classic's program, or None when it isn't installed where Adobe puts it."""
    if sys.platform == 'win32':
        roots = {os.environ.get(k) for k in ('ProgramW6432', 'ProgramFiles')} | {r'C:\Program Files'}
        for root in filter(None, roots):
            found = sorted(glob.glob(os.path.join(root, 'Adobe', 'Adobe Lightroom Classic*', 'Lightroom.exe')))
            if found:
                return found[0]
        return None
    found = sorted(glob.glob('/Applications/Adobe Lightroom Classic*/Adobe Lightroom Classic.app'))
    return found[0] if found else None


def running():
    try:
        if sys.platform == 'win32':
            out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Lightroom.exe', '/NH'], capture_output=True,
                                 text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return 'lightroom.exe' in out.lower()
        return subprocess.run(['pgrep', '-x', 'Adobe Lightroom Classic'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def launch():
    """Start Lightroom Classic; True if it could be started."""
    exe = executable()
    if not exe:
        return False
    try:
        subprocess.Popen(['open', exe] if sys.platform == 'darwin' else [exe], close_fds=True)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ data

def data_dir(cfg):
    return os.path.join(os.path.dirname(str(cfg.path)), 'lightroom')


def send_dir(cfg):
    return os.path.join(data_dir(cfg), 'send')


def send(cfg, paths):
    """Ask the plugin to add these files to the Lightroom catalog. Returns the request's name (see result)."""
    out = send_dir(cfg)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):                       # answers nobody waited for
        p = os.path.join(out, f)
        try:
            if f.endswith('.done') and os.path.getmtime(p) < time.time() - 3600:
                os.remove(p)
        except OSError:
            pass
    name = str(time.time_ns())                      # sorts by time: the plugin takes the oldest first
    tmp = os.path.join(out, name + '.part')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(''.join(os.path.abspath(p) + '\n' for p in paths))
    os.replace(tmp, os.path.join(out, name + '.txt'))
    return name


def result(cfg, name):
    """(added, already in the catalog, failed) once Lightroom has taken the request, else None."""
    p = os.path.join(send_dir(cfg), name + '.done')
    try:
        with open(p, encoding='utf-8') as fh:
            counts = tuple(int(x) for x in fh.read().split()[:3])
        os.remove(p)
    except (OSError, ValueError):
        return None
    return counts if len(counts) == 3 else None


def _clean(s):
    return ' '.join(str(s or '').split())


def _font(px, bold=False):
    for name in (('seguisb.ttf', 'segoeuib.ttf') if bold else ('segoeui.ttf',)) + ('arialbd.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def render(entry, cached, dest):
    """Round photo (or coloured initials) with the jersey number, like the app's player tiles."""
    s = SIZE * 2                                 # draw large, scale down for smooth edges
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    mask = Image.new('L', (s, s), 0)
    ImageDraw.Draw(mask).ellipse((2, 2, s - 3, s - 3), fill=255)
    photo = None
    if cached and os.path.exists(cached):
        try:
            photo = Image.open(cached).convert('RGB').resize((s, s), Image.Resampling.LANCZOS)
        except OSError:
            photo = None
    if photo is None:
        color = PALETTE[int(hashlib.md5(entry['name'].encode('utf-8')).hexdigest(), 16) % len(PALETTE)]
        photo = Image.new('RGB', (s, s), color)
        d = ImageDraw.Draw(photo)
        initials = avatars.initials(entry['name'])
        f = _font(int(s * 0.38), bold=True)
        box = d.textbbox((0, 0), initials, font=f)
        d.text(((s - box[2] - box[0]) / 2, (s - box[3] - box[1]) / 2), initials, font=f, fill='white')
    im.paste(photo, (0, 0), mask)
    if entry.get('number'):
        d = ImageDraw.Draw(im)
        f = _font(int(s * 0.2), bold=True)
        t = entry['number']
        tw = d.textbbox((0, 0), t, font=f)[2]
        w, h = max(int(s * 0.3), tw + int(s * 0.12)), int(s * 0.26)
        x, y = int(s * 0.02), s - h - int(s * 0.02)
        d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(20, 20, 22, 240), outline='white', width=3)
        tb = d.textbbox((0, 0), t, font=f)
        d.text((x + (w - (tb[2] - tb[0])) / 2 - tb[0], y + (h - (tb[3] - tb[1])) / 2 - tb[1]), t, font=f, fill='white')
    im.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(dest)


HEADINGS = {'staff': 'STAFF', 'game': 'THIS\nGAME', 'referees': 'REFEREES', 'linesmen': 'LINESMEN'}


def render_heading(text, dest):
    """A tile-sized heading ("STAFF") placed in the run of people: grey, readable on light and dark windows."""
    s = SIZE * 2
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = _font(int(s * 0.17), bold=True)
    box = d.multiline_textbbox((0, 0), text, font=f, align='center', spacing=4)
    w, h = box[2] - box[0], box[3] - box[1]
    d.multiline_text(((s - w) / 2 - box[0], (s - h) / 2 - box[1] - 6), text, font=f, fill=(128, 128, 134, 255),
                     align='center', spacing=4)
    d.line((s * 0.2, (s + h) / 2 + 8, s * 0.8, (s + h) / 2 + 8), fill=(128, 128, 134, 255), width=3)
    im.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(dest)


def export(cfg, avatar_dir, fetch_missing=True, workers=4):
    """Write players.txt and the pictures for the plugin. Returns (people, pictures drawn)."""
    out = data_dir(cfg)
    img_dir = os.path.join(out, 'img')
    os.makedirs(img_dir, exist_ok=True)
    blank = os.path.join(img_dir, 'blank.png')
    if not os.path.exists(blank):
        Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0)).save(blank)
    lines, jobs, keep = ['v\t1'], [], {'blank.png'}
    chosen = (list(getattr(cfg, 'settings', {}).get('team_panel') or []) + ['', ''])[:2]
    lines.append('\t'.join(['d', *chosen]))           # the teams picked in the app open first in Lightroom
    for key, text in HEADINGS.items():
        fname = f'h_{key}.png'
        keep.add(fname)
        if not os.path.exists(os.path.join(img_dir, fname)):
            render_heading(text, os.path.join(img_dir, fname))
    for p in cfg.tag_presets:
        slug = (p.get('liiga') or '').split(':', 1)[-1]
        lines.append('\t'.join(['t', p['id'], _clean(p['name']), p.get('liiga', ''), _clean(p.get('keywords', '')),
                                GENITIVE.get(slug, '')]))
        for e in players(p):
            cached = avatars.cache_path(avatar_dir, e['image']) if e.get('image') else ''
            has = bool(cached) and os.path.exists(cached)    # in the name: redrawn once the photo is there
            key = f'{RENDER}|{e["name"]}|{e.get("number")}|{e.get("image")}|{has}'
            fname = hashlib.sha1(key.encode('utf-8')).hexdigest()[:20] + '.png'
            keep.add(fname)
            lines.append('\t'.join(['p', _clean(e['name']), _clean(e.get('number')), _clean(e.get('role')), fname]))
            if not os.path.exists(os.path.join(img_dir, fname)):
                jobs.append((e, cached, os.path.join(img_dir, fname)))
    for gid, g in liiga.load_games(cfg).items():
        city = _clean(g.get('city'))
        lines.append('\t'.join(['g', g.get('date', ''), *[(t or '') for t in (g.get('teams') or ['', ''])[:2]],
                                '|'.join(_clean(r) for r in g.get('refs') or []), _clean(g.get('rink')), city,
                                LOCATIVE.get(city, ''), 'CHL' if str(gid).startswith('chl:') else 'Liiga',
                                *[_clean(n) for n in (list(g.get('names') or []) + ['', ''])[:2]],
                                _clean(g.get('country', 'Finland')), _clean(g.get('code', 'FI')),
                                _clean(arena_in(g.get('rink'), (g.get('teams') or [''])[0]))]))

    def draw(job):
        e, cached, dest = job
        if cached and not os.path.exists(cached) and fetch_missing:
            try:
                os.makedirs(avatar_dir, exist_ok=True)
                avatars.make_avatar_file(e['image'], cached)
            except Exception:                       # offline, placeholder, gone: initials
                pass
        render(e, cached, dest)

    if jobs:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(draw, jobs))
    tmp = os.path.join(out, 'players.txt.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    os.replace(tmp, os.path.join(out, 'players.txt'))
    for f in os.listdir(img_dir):                   # pictures nobody uses any more
        if f.endswith('.png') and f not in keep:
            try:
                os.remove(os.path.join(img_dir, f))
            except OSError:
                pass
    return sum(1 for ln in lines if ln.startswith('p\t')), len(jobs)
