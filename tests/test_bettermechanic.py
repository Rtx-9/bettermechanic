"""Run with:  python -m unittest discover tests"""
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([sys.argv[0], '-platform', 'offscreen'])

import samples  # noqa: E402
from bettermechanic import core, imaging, previews  # noqa: E402
from bettermechanic import metadata as M  # noqa: E402

SETTINGS = {'jpeg_mode': 'embed', 'write_iim': True, 'people_to_keywords': True, 'seq_digits': 4, 'seq': 1}


def is_red(img, x, y):
    r, g, b = img.getpixel((x, y))[:3]
    return r > 200 and g < 80 and b < 80


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card = samples.write_card(self.tmp, 4)
        self.p = lambda n: os.path.join(self.card, n)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestPreviews(Base):
    def test_jpeg_exif(self):
        a = previews.analyze(self.p('IMG_0001.JPG'))
        self.assertEqual(a.format, 'jpeg')
        self.assertEqual([(c.w, c.h) for c in a.cands], [(160, 120), (900, 600)])
        self.assertEqual(a.exif['date'], '2026:10:21 19:30:00')
        self.assertEqual(a.exif['iso'], 3200)
        self.assertAlmostEqual(a.exif['exposure'], 0.001)

    def test_letterboxed_exif_thumb_is_cropped(self):
        a = previews.analyze(self.p('IMG_0001.JPG'))
        data, q = imaging.make_thumb(self.p('IMG_0001.JPG'), a, 240, False)
        img = Image.open(io.BytesIO(data)).convert('RGB')
        self.assertAlmostEqual(img.width / img.height, 1.5, delta=0.05)
        self.assertGreater(sum(img.getpixel((img.width // 2, 1))), 60, 'black bar left in thumbnail')

    def test_orientation_6(self):
        a = previews.analyze(self.p('IMG_0003.JPG'))
        self.assertEqual(a.orient, 6)
        self.assertEqual((a.ow, a.oh), (600, 900))
        img = imaging.make_preview(self.p('IMG_0003.JPG'), a)
        self.assertEqual(img.size, (600, 900))
        self.assertTrue(is_red(img, img.width - 5, 5), 'stored top-left must end up top-right')

    def test_nef(self):
        a = previews.analyze(self.p('DSC_0100.NEF'))
        self.assertEqual(a.format, 'tiff')
        self.assertEqual([(c.w, c.h) for c in a.cands], [(300, 200), (1200, 800)])  # raw strip ignored
        self.assertEqual(a.exif['model'], 'Fake Z9')
        img = imaging.make_preview(self.p('DSC_0100.NEF'), a, 400, 400)
        self.assertEqual(img.size, (267, 400))
        self.assertTrue(is_red(img, img.width - 3, 3))

    def test_cr3(self):
        a = previews.analyze(self.p('IMG_0200.CR3'))
        self.assertEqual(a.format, 'cr3')
        self.assertEqual([(c.w, c.h) for c in a.cands], [(160, 107), (600, 400), (1200, 800)])
        self.assertEqual(a.orient, 8)
        self.assertEqual(a.exif['date'], '2026:10:21 19:31:10')
        self.assertEqual(a.exif['model'], 'Fake R3')
        img = imaging.make_preview(self.p('IMG_0200.CR3'), a)
        self.assertEqual(img.size, (800, 1200))
        self.assertTrue(is_red(img, 3, img.height - 3), 'orientation 8: stored top-left goes bottom-left')

    def test_orf_scan_fallback(self):
        a = previews.analyze(self.p('P_0300.ORF'))
        self.assertEqual([(c.w, c.h) for c in a.cands], [(1200, 800)])
        data, q = imaging.make_thumb(self.p('P_0300.ORF'), a, 256, True)
        self.assertEqual(q, 256)


class TestMetadata(Base):
    META = dict(M.blank(), rating=4, label='Red', tagged=True, people=['Gustav', 'Mäkelä'], keywords=['Hockey'],
                caption='Gustav scores — åäö', headline='Big win', city='Helsinki')

    def test_jpeg_roundtrip(self):
        path = self.p('IMG_0002.JPG')
        before = previews.analyze(path)
        with open(path, 'rb') as fh:
            out = M.rewrite_jpeg(fh.read(), self.META)
        with open(path, 'wb') as fh:
            fh.write(out)
        a = previews.analyze(path)
        self.assertEqual([(c.w, c.h) for c in a.cands], [(c.w, c.h) for c in before.cands])
        self.assertEqual(a.exif['date'], before.exif['date'])
        m = M.read_jpeg_meta(a.xmp, a.app13)
        for k in ('rating', 'label', 'tagged', 'people', 'caption', 'headline', 'city'):
            self.assertEqual(m[k], self.META[k], k)
        self.assertEqual(set(m['keywords']), {'Hockey', 'Gustav', 'Mäkelä'})
        iim = M.parse_app13(a.app13)
        self.assertEqual(iim['caption'], self.META['caption'])
        self.assertIsNotNone(imaging.make_preview(path, a))
        # rewriting again must not grow the file (old segments replaced)
        out2 = M.rewrite_jpeg(out, self.META)
        self.assertEqual(len(out2), len(out))

    def test_sidecar_merge_keeps_other_tools_data(self):
        existing = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                    '<rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" '
                    'xmlns:xmp="http://ns.adobe.com/xap/1.0/" crs:Exposure2012="+0.35" xmp:Rating="1"/>'
                    '</rdf:RDF></x:xmpmeta>')
        out = M.build_xmp(self.META, existing)
        self.assertIn('crs:Exposure2012="+0.35"', out)
        self.assertEqual(M.parse_xmp(out)['rating'], 4)
        self.assertEqual(M.parse_xmp(out)['people'], ['Gustav', 'Mäkelä'])
        self.assertNotIn('ns0:', out)

    def test_write_item_meta_pair(self):
        files, sc = core.scan_folder(self.card)
        items = core.build_items(files, sc, True)
        pair = next(it for it in items if it.is_pair)
        core.ensure_meta(pair, SETTINGS)
        pair.meta.update(people=['Stan'], tagged=True)
        core.write_item_meta(pair, M.copy_meta(pair.meta), SETTINGS)
        self.assertTrue(os.path.exists(self.p('DSC_0101.xmp')))
        files, sc = core.scan_folder(self.card)
        again = next(it for it in core.build_items(files, sc, True) if it.is_pair)
        core.ensure_meta(again, SETTINGS)
        self.assertEqual(again.meta['people'], ['Stan'])
        self.assertTrue(again.meta['tagged'])
        self.assertEqual(again.meta['keywords'], [])


class TestCore(Base):
    def test_scan_and_pairs(self):
        files, sc = core.scan_folder(self.tmp, recursive=True)
        items = core.build_items(files, sc, True)
        self.assertEqual(len(items), 4 + 4)          # 4 jpeg + NEF + CR3 + ORF + 1 pair
        pair = [it for it in items if it.is_pair]
        self.assertEqual(len(pair), 1)
        self.assertEqual(pair[0].pv.kind, 'jpeg')
        self.assertEqual(len(core.scan_folder(self.tmp, recursive=False)[0]), 0)

    def test_templates(self):
        files, sc = core.scan_folder(self.card)
        it = next(i for i in core.build_items(files, sc) if i.name == 'IMG_0001.JPG')
        core.ensure_meta(it, SETTINGS)
        it.meta['people'] = ['Gustav', 'John', 'Mark']
        it.meta['event'] = 'Final'
        s = core.expand('{people} in the {event} {yyyy}-{mm}-{dd} {seq:3} {orig}', it, seq=7)
        self.assertEqual(s, 'Gustav, John and Mark in the Final 2026-10-21 007 IMG_0001')
        self.assertEqual(core.sanitize('a/b:c?'), 'a_b_c_')


class TestCopy(Base):
    def test_ingest_copy(self):
        from bettermechanic.workers import Bus, CopyJob
        files, sc = core.scan_folder(self.tmp, recursive=True)
        items = sorted(core.build_items(files, sc), key=lambda i: i.name)
        for it in items:
            core.ensure_meta(it, SETTINGS)
        items[0].meta['rating'] = -1                  # rejected -> not copied
        items[1].meta['people'] = ['Joe']
        dest = os.path.join(self.tmp, 'out')
        os.makedirs(dest)
        preset = {'fields': {'caption': '{people} at {city}', 'city': 'Tampere', 'keywords': 'Soccer'}}
        opts = dict(dest=dest, backup='', use_backup=False, sub='{yyyy}{mm}{dd}', rename='{date}_{seq:3}',
                    which='not_rejected', fmt='original', meta_preset='x', preset_mode='replace', exists='skip',
                    write_meta=True, ingest=True, skip_ingested=True)
        hist = os.path.join(self.tmp, 'history.json')
        bus, done = Bus(), threading.Event()
        res = {}
        bus.copy_done.connect(lambda r: (res.update(r), done.set()))
        job = CopyJob(bus, items, [], opts, SETTINGS, preset, 'Soccer', hist)
        job.run()                                     # synchronous for the test
        self.assertEqual(res['copied'], len(items) - 1, res)
        out = sorted(os.listdir(os.path.join(dest, '20261021')))
        self.assertIn('20261021_001.NEF', out)        # DSC_0100.NEF sorted first after the rejected one
        self.assertTrue(any(n.endswith('.xmp') for n in out))
        first_jpg = next(n for n in out if n.endswith('.JPG'))
        a = previews.analyze(os.path.join(dest, '20261021', first_jpg))
        m = M.read_jpeg_meta(a.xmp, a.app13)
        self.assertEqual(m['city'], 'Tampere')
        self.assertIn('Soccer', m['keywords'])
        # ingesting the same card again (sequence continues) copies nothing new
        res.clear()
        CopyJob(bus, items, [], opts, dict(SETTINGS, seq=50), preset, 'Soccer', hist).run()
        self.assertEqual((res['copied'], res['skipped']), (0, len(items) - 1))



class TestRoster(unittest.TestCase):
    def test_parse_roster(self):
        from bettermechanic.config import parse_roster
        rows = parse_roster('9, Gustav Forsling, https://ex.com/p/9.jpg\n'
                            '12\tMark Lee\tC:\\pics\\mark.png\n'
                            '#91 John Smith\n'
                            '7. Joe Bloggs | https://x.y/7.png\n'
                            'Stan\n\n')
        self.assertEqual(rows, [
            {'name': 'Gustav Forsling', 'number': '9', 'image': 'https://ex.com/p/9.jpg'},
            {'name': 'Mark Lee', 'number': '12', 'image': 'C:\\pics\\mark.png'},
            {'name': 'John Smith', 'number': '91', 'image': ''},
            {'name': 'Joe Bloggs', 'number': '7', 'image': 'https://x.y/7.png'},
            {'name': 'Stan', 'number': '', 'image': ''}])

    def test_players_merge_roster_and_keys(self):
        from bettermechanic.config import players, tag_preset
        p = tag_preset('Hockey', ['Gustav', 'Zed'])
        p['roster'] = [{'name': 'Ann', 'number': '1', 'image': ''}, {'name': 'Gustav', 'number': '9', 'image': 'x'}]
        out = players(p)
        self.assertEqual([(e['name'], e['number'], e['key']) for e in out],
                         [('Ann', '1', None), ('Gustav', '9', 0), ('Zed', '', 1)])

    def test_avatar_from_file_and_link(self):
        from bettermechanic import avatars
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, 'head.jpg')
            Image.new('RGB', (300, 500), (200, 30, 30)).save(src)
            for i, s in enumerate((src, 'file:///' + src.replace('\\', '/'))):
                dest = os.path.join(tmp, f'a{i}.jpg')
                avatars.make_avatar_file(s, dest)
                with Image.open(dest) as im:
                    self.assertEqual(im.size, (avatars.SIZE, avatars.SIZE))
            with self.assertRaises(Exception):
                avatars.make_avatar_file(os.path.join(tmp, 'missing.jpg'), os.path.join(tmp, 'x.jpg'))
            self.assertEqual(avatars.initials('Gustav Forsling'), 'GF')
            self.assertEqual(avatars.initials('Stan'), 'S')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCards(Base):
    def test_is_card(self):
        self.assertTrue(core.is_card(self.tmp))                       # has DCIM
        self.assertTrue(core.is_card(self.card))                      # inside DCIM
        self.assertFalse(core.is_card(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(core.card_scan_root(self.tmp), os.path.join(os.path.abspath(self.tmp), 'DCIM'))

    def test_culling_survives_reopen(self):
        store_path = os.path.join(self.tmp, 'culls.json')
        files, sc = core.scan_folder(self.card)
        items = {i.name: i for i in core.build_items(files, sc)}
        store = core.CullStore(store_path)
        it = items['IMG_0002.JPG']
        core.ensure_meta(it, SETTINGS)
        it.meta.update(tagged=True, rating=3, people=['Gustav'])
        store.put(it)
        store.save()
        # nothing was written next to the photos
        self.assertFalse(any(n.lower().endswith('.xmp') for n in os.listdir(self.card)))
        files, sc = core.scan_folder(self.card)
        again = {i.name: i for i in core.build_items(files, sc)}['IMG_0002.JPG']
        again.overlay = core.CullStore(store_path).get(again)
        core.ensure_meta(again, SETTINGS)
        self.assertEqual((again.meta['tagged'], again.meta['rating'], again.meta['people']), (True, 3, ['Gustav']))
        # culling saved by 0.4.x could also hold edit settings: ignored now
        legacy = {i.name: i for i in core.build_items(*core.scan_folder(self.card))}['IMG_0002.JPG']
        legacy.overlay = {'tagged': True, 'develop': {'Exposure2012': 1.0}}
        core.ensure_meta(legacy, SETTINGS)
        self.assertTrue(legacy.meta['tagged'])
        self.assertNotIn('develop', legacy.meta)
        # clearing everything removes the entry
        again.meta.update(tagged=False, rating=0, people=[])
        store2 = core.CullStore(store_path)
        store2.put(again)
        self.assertIsNone(store2.get(again))

if __name__ == '__main__':
    unittest.main()
