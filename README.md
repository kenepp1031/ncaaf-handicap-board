# College Football Picks

Batch pipeline, matching the architecture of the sibling NFL 2.0 app: run it, it ingests this week's data into a local SQLite database, fits the rating model, and writes one static `dashboard/dashboard.html` that opens in your browser. No live server, no polling, no picks/wager tracker — open the file, read it, close it, run it again next time you want fresh numbers.

The page is one continuous scroll: a short note on how to read it, then every Top-50 matchup in kickoff order, then the power ranking. There is deliberately no ranked pick list — see **Measured accuracy** below. Kickoff times are shown in the time zone of the machine that ran the pipeline, as "1:00 PM Saturday". `streamlit_app.py` is the optional phone view: it embeds the same rendered file on Streamlit Cloud, so refresh it by re-running the pipeline and pushing `dashboard/dashboard.html`.

## Running it

Double-click `Start NCAAF Handicap.cmd`, or from a terminal:

```
python main.py                          # auto-detects season/week from today's date
python main.py --week 3                 # explicit week, current season
python main.py --season 2026 --week 3   # explicit season and week
python main.py --skip-scrape            # re-fit/re-render only, no network calls
python main.py --no-open                # don't open the dashboard in a browser
python main.py --ingest-seasons 2024,2025,2026   # one-time historical backfill
```

There is also a desktop shortcut, `NCAAF Handicap` in `Desktop\My shit`, pointing at the same `.cmd`.

Each run: pulls the ESPN scoreboard/schedule, CBS/AP/Coaches rankings, DraftKings betting splits and lines, Open-Meteo weather, school-spending and 247Sports talent figures, team-level penalty tendencies, ESPN box scores and play-by-play, the covers.com injury report, and (weekly) each school's 247Sports transfer-portal page; fits the rating model on everything completed so far; writes projections, notes and power ratings to `ncaaf_handicap.db`; grades last week's completed games into the backtest log; and renders `dashboard/dashboard.html`.

## Daily refresh

A Windows scheduled task, **NCAAF Handicap Daily Update**, runs `scripts/daily_update.ps1` every morning at 6:30 so the dashboard is current before kickoff. That script is just `main.py --no-open` with logging around it — `main.py` auto-detects the season and week from the games already in the database, so nothing about the schedule is hardcoded.

```
powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1              # install / re-install
powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -At 05:30    # different time
powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -Uninstall   # remove
Start-ScheduledTask -TaskName 'NCAAF Handicap Daily Update'                          # run it now
```

It runs as the logged-in user with an interactive token (not SYSTEM), so it resolves Python the same way `Start NCAAF Handicap.cmd` does. `StartWhenAvailable` catches the run up if the machine was asleep at 6:30, and a failed run retries twice at 30-minute intervals.

Output goes to `logs/update-<date>.log`, with `logs/last_run.json` as the at-a-glance status — `ok`, the fitted-model status line, and the dashboard's write time. Logs older than 30 days are deleted. A failed run exits non-zero, so the task's Last Run Result shows it.

From late January through July the script skips the pipeline and logs that it did: no new games are played, no lines are posted, and the ratings fit would be identical every morning. Pass `-Force` to run anyway.

## Model and rankings

Opponent-adjusted offense and defense are fitted to scoring results from the current and previous season with a 365-day recency half-life and light ridge regularization (1.5), chosen by walk-forward testing. `ratings/handicap_model.py` holds the rating engine itself — dependency-free, unchanged from the pre-migration app, and still usable standalone via its `ratings`/`predict`/`backtest` CLI over CSV files.

Every FCS opponent shares one pooled rating rather than carrying its own — an FCS school appears in one or two FBS results a season, and ridge shrinkage pulls a coefficient built from that little evidence too far toward the mean. The pooled entity is backed by every FCS-vs-FBS game. Without CBS's membership list there is nothing to pool against, so every team keeps its own identity.

The model lean compares the independent model spread, adjusted for rest/lookahead/letdown notes, with the observed market. Stadium reputation is context only; home advantage is already in the scoring model. Confidence is a qualitative Low/Moderate/High label rating **how much to trust the projection**, not how good a bet is — it falls as the model moves away from the market. It is not a calibrated cover probability.

## Measured accuracy

Walk-forward over the 2025 and 2026 seasons (refit per game-date on prior data only), 786 FBS-vs-FBS games:

| | model | closing line |
|---|---|---|
| margin MAE | 13.07 | **11.83** |
| 2026 only (n=114) | 14.46 | **11.59** |
| correlation with actual margin | 0.609 | **0.691** |

**This model does not beat the closing line.** Its error also grows monotonically with its distance from that line — 10.7 margin MAE where it sits within a point of the market, 17.9 where it is 10+ points away, and 49-61 ATS in the 6-10 point band. Ranking games by model-vs-market disagreement therefore selects for model error, which is why the top-five picks panel and the old "bigger edge = higher confidence" scale were both removed on 2026-09-20.

