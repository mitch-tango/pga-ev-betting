"""
PGA +EV Betting System — Configuration

All constants, thresholds, blend weights, and sizing parameters.
Calibrated from OAD backtest (278 events, 35,064 player-events, 2020-2026).
Matchup weights are provisional (100% DG) until matchup backtest determines optimal.
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

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# --- Blend Weights ---
# Win/placement weights from OAD backtest (278 events, 2020-2026).
# Matchup/3-ball weights are 100% DG until backtest determines optimal (Amendment #7).
BLEND_WEIGHTS = {
    "win":                  {"dg": 0.35, "books": 0.65},
    "placement":            {"dg": 0.55, "books": 0.45},   # T5, T10, T20
    "make_cut":             {"dg": 0.35, "books": 0.65},   # Binary outcome like win
    "matchup":              {"dg": 1.0,  "books": 0.0},    # 75-event backtest: 100% DG tied for best ROI (2.4%)
    "three_ball":           {"dg": 1.0,  "books": 0.0},    # Same as matchup
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
        "draftkings": 1, "fanduel": 1, "bovada": 1,
    },
    "placement": {
        "betonline": 1, "draftkings": 1, "fanduel": 1, "bovada": 1,
    },
    "make_cut": {
        "pinnacle": 2, "betcris": 2, "betonline": 2,
        "draftkings": 1, "fanduel": 1, "bovada": 1,
    },
}

# --- Edge Thresholds ---
# Calibrated from backtests (80 events, 2022-2026):
#   T5:  17.3% DH rate, ~11.8% payout reduction → effectively skip
#   T10: 5.5% DH rate, ~3.6% reduction → 5% threshold covers it
#   T20: 4.3% DH rate, ~3.5% reduction → raised to 5% (was 3%)
#   Matchups: ROI consistent at 2.4% across 3-5% thresholds, use 5% for safety
MIN_EDGE = {
    "win":                0.05,   # 5% — hardest market to beat
    "t5":                 0.25,   # 25% — effectively skip (dead-heat kills edge)
    "t10":                0.05,   # 5% — 3.6% DH buffer
    "t20":                0.05,   # 5% — raised from 3% (3.5% DH impact at scale)
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
# Calibrated from backtest (80 events, 2022-2026):
#   T5:  17.3% DH rate → ~11.8% avg payout reduction → AVOID
#   T10: 5.5% DH rate → ~3.6% avg payout reduction
#   T20: 4.3% DH rate → ~3.5% avg payout reduction
DEADHEAT_AVG_REDUCTION = {
    "t5":  0.118,   # ~11.8% — T5 is significantly impacted
    "t10": 0.036,   # ~3.6%
    "t20": 0.035,   # ~3.5%
}

# --- Signature Event ---
SIGNATURE_PURSE_THRESHOLD = 20_000_000

# --- Deep Field ---
DEEP_FIELD_RANK_THRESHOLD = 61  # Players ranked 61+ use 100% DG

# --- Market Type Classification ---
PLACEMENT_MARKETS = {"win", "t5", "t10", "t20", "make_cut"}
MATCHUP_MARKETS = {"tournament_matchup", "round_matchup"}
THREE_BALL_MARKETS = {"3_ball"}
ALL_MARKETS = PLACEMENT_MARKETS | MATCHUP_MARKETS | THREE_BALL_MARKETS
