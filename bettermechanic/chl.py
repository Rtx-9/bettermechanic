"""Champions Hockey League: the games of the Finnish clubs, and the clubs they play as tag presets.

The games come from chl.hockey (the public feed its own site shows the schedule from). Finnish clubs are the Liiga
presets; the clubs from abroad get a preset of their own when their roster can be read (CLUBS: each club's website).
Captions of CHL games say "CHL-ottelussa" instead of "Liiga-ottelussa".
"""
from __future__ import annotations

import datetime
import html
import json
import re
import urllib.request

from . import liiga

LIVE = 'https://www.chl.hockey/api/s3/live?q=live-events.json'
PREFIX = 'chl:'                         # preset / game ids: 'chl:pardubice', 'chl:<chl.hockey match id>'

# Czech staff roles as Finnish captions write them
ROLES = {'hlavní trenér': 'Päävalmentaja', 'asistent trenéra': 'Apuvalmentaja', 'trenér brankářů': 'Maalivahtivalmentaja',
         'skills coach': 'Taitovalmentaja', 'kondiční trenér': 'Fysiikkavalmentaja', 'videotrenér': 'Videovalmentaja',
         'vedoucí mužstva': 'Joukkueenjohtaja', 'hlavní analytik': 'Pääanalyytikko', 'analytik': 'Analyytikko',
         'lékař': 'Lääkäri', 'fyzioterapeut': 'Fysioterapeutti', 'masér': 'Hieroja', 'kustod': 'Huoltaja',
         'sportovní manažer': 'Urheilutoimenjohtaja', 'generální manažer': 'Urheilutoimenjohtaja'}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'BetterMechanic'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000).decode('utf-8', 'replace')


def _text(s):
    return html.unescape(re.sub('<[^>]+>', '', s or '')).strip()


def esports_cz(url, timeout=20, page=None):
    """A Czech club site on the eSports.cz system (hcdynamo.cz …): players with numbers and photos, then the staff."""
    page = page if page is not None else _get(url, timeout)
    base = re.match(r'https?://[^/]+', url).group(0)
    roster = []
    for num, img, name in re.findall(r'player-roster-number[^>]*>\s*([^<]*?)\s*</span>\s*<img[^>]*?src="([^"]+)"'
                                     r'[^>]*?alt="([^"]+)"', page):
        roster.append({'name': _text(name), 'number': _text(num), 'image': html.unescape(base + img
                                                                                     if img.startswith('/') else img)})
    at = page.find('Realizační tým')
    staff = page[at:page.find('</section>', at)] if at >= 0 else ''
    for img, name, role in re.findall(r'<img[^>]*?src="([^"]+)"[^>]*>\s*<div[^>]*>\s*<h4[^>]*>([^<]+)</h4>\s*'
                                      r'<span[^>]*>([^<]*)</span>', staff):
        name = re.sub(r'^(?:MUDr|MVDr|Mgr|Ing|Bc|PhDr|Dr)\.\s*', '', _text(name))
        role = _text(role)
        roster.append({'name': name, 'number': '', 'image': html.unescape(base + img if img.startswith('/') else img),
                       'role': ROLES.get(role.lower(), role or 'Staff')})
    return roster


# the clubs from abroad we can read a roster for: chl.hockey team id -> preset
CLUBS = {
    '3e2b15fb0e41329efc1f6237': {'id': PREFIX + 'pardubice', 'name': 'Dynamo Pardubice', 'city': 'Pardubice',
                                 'country': 'Czech Republic', 'code': 'CZ', 'rink': 'Enteria Arena',
                                 'roster': lambda timeout: esports_cz('https://hcdynamo.cz/team/MUZ', timeout)},
}


def local_date(start):
    t = datetime.datetime.fromisoformat(str(start).replace('Z', '+00:00'))
    return (t + datetime.timedelta(hours=3)).date().isoformat()          # as liiga.game_record: Finnish date


def _slug(name):
    return (name or '').split()[0].lower() if name else ''


def games_from(feed, liiga_ids, liiga_games=None):
    """chl.hockey's live-events feed -> {game id: game record} for the games of the Finnish clubs.

    liiga_ids: the Liiga team ids ('933686567:saipa'); a CHL team is that club when its name starts with the slug.
    A Finnish home game takes its arena and city from the club's Liiga home games.
    """
    by_slug = {i.split(':', 1)[-1]: i for i in liiga_ids}
    home_of = {}
    for g in (liiga_games or {}).values():
        if g.get('teams') and g.get('city'):
            home_of[g['teams'][0]] = g
    out = {}
    for m in (feed or {}).get('data') or []:
        try:
            teams = m.get('teams') or {}
            ids, names = [], []
            for side in ('home', 'away'):
                t = teams.get(side) or {}
                club = CLUBS.get(t.get('_entityId'))
                ids.append(by_slug.get(_slug(t.get('name'))) or (club and club['id'])
                           or PREFIX + re.sub(r'\W+', '-', str(t.get('name') or '').lower()).strip('-'))
                names.append(club['name'] if club else str(t.get('name') or ''))
            if not any(i in liiga_ids for i in ids):
                continue
            rec = {'date': local_date(m['startDate']), 'teams': ids, 'refs': [], 'names': names,
                   'rink': str((m.get('venue') or {}).get('name') or ''), 'city': '', 'country': '', 'code': ''}
            home = next((c for c in CLUBS.values() if c['id'] == ids[0]), None)
            if home:
                rec.update(city=home['city'], country=home['country'], code=home['code'])
            elif ids[0] in liiga_ids:
                rec.update(country='Finland', code='FI')
                if ids[0] in home_of:
                    rec.update(rink=home_of[ids[0]]['rink'], city=home_of[ids[0]]['city'])
            out[PREFIX + str(m['_entityId'])] = rec
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch(liiga_ids, liiga_games=None, timeout=20):
    """{'teams': [presets of the clubs from abroad that play a Finnish club], 'games': {…}}. Raises when offline."""
    games = games_from(json.loads(_get(LIVE, timeout)), set(liiga_ids), liiga_games)
    playing = {i for g in games.values() for i in g['teams']}
    teams = []
    for club in CLUBS.values():
        if club['id'] not in playing:
            continue
        try:
            roster = club['roster'](timeout)
        except Exception:               # the club's site is down or changed: keep what the preset has
            continue
        if roster:
            roster.sort(key=liiga._order)            # players by number, then the staff, head coach first
            teams.append({'id': club['id'], 'name': club['name'], 'roster': roster,
                          'keywords': f'{club["name"]}, CHL'})
    return {'teams': teams, 'games': games}
