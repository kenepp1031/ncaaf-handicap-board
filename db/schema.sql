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

-- One row per observed change in a side's money/ticket share, so a sudden
-- handle jump (someone loading up) can be seen between refreshes.
CREATE TABLE IF NOT EXISTS splits_history (
    team_key TEXT NOT NULL,
    month_day TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    handle_pct REAL,
    bets_pct REAL,
    PRIMARY KEY (team_key, month_day, captured_at)
);

-- Kalshi winner-market money per game: real dollars takers put on each side.
CREATE TABLE IF NOT EXISTS kalshi (
    game_id TEXT PRIMARY KEY,
    event_ticker TEXT,
    home_price REAL,                -- last trade, dollars per $1 payout = implied win chance
    away_price REAL,
    home_dollars REAL,
    away_dollars REAL,
    home_dollars_24h REAL,
    away_dollars_24h REAL,
    biggest_dollars REAL,
    biggest_side TEXT,              -- 'home' | 'away'
    biggest_at TEXT,
    captured_at TEXT NOT NULL
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

-- Per-team box score from ESPN's game summary. One row per (game, side);
-- a finished game's box never changes, so ingest.box_scores only fetches misses.
CREATE TABLE IF NOT EXISTS box_scores (
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,             -- 'home' | 'away'
    team_id TEXT NOT NULL,
    plays INTEGER,                  -- pass attempts + rush attempts (sacks count as rushes in CFB)
    total_yards INTEGER,
    pass_attempts INTEGER,
    rush_attempts INTEGER,
    first_downs INTEGER,
    third_down_conv INTEGER,
    third_down_att INTEGER,
    turnovers INTEGER,
    possession_seconds INTEGER,
    qb_id TEXT,                     -- player with the most pass attempts
    qb_name TEXT,
    qb_attempts INTEGER,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (game_id, side)
);
CREATE INDEX IF NOT EXISTS idx_box_scores_team ON box_scores(team_id);

-- Per-team play-by-play efficiency from the same ESPN summary (drives -> plays).
-- One row per (game, side). "ng" columns exclude garbage time (lead over 38 in
-- the 2nd quarter, 28 in the 3rd, 22 in the 4th). Permanent cache, misses only.
CREATE TABLE IF NOT EXISTS play_stats (
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,             -- 'home' | 'away'
    team_id TEXT NOT NULL,
    plays INTEGER,                  -- scrimmage plays (rush, pass, sack); no kicks/penalties
    yards INTEGER,
    successes INTEGER,              -- 50% of distance on 1st, 70% on 2nd, all of it on 3rd/4th
    explosives INTEGER,             -- rush 12+ or pass 16+
    turnovers INTEGER,
    rush_plays INTEGER,
    rush_yards INTEGER,
    rush_successes INTEGER,
    pass_plays INTEGER,
    pass_yards INTEGER,
    pass_successes INTEGER,
    plays_ng INTEGER,
    yards_ng INTEGER,
    successes_ng INTEGER,
    explosives_ng INTEGER,
    turnovers_ng INTEGER,
    drives INTEGER,
    drive_points INTEGER,           -- points scored by this offense on its drives (TD 7, FG 3)
    captured_at TEXT NOT NULL,
    PRIMARY KEY (game_id, side)
);
CREATE INDEX IF NOT EXISTS idx_play_stats_team ON play_stats(team_id);

-- covers.com injury report. `injuries` is the current snapshot (replaced each
-- run); `injury_history` appends a row whenever a player's status or date changes,
-- so a game can be judged on what was listed before it kicked off.
CREATE TABLE IF NOT EXISTS injuries (
    team_id TEXT NOT NULL,
    player TEXT NOT NULL,           -- as listed: "J. Sayin"
    pos TEXT,
    status TEXT,                    -- Out | Doubtful | Questionable | Probable | Day-To-Day ...
    injury TEXT,
    reported TEXT,                  -- covers' date text, "Sun, Sep 27"
    note TEXT,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (team_id, player)
);
CREATE TABLE IF NOT EXISTS injury_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    player TEXT NOT NULL,
    pos TEXT,
    status TEXT,
    injury TEXT,
    reported TEXT,
    note TEXT,
    captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_injury_history_team ON injury_history(team_id, captured_at);

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
    manual_margin_shift REAL,       -- your hand (manual_adjustments.csv): home nudge minus away nudge, in points
    injury_margin_shift REAL,       -- starting-QB injury prior (ratings/injury_prior.py), points toward home
    pooled_fcs_json TEXT,           -- which side(s), if any, resolved to the pooled FCS identity
    generated_at TEXT
);

