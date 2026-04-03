-- ============================================
-- PGA +EV Betting System — Database Schema
-- Run this in the Supabase SQL Editor:
-- https://supabase.com/dashboard/project/idvxybbqdrrbxlmfzfwz/sql
-- ============================================

-- Players (canonical records)
CREATE TABLE IF NOT EXISTS players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL UNIQUE,
    dg_id TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Player aliases (cross-book name mapping)
CREATE TABLE IF NOT EXISTS player_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id UUID REFERENCES players(id) NOT NULL,
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    UNIQUE(source, source_name)
);
CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON player_aliases(source, source_name);

-- Book settlement rules
CREATE TABLE IF NOT EXISTS book_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book TEXT NOT NULL,
    market_type TEXT NOT NULL,
    tie_rule TEXT NOT NULL,
    wd_rule TEXT NOT NULL,
    dead_heat_method TEXT,
    notes TEXT,
    UNIQUE(book, market_type)
);

-- Seed book rules
INSERT INTO book_rules (book, market_type, tie_rule, wd_rule, dead_heat_method, notes) VALUES
    ('draftkings', 't20', 'dead_heat', 'void', 'standard', 'DK applies dead-heat reduction on placement ties'),
    ('draftkings', 't10', 'dead_heat', 'void', 'standard', NULL),
    ('draftkings', 't5', 'dead_heat', 'void', 'standard', NULL),
    ('draftkings', 'tournament_matchup', 'push', 'void', NULL, 'Ties push, WD voids'),
    ('draftkings', 'round_matchup', 'push', 'void', NULL, NULL),
    ('draftkings', '3_ball', 'dead_heat', 'void', 'standard', 'Ties split'),
    ('fanduel', 't20', 'dead_heat', 'void', 'standard', NULL),
    ('fanduel', 't10', 'dead_heat', 'void', 'standard', NULL),
    ('fanduel', 't5', 'dead_heat', 'void', 'standard', NULL),
    ('fanduel', 'tournament_matchup', 'push', 'void', NULL, NULL),
    ('fanduel', 'round_matchup', 'push', 'void', NULL, NULL),
    ('fanduel', '3_ball', 'dead_heat', 'void', 'standard', NULL),
    ('betonline', 't20', 'dead_heat', 'void', 'standard', NULL),
    ('betonline', 'tournament_matchup', 'push', 'void', NULL, NULL),
    ('betonline', 'round_matchup', 'push', 'void', NULL, NULL),
    ('betonline', '3_ball', 'dead_heat', 'void', 'standard', NULL),
    ('bovada', 't20', 'dead_heat', 'void', 'standard', NULL),
    ('bovada', 'tournament_matchup', 'push', 'void', NULL, NULL),
    ('bovada', 'round_matchup', 'push', 'void', NULL, NULL),
    ('bovada', '3_ball', 'dead_heat', 'void', 'standard', NULL)
ON CONFLICT (book, market_type) DO NOTHING;

-- Tournaments
CREATE TABLE IF NOT EXISTS tournaments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_name TEXT NOT NULL,
    dg_event_id TEXT,
    season INTEGER,
    start_date DATE NOT NULL,
    purse BIGINT NOT NULL,
    is_signature BOOLEAN DEFAULT FALSE,
    is_no_cut BOOLEAN DEFAULT FALSE,
    cut_line TEXT DEFAULT 'top_65_ties',
    putting_surface TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(dg_event_id, season)
);

