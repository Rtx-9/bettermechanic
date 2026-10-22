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
local modules = {
  LrPathUtils = { child = path_child, getStandardFilePath = function() return STUB.appdata end },
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
function makePhoto(id, names, day)
  local p = { localIdentifier = id, kws = {}, personShown = '', day = day }
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
  function p:getFormattedMetadata(key) return self.personShown end
  function p:setRawMetadata(key, value) assert(key == 'personShown'); self.personShown = value end
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
        home['liiga'], away['liiga'], home['keywords'] = '1:home', '1:away', 'Home, Liiga'
        home['roster'] = [{'name': 'Aa Bee', 'number': '29', 'image': ''},
                          {'name': 'Cc Coach', 'number': '', 'image': '', 'role': 'Päävalmentaja'}]
        away['roster'] = [{'name': 'Dd Away', 'number': '7', 'image': ''}]
        refs = tag_preset('Liiga Referees')
        refs['liiga'] = liiga.REFEREES
        refs['roster'] = [{'name': f'Ref {i}', 'number': '', 'image': '', 'role': 'Referee' if i < 3 else 'Linesman'}
                          for i in range(6)]
        self.cfg.tag_presets = [home, away, refs]
        liiga.save_games(self.cfg, {'2027:1': {'date': '2026-10-21', 'teams': ['1:away', '1:home'],
                                               'refs': ['Ref 4', 'Ref 1']}})

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
        self.assertIn('\t'.join(['t', self.cfg.tag_presets[0]['id'], 'Home', '1:home', 'Home, Liiga']), lines)
        self.assertTrue(any(ln.startswith('p\tCc Coach\t\tPäävalmentaja\t') for ln in lines))
        self.assertIn('g\t2026-10-21\t1:away\t1:home\tRef 4|Ref 1', lines)
        pic = next(ln for ln in lines if ln.startswith('p\tAa Bee')).split('\t')[4]
        with Image.open(os.path.join(out, 'img', pic)) as im:
            self.assertEqual(im.size, (lightroom.SIZE, lightroom.SIZE))
            self.assertEqual(im.getpixel((0, 0))[3], 0)                       # round: transparent corners
        self.assertEqual(lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)[1], 0)
        self.cfg.tag_presets[1]['roster'] = []                                # pictures nobody uses are removed
        lightroom.export(self.cfg, os.path.join(self.tmp, 'avatars'), fetch_missing=False)
        self.assertEqual(len(os.listdir(os.path.join(out, 'img'))), 8 + 1)   # 8 people + blank.png

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
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:home', '1:away').date, '2026-10-21')
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:home', '').date, '2026-10-21')      # one team is enough
        self.assertEqual(model.gameFor(d, '2026-10-21', '1:home', None).date, '2026-10-21')
        self.assertIsNone(model.gameFor(d, '2026-10-22', '1:home', '1:away'))
        self.assertIsNone(model.gameFor(d, None, '1:home', '1:away'))
        props, shown = self.lua.table(), self.lua.table()
        counts = self.lua.table_from({'Aa Bee': 2, 'Dd Away': 1})
        game = model.gameFor(d, '2026-10-21', '1:home', '1:away')
        model.fillAll(props, shown, d, d.teams[1], d.teams[2], counts, 2, game)
        self.assertEqual(props['ap_1_title'], '✓ #29 Bee')
        self.assertEqual(props['as_1_title'], 'Coach')
        self.assertEqual(props['as_1_tip'], 'Cc Coach  ·  Päävalmentaja')
        self.assertEqual(props['bp_1_title'], '• #7 Away')
        self.assertFalse(props['ap_2_vis'])
        self.assertTrue(props['ap_row_1'])
        self.assertFalse(props['ap_row_2'])
        self.assertEqual(props['ap_head'], 'PLAYERS   1')
        self.assertEqual([props[f'rg_{i}_title'] for i in (1, 2)], ['4', '1'])       # this game's refs first
        self.assertEqual(props['rr_1_title'], '0')
        self.assertEqual(props['rl_1_title'], '3')
        self.assertEqual(shown['rg_1'].name, 'Ref 4')

    def test_tagging(self):
        lua = self.lua
        photos = lua.eval('{ makePhoto(1, {}, 1000), makePhoto(2, {"Aa Bee"}, 1000) }')
        catalog = lua.eval('makeCatalog')(photos)
        tagging = lua.eval('require("Tagging")')
        entry = self.data.teams[1].people[1]
        self.assertEqual(tagging.toggle(catalog, photos, entry), 'added')
        self.assertTrue(photos[1].kws['Aa Bee'] and photos[1].kws['Home'] and photos[1].kws['Liiga'])
        self.assertEqual(photos[1].personShown, 'Aa Bee')
        self.assertEqual(tagging.toggle(catalog, photos, entry), 'removed')      # everyone had it: off again
        self.assertIsNone(photos[1].kws['Aa Bee'])
        self.assertTrue(photos[1].kws['Home'])                                     # team keywords stay, like the app
        self.assertEqual(photos[2].personShown, '')
        self.assertEqual(tagging.day(photos[1]), '2026-10-21')
        counts, n = tagging.counts(photos, 300)
        self.assertEqual(n, 2)
        empty = lua.eval('makeCatalog({})')
        self.assertEqual(len(list(tagging.selection(empty).values())), 0)       # nothing selected: nothing tagged

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
        self.assertEqual(props['ap_1_title'], '#29 Bee')
        self.assertEqual(props['rg_1_title'], '4')                               # the photo's game
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
        buttons['ap_1_title'].action()
        self.assertTrue(photos[1].kws['Aa Bee'])
        self.assertEqual(props['ap_1_title'], '✓ #29 Bee')
        self.assertIn('Tagged Aa Bee on 1 photo', props.status)
        props.teamB = ''
        props.observers['teamB']()
        self.assertFalse(props['bp_1_vis'])
        self.assertEqual(stub.prefs.teamB, '')


if __name__ == '__main__':
    unittest.main()
