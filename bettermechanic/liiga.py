"""Liiga (Finnish ice hockey league) rosters as tag presets: one preset per team, every player with number and photo.

A snapshot ships with the app so the teams are there offline; `fetch()` gets the current rosters from liiga.fi
(the same public API the league's own site uses).
"""
from __future__ import annotations

import datetime
import json
import urllib.request

from .config import tag_preset

API = 'https://liiga.fi/api/v2/players/info?tournament=runkosarja&fromSeason={0}&toSeason={0}'


def season_for(day=None):
    """Liiga seasons are named by the year they end in: autumn 2026 belongs to season 2027."""
    day = day or datetime.date.today()
    return day.year + 1 if day.month >= 7 else day.year


def teams_from(players):
    """Raw /players/info rows -> [{'id', 'name', 'roster'}], players sorted by jersey number."""
    teams, seen = {}, set()
    for p in players:
        if not isinstance(p, dict) or p.get('removed') or not p.get('teamId') or p.get('id') in seen:
            continue
        name = ' '.join(x for x in (str(p.get('firstName') or '').strip(), str(p.get('lastName') or '').strip()) if x)
        if not name:
            continue
        seen.add(p.get('id'))
        t = teams.setdefault(p['teamId'], {'id': p['teamId'], 'name': str(p.get('teamName') or p['teamId']), 'roster': []})
        t['roster'].append({'name': name, 'number': str(p.get('jersey') or ''), 'image': p.get('pictureUrl') or ''})
    for t in teams.values():
        t['roster'].sort(key=lambda r: (not r['number'], int(r['number']) if r['number'].isdigit() else 0, r['name']))
    return sorted(teams.values(), key=lambda t: t['name'])


def fetch(season=None, timeout=20):
    """Current rosters from liiga.fi. Raises on network errors or an implausible answer."""
    req = urllib.request.Request(API.format(season or season_for()), headers={'User-Agent': 'BetterMechanic'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        teams = teams_from(json.loads(r.read().decode('utf-8')))
    if len(teams) < 8 or sum(len(t['roster']) for t in teams) < 150:
        raise ValueError('liiga.fi returned no rosters for this season yet')
    return teams


def snapshot():
    from .liiga_snapshot import SEASON, TEAMS
    return SEASON, TEAMS


def add_bundled(cfg):
    """First start with this feature: add every Liiga team from the snapshot, once."""
    if cfg.settings.get('liiga_added'):
        return 0
    cfg.settings['liiga_added'] = True
    return apply(cfg, snapshot()[1])[0]


def due(cfg, day=None):
    s = cfg.settings
    return bool(s.get('liiga_auto_update')) and s.get('liiga_checked') != (day or datetime.date.today()).isoformat() \
        and any(p.get('liiga') for p in cfg.tag_presets)


def apply(cfg, teams, add_missing=True):
    """Put rosters into the matching presets (or new ones). Quick keys, keywords and captions are left alone.

    Returns (added, updated) preset counts.
    """
    mine = {p.get('liiga'): p for p in cfg.tag_presets if p.get('liiga')}
    added = updated = 0
    for t in teams:
        if not t['roster']:
            continue
        p = mine.get(t['id'])
        if p is None:
            if not add_missing:
                continue
            p = tag_preset(t['name'])
            p['liiga'] = t['id']
            p['keywords'] = f'{t["name"]}, Liiga'
            cfg.tag_presets.append(p)
            added += 1
        roster = [dict(r) for r in t['roster']]
        if p.get('roster') != roster:
            p['roster'] = roster
            updated += 1
    return added, updated - added
