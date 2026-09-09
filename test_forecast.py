import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from feeds import add_weather
from power import weather_alert


class ForecastTests(unittest.TestCase):
    def test_kickoff_timezone_window_and_missing_forecast(self):
        hourly={'time':['2026-09-12T17:00','2026-09-12T18:00','2026-09-12T19:00','2026-09-12T20:00','2026-09-12T21:00'],
                'temperature_2m':[70]*5,'weather_code':[0,0,66,0,0],
                'wind_speed_10m':[50,5,16,8,4], 'wind_gusts_10m':[60,9,20,10,5],
                'precipitation':[0,.01,.01,0,0],'rain':[0,.01,0,0,0],'snowfall':[0]*5}
        base={'game_date':'2026-09-12','kickoff':'2026-09-12T14:00:00-04:00',
              'venue':{'address':{'city':'Test','state':'TX','country':'USA'}}}
        events=[dict(base),dict(base,kickoff='2026-10-12T14:00:00-04:00'),dict(base,venue=dict(base['venue'],indoor=True))]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'locations.json').write_text(json.dumps({'Test|TX|USA':{'latitude':30,'longitude':-97}}))
            with patch('feeds.fetch',return_value=json.dumps({'hourly':hourly})) as fetch:
                add_weather(events,folder,'2026-09-12','2026-09-12')
            self.assertIn('hourly=',fetch.call_args.args[0])
            self.assertNotIn('current=',fetch.call_args.args[0])
        self.assertEqual(events[0]['weather']['wind_speed_10m'],16)
        self.assertEqual(events[0]['weather']['time'],'2026-09-12T18:00')
        self.assertIn('sleet',weather_alert(events[0]))
        self.assertIsNone(events[1]['weather'])
        self.assertIsNone(events[2]['weather'])

    def test_snow_without_wind_measurement_and_light_rain(self):
        self.assertIn('snow',weather_alert({'weather':{'weather_code':75}}))
        self.assertIn('rain',weather_alert({'weather':{'rain':.001}}))
