"""Tagged photos get a mark Lightroom reads (label / stars / keyword), reversibly."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([sys.argv[0], '-platform', 'offscreen'])

import samples  # noqa: E402
from bettermechanic import core, previews  # noqa: E402
from bettermechanic import metadata as M  # noqa: E402

BASE = {'jpeg_mode': 'embed', 'write_iim': True, 'people_to_keywords': True, 'seq_digits': 4, 'seq': 1}


def meta(**kw):
    m = M.blank()
    m.update(kw)
    return m


class TestMarks(unittest.TestCase):
    def roundtrip(self, m, spec, existing=None):
        x = M.build_xmp(m, existing, True, spec)
        return x, M.parse_xmp(x)

    def test_label(self):
        x, back = self.roundtrip(meta(tagged=True), 'label:Green')
        self.assertIn('<xmp:Label>Green</xmp:Label>', x)                  # what Lightroom reads
        self.assertEqual(back['label'], '')                               # not a "real" label in the app
        self.assertTrue(back['tagged'])
        x, back = self.roundtrip(meta(tagged=True, label='Red'), 'label:Green')
        self.assertIn('<xmp:Label>Red</xmp:Label>', x)                    # your own label wins
        self.assertEqual(back['label'], 'Red')
        x, _ = self.roundtrip(meta(tagged=False), 'label:Green')
        self.assertNotIn('Label', x)

    def test_stars(self):
        x, back = self.roundtrip(meta(tagged=True, rating=0), 'stars:2')
        self.assertIn('<xmp:Rating>2</xmp:Rating>', x)
        self.assertEqual(back['rating'], 0)
        x, back = self.roundtrip(meta(tagged=True, rating=1), 'stars:2')
        self.assertEqual(back['rating'], 1)                               # remembered what it replaced
        x, back = self.roundtrip(meta(tagged=True, rating=4), 'stars:2')
        self.assertIn('<xmp:Rating>4</xmp:Rating>', x)                    # higher own rating kept
        self.assertEqual(back['rating'], 4)
        x, _ = self.roundtrip(meta(tagged=True, rating=-1), 'stars:2')    # rejected stays rejected
        self.assertIn('<xmp:Rating>-1</xmp:Rating>', x)

    def test_keyword(self):
        x, back = self.roundtrip(meta(tagged=True, keywords=['Hockey']), 'keyword:Tagged')
        self.assertIn('<rdf:li>Tagged</rdf:li>', x)
        self.assertEqual(back['keywords'], ['Hockey'])

    def test_untag_removes_the_mark(self):
        x, _ = self.roundtrip(meta(tagged=True), 'label:Green')
        x2, back = self.roundtrip(meta(tagged=False), 'label:Green', existing=x)
        self.assertNotIn('Green', x2)
        self.assertNotIn('LightroomMark', x2)
        self.assertFalse(back.get('tagged', False))

    def test_lightroom_changed_it_afterwards(self):
        x, _ = self.roundtrip(meta(tagged=True), 'label:Green')
        x = x.replace('<xmp:Label>Green</xmp:Label>', '<xmp:Label>Blue</xmp:Label>')
        self.assertEqual(M.parse_xmp(x)['label'], 'Blue')                 # someone else's change is kept

    def test_off(self):
        x, _ = self.roundtrip(meta(tagged=True), 'none')
        self.assertNotIn('Label', x)
        self.assertNotIn('bettermechanic', x)


class TestMarkInFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card = samples.write_card(self.tmp, 2)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_jpeg_xmp_and_iptc(self):
        it = {i.name: i for i in core.build_items(*core.scan_folder(self.card))}['IMG_0001.JPG']
        core.ensure_meta(it, BASE)
        it.meta['tagged'] = True
        core.write_item_meta(it, it.meta, dict(BASE, lr_tag_mark='keyword:Tagged'))
        a = previews.analyze(it.pv.path)
        self.assertIn('Tagged', M.parse_app13(a.app13)['keywords'])      # newsroom IPTC too
        self.assertNotIn('Tagged', M.read_jpeg_meta(a.xmp, a.app13)['keywords'])
        again = {i.name: i for i in core.build_items(*core.scan_folder(self.card))}['IMG_0001.JPG']
        core.ensure_meta(again, BASE)
        self.assertEqual(again.meta['keywords'], [])

    def test_ingest_marks_tagged_copies(self):
        from bettermechanic.workers import Bus, CopyJob
        items = sorted(core.build_items(*core.scan_folder(self.tmp, True)), key=lambda i: i.name)
        for it in items:
            core.ensure_meta(it, BASE)
        nef = next(i for i in items if i.name == 'DSC_0100.NEF')
        nef.meta['tagged'] = True
        dest = os.path.join(self.tmp, 'out')
        os.makedirs(dest)
        CopyJob(Bus(), [nef], [], dict(dest=dest, sub='', rename='{orig}', which='tagged', fmt='original',
                                      exists='skip', write_meta=True), dict(BASE, lr_tag_mark='stars:1'), None, '').run()
        with open(os.path.join(dest, 'DSC_0100.xmp'), encoding='utf-8') as fh:
            self.assertIn('<xmp:Rating>1</xmp:Rating>', fh.read())


if __name__ == '__main__':
    unittest.main()
