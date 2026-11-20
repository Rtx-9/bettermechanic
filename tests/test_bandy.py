"""Bandyliiga: the season's games and every team's roster from bandyliiga.fi."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bettermechanic import bandy, liiga  # noqa: E402
from bettermechanic.config import Config  # noqa: E402


def row(when, home, away, score='–'):
    def team(slug, name):
        return (f'<a class="blrh-team" href="/joukkueet/{slug}/"><img src="/logos/{slug}.png" alt="{name}">'
                f'<span class="blrh-team-label">{name}</span></a>')
    return (f'<div class="blrh-row"><span>{when}</span>{team(*home)}<b>{score}</b>{team(*away)}'
            f'<a class="blrh-match-link" href="/kausi-2026-27/?blrh_match=abc">›</a></div>')


VEITERA, KAMPPARIT, HIFK = ('veitera', 'Veiterä'), ('kampparit', 'Kampparit'), ('hifk', 'HIFK')
SEASON = ('<section><div class="blrh-list">' + row('15.11.2026 13:00', ('ols', 'OLS'), VEITERA, '3–11')
          + row('20.11.2026 19:00', VEITERA, KAMPPARIT) + row('05.12.2026 14:00', VEITERA, HIFK)
          + row('06.01.2027', HIFK, ('botnia', 'Botnia')) + '<div class="blrh-row"><span>TBA</span></div>'
          + '</div></section>')

ROSTERS = '''<nav class="blrv34__tabs">
<a class="blrv34__tab" href="https://bandyliiga.fi/team/veitera/roster/" aria-label="Avaa Veiterä rosteri">
  <span class="blrv34__tab-logo"><img src="veitera.png"></span><span class="blrv34__tab-name">Veiterä</span></a>
<a class="blrv34__tab" href="https://bandyliiga.fi/team/kampparit/roster/" aria-label="Avaa Kampparit rosteri">
  <span class="blrv34__tab-name">Kampparit</span></a>
</nav>'''


def member(name, number='', position='', staff=False, img='https://bandyliiga.fi/x-140x210.webp'):
    kind = 'staff' if staff else 'player'
    num = f'<div class="team-roster__member-number">{number}</div>' if number else ''
    return (f'<div class="team-roster__item"><div class="team-roster__holder"><figure class="team-roster__img">'
            f'<a href="https://bandyliiga.fi/{kind}/x/"><img width="140" src="{img}" alt=""></a></figure>'
            f'<div class="team-roster__content"><header class="team-roster__member-header">{num}'
            f'<h2 class="team-roster__member-name team-roster__member-name--no-link">{name}</h2></header>'
            f'<div class="team-roster__member-subheader"><div class="team-roster__member-position">\n'
            f'  {position}  </div></div></div><a href="https://bandyliiga.fi/{kind}/x/" class="btn-fab"></a></div></div>')


ROSTER = ('<div class="team-roster">' + member('Topi Peuhkuri', '2', 'Maalivahti')
          + member('Tero liimatainen', '62', 'Hyökkääjä') + member('Niklas Loikkanen', '17')
          + member('Joonas Ylä-Outinen', position='Päävalmentaja', staff=True)
          + member('Mika Simpura', position='Huoltaja', staff=True) + '</div>')


class TestBandy(unittest.TestCase):
    def test_season_slug(self):
        self.assertEqual(bandy.season_slug(2027), '2026-27')
        self.assertEqual(bandy.season_slug(2030), '2029-30')

    def test_games(self):
        games = bandy.games_from(SEASON, 2027)
        self.assertEqual(len(games), 4)                                   # played and to come, not the broken row
        g = games['bandy:2027:veitera-kampparit-2026-11-20']
        self.assertEqual(g['teams'], ['bandy:veitera', 'bandy:kampparit'])
        self.assertEqual(g['names'], ['Veiterä', 'Kampparit'])
        self.assertEqual((g['rink'], g['city'], g['where']), ('Kisapuisto', 'Lappeenranta', 'Lappeenrannan Kisapuistossa'))
        away = games['bandy:2027:ols-veitera-2026-11-15']
        self.assertEqual((away['city'], away['where']), ('Oulu', 'Oulussa'))
        self.assertEqual(games['bandy:2027:hifk-botnia-2027-01-06']['where'], 'Kallion tekojääradalla')

    def test_roster(self):
        self.assertEqual(bandy.roster_links(ROSTERS), {'Veiterä': 'https://bandyliiga.fi/team/veitera/roster/',
                                                       'Kampparit': 'https://bandyliiga.fi/team/kampparit/roster/'})
        roster = bandy.roster_from(ROSTER)
        self.assertEqual([(r['number'], r['name'], r['role']) for r in roster],
                         [('2', 'Topi Peuhkuri', ''), ('62', 'Tero Liimatainen', ''), ('17', 'Niklas Loikkanen', ''),
                          ('', 'Joonas Ylä-Outinen', 'Päävalmentaja'), ('', 'Mika Simpura', 'Huoltaja')])
        self.assertEqual(roster[0]['image'], 'https://bandyliiga.fi/x-140x210.webp')

    def test_fetch_and_apply(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = Config(os.path.join(tmp, 'config.json'))
        pages = {f'{bandy.BASE}/kausi-2026-27/': SEASON, f'{bandy.BASE}/rosterit-2026-27/': ROSTERS}
        with mock.patch.object(bandy, '_get', side_effect=lambda url, timeout=20: pages.get(url, ROSTER)):
            data = bandy.fetch(2027)
        self.assertEqual([(t['id'], t['name'], t['keywords']) for t in data['teams']],
                         [('bandy:veitera', 'Veiterä', 'Veiterä, Bandyliiga'),
                          ('bandy:kampparit', 'Kampparit', 'Kampparit, Bandyliiga')])   # teams with a roster page
        self.assertEqual([r['number'] for r in data['teams'][0]['roster'][:3]], ['2', '17', '62'])   # by number
        self.assertEqual(liiga.apply(cfg, data), (2, 0))
        self.assertIn('bandy:2027:veitera-kampparit-2026-11-20', liiga.load_games(cfg))
        with mock.patch.object(bandy, '_get', return_value='<html>no games</html>'):
            self.assertRaises(ValueError, bandy.fetch, 2027)


if __name__ == '__main__':
    unittest.main()
