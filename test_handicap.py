import unittest
from datetime import date
from types import SimpleNamespace
from handicap import Model, backtest, projection


def game(day, home='A', away='B', hp=30, ap=20, spread=-3):
    return dict(date=date(2025, 9, day), home_team=home, away_team=away, home_score=hp, away_score=ap, neutral=False, home_spread=spread, total=50, home_odds=-110, away_odds=-110)


class ModelTests(unittest.TestCase):
    def test_future_and_same_day_scores_cannot_change_model(self):
        past = [game(1), game(2, 'B', 'A', 20, 30)]
        m = Model(past, date(2025, 9, 3))
        contaminated = Model(past+[game(3, hp=100), game(4, hp=200)], date(2025, 9, 3))
        self.assertEqual(m.predict(game(3)), contaminated.predict(game(3)))

    def test_neutral_venue_and_spread_sign(self):
        m = Model([game(1, hp=25, ap=25)], date(2025, 9, 2))
        g = game(3)
        home = m.predict(g)
        g['neutral'] = True
        neutral = m.predict(g)
        self.assertAlmostEqual((home[0]-home[1])-(neutral[0]-neutral[1]), 3)
        p = projection(m, g)
        self.assertAlmostEqual(p['home_edge_points'], -p['fair_home_spread']-3, places=2)

    def test_unknown_team_is_rejected(self):
        m = Model([game(1)], date(2025, 9, 2))
        with self.assertRaises(ValueError):
            m.predict(game(3, away='Unknown'))

    def test_backtest_push_win_loss_and_vig(self):
        games = [game(1, hp=40, ap=10), game(2, hp=40, ap=10), game(3, hp=20, ap=20, spread=0), game(4, hp=30, ap=10, spread=0), game(5, hp=10, ap=30, spread=0)]
        args = SimpleNamespace(ridge=8, half_life=180, home_advantage=3, min_games=2, threshold=0)
        r = backtest(games, args)
        self.assertEqual((r['wins'], r['losses'], r['pushes']), (1, 1, 1))
        self.assertAlmostEqual(r['profit_units'], 100/110-1)


if __name__ == '__main__':
    unittest.main()
