import tempfile
import unittest
from pathlib import Path
import jscheck

FOLDER = Path(__file__).resolve().parent
PAGE = FOLDER/'dashboard.html'
APP_JS = FOLDER/'app.js'
# The exact shape that shipped broken: the false branch of a ternary inside a
# template expression opened a string it never closed, so the browser refused
# the entire script and the dashboard rendered nothing.
SHIPPED_BROKEN = "let card=(p,e)=>`<div>${p?line(e):'}<b>O/U ${half(e.total)}</b>${block(e)}${p?'':`<i>x</i>`}</div>`;"
SHIPPED_FIXED = "let card=(p,e)=>`<div>${p?line(e):''}<b>O/U ${half(e.total)}</b>${block(e)}${p?'':`<i>x</i>`}</div>`;"


class ScannerTests(unittest.TestCase):
    def test_it_catches_the_unterminated_string_that_broke_the_page(self):
        with self.assertRaises(jscheck.JsSyntaxError):
            jscheck.check(SHIPPED_BROKEN)

    def test_the_corrected_form_passes(self):
        self.assertTrue(jscheck.check(SHIPPED_FIXED))

    def test_nested_templates_and_expressions_are_balanced(self):
        self.assertTrue(jscheck.check('let a=`x${b?`y${c}z`:""}w`;const d={e:1};'))

    def test_an_unclosed_template_expression_is_reported(self):
        with self.assertRaises(jscheck.JsSyntaxError):
            jscheck.check('let a=`x${b;')

    def test_an_unclosed_template_literal_is_reported(self):
        with self.assertRaises(jscheck.JsSyntaxError):
            jscheck.check('let a=`x${b}y;')

    def test_a_regex_holding_quotes_and_braces_is_not_mistaken_for_code(self):
        self.assertTrue(jscheck.check("""const esc=s=>String(s).replace(/[&<>"']/g,c=>c);"""))

    def test_division_is_not_mistaken_for_a_regex(self):
        self.assertTrue(jscheck.check("const half=n=>(Math.round(n*2)/2).toFixed(1);const w=a/b/c;"))

    def test_comments_and_apostrophes_inside_them_are_ignored(self):
        self.assertTrue(jscheck.check("// it's fine\n/* also ' fine { */ let a=1;"))

    def test_unbalanced_braces_are_reported(self):
        with self.assertRaises(jscheck.JsSyntaxError):
            jscheck.check('function f(){ if(a){ return 1; }')

    def test_the_reported_line_number_points_at_the_problem(self):
        with self.assertRaises(jscheck.JsSyntaxError) as caught:
            jscheck.check("let a=1;\nlet b=2;\nlet c='oops;\n")
        self.assertIn('line 3', str(caught.exception))


class DashboardPageTests(unittest.TestCase):
    def test_the_shipped_page_and_every_script_it_loads_parse(self):
        # The bootstrap in the page plus app.js.
        self.assertGreaterEqual(jscheck.check_page(FOLDER), 2)

    def test_reintroducing_the_original_break_is_caught(self):
        source = APP_JS.read_text(encoding='utf-8')
        self.assertIn("${printing?marketLine(e):''}", source)
        broken = source.replace("${printing?marketLine(e):''}", "${printing?marketLine(e):'}", 1)
        with self.assertRaises(jscheck.JsSyntaxError):
            jscheck.check(broken, 'app.js')

    def test_a_broken_external_script_is_caught_through_the_page(self):
        with tempfile.TemporaryDirectory() as folder:
            here = Path(folder)
            (here/'page.html').write_text('<script>window.T="x";</script><script src="/broken.js"></script>',
                                          encoding='utf-8')
            (here/'broken.js').write_text("let a='unterminated;\n", encoding='utf-8')
            with self.assertRaises(jscheck.JsSyntaxError):
                jscheck.check_page(here, 'page.html')

    def test_a_page_whose_scripts_all_parse_reports_how_many_it_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            here = Path(folder)
            (here/'page.html').write_text('<script>window.T="x";</script><script src="/ok.js"></script>',
                                          encoding='utf-8')
            (here/'ok.js').write_text('const a = 1;\n', encoding='utf-8')
            self.assertEqual(jscheck.check_page(here, 'page.html'), 2)


if __name__ == '__main__':
    unittest.main()
