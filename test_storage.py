import tempfile
import unittest
from pathlib import Path
from storage import Store, settle


def pick(**updates):
    p = dict(game_date='2026-09-12', home='School A', away='School B', side='Home', spread=-7, odds=-110, stake=1, home_score=None, away_score=None, notes='My pick')
    p.update(updates)
    return p


class TrackerTests(unittest.TestCase):
    def test_settlement(self):
        self.assertEqual(settle(pick()), ('Pending', 0))
        self.assertEqual(settle(pick(home_score=27, away_score=20)), ('Push', 0))
        self.assertEqual(settle(pick(home_score=26, away_score=20)), ('Loss', -1))
        self.assertAlmostEqual(settle(pick(home_score=28, away_score=20))[1], 100/110)
        self.assertEqual(settle(pick(side='Away', spread=7.5, home_score=27, away_score=20, odds=120, stake=2)), ('Win', 2.4))

    def test_persistence_edit_and_backup(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d)/'picks.sqlite3'
            s = Store(db)
            s.save(pick())
            created = s.all()[0]['created_at']
            s.db.close()
            s = Store(db)
            self.assertEqual(len(s.all()), 1)
            s.save(pick(home_score=30, away_score=20), s.all()[0]['id'])
            self.assertEqual(s.all()[0]['created_at'], created)
            self.assertEqual(settle(s.all()[0])[0], 'Win')
            backup = Path(d)/'backup.sqlite3'
            s.backup(backup)
            b = Store(backup)
            self.assertEqual(b.all(), s.all())
            b.db.close()
            s.db.close()

    def test_auto_grading_preserves_picked_line(self):
        s = Store(':memory:')
        s.save(pick(event_id='123', market_snapshot='original', spread=-7))
        s.apply_scores([dict(id='123', completed=False, home_score=30, away_score=20)])
        self.assertEqual(settle(s.all()[0])[0], 'Pending')
        s.apply_scores([dict(id='123', completed=True, home_score=30, away_score=20, home_spread=-12)])
        saved = s.all()[0]
        self.assertEqual(saved['spread'], -7)
        self.assertEqual(saved['market_snapshot'], 'original')
        self.assertEqual(settle(saved)[0], 'Win')
        s.db.close()


if __name__ == '__main__':
    unittest.main()
