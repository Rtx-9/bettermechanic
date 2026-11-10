"""Champions Hockey League: the Finnish clubs' games from chl.hockey and the rosters of the clubs they play."""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bettermechanic import chl, liiga  # noqa: E402
from bettermechanic.config import Config  # noqa: E402

PARDUBICE = '3e2b15fb0e41329efc1f6237'


def match(mid, start, home, away, stage='Round of 16', venue='Kisapuisto'):
    def team(t):
        return {'_entityId': t[0], 'name': t[1]}
    return {'_entityId': mid, 'startDate': start, 'venue': {'name': venue}, 'stage': {'group': {'name': stage}},
            'teams': {'home': team(home), 'away': team(away)}}


SAIPA, KOOKOO = ('6aa', 'SaiPa Lappeenranta'), ('c98', 'KooKoo Kouvola')
FEED = {'data': [
    match('m1', '2026-11-11T16:30:00.000Z', SAIPA, (PARDUBICE, 'Dynamo Pardubice')),
    match('m2', '2026-11-18T17:00:00.000Z', (PARDUBICE, 'Dynamo Pardubice'), SAIPA, venue='Enteria Arena'),
    match('m3', '2026-11-18T18:30:00.000Z', ('2e6', 'Eisbären Berlin'), KOOKOO, venue='Wellblechpalast'),
    match('m4', '2026-11-11T18:45:00.000Z', ('41e', 'Genève-Servette'), ('9b6', 'Fribourg-Gottéron')),
    match('m5', '2026-10-14T15:30:00.000Z', SAIPA, ('xx', 'HC Pilsen'), stage='Regular Season'),
    {'broken': True},
]}
IDS = ['933686567:saipa', '461765763:kookoo']
LIIGA_GAMES = {'2027:1': {'date': '2026-09-01', 'teams': ['933686567:saipa', '362185137:tappara'],
                          'rink': 'Lappeenrannan jäähalli I', 'city': 'Lappeenranta'}}

PAGE = '''<section id="soupiska"><h3 class="h3">Brankáři</h3><ul>
<li><a href="/player/1465/MUZ" title="Přejít na profil hráče: Malcolm Subban">
  <span class="player-roster-number absolute">32</span>
  <img class="w-full" src="/image?file=https://x.cz/Subban-Malcolm.png?1&amp;w=651&amp;h=768" width="434" alt="Malcolm Subban">
  <h4>Malcolm Subban</h4></a></li>
<li><a href="/player/1" title="Přejít na profil hráče: Roman Červenka">
  <span class="player-roster-number absolute">19</span>
  <img src="/image?file=https://x.cz/Cervenka.png" alt="Roman Červenka"></a></li>
</ul></section>
<section aria-label="Realizační tým"><h2>Realizační tým</h2><ul>
<li class="swiper-slide"><img class="w-full" src="/image?file=https://x.cz/rt/pesan.png" alt="Filip Pešán">
  <div class="flex"><h4 class="h4 text-white">Filip Pešán</h4><span class="font-medium">Hlavní trenér</span></div></li>
<li class="swiper-slide"><img src="/image?file=https://x.cz/rt/hoza.png" alt="Petr Hoza">
  <div class="flex"><h4 class="h4 text-white">MUDr. Petr Hoza</h4><span class="font-medium">Lékař</span></div></li>
<li class="swiper-slide"><img src="/image?file=https://x.cz/rt/x.png" alt="X Y">
  <div class="flex"><h4 class="h4 text-white">Xavier Young</h4><span class="font-medium">Manažer marketingu</span></div></li>
</ul></section><footer><h4>Not staff</h4><span>Kontakt</span></footer>'''


class TestCHL(unittest.TestCase):
    def test_games_of_the_finnish_clubs(self):
        games = chl.games_from(FEED, set(IDS), LIIGA_GAMES)
        self.assertEqual(sorted(games), ['chl:m1', 'chl:m2', 'chl:m3', 'chl:m5'])       # not Genève–Fribourg
        home = games['chl:m1']
        self.assertEqual(home['date'], '2026-11-11')
        self.assertEqual(home['teams'], ['933686567:saipa', 'chl:pardubice'])           # the Liiga preset, the CHL one
        self.assertEqual(home['names'], ['SaiPa Lappeenranta', 'Dynamo Pardubice'])
        self.assertEqual(home['series'], 'Mestarien liigan neljännesvälieräottelussa')
        self.assertEqual((home['rink'], home['city'], home['country'], home['code']),       # as in the club's Liiga games
                         ('Lappeenrannan jäähalli I', 'Lappeenranta', 'Finland', 'FI'))
        away = games['chl:m2']
        self.assertEqual((away['rink'], away['city'], away['country'], away['code']),
                         ('Enteria Arena', 'Pardubice', 'Czech Republic', 'CZ'))
        berlin = games['chl:m3']                                       # a club we have no roster for: still its game
        self.assertEqual(berlin['teams'], ['chl:eisbären-berlin', '461765763:kookoo'])
        self.assertEqual((berlin['city'], berlin['country']), ('', ''))                 # unknown, not "Finland"
        self.assertEqual(games['chl:m5']['series'], 'Mestarien liigan ottelussa')

    def test_esports_cz_roster(self):
        roster = chl.esports_cz('https://hcdynamo.cz/team/MUZ', page=PAGE)
        self.assertEqual([(r['number'], r['name'], r.get('role', '')) for r in roster],
                         [('32', 'Malcolm Subban', ''), ('19', 'Roman Červenka', ''), ('', 'Filip Pešán', 'Päävalmentaja'),
                          ('', 'Petr Hoza', 'Lääkäri'), ('', 'Xavier Young', 'Manažer marketingu')])
        self.assertEqual(roster[0]['image'], 'https://hcdynamo.cz/image?file=https://x.cz/Subban-Malcolm.png?1&w=651&h=768')

    def test_fetch_and_apply(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = Config(os.path.join(tmp, 'config.json'))
        with mock.patch.object(chl, '_get', side_effect=lambda url, timeout=20: json.dumps(FEED) if url == chl.LIVE
                               else PAGE):
            data = chl.fetch(IDS, LIIGA_GAMES)
        self.assertEqual([t['id'] for t in data['teams']], ['chl:pardubice'])          # only clubs we can read
        team = data['teams'][0]
        self.assertEqual([r['name'] for r in team['roster']][:3], ['Roman Červenka', 'Malcolm Subban', 'Filip Pešán'])
        self.assertEqual(liiga.apply(cfg, data), (1, 0))
        p = next(p for p in cfg.tag_presets if p.get('liiga') == 'chl:pardubice')
        self.assertEqual((p['name'], p['keywords']), ('Dynamo Pardubice', 'Dynamo Pardubice, CHL'))
        self.assertIn('chl:m1', liiga.load_games(cfg))
        self.assertEqual(liiga.game_on(liiga.load_games(cfg), datetime.date(2026, 11, 11),
                                       ['933686567:saipa', 'chl:pardubice'])['rink'], 'Lappeenrannan jäähalli I')


if __name__ == '__main__':
    unittest.main()
