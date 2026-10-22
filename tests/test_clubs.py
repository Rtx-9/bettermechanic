"""Reading staff and photos from club websites, which are all built differently (no network: sample pages)."""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bettermechanic import clubs  # noqa: E402

BASE = 'https://club.example/joukkue/'


def people(page):
    return [(p['name'], p['role'], p['image']) for p in clubs.staff_from_html(page, BASE)]


class TestClubPages(unittest.TestCase):
    def test_table_rows(self):                                    # Sport, Tappara, KalPa
        page = ('<h2>Valmennus &amp; staff</h2><table><tr><td>Lauri Mikkola</td><td>Päävalmentaja</td></tr>'
                '<tr><td><a href="/p/1"><strong>Jussi Tapio</strong></a></td><td>Valmentaja</td></tr>'
                '<tr><td>Mikko Valto</td><td>Naprapaatti</td></tr>'
                '<tr><td>Thomas Holmberg</td><td>Huoltopäällikkö</td></tr></table>')
        self.assertEqual([(n, r) for n, r, _ in people(page)],
                         [('Lauri Mikkola', 'Päävalmentaja'), ('Jussi Tapio', 'Valmentaja'),
                          ('Mikko Valto', 'Naprapaatti'), ('Thomas Holmberg', 'Huoltopäällikkö')])

    def test_photo_captions_link_the_full_size_picture(self):     # TPS, Jukurit, SaiPa
        card = ('<div class="col"><a href="https://lh3.googleusercontent.com/{0}=s1600"><picture>'
                '<img src="https://lh3.googleusercontent.com/{0}=s560"></picture></a>'
                '<div class="legend"><p>{1}<br>{2}</p></div></div>')
        page = card.format('aa', 'Jonne Virtanen', 'Päävalmentaja') + card.format('bb', 'Päävalmentaja<br>Toni Söderholm', '')
        self.assertEqual(people(page), [('Jonne Virtanen', 'Päävalmentaja', 'https://lh3.googleusercontent.com/aa=s1600'),
                                        ('Toni Söderholm', 'Päävalmentaja', 'https://lh3.googleusercontent.com/bb=s1600')])

    def test_cards_with_split_names_and_srcset(self):            # Ässät, KooKoo
        page = ''.join('<div class="item"><img src="/s/{0}-300.jpg" srcset="/s/{0}-300.jpg 300w, /s/{0}.jpg 1080w">'
                       '<h6>{1}</h6><h5>{2}</h5><span>{3}</span></div>'.format(*x)
                       for x in (('a', 'Jarno', 'Pikkarainen', 'Päävalmentaja'), ('b', 'Kari', 'Kalto', 'valmentaja')))
        self.assertEqual(people(page), [('Jarno Pikkarainen', 'Päävalmentaja', 'https://club.example/s/a.jpg'),
                                        ('Kari Kalto', 'Valmentaja', 'https://club.example/s/b.jpg')])

    def test_soft_hyphens_and_name_particles(self):              # Kärpät
        page = ('<div><h5>Petri <strong>Karjalainen</strong> <span>Pää­valmentaja</span></h5></div>'
                '<div><h5>Ari <strong>af Hällström</strong> <span>Kuljettaja</span></h5></div>')
        self.assertEqual([(n, r) for n, r, _ in people(page)],
                         [('Petri Karjalainen', 'Päävalmentaja'), ('Ari af Hällström', 'Kuljettaja')])

    def test_role_then_name_in_one_line_and_name_comma_role(self):    # Pelicans U20, K-Espoo
        page = ('<p>Päävalmentaja: Jani Allenius</p><p>Huoltaja: Jouni Paakki</p>'
                '<p><strong>Jyrki Aho</strong>, vastuuvalmentaja<br><strong>Kurtis McLean</strong>, valmentaja<br>'
                '<strong>Rolf von Hedenberg</strong>, mv-valmentaja</p>')
        self.assertEqual([(n, r) for n, r, _ in people(page)],
                         [('Jani Allenius', 'Päävalmentaja'), ('Jouni Paakki', 'Huoltaja'),
                          ('Jyrki Aho', 'Vastuuvalmentaja'), ('Kurtis McLean', 'Valmentaja'),
                          ('Rolf von Hedenberg', 'Mv-valmentaja')])

    def test_people_under_a_staff_heading(self):                 # HIFK, JYP: no role per person
        page = ('<div><h2>Pelaajat</h2><div class="row"><div class="p"><img src="/p1.jpg"><h3>Some Player</h3></div></div>'
                '<h2>Valmennus</h2><div class="row">'
                '<div class="p"><img src="/c1.jpg"><div class="name">Tommi<br><span>Miettinen</span></div></div>'
                '<div class="p"><img src="/c2.jpg"><h3>Ari Halttunen</h3></div></div>'
                '<ul class="share"><li>Like</li><li>Tweet</li></ul></div>')
        self.assertEqual(people(page), [('Tommi Miettinen', 'Valmentaja', 'https://club.example/c1.jpg'),
                                        ('Ari Halttunen', 'Valmentaja', 'https://club.example/c2.jpg')])

    def test_page_photos_cover_players_too(self):
        page = ('<div class="p"><img src="/p1.jpg"><h3>Niilo Hinno</h3></div>'
                '<div class="p"><img src="/p2.jpg"><h3>Kasper Soini</h3></div>')
        self.assertEqual(clubs.read_page(page, BASE)[1], {'Niilo Hinno': 'https://club.example/p1.jpg',
                                                          'Kasper Soini': 'https://club.example/p2.jpg'})