-- Candidate bets (all +EV opportunities flagged)
CREATE TABLE IF NOT EXISTS candidate_bets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id UUID REFERENCES tournaments(id),
    scan_type TEXT NOT NULL,
    scan_timestamp TIMESTAMPTZ DEFAULT NOW(),
    market_type TEXT NOT NULL,
    player_id UUID REFERENCES players(id),
    player_name TEXT NOT NULL,
    opponent_id UUID REFERENCES players(id),
    opponent_name TEXT,
    opponent_2_id UUID REFERENCES players(id),
    opponent_2_name TEXT,
    round_number INTEGER,
    dg_prob REAL NOT NULL,
    book_consensus_prob REAL,
    your_prob REAL NOT NULL,
    best_book TEXT NOT NULL,
    best_odds_decimal REAL NOT NULL,
    best_odds_american TEXT,
    best_implied_prob REAL NOT NULL,
    raw_edge REAL NOT NULL,
    deadheat_adj REAL DEFAULT 0,
    edge REAL NOT NULL,
    kelly_fraction REAL,
    correlation_haircut REAL DEFAULT 1.0,
    suggested_stake REAL,
    all_book_odds JSONB,
    status TEXT DEFAULT 'pending',
    skip_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_candidates_tournament ON candidate_bets(tournament_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidate_bets(status);
CREATE INDEX IF NOT EXISTS idx_candidates_market ON candidate_bets(market_type);
CREATE INDEX IF NOT EXISTS idx_candidates_player ON candidate_bets(player_id);

-- Bets (actually placed)
CREATE TABLE IF NOT EXISTS bets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES candidate_bets(id),
    tournament_id UUID REFERENCES tournaments(id),
    market_type TEXT NOT NULL,
    player_id UUID REFERENCES players(id),
    player_name TEXT NOT NULL,
    opponent_id UUID REFERENCES players(id),
    opponent_name TEXT,
    opponent_2_id UUID REFERENCES players(id),
    opponent_2_name TEXT,
    round_number INTEGER,
    book TEXT NOT NULL,
    bet_timestamp TIMESTAMPTZ DEFAULT NOW(),
    is_live BOOLEAN DEFAULT FALSE,
    scanned_odds_decimal REAL,
    odds_at_bet_decimal REAL NOT NULL,
    odds_at_bet_american TEXT,
    implied_prob_at_bet REAL NOT NULL,
    your_prob REAL NOT NULL,
    edge REAL NOT NULL,
    stake REAL NOT NULL,
    correlation_haircut REAL DEFAULT 1.0,
    closing_odds_decimal REAL,
    closing_implied_prob REAL,
    clv REAL,
    outcome TEXT,
    settlement_rule TEXT,
    payout REAL,
    pnl REAL,
    actual_finish TEXT,
    opponent_finish TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bets_tournament ON bets(tournament_id);
CREATE INDEX IF NOT EXISTS idx_bets_market ON bets(market_type);
CREATE INDEX IF NOT EXISTS idx_bets_book ON bets(book);
CREATE INDEX IF NOT EXISTS idx_bets_outcome ON bets(outcome);
CREATE INDEX IF NOT EXISTS idx_bets_player ON bets(player_id);

-- Bankroll ledger
CREATE TABLE IF NOT EXISTS bankroll_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_date TIMESTAMPTZ DEFAULT NOW(),
    entry_type TEXT NOT NULL,
    amount REAL NOT NULL,
    bet_id UUID REFERENCES bets(id),
    running_balance REAL NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ledger_date ON bankroll_ledger(entry_date);

-- Odds snapshots (for CLV)
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tournament_id UUID REFERENCES tournaments(id),
    snapshot_type TEXT NOT NULL,
    snapshot_timestamp TIMESTAMPTZ DEFAULT NOW(),
    market_type TEXT NOT NULL,
    player_name TEXT NOT NULL,
    player_dg_id TEXT,
    opponent_name TEXT,
    round_number INTEGER,
    dg_prob REAL,
    book_odds JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_snapshots_tournament ON odds_snapshots(tournament_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_type ON odds_snapshots(snapshot_type);

-- ============================================
-- Analytical Views
-- ============================================

-- ROI by market type
CREATE OR REPLACE VIEW v_roi_by_market AS
SELECT
    market_type,
    COUNT(*) AS total_bets,
    SUM(stake) AS total_staked,
    SUM(pnl) AS total_pnl,
    ROUND((SUM(pnl) / NULLIF(SUM(stake), 0) * 100)::numeric, 2) AS roi_pct,
    ROUND((AVG(edge) * 100)::numeric, 2) AS avg_edge_pct,
    ROUND((AVG(clv) * 100)::numeric, 2) AS avg_clv_pct,
    COUNT(*) FILTER (WHERE outcome = 'win') AS wins,
    COUNT(*) FILTER (WHERE outcome = 'loss') AS losses
FROM bets
WHERE outcome IS NOT NULL
GROUP BY market_type;

-- ROI by book
CREATE OR REPLACE VIEW v_roi_by_book AS
SELECT
    book,
    COUNT(*) AS total_bets,
    SUM(stake) AS total_staked,
    SUM(pnl) AS total_pnl,
    ROUND((SUM(pnl) / NULLIF(SUM(stake), 0) * 100)::numeric, 2) AS roi_pct,
    ROUND((AVG(clv) * 100)::numeric, 2) AS avg_clv_pct
FROM bets
WHERE outcome IS NOT NULL
GROUP BY book;

-- ROI by edge tier
CREATE OR REPLACE VIEW v_roi_by_edge_tier AS
SELECT
    CASE
        WHEN edge >= 0.08 THEN '8%+'
        WHEN edge >= 0.05 THEN '5-8%'
        WHEN edge >= 0.03 THEN '3-5%'
        ELSE '<3%'
    END AS edge_tier,
    COUNT(*) AS total_bets,
    SUM(stake) AS total_staked,
    SUM(pnl) AS total_pnl,
    ROUND((SUM(pnl) / NULLIF(SUM(stake), 0) * 100)::numeric, 2) AS roi_pct,
    ROUND((AVG(clv) * 100)::numeric, 2) AS avg_clv_pct
FROM bets
WHERE outcome IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- CLV trend (weekly)
CREATE OR REPLACE VIEW v_clv_weekly AS
SELECT
    DATE_TRUNC('week', bet_timestamp) AS week,
    COUNT(*) AS bets,
    ROUND((AVG(clv) * 100)::numeric, 2) AS avg_clv_pct,
    ROUND(SUM(pnl)::numeric, 2) AS weekly_pnl,
    ROUND((AVG(edge) * 100)::numeric, 2) AS avg_edge_pct
FROM bets
WHERE clv IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Calibration check
CREATE OR REPLACE VIEW v_calibration AS
SELECT
    ROUND((your_prob * 20)::numeric) / 20 AS prob_bucket,
    COUNT(*) AS n,
    ROUND((AVG(your_prob) * 100)::numeric, 1) AS avg_predicted_pct,
    ROUND((AVG(CASE WHEN outcome = 'win' THEN 1.0 ELSE 0.0 END) * 100)::numeric, 1) AS actual_hit_pct
FROM bets
WHERE outcome IN ('win', 'loss')
GROUP BY 1
HAVING COUNT(*) >= 5
ORDER BY 1;

-- Bankroll curve
CREATE OR REPLACE VIEW v_bankroll_curve AS
SELECT
    entry_date,
    entry_type,
    amount,
    running_balance
FROM bankroll_ledger
ORDER BY entry_date;

-- Weekly exposure
CREATE OR REPLACE VIEW v_weekly_exposure AS
SELECT
    DATE_TRUNC('week', bet_timestamp) AS week,
    COUNT(*) AS bets_placed,
    SUM(stake) AS total_exposure,
    MAX(stake) AS largest_single_bet,
    COUNT(DISTINCT player_name) AS unique_players
FROM bets
GROUP BY 1
ORDER BY 1;
