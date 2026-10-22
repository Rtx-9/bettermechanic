"""Lightroom Classic plugin: install it, and give it the teams, people, photos and games to show.

The plugin (assets/BetterMechanic.lrplugin, Lua) is a floating window in Lightroom with two teams and the
referees; clicking someone tags the photos selected in Lightroom. It reads what this module writes to
<app folder>/lightroom: players.txt (one tab-separated record per line) and ready-made round photos with the
jersey number on them, so the plugin needs no network, image or JSON code of its own.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

from . import avatars, liiga
from .config import players

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


# ------------------------------------------------------------------ data

def data_dir(cfg):
    return os.path.join(os.path.dirname(str(cfg.path)), 'lightroom')


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


def export(cfg, avatar_dir, fetch_missing=True, workers=4):
    """Write players.txt and the pictures for the plugin. Returns (people, pictures drawn)."""
    out = data_dir(cfg)
    img_dir = os.path.join(out, 'img')
    os.makedirs(img_dir, exist_ok=True)
    blank = os.path.join(img_dir, 'blank.png')
    if not os.path.exists(blank):
        Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0)).save(blank)
    lines, jobs, keep = ['v\t1'], [], {'blank.png'}
    for p in cfg.tag_presets:
        lines.append('\t'.join(['t', p['id'], _clean(p['name']), p.get('liiga', ''), _clean(p.get('keywords', ''))]))
        for e in players(p):
            cached = avatars.cache_path(avatar_dir, e['image']) if e.get('image') else ''
            has = bool(cached) and os.path.exists(cached)    # in the name: redrawn once the photo is there
            key = f'{RENDER}|{e["name"]}|{e.get("number")}|{e.get("image")}|{has}'
            fname = hashlib.sha1(key.encode('utf-8')).hexdigest()[:20] + '.png'
            keep.add(fname)
            lines.append('\t'.join(['p', _clean(e['name']), _clean(e.get('number')), _clean(e.get('role')), fname]))
            if not os.path.exists(os.path.join(img_dir, fname)):
                jobs.append((e, cached, os.path.join(img_dir, fname)))
    for g in liiga.load_games(cfg).values():
        lines.append('\t'.join(['g', g.get('date', ''), *[(t or '') for t in (g.get('teams') or ['', ''])[:2]],
                                '|'.join(_clean(r) for r in g.get('refs') or [])]))

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
