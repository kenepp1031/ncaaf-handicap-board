"""SQLite connection + schema bootstrap for the batch pipeline."""
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = APP_DIR / "ncaaf_handicap.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with connect() as con:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        existing = {r["name"] for r in con.execute("PRAGMA table_info(teams)")}
        for col in ("color", "alt_color"):
            if col not in existing:
                con.execute(f"ALTER TABLE teams ADD COLUMN {col} TEXT")
        # CREATE TABLE IF NOT EXISTS won't widen a table that already exists, so
        # grading columns added after a DB was first built need an explicit ALTER.
        logged = {r["name"] for r in con.execute("PRAGMA table_info(backtest_log)")}
        for col, decl in (("graded_spread", "REAL"), ("edge_points", "REAL"),
                          ("pooled_fcs", "INTEGER NOT NULL DEFAULT 0"), ("generated_at", "TEXT"),
                          ("manual_margin_shift", "REAL"), ("ats_result_model", "TEXT"),
                          ("injury_margin_shift", "REAL")):
            if col not in logged:
                con.execute(f"ALTER TABLE backtest_log ADD COLUMN {col} {decl}")
        # Manual adjustments (manual_adjustments.csv) and the QB-injury prior are stored
        # beside the model's own numbers so the record can be read with and without them.
        for table in ("projections", "projection_snapshots"):
            cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col in ("manual_margin_shift", "injury_margin_shift"):
                if col not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
