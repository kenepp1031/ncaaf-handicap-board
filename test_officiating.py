import unittest
import officiating


def summary(home_pen, home_yards, away_pen, away_yards):
    return {'boxscore': {'teams': [
        {'team': {}, 'homeAway': 'home', 'statistics': [
            {'name': 'totalPenaltiesYards', 'displayValue': f'{home_pen}-{home_yards}'}]},
        {'team': {}, 'homeAway': 'away', 'statistics': [
            {'name': 'totalPenaltiesYards', 'displayValue': f'{away_pen}-{away_yards}'}]}]}}


class ExtractTests(unittest.TestCase):
    def test_extracts_both_sides(self):
        row = officiating._extract(summary(9, 64, 4, 27))
        self.assertEqual(row, {'home_penalties': 9, 'home_penalty_yards': 64,
                                'away_penalties': 4, 'away_penalty_yards': 27})

    def test_missing_stat_yields_none(self):
        self.assertIsNone(officiating._extract({'boxscore': {'teams': []}}))


class TeamRatesTests(unittest.TestCase):
    def setUp(self):
        self.events = [
            {'id': 'g1', 'completed': True, 'home_id': 'A', 'away_id': 'B'},
            {'id': 'g2', 'completed': True, 'home_id': 'B', 'away_id': 'A'},
            {'id': 'g3', 'completed': False, 'home_id': 'A', 'away_id': 'C'},
        ]
        self.cache = {
            'g1': {'home_penalties': 10, 'home_penalty_yards': 90, 'away_penalties': 4, 'away_penalty_yards': 30},
            'g2': {'home_penalties': 6, 'home_penalty_yards': 50, 'away_penalties': 8, 'away_penalty_yards': 70},
        }

    def test_incomplete_or_uncached_games_are_skipped(self):
        rates = officiating.team_rates(self.events, self.cache)
        self.assertNotIn('C', rates)

    def test_own_and_drawn_rates_average_across_home_and_away(self):
        rates = officiating.team_rates(self.events, self.cache)
        # A: 10 (home in g1) + 8 (away in g2) committed = 9/game; drew 4+6=5/game
        self.assertEqual(rates['A']['penalties_per_game'], 9.0)
        self.assertEqual(rates['A']['drawn_per_game'], 5.0)
        self.assertEqual(rates['A']['net_penalty_margin'], -4.0)
        self.assertEqual(rates['A']['home_penalties_per_game'], 10.0)
        self.assertEqual(rates['A']['away_penalties_per_game'], 8.0)


class FitAndShiftTests(unittest.TestCase):
    def test_fit_returns_none_without_enough_overlap(self):
        ratings = {'A': {'rating': 5.0}}
        rates = {'A': {'games': 5, 'net_penalty_margin': 1.0}}
        self.assertIsNone(officiating.fit(ratings, rates))

    def test_weight_grows_with_sample_then_caps(self):
        self.assertEqual(officiating.weight(0), 0.0)
        half = officiating.weight(officiating.FULL_SAMPLE_GAMES/2)
        full = officiating.weight(officiating.FULL_SAMPLE_GAMES)
        over = officiating.weight(officiating.FULL_SAMPLE_GAMES*2)
        self.assertAlmostEqual(half, officiating.MAX_WEIGHT/2)
        self.assertEqual(full, officiating.MAX_WEIGHT)
        self.assertEqual(over, officiating.MAX_WEIGHT)

    def test_margin_shift_is_zero_without_a_fit(self):
        self.assertEqual(officiating.margin_shift(None, {'games': 5, 'net_penalty_margin': 2}, {'games': 5, 'net_penalty_margin': -2}, 1.0, -1.0), 0.0)

    def test_margin_shift_favors_the_side_with_the_better_implied_rating(self):
        fitted = {'slope': 1.0, 'intercept': 0.0}
        home_rate = {'games': officiating.FULL_SAMPLE_GAMES, 'net_penalty_margin': 5.0}
        away_rate = {'games': officiating.FULL_SAMPLE_GAMES, 'net_penalty_margin': -5.0}
        shift = officiating.margin_shift(fitted, home_rate, away_rate, 0.0, 0.0)
        self.assertGreater(shift, 0.0)


if __name__ == '__main__':
    unittest.main()
