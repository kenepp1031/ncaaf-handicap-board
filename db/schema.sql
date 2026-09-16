-- NCAAF handicap schema. Batch-pipeline architecture ported from NFL 2.0.

CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY,      -- ESPN numeric team id, as a string
    name TEXT,
    logo TEXT,
    fbs INTEGER NOT NULL DEFAULT 0,
    color TEXT,                    -- ESPN primary hex, no '#'
    alt_color TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,       -- ESPN event id
    season INTEGER NOT NULL,
    week INTEGER,
    week_type INTEGER,              -- ESPN season_type (2=regular, 3=postseason)
    game_date TEXT NOT NULL,        -- local date, YYYY-MM-DD
    kickoff TEXT NOT NULL,          -- ISO timestamp with offset
    status TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    neutral INTEGER NOT NULL DEFAULT 0,
    home_id TEXT NOT NULL,
    away_id TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    home_spread REAL,
    away_spread REAL,
    home_odds REAL,
    away_odds REAL,
    total REAL,
    odds_status TEXT,
    market_source TEXT,
    market_observed_at TEXT,
    venue_json TEXT                 -- raw ESPN venue block (name/address/indoor)
);
CREATE INDEX IF NOT EXISTS idx_games_season_week ON games(season, week);
CREATE INDEX IF NOT EXISTS idx_games_home ON games(home_id);
CREATE INDEX IF NOT EXISTS idx_games_away ON games(away_id);

CREATE TABLE IF NOT EXISTS weeks (
    season INTEGER NOT NULL,
    week_type INTEGER NOT NULL,
    number INTEGER NOT NULL,
    label TEXT,
    start_date TEXT,
    end_date TEXT,
    detail TEXT,
    PRIMARY KEY (season, week_type, number)
);

CREATE TABLE IF NOT EXISTS polls (
    team_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    poll_type TEXT NOT NULL,        -- 'cbs' | 'ap' | 'coaches' | 'combined'
    rank INTEGER,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (team_id, season, poll_type)
);

CREATE TABLE IF NOT EXISTS line_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    kickoff TEXT,
    home_spread REAL,
    total REAL,
    home_odds REAL,
    away_odds REAL,
    source TEXT,
    UNIQUE(game_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_line_history_game ON line_history(game_id, captured_at);

CREATE TABLE IF NOT EXISTS splits (
    game_id TEXT,
    team_key TEXT NOT NULL,         -- normalized team name (matches feeds.normal())
    month_day TEXT NOT NULL,
    spread REAL,
    odds REAL,
    handle_pct REAL,
    bets_pct REAL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (team_key, month_day)
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    country TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    admin1 TEXT,
    country_code TEXT,
    PRIMARY KEY (city, state, country)
);

CREATE TABLE IF NOT EXISTS weather (
    game_id TEXT PRIMARY KEY,
    temp_f REAL,
    wind_mph REAL,
    wind_gusts_mph REAL,
    precip_in REAL,
    rain_in REAL,
    snowfall_in REAL,
    weather_code INTEGER,
    weather_codes_json TEXT,
    forecast_time TEXT,
    status TEXT,
    alert_text TEXT,         -- outdoor-game-window severe-weather banner text
    lean_note TEXT,          -- "guides lean Under" text, wind/rain threshold note
    checked_at TEXT
);

CREATE TABLE IF NOT EXISTS nil_spend (
    school_key TEXT NOT NULL,       -- nil.py's key(name)
    season INTEGER NOT NULL,
    school_name TEXT,
    roster_cost INTEGER,
    athletic_expenses INTEGER,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (school_key, season)
);

CREATE TABLE IF NOT EXISTS talent (
    school_key TEXT NOT NULL,       -- talent.py's key(name)
    season INTEGER NOT NULL,
    school_name TEXT,
    rank INTEGER,
    points REAL,
    avg_rating REAL,
    players INTEGER,
    five_star INTEGER,
    four_star INTEGER,
    three_star INTEGER,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (school_key, season)
);

CREATE TABLE IF NOT EXISTS officiating_penalties (
    game_id TEXT PRIMARY KEY,
    home_penalties INTEGER,
    home_penalty_yards INTEGER,
    away_penalties INTEGER,
    away_penalty_yards INTEGER,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_ratings (
    team_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    as_of_date TEXT NOT NULL,
    rating REAL,
    offense REAL,
    defense REAL,
    games INTEGER,
    offense_rank INTEGER,
    defense_rank INTEGER,
    offense_grade TEXT,
    defense_grade TEXT,
    combined_rank INTEGER,
    ap_rank INTEGER,
    blended_rating REAL,
    power_rank INTEGER,
    trend TEXT,                     -- integer as text, or 'new'
    ranking_scope TEXT,
    ranking_population INTEGER,
    PRIMARY KEY (team_id, season, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_team_ratings_asof ON team_ratings(season, as_of_date);

CREATE TABLE IF NOT EXISTS game_notes (
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,             -- 'home' | 'away'
    note_order INTEGER NOT NULL,
    note_text TEXT NOT NULL,
    PRIMARY KEY (game_id, side, note_order)
);

CREATE TABLE IF NOT EXISTS projections (
    game_id TEXT PRIMARY KEY,
    home_points REAL,
    away_points REAL,
    fair_home_spread REAL,
    projected_total REAL,
    lean_home_spread REAL,
    lean_source TEXT,
    lean_side TEXT,
    home_edge_points REAL,
    lean_edge_points REAL,
    total_edge_points REAL,
    sample_games INTEGER,
    confidence TEXT,
    confidence_detail TEXT,
    spend_margin_shift REAL,
    officiating_margin_shift REAL,
    talent_margin_shift REAL,
    pooled_fcs_json TEXT,           -- which side(s), if any, resolved to the pooled FCS identity
    generated_at TEXT
);

CREATE TABLE IF NOT EXISTS backtest_log (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER,
    predicted_spread REAL,
    closing_spread REAL,
    error_spread REAL,
    predicted_total REAL,
    closing_total REAL,
    error_total REAL,
    ats_result TEXT,      -- win | loss | push | NULL
    ou_result TEXT,        -- over | under | push | NULL
    confidence TEXT
);
