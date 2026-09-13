"""Public, mobile-friendly companion for the NCAAF handicapping board.

This app deliberately reads the checked-in JSON snapshot (data/web_snapshot.json)
rather than the Windows desktop UI or its live caches. That makes it suitable
for Streamlit Community Cloud: the site can stay open even when the authoring
PC is off. It never touches dashboard.py, app.js, storage.py, or any other
file the desktop app uses, and it has no write/editing capability.

Refresh the snapshot with `python export_web_snapshot.py` after using the
desktop app, then commit+push data/web_snapshot.json — see README_WEB.md.

Rendering here intentionally mirrors app.js's matchupCard/grades/modelDetail/
notesBlock/renderPower wording so the phone view reads the same as the
desktop page.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = APP_DIR / "data" / "web_snapshot.json"


@st.cache_data(ttl=300)
def load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError("The published board snapshot is missing.")
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def kickoff_text(value: str | None) -> str:
    if not value:
        return "Kickoff time unavailable"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        hour = moment.hour % 12 or 12
        return f"{moment:%a, %b} {moment.day} · {hour}:{moment:%M %p}"
    except ValueError:
        return value


def half(value) -> str:
    return "—" if value is None else f"{value:.1f}"


def spread_text(value) -> str:
    if value is None:
        return "—"
    return f"{'+' if value > 0 else ''}{value:.1f}"


def money(value) -> str:
    if value is None:
        return "—"
    return f"${value/1e6:.1f}M" if value >= 1e6 else f"${round(value/1e3):,}K"


def market_line(game: dict) -> str:
    if game.get("home_spread") is None:
        return "No market spread"
    side = "home" if game["home_spread"] <= 0 else "away"
    line = game["home_spread"] if side == "home" else game["away_spread"]
    return f"{game[side]} {spread_text(line)}"


def lean_text(game: dict) -> str:
    side = game.get("lean_side")
    if not side:
        return "No lean"
    key = side.lower()
    team = game.get(key)
    home_line = game.get("lean_home_spread")
    if home_line is None:
        return f"{team} —"
    line = home_line if key == "home" else -home_line
    mark = {"Win": " · RIGHT", "Loss": " · WRONG", "Push": " · PUSH"}.get(game.get("lean_result"), "")
    return f"{team} {spread_text(line)}{mark}"


def ats_text(record: dict | None) -> str | None:
    if not record or (record.get("wins", 0) + record.get("losses", 0) + record.get("pushes", 0)) == 0:
        return None
    return f"{record['wins']}-{record['losses']}-{record['pushes']} ATS"


def grade_text(grade: dict | None) -> tuple[str, str, str | None]:
    """Mirror app.js's grades(): (offense line, defense line, footnote)."""
    if grade is None:
        return "Offense: Unrated", "Defense: Unrated", None
    if grade.get("ranked") is False:
        return "Outside FBS ranking pool", "Not assigned an FBS rank or grade", None
    off = f"#{grade['offense_rank']} · {grade['offense_grade']}" if grade.get("offense_rank") else "Unrated"
    dfn = f"#{grade['defense_rank']} · {grade['defense_grade']}" if grade.get("defense_rank") else "Unrated"
    games = grade.get("games")
    footnote = None
    if games is not None:
        pop = grade.get("ranking_population") or "—"
        scope = grade.get("ranking_scope") or "FBS"
        footnote = f"Out of {pop} {scope} teams · {games} games across recent seasons" + (
            " · provisional" if games < 4 else ""
        )
    return f"Offense: {off}", f"Defense: {dfn}", footnote


def previous_game_text(prev: dict | None) -> str | None:
    if not prev:
        return None
    return (
        f"PREVIOUS GAME · {prev.get('game_date', '')} — vs {prev.get('opponent')} · "
        f"{prev.get('result')} {prev.get('scored')}–{prev.get('allowed')}"
    )


def notes_for(game: dict, side: str) -> list[str]:
    """Mirror notesBlock: ATS record first, then situational notes minus the raw 'Last result:' line."""
    notes = [n for n in (game.get(f"{side}_notes") or []) if not n.startswith("Last result:")]
    ats = ats_text(game.get(f"{side}_ats"))
    return ([ats] if ats else []) + notes


