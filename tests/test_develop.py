"""Lightroom preset import, develop rendering and Camera Raw XMP round-trips."""
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([sys.argv[0], '-platform', 'offscreen'])

import samples  # noqa: E402
from bettermechanic import core, develop, imaging, previews  # noqa: E402
from bettermechanic import metadata as M  # noqa: E402

XMP_PRESET = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Normal" crs:UUID="5C5D2E1A" crs:SupportsAmount="True" crs:SupportsColor="True"
   crs:Version="15.0" crs:ProcessVersion="11.0" crs:Exposure2012="+0.30" crs:Contrast2012="+25"
   crs:Highlights2012="-40" crs:Shadows2012="+30" crs:Clarity2012="+15" crs:Vibrance="+20"
   crs:SaturationAdjustmentYellow="+30" crs:HasSettings="True">
   <crs:Name><rdf:Alt><rdf:li xml:lang="x-default">Arena Punch</rdf:li></rdf:Alt></crs:Name>
   <crs:Group><rdf:Alt><rdf:li xml:lang="x-default">Sports</rdf:li></rdf:Alt></crs:Group>
   <crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 0</rdf:li><rdf:li>128, 136</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>'''

LOOK_PROFILE = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
 <rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" crs:PresetType="Look"
  crs:Contrast2012="+10"/></rdf:RDF></x:xmpmeta>'''

LRTEMPLATE = '''s = {
	id = "6C9A",
	internalName = "Vintage Fade",
	title = "Vintage Fade",
	type = "Develop",
	value = {
		settings = {
			Contrast2012 = -20,
			Exposure2012 = 0.15,
			ParametricShadows = 20,
			SplitToningShadowHue = 210,
			SplitToningShadowSaturation = 15,
			ToneCurvePV2012 = { 0, 30, 255, 245, },
			ProcessVersion = "10.0",
		},
		uuid = "6C9A",
	},
	version = 0,
}
'''


class TestPresets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_xmp_preset(self):
        p = develop.parse_xmp_preset(XMP_PRESET)
        self.assertEqual((p['name'], p['group']), ('Arena Punch', 'Sports'))
        s = p['settings']
        self.assertEqual((s['Exposure2012'], s['Contrast2012'], s['Highlights2012']), (0.3, 25, -40))
        self.assertEqual(s['ToneCurvePV2012'], ['0, 0', '128, 136', '255, 255'])
        self.assertEqual(s['ProcessVersion'], '11.0')                # kept as text
        self.assertNotIn('UUID', s)
        self.assertIsNone(develop.parse_xmp_preset(LOOK_PROFILE))      # profiles are not develop presets

    def test_lrtemplate(self):
        p = develop.parse_lrtemplate(LRTEMPLATE)
        self.assertEqual(p['name'], 'Vintage Fade')
        s = p['settings']
        self.assertEqual((s['Contrast2012'], s['Exposure2012'], s['SplitToningShadowHue']), (-20, 0.15, 210))
        self.assertEqual(s['ToneCurvePV2012'], ['0, 30', '255, 245'])

    def test_import_folder_and_zip(self):
        folder = os.path.join(self.tmp, 'My Looks')
        os.makedirs(folder)
        with open(os.path.join(folder, 'vintage.lrtemplate'), 'w', encoding='utf-8') as fh:
            fh.write(LRTEMPLATE)
        with open(os.path.join(folder, 'profile.xmp'), 'wb') as fh:
            fh.write(LOOK_PROFILE)
        zpath = os.path.join(self.tmp, 'Hockey Pack.zip')
        with zipfile.ZipFile(zpath, 'w') as z:
            z.writestr('Hockey Pack/Arena Punch.xmp', XMP_PRESET)
            z.writestr('Hockey Pack/Ice White.xmp', XMP_PRESET.replace(b'Arena Punch', b'Ice White')
                       .replace(b'>Sports<', b'><'))
            z.writestr('__MACOSX/Hockey Pack/._Ice White.xmp', b'junk')
            z.writestr('readme.txt', b'hi')
        found, skipped = develop.read_presets([folder, zpath])
        names = sorted((p['group'], p['name']) for p in found)
        self.assertEqual(names, [('Hockey Pack', 'Ice White'), ('My Looks', 'Vintage Fade'), ('Sports', 'Arena Punch')])
        self.assertEqual(skipped, 1)                                  # the profile
        lib = develop.PresetLibrary(os.path.join(self.tmp, 'lib.json'))
        self.assertEqual(lib.add_many(found), 3)
        self.assertEqual(lib.add_many(found), 0)                      # importing again doesn't duplicate
        self.assertEqual(sorted(develop.PresetLibrary(os.path.join(self.tmp, 'lib.json')).groups()),
                         ['Hockey Pack', 'My Looks', 'Sports'])

    def test_amount(self):
        s = develop.parse_xmp_preset(XMP_PRESET)['settings']
        half = develop.scale_settings(s, 0.5)
        self.assertEqual((half['Exposure2012'], half['Contrast2012'], half['ToneCurvePV2012'][1]), (0.15, 12, '128, 132'))
        self.assertEqual(half['ProcessVersion'], '11.0')


