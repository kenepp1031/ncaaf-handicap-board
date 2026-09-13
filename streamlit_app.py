"""Public, mobile-friendly companion for the NCAAF handicapping board.

Earlier versions of this file re-implemented the desktop dashboard as a
Streamlit-widget page (sidebar controls, st.metric, st.dataframe, ...). The
owner wants a pixel-identical copy of the real desktop page instead, so this
file now does something much simpler: it embeds the real markup/CSS/JS --
web_dashboard.html + app.css + web_app.js, a read-only copy of the desktop
app's dashboard.html/app.css/app.js -- inside a Streamlit page via
st.iframe(). The visual result is the desktop app, because it is literally
the same HTML/CSS/JS, just fed from a static JSON snapshot instead of a
live server.

This file intentionally contains almost no UI logic of its own: it loads
three text files and one JSON snapshot, inlines them into one HTML document,
and hands the whole thing to st.iframe(). It never touches
dashboard.py, app.js, app.css, or storage.py -- those keep serving the
desktop app unchanged. See export_web_snapshot.py and README_WEB.md for how
data/web_snapshot.json is produced and published.

Refresh the snapshot with `python export_web_snapshot.py` after using the
desktop app, then commit+push data/web_snapshot.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = APP_DIR / "data" / "web_snapshot.json"
CSS_PATH = APP_DIR / "app.css"
JS_PATH = APP_DIR / "web_app.js"
HTML_PATH = APP_DIR / "web_dashboard.html"

st.set_page_config(page_title="NCAAF Handicapping Board", page_icon="🏈", layout="wide")

if not SNAPSHOT_PATH.exists():
    st.error(
        "The published board snapshot (data/web_snapshot.json) is missing. "
        "Run the desktop app, then `python export_web_snapshot.py`, and "
        "commit + push the result -- see README_WEB.md."
    )
    st.stop()

try:
    snapshot_json = SNAPSHOT_PATH.read_text(encoding="utf-8")
    json.loads(snapshot_json)  # fail fast, with a clear message, on a corrupt file
except (OSError, json.JSONDecodeError) as error:
    st.error(f"Unable to load the published board: {error}")
    st.stop()

css = CSS_PATH.read_text(encoding="utf-8")
js = JS_PATH.read_text(encoding="utf-8")
html = HTML_PATH.read_text(encoding="utf-8")

# web_dashboard.html is written as a standalone page that expects a server at
# "/" (it links app.css and web_app.js by absolute path). st.iframe() renders
# into a sandboxed iframe with no such server, so pull out everything after
# that <link> tag -- the read-only-mode <style>
# block plus the header/nav/sections/footer markup -- and drop the trailing
# <script src="..."> tag; both the CSS and JS are inlined directly below
# instead, with no fetch/CORS involved.
_, _, body_and_style = html.partition('<link rel="stylesheet" href="/app.css">')
body_and_style = body_and_style.replace('<script src="/web_app.js" defer></script>', '')
body_and_style = body_and_style[: body_and_style.rfind('</html>')].strip()

page = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{css}</style>
</head><body>
{body_and_style}
<script>window.__SNAPSHOT__={snapshot_json};</script>
<script>{js}</script>
</body></html>"""

# height="content" measures and auto-sizes the iframe to the rendered page
# (no fixed-height guess, no wasted scroll-within-scroll space); st.iframe
# is the current, non-deprecated replacement for components.html() here.
st.iframe(page, height="content")
