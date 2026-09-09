import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
import dashboard


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
            dashboard.STATE = {'data': {'events': []}, 'error':'', 'refreshing':False}
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


if __name__ == '__main__':
    unittest.main()
