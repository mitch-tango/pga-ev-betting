"""
PGA +EV Betting System — Configuration

All constants, thresholds, blend weights, and sizing parameters.
Calibrated from OAD backtest (278 events, 35,064 player-events, 2020-2026)
and matchup/dead-heat backtests (99-101 events, 19,996 records, 2022-2026).
"""

import os
from dotenv import load_dotenv

load_dotenv()


def env_flag(name: str, default: str = "0") -> bool:
    """Parse an environment variable as a boolean flag.

    Returns True for "1", "true", "yes" (case-insensitive).
    Returns False for everything else including "0", "false", "no", "".
    """
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


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

# --- Polymarket ---
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_RATE_LIMIT_DELAY = 0.1  # 100ms between calls (conservative vs 1,500 req/10s)
POLYMARKET_MIN_VOLUME = 100  # Minimum market volume to include
POLYMARKET_MAX_SPREAD_ABS = 0.10  # Absolute spread ceiling
POLYMARKET_MAX_SPREAD_REL = 0.15  # Relative spread factor
POLYMARKET_FEE_RATE = 0.002  # Taker fee applied to ask price for bettable cost
POLYMARKET_GOLF_TAG_ID = os.getenv("POLYMARKET_GOLF_TAG_ID", "100219")
POLYMARKET_MARKET_TYPES = {"win": "winner", "t10": "top-10", "t20": "top-20"}
POLYMARKET_ENABLED = env_flag("POLYMARKET_ENABLED", "1")  # On by default (no auth needed)

# --- ProphetX ---
PROPHETX_BASE_URL = "https://www.prophetx.co"
PROPHETX_RATE_LIMIT_DELAY = 0.1  # Conservative (rate limits undocumented)
PROPHETX_MIN_OPEN_INTEREST = 100  # Minimum OI threshold
PROPHETX_MAX_SPREAD = 0.05  # Max bid-ask spread
PROPHETX_ENABLED = env_flag("PROPHETX_ENABLED", "1")  # On by default (public API, no auth needed)

# --- Betsperts Golf ---
BETSPERTS_BASE_URL = "https://api.betspertsgolf.com"
BETSPERTS_SESSION_KEY = os.getenv("BETSPERTS_SESSION_KEY")
BETSPERTS_RATE_LIMIT_DELAY = 1.0  # Conservative (rate limits undocumented)
BETSPERTS_ENABLED = env_flag("BETSPERTS_ENABLED", "1")

# --- Course-Fit (Betsperts) ---
COURSEFIT_MIN_ROUNDS = 20  # Minimum baseline-window rounds to trust signal
# Course profiles are defined in src/core/coursefit.py (COURSE_PROFILES dict
# in config can override/extend the built-in profiles)

# --- Expert Picks ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EXPERT_PICKS_ENABLED = env_flag("EXPERT_PICKS_ENABLED", "1")
EXPERT_YOUTUBE_CHANNELS = {
    "rick_gehman": {
        "channel_query": "Rick Gehman golf",
        "search_terms": ["picks", "preview", "betting", "DFS"],
    },
    "pat_mayo": {
        "channel_query": "Pat Mayo golf",
        "search_terms": ["golf picks", "fantasy golf", "masters"],
    },
    "betsperts": {
        "channel_query": "Betsperts Golf",
        "search_terms": ["picks", "preview", "betting"],
    },
}

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# --- Discord ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_ALERT_CHANNEL_ID = int(os.getenv("DISCORD_ALERT_CHANNEL_ID", "0"))
DISCORD_ALERT_ROLE_ID = int(os.getenv("DISCORD_ALERT_ROLE_ID", "0"))  # Role to @mention for high-edge alerts

# --- Alert Schedule ---
# Times are US Eastern. Pre-tournament scan runs day before (Wednesday).
# Pre-round scans run each morning Thu-Sun.
ALERT_PRETOURNAMENT_HOUR = 18   # 6 PM ET Wednesday
ALERT_PREROUND_HOUR = 7        # 7 AM ET Thu-Sun
ALERT_CLOSING_HOUR = 6         # 6 AM ET Thu-Sun — closing-odds capture (CLV)
ALERT_SETTLEMENT_HOUR = 22     # 10 PM ET Thu-Sun
ALERT_HIGH_EDGE_THRESHOLD = 0.08  # 8%+ edge gets @role mention
ALERT_ENABLED = bool(os.getenv("DISCORD_ALERT_CHANNEL_ID", ""))

