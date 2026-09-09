import unittest
from datetime import date
import power
from test_power import played


class RankingPoolTests(unittest.TestCase):
    def test_fcs_opponent_is_not_given_an_fbs_grade(self):
        events=[played('1',1,'P','F',42,3),played('2',2,'Q','F',21,7)]
        payload={'events':events,'cbs':{'teamp':1,'teamq':2},'top50':[{'id':'P','rank':1},{'id':'Q','rank':2}]}
        result=power.build(payload,date(2026,9,9))
        rows={t['id']:t for t in result['team_ratings']}
        self.assertEqual(result['ranking_population'],2)
        self.assertIsNone(rows['F']['offense_rank'])
        self.assertIsNone(rows['F']['offense_grade'])
        self.assertFalse(rows['F']['ranked'])
        for metric in ('offense','defense'):
            self.assertEqual(sorted(rows[t][metric+'_rank'] for t in ('P','Q')),[1,2])
            self.assertEqual(rows['P'][metric+'_grade'],power.letter_grade(rows['P'][metric],[rows[t][metric] for t in ('P','Q')]))
        for row in result['ratings']:
            self.assertEqual(row['offense_rank'],rows[row['id']]['offense_rank'])
            self.assertEqual(row['offense_grade'],rows[row['id']]['offense_grade'])

    def test_cbs_abbreviations_match_schedule_names(self):
        for short,long in [('Miss. State','Mississippi State'),('Iowa St.','Iowa State'),('FIU','Florida International'),('San José State','San Jose State')]:
            self.assertEqual(power.fbs_key(short),power.fbs_key(long))
