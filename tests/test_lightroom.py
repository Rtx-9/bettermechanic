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
STUB = { log = {}, kw = {}, written = 0, dialogs = {}, dirs = {} }
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
    exists = function(p) return STUB.files[p] ~= nil or STUB.dirs[p] ~= nil end,
    readFile = function(p) return STUB.files[p] end,
    files = function(dir)
      local list = {}
      for p in pairs(STUB.files) do
        if p:sub(1, #dir + 1) == dir .. '/' and not p:sub(#dir + 2):find('/') then list[#list + 1] = p end
      end
      local i = 0
      return function() i = i + 1; return list[i] end
    end,
    delete = function(p) STUB.files[p] = nil end,
  },
  LrDate = { timeToUserFormat = function(t, fmt) return STUB.days[t] end },
  LrDialogs = {
    message = function(a, b) STUB.log[#STUB.log + 1] = 'message: ' .. b end,
    showBezel = function(m) STUB.log[#STUB.log + 1] = 'bezel: ' .. m end,
    attachErrorDialogToFunctionContext = function() end,
    presentFloatingDialog = function(plugin, args)
      STUB.dialog, STUB.opened = args, (STUB.opened or 0) + 1
      if args.onShow then args.onShow({ toFront = function() end, close = function() args.windowWillClose() end }) end
    end,
  },
  LrFunctionContext = { postAsyncTaskWithContext = function(name, fn) fn({}) end },
  LrPrefs = { prefsForPlugin = function() return STUB.prefs end },
  LrTasks = {
    startAsyncTask = function(fn) fn() end,
    pcall = pcall,
    sleep = function()                    -- what the user does while the window is open; then they close it
      local step = STUB.steps and table.remove(STUB.steps, 1)
      if step then step(STUB.dialog.contents.bind_to_object) else STUB.dialog.windowWillClose() end
    end,
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
  function c:withWriteAccessDo(title, fn)
    if STUB.busy then return 'aborted' end
    STUB.written = STUB.written + 1; fn(); return 'executed'
  end
  -- adding photos: the catalog knows paths, a file that isn't an image can't be added
  c.byPath = {}
  function c:findPhotoByPath(path) return self.byPath[path] end
  function c:addPhoto(path)
    if path:sub(-4) == '.txt' then error('not a photo') end
    local p = makePhoto(path, {}); self.byPath[path] = p; return p
  end
  function c:createCollection(name, parent, existing)
    self.collection = self.collection or { name = name, photos = {} }
    local col = self.collection
    function col:removeAllPhotos() self.photos = {} end
    function col:addPhotos(ps) for _, p in ipairs(ps) do self.photos[#self.photos + 1] = p end end
    return col
  end
  function c:setActiveSources(s) self.sources = s end
  function c:setSelectedPhotos(active, all) self.selected = all end
  return c
end
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(os.path.join(self.tmp, 'BetterMechanic', 'config.json'))    # tmp is the plugin's APPDATA
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
                                               'city': 'Lappeenranta'},
                                    'chl:1': {'date': '2026-11-18', 'teams': ['chl:pardubice', '1:saipa'], 'refs': [],
                                              'names': ['Dynamo Pardubice', 'SaiPa Lappeenranta'],
                                              'rink': 'Enteria Arena', 'city': 'Pardubice', 'country': 'Czech Republic',
                                              'code': 'CZ'}})

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
                      'Lappeenrannassa\tLiiga\t\t\tFinland\tFI', lines)
        self.assertIn('g\t2026-11-18\tchl:pardubice\t1:saipa\t\tEnteria Arena\tPardubice\tPardubicessa\t'
                      'CHL\tDynamo Pardubice\tSaiPa Lappeenranta\t'
                      'Czech Republic\tCZ', lines)
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

    def test_send_and_result(self):
        name = lightroom.send(self.cfg, [os.path.join(self.tmp, 'a.NEF'), os.path.join(self.tmp, 'b.JPG')])
        req = os.path.join(lightroom.send_dir(self.cfg), name + '.txt')
        with open(req, encoding='utf-8') as fh:
            self.assertEqual(fh.read().splitlines(), [os.path.join(self.tmp, 'a.NEF'), os.path.join(self.tmp, 'b.JPG')])
        self.assertIsNone(lightroom.result(self.cfg, name))                    # Lightroom hasn't taken it yet
        later = lightroom.send(self.cfg, [])
        self.assertLess(name, later)                                          # the plugin takes them in order
        with open(os.path.join(lightroom.send_dir(self.cfg), name + '.done'), 'w') as fh:
            fh.write('1 1 0\n')
        self.assertEqual(lightroom.result(self.cfg, name), (1, 1, 0))
        self.assertFalse(os.path.exists(os.path.join(lightroom.send_dir(self.cfg), name + '.done')))

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
        self.assertEqual(cap.date('2026-09-05'), '05.09.2026')
        self.assertEqual(cap.people(names(['Aa Bee']), index), 'Kärppien Aa Bee (29)')
        self.assertEqual(cap.people(names(['Aa Bee', 'Dd Away']), index), 'Kärppien Aa Bee (29) ja SaiPan Dd Away (7)')
        self.assertEqual(cap.people(names(['Aa Bee', 'Cc Coach', 'Dd Away', 'Ref 4']), index),
                         'Kärppien Aa Bee (29) ja päävalmentaja Cc Coach, SaiPan Dd Away (7) sekä linjatuomari Ref 4')
        self.assertEqual(cap.people(names(['Someone Else']), index), 'Someone Else')    # not in any team
        template, info = cap.fromGame(d, d.games[1])
        self.assertEqual(template, '{people} Away–Home Liiga-ottelussa 21.10.2026.')
        self.assertEqual((info.headline, info.city, info.country, info.isoCountryCode, info.location),
                         ('Away–Home', 'Lappeenranta', 'Finland', 'FI', 'Lappeenrannan jäähalli I'))
        self.assertEqual(cap.render(template, 'Kärppien Aa Bee (29)'),
                         'Kärppien Aa Bee (29) Away–Home Liiga-ottelussa 21.10.2026.')
        self.assertEqual(cap.render('{people}, Oulu', 'linjatuomari X'), 'Linjatuomari X, Oulu')
        chl = next(g for g in d.games.values() if g.date == '2026-11-18')          # a CHL game abroad
        template, info = cap.fromGame(d, chl)
        self.assertEqual(template, '{people} Dynamo Pardubice–Away CHL-ottelussa 18.11.2026.')   # no preset for Pardubice: its CHL name
        self.assertEqual((info.headline, info.city, info.country, info.isoCountryCode, info.location),
                         ('Dynamo Pardubice–Away', 'Pardubice', 'Czech Republic', 'CZ', 'Enteria Arena'))

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
                         'Kärppien Aa Bee (29) Away–Home Liiga-ottelussa 21.10.2026.')
        self.assertEqual(photos[2].meta.caption, 'Yleisö juhlii.')                  # your own caption stays
        self.assertEqual((photos[1].meta.headline, photos[1].meta.city, photos[1].meta.location),
                         ('Away–Home', 'Lappeenranta', 'Lappeenrannan jäähalli I'))
        self.assertEqual(photos[2].meta.city, 'Oulu')                               # filled in only where empty
        tagging.toggle(catalog, lua.eval('function(p) return { p } end')(photos[1]), d.teams[2].people[1], opts)
        self.assertEqual(photos[1].meta.personShown, 'Aa Bee, Dd Away')
        self.assertTrue(photos[1].meta.caption.startswith('Kärppien Aa Bee (29) ja SaiPan Dd Away (7) Away–Home'))
        tagging.toggle(catalog, lua.eval('function(p) return { p } end')(photos[1]), d.teams[1].people[1], opts)
        self.assertTrue(photos[1].meta.caption.startswith('SaiPan Dd Away (7) Away–Home'))   # Aa Bee taken off

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
        self.assertEqual(props.template, '{people} Away–Home Liiga-ottelussa 21.10.2026.')
        self.assertIn('Away–Home', props.infoText)
        self.assertEqual(stub.prefs.template, props.template)                      # remembered
        buttons['a_1_title'].action()
        self.assertTrue(photos[1].kws['Aa Bee'])
        self.assertEqual(props['a_1_title'], '✓ #29 Bee')
        self.assertIn('Tagged Aa Bee on 1 photo', props.status)
        self.assertEqual(photos[1].meta.caption,
                         'Kärppien Aa Bee (29) Away–Home Liiga-ottelussa 21.10.2026.')
        self.assertEqual(photos[1].meta.location, 'Lappeenrannan jäähalli I')
        props.teamB = ''
        props.observers['teamB']()
        self.assertFalse(props['b_1_vis'])
        self.assertEqual(stub.prefs.teamB, '')
        props.showRefs = False                                                    # referees off: column empty
        props.observers['showRefs']()
        self.assertFalse(props['r_2_btn'])

    def find(self, root, test):
        return self.lua.eval('''function(root, test)
            local found = {}
            local function walk(v)
              if type(v) ~= 'table' then return end
              if test(v) then found[#found + 1] = v end
              for _, c in ipairs(v) do walk(c) end
            end
            walk(root)
            return found
        end''')(root, test)

    def test_click_the_picture(self):
        lua = self.lua
        photos = lua.eval('{ makePhoto(1, {}, 1000) }')
        lua.globals().STUB.catalog = lua.eval('makeCatalog')(photos)
        lua.execute(f'dofile([[{PLUGIN}/Players.lua]])')
        contents = lua.globals().STUB.dialog.contents
        pictures = self.find(contents, lambda v: v.kind == 'view' and v.place == 'overlapping')
        self.assertEqual(pictures[1][1].kind, 'picture')
        click = pictures[1][2]                                                    # on top of a_1's picture
        self.assertEqual((click.kind, click.visible.bind), ('static_text', 'a_1_btn'))
        click.mouse_down()
        self.assertTrue(photos[1].kws['Aa Bee'])
        click.mouse_down()                                                        # again: off
        self.assertFalse(photos[1].kws['Aa Bee'])

    def test_layout_changes_reopen_the_window(self):
        lua, stub = self.lua, self.lua.globals().STUB
        stub.catalog = lua.eval('makeCatalog')(lua.eval('{ makePhoto(1, {}, 1000) }'))
        frames, widths = [], []

        def seen(props):
            frames.append(stub.dialog.save_frame)
            views = self.find(stub.dialog.contents, lambda v: v.kind == 'scrolled_view')
            widths.append([views[i].width for i in range(1, len(views) + 1)])

        def refs_off(props):
            seen(props)
            props.showRefs = False
            props.observers['showRefs']()

        def larger(props):
            seen(props)
            props.size = 'large'
            props.observers['size']()
        stub.steps = lua.table_from([refs_off, larger, seen])
        lua.execute(f'dofile([[{PLUGIN}/Players.lua]])')
        self.assertEqual(stub.opened, 3)
        self.assertEqual(frames, ['BetterMechanicPlayersWindow_medium', 'BetterMechanicPlayersWindow_medium_norefs',
                                  'BetterMechanicPlayersWindow_large_norefs'])
        self.assertEqual(widths, [[456, 456, 248], [456, 456], [560, 560]])    # no referees column, then wider
        self.assertEqual((stub.prefs.showRefs, stub.prefs.size), (False, 'large'))   # and the next time too

    def test_inbox_adds_sent_photos(self):
        lua, stub = self.lua, self.lua.globals().STUB
        a, b = os.path.join(self.tmp, 'a.NEF'), os.path.join(self.tmp, 'b.JPG')
        name = lightroom.send(self.cfg, [a, b, os.path.join(self.tmp, 'gone.NEF'), os.path.join(self.tmp, 'c.txt')])
        send = f'{stub.appdata}/BetterMechanic/lightroom/send'
        req = os.path.join(lightroom.send_dir(self.cfg), name + '.txt')
        with open(req, encoding='utf-8') as fh:
            text = fh.read()
        os.remove(req)                                  # the stub's file system holds it from here on
        for p in (a, b, os.path.join(self.tmp, 'c.txt')):
            stub.files[p] = ''
        stub.files[f'{send}/{name}.txt'] = text
        stub.dirs[send] = True
        catalog = lua.eval('makeCatalog({})')
        catalog.byPath[b] = lua.eval('makePhoto')('b', lua.table())         # already in the catalog
        inbox = lua.eval('require("Inbox")')
        self.assertEqual(inbox.folder(), send)
        stub.busy = True                                # catalog busy: the request waits
        inbox.process(catalog)
        self.assertIsNotNone(stub.files[f'{send}/{name}.txt'])
        stub.busy = False
        inbox.process(catalog)
        self.assertIsNone(stub.files[f'{send}/{name}.txt'])
        self.assertEqual(lightroom.result(self.cfg, name), (1, 1, 2))         # the app reads the answer
        self.assertIsNotNone(catalog.byPath[a])
        self.assertEqual(len(catalog.collection.photos), 2)
        self.assertEqual(catalog.collection.name, 'BetterMechanic')
        self.assertEqual(catalog.sources[1].name, 'BetterMechanic')                 # shown in Lightroom
        self.assertEqual(len(catalog.selected), 2)
        self.assertIn('bezel: Added 1 photo from BetterMechanic, 1 already in the catalog, 2 could not be added',
                      list(stub.log.values()))
        info = lua.eval(f'dofile([[{PLUGIN}/Info.lua]])')
        self.assertEqual((info.LrInitPlugin, info.LrShutdownPlugin), ('Init.lua', 'Shutdown.lua'))
        self.assertTrue(info.LrForceInitPlugin)         # at startup, not once the window is first opened

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