def weather_text(game: dict) -> str | None:
    venue = game.get("venue") or {}
    w = game.get("weather")
    if venue.get("indoor"):
        return "Indoor venue · field conditions sheltered"
    if not w or not w.get("forecast"):
        return game.get("weather_status") or "Game forecast unavailable"
    try:
        fetched = datetime.fromisoformat(w["fetched_at"])
        age_hours = (datetime.now(fetched.tzinfo) - fetched).total_seconds() / 3600
    except (KeyError, ValueError, TypeError):
        age_hours = 0
    stale = "Stale · " if age_hours > 2 else ""
    temp = w.get("temperature_2m")
    wind = w.get("wind_speed_10m") or 0
    temp_str = "—" if temp is None else f"{round(temp)}°F"
    return f"{stale}{temp_str}, wind {round(wind)} mph ({w.get('location', 'nearby')})"


def model_detail(game: dict) -> list[str]:
    """Mirror app.js's modelDetail(): the full 'Model detail' breakdown, one line per row."""
    if game.get("lean_source") != "model":
        return []
    home, away = game["home"], game["away"]

    def toward(n):
        if n is None:
            return None
        if n == 0:
            return "even with the market"
        return f"{abs(n):.1f} pts toward {home if n > 0 else away}"

    rows = []
    raw = toward(game.get("home_edge_points"))
    if raw:
        rows.append(f"Model line vs market: {raw}")
    fair, lean = game.get("fair_home_spread"), game.get("lean_home_spread")
    nudge = (fair - lean) if fair is not None and lean is not None else None
    if nudge is not None and abs(nudge) >= 0.5:
        rows.append(f"Situational adjustment: {toward(nudge)} (rest, letdown and lookahead notes shown beside each team)")
    used = toward(game.get("lean_edge_points"))
    if used:
        rows.append(f"Edge behind the lean: {used} (needs 1.0 pt for any lean; 2.0 pts and two games each for "
                     "Moderate; 4.0 pts and five games each for High)")
    if game.get("projected_total") is not None:
        gap = game.get("total_edge_points")
        compared = "no market total to compare" if gap is None else f"{abs(gap):.1f} pts {'above' if gap >= 0 else 'below'} the market"
        rows.append(f"Projected total: {half(game['projected_total'])} · {compared} (context only — no Over/Under picks)")
    measure = game.get("spend_measure")
    if measure:
        field = "roster_cost" if measure == "roster" else "athletic_expenses"
        label = "Roster cost" if measure == "roster" else "athletic dept. budget"
        shift = game.get("spend_margin_shift")
        effect = toward(shift) if shift else "no adjustment left — both teams have enough games this season"
        hs = (game.get("home_spending") or {}).get(field)
        aws = (game.get("away_spending") or {}).get(field)
        rows.append(f"Spending prior: {effect} ({label}: {home} {money(hs)} · {away} {money(aws)})")
    home_talent, away_talent = game.get("home_talent"), game.get("away_talent")
    if home_talent or away_talent:
        def talent_str(r):
            return f"{r['avg_rating']:.2f} avg · #{r['rank']}" if r else "not on the composite"
        shift = game.get("talent_margin_shift") or 0
        effect = toward(shift) if abs(shift) >= 0.25 else "under half a point"
        rows.append(f"Roster talent prior: {effect} (247Sports average player rating: "
                     f"{home} {talent_str(home_talent)} · {away} {talent_str(away_talent)})")
    pooled = game.get("pooled_fcs")
    if pooled:
        who = " and ".join(game[s] for s in pooled)
        rows.append(f"FCS opponent: {who} — rated as a pooled FCS baseline, not individually")
    if game.get("weather_note"):
        rows.append(game["weather_note"])
    if game.get("confidence_detail"):
        rows.append(game["confidence_detail"])
    return rows


st.set_page_config(page_title="NCAAF Handicapping Board", page_icon="🏈", layout="wide")
st.title("NCAAF handicapping board")
st.caption("Public web companion · research only, not betting advice")

try:
    snapshot = load_snapshot()
except (json.JSONDecodeError, FileNotFoundError) as error:
    st.error(f"Unable to load the published board: {error}")
    st.stop()

