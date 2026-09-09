# NCAAF changes and data audit — September 9, 2026

Updated the existing app used by NCAAF.lnk, in `i-wa/outputs/cfb_handicap`.

## Later the same day — page fix, launch fix, spending

- **The dashboard was rendering nothing.** `dashboard.html` had been left with `${printing?marketLine(e):'}` — an unterminated string, so the browser refused the entire `<script>` and no part of the page ran. Fixed, and `jscheck.py` now proves the inline script parses as part of the test suite; `test_jscheck.py` re-breaks the real page the same way to show the guard catches it. Node is not a dependency, so this is a structural scan, not a full parse.
- **Stale servers.** Four copies were live on 8765-8768, one of them serving the desktop shortcut from older code, because the default port had moved and `Stop Weekly Picks.cmd` only ever swept 8768. Each server now registers its port and shutdown token in `data/servers.json`; a launch finds a running instance on any port and opens that instead of binding a second one, and `--stop` closes them all — asking politely over HTTP first, force-killing only processes it can confirm are `dashboard.py`, and leaving other programs' ports alone. `.claude/launch.json` said 8765 and now says 8768.
- **Model detail** on each matchup card exposes figures the model already computed but never showed: raw model line vs market, the situational adjustment, the edge actually behind the lean, projected total vs market total, and the confidence sample. Totals are labelled context — no Over/Under picks are made.
- **Data health** panel in Power Ranking reports feed counts, poll dates, the fitted spending slope and which of this week's games have no market spread. That last row replaces the manual missing-odds table below: at the checked refresh only Prairie View A&M at Baylor was still missing a line.
- **School spending** from nil-ncaa.com, cached weekly in `data/nil.json`: estimated 2026 roster cost for 68 Power 4 programs and FY2025 athletic department expenses for 263 schools, listed in Power Ranking and shown per matchup. thesideline.co returns 403 to automated requests and was not used.

### What spending does and does not move

Roster cost feeds a prior on the projected margin. The points-per-dollar slope is fitted each refresh by regressing team rating on log payroll rather than assumed — currently 6.82 points per doubling, R² 0.33 across 68 schools — so a weak relationship yields a weak adjustment. It is weighted by how little the model has seen of a team this season, fades linearly to zero at eight games, and moves the margin without touching the projected total. Observed effect this week: 13 of 41 games, 0.5 to 2.0 points.

Athletic department budgets are listed but never move a spread. Fitted across FBS and FCS together, that line puts Miami about 3 points above Florida A&M where the ratings say 11 and the market says 56.5; shrinking toward it moved those projections further from the market, so the model uses roster cost only, which is fitted on one homogeneous population. Games where either school has no roster cost get no prior at all rather than an assumed budget.

Two behaviours worth knowing. Because the prior pulls a team toward the fitted line, it favours whichever side sits furthest below its own payroll — not always the bigger spender. And it does not currently help the Power 4 versus FCS mismatch, which is the case it was asked for; doing that honestly needs a fit that models the subdivision gap instead of one line through both.

Fixed while building this: the expenses table lists two schools called "Miami", and the MAC row was overwriting the ACC one, so Miami (FL) carried Miami (OH)'s $40.8M budget. They are now separated by conference. Regression tests cover both this and the roster-versus-budget comparison.

Suite: 119 tests.

## Delivered

- Combined This Week and Board: weekly matchup layout with instant side selection, real-bet stars, and an editor for stakes, odds, notes and manual lines. Repeating a saved-side click preserves the captured line. Missing prices open the editor instead of silently assuming -110.
- Print: home and away columns, offense/defense numeric ranks and letter grades, central market spread and total, model lean/confidence underneath, venue, forecast, recent results, rest/lookahead and rivalry context. No pick buttons or “My Pick” text. Optional highlighting defaults off; color and ink-saving modes are available. Displayed spreads and projections use half-point increments and one decimal. Underlying calculations retain precision.
- Combined poll list moved into Power Ranking. Offense/defense ranks and grades now compare all teams with scoring history, including opponents outside the tracked Top 50.
- Removed market-line and arbitrary poll fallback picks. Stadium reputation remains context and no longer adds a second home-field adjustment. The independent scoring model includes 958 completed games involving FBS teams from 2025 plus 99 current-season games, with a 180-day recency half-life. ATS selection compares that projection with the market.
- Confidence is qualitative, not a calibrated cover probability. Early-season samples are Low; Moderate requires at least four current-season games for each team and a three-point edge. No High label is issued. No market spread means no ATS lean. No adequate team history means no projection.
- Hourly venue-city forecasts cover kickoff through about three hours afterward, rather than today's current conditions. In-app alerts flag sustained wind or gusts at least 15 mph, any forecast rain, snow and freezing/mixed precipitation. Sleet is identified as a risk from mixed/freezing codes, not a separately measured sleet forecast. Indoor venues suppress field-weather alerts. Forecasts beyond the provider's 16-day window remain unavailable.
- Removed stale split fields during refresh, excluded cached events from other seasons, added legacy ESPN spread parsing, removed duplicate Board rendering/styles and unused rank-proxy code. Startup now prevents additional copies from binding the same Windows port.

