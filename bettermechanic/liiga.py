"""Liiga (Finnish ice hockey league) as tag presets: one preset per team with players and staff, plus the referees.

A snapshot ships with the app so everything is there offline; `fetch()` gets current data from liiga.fi (the same
public API the league's own site uses). Games are kept too, so the referees of the game a photo is from can be
shown first.
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import clubs
from .config import tag_preset

BASE = 'https://liiga.fi/api/v2'
TOURNAMENTS = ('runkosarja', 'playoffs')
REFEREES = 'referees'                   # preset id of the referees "team"
BUNDLE = 3                              # snapshot contents: 1 teams, 2 + referees and games, 3 + club staff
STAFF = ('Päävalmentaja', 'Toimitusjohtaja', 'Urheilutoimenjohtaja', 'Puheenjohtaja')   # liiga.fi team facts
OFFICIALS = {'PT': 'Referee', 'LT': 'Linesman'}


def season_for(day=None):
    """Liiga seasons are named by the year they end in: autumn 2026 belongs to season 2027."""
    day = day or datetime.date.today()
    return day.year + 1 if day.month >= 7 else day.year


def _get(path, timeout=20):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': 'BetterMechanic'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _name(first, last):
    return ' '.join(x for x in (str(first or '').strip(), str(last or '').strip()) if x)


def _rank(role):
    """Staff order: head coach, other coaches, managers, everyone else (referees before linesmen)."""
    r = role.lower()
    if r == 'referee' or re.search('pää|vastuu|head', r) and 'valmentaja' in r or r == 'head coach':
        return 0
    if 'valmentaja' in r or 'coach' in r or r == 'linesman':
        return 1
    if re.search('johtaja|manager|päällikkö', r):
        return 2
    return 3


def _order(r):
    role = r.get('role', '')
    if role:
        return (1, _rank(role), 0, r['name'])
    return (0, not r['number'], int(r['number']) if r['number'].isdigit() else 0, r['name'])


def teams_from(players):
    """Raw /players/info rows -> [{'id', 'name', 'roster'}], players sorted by jersey number."""
    teams, seen = {}, set()
    for p in players:
        if not isinstance(p, dict) or p.get('removed') or not p.get('teamId') or p.get('id') in seen:
            continue
        name = _name(p.get('firstName'), p.get('lastName'))
        if not name:
            continue
        seen.add(p.get('id'))
        t = teams.setdefault(p['teamId'], {'id': p['teamId'], 'name': str(p.get('teamName') or p['teamId']), 'roster': []})
        t['roster'].append({'name': name, 'number': str(p.get('jersey') or ''), 'image': p.get('pictureUrl') or '',
                            'pid': p.get('id')})
    for t in teams.values():
        t['roster'].sort(key=_order)
    return sorted(teams.values(), key=lambda t: t['name'])


def staff_from(team_info):
    """/teams/info -> {team id: [staff entries]} from each team's fact table (head coach, CEO, …)."""
    out = {}
    for tid, t in (team_info.get('teams') or {}).items():
        rows = re.findall(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', t.get('general_info') or '', re.S)
        people = []
        for label, value in rows:
            role = html.unescape(re.sub('<[^>]+>', '', label)).strip()
            if role not in STAFF:
                continue
            for name in re.split(r'<br\s*/?>|,| ja ', value):
                name = html.unescape(re.sub('<[^>]+>', '', name)).strip()
                if name and len(name.split()) >= 2 and len(name) < 40:
                    people.append({'name': name, 'number': '', 'image': '', 'role': role})
        if people:
            out[tid] = people
    return out


def game_from(detail):
    """/games/{season}/{id} -> (game id, {'date', 'teams', 'refs'}, {name: referee entry})."""
    g = detail.get('game') or {}
    start = datetime.datetime.fromisoformat(str(g.get('start', '')).replace('Z', '+00:00'))
    day = (start + datetime.timedelta(hours=3)).date().isoformat()      # Finnish local date
    refs = {}
    for r in g.get('referees') or []:
        name = _name(r.get('firstName'), r.get('lastName'))
        if name:
            refs[name] = {'name': name, 'number': '', 'image': r.get('pictureUrl') or '',
                          'role': OFFICIALS.get(r.get('roleAbbrv'), str(r.get('roleName') or 'Referee'))}
    teams = [(g.get('homeTeam') or {}).get('teamId'), (g.get('awayTeam') or {}).get('teamId')]
    return g.get('id'), {'date': day, 'teams': teams, 'refs': list(refs)}, refs


def referees_team(officials):
    roster = sorted(officials.values(), key=_order)
    return {'id': REFEREES, 'name': 'Liiga Referees', 'roster': roster}


def fetch(season=None, games=None, timeout=20):
    """Current rosters, staff, referees and games from liiga.fi.

    games: games already known ({id: record}); only new ones are downloaded. Raises on network errors or an
    implausible answer.
    """
    season = season or season_for()
    teams = teams_from(_get(f'/players/info?tournament=runkosarja&fromSeason={season}&toSeason={season}', timeout))
    if len(teams) < 8 or sum(len(t['roster']) for t in teams) < 150:
        raise ValueError('liiga.fi returned no rosters for this season yet')
    try:
        staff = staff_from(_get('/teams/info', timeout))
    except Exception:           # staff is a nice-to-have
        staff = {}
    slugs = {t['id']: t['id'].split(':', 1)[-1] for t in teams}
    with ThreadPoolExecutor(max_workers=6) as pool:     # the clubs' own sites: full staff, more photos
        club = dict(zip(slugs.values(), pool.map(lambda s: _try(lambda: clubs.club(s, timeout)) or ([], {}),
                                                  slugs.values())))
    earlier = _earlier_photos(season, timeout)
    for t in teams:
        people, photos = club.get(slugs[t['id']], ([], {}))
        t['roster'] += merge_staff(staff.get(t['id'], []), people)
        for r in t['roster']:
            if not r['image']:
                r['image'] = earlier.get(r.get('pid')) or photos.get(r['name'], '')
    known = {str(k): v for k, v in (games or {}).items() if str(k).startswith(f'{season}:')}
    todo = []
    for tour in TOURNAMENTS:
        try:
            for g in _get(f'/games?tournament={tour}&season={season}', timeout):
                key = f'{season}:{g.get("id")}'
                if (g.get('started') or g.get('ended')) and (key not in known or not known[key]['refs']):
                    todo.append(g['id'])
        except Exception:
            continue
    officials = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for detail in pool.map(lambda gid: _try(lambda: _get(f'/games/{season}/{gid}', timeout)), todo):
            if detail:
                gid, rec, refs = game_from(detail)
                known[f'{season}:{gid}'] = rec
                officials.update(refs)
        refs = list(officials.values())
        for r, url in zip(refs, pool.map(lambda r: _photo(r['image'], season, timeout), refs)):
            r['image'] = url
    people = [r for t in teams for r in t['roster']] + list(officials.values())
    wiki = _try(lambda: clubs.wikipedia_photos([r['name'] for r in people if not r['image']], timeout)) or {}
    for r in people:
        r['image'] = r['image'] or wiki.get(r['name'], '')
        r.pop('pid', None)
    for t in teams:
        t['roster'].sort(key=_order)
    return {'season': season, 'teams': teams, 'officials': officials, 'games': known}


def merge_staff(league, club):
    """The club's own staff list; liiga.fi's (head coach, CEO, chairman) only when the club lists nobody.

    liiga.fi's team facts lag behind (former coaches stay listed), so they only add a role to someone the club
    lists without one.
    """
    out = {p['name']: {'name': p['name'], 'number': '', 'image': p.get('image', ''), 'role': p.get('role', ''),
                       'generic': p.get('generic', False)} for p in club}
    for p in league:
        q = out.get(p['name'])
        if q is None:
            if not club:
                out[p['name']] = dict(p)
        elif q['generic'] or not q['role']:
            q['role'] = p['role']
    for q in out.values():
        q.pop('generic', None)
        q['role'] = q['role'] or 'Staff'
    return list(out.values())


def _earlier_photos(season, timeout=20):
    """{player id: photo} from the last seasons, for players whose photo isn't up for this season yet."""
    out = {}
    for year in (season - 2, season - 1):
        rows = _try(lambda: _get(f'/players/info?tournament=runkosarja&fromSeason={year}&toSeason={year}', timeout))
        for p in rows or []:
            if isinstance(p, dict) and p.get('pictureUrl'):
                out[p.get('id')] = p['pictureUrl']
    return out


def _photo(url, season, timeout=20):
    """Referee photos often aren't uploaded for the new season yet: fall back to the last seasons' photo."""
    if not url:
        return ''
    for year in (season, season - 1, season - 2):
        u = url.replace(f'/{season}/', f'/{year}/')
        try:
            req = urllib.request.Request(u, method='HEAD', headers={'User-Agent': 'BetterMechanic'})
            with urllib.request.urlopen(req, timeout=timeout):
                return u
        except Exception:
            continue
    return ''


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


# ----------------------------------------------------------------- local data

def snapshot():
    from .liiga_snapshot import GAMES, OFFICIALS as REFS, SEASON, TEAMS
    return {'season': SEASON, 'teams': TEAMS, 'officials': REFS, 'games': GAMES}


def games_path(cfg):
    return os.path.join(os.path.dirname(str(cfg.path)), 'liiga_games.json')


def load_games(cfg):
    try:
        with open(games_path(cfg), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_games(cfg, games):
    path = games_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(games, fh, ensure_ascii=False)
    os.replace(path + '.tmp', path)


def game_on(games, day, team_ids):
    """The game on `day` (date) between the given teams (one or two liiga ids), or None."""
    want = {t for t in team_ids if t}
    if not want:
        return None
    for g in games.values():
        if g.get('date') == day.isoformat() and want <= set(g.get('teams') or []):
            return g
    return None


def add_bundled(cfg):
    """Add what the snapshot has that this config hasn't seen yet (all teams at first; referees in an upgrade)."""
    s = cfg.settings
    have = int(s.get('liiga_bundle') or (1 if s.get('liiga_added') else 0))
    if have >= BUNDLE:
        return 0
    s['liiga_bundle'], s['liiga_added'] = BUNDLE, True
    data = snapshot()
    if have == 0:
        return apply(cfg, data)[0]
    if have == 1:                                    # rosters from 0.6/0.7: everyone came from liiga.fi
        for p in cfg.tag_presets:
            if p.get('liiga'):
                for r in p.get('roster') or []:
                    r['liiga'] = True
    s['liiga_checked'] = ''                          # and refresh soon
    return apply(cfg, data, add_missing={REFEREES})[0]


def due(cfg, day=None):
    s = cfg.settings
    return bool(s.get('liiga_auto_update')) and s.get('liiga_checked') != (day or datetime.date.today()).isoformat() \
        and any(p.get('liiga') for p in cfg.tag_presets)


def apply(cfg, data, add_missing=True):
    """Put liiga.fi data into the matching presets (or new ones). Returns (added, updated) preset counts.

    add_missing: add presets for teams you don't have (True), none (False) or only these team ids (a set).
    Quick keys, keywords, captions and people you added to a roster yourself are kept. The referees list only
    grows: officials from earlier games stay.
    """
    games = dict(load_games(cfg))
    games.update(data.get('games') or {})
    save_games(cfg, games)
    teams = list(data.get('teams') or [])
    mine = {p.get('liiga'): p for p in cfg.tag_presets if p.get('liiga')}
    if data.get('officials'):
        old = {r['name']: r for r in (mine.get(REFEREES) or {}).get('roster') or [] if r.get('liiga')}
        old.update(data['officials'])
        teams.append(referees_team(old))
    added = updated = 0
    for t in teams:
        if not t['roster']:
            continue
        p = mine.get(t['id'])
        if p is None:
            if not add_missing or add_missing is not True and t['id'] not in add_missing:
                continue
            p = tag_preset(t['name'])
            p['liiga'] = t['id']
            p['keywords'] = 'Liiga' if t['id'] == REFEREES else f'{t["name"]}, Liiga'
            cfg.tag_presets.append(p)
            added += 1
        fresh = [dict(r, role=r.get('role', ''), liiga=True) for r in t['roster']]
        names = {r['name'] for r in fresh}
        own = [r for r in p.get('roster') or [] if not r.get('liiga') and r['name'] not in names]
        roster = fresh + own
        if p.get('roster') != roster:
            p['roster'] = roster
            updated += 1
    return added, updated - added