events = snapshot.get("events", [])
rankings = snapshot.get("rankings", [])
top50 = snapshot.get("top50", [])
power_meta = snapshot.get("power_meta", {})
weeks = sorted({e["week"] for e in events if e.get("week") is not None})

with st.sidebar:
    st.header("Board controls")
    week = st.selectbox("Week", weeks, index=len(weeks) - 1 if weeks else 0) if weeks else None
    show_model = st.toggle("Show model lean", value=True)
    show_detail = st.toggle("Show full model detail", value=False)
    st.divider()
    st.caption(f"Season {snapshot.get('season', '—')} · Snapshot updated {snapshot.get('updated_at', 'unknown')}")
    st.caption(
        "This cloud edition uses the latest snapshot committed to the site. "
        "Run the desktop app, then `python export_web_snapshot.py` and push to publish new lines, scores, rankings, or picks."
    )

week_games = [e for e in events if e.get("week") == week] if week is not None else events
week_games = sorted(week_games, key=lambda e: e.get("kickoff") or "")
finals = sum(e.get("completed") for e in week_games)
picked = sum(bool(e.get("pick_side")) for e in week_games)
starred = sum(bool(e.get("pick_favorite")) for e in week_games)
with st.container(horizontal=True):
    st.metric("Games", len(week_games), border=True)
    st.metric("Final", finals, border=True)
    st.metric("Saved picks", picked, border=True)
    st.metric("Starred bets", starred, border=True)

def confidence_rating(game: dict) -> int | None:
    """Mirror app.js's confidenceRating(): edge points (1.0-4.0) onto a 1-10 display rating."""
    edge = game.get("lean_edge_points")
    if edge is None:
        return None
    return max(1, min(10, round(edge * 2.5)))


def render_matchup_card(game: dict) -> None:
    home, away = game["home"], game["away"]
    with st.container(border=True):
        st.caption(kickoff_text(game.get("kickoff")))
        if game.get("weather_alert"):
            st.warning(game["weather_alert"], icon="⚠️")
        left, middle, right = st.columns((4, 3, 4))
        with left:
            st.markdown(f"### {away}")
            if game.get("away_combined"):
                st.caption(f"Poll #{game['away_combined']}")
            st.caption(f"Record: {game.get('away_record') or '—'}")
            off, dfn, footnote = grade_text(game.get("away_grade"))
            st.caption(off)
            st.caption(dfn)
            if footnote:
                st.caption(footnote)
            for note in notes_for(game, "away"):
                st.caption(f"• {note}")
            prev = previous_game_text(game.get("away_previous"))
            if prev:
                st.caption(prev)
        with middle:
            st.metric("Market spread", market_line(game))
            st.metric("Total", "—" if game.get("total") is None else f"O/U {game['total']:g}")
            if game.get("completed"):
                st.caption(f"Final: {away} {game.get('away_score', '—')} · {home} {game.get('home_score', '—')}")
            elif game.get("pick_side"):
                pick_team = home if game["pick_side"] == "Home" else away
                st.caption(f"Saved pick: {pick_team}" + (" ★" if game.get("pick_favorite") else ""))
            if show_model:
                st.caption(f"Our lean: {lean_text(game)}")
                st.caption(f"Confidence: {game.get('confidence') or 'Unavailable'}")
                if game.get("home_points") is not None and game.get("away_points") is not None:
                    st.caption(f"Projected score: {home} {half(game['home_points'])} · {away} {half(game['away_points'])}")
            wtext = weather_text(game)
            if wtext:
                st.caption(wtext)
            splits = game.get("home_splits")
            if splits:
                away_bets = round(100 - splits.get("bets", 0))
                away_handle = round(100 - splits.get("handle", 0))
                st.caption(f"Bets: {home} {round(splits.get('bets', 0))}% · {away} {away_bets}%")
                st.caption(f"Money: {home} {round(splits.get('handle', 0))}% · {away} {away_handle}%")
            if show_detail:
                detail_rows = model_detail(game)
                if detail_rows:
                    with st.expander("Model detail"):
                        for row in detail_rows:
                            st.caption(row)
        with right:
            st.markdown(f"### {home}")
            if game.get("home_combined"):
                st.caption(f"Poll #{game['home_combined']}")
            st.caption(f"Record: {game.get('home_record') or '—'}")
            off, dfn, footnote = grade_text(game.get("home_grade"))
            st.caption(off)
            st.caption(dfn)
            if footnote:
                st.caption(footnote)
            for note in notes_for(game, "home"):
                st.caption(f"• {note}")
            prev = previous_game_text(game.get("home_previous"))
            if prev:
                st.caption(prev)
        st.caption(f"{game.get('market_source') or 'No odds supplied by provider'}"
                   + (f" · {game['market_observed_at'][:10]}" if game.get("market_observed_at") else ""))