A sweep of ridge (0.5-15), half-life (90-730) and home advantage (2.0-4.5) put the shipped settings at the MAE minimum, with ATS at a 3+ point threshold near 50% across the entire grid. The gap to the market is structural, not a tuning problem: the model sees only final scores — no possessions, yards, success rate, turnover regression, garbage-time control, or QB/injury information.

## Sharp Side: the straight-bet list

Measured 2026-10-02 on completed 2026 games, the market signals the board already captures did better than the model: the side where DraftKings' **money share beats its ticket share by 10+ points** went 47-34 ATS (58%) and won 60% straight up on lines averaging pick'em (82 games); line moves of 1.5+ covered 61% at the close (49); reverse line moves 62% but as 15-point dogs (42). The model lean alone went 56-62. Fading the public was a coin flip and Kalshi crowd money was a fade (26-42 where its dollar share exceeded its price). All small samples.

`ratings/sharp_side.py` turns the first signal into a logged list. Every run, each side whose money-minus-tickets gap is at least `SHARP_GAP` (10) on a game that has not kicked off is written to `sharp_picks` **once**, with the spread on the board, the line move so far and whether the model agreed; it is never deleted (if the gap closes later, `still_qualifies` drops to 0 but the pick stays). Finished games are graded straight up, ATS at the close and ATS at the line when first listed. The dashboard's top card, "Sharp Side — straight bets", lists this week's sides sorted by gap (20+ highlighted) with the season record. `python ratings\sharp_side.py 2026` prints the log. Judge it after about eight weeks.

## Your hand: manual_adjustments.csv

The one input the model cannot see is what you know: a starting QB out, a team that dominated on yards and lost on a fumble, a coaching change. `manual_adjustments.csv` in the project root is where that goes. One row per team: `team,points,note,until`. `points` is added to that team's projected margin in every game it plays (positive = better than the model says; a starting QB out is typically -4 to -7, "a hair" is 0.5 to 1.5; capped at ±10). `until` is an optional last date. Lines starting with `#` are ignored and names that don't match an FBS team are logged and skipped. The hourly task picks the file up on its next run; `python main.py --skip-scrape --no-open` applies it immediately.

The dashboard shows the nudge on the matchup card ("Your adjustment"), in the Power Ranking table, and in a full list of every FBS team sorted by model rating plus nudge. The adjustment is stored on its own in `projections`, `projection_snapshots` and `backtest_log`, so `python backtest/report.py --season 2026` reports `your_hand`: the ATS record of the published number against what the model alone would have picked, on the games you touched. If "with_your_hand" is not beating "model_alone" over a real sample, the nudges are not helping.

Measured 2026-10-02 and **not** adopted: fitting the model on box-score quality (yards per play, turnovers, first downs, third-down rate, blended with or replacing the final margin) left walk-forward margin error unchanged (12.8 against the market's 11.7 under every blend tested) and ATS at a coin flip. Team-level box stats carry nothing the final score did not already say. Capping blowout margins at 28 was worse (13.3).

## Starting-QB injuries: covers.com + ratings/injury_prior.py

ESPN's college injury feed is empty, so `ingest/injuries.py` scrapes covers.com's season injury page every run: all 138 FBS teams, player, position, status, injury and date (`injuries` is the current list, `injury_history` keeps every change). `ratings/injury_prior.py` joins the QBs on that list to the starter the box scores say each team actually uses (most starts this season, by pass attempts). When the starter is listed **Out** or **Doubtful** for a game inside the next 8 days, the team is docked `QB_OUT_POINTS` (4) or `QB_DOUBTFUL_POINTS` (2), halved if the backup already started the team's last game. Questionable/Probable only produce a note. The shift is stored as `injury_margin_shift` in `projections`, `projection_snapshots` and `backtest_log`, and `python backtest/report.py --season 2026` reports `qb_injury_prior`: the touched games graded with and without it. The 4 points is a convention, not a measurement -- tune it once that section has a sample. Each card shows the team's Out/Doubtful and Questionable lists; the Power Ranking and all-FBS tables carry a Starting QB column.

## Transfer portal: 247Sports (context only)

`ingest/transfers.py` pulls each FBS school's portal page (`247sports.com/college/<slug>/season/<year>-football/transferportal/`, slugs taken from the talent composite's roster links) once a week: every incoming and outgoing transfer with position, composite rating, stars and status, into `transfers`. Cards show "Portal: N in (avg) · M out (avg) · net", where net is the rating weight above 0.80 gained minus lost (hover for the top three each way); the all-FBS table has a Portal net column. It does not touch the number: the talent composite already counts enrolled transfers, and there is no local sample to fit churn against.

## School spending and roster talent

