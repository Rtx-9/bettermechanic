"""Lightroom Classic plugin: the data the app writes for it, installing it, and the plugin's own Lua code
(run with Lua 5.1, Lightroom's version, against stand-ins for Lightroom's modules; skipped without lupa)."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from bettermechanic import lightroom, liiga  # noqa: E402
from bettermechanic.config import Config, tag_preset  # noqa: E402

try:
    from lupa.lua51 import LuaRuntime
except ImportError:                     # pragma: no cover - optional test dependency
    LuaRuntime = None

PLUGIN = lightroom.plugin_source()

STUBS = r'''
STUB = { log = {}, kw = {}, written = 0, dialogs = {} }
local function path_child(a, b) return a .. '/' .. b end
os.getenv = function(k) return STUB.env and STUB.env[k] end
local modules = {
  LrPathUtils = {
    child = path_child,
    getStandardFilePath = function(kind) return kind == 'appData' and STUB.lrAppData or '/home' end,
    leafName = function(p) return p:match('([^/]+)$') end,
    parent = function(p) return p:match('^(.*)/[^/]+$') or p end,
  },
  LrFileUtils = {
    exists = function(p) return STUB.files[p] ~= nil end,
    readFile = function(p) return STUB.files[p] end,
  },
  LrDate = { timeToUserFormat = function(t, fmt) return STUB.days[t] end },
  LrDialogs = {
    message = function(a, b) STUB.log[#STUB.log + 1] = 'message: ' .. b end,
    attachErrorDialogToFunctionContext = function() end,
    presentFloatingDialog = function(plugin, args) STUB.dialog = args end,
  },
  LrFunctionContext = { postAsyncTaskWithContext = function(name, fn) fn({}) end },
  LrPrefs = { prefsForPlugin = function() return STUB.prefs end },
  LrTasks = {
    startAsyncTask = function(fn) fn() end,
    sleep = function() STUB.dialog.windowWillClose() end,      -- the window closes during the first wait
  },
  LrBinding = { makePropertyTable = function()
    local t = { observers = {} }
    function t:addObserver(key, fn) self.observers[key] = fn end
    return t
  end },
  LrView = {
    bind = function(k) return { bind = k } end,
    osFactory = function()
      return setmetatable({}, { __index = function(_, kind)
        return function(self, spec) spec.kind = kind; return spec end
      end })
    end,
  },
  LrApplication = { activeCatalog = function() return STUB.catalog end },
}
function import(name) return assert(modules[name], 'no stub for ' .. name) end
_PLUGIN = {}

-- a catalog with photos whose keywords are names
function makePhoto(id, names, day, meta)
  local p = { localIdentifier = id, kws = {}, meta = meta or {}, day = day }
  for _, n in ipairs(names) do p.kws[n] = true end
  function p:getRawMetadata(key)
    if key == 'keywords' then
      local out = {}
      for n in pairs(self.kws) do out[#out + 1] = { getName = function() return n end } end
      return out
    elseif key == 'dateTimeOriginal' then return self.day end
  end
  function p:addKeyword(kw) self.kws[kw.name] = true end
  function p:removeKeyword(kw) self.kws[kw.name] = nil end
  function p:getFormattedMetadata(key) return self.meta[key] or '' end
  function p:setRawMetadata(key, value) self.meta[key] = value end
  return p
end
function makeCatalog(photos)
  local c = { photos = photos }
  function c:getTargetPhoto() return self.photos[1] end
  function c:getTargetPhotos() return self.photos end
  function c:createKeyword(name) STUB.kw[name] = true; return { name = name } end
  function c:withWriteAccessDo(title, fn) STUB.written = STUB.written + 1; fn() end
  return c
end
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(os.path.join(self.tmp, 'config.json'))
        home, away = tag_preset('Home'), tag_preset('Away')
        home['liiga'], away['liiga'], home['keywords'] = '1:kärpät', '1:saipa', 'Home, Liiga'
        home['roster'] = [{'name': 'Aa Bee', 'number': '29', 'image': ''},
                          {'name': 'Cc Coach', 'number': '', 'image': '', 'role': 'Päävalmentaja'}]
        away['roster'] = [{'name': 'Dd Away', 'number': '7', 'image': ''}]
        refs = tag_preset('Liiga Referees')
        refs['liiga'] = liiga.REFEREES
        refs['roster'] = [{'name': f'Ref {i}', 'number': '', 'image': '', 'role': 'Referee' if i < 3 else 'Linesman'}
                          for i in range(6)]
        self.cfg.tag_presets = [home, away, refs]
        liiga.save_games(self.cfg, {'2027:1': {'date': '2026-10-21', 'teams': ['1:saipa', '1:kärpät'],
                                               'refs': ['Ref 4', 'Ref 1'], 'rink': 'Lappeenrannan jäähalli I',
                                               'city': 'Lappeenranta'}})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestExport(Base):
    def test_players_file_and_pictures(self):
        people, drawn = lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        self.assertEqual((people, drawn), (9, 9))
        out = lightroom.data_dir(self.cfg)
        with open(os.path.join(out, 'players.txt'), encoding='utf-8') as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0], 'v\t1')
        self.assertEqual(lines[1], 'd\t\t')                                    # no teams chosen in the app yet
        self.assertIn('\t'.join(['t', self.cfg.tag_presets[0]['id'], 'Home', '1:kärpät', 'Home, Liiga', 'Kärppien']),
                      lines)
        self.assertTrue(os.path.exists(os.path.join(out, 'img', 'h_staff.png')))
        self.assertTrue(any(ln.startswith('p\tCc Coach\t\tPäävalmentaja\t') for ln in lines))
        self.assertIn('g\t2026-10-21\t1:saipa\t1:kärpät\tRef 4|Ref 1\tLappeenrannan jäähalli I\tLappeenranta\t'
                      'Lappeenrannassa', lines)
        pic = next(ln for ln in lines if ln.startswith('p\tAa Bee')).split('\t')[4]
        with Image.open(os.path.join(out, 'img', pic)) as im:
            self.assertEqual(im.size, (lightroom.SIZE, lightroom.SIZE))
            self.assertEqual(im.getpixel((0, 0))[3], 0)                       # round: transparent corners
        self.assertEqual(lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)[1], 0)
        self.cfg.tag_presets[1]['roster'] = []                                # pictures nobody uses are removed
        lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        self.assertEqual(len(os.listdir(os.path.join(out, 'img'))), 8 + 1 + 4)   # 8 people, blank, 4 headings
        self.cfg.settings['team_panel'] = [self.cfg.tag_presets[1]['id'], self.cfg.tag_presets[0]['id']]
        lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        with open(os.path.join(out, 'players.txt'), encoding='utf-8') as fh:
            self.assertEqual(fh.read().splitlines()[1], f'd\t{self.cfg.settings["team_panel"][0]}\t'
                                                        f'{self.cfg.settings["team_panel"][1]}')

    def test_install(self):
        with mock.patch.object(lightroom, 'modules_dir', return_value=os.path.join(self.tmp, 'Modules')):
            self.assertFalse(lightroom.installed())
            dest = lightroom.install()
            self.assertTrue(lightroom.installed())
            self.assertTrue(lightroom.up_to_date())
            self.assertTrue(os.path.exists(os.path.join(dest, 'Players.lua')))
            lightroom.install()                                               # again: replaces it


@unittest.skipIf(LuaRuntime is None, 'lupa (Lua 5.1) not installed')
class TestPluginLua(Base):
    def setUp(self):
        super().setUp()
        lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.lua.execute(f'package.path = [[{PLUGIN}]] .. "/?.lua;" .. package.path')
        folder = lightroom.data_dir(self.cfg).replace('\\', '/')
        stub = self.lua.globals().STUB
        stub.appdata = os.path.dirname(os.path.dirname(folder))
        stub.env = self.lua.table_from({'APPDATA': stub.appdata})
        files = self.lua.table()
        with open(os.path.join(folder, 'players.txt'), encoding='utf-8') as fh:
            files[f'{stub.appdata}/BetterMechanic/lightroom/players.txt'] = fh.read()
        stub.files = files
        stub.days = self.lua.table_from({1000: '2026-10-21', 2000: '2026-10-22'})
        stub.prefs = self.lua.table()
        self.data = self.lua.eval('require("Data").load()')

    def test_every_file_compiles(self):
        for name in os.listdir(PLUGIN):
            if name.endswith('.lua'):
                with open(os.path.join(PLUGIN, name), encoding='utf-8') as fh:
                    ok, err = self.lua.eval('function(src, n) local f, e = loadstring(src, n) '
                                            'return f ~= nil, tostring(e) end')(fh.read(), name)
                self.assertTrue(ok, f'{name}: {err}')
        info = self.lua.eval(f'dofile([[{PLUGIN}/Info.lua]])')
        self.assertEqual(info.LrLibraryMenuItems[1].file, 'Players.lua')

    def test_data_folder(self):
        data = self.lua.eval('require("Data")')
        self.assertEqual(data.folder(), self.lua.globals().STUB.appdata + '/BetterMechanic/lightroom')
        stub = self.lua.globals().STUB
        stub.env = None                     # no APPDATA: Lightroom's "appData" is …/Roaming/Adobe/Lightroom
        stub.lrAppData = 'C:/Users/x/AppData/Roaming/Adobe/Lightroom'
        self.assertEqual(data.folder(), 'C:/Users/x/AppData/Roaming/BetterMechanic/lightroom')
        stub.lrAppData = None               # a Mac: ~/Library/Application Support
        self.assertEqual(data.folder(), '/home/Library/Application Support/BetterMechanic/lightroom')

    def test_data(self):
        d = self.data
        self.assertEqual([d.teams[i].name for i in (1, 2, 3)], ['Home', 'Away', 'Liiga Referees'])
        self.assertEqual(d.referees.name, 'Liiga Referees')
        aa = d.teams[1].people[1]
        self.assertEqual((aa.name, aa.number, aa.role), ('Aa Bee', '29', ''))
        self.assertTrue(aa.image.endswith('.png') and '/img/' in aa.image)
        self.assertEqual(d.games[1].refs[2], 'Ref 1')

    def test_model(self):
        model = self.lua.eval('require("Model")')
        d = self.data
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:kärpät', '1:saipa').date, '2026-10-21')
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:kärpät', '').date, '2026-10-21')      # one team is enough
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:kärpät', None).date, '2026-10-21')
        self.assertIsNone(model.gameFor(d, '2026-10-22', '1:kärpät', '1:saipa'))
        self.assertIsNone(model.gameFor(d, None, '1:kärpät', '1:saipa'))
        props, shown = self.lua.table(), self.lua.table()
        counts = self.lua.table_from({'Aa Bee': 2, 'Dd Away': 1})
        game = model.gameFor(d, '2026-10-21', '1:kärpät', '1:saipa')
        model.fillAll(props, shown, d, d.teams[1], d.teams[2], counts, 2, game)
        # home: player, Staff heading, coach, then hidden tiles
        self.assertEqual(props['a_1_title'], '✓ #29 Bee')
        self.assertTrue(props['a_2_vis'])
        self.assertFalse(props['a_2_btn'])                                     # a heading: picture only
        self.assertTrue(props['a_2_img'].endswith('h_staff.png'))
        self.assertIsNone(shown['a_2'])
        self.assertEqual((props['a_3_title'], props['a_3_tip']), ('Coach', 'Cc Coach  ·  Päävalmentaja'))
        self.assertFalse(props['a_4_vis'] or props['a_4_btn'])
        self.assertTrue(props['a_4_img'].endswith('blank.png'))
        self.assertEqual(props['b_1_title'], '• #7 Away')
        self.assertFalse(props['b_2_vis'])                                     # no staff, no heading
        # referees: THIS GAME heading, the game's two (as the game lists them), REFEREES, LINESMEN
        titles = [props[f'r_{i}_title'] for i in range(1, 11)]
        self.assertEqual(titles, ['', '4', '1', '', '0', '2', '', '3', '5', ''])
        self.assertTrue(props['r_1_img'].endswith('h_game.png'))
        self.assertTrue(props['r_7_img'].endswith('h_linesmen.png'))
        self.assertEqual(shown['r_2'].name, 'Ref 4')
        model.fillAll(props, shown, d, d.teams[1], None, counts, 2, None)     # no game: no THIS GAME heading
        self.assertTrue(props['r_1_img'].endswith('h_referees.png'))

    def test_tagging(self):
        lua = self.lua
        photos = lua.eval('{ makePhoto(1, {}, 1000), makePhoto(2, {"Aa Bee"}, 1000) }')
        catalog = lua.eval('makeCatalog')(photos)
        tagging = lua.eval('require("Tagging")')
        entry = self.data.teams[1].people[1]
        self.assertEqual(tagging.toggle(catalog, photos, entry), ('added', 0))
        self.assertTrue(photos[1].kws['Aa Bee'] and photos[1].kws['Home'] and photos[1].kws['Liiga'])
        self.assertEqual(photos[1].meta.personShown, 'Aa Bee')
        self.assertEqual(tagging.toggle(catalog, photos, entry)[0], 'removed')   # everyone had it: off again
        self.assertIsNone(photos[1].kws['Aa Bee'])
        self.assertTrue(photos[1].kws['Home'])                                     # team keywords stay, like the app
        self.assertEqual(photos[2].meta.personShown, '')
        self.assertIsNone(photos[1].meta.caption)                                  # no caption set: none written
        self.assertEqual(tagging.day(photos[1]), '2026-10-21')
        counts, n = tagging.counts(photos, 300)
        self.assertEqual(n, 2)
        empty = lua.eval('makeCatalog({})')
        self.assertEqual(len(list(tagging.selection(empty).values())), 0)       # nothing selected: nothing tagged

    def test_caption_text(self):
        cap = self.lua.eval('require("Caption")')
        d = self.data
        index = cap.index(d, d.teams[1], d.teams[2])
        names = self.lua.table_from
        self.assertEqual(cap.longDate('2026-10-20'), '20. lokakuuta 2026')
        self.assertEqual(cap.people(names(['Aa Bee']), index), 'Kärppien Aa Bee (29)')
        self.assertEqual(cap.people(names(['Aa Bee', 'Dd Away']), index), 'Kärppien Aa Bee (29) ja SaiPan Dd Away (7)')
        self.assertEqual(cap.people(names(['Aa Bee', 'Cc Coach', 'Dd Away', 'Ref 4']), index),
                         'Kärppien Aa Bee (29) ja päävalmentaja Cc Coach, SaiPan Dd Away (7) sekä linjatuomari Ref 4')
        self.assertEqual(cap.people(names(['Someone Else']), index), 'Someone Else')    # not in any team
        template, info = cap.fromGame(d, d.games[1])
        self.assertEqual(template, '{people} Liigan ottelussa Away–Home Lappeenrannassa 21. lokakuuta 2026.')
        self.assertEqual((info.headline, info.city, info.country, info.isoCountryCode, info.location),
                         ('Away–Home', 'Lappeenranta', 'Finland', 'FI', 'Lappeenrannan jäähalli I'))
        self.assertEqual(cap.render(template, 'Kärppien Aa Bee (29)'),
                         'Kärppien Aa Bee (29) Liigan ottelussa Away–Home Lappeenrannassa 21. lokakuuta 2026.')
        self.assertEqual(cap.render('{people}, Oulu', 'linjatuomari X'), 'Linjatuomari X, Oulu')

    def test_caption_follows_the_people(self):
        cap = self.lua.eval('require("Caption")')
        t = '{people} Liigan ottelussa.'
        self.assertEqual(cap.update('', t, '', 'A (1)'), 'A (1) Liigan ottelussa.')
        self.assertEqual(cap.update('A (1) Liigan ottelussa.', t, 'A (1)', 'A (1) ja B (2)'),
                         'A (1) ja B (2) Liigan ottelussa.')
        self.assertEqual(cap.update('A (1) Liigan ottelussa.', t, 'A (1)', ''), '')        # last one off: empty again
        # your own wording: only the names change
        self.assertEqual(cap.update('Maali! A (1) tuulettaa.', t, 'A (1)', 'A (1) ja B (2)'),
                         'Maali! A (1) ja B (2) tuulettaa.')
        self.assertIsNone(cap.update('Yleisö juhlii.', t, '', 'A (1)'))                  # no names in it: left alone
        self.assertIsNone(cap.update('', '', '', 'A (1)'))                                # no template: nothing

    def test_tagging_writes_caption_and_game_details(self):
        lua = self.lua
        photos = lua.eval('''{ makePhoto(1, {}, 1000), makePhoto(2, {}, 1000, { caption = 'Yleisö juhlii.', city = 'Oulu' }) }''')
        catalog = lua.eval('makeCatalog')(photos)
        tagging, cap = lua.eval('require("Tagging")'), lua.eval('require("Caption")')
        d = self.data
        template, info = cap.fromGame(d, d.games[1])
        opts = lua.table_from({'template': template, 'index': cap.index(d, d.teams[1], d.teams[2]), 'info': info})
        self.assertEqual(tagging.toggle(catalog, photos, d.teams[1].people[1], opts), ('added', 1))
        self.assertEqual(photos[1].meta.caption,
                         'Kärppien Aa Bee (29) Liigan ottelussa Away–Home Lappeenrannassa 21. lokakuuta 2026.')
        self.assertEqual(photos[2].meta.caption, 'Yleisö juhlii.')                  # your own caption stays
        self.assertEqual((photos[1].meta.headline, photos[1].meta.city, photos[1].meta.location),
                         ('Away–Home', 'Lappeenranta', 'Lappeenrannan jäähalli I'))
        self.assertEqual(photos[2].meta.city, 'Oulu')                               # filled in only where empty
        tagging.toggle(catalog, lua.eval('function(p) return { p } end')(photos[1]), d.teams[2].people[1], opts)
        self.assertEqual(photos[1].meta.personShown, 'Aa Bee, Dd Away')
        self.assertTrue(photos[1].meta.caption.startswith('Kärppien Aa Bee (29) ja SaiPan Dd Away (7) Liigan'))
        tagging.toggle(catalog, lua.eval('function(p) return { p } end')(photos[1]), d.teams[1].people[1], opts)
        self.assertTrue(photos[1].meta.caption.startswith('SaiPan Dd Away (7) Liigan'))   # Aa Bee taken off

    def test_window_builds_and_tags(self):
        lua = self.lua
        photos = lua.eval('{ makePhoto(1, {}, 1000) }')
        lua.globals().STUB.catalog = lua.eval('makeCatalog')(photos)
        lua.execute(f'dofile([[{PLUGIN}/Players.lua]])')
        stub = lua.globals().STUB
        dialog = stub.dialog
        self.assertEqual(dialog.title, 'BetterMechanic Players')
        self.assertEqual(dialog.contents.kind, 'column')
        props = dialog.contents.bind_to_object
        self.assertEqual(props.teamA, self.cfg.tag_presets[0]['id'])
        self.assertEqual(props['a_1_title'], '#29 Bee')
        self.assertEqual(props['r_2_title'], '4')                                 # the photo's game
        # find the button for Aa Bee and press it
        buttons = lua.eval('''function(root)
            local found = {}
            local function walk(v)
              if type(v) ~= 'table' then return end
              if v.kind == 'push_button' and v.title and v.title.bind then found[v.title.bind] = v end
              for _, c in ipairs(v) do walk(c) end
            end
            walk(root)
            return found
        end''')(dialog.contents)
        named = lua.eval('''function(root)
            local found = {}
            local function walk(v)
              if type(v) ~= 'table' then return end
              if v.kind == 'push_button' and type(v.title) == 'string' then found[v.title] = v end
              for _, c in ipairs(v) do walk(c) end
            end
            walk(root)
            return found
        end''')(dialog.contents)
        named['From Game'].action()                                                # caption for the photo's game
        self.assertEqual(props.template, '{people} Liigan ottelussa Away–Home Lappeenrannassa 21. lokakuuta 2026.')
        self.assertIn('Away–Home', props.infoText)
        self.assertEqual(stub.prefs.template, props.template)                      # remembered
        buttons['a_1_title'].action()
        self.assertTrue(photos[1].kws['Aa Bee'])
        self.assertEqual(props['a_1_title'], '✓ #29 Bee')
        self.assertIn('Tagged Aa Bee on 1 photo', props.status)
        self.assertEqual(photos[1].meta.caption,
                         'Kärppien Aa Bee (29) Liigan ottelussa Away–Home Lappeenrannassa 21. lokakuuta 2026.')
        self.assertEqual(photos[1].meta.location, 'Lappeenrannan jäähalli I')
        props.teamB = ''
        props.observers['teamB']()
        self.assertFalse(props['b_1_vis'])
        self.assertEqual(stub.prefs.teamB, '')
        props.showRefs = False                                                    # referees off: column empty
        props.observers['showRefs']()
        self.assertFalse(props['r_2_btn'])

    def test_window_opens_with_the_apps_teams(self):
        lua = self.lua
        self.cfg.settings['team_panel'] = [self.cfg.tag_presets[1]['id'], self.cfg.tag_presets[0]['id']]
        lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        with open(os.path.join(lightroom.data_dir(self.cfg), 'players.txt'), encoding='utf-8') as fh:
            stub = lua.globals().STUB
            stub.files[f'{stub.appdata}/BetterMechanic/lightroom/players.txt'] = fh.read()
        stub.catalog = lua.eval('makeCatalog({})')
        lua.execute(f'dofile([[{PLUGIN}/Players.lua]])')
        props = stub.dialog.contents.bind_to_object
        self.assertEqual((props.teamA, props.teamB), tuple(self.cfg.settings['team_panel']))
        self.assertEqual(props['a_1_title'], '#7 Away')


if __name__ == '__main__':
    unittest.main()