class TestWhiteBalanceReference(unittest.TestCase):
    """Presets made in Lightroom 12+ carry the as-shot white balance of the photo they were made on."""
    PRESET = XMP_PRESET.replace(b'crs:HasSettings="True"', b'crs:WhiteBalance="Custom" crs:Temperature="4500" '
                                b'crs:Tint="+23" crs:AsShotTemperature="4950" crs:AsShotTint="18" crs:RedSaturation="+56" '
                                b'crs:HasSettings="True"')

    def test_reference_is_private_and_scaled_in_mired(self):
        s = develop.parse_xmp_preset(self.PRESET)['settings']
        self.assertNotIn('AsShotTemperature', s)
        self.assertEqual((s['_RefTemperature'], s['_RefTint']), (4950, 18))
        half = develop.preset_values(s, 0.5)
        self.assertTrue(4500 < half['Temperature'] < 4950)
        self.assertEqual(half['Tint'], 20)
        x = M.build_xmp(M.blank(), None, develop=half)
        self.assertNotIn('_Ref', x)
        self.assertNotIn('AsShot', x)
        self.assertIn('crs:Temperature=', x)
        # older imports kept AsShot* in the settings: migrated when applied
        old = dict(s, AsShotTemperature=s.pop('_RefTemperature'))
        self.assertIn('_RefTemperature', develop.preset_values(old))

    def test_cooler_than_as_shot_renders_cooler(self):
        img = np.full((40, 60, 3), 150, np.uint8)
        s = develop.parse_xmp_preset(self.PRESET)['settings']
        only_wb = {k: s[k] for k in ('WhiteBalance', 'Temperature', '_RefTemperature')}
        out = develop.render(img, only_wb).astype(int)
        self.assertLess(out[..., 0].mean(), out[..., 2].mean())     # 4500 K < 4950 K as shot: bluer
        self.assertIs(develop.render(img, {'WhiteBalance': 'Custom', 'Temperature': 4500}), img)  # no reference

    def test_red_primary_turns_yellow_orange(self):
        img = np.zeros((10, 10, 3), np.uint8)
        img[...] = (220, 190, 30)
        out = develop.render(img, {'RedSaturation': 80}).astype(int)
        self.assertGreater(out[0, 0, 0] - out[0, 0, 1], 220 - 190)   # red pulls ahead of green