# Top picks banner (app.js's renderTopPicks): up to 5 non-completed games this
# week with a lean, ranked by |lean_edge_points| descending. Hidden entirely
# (not shown empty) when none qualify -- early season often has none.
top_picks = sorted(
    (g for g in week_games if not g.get("completed") and g.get("lean_side")),
    key=lambda g: abs(g.get("lean_edge_points") or 0),
    reverse=True,
)[:5]
if top_picks:
    st.subheader("Our top picks this week")
    for game in top_picks:
        rating = confidence_rating(game)
        st.markdown(f"**Confidence {rating if rating is not None else '—'}/10**")
        render_matchup_card(game)

st.subheader(f"Week {week} matchups" if week is not None else "This week's matchups")
if not week_games:
    st.info("No Top 50 matchups in this snapshot's schedule.")
for game in week_games:
    render_matchup_card(game)

st.subheader("Our Top 50 teams · combined rankings")
if top50:
    st.dataframe(
        [{"Rank": t.get("rank"), "Team": t.get("team"), "CBS": t.get("cbs"), "AP": t.get("ap"), "Coaches": t.get("coaches")}
         for t in top50],
        hide_index=True, width="stretch",
    )

st.subheader("Power Ranking")
st.caption(power_meta.get("status") or "Power ratings will appear once this season has completed games.")
if rankings:
    ranking_rows = []
    for row in rankings:
        ats = row.get("ats")
        talent_row = row.get("talent")
        ranking_rows.append({
            "Rank": row.get("rank"),
            "Team": row.get("team"),
            "Trend": row.get("trend"),
            "Rating": row.get("rating"),
            "Off": f"#{row['offense_rank']} ({row['offense_grade']})" if row.get("offense_rank") else "—",
            "Def": f"#{row['defense_rank']} ({row['defense_grade']})" if row.get("defense_rank") else "—",
            "Roster talent": f"#{talent_row['rank']}" if talent_row and talent_row.get("rank") else "—",
            "Games": row.get("games"),
            "ATS": ats_text(ats) or "—",
            "AP": row.get("ap_rank"),
            "Combined poll": row.get("combined_rank"),
            "Poll trend": row.get("poll_trend"),
        })
    st.dataframe(ranking_rows, hide_index=True, width="stretch")
else:
    st.info("No rankings available in this snapshot.")

talent_board = power_meta.get("talent_board") or []
if talent_board:
    with st.expander("Roster talent · 247Sports Team Talent Composite"):
        fit = power_meta.get("talent_fit")
        if fit:
            st.caption(f"Average player rating explains {round(fit['r_squared']*100)}% of the rating spread this "
                       f"refresh ({fit['slope']} rating pts per point of average).")
        st.dataframe(
            [{"#": r.get("rank"), "School": r.get("team"), "Talent score": r.get("points"),
              "Avg player rating": r.get("avg_rating"), "5★": r.get("five_star"), "4★": r.get("four_star"),
              "3★": r.get("three_star"), "Rated players": r.get("players")} for r in talent_board],
            hide_index=True, width="stretch",
        )

spend_board = power_meta.get("spend_board") or []
if spend_board:
    labels = power_meta.get("spend_labels") or {}
    with st.expander("School spending · roster cost and athletic department expenses"):
        fit = (power_meta.get("spend_fit") or {}).get("roster")
        if fit:
            st.caption(f"{labels.get('roster', 'Roster cost')} explains {round(fit['r_squared']*100)}% of the "
                       f"rating spread this refresh ({fit['points_per_doubling']} pts per doubling of payroll).")
        st.dataframe(
            [{"#": r.get("spend_rank"), "School": r.get("school"), "Est. roster cost": money(r.get("roster_cost")),
              "Athletic dept. expenses": money(r.get("athletic_expenses"))} for r in spend_board],
            hide_index=True, width="stretch",
        )

