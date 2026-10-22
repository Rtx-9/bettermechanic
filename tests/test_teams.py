"""Players panel: two teams side by side, click a tile to tag or untag the selected photos."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([sys.argv[0], '-platform', 'offscreen'])

import samples  # noqa: E402
from bettermechanic.app import MainWindow  # noqa: E402
from bettermechanic.config import Config, tag_preset  # noqa: E402


def pump(secs=0.3):
    t = time.time()
    while time.time() - t < secs:
        APP.processEvents(QEventLoop.AllEvents, 20)


class TestTeamsPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(os.path.join(self.tmp, 'config.json'))
        self.cfg.settings.update(liiga_added=True, liiga_auto_update=False, auto_save=False)
        home, away = tag_preset('Home', ['Aa Home']), tag_preset('Away')
        home['keywords'], away['keywords'] = 'HomeTeam', 'AwayTeam'
        away['roster'] = [{'name': 'Bb Away', 'number': '29', 'image': ''},
                          {'name': 'Cc Away', 'number': '7', 'image': ''}]
        self.cfg.tag_presets = [home, away]
        self.cfg.active_tag = home['id']
        self.win = MainWindow(self.cfg)
        self.win.resize(1300, 900)
        self.win.show()
        folder = os.path.join(self.tmp, 'photos')
        os.makedirs(folder)
        samples.write_card(folder, 2)
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
        self.assertEqual([e['name'] for e in self.panel.cols[1].grid.entries], ['Bb Away', 'Cc Away'])

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

    def test_tiles_flow_into_rows(self):
        g = self.panel.cols[0].grid
        g.set_entries([{'name': f'P {i}', 'number': str(i), 'image': ''} for i in range(30)])
        pump()
        rows = -(-30 // g.cols())
        self.assertEqual(g.minimumHeight(), rows * g.TILE.height() + 4)
        self.assertEqual(g.index_at(g.tile_rect(13).center().toPoint()), 13)


if __name__ == '__main__':
    unittest.main()
