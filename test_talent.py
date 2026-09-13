import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import talent


def item(rank, team, points, avg, players, five, four, three):
    """One school, shaped like a row of 247's Team Talent Composite page."""
    link = 'https://247sports.com/college/x/team/x-football-1/roster/'
    return (f'<li class="rankings-page__list-item"> <div class="wrapper"> <div class="rank-column"> <div class="primary"> {rank} </div> </div>'
            f' <div class="team-image-block"><img alt="{team}" /></div> <div class="team"> <a class="rankings-page__name-link" href="{link}">{team} </a> </div>'
            f' <div class="total"> <a href="{link}">{players} Commits </a> </div> <div class="avg"> {avg} </div>'
            f' <ul class="star-commits-list"> <li> <h2>5-Star</h2> <div class="gold"> {five} </div> </li> <li> <h2>4-Star</h2> <div class="gold"> {four} </div> </li>'
            f' <li> <h2>3-Star</h2> <div> {three} </div> </li> </ul> <div class="points"> <a class="number" href="{link}">{points} </a> </div>'
            f' </div> <div data-react-container="player-ranking-flyout"></div> </li>')


SHOW_MORE = '<li class="rankings-page__showmore showmore_blk"><a data-js="showmore" href="?Page=2">Load More</a></li>'
PAGE = ('<ul><li class="rankings-page__header"><b><a href="?OrderBy=Points">Points</a></b></li>'
        + item(1, 'Georgia', '1,003.67', '91.97', 105, 13, 69, 23)
        + item(2, 'San Jose State', '412.10', '84.20', 61, 0, 2, 40)
        + SHOW_MORE+'</ul>')


class ParseTests(unittest.TestCase):
    def test_a_row_is_read_with_its_thousands_separator(self):
        self.assertEqual(talent.parse(PAGE)[0], {'team': 'Georgia', 'rank': 1, 'points': 1003.67, 'avg_rating': 91.97,
                                                 'players': 105, 'five_star': 13, 'four_star': 69, 'three_star': 23})

    def test_every_row_is_read_and_the_load_more_link_is_not_a_school(self):
        self.assertEqual([r['team'] for r in talent.parse(PAGE)], ['Georgia', 'San Jose State'])

    def test_a_page_without_rows_reads_as_empty(self):
        self.assertEqual(talent.parse('<html><body>Not found</body></html>'), [])


class KeyTests(unittest.TestCase):
    def test_247_names_reach_the_scoreboards_name(self):
        for scoreboard, composite in (('San José State', 'San Jose State'), ('UL Monroe', 'Louisiana-Monroe'),
                                      ('Florida International', 'FIU'), ('Ole Miss', 'Ole Miss'),
                                      ('Miami (OH)', 'Miami (OH)')):
            self.assertEqual(talent.key(scoreboard), talent.key(composite), scoreboard)

    def test_the_two_miamis_stay_apart(self):
        self.assertNotEqual(talent.key('Miami'), talent.key('Miami (OH)'))


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.original, talent.MIN_SCHOOLS = talent.MIN_SCHOOLS, 3

    def tearDown(self):
        talent.MIN_SCHOOLS = self.original

    def test_load_more_pages_are_followed_until_they_add_nobody(self):
        second = item(3, 'Texas', '980.00', '91.71', 90, 15, 42, 33)+SHOW_MORE
        pages = {1: PAGE, 2: second, 3: second}
        asked = []

        def get(url):
            page = int(url.rsplit('Page=', 1)[1]) if 'Page=' in url else 1
            asked.append(page)
            return pages[page]
        stored = talent.fetch_season(2026, get)
        self.assertEqual(set(stored['schools']), {'georgia', 'sanjosestate', 'texas'})
        self.assertEqual(asked, [1, 2, 3])
        self.assertEqual(stored['season'], 2026)

    def test_too_few_schools_is_refused_rather_than_cached(self):
        with self.assertRaises(ValueError):
            talent.fetch_season(2026, lambda url: '<html></html>')


class CacheTests(unittest.TestCase):
    def stored(self, season, age_days=0):
        fetched = (datetime.now().astimezone()-timedelta(days=age_days)).isoformat(timespec='seconds')
        return {'season': season, 'fetched_at': fetched, 'source': 'x',
                'schools': {talent.key(r['team']): r for r in talent.parse(PAGE)}}

    def refuse(self, url):
        raise OSError('offline')

    def test_a_missing_or_damaged_cache_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            self.assertEqual(talent.load(data), {})
            (data/talent.CACHE_NAME).write_text('{oops', encoding='utf-8')
            self.assertEqual(talent.load(data), {})

    def test_a_fresh_cache_for_this_season_is_reused_without_a_network_call(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data/talent.CACHE_NAME).write_text(json.dumps(self.stored(2026)), encoding='utf-8')
            self.assertIn('georgia', talent.refresh(data, 2026, get=self.refuse)['schools'])

    def test_last_seasons_rosters_are_never_used_for_this_season(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data/talent.CACHE_NAME).write_text(json.dumps(self.stored(2025)), encoding='utf-8')
            with self.assertRaises(OSError):
                talent.refresh(data, 2026, get=self.refuse)

    def test_a_failed_refresh_falls_back_to_this_seasons_older_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data/talent.CACHE_NAME).write_text(json.dumps(self.stored(2026, age_days=10)), encoding='utf-8')
            result = talent.refresh(data, 2026, get=self.refuse)
            self.assertIn('georgia', result['schools'])
            self.assertIn('cached copy', result['warning'])


