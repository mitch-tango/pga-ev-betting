# Implementation Plan: Kalshi Prediction Market Integration

## 1. Background & Motivation

The PGA +EV betting system currently sources all odds through the DataGolf API, which aggregates sportsbook lines from pinnacle, draftkings, fanduel, bovada, betonline, and betcris. These are de-vigged, blended with DataGolf's proprietary model probabilities, and used to find +EV opportunities.

Kalshi is a CFTC-regulated prediction market that offers binary contracts on PGA golf outcomes. Adding Kalshi serves two purposes:

1. **Additional consensus signal** — Kalshi's prediction market prices are informationally efficient (crowd-sourced from traders rather than set by oddsmakers), providing an independent probability estimate that strengthens the book consensus.
2. **Bettable outlet** — The user has funds on Kalshi and wants the system to recommend bets there when Kalshi offers the best edge, just like any other sportsbook.

Kalshi covers four of the system's market types: tournament winner (`win`), top 10 (`t10`), top 20 (`t20`), and head-to-head matchups (`tournament_matchup`). It does not offer make_cut, round matchups, or 3-ball markets.

### Key Differences from Traditional Sportsbooks

Kalshi odds arrive differently from DataGolf-sourced books:

- **Minimal devigging needed.** Sportsbook lines include vig that must be removed via power method or independent de-vig. Kalshi binary contracts have minimal vig — but the bid-ask spread means summing ask prices across a full field can total 105–115%, not 1.0. The **midpoint** `(bid + ask) / 2` is the best estimate of true market probability for consensus blending. The **ask** price (what you'd pay to buy) is used for edge/bettability evaluation.
- **Dual price usage.** For each Kalshi contract, we extract both bid and ask. Midpoint → consensus signal. Ask → bettable line for edge calculation. This separation prevents the spread from biasing the consensus.
- **Separate API.** DataGolf returns all books in one response. Kalshi data comes from its own REST API and must be fetched, matched by tournament and player, then merged into the existing pipeline.

---

## 2. Architecture Overview

```
┌─────────────┐     ┌──────────────┐
│  DataGolf   │     │   Kalshi     │
│  API        │     │   API        │
└──────┬──────┘     └──────┬───────┘
       │                   │
       ▼                   ▼
┌──────────────┐  ┌────────────────┐
│pull_outrights│  │  pull_kalshi   │  ← New pipeline module
│pull_matchups │  │                │
└──────┬───────┘  └───────┬────────┘
       │                  │
       │    ┌─────────────┘
       │    │  (name matching + merge)
       ▼    ▼
┌────────────────┐
│  edge.py       │  ← Kalshi injected as additional book columns
│  blend.py      │
│  devig.py      │
└───────┬────────┘
        │
        ▼
  CandidateBet list → Display / DB / Discord
```

The integration touches six areas:
1. New API client (`src/api/kalshi.py`)
2. New pipeline module (`src/pipeline/pull_kalshi.py`)
3. Config additions (`config.py`)
4. Edge calculation modifications (`src/core/edge.py`, `src/core/blend.py`)
5. Schema additions (`schema.sql`)
6. Workflow integration (`run_pretournament.py`, `run_preround.py`)

---

## 3. Kalshi API Client

### 3.1 Client Design

A new `KalshiClient` class in `src/api/kalshi.py`, following the `DataGolfClient` pattern:

```python
class KalshiClient:
    """Client for the Kalshi prediction market API (read-only)."""

    def __init__(self, base_url: str | None = None, cache_dir: str | None = None): ...
    def _api_call(self, endpoint: str, params: dict | None = None) -> dict: ...
    def _cache_response(self, data: dict, label: str, tournament_slug: str | None = None) -> Path: ...
    def get_golf_events(self, series_ticker: str) -> dict: ...
    def get_event_markets(self, event_ticker: str) -> dict: ...
    def get_market(self, ticker: str) -> dict: ...
    def get_orderbook(self, ticker: str) -> dict: ...
```

**Key differences from DataGolfClient:**

- **No API key.** Market data endpoints are public. No authentication headers needed.
- **Rate limiting.** Kalshi allows 20 req/sec (basic tier). The client should enforce this with a token bucket or simple delay. The existing DG client uses a fixed 1.5s delay between calls — Kalshi can be faster (0.05s minimum between calls to stay under 20/sec) but should start conservative at 0.1s.
- **Pagination.** Kalshi's `/events` and `/markets` endpoints use cursor-based pagination (`limit` up to 200, `cursor` for next page). The client must loop until no more pages.
- **Response format.** Kalshi returns `{"events": [...], "cursor": "..."}` or `{"markets": [...], "cursor": "..."}`. The client should unwrap and concatenate paginated results.

### 3.2 API Endpoints Used

| Method | Endpoint | Purpose |
|---|---|---|
| `get_golf_events` | `GET /events?series_ticker={ticker}&status=open` | Find current tournament events |
| `get_event_markets` | `GET /markets?event_ticker={ticker}` | All player contracts for an event |
| `get_market` | `GET /markets/{ticker}` | Single market with current prices |
| `get_orderbook` | `GET /markets/{ticker}/orderbook` | Full orderbook for liquidity check |

### 3.3 Error Handling

The client returns the same `{"status": "ok", "data": ...}` / `{"status": "error", ...}` envelope as `DataGolfClient`. On failure (network error, 429, 5xx), it retries with exponential backoff (3 attempts). On persistent failure, it returns an error dict and the pipeline gracefully proceeds without Kalshi data.

### 3.4 Caching

Responses are cached to `data/raw/{tournament_slug}/{timestamp}/kalshi_*.json`, following the existing convention.

---

## 4. Tournament & Player Matching

### 4.1 Tournament Matching

The system needs to find the Kalshi event corresponding to the current DataGolf tournament. The approach is **date-based matching**:

1. For each relevant series ticker (`KXPGATOUR`, `KXPGATOP10`, `KXPGATOP20`, `KXPGAH2H`), fetch open events.
2. Each Kalshi event has `expected_expiration_time` (when it settles) and an event title (e.g., "PGA Tour: Valero Texas Open Winner").
3. Match by comparing the event's expiration date to the current tournament's dates — the Kalshi event that expires within the tournament week is the match.
4. If no date match is found, fall back to fuzzy string matching on the event title against the DG tournament name.
5. If still no match (Kalshi hasn't posted markets yet), log a warning and proceed without Kalshi data.

This matching happens once per pipeline run and the result (a dict of `{series_ticker: event_ticker}`) is passed to the pull functions.

**Safety check:** Verify the matched event title contains "PGA" or a recognizable tournament name to avoid accidentally matching LIV Golf or DP World Tour events that may run on the same weekend.

### 4.2 Player Name Matching

Kalshi contract titles contain player names (e.g., "Will Scottie Scheffler win the Masters?"). These must be mapped to DataGolf canonical names.

The system already has `src/normalize/players.py` with `resolve_candidates()` which builds a player alias table over time. There is also `src/parsers/` with name-matching utilities for the Start book.

For Kalshi, the approach is:

1. **Extract player name from contract.** Parse the Kalshi market `title` or `subtitle` field to extract the player name. For outright markets, the title pattern is typically "[Player Name]" as a direct field or parseable from "Will [Player Name] win...?" For H2H, the pattern includes both players.
2. **Normalize.** Strip suffixes (Jr., III), normalize whitespace, handle international characters.
3. **Match to DG canonical name.** Use the existing player alias table (`player_aliases` in Supabase) with source = "kalshi". On first encounter, attempt fuzzy matching against known DG names and create the alias. On subsequent runs, the alias lookup is instant.
4. **Unmatched players.** If a Kalshi player can't be matched, log a warning and skip that player. The pipeline should never fail due to a name mismatch.

---

## 5. Pipeline Module

### 5.1 `src/pipeline/pull_kalshi.py`

A new pipeline module following the pattern of `pull_outrights.py`:

```python
def pull_kalshi_outrights(tournament_slug: str | None = None) -> dict[str, list[dict]]:
    """Pull Kalshi outright odds for win, t10, t20 markets.

    Returns:
        {"win": [{"player_name": str, "kalshi_prob": float, "open_interest": int}, ...],
         "t10": [...], "t20": [...]}
    """

def pull_kalshi_matchups(tournament_slug: str | None = None) -> list[dict]:
    """Pull Kalshi H2H matchup odds.

    Returns:
        [{"p1_name": str, "p2_name": str, "p1_prob": float, "p2_prob": float,
          "p1_oi": int, "p2_oi": int}, ...]
    """
```

**Processing steps for outrights:**
1. Call `KalshiClient.get_golf_events("KXPGATOUR")` to find the current tournament winner event.
2. Call `get_event_markets(event_ticker)` to get all player contracts. Verify this bulk endpoint returns `yes_bid_dollars` and `yes_ask_dollars` in the response — if so, no per-market orderbook calls are needed.
3. For each contract:
   - Extract player name from title/subtitle.
   - Read `yes_bid_dollars` and `yes_ask_dollars`.
   - Compute `midpoint = (bid + ask) / 2` for consensus probability.
   - Store `ask` separately for bettable edge evaluation.
   - Read `open_interest` for liquidity filtering.
   - Skip if `open_interest < KALSHI_MIN_OPEN_INTEREST` (100).
   - Skip if `(ask - bid) > KALSHI_MAX_SPREAD` (0.05) — wide spread indicates illiquid/unreliable pricing.
   - Validate price is in 0–1 range (if values are 0–100, divide by 100).
4. Normalize player names to DG canonical format.
5. Repeat for T10 and T20 series tickers.
6. Cache raw responses.
7. Only call individual `get_orderbook()` for markets that pass initial filtering and are needed for deeper liquidity analysis.

**Processing steps for H2H matchups:**
1. Call `get_golf_events("KXPGAH2H")` and `get_event_markets()`.
2. Each H2H event contains two contracts (Player A wins, Player B wins).
3. Extract both player names, read ask prices, check OI.
4. Return in a format compatible with the existing matchup pipeline.

### 5.2 Merging Kalshi Data into the Pipeline

Kalshi data must be merged into the existing data flow at the right point. There are two integration strategies, and we use **Strategy A: inject as book columns**.

**Strategy A: Inject as book columns (chosen)**

Convert Kalshi probabilities into the same format as sportsbook data — as if "kalshi" were another book column in the DG API response. This means:
- For outrights: add a `"kalshi"` key to each player record in the outrights data, with a value that looks like an American odds string (converted from the Kalshi **midpoint** probability).
- This allows the existing `calculate_placement_edges()` to pick up Kalshi naturally in its book discovery loop (Step 1 in edge.py: "Identify book columns in the data").

The reason to convert back to American odds strings (even though we started with probabilities) is that the edge calculator's book discovery relies on detecting string values starting with "+" or "-". Converting to American format lets Kalshi slot in without modifying the edge calculator's core logic.

**Important: midpoint vs ask distinction.** The American odds string injected uses the **midpoint** probability (for consensus blending). However, when the edge calculator evaluates Kalshi as a bettable book and stores `all_book_odds`, the actual decimal odds stored should reflect the **ask** price (what you'd actually pay). This means the merge step also stores raw ask data that edge.py uses when computing the actual offered decimal odds for the `all_book_odds` dict.

**For matchups:** Kalshi H2H data is injected into the matchups data structure alongside existing book odds, following the same `odds_dict` format used by `calculate_matchup_edges()`. However, per the interview decision, matchup probabilities remain 100% DG model — Kalshi is only used as a bettable outlet (edge = your_prob - kalshi_implied_prob), not blended into the probability model.

---

## 6. Book Consensus & Edge Calculation Changes

### 6.1 Config Additions

Add to `config.py`:

```python
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
```

Add "kalshi" to `BOOK_WEIGHTS`:

```python
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
}
```

### 6.2 De-vig Behavior for Kalshi

The existing edge calculator (Step 2 in `calculate_placement_edges`) de-vigs each book's full field using `power_devig()` or `devig_independent()`.

Since we inject the **midpoint** probability (not the ask), the field sum will be close to 1.0 for winner markets — the power de-vig will find k ≈ 1.0 and return probabilities nearly unchanged. For placement markets (T10/T20), midpoint probabilities summed across the field should approximate the expected outcome count (10 or 20), so `devig_independent()` will scale by ~1.0.

This means **no special handling is needed in edge.py for the de-vig step** — the math handles midpoint-based Kalshi data naturally. If in practice the sums deviate more than expected, the de-vig will apply a small correction, which is acceptable.

### 6.3 Kalshi as Bettable Book

When the edge calculator finds the "best book" for each player (Step 3 in `calculate_placement_edges`), Kalshi will be evaluated alongside all other books. If `your_prob - kalshi_implied_prob` exceeds the min_edge threshold and is the highest edge of any book, Kalshi becomes the "best_book" recommendation.

The `all_book_odds` dict stored in the database will include Kalshi's decimal odds, so the full picture is preserved.

### 6.3.1 Dead-Heat Advantage for T10/T20

This is a significant structural advantage of Kalshi over traditional sportsbooks for placement markets.

Currently, `adjust_edge_for_deadheat()` reduces the effective edge for T10/T20 bets to account for dead-heat payout reductions at sportsbooks (T10: ~4.4% avg reduction, T20: ~3.8%). These reductions are calibrated from backtest data and are applied uniformly because all sportsbooks use dead-heat rules on placement ties.

**Kalshi does not have this problem.** A Kalshi T10 YES contract pays $1 if the player finishes T10 or better — ties included, full payout, no reduction. This means:

- When evaluating a T10/T20 bet at a sportsbook: `adjusted_edge = raw_edge - deadheat_adj`
- When evaluating the same bet on Kalshi: `adjusted_edge = raw_edge` (no dead-heat adjustment)

**Implementation:** In `calculate_placement_edges()`, the dead-heat adjustment should be applied **per-book**, not globally. When computing the adjusted edge for each book candidate:
- For traditional sportsbooks: apply `adjust_edge_for_deadheat()` as currently done
- For Kalshi: skip the dead-heat adjustment (set `dh_adj = 0`)

This means Kalshi will frequently surface as the "best book" for T10/T20 bets even when its raw odds are slightly worse than a sportsbook — because the effective edge after dead-heat adjustment is higher. For example:

```
Player X — T10 market:
  your_prob = 0.30 (30%)

  DraftKings:  implied = 0.22, raw_edge = 8.0%, DH adj = -4.4%, effective = 3.6%
  Kalshi:      implied = 0.23, raw_edge = 7.0%, DH adj = 0.0%,  effective = 7.0%  ← winner
```

In this example, DraftKings has better raw odds but Kalshi wins on effective edge because of the dead-heat advantage.

### 6.4 Matchup Handling

Per the interview decision: matchup probabilities stay at 100% DG model. Kalshi H2H is a **bettable outlet only**.

In `calculate_matchup_edges()`, Kalshi H2H odds are included in `all_book_odds` and evaluated for "best edge" alongside traditional books, but they do NOT participate in `book_consensus_p1` blending. This requires a minor modification: when computing the book consensus for matchup blending, exclude Kalshi. When computing the best edge across books, include Kalshi.

---

## 7. Schema Additions

Add Kalshi settlement rules to `book_rules`:

```sql
INSERT INTO book_rules (book, market_type, tie_rule, wd_rule, dead_heat_method, notes) VALUES
    ('kalshi', 'win', 'void', 'void', NULL, 'Binary contract: $1 win / $0 lose. WD = voided contract.'),
    ('kalshi', 't10', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T10 or better, including ties. No dead-heat reduction.'),
    ('kalshi', 't20', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T20 or better, including ties. No dead-heat reduction.'),
    ('kalshi', 'tournament_matchup', 'void', 'void', NULL, 'Binary H2H: voided if tie or WD.')
ON CONFLICT (book, market_type) DO NOTHING;
```

**Important distinction from sportsbooks:** Kalshi top-N markets are binary YES/NO contracts that settle based on official finish position. If a player ties for 10th, the T10 YES contract settles at $1 (full win) — there is no dead-heat reduction like sportsbooks apply. This is a significant advantage for Kalshi placement bets and means the dead-heat edge adjustment in `adjust_edge_for_deadheat()` should be skipped when `best_book == "kalshi"` for placement markets.

Note: The exact settlement rules should be verified against Kalshi's contract language for the first golf tournament. The rules above represent the expected behavior based on Kalshi's general binary contract structure.

Add "kalshi" as a valid source in `player_aliases` for name resolution.

---

## 8. Workflow Integration

### 8.1 `scripts/run_pretournament.py` Changes

After pulling DG outrights and matchups, add a Kalshi pull step:

1. Call `pull_kalshi_outrights(tournament_slug)` → returns `{"win": [...], "t10": [...], "t20": [...]}`.
2. Call `pull_kalshi_matchups(tournament_slug)` → returns list of H2H matchup dicts.
3. Merge Kalshi outright data into the DG outrights dict (inject as book columns).
4. Merge Kalshi matchup data into the DG matchups list (inject as additional book in odds_dict).
5. Proceed with edge calculation as normal — Kalshi is now visible as another book.

If Kalshi data is unavailable (API down, no golf events), print a warning and proceed with DG-only data.

### 8.2 `scripts/run_preround.py` Changes

**Important constraint:** Kalshi tournament-long markets (win, T10, T20, tournament matchups) trade live during the event. Their prices reflect in-tournament performance. During pre-round runs (mid-tournament), comparing live Kalshi prices against stale pre-tournament DG probabilities would create massive false positive edges.

Therefore: during `run_preround.py`, **only pull Kalshi tournament-long markets if the pipeline is also using live DG predictions** (via `get_live_predictions()`). If the pre-round scan uses only pre-tournament DG data, skip Kalshi tournament markets entirely for that run.

Round-specific Kalshi markets (if they ever exist) would not have this issue, but currently Kalshi only offers tournament-long markets for golf.

### 8.3 Discord Bot

The bot already displays whatever `best_book` the edge calculator selects and shows `all_book_odds` in the detail view. Since Kalshi is injected as a standard book, it will appear automatically in:
- `/scan` — as a possible "Best Book" when it offers the highest edge
- `/place` — logged with `book = "kalshi"` when the user places a bet there
- `/status` — tracked in the `v_roi_by_book` view alongside other books

No bot code changes are needed unless the display format needs adjustment for the "kalshi" book name.

---

## 9. Odds Conversion Utilities

Add utility functions to `src/core/devig.py`:

```python
def kalshi_price_to_american(price_str: str) -> str:
    """Convert Kalshi dollar price string to American odds.
    
    '0.06' (6% implied) -> '+1567'
    '0.55' (55% implied) -> '-122'
    Rounds to standard integer format.
    """

def kalshi_price_to_decimal(price_str: str) -> float | None:
    """Convert Kalshi dollar price string to decimal odds.
    
    '0.06' -> 16.67
    '0.55' -> 1.818
    """

def kalshi_midpoint(bid_str: str, ask_str: str) -> float | None:
    """Compute midpoint probability from Kalshi bid/ask.
    
    ('0.04', '0.06') -> 0.05
    Returns None if either price is missing or invalid.
    """
```

The `kalshi_price_to_american()` function is used during the merge step (section 5.2) to convert Kalshi **midpoint** probabilities into the American odds format expected by the edge calculator. The `kalshi_price_to_decimal()` function is used to store the **ask**-based decimal odds in `all_book_odds`.

**Precision note:** When converting midpoint to American and back, there is minor rounding loss. For a 6% midpoint: 0.06 → "+1567" → 0.0600 (the round-trip preserves 2 decimal places of probability). This is acceptable — the same rounding applies to all books via `parse_american_odds()`.

---

## 10. Graceful Degradation Summary

| Failure Mode | Behavior |
|---|---|
| Kalshi API unreachable | Log warning, proceed with DG-only data |
| No open golf events on Kalshi | Log info, proceed without Kalshi |
| Tournament can't be matched | Log warning, skip Kalshi for this run |
| Player name can't be matched | Skip that player's Kalshi data, log warning |
| OI below threshold (< 100) | Exclude player from Kalshi consensus |
| Bid-ask spread > $0.05 | Exclude player — pricing unreliable |
| Rate limited (429) | Retry with backoff, then proceed without if persistent |
| Pre-round scan without live DG | Skip Kalshi tournament markets (stale model risk) |

The system should never fail or halt due to Kalshi integration issues.

---

## 11. Dependencies

Add to `requirements.txt`:
- No new dependencies needed. The Kalshi API is a standard REST API that `requests` (already a dependency) handles directly. The `kalshi-py` SDK is not necessary — the raw API is simple enough.

---

## 12. Future: Polymarket Integration (TODO)

Leave code comments at integration points for future Polymarket support:
- In `src/api/` — note that `polymarket.py` would follow the same client pattern
- In `src/pipeline/pull_kalshi.py` — note that Polymarket covers outrights and top-N but NOT matchups, and requires keyword-based event discovery
- In `config.py` — note where Polymarket book weights would be added

Polymarket details for future reference:
- Gamma API (`https://gamma-api.polymarket.com`) for market discovery
- CLOB API (`https://clob.polymarket.com`) for prices
- No auth needed for reads
- No golf-specific tag — requires keyword search
- Python SDK: `py-clob-client`
