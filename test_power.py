import unittest
from datetime import date
import power


def played(id, day, home, away, hs, as_, spread=-3, total=45, completed=True, home_combined=None, away_combined=None, weather=None):
    return {'id': id, 'game_date': date(2026, 9, day).isoformat() if day > 0 else date(2026, 8, 32+day).isoformat(),
            'home_id': home, 'away_id': away, 'home': f'Team {home}', 'away': f'Team {away}',
            'completed': completed, 'neutral': False, 'home_score': hs, 'away_score': as_,
            'home_spread': spread, 'total': total, 'home_combined': home_combined, 'away_combined': away_combined,
            'weather': weather}


class LetterGradeTests(unittest.TestCase):
    def test_best_in_pool_gets_an_a_plus(self):
        # 19 of 20 values below -> 95th percentile, right at the A+ cutoff.
        pool = list(range(1, 21))
        self.assertEqual(power.letter_grade(20, pool), 'A+')

    def test_worst_in_pool_gets_an_f(self):
        self.assertEqual(power.letter_grade(1.0, [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 'F')

    def test_middle_of_pool_gets_a_middling_grade(self):
        pool = list(range(1, 21))
        self.assertIn(power.letter_grade(10, pool), ('B-', 'B', 'C+', 'C'))

    def test_none_value_has_no_grade(self):
        self.assertIsNone(power.letter_grade(None, [1, 2, 3]))

    def test_empty_population_has_no_grade(self):
        self.assertIsNone(power.letter_grade(5.0, [None, None]))


class PowerLeanTests(unittest.TestCase):
    def test_no_notes_just_rounds_the_fair_spread(self):
        self.assertEqual(power.power_lean(-3.3, [], []), -3.5)
        self.assertEqual(power.power_lean(-3.1, [], []), -3.0)

    def test_home_letdown_moves_the_lean_toward_the_away_team(self):
        base = power.power_lean(-3.0, [], [])
        with_letdown = power.power_lean(-3.0, ['Letdown risk: won last week as an underdog'], [])
        self.assertGreater(with_letdown, base)

    def test_away_lookahead_moves_the_lean_toward_the_home_team(self):
        base = power.power_lean(0.0, [], [])
        with_lookahead = power.power_lean(0.0, [], ['Lookahead risk: plays a Top 25 team next week'])
        self.assertLess(with_lookahead, base)

    def test_bye_only_helps_the_rested_side(self):
        home_bye = power.power_lean(0.0, ['Off a bye (13 days rest)'], [])
        away_bye = power.power_lean(0.0, [], ['Off a bye (13 days rest)'])
        self.assertLess(home_bye, 0)
        self.assertGreater(away_bye, 0)

    def test_both_teams_off_a_bye_cancels_out(self):
        self.assertEqual(power.power_lean(0.0, ['Off a bye (13 days rest)'], ['Off a bye (14 days rest)']), 0.0)

    def test_hostile_environment_does_not_double_count_home_field(self):
        base = power.power_lean(0.0, [], [])
        with_hostile = power.power_lean(0.0, [], ['Road game at Tiger Stadium — hostile environment #1'])
        self.assertEqual(with_hostile, base)

    def test_result_is_always_rounded_to_the_nearest_half_point(self):
        for spread in (-7.3, -2.9, 0.0, 1.24, 4.76):
            result = power.power_lean(spread, [], [])
            self.assertEqual(result, round(result * 2) / 2)


class ApBlendTests(unittest.TestCase):
    def test_blend_pulls_toward_ap_and_can_flip_order(self):
        triples = [('P', 6.0, 25), ('Q', 5.0, 1), ('R', 10.0, None)]
        blended = dict(power._blend_with_ap(triples))
        self.assertGreater(blended['Q'], blended['P'])
        self.assertEqual(blended['R'], 10.0)

    def test_no_ranking_data_leaves_ratings_unchanged(self):
        triples = [('P', 6.0, None), ('Q', None, None)]
        self.assertEqual(power._blend_with_ap(triples), [('P', 6.0), ('Q', None)])

    def test_rank_one_maps_to_the_top_of_the_observed_range(self):
        blended = dict(power._blend_with_ap([('P', 1.0, 1), ('Q', 9.0, None)]))
        self.assertAlmostEqual(blended['P'], (1 - power.AP_BLEND_WEIGHT) * 1.0 + power.AP_BLEND_WEIGHT * 9.0)

    def test_none_rating_stays_none_even_when_ranked(self):
        blended = dict(power._blend_with_ap([('P', None, 1)]))
        self.assertIsNone(blended['P'])

    def test_a_poor_combined_rank_pulls_an_unranked_team_down_from_its_raw_rating(self):
        # This is what fixes an AP-unranked team acting as an unbeatable ceiling:
        # even the field's top raw rating loses ground once given a weak fallback rank.
        blended = dict(power._blend_with_ap([('P', 10.0, 45), ('Q', 8.0, 3)]))
        self.assertLess(blended['P'], 10.0)

    def test_build_wires_ap_rank_into_the_blend_without_touching_raw_rating(self):
        # Every team is already blended via its combined-poll rank as a fallback
        # (see _blend_with_ap), so this isolates what changes when AP data is
        # layered on top: the raw model numbers never move, only the blend does.
        events = [
            played('g1', -3, 'P', 'X1', 20, 10, spread=-10, home_combined=1),
            played('g1b', -2, 'P', 'X2', 20, 10, spread=-10, home_combined=1),
            played('g2', -3, 'Q', 'X3', 13, 10, spread=-3, home_combined=2),
            played('g2b', -2, 'Q', 'X4', 13, 10, spread=-3, home_combined=2),
        ]
        top50 = [{'id': 'P', 'rank': 1}, {'id': 'Q', 'rank': 2}]
        baseline = power.build({'events': events, 'top50': top50}, date(2026, 9, 5))
        with_ap = power.build({'events': events, 'top50': top50, 'ap': {'Q': 1}}, date(2026, 9, 5))
        base_by_id = {r['id']: r for r in baseline['ratings']}
        ap_by_id = {r['id']: r for r in with_ap['ratings']}
        self.assertIsNone(base_by_id['Q']['ap_rank'])
        self.assertEqual(ap_by_id['Q']['ap_rank'], 1)
        self.assertEqual(ap_by_id['P']['rating'], base_by_id['P']['rating'])
        self.assertEqual(ap_by_id['Q']['rating'], base_by_id['Q']['rating'])
        self.assertNotEqual(ap_by_id['Q']['blended_rating'], base_by_id['Q']['blended_rating'])


class AtsRecordTests(unittest.TestCase):
    def test_win_loss_push_from_closing_spread(self):
        events = [
            played('g1', -3, 'G', 'X', 20, 10, spread=-3),   # home win by 10, spread -3 -> covered (win)
            played('g2', -3, 'H', 'G', 13, 10, spread=-3),   # G away, lost by 3, spread for G is +3 -> push
            played('g3', -2, 'G', 'Y', 10, 20, spread=2),    # home dog +2, lost by 10 -> loss
        ]
        self.assertEqual(power.ats_record(events, 'G', date(2026, 9, 5)), {'wins': 1, 'losses': 1, 'pushes': 1})

    def test_games_without_a_spread_are_ignored(self):
        events = [played('g1', -3, 'G', 'X', 20, 10, spread=None)]
        self.assertEqual(power.ats_record(events, 'G', date(2026, 9, 5)), {'wins': 0, 'losses': 0, 'pushes': 0})


class SituationalNoteTests(unittest.TestCase):
    def test_bye_week_rest_is_flagged(self):
        events = [played('g1', -8, 'F', 'X', 30, 10, spread=-14),
                  played('g2', 5, 'F', 'W', 0, 0, completed=False)]
        notes = power.situational_notes(events, 'F', None, date(2026, 9, 5).isoformat(), {})
        self.assertTrue(any('bye' in n.lower() for n in notes))
        self.assertFalse(any('letdown' in n.lower() for n in notes))

    def test_letdown_after_underdog_upset_win_facing_unranked(self):
        events = [played('g1', -1, 'Z', 'A', 20, 24, spread=-10),  # A (away) was +10 dog and won outright
                  played('g2', 5, 'A', 'B', 0, 0, completed=False)]
        notes = power.situational_notes(events, 'A', None, date(2026, 9, 5).isoformat(), {})
        self.assertTrue(any('letdown' in n.lower() for n in notes))

    def test_no_letdown_when_team_was_the_favorite(self):
        events = [played('g1', -1, 'Z', 'A', 10, 30, spread=10),  # A (away) favored by 10, won big: not an upset
                  played('g2', 5, 'A', 'B', 0, 0, completed=False)]
        notes = power.situational_notes(events, 'A', None, date(2026, 9, 5).isoformat(), {})
        self.assertFalse(any('letdown' in n.lower() for n in notes))

    def test_lookahead_to_ranked_opponent_next_week(self):
        events = [played('g1', 5, 'C', 'D', 0, 0, completed=False),
                  played('g2', 12, 'E', 'C', 0, 0, completed=False)]
        notes = power.situational_notes(events, 'C', None, date(2026, 9, 5).isoformat(), {'E': 10})
        self.assertTrue(any('lookahead' in n.lower() for n in notes))

    def test_no_lookahead_when_this_week_opponent_is_also_ranked(self):
        events = [played('g1', 5, 'C', 'D', 0, 0, completed=False),
                  played('g2', 12, 'E', 'C', 0, 0, completed=False)]
        notes = power.situational_notes(events, 'C', 8, date(2026, 9, 5).isoformat(), {'E': 10})
        self.assertFalse(any('lookahead' in n.lower() for n in notes))


class WeatherNoteTests(unittest.TestCase):
    def test_high_wind_leans_under(self):
        self.assertIsNotNone(power.weather_note({'weather': {'wind_speed_10m': 22, 'precipitation': 0}}))

    def test_calm_and_dry_has_no_note(self):
        self.assertIsNone(power.weather_note({'weather': {'wind_speed_10m': 4, 'precipitation': 0}}))

    def test_rain_alone_leans_under(self):
        self.assertIsNotNone(power.weather_note({'weather': {'wind_speed_10m': 4, 'precipitation': 0.2}}))

    def test_missing_weather_has_no_note(self):
        self.assertIsNone(power.weather_note({}))


class WeatherAlertTests(unittest.TestCase):
    def test_wind_at_fifteen_mph_triggers_alert(self):
        alert = power.weather_alert({'weather': {'wind_speed_10m': 15, 'precipitation': 0}})
        self.assertIsNotNone(alert)
        self.assertIn('wind 15 mph', alert)

    def test_below_fifteen_mph_and_dry_has_no_alert(self):
        self.assertIsNone(power.weather_alert({'weather': {'wind_speed_10m': 14, 'precipitation': 0}}))

    def test_heavy_rain_triggers_alert(self):
        alert = power.weather_alert({'weather': {'wind_speed_10m': 2, 'precipitation': 0.15}})
        self.assertIn('rain', alert)

    def test_light_rain_triggers_alert(self):
        self.assertIn('rain', power.weather_alert({'weather': {'wind_speed_10m': 2, 'precipitation': 0.05}}))

    def test_snow_code_triggers_alert_regardless_of_wind_or_rain(self):
        alert = power.weather_alert({'weather': {'wind_speed_10m': 0, 'precipitation': 0, 'weather_code': 73}})
        self.assertIn('snow', alert)

    def test_snow_shower_code_also_triggers_alert(self):
        alert = power.weather_alert({'weather': {'wind_speed_10m': 0, 'precipitation': 0, 'weather_code': 85}})
        self.assertIn('snow', alert)

    def test_missing_weather_has_no_alert(self):
        self.assertIsNone(power.weather_alert({}))


class HostileEnvironmentTests(unittest.TestCase):
    def test_flags_a_true_road_game_at_a_ranked_venue(self):
        note = power.hostile_environment_note('LSU', neutral=False)
        self.assertIsNotNone(note)
        self.assertIn('Tiger Stadium', note)
        self.assertIn('#1', note)

    def test_note_is_terse_with_just_the_rank_and_venue(self):
        note = power.hostile_environment_note('Alabama', neutral=False)
        self.assertEqual(note, 'Road game at Bryant-Denny Stadium — hostile environment #6')

    def test_neutral_site_is_never_flagged(self):
        self.assertIsNone(power.hostile_environment_note('LSU', neutral=True))

    def test_unranked_venue_is_not_flagged(self):
        self.assertIsNone(power.hostile_environment_note('Kent State', neutral=False))

    def test_matching_is_case_and_punctuation_insensitive(self):
        self.assertIsNotNone(power.hostile_environment_note('texas a&m', neutral=False))


class PooledFcsTests(unittest.TestCase):
    """Every FCS opponent shares one rating; see power.pooled for why."""

    # Two FBS teams beat three different FCS schools badly, then host one of
    # them again. Individually each FCS team has one result and ridge shrinkage
    # rates it far too generously; pooled, they carry the weight of all four.
    EVENTS = [played('h1', -6, 'P', 'X', 49, 3), played('h2', -6, 'Q', 'Y', 45, 7),
              played('h3', -3, 'P', 'Z', 52, 0), played('h4', -3, 'Q', 'X', 38, 10),
              played('h5', 1, 'P', 'Q', 24, 21),
              played('up', 6, 'P', 'Z', 0, 0, completed=False, home_combined=1)]
    CBS = {'teamp': 1, 'teamq': 2}

    def build(self, **payload):
        base = {'events': self.EVENTS, 'cbs': self.CBS,
                'top50': [{'id': 'P', 'rank': 1}, {'id': 'Q', 'rank': 2}]}
        base.update(payload)
        return power.build(base, date(2026, 9, 5))

    def test_the_pooled_entity_carries_every_fcs_game(self):
        result = self.build()
        self.assertEqual(result['fcs_pooled']['games'], 4)
        self.assertIn('pooled rating', result['status'])

    def test_a_game_against_an_fcs_team_still_gets_a_projection(self):
        # Regression: ratings are keyed by pooled id, so looking them up by the
        # real team id silently skipped projections for exactly these games.
        game = self.build()['games']['up']
        self.assertEqual(game['lean_source'], 'model')
        self.assertIn('fair_home_spread', game)
        self.assertEqual(game['pooled_fcs'], ['away'])

    def test_an_fcs_opponent_projects_worse_than_an_fbs_one(self):
        fcs = self.build()['games']['up']['fair_home_spread']
        swapped = [e for e in self.EVENTS if e['id'] != 'up']
        swapped.append(played('up', 6, 'P', 'Q', 0, 0, completed=False, home_combined=1, away_combined=2))
        fbs = power.build({'events': swapped, 'cbs': self.CBS,
                           'top50': [{'id': 'P', 'rank': 1}, {'id': 'Q', 'rank': 2}]},
                          date(2026, 9, 5))['games']['up']['fair_home_spread']
        self.assertLess(fcs, fbs, 'the FCS visitor must be a bigger underdog than a rated FBS one')

    def test_per_team_fields_stay_keyed_to_the_real_team(self):
        game = self.build()['games']['up']
        for key in ('home_ats', 'away_ats', 'home_notes', 'away_notes'):
            self.assertIn(key, game)
        self.assertTrue(any('Last result' in n for n in game['away_notes']),
                        'the FCS visitor keeps its own recent result')


class BuildTests(unittest.TestCase):
    def test_ratings_and_projection_for_a_scheduled_game(self):
        events = [
            played('g1', -3, 'P', 'R', 30, 10, spread=-14, home_combined=1),
            played('g2', -3, 'Q', 'S', 28, 14, spread=-10, home_combined=2),
            played('g3', 1, 'S', 'P', 17, 20, spread=3, away_combined=1),
            played('g4', 1, 'Q', 'R', 35, 7, spread=-9, home_combined=2),
            played('g5', 5, 'P', 'Q', 0, 0, spread=-3, total=55, completed=False, home_combined=1, away_combined=2),
        ]
        payload = {'events': events, 'top50': [{'id': 'P', 'rank': 1}, {'id': 'Q', 'rank': 2}]}
        result = power.build(payload, date(2026, 9, 5))
        self.assertIn('Fit on 4 completed FBS games', result['status'])
        ids = {r['id']: r for r in result['ratings']}
        self.assertEqual(set(ids), {'P', 'Q'})
        self.assertEqual({ids['P']['games'], ids['Q']['games']}, {2})
        self.assertEqual({r['power_rank'] for r in result['ratings']}, {1, 2})
        game = result['games']['g5']
        self.assertIn('fair_home_spread', game)
        self.assertIsInstance(game['home_edge_points'], float)
        self.assertAlmostEqual(game['total_edge_points'], game['home_points']+game['away_points']-55, places=1)

    def test_thin_history_skips_projection_but_keeps_notes(self):
        events = [played('g1', -3, 'P', 'R', 30, 10, spread=-14, home_combined=1),
                  played('g2', 5, 'P', 'Q', 0, 0, spread=-3, completed=False, home_combined=1)]
        payload = {'events': events, 'top50': [{'id': 'P', 'rank': 1}]}
        result = power.build(payload, date(2026, 9, 5))
        game = result['games']['g2']
        self.assertNotIn('fair_home_spread', game)
        self.assertIn('home_notes', game)

    def test_no_history_does_not_manufacture_a_market_or_poll_pick(self):
        for spread in (None, -3, 14):
            events = [played('g1', 5, 'P', 'Q', 0, 0, completed=False, spread=spread)]
            game = power.build({'events': events, 'top50': [{'id':'P','rank':1}]}, date(2026,9,5))['games']['g1']
            self.assertEqual(game['lean_source'], 'unavailable')
            self.assertIsNone(game['lean_side'])
            self.assertNotIn('lean_home_spread', game)

    def test_market_changes_ats_side_but_not_model_prediction(self):
        prior = [played('p',1,'P','R',35,10), played('q',1,'Q','S',28,7)]
        projections=[]
        for spread in (-30, 30):
            event=played('g',8,'P','Q',0,0,completed=False,spread=spread)
            projections.append(power.build({'events':prior+[event],'top50':[]},date(2026,9,5))['games']['g'])
        self.assertEqual(projections[0]['lean_home_spread'],projections[1]['lean_home_spread'])
        self.assertEqual([p['lean_side'] for p in projections],['Away','Home'])
        self.assertEqual(projections[0]['confidence'],'Low')

    def test_freezing_precipitation_and_indoor_suppression(self):
        e={'weather':{'weather_code':66,'wind_speed_10m':0}}
        self.assertIn('sleet', power.weather_alert(e))
        e['venue']={'indoor':True}
        self.assertIsNone(power.weather_alert(e))

    def test_hostile_venue_and_severe_weather_flow_through_to_the_game_entry(self):
        game = played('g1', 5, 'H', 'A', 0, 0, completed=False)
        game['home'], game['away'] = 'LSU', 'Alabama'
        game['weather'] = {'wind_speed_10m': 18, 'precipitation': 0}
        result = power.build({'events': [game], 'top50': []}, date(2026, 9, 5))
        entry = result['games']['g1']
        self.assertTrue(any('Tiger Stadium' in n for n in entry['away_notes']))
        self.assertIn('wind 18 mph', entry['weather_alert'])


class HistoryTests(unittest.TestCase):
    def test_trend_reflects_movement_since_the_week_began(self):
        weeks = [{'type': 2, 'number': 1, 'label': 'Week 1', 'start': '2026-08-31T07:00Z', 'end': '2026-09-06T07:00Z'},
                 {'type': 2, 'number': 2, 'label': 'Week 2', 'start': '2026-09-07T07:00Z', 'end': '2026-09-13T07:00Z'}]
        events = [played('g1', 1, 'P', 'R', 45, 3, home_combined=1),
                  played('g1b', 2, 'P', 'U', 30, 10, home_combined=1),
                  played('g2', 1, 'Q', 'S', 20, 17, home_combined=2),
                  played('g2b', 2, 'Q', 'V', 24, 21, home_combined=2),
                  played('g3', 8, 'Q', 'P', 50, 0, home_combined=2, away_combined=1)]
        payload = {'events': events, 'top50': [{'id': 'P', 'rank': 1}, {'id': 'Q', 'rank': 2}], 'weeks': weeks}
        result = power.build(payload, date(2026, 9, 9))
        self.assertEqual(result['trend_since'], 'Week 2')
        self.assertEqual(result['history_weeks_tracked'], 1)
        by_id = {r['id']: r for r in result['ratings']}
        self.assertEqual(by_id['Q']['power_rank'], 1)
        self.assertEqual(by_id['P']['power_rank'], 2)
        self.assertEqual(by_id['Q']['trend'], 1)
        self.assertEqual(by_id['P']['trend'], -1)

    def test_no_history_before_any_week_has_completed_games(self):
        weeks = [{'type': 2, 'number': 1, 'label': 'Week 1', 'start': '2026-09-07T07:00Z', 'end': '2026-09-13T07:00Z'}]
        events = [played('g1', 8, 'P', 'Q', 0, 0, completed=False, home_combined=1, away_combined=2)]
        result = power.build({'events': events, 'top50': [{'id': 'P', 'rank': 1}], 'weeks': weeks}, date(2026, 9, 9))
        self.assertEqual(result['history_weeks_tracked'], 0)
        self.assertIsNone(result['trend_since'])


if __name__ == '__main__':
    unittest.main()
