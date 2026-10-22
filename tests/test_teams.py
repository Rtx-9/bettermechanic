"""Players panel: two teams side by side, click a tile to tag or untag the selected photos."""
import os
import shutil
import sys
import datetime
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([sys.argv[0], '-platform', 'offscreen'])

import samples  # noqa: E402
from bettermechanic import liiga  # noqa: E402
from bettermechanic.app import MainWindow  # noqa: E402
from bettermechanic.config import Config, tag_preset  # noqa: E402


def pump(secs=0.3):
    t = time.time()
    while time.time() - t < secs:
        APP.processEvents(QEventLoop.AllEvents, 20)


class TestTeamsPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patch = mock.patch('bettermechanic.lightroom.modules_dir', return_value=os.path.join(self.tmp, 'Modules'))
        patch.start()                                   # never the real Lightroom plugin folder
        self.addCleanup(patch.stop)
        self.cfg = Config(os.path.join(self.tmp, 'config.json'))
        self.cfg.settings.update(liiga_bundle=liiga.BUNDLE, liiga_auto_update=False, auto_save=False)
        home, away, refs = tag_preset('Home', ['Aa Home']), tag_preset('Away'), tag_preset('Liiga Referees')
        home['keywords'], away['keywords'] = 'HomeTeam', 'AwayTeam'
        home['liiga'], away['liiga'], refs['liiga'] = '1:home', '1:away', liiga.REFEREES
        away['roster'] = [{'name': 'Bb Away', 'number': '29', 'image': ''},
                          {'name': 'Cc Away', 'number': '7', 'image': ''},
                          {'name': 'Dd Coach', 'number': '', 'image': '', 'role': 'Head coach'}]
        refs['roster'] = [{'name': f'Ref {i}', 'number': '', 'image': '', 'role': 'Referee' if i < 4 else 'Linesman'}
                          for i in range(8)]
        self.cfg.tag_presets = [home, away, refs]
        self.cfg.active_tag = home['id']
        self.win = MainWindow(self.cfg)
        self.win.resize(1300, 900)
        self.win.show()
        folder = os.path.join(self.tmp, 'photos')
        os.makedirs(folder)
        samples.write_card(folder, 2)
        self.day = datetime.date.fromtimestamp(os.path.getmtime(folder))
        liiga.save_games(self.cfg, {'2027:1': {'date': self.day.isoformat(), 'teams': ['1:away', '1:home'],
                                               'refs': ['Ref 6', 'Ref 2']}})
        self.win.open_folder(folder)
        pump(0.6)
        self.panel = self.win.teams

    def tearDown(self):
        self.win.dirty.clear()
        self.win.loader.stop()
        self.win.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def click(self, side, name):
        grid = self.panel.cols[side].grid
        i = next(i for i, e in enumerate(grid.entries) if e['name'] == name)
        QTest.mouseClick(grid, Qt.LeftButton, Qt.NoModifier, grid.tile_rect(i).center().toPoint())
        pump(0.2)

    def test_two_teams_shown(self):
        self.assertTrue(self.panel.isVisible())
        self.assertEqual([c.preset()['name'] for c in self.panel.cols], ['Home', 'Away'])
        grid = self.panel.cols[1].grid
        self.assertEqual([(t, [e['name'] for e in ents]) for t, ents in grid.sections],
                         [('Players', ['Bb Away', 'Cc Away']), ('Staff', ['Dd Coach'])])
        self.assertEqual(len(grid.heads), 2)
        self.assertFalse(hasattr(self.win, 'keys'))                         # the old tag-key sidebar is gone

    def test_click_tags_and_untags_selection(self):
        self.win.grid.selectAll()
        pump()
        ts = self.win.targets()
        self.assertGreater(len(ts), 1)
        self.click(1, 'Bb Away')
        self.assertTrue(all('Bb Away' in it.meta['people'] for it in ts))
        self.assertTrue(all('AwayTeam' in it.meta['keywords'] for it in ts))     # the clicked team's keywords
        self.assertNotIn('HomeTeam', ts[0].meta['keywords'])
        self.assertEqual(self.panel.cols[1].grid.have.get('Bb Away'), len(ts))   # highlighted
        self.click(1, 'Bb Away')
        self.assertFalse(any('Bb Away' in it.meta['people'] for it in ts))

    def test_swap_hide_and_deleted_team(self):
        self.panel.swap()
        self.assertEqual([c.preset()['name'] for c in self.panel.cols], ['Away', 'Home'])
        QTest.keyClick(self.win.grid, Qt.Key_B)
        self.assertFalse(self.panel.isVisible())
        self.assertFalse(self.cfg.settings['teams_visible'])
        QTest.keyClick(self.win.grid, Qt.Key_B)
        self.assertTrue(self.panel.isVisible())
        self.cfg.tag_presets = self.cfg.tag_presets[:1]                     # "Away" deleted
        self.win.preset_changed(quiet=True)
        self.assertEqual(self.panel.cols[0].preset()['name'], 'Home')
        self.assertIsNone(self.panel.cols[1].preset())

    def test_referees_of_this_game_first(self):
        for it in self.win.items:                    # every sample photo was taken on the game day
            it.time = datetime.datetime.combine(self.day, datetime.time(19, 30)).timestamp()
        self.win.grid.setCurrentIndex(self.win.model.index(0, 0))
        self.panel.reload()
        refs = self.panel.refs
        self.assertTrue(refs.isVisible())
        self.assertEqual([(t, [e['name'] for e in ents]) for t, ents in refs.grid.sections],
                         [('This game', ['Ref 2', 'Ref 6']), ('Referees', ['Ref 0', 'Ref 1', 'Ref 3']),
                          ('Linesmen', ['Ref 4', 'Ref 5', 'Ref 7'])])
        self.click_ref('Ref 6')
        self.assertIn('Ref 6', self.win.items[0].meta['people'])
        self.panel.cols[1]._pick(3)                                         # a team not in that game
        self.assertEqual(self.panel.cols[1].preset()['name'], 'Liiga Referees')
        self.assertEqual(refs.grid.sections[0][0], 'Referees')
        self.panel.ref_btn.click()                                          # hide the referees
        self.assertFalse(refs.isVisible())
        self.assertFalse(self.cfg.settings['teams_refs'])

    def click_ref(self, name):
        grid = self.panel.refs.grid
        i = next(i for i, e in enumerate(grid.entries) if e['name'] == name)
        QTest.mouseClick(grid, Qt.LeftButton, Qt.NoModifier, grid.tile_rect(i).center().toPoint())
        pump(0.2)

    def test_tiles_flow_into_rows(self):
        g = self.panel.cols[0].grid
        g.set_entries([{'name': f'P {i}', 'number': str(i), 'image': ''} for i in range(30)])
        pump()
        rows = -(-30 // g.cols())
        self.assertEqual(g.minimumHeight(), rows * g.TILE.height() + 4)
        self.assertEqual(g.index_at(g.tile_rect(13).center().toPoint()), 13)


if __name__ == '__main__':
    unittest.main()