class TestPhotos(unittest.TestCase):
    def test_placeholders(self):
        for url in ('https://hifk.fi/wp-content/themes/hifk/assets/images/PH-red.png',
                    'https://www.karpat.fi/hubfs/website/blank-player-image.png',
                    'https://wisenetwork.fi/assets/liiga/images/pelaaja.png'):
            self.assertTrue(clubs.is_placeholder_url(url), url)
        self.assertFalse(clubs.is_placeholder_url('https://assat.com/wp-content/uploads/PikkarainenJarno-1.jpg'))
        self.assertTrue(clubs.is_placeholder_url('https://x/logo.png', {'https://x/logo.png': 2}))   # on two people

    def test_shared_picture_is_not_a_photo(self):
        page = ''.join(f'<div class="p"><img src="/same.png"><h3>{n}</h3><span>Valmentaja</span></div>'
                       for n in ('Janne Grönvall', 'Kim Forsblom'))
        with mock.patch.object(clubs, 'fetch_page', return_value=page), \
                mock.patch.dict(clubs.PAGES, {'x': [BASE]}):
            staff, photos = clubs.club('x')
        self.assertEqual([p['image'] for p in staff], ['', ''])
        self.assertEqual(photos, {})

    def test_own_page_photo_at_full_size(self):
        listing = '<table><tr><td><a href="/p/sami">Sami Tervonen</a></td><td>Päävalmentaja</td></tr></table>'
        own = ('<meta property="og:image" content="https://lh3.googleusercontent.com/xyz=w1200-h628-c">')
        with mock.patch.object(clubs, 'fetch_page', side_effect=lambda url, timeout=20: own if '/p/' in url else listing), \
                mock.patch.dict(clubs.PAGES, {'x': [BASE]}):
            staff, _ = clubs.club('x')
        self.assertEqual(staff[0]['image'], 'https://lh3.googleusercontent.com/xyz=s1200')

    def test_wikipedia_only_for_hockey_people(self):
        answer = {'query': {'normalized': [{'from': 'jari viuhkola', 'to': 'Jari viuhkola'}],
                            'redirects': [{'from': 'Jari viuhkola', 'to': 'Jari Viuhkola'}],
                            'pages': {'1': {'title': 'Jari Viuhkola', 'extract': 'Jari Viuhkola on suomalainen jääkiekkoilija.',
                                            'thumbnail': {'source': 'https://upload.wikimedia.org/jv.jpg'}},
                                      '2': {'title': 'Matti Laitila', 'extract': 'Matti Laitila on suomalainen poliitikko.',
                                            'thumbnail': {'source': 'https://upload.wikimedia.org/ml.jpg'}}}}}

        def urlopen(req, timeout=20):
            r = io.BytesIO(json.dumps(answer).encode())
            r.__enter__, r.__exit__ = lambda *a: r, lambda *a: None
            return r
        with mock.patch.object(clubs.urllib.request, 'urlopen', urlopen):
            found = clubs.wikipedia_photos(['jari viuhkola', 'Matti Laitila'])
        self.assertEqual(found, {'jari viuhkola': 'https://upload.wikimedia.org/jv.jpg'})   # not the namesake


if __name__ == '__main__':
    unittest.main()