# --- Live Monitoring ---
LIVE_MONITOR_INTERVAL_MIN = 15    # Minutes between live scans during rounds
LIVE_MONITOR_START_HOUR = 8      # Start monitoring at 8 AM ET
LIVE_MONITOR_END_HOUR = 19       # Stop monitoring at 7 PM ET
LIVE_MONITOR_AUTOSTART = True    # Auto-start live monitor on bot boot during tournament hours (Thu-Sun, 8AM-7PM ET)

# --- Blend Weights ---
# Win/placement weights from OAD backtest (278 events, 2020-2026).
# Matchup weights from 99-event backtest (19,996 records, 2022-2026).
# Temporal stability validated: only tranche splits that are consistent
# across 2020-2022 vs 2023-2026 are implemented.
BLEND_WEIGHTS = {
    "win":                  {"dg": 0.35, "books": 0.65},   # Temporally unstable by tranche — keep global
    "placement":            {"dg": 0.55, "books": 0.45},   # T10/T20 fallback (when tranche unknown)
    "make_cut":             {"dg": 0.80, "books": 0.20},   # Raised from 0.35 — DG dominates (ALL stable: 75%→80% across periods)
    "matchup":              {"dg": 0.20, "books": 0.80},   # Global fallback (when tranche unknown)
    "three_ball":           {"dg": 1.0,  "books": 0.0},    # No book consensus data yet
    "signature_win":        {"dg": 0.15, "books": 0.85},
    "signature_placement":  {"dg": 0.40, "books": 0.60},
    "deep_field":           {"dg": 1.0,  "books": 0.0},    # Rank 61+
}

# --- Tranche-Specific Blend Weights ---
# Only implemented where temporally stable (consistent across 2020-2022 vs 2023-2026).
#
# Tranche thresholds (DG win probability):
#   favorite: >= 5%  |  mid: 1-5%  |  longshot: < 1%
TRANCHE_THRESHOLDS = {
    "favorite": 0.05,
    "mid":      0.01,
}

# Placement (T10/T20): DG dominates, especially for favorites.
# Revalidated 2026-04-07 with corrected make_cut de-vig (31K+ player-events).
# Favorites at 100% DG: strongly confirmed (monotonic improvement to 100%).
# Mid at 45%: T10 optimal=40%, T20 optimal=75%, split conservatively.
# Longshots at 45%: T10 optimal=40%, T20 optimal=50%, midpoint holds.
PLACEMENT_TRANCHE_WEIGHTS = {
    "favorite": {"dg": 1.00, "books": 0.00},  # Confirmed: monotonic to 100% both T10/T20
    "mid":      {"dg": 0.45, "books": 0.55},  # Was 0.55; T10=40%, T20=75%, conservative split
    "longshot": {"dg": 0.45, "books": 0.55},  # Unchanged: T10=40%, T20=50%, midpoint
}

# Make-cut: from 101-event backtest (13,296 player-events, 2020-2026).
# Revalidated 2026-04-07 with event-specific expected_outcomes (DG model sum).
# Favorites: 85% DG (was global 80%). Mid: 70% DG (was 80%). Longshot: 80% (unchanged).
MAKE_CUT_TRANCHE_WEIGHTS = {
    "favorite": {"dg": 0.85, "books": 0.15},  # N=390; optimal=85%, was 80% global
    "mid":      {"dg": 0.70, "books": 0.30},  # N=4,671; clear optimum, was 80% global
    "longshot": {"dg": 0.80, "books": 0.20},  # N=8,235; matches current global
}

# Matchups: from 99-event backtest (19,901 records, 2022-2026).
# Tranche = higher-ranked player's DG win probability.
MATCHUP_TRANCHE_WEIGHTS = {
    "favorite": {"dg": 0.60, "books": 0.40},  # N=1,452; DG far more informative for top players
    "mid":      {"dg": 0.30, "books": 0.70},  # N=10,988; slight DG edge
    "longshot": {"dg": 0.00, "books": 1.00},  # N=7,461; DG adds noise
}

