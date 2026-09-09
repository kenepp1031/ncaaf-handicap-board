import json
import math
import tempfile
import unittest
from pathlib import Path
import nil

# Shaped like the source page: a conference-median table that must be ignored,
# the per-school roster table, and the all-schools expense table.
PAGE = '''
<table><tr><th>Median FBS Roster Costs by Conference 2026-27</th><th>Total Payments to Players ($)</th>
<th>Paid by School</th></tr><tr><td>SEC</td><td>30,161,000</td><td>15,600,000</td></tr></table>
<table><tr><th>Estimated Roster Costs P4 Football Teams 2026 *</th><th>Conference</th><th>Roster Cost Estimate ($)</th></tr>
<tr><td>Texas</td><td>SEC</td><td>46,485,000</td></tr>
<tr><td>Louisiana State</td><td>SEC</td><td>40,966,000</td></tr>
<tr><td>Brigham Young</td><td>Big 12</td><td>23,041,000</td></tr></table>
<table><tr><th>NCAA I Athletic Department Annual Expenses 2022-25 *</th><th>Spending Rank *</th><th>Football Sub-Div</th>
<th>Football Conference</th><th>Basketball Conference</th><th>FY 2025 ($)</th></tr>
<tr><td>Ohio State</td><td>1</td><td>FBS</td><td>Big Ten</td><td>Big Ten</td><td>295,265,883</td></tr>
<tr><td>Miami</td><td>8</td><td>FBS</td><td>ACC</td><td>ACC</td><td>230,484,608</td></tr>
<tr><td>Miami</td><td>139</td><td>FBS</td><td>MAC</td><td>MAC</td><td>40,792,930</td></tr>
<tr><td>Prairie View A&amp;M</td><td>300</td><td>FCS</td><td>SWAC</td><td>SWAC</td><td>18,000,000</td></tr>
<tr><td>Some Lacrosse School</td><td>310</td><td></td><td></td><td></td><td>9,000,000</td></tr></table>
'''


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.parsed = nil.parse(PAGE)

    def test_the_conference_median_table_is_not_read_as_schools(self):
        self.assertNotIn('sec', self.parsed['roster'])
        self.assertEqual(len(self.parsed['roster']), 3)

    def test_roster_costs_are_read_with_formal_names_mapped(self):
        self.assertEqual(self.parsed['roster']['texas'], 46485000)
        self.assertEqual(self.parsed['roster']['lsu'], 40966000)
        self.assertEqual(self.parsed['roster']['byu'], 23041000)

    def test_expenses_cover_fbs_and_fcs_but_skip_schools_without_football(self):
        self.assertEqual(self.parsed['expenses']['ohiostate'], 295265883)
        self.assertEqual(self.parsed['expenses']['prairieviewam'], 18000000)
        self.assertNotIn('somelacrosseschool', self.parsed['expenses'])

    def test_the_expense_label_names_the_year_actually_taken(self):
        self.assertIn('FY 2025', self.parsed['labels']['expenses'])

    def test_the_two_schools_named_miami_are_kept_apart(self):
        # Regression: the MAC row overwrote the ACC one, so Miami (FL) carried
        # Miami (OH)'s budget into the model.
        self.assertEqual(self.parsed['expenses']['miami'], 230484608)
        self.assertEqual(self.parsed['expenses']['miamiohio'], 40792930)

    def test_a_page_with_no_tables_is_refused(self):
        with self.assertRaises(ValueError):
            nil.parse('<html><body>nothing here</body></html>')


class KeyTests(unittest.TestCase):
    def test_formal_names_reach_the_scoreboards_short_name(self):
        for formal, expected in (('Louisiana State', 'lsu'), ('Southern Cal', 'usc'), ('Texas Christian', 'tcu'),
                                 ('Southern Methodist', 'smu'), ('Central Florida', 'ucf'),
                                 ('Louisiana - Monroe', 'ullmonroe'), ('Mississippi', 'olemiss')):
            self.assertEqual(nil.key(formal), expected, formal)


