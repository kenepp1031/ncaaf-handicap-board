# Publish the NCAAF board for free

This project contains a phone-friendly web edition, `streamlit_app.py`, that
is a **pixel-identical embed of the real desktop dashboard** — not a
Streamlit-widget reimplementation. It works by inlining a read-only copy of
the desktop page's own markup/CSS/JS (`web_dashboard.html` + `app.css` +
`web_app.js`) into one HTML document and rendering it with `st.iframe()`, fed
by a static JSON snapshot instead of a live server. It never touches
`dashboard.py`, `app.js`, `app.css`, `dashboard.html`, or `storage.py`, and it
has no editing capability — saving/editing/starring picks still only happens
in the desktop app.

## How the embed works

- `export_web_snapshot.py` reads `data/live.json` (+ the picks database, poll
  history, and refresh() caches) and writes `data/web_snapshot.json` in
  **exactly** the shape `dashboard.py`'s `/api/state` sends to `app.js` —
  `{"data": ..., "picks": [...], "today": ...}` — by importing and reusing
  `dashboard.wire_data()` directly (read-only import; `dashboard.py`'s server
  never starts unless its own `__main__` runs). No reshaping/renaming, so
  there's nothing to keep in sync between the export and the renderer.
- `web_app.js` is a separate copy of `app.js` (the original is untouched) with
  every live-backend code path removed or turned into a no-op: no `/api/*`
  polling, no token/reload-recovery, and `quickPick()`, `toggleFavorite()`,
  `refresh()`, and the pick form's submit handler all just show an inline
  "Editing happens in the desktop app" notice instead of calling a server.
  Every rendering function (`matchupCard`, `renderGames`, `renderTopPicks`,
  `renderPower`, `renderSpending`, `renderTalent`, `renderHealth`,
  `renderPrint`, week-tab switching, theme toggle, filter tabs) is byte-for-
  byte identical to `app.js`, so the visuals match exactly.
- `web_dashboard.html` is a copy of `dashboard.html` referencing `web_app.js`
  instead of `app.js`, with a small inline `<style>` block hiding the
  write-only controls (`#editor`, `.spread-pair` quick-pick buttons,
  `.pick-actions` Edit/★ BET buttons) as a second, purely-cosmetic layer on
  top of the JS no-ops above.
- `streamlit_app.py` is a thin loader: it reads those three files plus
  `data/web_snapshot.json`, inlines the CSS into a `<style>` tag, assigns the
  snapshot to `window.__SNAPSHOT__` in an inline `<script>`, inlines
  `web_app.js` in another, and hands the combined HTML string to
  `st.iframe(page, height="content")`. It contains almost no UI logic of its
  own.

## Publish it

1. Run the desktop app at least once this session (`Start Weekly Picks.cmd`)
   so `data/live.json` is fresh.
2. Generate the snapshot:

   ```
   python export_web_snapshot.py
   ```

   This writes `data/web_snapshot.json`.
3. Create a public GitHub repository and upload this folder, including
   `streamlit_app.py`, `web_app.js`, `web_dashboard.html`, `app.css`,
   `requirements.txt`, `export_web_snapshot.py`, and `data/web_snapshot.json`.
   Do **not** upload `data/live.json`, `data/nil.json`, `data/talent.json`,
   `data/penalties.json`, `data/locations.json`, or `data/servers.json` —
   those stay gitignored, refetchable, and unnecessary for the public view.
4. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and sign in.
5. Select **Create app**, select the GitHub repository, and choose
   `streamlit_app.py` as the entry point.
6. Choose an app address and deploy. Save the resulting `https://…streamlit.app`
   address in your phone browser.

Streamlit Community Cloud is free and runs the published app independently of
your PC. The app is public if the GitHub repository/app is public.

## Keeping it current

The cloud app intentionally uses the snapshot committed to GitHub. To refresh:

1. Use the desktop app as usual (open it, let it sync) so `data/live.json`
   and the picks database are current.
2. Run `python export_web_snapshot.py` again.
3. Commit and push the updated `data/web_snapshot.json`.

Streamlit Cloud redeploys automatically on push. This prevents a public
website from needing access to your home computer.

## Limitations of the web edition

- No editing: saving, editing, or starring picks only works in the desktop
  app. The web page is read-only — every write control is hidden, and any JS
  path that could still reach one shows an inline notice instead of failing
  silently.
- The snapshot is only as fresh as your last `export_web_snapshot.py` run —
  there's no live polling like the desktop app's 5-second refresh.
- The snapshot keeps the full events list needed for accurate "previous game"
  lookups (any game involving a team that plays a Top-50 opponent this week),
  not just this week's Top-50 games, so it's larger than a purely filtered
  export but still a small fraction of the gitignored `live.json`.
- Poll-trend movement (the "Poll trend" column) only shows once
  `data/rank_history.json` has more than one archived week for the current
  week — that file is only written by the desktop app while it runs, so a
  brand-new season/week can show blank trend until the desktop app has run
  at least twice.
- The closing-line archive (`data/picks.sqlite3`'s `market_lines` table) is
  read, not written, by `export_web_snapshot.py` — it restores completed
  games' pre-kickoff spread for accurate ATS records, but only lines the
  desktop app already captured while running are available; it never adds
  new capture rows itself.
