import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
import dashboard
from storage import Store


WEEK1 = {'type': 2, 'number': 1, 'label': 'Week 1', 'start': '2026-08-31T07:00Z', 'end': '2026-09-06T07:00Z'}
WEEK2 = {'type': 2, 'number': 2, 'label': 'Week 2', 'start': '2026-09-07T07:00Z', 'end': '2026-09-13T07:00Z'}


class PollHistoryTests(unittest.TestCase):
    def test_first_snapshot_has_no_trend_yet(self):
        with tempfile.TemporaryDirectory() as folder:
            old_data, dashboard.DATA = dashboard.DATA, Path(folder)
            try:
                payload = {'season': 2026, 'weeks': [WEEK1], 'top50': [{'id': 'A', 'rank': 1}, {'id': 'B', 'rank': 2}]}
                trend, weeks_tracked = dashboard.snapshot_and_trend(payload, date(2026, 9, 1))
                self.assertEqual(trend, {})
                self.assertEqual(weeks_tracked, 1)
                self.assertTrue((Path(folder)/'rank_history.json').exists())
            finally:
                dashboard.DATA = old_data

    def test_trend_compares_to_the_prior_recorded_week(self):
        with tempfile.TemporaryDirectory() as folder:
            old_data, dashboard.DATA = dashboard.DATA, Path(folder)
            try:
                week1_payload = {'season': 2026, 'weeks': [WEEK1, WEEK2], 'top50': [{'id': 'A', 'rank': 1}, {'id': 'B', 'rank': 2}]}
                dashboard.snapshot_and_trend(week1_payload, date(2026, 9, 1))
                week2_payload = {'season': 2026, 'weeks': [WEEK1, WEEK2], 'top50': [{'id': 'B', 'rank': 1}, {'id': 'A', 'rank': 2}]}
                trend, weeks_tracked = dashboard.snapshot_and_trend(week2_payload, date(2026, 9, 8))
                self.assertEqual(weeks_tracked, 2)
                self.assertEqual(trend, {'B': 1, 'A': -1})
            finally:
                dashboard.DATA = old_data

    def test_a_new_team_in_the_poll_is_marked_new(self):
        with tempfile.TemporaryDirectory() as folder:
            old_data, dashboard.DATA = dashboard.DATA, Path(folder)
            try:
                dashboard.snapshot_and_trend({'season': 2026, 'weeks': [WEEK1, WEEK2], 'top50': [{'id': 'A', 'rank': 1}]}, date(2026, 9, 1))
                trend, _ = dashboard.snapshot_and_trend({'season': 2026, 'weeks': [WEEK1, WEEK2], 'top50': [{'id': 'A', 'rank': 1}, {'id': 'C', 'rank': 2}]}, date(2026, 9, 8))
                self.assertEqual(trend, {'A': 0, 'C': 'new'})
            finally:
                dashboard.DATA = old_data


class DashboardTests(unittest.TestCase):
    def test_http_save_reload_duplicate_and_favorite_toggle(self):
        with tempfile.TemporaryDirectory() as folder:
            old_data, old_state = dashboard.DATA, dashboard.STATE
            dashboard.DATA = Path(folder)
            dashboard.STATE = {'data': {'events': []}, 'error':'', 'refreshing':False,
                               'data_revision': 0, 'picks_revision': 0}
            server = dashboard.ThreadingHTTPServer(('127.0.0.1',0),dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}/api/'
            def call(path, data=None, token=dashboard.TOKEN):
                req = urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'X-Tracker-Token':token,'Content-Type':'application/json'})
                with urllib.request.urlopen(req) as r:
                    return r.read().decode()
            try:
                body=dict(game_date='2026-09-12',home='Test Home',away='Test Away',side='Away',spread=7.5,odds=-110,stake=1,home_score='',away_score='',notes='Test only')
                self.assertTrue(json.loads(call('save',body))['ok'])
                rows=json.loads(call('state'))['picks']
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['result'],'Pending')
                self.assertEqual(rows[0]['favorite'],0)
                with self.assertRaises(urllib.error.HTTPError):
                    call('save',body)
                body.update(id=rows[0]['id'],home_score=27,away_score=20)
                call('save',body)
                saved=json.loads(call('state'))['picks'][0]
                self.assertEqual(saved['result'],'Win')
                self.assertEqual(saved['spread'],7.5)
                self.assertTrue(json.loads(call('favorite',{'id':saved['id'],'favorite':True}))['ok'])
                self.assertEqual(json.loads(call('state'))['picks'][0]['favorite'],1)
                call('favorite',{'id':saved['id'],'favorite':False})
                self.assertEqual(json.loads(call('state'))['picks'][0]['favorite'],0)
                with self.assertRaises(urllib.error.HTTPError):
                    call('favorite',{'id':999999,'favorite':True})
                with self.assertRaises(urllib.error.HTTPError):
                    call('state',token='wrong')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                dashboard.DATA, dashboard.STATE = old_data, old_state


class ClosingLineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old_data = dashboard.DATA
        dashboard.DATA = Path(self.folder.name)

    def tearDown(self):
        dashboard.DATA = self.old_data
        self.folder.cleanup()

    def test_a_completed_game_gets_back_the_line_captured_before_kickoff(self):
        store = Store(dashboard.DATA/'picks.sqlite3')
        store.capture_lines([dict(id='g1', completed=False, home_spread=-6.5, total=48.0, home_odds=-110,
                                  away_odds=-110, kickoff='2026-09-06T20:00:00+00:00', market_source='ESPN')],
                            '2026-09-05T12:00:00-04:00')
        store.db.close()
        payload = {'events': [dict(id='g1', completed=True, home_spread=None, home_score=24, away_score=17),
                              dict(id='g2', completed=True, home_spread=None, home_score=10, away_score=3)]}
        dashboard.record_lines(payload, capture=False)
        self.assertEqual(payload['events'][0]['home_spread'], -6.5)
        self.assertIsNone(payload['events'][1]['home_spread'], 'no capture, no invented line')
        self.assertEqual(payload['lines_captured_since'], '2026-09-05T12:00:00-04:00')

    def test_a_line_the_feed_still_carries_is_left_alone(self):
        payload = {'events': [dict(id='g1', completed=True, home_spread=-3.0)]}
        dashboard.record_lines(payload)
        self.assertEqual(payload['events'][0]['home_spread'], -3.0)


