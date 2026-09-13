"""Public, mobile-friendly companion for the NCAAF handicapping board.

This app deliberately reads the checked-in JSON snapshot (data/web_snapshot.json)
rather than the Windows desktop UI or its live caches. That makes it suitable
for Streamlit Community Cloud: the site can stay open even when the authoring
PC is off. It never touches dashboard.py, app.js, storage.py, or any other
file the desktop app uses, and it has no write/editing capability.

Refresh the snapshot with `python export_web_snapshot.py` after using the
desktop app, then commit+push data/web_snapshot.json — see README_WEB.md.
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
    return f"{team} {spread_text(line)}"


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
weeks = sorted({e["week"] for e in events if e.get("week") is not None})

with st.sidebar:
    st.header("Board controls")
    week = st.selectbox("Week", weeks, index=len(weeks) - 1 if weeks else 0) if weeks else None
    show_model = st.toggle("Show model lean", value=True)
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

st.subheader(f"Week {week} matchups" if week is not None else "This week's matchups")
if not week_games:
    st.info("No Top 50 matchups in this snapshot's schedule.")
for game in week_games:
    home, away = game["home"], game["away"]
    with st.container(border=True):
        st.caption(kickoff_text(game.get("kickoff")))
        left, middle, right = st.columns((4, 3, 4))
        with left:
            st.markdown(f"### {away}")
            if game.get("away_combined"):
                st.caption(f"Poll #{game['away_combined']}")
            st.caption(f"Record: {game.get('away_record') or '—'}")
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
            if game.get("weather_alert"):
                st.caption(f"⚠️ {game['weather_alert']}")
        with right:
            st.markdown(f"### {home}")
            if game.get("home_combined"):
                st.caption(f"Poll #{game['home_combined']}")
            st.caption(f"Record: {game.get('home_record') or '—'}")

st.subheader("Combined rankings")
if rankings:
    ranking_rows = [
        {
            "Rank": row.get("rank"),
            "Team": row.get("team"),
            "Rating": row.get("rating"),
            "AP rank": row.get("ap_rank"),
            "Combined poll": row.get("combined_rank"),
        }
        for row in rankings
    ]
    st.dataframe(ranking_rows, hide_index=True, width="stretch")
elif top50:
    st.dataframe(
        [{"Rank": row.get("rank"), "Team": row.get("team")} for row in top50],
        hide_index=True,
        width="stretch",
    )
else:
    st.info("No rankings available in this snapshot.")

st.caption("Lines, model leans, rankings, and picks are research context. Verify current information before making any decision.")