# --- Book Weights (for building book consensus) ---
# Win/MC: sharp 2x, retail 1x
# Placement: equal weight (sharp premium dropped — DK/FD outperform BetOnline)
BOOK_WEIGHTS = {
    "win": {
        "pinnacle": 2, "betcris": 2, "betonline": 2,
        "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        "kalshi": 2,  # Sharp — prediction markets are efficient
        "polymarket": 1, "prophetx": 1,
    },
    "placement": {
        "betonline": 1, "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        "kalshi": 1,  # Equal weight for placement
        "polymarket": 1, "prophetx": 1,
    },
    "make_cut": {
        "pinnacle": 2, "betcris": 2, "betonline": 2,
        "draftkings": 1, "fanduel": 1, "bovada": 1, "start": 1,
        # No kalshi — they don't offer make_cut
        "prophetx": 1,  # Polymarket doesn't offer make_cut
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
    "live":               0.04,   # 4% — alert threshold (lowered from 8% for visibility)
}

# Display floor for scan output. Candidates between DISPLAY_MIN_EDGE and the
# market's MIN_EDGE are shown for visibility but flagged as sub-threshold
# (no Kelly stake computed, surfaced as info-only in the report).
# Anything below DISPLAY_MIN_EDGE is dropped entirely — too noisy to be useful.
DISPLAY_MIN_EDGE = 0.03

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

# Books exempt from dead-heat adjustment, per market type.
# Mirrors the `book_rules` table (source of truth): any book whose
# tie_rule is 'win' on a given market type pays ties in full and should
# skip the dead-heat haircut on edges against that book's line for that
# market. Market-aware because BetMGM and Pinnacle pay ties in full on
# placement markets (T5/T10/T20) but still apply dead-heat to 3-balls,
# so they can't be added to a flat global set.
# Keep in sync with schema.sql / book_rules by hand until we drive this
# from the DB directly.
NO_DEADHEAT_BOOKS_BY_MARKET: dict[str, set[str]] = {
    "t5":  {"kalshi", "polymarket", "prophetx", "betmgm", "pinnacle"},
    "t10": {"kalshi", "polymarket", "prophetx", "betmgm", "pinnacle"},
    "t20": {"kalshi", "polymarket", "prophetx", "betmgm", "pinnacle"},
}

# Legacy flat set: union of every book exempt in at least one placement
# market. Kept for back-compat with call sites that don't know the
# market type. New code should prefer NO_DEADHEAT_BOOKS_BY_MARKET.
NO_DEADHEAT_BOOKS: set[str] = set().union(*NO_DEADHEAT_BOOKS_BY_MARKET.values())

# Public exchanges — continuously traded orderbooks, reliable during live play.
# Sportsbook outrights go stale once rounds start and should not be used for
# edge detection during live periods.
EXCHANGE_BOOKS = {"kalshi", "polymarket", "prophetx"}

# --- Arbitrage ---
ARB_MIN_MARGIN = 0.005        # 0.5% minimum margin to flag an arb
ARB_DEFAULT_RETURN = 200      # Default guaranteed return for sizing display

# --- Signature Event ---
SIGNATURE_PURSE_THRESHOLD = 20_000_000

# --- Deep Field ---
DEEP_FIELD_RANK_THRESHOLD = 61  # Players ranked 61+ use 100% DG

# --- Market Type Classification ---
PLACEMENT_MARKETS = {"win", "t10", "t20", "make_cut"}
MATCHUP_MARKETS = {"tournament_matchup", "round_matchup"}
THREE_BALL_MARKETS = {"3_ball"}
ALL_MARKETS = PLACEMENT_MARKETS | MATCHUP_MARKETS | THREE_BALL_MARKETS

# Display labels for CLI output (internal values are unchanged)
MARKET_DISPLAY = {
    "make_cut": "MkCt",
    "tournament_matchup": "TnMtch",
    "round_matchup": "RdMtch",
    "3_ball": "3Ball",
}