class WeightTests(unittest.TestCase):
    def test_the_prior_is_strongest_before_any_games(self):
        self.assertAlmostEqual(nil.weight(0), nil.MAX_WEIGHT)

    def test_it_fades_to_exactly_zero_once_a_team_has_a_sample(self):
        self.assertEqual(nil.weight(nil.FADE_GAMES), 0.0)
        self.assertEqual(nil.weight(nil.FADE_GAMES+5), 0.0)

    def test_it_decreases_every_game(self):
        weights = [nil.weight(g) for g in range(nil.FADE_GAMES+1)]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_setting_the_maximum_weight_to_zero_disables_the_prior(self):
        original, nil.MAX_WEIGHT = nil.MAX_WEIGHT, 0.0
        try:
            self.assertEqual(nil.weight(0), 0.0)
            self.assertEqual(nil.team_shift({'slope': 9.8, 'intercept': -160.0}, 40000000, 1.0, 0), 0.0)
        finally:
            nil.MAX_WEIGHT = original


class TeamShiftTests(unittest.TestCase):
    FIT = {'slope': 10.0, 'intercept': -100.0}

    def test_spending_more_than_the_results_justify_pulls_a_team_up(self):
        dollars = math.exp(10.5)
        behind = nil.implied_rating(self.FIT, dollars)-10.0
        self.assertAlmostEqual(nil.team_shift(self.FIT, dollars, behind, 0), nil.MAX_WEIGHT*10.0, places=2)

    def test_a_team_already_matching_its_spending_is_not_moved(self):
        dollars = 30000000
        self.assertAlmostEqual(nil.team_shift(self.FIT, dollars, nil.implied_rating(self.FIT, dollars), 0), 0.0, places=6)

    def test_missing_money_or_fit_or_sample_means_no_shift(self):
        self.assertEqual(nil.team_shift(self.FIT, None, 0.0, 0), 0.0)
        self.assertEqual(nil.team_shift(None, 30000000, 0.0, 0), 0.0)
        self.assertEqual(nil.team_shift(self.FIT, 30000000, 0.0, nil.FADE_GAMES), 0.0)


class MarginShiftTests(unittest.TestCase):
    FITS = {'roster': {'slope': 10.0, 'intercept': -100.0},
            'expenses': {'slope': 3.0, 'intercept': -40.0}}
    P4 = {'roster_cost': 40000000, 'athletic_expenses': 220000000}
    RICH_P4 = {'roster_cost': 46000000, 'athletic_expenses': 280000000}
    FCS = {'roster_cost': None, 'athletic_expenses': 20000000}

    def test_two_power_four_schools_are_compared_on_roster_cost(self):
        points, measure = nil.margin_shift(self.FITS, self.RICH_P4, self.P4, 0.0, 0.0, 0, 0)
        self.assertEqual(measure, 'roster')
        self.assertGreater(points, 0)

    def test_a_game_against_an_fcs_school_gets_no_prior(self):
        # The expense fit puts a Power 4 host only a few points above an FCS
        # visitor, so shrinking toward it moved those projections the wrong way.
        self.assertEqual(nil.margin_shift(self.FITS, self.P4, self.FCS, 0.0, 0.0, 0, 0), (0.0, None))

    def test_a_roster_cost_is_never_compared_against_a_whole_athletic_budget(self):
        # Regression: an FCS school's $20M department budget outsized a Power 4
        # school's $19M player payroll, which pushed the prior toward the FCS side.
        lean_payroll = {'roster_cost': 19000000, 'athletic_expenses': 150000000}
        points, measure = nil.margin_shift(self.FITS, lean_payroll, self.FCS, 0.0, 0.0, 0, 0)
        self.assertIsNone(measure)
        self.assertEqual(points, 0.0)

    def test_the_bigger_spender_is_favoured_when_neither_has_overachieved(self):
        points, measure = nil.margin_shift(self.FITS, self.RICH_P4, self.P4,
                                           nil.implied_rating(self.FITS['roster'], self.RICH_P4['roster_cost']),
                                           nil.implied_rating(self.FITS['roster'], self.P4['roster_cost']), 0, 0)
        self.assertEqual(measure, 'roster')
        self.assertAlmostEqual(points, 0.0, places=6)

    def test_a_school_in_neither_table_sits_the_prior_out(self):
        blank = {'roster_cost': None, 'athletic_expenses': None}
        self.assertEqual(nil.margin_shift(self.FITS, self.P4, blank, 0.0, 0.0, 0, 0), (0.0, None))

    def test_no_fit_means_no_shift(self):
        self.assertEqual(nil.margin_shift(None, self.P4, self.P4, 0.0, 0.0, 0, 0), (0.0, None))

    def test_two_identical_schools_cancel_out(self):
        points, _ = nil.margin_shift(self.FITS, self.P4, self.P4, 2.0, 2.0, 0, 0)
        self.assertAlmostEqual(points, 0.0, places=6)

    def test_the_shift_shrinks_as_the_season_supplies_real_games(self):
        early, _ = nil.margin_shift(self.FITS, self.RICH_P4, self.P4, 0.0, 0.0, 0, 0)
        later, _ = nil.margin_shift(self.FITS, self.RICH_P4, self.P4, 0.0, 0.0, 4, 4)
        done, _ = nil.margin_shift(self.FITS, self.RICH_P4, self.P4, 0.0, 0.0, nil.FADE_GAMES, nil.FADE_GAMES)
        self.assertGreater(early, later)
        self.assertGreater(later, 0)
        self.assertEqual(done, 0.0)


