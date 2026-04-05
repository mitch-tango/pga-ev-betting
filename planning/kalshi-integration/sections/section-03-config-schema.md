# Section 03: Config Schema

## Overview

This section adds Kalshi-specific configuration constants to `config.py`, inserts Kalshi settlement rules into `schema.sql`, and adds Polymarket TODO comments at appropriate integration points. It has no dependencies on other sections and is a prerequisite for sections 04, 05, 06, and 07.

## Files to Modify

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/config.py`
- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/schema.sql`

## Files to Create

- `/Users/mitch_tango/Library/CloudStorage/Dropbox-NewCity/Maitland Thompson/Working/EV/pga-ev-betting/tests/test_kalshi_edge.py` (only the `TestKalshiBookWeights` class; other test classes in this file belong to later sections)

---

## Tests First

Create `tests/test_kalshi_edge.py` with the `TestKalshiBookWeights` test class. This is the only test class relevant to this section. The remaining classes in that file (`TestKalshiDevigBehavior`, `TestKalshiDeadHeatBypass`, `TestKalshiMatchupExclusion`, `TestKalshiAllBookOdds`) belong to sections 06 and 07 and should not be implemented here.

### TestKalshiBookWeights

```python
"""Tests for Kalshi book weight configuration and consensus integration."""

import config
from src.core.blend import build_book_consensus


class TestKalshiBookWeights:
    """Verify kalshi appears in BOOK_WEIGHTS with correct weight per market type."""

    def test_kalshi_weight_2_in_win_market(self):
        """kalshi has weight 2 in win market (sharp — prediction markets are efficient)."""

    def test_kalshi_weight_1_in_placement_market(self):
        """kalshi has weight 1 in placement market (t10, t20)."""

    def test_kalshi_absent_from_make_cut_weights(self):
        """kalshi is not present in make_cut weights — Kalshi does not offer make_cut."""

    def test_build_book_consensus_includes_kalshi(self):
        """build_book_consensus picks up kalshi with correct weight when present in book_probs dict.

        Provide a book_probs dict with pinnacle and kalshi for a win market.
        Verify the weighted average reflects kalshi at weight 2, same as pinnacle.
        """
```

Each test should import `config` and check `config.BOOK_WEIGHTS` directly. The last test should call `build_book_consensus()` from `src.core.blend` with a dict that includes a `"kalshi"` key and verify the output changes compared to omitting it. No mocking is needed; these tests exercise real config values and real blend logic.

---

## Implementation Details

### 1. Config Additions (`config.py`)

Add a new `# --- Kalshi ---` section after the existing `# --- DG API ---` block (around line 19, after `API_MAX_RETRIES`). The constants to add:

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
# TODO: Polymarket — add POLYMARKET_BASE_URL, POLYMARKET_CLOB_URL, book weights here
# Polymarket covers outrights + top-N but NOT matchups. Gamma API for discovery, CLOB for prices.
```

Explanation of each constant:

- **`KALSHI_BASE_URL`**: The Kalshi trade API v2 base URL. No API key is needed for public market data reads.
- **`KALSHI_RATE_LIMIT_DELAY`**: Minimum delay between API calls. Kalshi allows 20 requests/sec for the basic tier. 0.1s (10 req/sec) is conservative.
- **`KALSHI_MIN_OPEN_INTEREST`**: Contracts with OI below 100 are excluded from consensus — too thin for reliable pricing.
- **`KALSHI_MAX_SPREAD`**: Contracts with bid-ask spread exceeding $0.05 are excluded — wide spread indicates illiquid or unreliable pricing.
- **`KALSHI_SERIES_TICKERS`**: Maps the system's internal market type names to Kalshi series ticker strings used in API calls.

### 2. Book Weights Update (`config.py`)

Modify the existing `BOOK_WEIGHTS` dict (currently around line 46) to add `"kalshi"` entries:

- In the `"win"` sub-dict, add `"kalshi": 2`. Kalshi gets sharp-tier weight (same as pinnacle, betcris, betonline) because prediction market prices are informationally efficient — crowd-sourced from traders rather than set by oddsmakers.
- In the `"placement"` sub-dict, add `"kalshi": 1`. Equal weight with other placement books.
- Do **not** add kalshi to the `"make_cut"` sub-dict. Kalshi does not offer make_cut markets.

The updated `BOOK_WEIGHTS` should look like:

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
    # Matchups: equal-weighted average in edge.py (no weight dict needed),
    # but listed here for reference when Start outrights are added.
}
```

