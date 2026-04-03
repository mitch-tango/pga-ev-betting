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
    "matchup":              {"dg": 0.45, "books": 0.55},   # Backtest optimal: 40-50% DG
    "three_ball":           {"dg": 0.45, "books": 0.55},   # Same as matchup (same market dynamics)
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
# Calibrated from backtests:
#   T5: raised to 25% due to ~20% dead-heat reduction (effectively skip most T5 bets)
#   T10: raised to 5% due to ~3% dead-heat reduction
#   T20: 3% threshold holds (only ~2.3% DH impact)
#   Matchups: raised to 5% per backtest (better ROI at higher threshold)
MIN_EDGE = {
    "win":                0.05,   # 5% — hardest market to beat
    "t5":                 0.25,   # 25% — effectively skip (dead-heat kills edge)
    "t10":                0.05,   # 5% — raised for dead-heat buffer
    "t20":                0.03,   # 3% — minimal dead-heat impact
    "make_cut":           0.03,
    "tournament_matchup": 0.05,   # 5% — raised per matchup backtest
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
# Calibrated from backtest (21 events, 2025-2026):
#   T5:  28.4% of winners face DH → ~20% avg payout reduction → AVOID or high threshold
#   T10: 4.3% face DH → ~3% avg payout reduction
#   T20: 2.8% face DH → ~2.3% avg payout reduction
DEADHEAT_AVG_REDUCTION = {
    "t5":  0.20,    # ~20% — T5 is significantly impacted by dead-heat
    "t10": 0.03,    # ~3%
    "t20": 0.023,   # ~2.3%
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
