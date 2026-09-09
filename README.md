# College Football Picks

Run `Start Weekly Picks.cmd` or the NCAAF desktop shortcut. The local browser app uses port 8768. Reopening it reuses the running server, whichever port that server is on: each one registers itself in `data/servers.json`, so a launch finds it instead of starting a second copy. Use `Stop Weekly Picks.cmd` (or `python dashboard.py --stop`) before restarting after Python source changes; it closes every tracker instance and leaves ports belonging to other programs alone.

## Weekly picks

This Week combines the weekly matchup layout and one-click Board controls. Select a side to save its available spread and price, use the star to mark an actual wager, and Edit for stakes, notes, corrections or manually supplied odds. Clicking the already saved side does not overwrite its original line. Missing prices require manual entry. Market refreshes preserve saved picks, and completed scores settle them automatically.

The displayed schedule includes games involving the combined Top 50 (CBS, AP and Coaches). The combined rankings list lives in Power Ranking. Week tabs follow ESPN's season calendar.

## Model and rankings

Opponent-adjusted offense and defense are fitted to scoring results from the current and previous season with a 180-day recency half-life. Games on or after the fit date are excluded. Rankings and grades compare rated FBS teams from the full CBS membership list; FCS opponents receive no FBS rank or grade. The combined poll rank beside a school is labeled separately. Game counts include the prior season. The overall Top 50 leaderboard retains its poll blend; individual game projections use the scoring model.

The ATS lean compares the independent model spread, adjusted for rest/lookahead/letdown notes, with the observed market. Stadium reputation is context only; home advantage is already in the scoring model. No odds or insufficient team data means no ATS lean. An edge below one point also produces no lean.

## School spending

Power Ranking lists estimated 2026 roster cost (what a program pays its players) and FY2025 athletic department expenses for every school on nil-ncaa.com, cached weekly in `data/nil.json`. Each matchup's Model detail shows both sides' figures.

Roster cost also feeds a prior on the projected margin, fitted fresh each refresh by regressing team rating on log payroll — the points-per-dollar slope is measured, never assumed, so a weak relationship produces a weak adjustment. It applies only while a team has under eight games this season, fades linearly to zero, moves the margin without touching the projected total, and is skipped unless both schools report a roster cost. Set `MAX_WEIGHT = 0` in `nil.py` to disable it.

Athletic department budgets are reference only and never move a spread. Fitted across FBS and FCS together, that line puts a Power 4 host about three points above an FCS visitor where the ratings say eleven and the market says fifty-six; shrinking toward it made those projections worse. Because the prior works by pulling a team toward the fitted line, it favours whichever side sits furthest below its own payroll, which is not always the bigger spender.

Confidence is a qualitative Low/Moderate label, not a calibrated cover probability. Moderate requires at least four current-season games for both sides and an absolute edge of at least three points. No High label is issued. The model has not demonstrated profitable out-of-sample ATS performance. Rosters, injuries, returning production and play-level efficiency are not modeled. Reconstructed ranking trends use current poll context, not historical poll knowledge.

## Weather and print

Open-Meteo supplies hourly city forecasts from kickoff through about three hours afterward, up to 16 days out. Outdoor-game banners flag wind/gusts at least 15 mph, rain, snow, and freezing/mixed precipitation (sleet risk). These are in-app alerts, refreshed on launch, week selection and every 15 minutes while the page is open. Indoor venues suppress field-weather alerts. Missing or old forecasts are labeled.

Print shows offense/defense ranks and letters beside the teams, with spread, total, lean and confidence in the middle. Context includes recent results, venue, weather and selected verified rivalries. Pick controls and My Pick text are omitted. Optional pick highlighting defaults off. Color and ink-saving modes are available; printing uses landscape pages. Displayed spreads/projections round to half points with one decimal; stored lines and calculations keep precision.

## Data and maintenance

Power Ranking also carries a Data health panel: feed counts, poll dates, the fitted spending slope, and which of this week's games have no market spread.

`data/picks.sqlite3` stores picks and captured market snapshots. `data/live.json` stores feeds. `nil.json` caches school spending and `servers.json` tracks running instances. `history-YYYY.json` caches prior-season scores, `locations.json` caches city coordinates, and `rank_history.json` preserves observed poll snapshots. Missing provider odds remain missing; no betting lines are invented. ATS history needs historical closing spreads and may be unavailable even when scores exist.

`weekly.py` is the alternate Tkinter tracker. `handicap.py`, `rankings.py`, `make_demo.py` and CSV templates are retained command-line/legacy workflows; they are not the desktop browser entry point.

Run `python -m unittest discover` for regression checks. `test_jscheck.py` also proves the dashboard's inline script still parses — an unterminated string there stops the browser reading the whole `<script>` and the page renders nothing, which no other test would catch. It is a structural check, so still load the page once after editing the script. See `CHANGELOG-2026-09-09.md` for the detailed changes and audit.
