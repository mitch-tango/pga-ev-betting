# Prediction Markets Integration — Usage Guide

## Quick Start

The prediction markets integration adds Polymarket and ProphetX as additional odds sources alongside the existing DG + Kalshi pipeline. No code changes are needed to use them — they're integrated into the existing workflow scripts.

### Configuration

Set these environment variables (or add to `.env`):

```bash
# Polymarket — enabled by default (no auth needed)
POLYMARKET_ENABLED=1          # Set to 0 to disable
POLYMARKET_GOLF_TAG_ID=...    # Optional: Polymarket golf tag for filtering

# ProphetX — auto-enabled when credentials are present
PROPHETX_EMAIL=you@example.com
PROPHETX_PASSWORD=your_password
```

Config constants in `config.py`:
- `POLYMARKET_MIN_VOLUME` — minimum market volume (default: 100)
- `POLYMARKET_MAX_SPREAD_ABS` / `POLYMARKET_MAX_SPREAD_REL` — spread filters
- `POLYMARKET_FEE_RATE` — taker fee applied to ask price (default: 0.002)
- `PROPHETX_MIN_OPEN_INTEREST` — minimum OI threshold (default: 100)
- `PROPHETX_MAX_SPREAD` — max bid-ask spread (default: 0.05)

### Running the Pipeline

```bash
# Pre-tournament scan (Wednesday) — pulls all markets automatically
python scripts/run_pretournament.py --tournament masters-2026

# Pre-round scan (Thu-Sun mornings) — includes ProphetX matchups
python scripts/run_preround.py --round 1

# Live edge detection — includes Polymarket + ProphetX odds
python scripts/run_live_check.py
```

## How It Works

### Pull Order
1. **DG API** — outright odds (win, T10, T20, MC) + matchups
2. **Kalshi** — outrights + matchups (binary prediction market)
3. **Polymarket** — outrights only (win, T10, T20 via Gamma API + CLOB orderbooks)
4. **ProphetX** — outrights + matchups (American or binary odds, auto-detected)

### Graceful Degradation
Each market is wrapped in try/except. If any market fails:
- A warning is printed
- The pipeline continues with remaining markets
- Edge calculation works with whatever books are available

### Edge Calculation
- All prediction markets contribute to the book consensus probability
- `BOOK_WEIGHTS` in `config.py` controls relative weight per market
- Dead-heat adjustment: Kalshi and Polymarket skip dead-heat (binary YES/NO), ProphetX applies standard reduction
- Ask-based pricing: `_{book}_ask_prob` keys provide the actual bettable price

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | All prediction market constants and feature flags |
| `src/api/polymarket.py` | Polymarket Gamma + CLOB API client |
| `src/api/prophetx.py` | ProphetX authenticated API client |
| `src/pipeline/polymarket_matching.py` | Tournament matching + player name extraction |
| `src/pipeline/prophetx_matching.py` | Tournament matching + market classification |
| `src/pipeline/pull_polymarket.py` | Pull + merge Polymarket outrights |
| `src/pipeline/pull_prophetx.py` | Pull + merge ProphetX outrights + matchups |
| `src/pipeline/pull_live_edges.py` | Live edge pipeline (includes both markets) |
| `src/core/edge.py` | Generalized edge calculator (all books) |
| `src/core/devig.py` | Binary price conversions (shared by all prediction markets) |

## Testing

```bash
# Run all prediction market tests
uv run pytest tests/test_polymarket_*.py tests/test_prophetx_*.py tests/test_prediction_market_workflow.py tests/test_edge_prediction_markets.py tests/test_config_prediction_markets.py tests/test_workflow_integration.py -v

# Full regression suite
uv run pytest -v
```

## Example Output

```
=== Pre-Tournament Scan (PGA) ===
Pulling outright odds...
  win: 156 players
  top_10: 156 players

Pulling Kalshi odds...
  Kalshi win: 48 players merged

Pulling Polymarket odds...
  Polymarket win: 35 players merged
  Polymarket t10: 28 players merged

Pulling ProphetX odds...
  ProphetX win: 42 players merged
  ProphetX matchups: 15 merged

Calculating edges for The Masters...
  win: 3 candidates
  t10: 5 candidates
  matchups: 2 candidates
```
