"""
PGA +EV Betting System — Configuration

All constants, thresholds, blend weights, and sizing parameters.
Calibrated from OAD backtest (278 events, 35,064 player-events, 2020-2026)
and matchup/dead-heat backtests (99-101 events, 19,996 records, 2022-2026).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- DG API ---
DG_API_KEY = os.getenv("DG_API_KEY")
DG_BASE_URL = "https://feeds.datagolf.com"
RATE_LIMIT_DELAY = 1.5  # seconds between API calls
API_TIMEOUT = 30  # seconds
API_MAX_RETRIES = 3

# --- Kalshi ---
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_RATE_LIMIT_DELAY = 0.1  # 100ms between calls (conservative vs 20/sec limit)
KALSHI_MIN_OPEN_INTEREST = 100  # Minimum OI to include in consensus
KALSHI_MAX_SPREAD = 0.05  # Max bid-ask spread ($0.05) — wider = illiquid
KALSHI_SERIES_TICKERS = {
    "win": "KXPGATOUR",
    "t10": "KXPGATOP10",
    "t20": "KXPGATOP20",
    "tournament_matchup": "KXPGAH2H",
}
# TODO: Polymarket — add POLYMARKET_BASE_URL, POLYMARKET_CLOB_URL, book weights here
# Polymarket covers outrights + top-N but NOT matchups. Gamma API for discovery, CLOB for prices.

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# --- Discord ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# --- Blend Weights ---
# Win/placement weights from OAD backtest (278 events, 2020-2026).
# Matchup weights from 99-event backtest (19,996 records, 2022-2026).
BLEND_WEIGHTS = {
    "win":                  {"dg": 0.35, "books": 0.65},
    "placement":            {"dg": 0.55, "books": 0.45},   # T10, T20
    "make_cut":             {"dg": 0.35, "books": 0.65},   # Binary outcome like win
    "matchup":              {"dg": 0.20, "books": 0.80},   # 99-event backtest: 20% DG optimal by log-loss (full-distribution derivation), ROI 2.5%
    "three_ball":           {"dg": 1.0,  "books": 0.0},    # No book consensus data yet
    "signature_win":        {"dg": 0.15, "books": 0.85},
    "signature_placement":  {"dg": 0.40, "books": 0.60},
    "deep_field":           {"dg": 1.0,  "books": 0.0},    # Rank 61+
}

# --- Book Weights (for building book consensus) ---
# Win/MC: sharp 2x, retail 1x
# Placement: equal weight (sharp premium dropped — DK/FD outperform BetOnline)
BOOK_WEIGHTS = {
    "win": {
        "pinnacle": 2, "betcris": 2, "betonline": 2,
        "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        "kalshi": 2,  # Sharp — prediction markets are efficient
    },
    "placement": {
        "betonline": 1, "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        "kalshi": 1,  # Equal weight for placement
    },
    "make_cut": {
        "pinnacle": 2, "betcris": 2, "betonline": 2,
        "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        # No kalshi — they don't offer make_cut
    },
    # Matchups: equal-weighted average in edge.py (no weight dict needed),
    # but listed here for reference when Start outrights are added.
}

# --- Edge Thresholds ---
# Calibrated from backtests (101 events, 2022-2026):
#   T5:  REMOVED — 19.9% DH rate, 13.6% payout reduction, -EV at any realistic edge
#   T10: 6.6% DH rate, 4.4% reduction -> 6% threshold (raised from 5%)
#   T20: 4.7% DH rate, 3.8% reduction -> 6% threshold (raised from 5%)
#   Matchups: ROI consistent at 2.3-3.1% across thresholds, use 5%
MIN_EDGE = {
    "win":                0.05,   # 5% — hardest market to beat
    "t10":                0.06,   # 6% — 4.4% DH impact + buffer
    "t20":                0.06,   # 6% — 3.8% DH impact + buffer
    "make_cut":           0.03,   # 3% — no dead-heat on binary market
    "tournament_matchup": 0.05,   # 5% — per matchup backtest
    "round_matchup":      0.05,   # 5%
    "3_ball":             0.05,   # 5%
    "live":               0.08,   # 8% — stale book odds (Amendment #6)
}

# --- Kelly Sizing ---
KELLY_FRACTION = 0.25         # Quarter-Kelly
MAX_SINGLE_BET_PCT = 0.03    # 3% max single bet as % of bankroll
MAX_WEEKLY_EXPOSURE_PCT = 0.15   # 15% max total weekly exposure
MAX_PLAYER_EXPOSURE_PCT = 0.05   # 5% max exposure on one player
MAX_TOURNAMENT_EXPOSURE_PCT = 0.08  # 8% max per tournament

# Correlation haircut (Amendment #1): successive bets on the same player
# get reduced stakes to account for correlated outcomes.
# Index = number of prior bets on this player (0 = first bet = full Kelly)
CORRELATION_HAIRCUT = [1.0, 0.5, 0.25, 0.125]

# --- Dead-Heat (Amendment #2) ---
# Average dead-heat reduction by placement market.
# Calibrated from backtest (101 events, 2022-2026):
#   T5:  REMOVED — 19.9% DH rate, 13.6% reduction, -EV
#   T10: 6.6% DH rate -> 4.4% avg payout reduction
#   T20: 4.7% DH rate -> 3.8% avg payout reduction
DEADHEAT_AVG_REDUCTION = {
    "t10": 0.044,   # ~4.4%
    "t20": 0.038,   # ~3.8%
}

# Books exempt from dead-heat adjustment (binary contract payout, no DH reduction)
KALSHI_NO_DEADHEAT_BOOKS = {"kalshi"}

# --- Signature Event ---
SIGNATURE_PURSE_THRESHOLD = 20_000_000

# --- Deep Field ---
DEEP_FIELD_RANK_THRESHOLD = 61  # Players ranked 61+ use 100% DG

# --- Market Type Classification ---
PLACEMENT_MARKETS = {"win", "t10", "t20", "make_cut"}
MATCHUP_MARKETS = {"tournament_matchup", "round_matchup"}
THREE_BALL_MARKETS = {"3_ball"}
ALL_MARKETS = PLACEMENT_MARKETS | MATCHUP_MARKETS | THREE_BALL_MARKETS