## Missing odds

The live ESPN Week 2 scoreboard had no odds object for these four games when checked:

| Away | Home |
|---|---|
| Weber State | Colorado |
| Campbell | Florida |
| Towson | South Carolina |
| Prairie View A&M | Baylor |

This is missing provider coverage, not a rendering issue. All four involve FCS opponents, but the feed does not state why it omitted them. The app labels the missing source data and allows a manually entered line. It does not invent odds.

## Data now useful, and remaining candidates

| Data | Status / decision |
|---|---|
| Offense/defense coefficients and grades | Now used for numeric ranks and letter grades in both matchup and print views. |
| Recent scores, venue, neutral-site flag, rest and schedule neighbors | Used in projections or visible matchup context. |
| Prior-season scoring results | Newly used to stabilize the early-season fit; roster/coaching turnover is not modeled separately. |
| Public bet/handle splits | Visible context only. No unvalidated “fade the public” adjustment. |
| ATS history | Current cached completed games lack usable closing spreads, so zero records now read “ATS history unavailable.” Saved personal picks still settle from the exact saved line. |
| `home_edge_points`, `total_edge_points`, `weather_note` | Retained analytical outputs not displayed separately in the simplified cards. Candidates for a future model-detail view or removal after checking external consumers. Total edges and weather notes do not currently generate total picks. |
| `ap_date`, feed import/split counts, raw curated ranks and unused venue metadata | Retained source/audit metadata, not all directly displayed. Could feed a dedicated data-health panel; do not treat these as independent predictive inputs. |
| `market_snapshot` in saved picks | Keep: provenance of the exact market observed when the pick was recorded. |
| `rank_history.json` | Keep: real archived poll snapshots support poll movement. Reconstructed model trends still use current poll context, so they are not historical backtests. |
| `weekly.py`, `rankings.py`, CSV templates, demo/CLI paths | Not used by the desktop browser shortcut. Retained as alternate tools rather than deleting potentially useful workflows. |
| Injuries, roster continuity, returning production, pace, play efficiency, turnovers and travel | Not present as reliable structured model inputs. These remain model limitations; nothing was fabricated. |
| Rivalries | Verified Border Showdown and Cy-Hawk examples added. This is a small curated list, not comprehensive season coverage. |

The model remains a scoring model, not a proven betting system. In the checked Week 2 snapshot after adding previous-season data, it produced 9 home leans, 27 away leans and 5 no-leans. This demonstrates removal of the mechanical home bias, not demonstrated betting accuracy. Out-of-sample ATS calibration remains future work.

## Verification and launch

- Python regression suite: 67 tests covering storage/HTTP picks, settlement, model signs and future-data exclusion, no fabricated fallback picks, weather thresholds and UTC forecast-window selection.
- JavaScript checks: render, print omission of pick controls, one-decimal half-point display and repeat-click preservation of a saved line.
- Live forecasts: 41/41 tracked Week 2 games, with 25 weather alerts at the checked refresh.
- Browser review: combined weekly board and print layout rendered successfully.

The updated app is running at http://127.0.0.1:8766 for review. Five pre-existing Python servers were found on port 8765. Windows denied terminating those processes from this session. To update the desktop shortcut's running backend, close the old servers using `Stop Weekly Picks.cmd`, then reopen NCAAF. The new startup guard prevents additional duplicates. Saved picks were not changed during testing.

Alerts refresh in the app on launch, week changes and every 15 minutes while its page is open. This work does not install background desktop/push notifications.

Sources: [Open-Meteo hourly forecasts and weather codes](https://open-meteo.com/en/docs), [ESPN Week 2](https://www.espn.com/college-football/schedule/_/week/2/year/2026/seasontype/2), [Kansas Border Showdown](https://kuathletics.com/news/2026/9/7/football-jayhawks-welcome-tigers-for-122nd-playing-of-border-showdown), [Iowa Cy-Hawk series](https://hawkeyesports.com/corn-cy-hawk-series).
