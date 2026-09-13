# College Football Picks

Run `Start Weekly Picks.cmd` or the NCAAF desktop shortcut. The local browser app uses port 8768. Reopening it reuses the running server, whichever port that server is on: each one registers itself in `data/servers.json`, so a launch finds it instead of starting a second copy. Use `Stop Weekly Picks.cmd` (or `python dashboard.py --stop`) before restarting after Python source changes; it closes every tracker instance and leaves ports belonging to other programs alone.

The page opens as soon as the server binds, then shows "Refreshing…" while the cached season and fresh feeds load. It polls every five seconds but receives the season data only when it has changed — an idle poll is about 6 KB — and redraws only when something actually moved, so open panels stay open. Switching weeks renders instantly from data already on the page; each week gets one background top-up for odds and weather, and the Refresh button forces a pull. If the server restarts while the page is open, the page reloads itself once to pick up the new session.

## Weekly picks

This Week combines the weekly matchup layout and one-click Board controls. Select a side to save its available spread and price, use the star to mark an actual wager, and Edit for stakes, notes, corrections or manually supplied odds. Clicking the already saved side does not overwrite its original line. Missing prices require manual entry. Market refreshes preserve saved picks, and completed scores settle them automatically.

The displayed schedule includes games involving the combined Top 50 (CBS, AP and Coaches). The combined rankings list lives in Power Ranking. Week tabs follow ESPN's season calendar.

## Model and rankings

Opponent-adjusted offense and defense are fitted to scoring results from the current and previous season with a 365-day recency half-life and light ridge regularization (1.5), both chosen by walk-forward testing: each 2025 game predicted only from earlier games and scored against its final margin, then confirmed on 2026 games the choice never saw. Against the previous settings (ridge 8, 180-day half-life) mean margin error fell from 13.1 to 12.3 points on 2025 and from 18.7 to 17.2 on the 2026 holdout, with the median improving too. Games on or after the fit date are excluded. Rankings and grades compare rated FBS teams from the full CBS membership list; FCS opponents receive no FBS rank or grade. The combined poll rank beside a school is labeled separately. Game counts include the prior season. The overall Top 50 leaderboard retains its poll blend; individual game projections use the scoring model.

Every FCS opponent shares one pooled rating rather than carrying its own. An FCS school appears in one or two FBS results a season, and ridge shrinkage pulls a coefficient built from that little evidence most of the way back to the mean, so the model rated them far too generously — it projected Miami by 14 where the market said 57. The pooled entity is backed by every FCS-vs-FBS game, which estimates the one thing the data supports: how much weaker the division is. Across 147 games with a market line this cut mean error against the market from 12.1 to 7.5 points, and games off by more than 20 points from 33 to 7. The cost is that FCS opponents are no longer told apart from one another, which the matchup card labels. Without a CBS membership list there is nothing to pool against, so every team keeps its own identity and the fix simply does not apply.

The ATS lean compares the independent model spread, adjusted for rest/lookahead/letdown notes, with the observed market. Stadium reputation is context only; home advantage is already in the scoring model. No odds or insufficient team data means no ATS lean. An edge below one point also produces no lean.

## School spending

Power Ranking lists estimated 2026 roster cost (what a program pays its players) and FY2025 athletic department expenses for every school on nil-ncaa.com, cached weekly in `data/nil.json`. Each matchup's Model detail shows both sides' figures.

Roster cost also feeds a prior on the projected margin, fitted fresh each refresh by regressing team rating on log payroll — the points-per-dollar slope is measured, never assumed, so a weak relationship produces a weak adjustment. It applies only while a team has under eight games this season, fades linearly to zero, moves the margin without touching the projected total, and is skipped unless both schools report a roster cost. Set `MAX_WEIGHT = 0` in `nil.py` to disable it.

Athletic department budgets are reference only and never move a spread. Fitted across FBS and FCS together, that line puts a Power 4 host about three points above an FCS visitor where the ratings say eleven and the market says fifty-six; shrinking toward it made those projections worse. Because the prior works by pulling a team toward the fitted line, it favours whichever side sits furthest below its own payroll, which is not always the bigger spender.