st.subheader("Season picks")
picks = snapshot.get("picks", [])
bets_only = st.toggle("Bets only (starred picks)", value=False)
shown_picks = [p for p in picks if p.get("favorite")] if bets_only else picks
w = sum(1 for p in shown_picks if p.get("result") == "Win")
l = sum(1 for p in shown_picks if p.get("result") == "Loss")
push = sum(1 for p in shown_picks if p.get("result") == "Push")
pending = sum(1 for p in shown_picks if p.get("result") == "Pending")
net = sum(p.get("profit_units") or 0 for p in shown_picks)
with st.container(horizontal=True):
    st.metric("Record", f"{w}-{l}-{push}", border=True)
    st.metric("Pending", pending, border=True)
    st.metric("ATS win rate", f"{100*w/(w+l):.1f}%" if (w + l) else "—", border=True)
    st.metric("Net units", f"{net:+.2f}", border=True)
if shown_picks:
    st.dataframe(
        [{
            "Date": p.get("game_date"),
            "Matchup": f"{p.get('away')} @ {p.get('home')}",
            "Pick": f"{p.get('side') == 'Home' and p.get('home') or p.get('away')} {spread_text(p.get('spread'))}",
            "Odds · units": f"{p.get('odds'):+.0f} · {p.get('stake')}" if p.get("odds") is not None else "—",
            "Score": "—" if p.get("result") == "Pending" else f"{p.get('away_score')}–{p.get('home_score')}",
            "Result": p.get("result"),
            "Profit (units)": "—" if p.get("result") == "Pending" else f"{p.get('profit_units'):+.2f}",
            "★": "★" if p.get("favorite") else "",
        } for p in shown_picks],
        hide_index=True, width="stretch",
    )
else:
    st.info("No bets marked yet." if bets_only else "No saved picks in this snapshot.")

with st.expander("Data health"):
    missing = [g for g in week_games if g.get("home_spread") is None]
    fit = ((power_meta.get("spend_fit") or {}).get("roster"))
    talent_fit = power_meta.get("talent_fit")
    health_rows = [
        ("Season", snapshot.get("season")),
        ("Feed last refreshed", snapshot.get("updated_at")),
        ("Games imported this refresh", snapshot.get("imported_count")),
        ("Betting-splits rows read", snapshot.get("splits_count")),
        ("Previous-season games cached", snapshot.get("history_events_count")),
        ("AP poll dated", snapshot.get("ap_date")),
        ("Model fit as of", power_meta.get("as_of")),
        ("Ranking comparison pool", f"{power_meta['ranking_population']} {power_meta.get('ranking_scope') or 'teams'}"
         if power_meta.get("ranking_population") is not None else None),
        ("Games needed to be rated", power_meta.get("min_games")),
        ("Model weeks reconstructed", power_meta.get("history_weeks_tracked")),
        ("Poll snapshots archived", snapshot.get("poll_history_weeks")),
        ("Spending figures loaded", len(power_meta.get("spend_board") or []) or None),
        ("Roster cost vs rating fit", f"{fit['points_per_doubling']} pts per doubling · R² {fit['r_squared']} · {fit['teams']} schools" if fit else None),
        ("Roster talent loaded", len(power_meta.get("talent_board") or []) or None),
        ("Roster talent vs rating fit", f"{talent_fit['slope']} pts per point of average rating · R² {talent_fit['r_squared']} · {talent_fit['teams']} schools" if talent_fit else None),
        ("Games shown this week", len(week_games)),
        ("Shown games with no market spread", ", ".join(f"{g['away']} at {g['home']}" for g in missing) if missing else "Every shown game has a provider line."),
    ]
    for label, value in health_rows:
        st.caption(f"**{label}:** {value if value not in (None, '') else '—'}")
    warnings = snapshot.get("warnings") or []
    if warnings:
        st.markdown("**Refresh warnings**")
        for warning in warnings:
            st.caption(warning)

st.caption("Lines, model leans, rankings, and picks are research context. Verify current information before making any decision.")
