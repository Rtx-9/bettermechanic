"""Liiga teams as tag presets: bundled snapshot, staff, referees and games, updates, avatar crop for cut-outs."""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from bettermechanic import avatars, liiga  # noqa: E402
from bettermechanic.config import Config, players  # noqa: E402


def row(pid, team, first, last, jersey, removed=False):
    return {'id': pid, 'teamId': f'1:{team.lower()}', 'teamName': team, 'firstName': first, 'lastName': last,
            'jersey': jersey, 'removed': removed, 'pictureUrl': f'https://x/{pid}.png'}


def detail(gid, start, home, away, refs):
    return {'game': {'id': gid, 'start': start, 'homeTeam': {'teamId': home}, 'awayTeam': {'teamId': away},
                     'iceRink': {'name': 'Oulun jäähalli', 'city': 'OULU'},
                     'referees': [{'firstName': f, 'lastName': l, 'roleAbbrv': a, 'pictureUrl': None}
                                  for f, l, a in refs]}}


class TestLiiga(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(os.path.join(self.tmp, 'config.json'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def preset(self, name):
        return next(p for p in self.cfg.tag_presets if p['name'] == name)

    def test_season(self):
        self.assertEqual(liiga.season_for(datetime.date(2026, 10, 22)), 2027)
        self.assertEqual(liiga.season_for(datetime.date(2027, 3, 1)), 2027)
        self.assertEqual(liiga.season_for(datetime.date(2027, 8, 1)), 2028)

    def test_teams_from(self):
        teams = liiga.teams_from([row(1, 'Tappara', 'Aa', 'Bb', 29), row(2, 'Tappara', 'Cc', 'Dd', 4),
                                  row(3, 'Tappara', 'Gone', 'Player', 9, removed=True), row(1, 'Tappara', 'Aa', 'Bb', 29),
                                  row(4, 'Tappara', 'No', 'Number', None), row(5, 'Ilves', 'Ee', 'Ff', 1)])
        self.assertEqual([t['name'] for t in teams], ['Ilves', 'Tappara'])
        self.assertEqual([(r['number'], r['name']) for r in teams[1]['roster']],
                         [('4', 'Cc Dd'), ('29', 'Aa Bb'), ('', 'No Number')])

    def test_staff_from_team_facts(self):
        info = {'teams': {'1:x': {'general_info': '<table><tbody><tr><td>Perustettu</td><td>1946</td></tr>'
                                                  '<tr><td>Puheenjohtaja</td><td>Juha Junno</td></tr>'
                                                  '<tr><td>Päävalmentaja</td><td>Petri Karjalainen</td></tr>'
                                                  '<tr><td>Kapteenisto</td><td>C Someone Else</td></tr>'
                                                  '</tbody></table>'}}}
        self.assertEqual([(s['name'], s['role']) for s in liiga.staff_from(info)['1:x']],
                         [('Juha Junno', 'Puheenjohtaja'), ('Petri Karjalainen', 'Päävalmentaja')])

    def test_club_staff_wins_over_stale_league_facts(self):
        league = [{'name': 'Old Coach', 'number': '', 'image': '', 'role': 'Päävalmentaja'},
                  {'name': 'Same Person', 'number': '', 'image': '', 'role': 'Päävalmentaja'}]
        club = [{'name': 'Same Person', 'role': 'Valmentaja', 'image': 'p.jpg', 'generic': True},
                {'name': 'Kit Man', 'role': 'Huoltaja', 'image': ''}]
        merged = {p['name']: p for p in liiga.merge_staff(league, club)}
        self.assertNotIn('Old Coach', merged)                          # liiga.fi still lists a former coach
        self.assertEqual(merged['Same Person']['role'], 'Päävalmentaja')   # but knows who's the head coach
        self.assertEqual(merged['Kit Man']['role'], 'Huoltaja')
        self.assertEqual(len(liiga.merge_staff(league, [])), 2)         # a club with no staff page
        order = sorted([{'name': 'B', 'number': '', 'role': 'Huoltaja'}, {'name': 'A', 'number': '', 'role': 'Valmentaja'},
                        {'name': 'C', 'number': '', 'role': 'Päävalmentaja'}, {'name': 'D', 'number': '9', 'role': ''}],
                       key=liiga._order)
        self.assertEqual([r['name'] for r in order], ['D', 'C', 'A', 'B'])

    def test_game_and_its_referees(self):
        gid, rec, refs = liiga.game_from(detail(7, '2026-10-21T15:30:00Z', '1:a', '1:b',
                                                [('Ref', 'One', 'PT'), ('Line', 'Two', 'LT')]))
        self.assertEqual(gid, 7)
        self.assertEqual(rec, {'date': '2026-10-21', 'teams': ['1:a', '1:b'], 'refs': ['Ref One', 'Line Two'],
                               'rink': 'Oulun jäähalli', 'city': 'Oulu'})
        self.assertEqual(refs['Line Two']['role'], 'Linesman')
        late = liiga.game_from(detail(8, '2026-10-21T22:30:00Z', '1:a', '1:b', []))[1]
        self.assertEqual(late['date'], '2026-10-22')                    # Finnish local date, not UTC
        games = {'2027:7': rec}
        self.assertIs(liiga.game_on(games, datetime.date(2026, 10, 21), ['1:b', '1:a']), rec)
        self.assertIs(liiga.game_on(games, datetime.date(2026, 10, 21), ['1:a', None]), rec)
        self.assertIsNone(liiga.game_on(games, datetime.date(2026, 10, 21), ['1:a', '1:c']))
        self.assertIsNone(liiga.game_on(games, datetime.date(2026, 10, 20), ['1:a', '1:b']))

    def test_snapshot(self):
        data = liiga.snapshot()
        self.assertEqual(data['season'], 2027)
        self.assertEqual(len(data['teams']), 17)
        self.assertTrue(all(len(t['roster']) >= 20 for t in data['teams']))
        self.assertGreater(len(data['officials']), 20)
        self.assertGreater(len(data['games']), 50)
        karpat = next(t for t in data['teams'] if t['name'] == 'Kärpät')
        roles = [r.get('role') for r in karpat['roster']]
        self.assertIn('Päävalmentaja', roles)
        self.assertGreater(sum(1 for r in roles if r), 8)              # the club's whole staff, not just three

    def test_added_once_with_referees_and_games(self):
        before = len(self.cfg.tag_presets)
        self.assertEqual(liiga.add_bundled(self.cfg), 18)                # 17 teams + referees
        self.assertEqual(liiga.add_bundled(self.cfg), 0)
        self.assertEqual(len(self.cfg.tag_presets), before + 18)
        kalpa = self.preset('KalPa')
        self.assertEqual(kalpa['keywords'], 'KalPa, Liiga')
        self.assertGreater(len(players(kalpa)), 20)
        refs = self.preset('Liiga Referees')
        self.assertEqual(refs['liiga'], liiga.REFEREES)
        self.assertEqual({r['role'] for r in refs['roster']}, {'Referee', 'Linesman'})
        self.assertGreater(len(liiga.load_games(self.cfg)), 50)
        self.cfg.save()
        again = Config(os.path.join(self.tmp, 'config.json'))       # roles survive saving and loading
        staff = [r for r in next(p for p in again.tag_presets if p['name'] == 'KalPa')['roster'] if r['role']]
        self.assertTrue(staff and all(r['liiga'] for r in staff))

    def test_upgrade_from_teams_only(self):
        self.cfg.settings['liiga_added'] = True                      # 0.6 / 0.7: teams without staff or referees
        self.cfg.settings['liiga_checked'] = '2026-10-22'
        team = liiga.snapshot()['teams'][0]
        liiga.apply(self.cfg, {'teams': [dict(team, roster=[r for r in team['roster'] if not r.get('role')])]})
        p = self.preset(team['name'])
        for r in p['roster']:
            r.pop('liiga')
        self.assertEqual(liiga.add_bundled(self.cfg), 1)             # just the referees
        self.assertTrue(all(r['liiga'] for r in p['roster']))       # existing people marked as from liiga.fi
        self.assertEqual(self.cfg.settings['liiga_checked'], '')     # refresh soon to get the staff
        self.assertIsNotNone(self.preset('Liiga Referees'))

    def test_upgrade_from_08_brings_club_staff_but_not_deleted_teams(self):
        liiga.add_bundled(self.cfg)
        for p in self.cfg.tag_presets:                                # as 0.8 had them: three staff at most
            p['roster'] = [r for r in p['roster'] if not r['role'] or r['role'] == 'Päävalmentaja']
        self.cfg.tag_presets = [p for p in self.cfg.tag_presets if p['name'] != 'HPK']
        self.cfg.settings['liiga_bundle'] = 2
        n = len(self.cfg.tag_presets)
        self.assertEqual(liiga.add_bundled(self.cfg), 0)
        self.assertEqual(len(self.cfg.tag_presets), n)                # HPK stays deleted
        self.assertGreater(sum(1 for r in self.preset('Kärpät')['roster'] if r['role']), 8)

    def test_update_keeps_your_own_settings_and_people(self):
        liiga.add_bundled(self.cfg)
        p = self.preset('Tappara')
        p['slots'][0], p['keywords'], p['name'] = 'Captain', 'Tampere', 'Tappara (home)'
        p['roster'].append({'name': 'My Assistant', 'number': '', 'image': '', 'role': 'Assistant coach'})
        team = {'id': p['liiga'], 'name': 'Tappara', 'roster': [{'name': 'New Guy', 'number': '99', 'image': ''}]}
        self.assertEqual(liiga.apply(self.cfg, {'teams': [team]}), (0, 1))
        self.assertEqual([r['name'] for r in p['roster']], ['New Guy', 'My Assistant'])   # departed players gone
        self.assertEqual((p['slots'][0], p['keywords'], p['name']), ('Captain', 'Tampere', 'Tappara (home)'))
        self.assertEqual(liiga.apply(self.cfg, {'teams': [team]}), (0, 0))                # nothing new

    def test_referees_only_grow(self):
        liiga.add_bundled(self.cfg)
        n = len(self.preset('Liiga Referees')['roster'])
        new = {'Brand New': {'name': 'Brand New', 'number': '', 'image': '', 'role': 'Referee'}}
        liiga.apply(self.cfg, {'teams': [], 'officials': new, 'games': {'2027:999': {
            'date': '2027-01-01', 'teams': ['a', 'b'], 'refs': ['Brand New']}}})
        refs = self.preset('Liiga Referees')['roster']
        self.assertEqual(len(refs), n + 1)
        self.assertIn('2027:999', liiga.load_games(self.cfg))
        self.assertIn('2027:2701274', liiga.load_games(self.cfg))   # earlier games kept

    def test_deleted_team_comes_back_only_when_asked(self):
        liiga.add_bundled(self.cfg)
        data = liiga.snapshot()
        self.cfg.tag_presets = [p for p in self.cfg.tag_presets if p['name'] != 'HPK']
        self.assertEqual(liiga.apply(self.cfg, data, add_missing=False)[0], 0)       # daily check
        self.assertEqual(liiga.apply(self.cfg, data)[0], 1)                          # Update Liiga Rosters

    def test_due(self):
        today = datetime.date(2026, 10, 22)
        self.assertFalse(liiga.due(self.cfg, today))                 # no Liiga presets yet
        liiga.add_bundled(self.cfg)
        self.assertTrue(liiga.due(self.cfg, today))
        self.cfg.settings['liiga_checked'] = today.isoformat()
        self.assertFalse(liiga.due(self.cfg, today))
        self.cfg.settings['liiga_auto_update'] = False
        self.assertFalse(liiga.due(self.cfg, today + datetime.timedelta(days=1)))

    def test_crop_centres_on_the_face(self):
        wide = Image.new('RGB', (1200, 800))
        with mock.patch.object(avatars, 'find_face', return_value=(900, 100, 80, 100)):
            box = avatars._square(wide)
        self.assertEqual(box.size[0], box.size[1])
        self.assertEqual(box.size[0], 260)                          # head and shoulders, not the whole picture
        with mock.patch.object(avatars, 'find_face', return_value=None):
            self.assertEqual(avatars._square(wide).size, (800, 800))   # no face found: centre crop as before

    def test_cutout_avatar(self):
        im = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
        def noise(add):                                            # photo-like detail, its own in every channel
            return Image.effect_noise((600, 600), 40).point(lambda v: min(255, max(0, v - 128 + add)))
        head = Image.merge('RGB', [noise(210), noise(160), noise(130)])
        shirt = Image.merge('RGB', [noise(40), noise(60), noise(190)])
        im.paste(head.crop((250, 40, 350, 180)), (250, 40))
        im.paste(shirt.crop((80, 220, 520, 600)), (80, 220))
        src, dest = os.path.join(self.tmp, 'p.png'), os.path.join(self.tmp, 'a.jpg')
        im.save(src)
        avatars.make_avatar_file(src, dest)
        out = Image.open(dest).convert('RGB')
        self.assertEqual(out.size, (avatars.SIZE, avatars.SIZE))
        r, g, b = out.getpixel((4, 4))
        self.assertGreater(min(r, g, b), 200)                        # light background, not black
        r, g, b = out.getpixel((avatars.SIZE // 2, avatars.SIZE // 4))
        self.assertGreater(r, 150)                                   # the head is in frame


if __name__ == '__main__':
    unittest.main()
