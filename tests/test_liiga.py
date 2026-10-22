"""Liiga teams as tag presets: bundled snapshot, updates from liiga.fi data, avatar crop for cut-out headshots."""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from bettermechanic import avatars, liiga  # noqa: E402
from bettermechanic.config import Config, players  # noqa: E402


def row(pid, team, first, last, jersey, removed=False):
    return {'id': pid, 'teamId': f'1:{team.lower()}', 'teamName': team, 'firstName': first, 'lastName': last,
            'jersey': jersey, 'removed': removed, 'pictureUrl': f'https://x/{pid}.png'}


class TestLiiga(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(os.path.join(self.tmp, 'config.json'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def test_snapshot(self):
        season, teams = liiga.snapshot()
        self.assertEqual(season, 2027)
        self.assertEqual(len(teams), 17)
        self.assertTrue(all(len(t['roster']) >= 20 for t in teams))
        self.assertIn('Kärpät', [t['name'] for t in teams])

    def test_added_once(self):
        before = len(self.cfg.tag_presets)
        self.assertEqual(liiga.add_bundled(self.cfg), 17)
        self.assertEqual(liiga.add_bundled(self.cfg), 0)
        self.assertEqual(len(self.cfg.tag_presets), before + 17)
        kalpa = next(p for p in self.cfg.tag_presets if p['name'] == 'KalPa')
        self.assertTrue(kalpa['liiga'])
        self.assertEqual(kalpa['keywords'], 'KalPa, Liiga')
        self.assertGreater(len(players(kalpa)), 20)
        self.cfg.save()
        again = Config(os.path.join(self.tmp, 'config.json'))       # survives saving and loading
        self.assertEqual(sum(1 for p in again.tag_presets if p['liiga']), 17)
        self.assertTrue(again.settings['liiga_added'])

    def test_update_keeps_your_own_settings(self):
        liiga.add_bundled(self.cfg)
        p = next(p for p in self.cfg.tag_presets if p['name'] == 'Tappara')
        p['slots'][0], p['keywords'], p['name'] = 'Captain', 'Tampere', 'Tappara (home)'
        team = {'id': p['liiga'], 'name': 'Tappara', 'roster': [{'name': 'New Guy', 'number': '99', 'image': ''}]}
        self.assertEqual(liiga.apply(self.cfg, [team]), (0, 1))
        self.assertEqual(p['roster'], team['roster'])
        self.assertEqual((p['slots'][0], p['keywords'], p['name']), ('Captain', 'Tampere', 'Tappara (home)'))
        self.assertEqual(liiga.apply(self.cfg, [team]), (0, 0))                 # nothing new

    def test_deleted_team_comes_back_only_when_asked(self):
        liiga.add_bundled(self.cfg)
        teams = liiga.snapshot()[1]
        self.cfg.tag_presets = [p for p in self.cfg.tag_presets if p['name'] != 'HPK']
        self.assertEqual(liiga.apply(self.cfg, teams, add_missing=False), (0, 0))   # daily check
        self.assertEqual(liiga.apply(self.cfg, teams), (1, 0))                      # Update Liiga Rosters

    def test_due(self):
        today = datetime.date(2026, 10, 22)
        self.assertFalse(liiga.due(self.cfg, today))                 # no Liiga presets yet
        liiga.add_bundled(self.cfg)
        self.assertTrue(liiga.due(self.cfg, today))
        self.cfg.settings['liiga_checked'] = today.isoformat()
        self.assertFalse(liiga.due(self.cfg, today))
        self.cfg.settings['liiga_auto_update'] = False
        self.assertFalse(liiga.due(self.cfg, today + datetime.timedelta(days=1)))

    def test_cutout_avatar(self):
        im = Image.new('RGBA', (600, 600), (0, 0, 0, 0))
        im.paste((200, 150, 120, 255), (250, 40, 350, 180))        # head
        im.paste((20, 40, 200, 255), (80, 220, 520, 600))          # jersey
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