Confidence is a qualitative Low/Moderate label, not a calibrated cover probability. Moderate requires at least four current-season games for both sides and an absolute edge of at least three points. No High label is issued. The model has not demonstrated profitable out-of-sample ATS performance. Roster talent enters only as the light prior described under Roster talent; injuries, returning production and play-level efficiency are not modeled. Reconstructed ranking trends use current poll context, not historical poll knowledge.

## Roster talent

Power Ranking lists every FBS roster from 247Sports' Team Talent Composite — each player on the roster rated by his recruiting grade, summarized as rated players, 5-, 4- and 3-star counts, average player rating and 247's weighted talent score — cached weekly in `data/talent.json`. The Power Ranking table carries each team's talent rank, and each matchup's Model detail shows both sides' average rating.

Average player rating feeds a prior on the projected margin, built like the roster-cost prior: team rating is regressed on it fresh each refresh, and each FBS team is pulled 20% of the way toward the rating its roster implies before it has played, fading to zero at eight games this season. Unlike roster cost, an FCS opponent with no composite row sits out while its FBS opponent is still measured. Last season's composite is never used for the current season.

It was chosen by the same walk-forward test as the model settings: each 2025 game predicted only from earlier games using 2025's composite, then confirmed once on 2026's first 100 games. On 2025 it made no measurable difference (mean margin error 12.665 to 12.649); on the 2026 holdout error fell from 17.20 to 16.89. Against the week of Sept. 12's 84 DraftKings lines it made no net difference once every other adjustment is included (average gap 6.57 to 6.58 points): closer on FBS-vs-FCS games, further on FBS-vs-FBS ones. Average rating beat 247's talent score, adding 247's transfer-portal class, and last season's talent change, which made 2025 worse. It is deliberately a nudge and does not close the biggest gaps with the market. Set `MAX_WEIGHT = 0` in `talent.py` to disable it.

The 2026 composite grades players by 247's own high-school ratings, not a transfer grade. Returning production is not modeled: the free tables cover 2026 alone, so it cannot be tested the same way.

## Weather and print

Open-Meteo supplies hourly city forecasts from kickoff through about three hours afterward, up to 16 days out. Outdoor-game banners flag wind/gusts at least 15 mph, rain, snow, and freezing/mixed precipitation (sleet risk). These are in-app alerts, refreshed on launch, week selection and every 15 minutes while the page is open. Indoor venues suppress field-weather alerts. Missing or old forecasts are labeled.

Print shows offense/defense ranks and letters beside the teams, with spread, total, lean and confidence in the middle. Context includes recent results, venue, weather and selected verified rivalries. Pick controls and My Pick text are omitted. Optional pick highlighting defaults off. Color and ink-saving modes are available; printing uses landscape pages. Displayed spreads/projections round to half points with one decimal; stored lines and calculations keep precision.

## Data and maintenance

Power Ranking also carries a Data health panel: feed counts, poll dates, the fitted spending slope, and which of this week's games have no market spread.

`data/picks.sqlite3` stores picks and captured market snapshots. `data/live.json` stores feeds. `nil.json` caches school spending, `talent.json` caches the 247Sports roster talent composite and `servers.json` tracks running instances. `history-YYYY.json` caches prior-season scores, `locations.json` caches city coordinates, and `rank_history.json` preserves observed poll snapshots. Missing provider odds remain missing; no betting lines are invented.

ESPN removes the odds from a game once it kicks off, so the app archives lines itself: every sync records each upcoming game's spread, total and prices in the `market_lines` table whenever they change, and the last capture before kickoff becomes that game's closing line. Completed games get their closing line back in memory before the model runs, which is what lets ATS records and the letdown note work. Archiving began on 2026-09-10; nothing earlier can be recovered, so ATS records fill in only for games played after that. The cards say "capturing lines since …" until a team has one.

`handicap.py` holds the rating model `power.py` fits, plus a command-line `ratings`/`predict`/`backtest` interface over CSV files. The dashboard uses only its `Model` class.

The project is a git repository; `data/picks.sqlite3` and `data/rank_history.json` are tracked because neither can be recovered if lost, while the large refetchable caches are ignored.

Run `python -m unittest discover` for regression checks. `test_jscheck.py` also proves the dashboard's inline script still parses — an unterminated string there stops the browser reading the whole `<script>` and the page renders nothing, which no other test would catch. It is a structural check, so still load the page once after editing the script. See `CHANGELOG-2026-09-09.md` for the detailed changes and audit.