class WarmUpTests(unittest.TestCase):
    def test_saving_an_event_pick_before_the_season_loads_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            old_data, old_state = dashboard.DATA, dashboard.STATE
            dashboard.DATA = Path(folder)
            dashboard.STATE = {'data': {}, 'error': '', 'refreshing': True, 'data_revision': 0, 'picks_revision': 0}
            server = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                pick = dict(game_date='2026-09-12', home='A', away='B', side='Home', spread=-3, odds=-110,
                            stake=1, home_score='', away_score='', notes='', event_id='401')
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/save',
                                                 data=json.dumps(pick).encode(),
                                                 headers={'X-Tracker-Token': dashboard.TOKEN,
                                                          'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertIn('Still loading', json.loads(caught.exception.read())['error'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                dashboard.DATA, dashboard.STATE = old_data, old_state


class RevisionGatingTests(unittest.TestCase):
    """The season payload should move only when it actually changes."""

    # events survives the strip and is the bulk of a real payload; the four
    # server-only keys do not.
    BULK = {'events': [{'id': str(i), 'filler': 'x'*200} for i in range(200)],
            'season': 2026, 'top50': [{'id': 'A', 'rank': 1}]*50,
            'cbs': {'alabama': 1}, 'ap': {'A': 1}, 'coaches': {'A': 1},
            'history_events': [{'filler': 'x'*200} for _ in range(200)]}

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old_data, self.old_state = dashboard.DATA, dashboard.STATE
        dashboard.DATA = Path(self.folder.name)
        dashboard.STATE = {'data': dict(self.BULK), 'error': '', 'refreshing': False,
                           'data_revision': 4, 'picks_revision': 2}
        self.server = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}/api/'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        dashboard.DATA, dashboard.STATE = self.old_data, self.old_state
        self.folder.cleanup()

    def call(self, path, data=None):
        request = urllib.request.Request(self.base+path,
                                         data=json.dumps(data).encode() if data is not None else None,
                                         headers={'X-Tracker-Token': dashboard.TOKEN,
                                                  'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            return response.read().decode()

    def test_a_caller_with_no_copy_gets_the_season_data(self):
        body = json.loads(self.call('state'))
        self.assertIn('data', body)
        self.assertEqual(body['data_revision'], 4)
        self.assertEqual(body['picks_revision'], 2)

    def test_a_caller_already_holding_the_current_revision_gets_no_bulk(self):
        fresh = self.call('state')
        gated = self.call('state?since=4')
        self.assertNotIn('data', json.loads(gated))
        self.assertLess(len(gated), len(fresh)/10, 'the gated poll should be far smaller')

    def test_the_gated_poll_still_carries_everything_the_page_renders_from(self):
        body = json.loads(self.call('state?since=4'))
        for key in ('picks', 'all_summary', 'today', 'refreshing', 'error',
                    'data_revision', 'picks_revision'):
            self.assertIn(key, body)

    def test_a_stale_revision_gets_the_bulk_again(self):
        self.assertIn('data', json.loads(self.call('state?since=3')))
        self.assertIn('data', json.loads(self.call('state?since=notanumber')))

    def test_publishing_new_data_moves_the_revision_on(self):
        before = json.loads(self.call('state?since=4'))
        with dashboard.LOCK:
            dashboard.publish({'events': [], 'season': 2027})
        after = json.loads(self.call('state?since=4'))
        self.assertNotIn('data', before)
        self.assertIn('data', after, 'a stale caller must be resent the new data')
        self.assertEqual(after['data']['season'], 2027)
        self.assertEqual(after['data_revision'], 5)

    def test_server_only_keys_are_stripped_from_the_wire(self):
        data = json.loads(self.call('state'))['data']
        for key in dashboard.WIRE_OMIT:
            self.assertNotIn(key, data)
        self.assertEqual(data['history_events_count'], 200)
        self.assertEqual(data['season'], 2026, 'the rest of the payload must survive')
        self.assertEqual(len(data['top50']), 50)

    def test_stripping_the_wire_never_touches_the_published_data(self):
        # The real hazard: power.build reads cbs for the FBS pool, ap for the
        # blend and history_events for the fit. Losing any of them from
        # STATE['data'] would degrade the model with no error at all.
        self.call('state')
        self.call('state?since=0')
        for key in dashboard.WIRE_OMIT:
            if key in self.BULK:
                self.assertIn(key, dashboard.STATE['data'], f'{key} must survive in STATE')
        self.assertEqual(len(dashboard.STATE['data']['history_events']), 200)

    def test_the_market_snapshot_is_kept_in_the_database_but_not_shipped(self):
        pick = dict(game_date='2026-09-12', home='Test Home', away='Test Away', side='Away',
                    spread=7.5, odds=-110, stake=1, home_score='', away_score='', notes='Test only')
        self.call('save', pick)
        sent = json.loads(self.call('state?since=4'))['picks'][0]
        self.assertNotIn('market_snapshot', sent)
        self.assertIn('spread', sent, 'the rest of the pick must still be there')
        store = Store(Path(self.folder.name)/'picks.sqlite3')
        try:
            self.assertIn('market_snapshot', store.all()[0])
        finally:
            store.db.close()

    def test_saving_and_starring_a_pick_move_the_picks_revision(self):
        pick = dict(game_date='2026-09-12', home='Test Home', away='Test Away', side='Away',
                    spread=7.5, odds=-110, stake=1, home_score='', away_score='', notes='Test only')
        self.call('save', pick)
        saved = json.loads(self.call('state?since=4'))
        self.assertEqual(saved['picks_revision'], 3)
        self.call('favorite', {'id': saved['picks'][0]['id'], 'favorite': True})
        self.assertEqual(json.loads(self.call('state?since=4'))['picks_revision'], 4)


if __name__ == '__main__':
    unittest.main()
