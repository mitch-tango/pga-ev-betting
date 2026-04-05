# Section 11: Testing Infrastructure & Integration Tests

## Overview

This section creates shared test fixture factories for Polymarket and ProphetX data, plus cross-cutting integration tests that verify the full prediction market workflow. Individual unit tests for each module are defined in their respective sections; this section covers shared infrastructure and end-to-end validation.

## Dependencies

All previous sections (01 through 10) must be implemented.

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Add shared fixture factories for Polymarket and ProphetX test data |
| `tests/test_prediction_market_workflow.py` | Integration tests: full pipeline, partial failure, total failure, regression |

## Fixture Factories (in `tests/conftest.py`)

### Polymarket Factories

```python
# _make_polymarket_event(title, start_date, end_date, markets)
#   Creates Gamma API event dict with: id, title, slug, startDate, endDate, markets[]
#   Markets default to empty list if not provided.

# _make_polymarket_market(question, slug, outcome_prices, clob_token_ids, volume, outcomes=None)
#   Creates single market dict with: id, question, slug, outcomePrices (JSON string),
#   clobTokenIds (JSON string), volume, outcomes (default ["Yes", "No"]), marketType, liquidity.
#   outcome_prices: list of two floats (e.g., [0.45, 0.55])
#   clob_token_ids: list of two strings

# _make_polymarket_books_response(token_id, best_bid, best_ask)
#   Creates CLOB /books response for one token with: bids [{price, size}], asks [{price, size}]
```

### ProphetX Factories

```python
# _make_prophetx_event(name, start_date, event_id)
#   Creates ProphetX event dict with: id, name, start_date, end_date
#   Uses field names matching what prophetx_matching tries

# _make_prophetx_market(line_id, competitors, odds, market_type="moneyline", sub_type="outrights")
#   Creates ProphetX market dict with: line_id, market_type, sub_type, competitors[], odds
#   competitors: list of dicts with competitor_name
#   odds: American int/string or binary float

# _make_prophetx_matchup_market(line_id, player1, player2, p1_odds, p2_odds)
#   Convenience wrapper: 2 competitors, moneyline type
```

## Integration Tests (`tests/test_prediction_market_workflow.py`)

### TestFullPipelineAllMarkets

```python
# Test: all three markets merge into outrights
#   Mock DG (20 players), Kalshi (15), Polymarket (12), ProphetX (10)
#   Verify some players have all 3 prediction market keys
#   Verify edge calculation produces CandidateBet results

# Test: pull order is DG → Kalshi → Polymarket → ProphetX → edge calc

# Test: edges found with all markets contributing to consensus

# Test: best_book can be any prediction market
```

### TestPartialFailure

```python
# Test: Polymarket down, Kalshi + ProphetX ok → edges still calculated
# Test: ProphetX down, Kalshi + Polymarket ok → edges still calculated
# Test: Kalshi down, Polymarket + ProphetX ok → edges still calculated
# Test: two markets down, one remaining → edges still calculated
# Test: graceful degradation prints warning messages
```

### TestTotalPredictionMarketFailure

```python
# Test: all prediction markets down → DG-only pipeline works
# Test: DG-only regression (all markets disabled via config)
```

### TestEnabledFlags

```python
# Test: Polymarket skipped when POLYMARKET_ENABLED=False
# Test: ProphetX skipped when PROPHETX_ENABLED=False
# Test: both disabled → DG + Kalshi only (pre-integration baseline)
```

### TestWorkflowScriptContents

```python
# Test: run_pretournament.py imports pull_polymarket and pull_prophetx
# Test: run_pretournament.py has try/except for each market
# Test: run_preround.py imports both markets
# Test: run_live_check.py references prediction market stats
```

## Test Approach

Tests do NOT call scripts as subprocesses. Instead:

1. **Mock at client level**, call pull/merge directly, verify data flows through real merge and edge logic
2. **Inspect script source** for structural patterns (imports, try/except, warnings) — following `tests/test_kalshi_workflow.py` pattern

Mock pattern:
```python
with patch("src.pipeline.pull_polymarket.PolymarketClient") as mock_cls:
    mock_client = mock_cls.return_value
    mock_client.get_golf_events.return_value = [...]  # fixture factories
    result = pull_polymarket_outrights("Tournament", "2026-04-09", "2026-04-13")
```

## Key Verification Points

1. **Merged data shape**: Player dicts contain sportsbook keys + matched prediction market keys + `_ask_prob` floats for binary markets
2. **Edge compatibility**: `calculate_placement_edges` handles players with varying subsets of book keys
3. **Dead-heat correctness**: Polymarket → `deadheat_adj == 0.0` for placements; ProphetX → reduction applied
4. **Degradation chain**: Any combination of 0-3 markets produces valid output
5. **Config enforcement**: Disabled markets → no API calls, clean skip

## Running Tests

```bash
uv run pytest tests/test_prediction_market_workflow.py -v
uv run pytest -v  # full suite for regression check
```