class TestRender(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.img = (rng.random((120, 180, 3)) * 255).astype(np.uint8)
        self.img[:, :60] = (230, 190, 40)                             # a yellow block

    def test_identity(self):
        self.assertIs(develop.render(self.img, {}), self.img)
        self.assertFalse(develop.is_active({'Exposure2012': 0, 'Sharpness': 40, 'ProcessVersion': '11.0'}))

    def test_adjustments_move_in_the_right_direction(self):
        base = self.img.astype(float)
        brighter = develop.render(self.img, {'Exposure2012': 1.0}).astype(float)
        self.assertGreater(brighter.mean(), base.mean() + 15)
        gray = develop.render(self.img, {'ConvertToGrayscale': True})
        self.assertLess(np.abs(gray[..., 0].astype(int) - gray[..., 2]).max(), 3)
        desat = develop.render(self.img, {'SaturationAdjustmentYellow': -100}).astype(float)
        yellow_before = base[:, :60, 0] - base[:, :60, 2]
        yellow_after = desat[:, :60, 0] - desat[:, :60, 2]
        self.assertLess(yellow_after.mean(), yellow_before.mean() * 0.5)
        warm = develop.render(self.img, {'IncrementalTemperature': 60}).astype(float)
        self.assertGreater((warm[..., 0] - warm[..., 2]).mean(), (base[..., 0] - base[..., 2]).mean())
        vign = develop.render(self.img, {'PostCropVignetteAmount': -80}).astype(float)
        self.assertLess(vign[0, 0].mean(), base[0, 0].mean())
        self.assertEqual(develop.render(self.img, {'Contrast2012': 30}).shape, self.img.shape)


class TestDevelopXmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card = samples.write_card(self.tmp, 2)
        self.S = {'jpeg_mode': 'embed', 'write_iim': True, 'people_to_keywords': True}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def items(self):
        files, sc = core.scan_folder(self.card)
        return {i.name: i for i in core.build_items(files, sc)}

    def test_raw_sidecar_keeps_lightroom_settings(self):
        nef = os.path.join(self.card, 'DSC_0100.xmp')
        with open(nef, 'w', encoding='utf-8') as fh:
            fh.write('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                     '<rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" '
                     'crs:ProcessVersion="11.0" crs:LensProfileEnable="1" crs:Clarity2012="+15"/></rdf:RDF></x:xmpmeta>')
        it = self.items()['DSC_0100.NEF']
        core.ensure_meta(it, self.S)
        self.assertEqual(it.develop['Clarity2012'], 15)
        self.assertTrue(it.looks_edited)
        it.develop.update(Exposure2012=0.5, Clarity2012=None)
        it.dev_edits |= {'Exposure2012', 'Clarity2012'}
        core.write_item_meta(it, it.meta, self.S, core.develop_edits(it))
        with open(nef, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('crs:ProcessVersion="11.0"', text)              # untouched, still text
        self.assertIn('crs:LensProfileEnable="1"', text)
        self.assertIn('crs:Exposure2012="+0.50"', text)
        self.assertNotIn('Clarity2012', text)
        again = self.items()['DSC_0100.NEF']
        core.ensure_meta(again, self.S)
        self.assertEqual(again.develop.get('Exposure2012'), 0.5)

    def test_jpeg_embeds_edits_and_export_renders_them(self):
        it = self.items()['IMG_0001.JPG']
        core.ensure_meta(it, self.S)
        it.develop.update(Exposure2012=1.0, ConvertToGrayscale=True)
        it.dev_edits |= {'Exposure2012', 'ConvertToGrayscale'}
        core.write_item_meta(it, it.meta, self.S, core.develop_edits(it))
        a = previews.analyze(it.pv.path)
        self.assertEqual(M.parse_develop(a.xmp)['ConvertToGrayscale'], True)
        out = imaging.render_jpeg(it.pv.path, a, 300, 90, develop.clean(it.develop))
        from PIL import Image
        im = np.asarray(Image.open(io.BytesIO(out)).convert('RGB')).astype(int)
        self.assertLess(np.abs(im[..., 0] - im[..., 2]).max(), 12)    # black & white


if __name__ == '__main__':
    unittest.main()
