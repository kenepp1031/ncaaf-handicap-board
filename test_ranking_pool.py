import unittest
from datetime import date
import power
from test_power import played


class RankingPoolTests(unittest.TestCase):
    def test_fcs_opponent_is_not_rated_individually(self):
        events=[played('1',1,'P','F',42,3),played('2',2,'Q','F',21,7)]
        payload={'events':events,'cbs':{'teamp':1,'teamq':2},'top50':[{'id':'P','rank':1},{'id':'Q','rank':2}]}
        result=power.build(payload,date(2026,9,9))
        rows={t['id']:t for t in result['team_ratings']}
        self.assertEqual(result['ranking_population'],2)
        # F now shares the pooled FCS rating rather than carrying an unranked
        # row of its own, and the pooled entity is not a team either.
        self.assertNotIn('F',rows)
        self.assertNotIn(power.POOLED_FCS,rows)
        self.assertEqual(sorted(rows),['P','Q'])
        self.assertEqual(result['fcs_pooled']['games'],2)
        for metric in ('offense','defense'):
            self.assertEqual(sorted(rows[t][metric+'_rank'] for t in ('P','Q')),[1,2])
            self.assertEqual(rows['P'][metric+'_grade'],power.letter_grade(rows['P'][metric],[rows[t][metric] for t in ('P','Q')]))
        for row in result['ratings']:
            self.assertEqual(row['offense_rank'],rows[row['id']]['offense_rank'])
            self.assertEqual(row['offense_grade'],rows[row['id']]['offense_grade'])

    def test_without_a_membership_list_no_team_is_pooled_away(self):
        # A failed CBS fetch must cost only the FCS fix, never collapse the
        # whole league into one entity.
        events=[played('1',1,'P','F',42,3),played('2',2,'Q','F',21,7)]
        result=power.build({'events':events,'top50':[{'id':'P','rank':1}]},date(2026,9,9))
        rows={t['id']:t for t in result['team_ratings']}
        self.assertEqual(sorted(rows),['F','P','Q'])
        self.assertIsNone(result['fcs_pooled'])

    def test_cbs_abbreviations_match_schedule_names(self):
        for short,long in [('Miss. State','Mississippi State'),('Iowa St.','Iowa State'),('FIU','Florida International'),('San José State','San Jose State')]:
            self.assertEqual(power.fbs_key(short),power.fbs_key(long))