class FitTests(unittest.TestCase):
    def _ratings(self, count):
        return {f't{i}': {'rating': i*0.5, 'games': 3} for i in range(count)}

    def _names(self, count):
        return {f't{i}': f'School{i}' for i in range(count)}

    def _stored(self, count):
        return {'roster': {nil.key(f'School{i}'): 20000000+i*1000000 for i in range(count)}}

    def test_too_few_overlapping_schools_produces_no_fit(self):
        n = nil.MIN_FIT_TEAMS-1
        self.assertIsNone(nil.fit(self._stored(n), self._ratings(n), self._names(n)))

    def test_a_clean_relationship_is_recovered(self):
        n = nil.MIN_FIT_TEAMS+10
        fits = nil.fit(self._stored(n), self._ratings(n), self._names(n))
        self.assertIn('roster', fits)
        self.assertGreater(fits['roster']['r_squared'], 0.9)
        self.assertEqual(fits['roster']['teams'], n)
        self.assertGreater(fits['roster']['points_per_doubling'], 0)


class CacheAndBoardTests(unittest.TestCase):
    def test_a_missing_or_damaged_cache_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            self.assertEqual(nil.load(data), {})
            (data/nil.CACHE_NAME).write_text('{oops', encoding='utf-8')
            self.assertEqual(nil.load(data), {})

    def test_a_fresh_cache_is_reused_without_a_network_call(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stored = nil.parse(PAGE)
            (data/nil.CACHE_NAME).write_text(json.dumps(stored), encoding='utf-8')
            self.assertEqual(nil.refresh(data)['roster'], stored['roster'])

    def test_the_leaderboard_puts_roster_spending_first(self):
        rows = nil.leaderboard(nil.parse(PAGE))
        self.assertEqual(rows[0]['school'], 'Texas')
        self.assertEqual(rows[0]['spend_rank'], 1)
        self.assertIsNone(rows[-1]['roster_cost'])
        costs = [r['roster_cost'] for r in rows if r['roster_cost']]
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_spending_lookup_uses_the_scoreboard_name(self):
        stored = nil.parse(PAGE)
        self.assertEqual(nil.spending(stored, 'LSU')['roster_cost'], 40966000)
        self.assertEqual(nil.spending(stored, 'Prairie View A&M')['athletic_expenses'], 18000000)
        self.assertEqual(nil.spending(stored, 'Nowhere State'), {'roster_cost': None, 'athletic_expenses': None})


if __name__ == '__main__':
    unittest.main()
