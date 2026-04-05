# PGA +EV Betting System — Roadmap

Last updated: 2026-04-05

## Completed

- **Core system**: Outrights (win, T10, T20, MC), matchups, 3-balls
- **Backtesting & calibration**: 278-event OAD backtest, 99-event matchup backtest, dead-heat analysis
- **Kalshi integration**: API client, odds conversion, tournament matching, pipeline merge, dead-heat bypass, workflow integration (8 sections, 304 tests)
- **Discord bot**: /status, /bankroll, /scan, /place, /live, /clv, /settle commands
- **Data pipeline**: DG API pull, player normalization, Supabase logging
- **Settlement**: Auto-settlement, CLV tracking, ROI by market/book

---

## Next Up

### 1. Discord Alerts — Push Notifications for +EV Opportunities
**Priority: High** | Effort: Medium

The bot currently requires manual `/scan` commands. Add proactive alerts:
- Scheduled scans (e.g., Tuesday evening pre-tournament, Thu-Sun mornings pre-round)
- Push embed to a dedicated channel when candidates are found above threshold
- Alert tiers: high-edge (>8%) gets @mention, moderate (5-8%) is silent post
- Include quick-action buttons or `/place` instructions in the alert
- Edge-gone alerts: re-check and notify if a previously-alerted edge has moved

### 2. Live Round Monitoring
**Priority: High** | Effort: Medium

`run_preround.py` has Kalshi disabled pending live DG predictions:
- Implement `get_live_predictions()` using DG's in-play model
- Enable Kalshi comparison during rounds (currently guarded by `kalshi_enabled = False`)
- Discord alert when a live edge appears mid-round
- Configurable polling interval (e.g., every 15 min during rounds)

### 3. End-to-End Live Validation
**Priority: High** | Effort: Low

Run the full pipeline against a real tournament to validate:
- Kalshi API returns real data and merges correctly
- Edge calculator produces sensible results with Kalshi as a book
- Dead-heat bypass works in practice for T10/T20
- Settlement handles Kalshi-sourced bets

### 4. Additional Prediction Markets
**Priority: Medium** | Effort: Medium

TODOs already in codebase for Polymarket:
- Polymarket covers win/T10/T20 but NOT matchups
- Gamma API for event discovery, CLOB for prices
- Same pull-merge-edge pattern as Kalshi
- Add config constants (POLYMARKET_BASE_URL, POLYMARKET_CLOB_URL, book weights)

### 5. Bankroll & Kelly Sizing Refinements
**Priority: Medium** | Effort: Low-Medium

- Track actual P&L vs expected P&L over time
- Fractional Kelly ramp (e.g., start at 0.25 Kelly, increase with sample size)
- Drawdown alerts via Discord when bankroll drops below threshold
- Correlation-aware portfolio Kelly (account for overlapping player exposure)

### 6. Additional Sportsbooks
**Priority: Medium** | Effort: Medium

Expand beyond DG's aggregated feed:
- Direct Pinnacle API (sharpest lines, better CLV benchmark)
- PrizePicks / Underdog for player props
- Integrate as additional book columns in the existing pipeline

### 7. Dashboard / Web UI
**Priority: Low** | Effort: High

- Web dashboard for monitoring edges, bankroll curve, historical performance
- Visualize ROI by market, book, time period
- Alert configuration UI
- Could be a simple Streamlit app or full Next.js build

### 8. Backtest Expansion
**Priority: Low** | Effort: Medium

- Backtest Kalshi-style dead-heat advantage historically
- Simulate bankroll growth with different Kelly fractions
- Add more granular market analysis (e.g., T5, FRL)
