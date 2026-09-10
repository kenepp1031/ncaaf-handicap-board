"""Structural guards on the split front end.

None of the Python tests can prove the page *works*, but they can prove the
pieces still fit together. These cover the failure that has no other alarm:
the page loads, looks correct, and every control is dead.
"""
import re
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
PAGE = (FOLDER/'dashboard.html').read_text(encoding='utf-8')
APP_JS = (FOLDER/'app.js').read_text(encoding='utf-8')
APP_CSS = (FOLDER/'app.css').read_text(encoding='utf-8')


class PageWiringTests(unittest.TestCase):
    def test_the_page_loads_both_assets_from_the_served_routes(self):
        self.assertIn('<link rel="stylesheet" href="/app.css">', PAGE)
        self.assertRegex(PAGE, r'<script src="/app\.js"[^>]*>')

    def test_app_js_is_a_classic_deferred_script_not_a_module(self):
        # An ES module keeps its top-level functions off the global object, so
        # every inline onclick in the markup would silently stop resolving --
        # a page that renders perfectly and does nothing.
        tag = re.search(r'<script[^>]*src="/app\.js"[^>]*>', PAGE).group(0)
        self.assertIn('defer', tag)
        self.assertNotIn('type="module"', tag)

    def test_every_inline_handler_resolves_to_something_in_app_js(self):
        called = set(re.findall(r'\bon\w+="(\w+)\(', PAGE))
        self.assertTrue(called, 'expected the markup to carry inline handlers')
        builtin = {'window'}
        for name in called - builtin:
            self.assertRegex(APP_JS, r'\b(?:function\s+%s\b|(?:const|let|var)\s+%s\s*=)' % (name, name),
                             f'inline handler {name}() is not declared in app.js')

    def test_the_token_placeholder_lives_only_in_the_page(self):
        # app.js is served as a static file, so a placeholder there would never
        # be substituted and would ship the literal string to the browser.
        self.assertEqual(PAGE.count('__TOKEN__'), 1)
        self.assertNotIn('__TOKEN__', APP_JS)
        self.assertNotIn('__TOKEN__', APP_CSS)
        self.assertIn('window.CFB_TOKEN', PAGE)
        self.assertIn('window.CFB_TOKEN', APP_JS)

    def test_no_style_or_inline_app_code_is_left_behind_in_the_page(self):
        # A leftover <style> after the <link> would reorder equal-specificity
        # rules; leftover app code would drift from app.js.
        self.assertNotIn('<style>', PAGE)
        self.assertNotIn('function render(', PAGE)

    def test_the_print_rules_moved_across_with_the_stylesheet(self):
        self.assertIn('@media print', APP_CSS)
        self.assertIn('#view-print', APP_CSS)

    def test_the_ids_app_js_reaches_for_exist_in_the_markup(self):
        wanted = set(re.findall(r"\$\('([\w-]+)'\)", APP_JS))
        self.assertTrue(wanted)
        present = set(re.findall(r'id="([\w-]+)"', PAGE))
        self.assertEqual(sorted(wanted - present), [],
                         'app.js looks up element ids that the markup does not define')


class BehaviourContractTests(unittest.TestCase):
    def body(self, name):
        match = re.search(r'function %s\([^)]*\)\{(.*?)\}\n' % name, APP_JS, re.S)
        self.assertIsNotNone(match, f'{name} not found')
        return match.group(1)

    def test_switching_weeks_never_waits_on_a_network_sync(self):
        # Each click used to await a full refresh: CBS, ESPN, up to twenty
        # DraftKings pages. The week's games are already on the page.
        for name in ('switchWeek', 'currentWeek'):
            self.assertNotIn('refresh(', self.body(name))
            self.assertIn('topUp()', self.body(name))

    def test_a_403_goes_through_ping_gated_recovery(self):
        self.assertIn('recoverToken()', APP_JS)
        self.assertIn("fetch('/api/ping'", APP_JS)
        self.assertIn('sessionStorage', APP_JS, 'the reload must be rate-limited so it cannot loop')

    def test_matchup_cards_are_updated_in_place_not_rebuilt(self):
        # Rebuilding #games with innerHTML closed every open panel and reset
        # the list's scroll on each refresh or saved pick.
        self.assertNotIn("$('games').innerHTML=games.map", APP_JS)
        self.assertIn('renderGames(games)', APP_JS)
        self.assertIn('dataset.key=e.id', APP_JS)

    def test_the_poll_asks_only_for_data_it_lacks(self):
        self.assertIn("api('state?since='", APP_JS)
        self.assertNotIn('JSON.stringify(next)', APP_JS)


if __name__ == '__main__':
    unittest.main()
