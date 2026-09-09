import unittest
from feeds import parse_events, parse_cbs, parse_dk, composite_teams


class FeedTests(unittest.TestCase):
    def test_composite_has_50_unique_teams_and_counts_each_poll_once(self):
        events=[{'home_id':str(i),'home':f'Team {i}','away_id':str(i+1),'away':f'Team {i+1}'} for i in range(1,60)]
        cbs={f'team{i}':i for i in range(1,61)}
        ap={str(i):i for i in range(1,26)}
        coaches={str(i):i for i in range(1,26)}
        teams=composite_teams(events,cbs,ap,coaches)
        self.assertEqual(len(teams),50)
        self.assertEqual(len({t['id'] for t in teams}),50)
        self.assertEqual(teams[0]['score'],100)
        self.assertEqual(teams[-1]['team'],'Team 50')
        self.assertEqual(teams,composite_teams(list(reversed(events)),cbs,ap,coaches))

    def test_away_favorite_and_unfinished_score(self):
        data = {'events': [dict(id='1', date='2026-09-12T18:00Z', season={'year':2026}, competitions=[dict(status={'type':{'completed':False}}, competitors=[dict(homeAway='home', team={'id':'a','displayName':'A'},score='20'),dict(homeAway='away',team={'id':'b','displayName':'B'},score='30')], odds=[{'provider':{'name':'DraftKings'}, 'pointSpread':{'home':{'close':{'line':'+7','odds':'-105'}},'away':{'close':{'line':'-7','odds':'-115'}}}}])])]}
        e = parse_events(data)[0]
        self.assertEqual(e['home_spread'], 7)
        self.assertEqual(e['away_spread'], -7)
        self.assertIsNone(e['home_score'])

    def test_changed_cbs_layout_fails_explicitly(self):
        with self.assertRaises(ValueError):
            parse_cbs('<html>No rankings</html>')

    def test_splits_only_spread_market(self):
        template = '''<div class="tb-se border-x"><h5>A @ B</h5><span>9/12, 12PM</span><div class="tb-se-head">Spread Odds</div><div class="tb-sodd"><div class="tb-slipline">B +7</div><a class="tb-odd-s">−110</a><div class="flex-1">65%</div><div class="flex-1">40%</div><div class="tb-se-head">Total Odds</div><div class="tb-sodd"><div class="tb-slipline">Over +50</div><a class="tb-odd-s">−110</a><div class="flex-1">99%</div><div class="flex-1">99%</div>'''
        rows = parse_dk(template)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['handle'],rows[0]['bets']), (65,40))


if __name__ == '__main__':
    unittest.main()