-- Append-only record of every projection made BEFORE kickoff. `projections` is a
-- single current-view row per game and gets overwritten each run, so it cannot
-- answer "what did we actually say on Friday?". This can. The grader reads the
-- last snapshot captured before kickoff and nothing else, so a backfill run can
-- never launder hindsight into the record.
CREATE TABLE IF NOT EXISTS projection_snapshots (
    game_id TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    kickoff TEXT,
    fair_home_spread REAL,
    lean_home_spread REAL,
    projected_total REAL,
    lean_side TEXT,
    lean_edge_points REAL,
    home_edge_points REAL,
    sample_games INTEGER,
    confidence TEXT,
    market_home_spread REAL,   -- the line on the board when this snapshot was taken
    pooled_fcs_json TEXT,
    manual_margin_shift REAL,  -- points of your hand inside fair/lean (0 = model alone); lets the grader score both
    injury_margin_shift REAL,  -- points of the QB-injury prior inside fair/lean
    PRIMARY KEY (game_id, generated_at)
);
CREATE INDEX IF NOT EXISTS idx_proj_snap_game ON projection_snapshots(game_id, generated_at);

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
    confidence TEXT,
    graded_spread REAL,   -- the number actually bet (lean_home_spread), not the raw model line
    edge_points REAL,     -- graded_spread vs closing_spread; the bucket this pick belongs in
    pooled_fcs INTEGER NOT NULL DEFAULT 0,  -- 1 = an FCS side was pooled; excluded from headline accuracy
    generated_at TEXT,    -- when the graded forecast was made (always < kickoff)
    manual_margin_shift REAL,   -- your hand inside graded_spread; report.py scores the pick with and without it
    ats_result_model TEXT,      -- ATS result the model alone would have had (same as ats_result when no hand)
    injury_margin_shift REAL    -- QB-injury prior inside graded_spread; report.py scores with and without it too
);

-- "Sharp side" log: a game/side is written the first run it qualifies (DraftKings
-- money share beats ticket share by SHARP_GAP or more) with the line on the board at
-- that moment, and is never deleted, so the record is what you could actually have bet.
CREATE TABLE IF NOT EXISTS sharp_picks (
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,             -- 'home' | 'away'
    season INTEGER,
    week INTEGER,
    first_seen TEXT NOT NULL,       -- when it first qualified
    spread_at_pick REAL,            -- that side's spread when first seen (negative = favorite)
    handle_pct REAL,                -- money share at first sighting
    bets_pct REAL,                  -- ticket share at first sighting
    gap REAL,                       -- handle - bets at first sighting
    line_move REAL,                 -- points the line had moved toward this side by first sighting
    model_agrees INTEGER,           -- 1 if the model lean (1+ pt) was on the same side
    last_handle_pct REAL,           -- latest capture, for display
    last_bets_pct REAL,
    still_qualifies INTEGER NOT NULL DEFAULT 1,
    closing_spread REAL,            -- this side's closing spread, filled at grading
    ats_result TEXT,                -- win | loss | push vs the closing line
    ats_result_at_pick TEXT,        -- vs the line at first sighting
    su_result TEXT,                 -- win | loss
    PRIMARY KEY (game_id, side)
);

-- 247Sports transfer portal, per player, from each FBS team's portal page.
-- direction 'in' = joined this team, 'out' = left it. Refreshed weekly.
CREATE TABLE IF NOT EXISTS transfers (
    season INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    direction TEXT NOT NULL,        -- 'in' | 'out'
    player_key INTEGER NOT NULL,    -- 247Sports player key
    player TEXT,
    pos TEXT,
    rating REAL,                    -- 247 composite (transfer rating when given, else high-school)
    stars INTEGER,
    status TEXT,                    -- Enrolled | Committed | Entered | ...
    from_school TEXT,
    to_school TEXT,
    transfer_date TEXT,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (season, team_id, direction, player_key)
);
