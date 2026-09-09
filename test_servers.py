import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import dashboard
import servers


class Foreign(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({'app': 'some-other-program'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class serving:
    """Run a handler on a loopback port for the duration of the block."""

    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_port

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        return False


class RegistryTests(unittest.TestCase):
    def test_register_then_deregister_leaves_no_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            servers.register(data, 8768, 'secret')
            entry = servers.read(data)['8768']
            self.assertEqual(entry['token'], 'secret')
            self.assertIn('started_at', entry)
            servers.deregister(data, 8768)
            self.assertEqual(servers.read(data), {})

    def test_registering_drops_entries_whose_server_is_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            servers.register(data, 9, 'stale-entry-for-a-dead-server')
            servers.register(data, 8768, 'live')
            self.assertEqual(list(servers.read(data)), ['8768'])

    def test_a_missing_or_damaged_registry_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            self.assertEqual(servers.read(data), {})
            (data/servers.REGISTRY_NAME).write_text('not json', encoding='utf-8')
            self.assertEqual(servers.read(data), {})

    def test_candidates_cover_legacy_ports_without_repeats(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            servers.register(data, 8768, 'live')
            found = servers.candidates(data, (8790,))
            self.assertEqual(len(found), len(set(found)))
            self.assertEqual(found[0], 8768)
            self.assertIn(8790, found)
            for port in servers.LEGACY_PORTS:
                self.assertIn(port, found)


class PingTests(unittest.TestCase):
    def test_a_closed_port_answers_nothing(self):
        self.assertIsNone(servers.ping(9, timeout=0.5))

    def test_another_program_on_the_port_is_not_mistaken_for_the_tracker(self):
        with serving(Foreign) as port:
            self.assertIsNone(servers.ping(port))

    def test_a_running_tracker_identifies_itself(self):
        with serving(dashboard.Handler) as port:
            self.assertEqual(servers.ping(port)['app'], servers.APP)
            self.assertEqual(servers.ping(port)['port'], port)


class FindAndStopTests(unittest.TestCase):
    def test_find_running_returns_the_live_tracker_port(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with serving(dashboard.Handler) as port:
                servers.register(data, port, dashboard.TOKEN)
                self.assertEqual(servers.find_running(data, legacy=False), port)

    def test_stop_all_closes_a_registered_tracker_and_clears_its_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port
            try:
                servers.register(data, port, dashboard.TOKEN)
                stopped, skipped = servers.stop_all(data, (port,), report=lambda *a: None, legacy=False)
                self.assertIn(port, stopped)
                self.assertEqual(skipped, [])
                self.assertNotIn(str(port), servers.read(data))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_stop_all_leaves_another_programs_port_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with serving(Foreign) as port:
                stopped, skipped = servers.stop_all(data, (port,), report=lambda *a: None, legacy=False)
                self.assertEqual(stopped, [])
                self.assertIn(port, skipped)
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ping', timeout=2) as response:
                    self.assertEqual(json.loads(response.read())['app'], 'some-other-program')


if __name__ == '__main__':
    unittest.main()
