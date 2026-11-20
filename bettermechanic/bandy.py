"""Bandyliiga (Finnish bandy league) as tag presets: every team with its players, numbers, photos and staff, and
the season's games, from bandyliiga.fi.

The schedule is the season page (kausi-2026-27) and the rosters are the teams' roster pages, both plain HTML.
Captions of these games say "Bandyliiga-ottelussa" and end with the home team's ground ("Lappeenrannan
Kisapuistossa").
"""
from __future__ import annotations

import datetime
import html
import re
import urllib.request

from . import liiga

BASE = 'https://bandyliiga.fi'
PREFIX = 'bandy:'                       # preset / game ids: 'bandy:veitera', 'bandy:2027:<home>-<away>-<date>'

# schedule slug -> (name in captions, preset name, genitive, city, home ground, "at the ground")
TEAMS = {
    'veitera': ('Veiterä', 'Veiterä', 'Veiterän', 'Lappeenranta', 'Kisapuisto', 'Lappeenrannan Kisapuistossa'),
    'akilles': ('Akilles', 'Akilles', 'Akilleksen', 'Porvoo', 'Pallokenttä', 'Porvoon Pallokentällä'),
    'botnia': ('Botnia', 'Botnia', 'Botnian', 'Helsinki', 'Oulunkylän tekojäärata', 'Oulunkylän tekojääradalla'),
    'hifk': ('HIFK', 'HIFK Bandy', 'HIFK:n', 'Helsinki', 'Kallion tekojäärata', 'Kallion tekojääradalla'),
    'jps': ('JPS', 'JPS', 'JPS:n', 'Jyväskylä', 'OP Keski-Suomi Areena', 'Jyväskylän OP Keski-Suomi Areenalla'),
    'kampparit': ('Kampparit', 'Kampparit', 'Kamppareiden', 'Mikkeli', 'Hänni', 'Mikkelin Hännissä'),
    'narukera': ('Narukerä', 'Narukerä', 'Narukerän', 'Pori', 'Basso Areena', 'Porin Basso Areenalla'),
    'ols': ('OLS', 'OLS', 'OLS:n', 'Oulu', '', 'Oulussa'),
    'wp-35': ('WP 35', 'WP 35', 'WP 35:n', 'Varkaus', 'Joro-Huvilat Areena', 'Varkauden Joro-Huvilat Areenalla'),
}
GENITIVE = {slug: t[2] for slug, t in TEAMS.items()}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'BetterMechanic'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(4_000_000).decode('utf-8', 'replace')


def _text(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', '', s or ''))).strip()


def season_slug(season):
    """Season 2027 (autumn 2026 to spring 2027) -> '2026-27', as bandyliiga.fi names its pages."""
    return f'{season - 1}-{season % 100:02d}'


def games_from(page, season):
    """The season page -> {game id: game record}: every game of the season, played or to come."""
    out = {}
    for row in re.findall(r'<div class="blrh-row[^"]*">(.*?)</div>', page, re.S):
        when = re.search(r'<span>\s*(\d+)\.(\d+)\.(\d{4})', row)
        teams = re.findall(r'href="/joukkueet/([^/"]+)/"', row)
        if not when or len(teams) != 2:
            continue
        d, m, y = (int(x) for x in when.groups())
        day = datetime.date(y, m, d).isoformat()
        home = TEAMS.get(teams[0])
        rec = {'date': day, 'teams': [PREFIX + t for t in teams], 'refs': [],
               'names': [TEAMS[t][0] if t in TEAMS else t for t in teams],
               'rink': home[4] if home else '', 'city': home[3] if home else '', 'where': home[5] if home else '',
               'country': 'Finland', 'code': 'FI'}
        out[f'{PREFIX}{season}:{teams[0]}-{teams[1]}-{day}'] = rec
    return out


def roster_links(page):
    """The season's roster page -> {team name as shown: roster url}."""
    out = {}
    for url, name in re.findall(r'<a class="blrv34__tab" href="([^"]+)"[^>]*>.*?blrv34__tab-name">([^<]+)<', page,
                                re.S):
        out[_text(name)] = html.unescape(url)
    return out


def _name(s):
    return ' '.join(w[:1].upper() + w[1:] for w in _text(s).split())   # "Tero liimatainen" -> "Tero Liimatainen"


def roster_from(page):
    """A team's roster page -> players (number, photo) and staff (role, photo)."""
    out = []
    for item in re.split(r'<div class="team-roster__item">', page)[1:]:
        name = re.search(r'team-roster__member-name[^>]*>([^<]+)<', item)
        if not name:
            continue
        img = re.search(r'<img[^>]*?src="([^"]+)"', item)
        num = re.search(r'team-roster__member-number">\s*([^<]*?)\s*<', item)
        pos = re.search(r'team-roster__member-position">\s*([^<]*?)\s*<', item, re.S)
        staff = '/staff/' in item
        out.append({'name': _name(name.group(1)), 'number': '' if staff else _text(num and num.group(1)),
                    'image': html.unescape(img.group(1)) if img else '',
                    'role': (_text(pos.group(1)) or 'Staff') if staff else ''})
    return out


def fetch(season=None, timeout=20):
    """{'teams': [a preset for every team], 'games': {…}} for the season. Raises when offline or not out yet."""
    season = season or liiga.season_for()
    slug = season_slug(season)
    games = games_from(_get(f'{BASE}/kausi-{slug}/', timeout), season)
    if not games:
        raise ValueError('bandyliiga.fi has no games for this season yet')
    links = roster_links(_get(f'{BASE}/rosterit-{slug}/', timeout))
    teams = []
    for key, (short, preset, *_rest) in TEAMS.items():
        url = links.get(short)
        if not url:
            continue
        try:
            roster = roster_from(_get(url, timeout))
        except Exception:               # one team's page down: keep what its preset has
            continue
        if roster:
            roster.sort(key=liiga._order)
            teams.append({'id': PREFIX + key, 'name': preset, 'roster': roster,
                          'keywords': f'{short}, Bandyliiga'})
    return {'teams': teams, 'games': games}