Roster cost (nil-ncaa.com) and 247Sports' Team Talent Composite each feed a light prior on the projected margin, fitted fresh every run from that run's own ratings — never assumed. Both fade to zero once a team has enough current-season games, and are skipped when a side doesn't report a figure. Set `MAX_WEIGHT = 0` in `ratings/nil_prior.py` or `ratings/talent_prior.py` to disable either.

Walk-forward, both measure as roughly neutral (MAE 13.05 and 13.03 respectively against 13.07 with all priors off). The third prior — penalty tendency, in `ratings/officiating_prior.py` — measured actively harmful (MAE 13.16, ATS 50.7% against 52.9%) and was disabled on 2026-09-20 by setting its `MAX_WEIGHT` to 0. Penalty differential is mostly game script and opponent quality rather than a team trait, and it typically fits at an R² near 0.01. Note that all three `fit()` calls regress their variable against the very ratings they then adjust, so the R² reported in the dashboard status line is in-sample against its own target and should not be read as evidence the prior predicts anything.

## Box scores (context only)

`ingest/box_scores.py` caches each finished game's ESPN box score — plays, yards, turnovers, first downs, third downs, possession, and the starting QB (most pass attempts) — in `box_scores`. Backfill with `python -m ingest.box_scores --budget 900`. Each matchup card shows the team's season yards/game and yards/play, gained and allowed, with FBS ranks and turnover margin. When a team's last game had a different starter from the QB who started most games before it, a **QB change** note appears.

None of this feeds the model. Walk-forward on 2026-09-26 (blend weights fit on 2025, scored on 162 unseen 2026 games) put opponent-adjusted yards per play at 13.14 margin MAE against 13.19 for scores alone. Turnover-adjusted scoring measured worse (13.31), and a QB-change flag moved nothing.

## Play-by-play efficiency (context only)

The same ESPN summary carries every drive and play. `ingest/plays.py` folds them into per-team success rate (50%/70%/100% of the distance on 1st/2nd/3rd-4th down), explosive-play rate (rush 12+, pass 16+), yards per play and points per drive, with garbage time removed (lead over 38/28/22 in the 2nd/3rd/4th quarter), in `play_stats`. Backfill with `python ingest\plays.py --budget 1200`. Each card shows the team's success rate, explosive rate and points per drive, gained and allowed, with FBS ranks; the all-FBS table shows success rate for and against.

Measured 2026-10-02 and **not** adopted as a training target (coefficients fit on 2025, walk-forward over 841 FBS-vs-FBS games with a line): a 50/50 blend of final margin and the efficiency margin (success rate + yards/play + explosiveness, R² 0.67 in-sample against the final margin) gave 12.76 MAE against 12.79 for plain scores and ATS 50.7% against 52.5%; efficiency alone 13.05; adding turnovers 12.78; success rate alone 12.80. Straight-up winner accuracy ticked up (74.1% vs 73.0%) but nothing touched the market's 11.73. Per-play quality aggregated to the team level is already in the scoreboard. Do not re-test without a new idea (e.g. opponent-adjusting the efficiency itself, or a market-anchored model).

## Weather

Open-Meteo supplies hourly city forecasts from kickoff through about three hours afterward, up to 16 days out. Outdoor-game banners flag wind/gusts at least 15 mph, rain, snow, and freezing/mixed precipitation. Indoor venues suppress field-weather alerts.

## Data

Everything lives in `ncaaf_handicap.db` (gitignored — regenerate with `--ingest-seasons`, or copy it elsewhere if you want a backup). `db/schema.sql` is the full table definition. ESPN removes the odds from a game once it kicks off, so `ingest/dk_lines.py` archives every observed line into `line_history`; the last capture before kickoff becomes that game's closing line for ATS grading.

`projection_snapshots` is the audit trail: an append-only row per (game, run) written **only before kickoff**, so the record of what was published can never be overwritten by a later run. `projections` remains a single current-view row per game for the dashboard. A finished game never gets a projection written at all — the earlier rule ("keep the first one") let a backfill run freeze hindsight projections in permanently, which left 201 of 205 completed 2026 games both ungradable and un-recomputable until it was fixed on 2026-09-20.

`backtest/log_results.py` grades the last pre-kickoff snapshot against the closing line, scoring `lean_home_spread` — the number the dashboard actually shows — rather than the raw model line. `backtest/report.py` splits the record by edge bucket and by confidence tier, reports the model's margin error beside the closing line's own on the same games, and quarantines pooled-FCS games from the headline (one Oregon 84–0 Portland State supplied 31.5 of the 44.2 total absolute error in the first version of the log). Run `python -m backtest.report --season 2026`.

Run `python -m unittest discover -s ratings` for the rating-engine regression checks. See `CHANGELOG-2026-09-09.md` for the pre-migration app's detailed change history.