class WeightTests(unittest.TestCase):
    def test_the_prior_is_strongest_before_any_games(self):
        self.assertAlmostEqual(talent.weight(0), talent.MAX_WEIGHT)

    def test_it_fades_to_exactly_zero_once_a_team_has_a_sample(self):
        self.assertEqual(talent.weight(talent.FADE_GAMES), 0.0)
        weights = [talent.weight(g) for g in range(talent.FADE_GAMES+1)]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_setting_the_maximum_weight_to_zero_disables_the_prior(self):
        original, talent.MAX_WEIGHT = talent.MAX_WEIGHT, 0.0
        try:
            self.assertEqual(talent.team_shift({'slope': 4.0, 'intercept': -340.0}, {'avg_rating': 92.0}, 0.0, 0), 0.0)
        finally:
            talent.MAX_WEIGHT = original


class ShiftTests(unittest.TestCase):
    # 90 average implies a +20 rating; 85 implies 0.
    FIT = {'slope': 4.0, 'intercept': -340.0}
    DEEP, THIN = {'avg_rating': 90.0}, {'avg_rating': 85.0}

    def test_a_team_rated_below_its_roster_is_pulled_up(self):
        self.assertAlmostEqual(talent.team_shift(self.FIT, self.DEEP, 10.0, 0), talent.MAX_WEIGHT*10.0, places=3)

    def test_a_team_rated_above_its_roster_is_pulled_down(self):
        self.assertAlmostEqual(talent.team_shift(self.FIT, self.THIN, 6.0, 0), -talent.MAX_WEIGHT*6.0, places=3)

    def test_a_team_already_matching_its_roster_is_not_moved(self):
        self.assertEqual(talent.team_shift(self.FIT, self.DEEP, 20.0, 0), 0.0)

    def test_an_fcs_opponent_sits_out_while_the_fbs_side_is_still_measured(self):
        self.assertAlmostEqual(talent.margin_shift(self.FIT, self.DEEP, None, 10.0, -30.0, 0, 0), talent.MAX_WEIGHT*10.0, places=2)
        self.assertAlmostEqual(talent.margin_shift(self.FIT, None, self.DEEP, -30.0, 10.0, 0, 0), -talent.MAX_WEIGHT*10.0, places=2)

    def test_the_shift_shrinks_as_the_season_supplies_real_games(self):
        early = talent.margin_shift(self.FIT, self.DEEP, self.THIN, 10.0, 6.0, 0, 0)
        later = talent.margin_shift(self.FIT, self.DEEP, self.THIN, 10.0, 6.0, 4, 4)
        done = talent.margin_shift(self.FIT, self.DEEP, self.THIN, 10.0, 6.0, talent.FADE_GAMES, talent.FADE_GAMES)
        self.assertGreater(early, later)
        self.assertGreater(later, 0)
        self.assertEqual(done, 0.0)

    def test_no_fit_or_no_row_means_no_shift(self):
        self.assertEqual(talent.margin_shift(None, self.DEEP, self.THIN, 0.0, 0.0, 0, 0), 0.0)
        self.assertEqual(talent.team_shift(self.FIT, None, 0.0, 0), 0.0)


class FitAndBoardTests(unittest.TestCase):
    def stored(self, count):
        return {'schools': {talent.key(f'School{i}'): {'team': f'School{i}', 'rank': count-i, 'avg_rating': 80+i*0.5}
                            for i in range(count)}}

    def ratings(self, count):
        return {f't{i}': {'rating': -20+i*2.0} for i in range(count)}

    def names(self, count):
        return {f't{i}': f'School{i}' for i in range(count)}

    def test_too_few_overlapping_schools_produces_no_fit(self):
        n = talent.MIN_FIT_TEAMS-1
        self.assertIsNone(talent.fit(self.stored(n), self.ratings(n), self.names(n)))

    def test_a_clean_relationship_is_recovered(self):
        n = talent.MIN_FIT_TEAMS+10
        fitted = talent.fit(self.stored(n), self.ratings(n), self.names(n))
        self.assertAlmostEqual(fitted['slope'], 4.0, places=3)
        self.assertGreater(fitted['r_squared'], 0.99)
        self.assertEqual(fitted['teams'], n)

    def test_the_leaderboard_follows_247s_rank(self):
        ranks = [r['rank'] for r in talent.leaderboard(self.stored(5))]
        self.assertEqual(ranks, sorted(ranks))

    def test_lookup_uses_the_scoreboard_name(self):
        stored = {'schools': {talent.key(r['team']): r for r in talent.parse(PAGE)}}
        self.assertEqual(talent.lookup(stored, 'San José State')['avg_rating'], 84.2)
        self.assertIsNone(talent.lookup(stored, 'Nowhere State'))
        self.assertIsNone(talent.lookup(None, 'Georgia'))


if __name__ == '__main__':
    unittest.main()