Note on matchups: Kalshi H2H is a **bettable outlet only** and is intentionally excluded from matchup consensus blending. This is handled in section 06, not here.

### 3. How `build_book_consensus` Picks Up Kalshi

No code changes are needed in `src/core/blend.py`. The existing `build_book_consensus()` function already iterates over whatever keys are in the `book_probs` dict and looks them up in `BOOK_WEIGHTS`. By adding `"kalshi"` to the weight dicts, the function will automatically include Kalshi in the weighted average when Kalshi data is present. When Kalshi data is absent (API down, no match, etc.), the `"kalshi"` key simply will not appear in `book_probs` and nothing changes.

### 4. Schema Additions (`schema.sql`)

Add Kalshi settlement rules to the `book_rules` seed data. Append the following `INSERT` statement after the existing `INSERT INTO book_rules` block (after line 59):

```sql
-- Kalshi settlement rules
-- Binary contracts: $1 payout on YES, $0 on NO. No dead-heat reduction on placement.
INSERT INTO book_rules (book, market_type, tie_rule, wd_rule, dead_heat_method, notes) VALUES
    ('kalshi', 'win', 'void', 'void', NULL, 'Binary contract: $1 win / $0 lose. WD = voided contract.'),
    ('kalshi', 't10', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T10 or better, including ties. No dead-heat reduction.'),
    ('kalshi', 't20', 'win', 'void', NULL, 'Binary: settles YES ($1) if official finish T20 or better, including ties. No dead-heat reduction.'),
    ('kalshi', 'tournament_matchup', 'void', 'void', NULL, 'Binary H2H: voided if tie or WD.')
ON CONFLICT (book, market_type) DO NOTHING;
```

Key distinctions from sportsbook rules:

- **`tie_rule = 'win'` for t10/t20**: A Kalshi T10 YES contract pays out in full if the player finishes T10 or better, even if tied at the cutoff position. Traditional sportsbooks apply dead-heat reduction in this scenario.
- **`dead_heat_method = NULL`**: No dead-heat math applies to Kalshi binary contracts. This is the structural advantage exploited in section 07.
- **`wd_rule = 'void'`**: Withdrawn players have their contracts voided (refunded) on Kalshi.

Also add `"kalshi"` as a recognized `source` value for the `player_aliases` table. No schema change is needed since `source` is a freeform `TEXT` column, but add a comment near the `player_aliases` table definition for documentation:

```sql
-- Valid sources: 'datagolf', 'start', 'kalshi'
-- TODO: Add 'polymarket' when Polymarket integration is built
```

### 5. Polymarket TODO Comments

Add TODO comments at the following locations:

- **`config.py`**: After the Kalshi constants block (shown above in the Kalshi config additions).
- **`schema.sql`**: After the Kalshi `book_rules` INSERT, add:
  ```sql
  -- TODO: Polymarket settlement rules — similar binary contract structure to Kalshi.
  -- Covers outrights and top-N, but NOT matchups. Requires keyword-based event discovery.
  ```

---

## Verification Checklist

After implementation, the following should hold:

1. `config.KALSHI_BASE_URL` returns `"https://api.elections.kalshi.com/trade-api/v2"`
2. `config.KALSHI_RATE_LIMIT_DELAY` returns `0.1`
3. `config.KALSHI_MIN_OPEN_INTEREST` returns `100`
4. `config.KALSHI_MAX_SPREAD` returns `0.05`
5. `config.KALSHI_SERIES_TICKERS` maps all four market types to their tickers
6. `config.BOOK_WEIGHTS["win"]["kalshi"]` returns `2`
7. `config.BOOK_WEIGHTS["placement"]["kalshi"]` returns `1`
8. `"kalshi"` is not in `config.BOOK_WEIGHTS["make_cut"]`
9. `build_book_consensus({"kalshi": 0.10, "pinnacle": 0.12}, "win")` returns `0.11` (both weight 2, simple average)
10. All four `TestKalshiBookWeights` tests pass
11. `schema.sql` contains the four Kalshi `book_rules` INSERT rows
12. Polymarket TODO comments are present in both `config.py` and `schema.sql`