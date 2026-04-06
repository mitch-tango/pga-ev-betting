# PGA +EV Betting System — Roadmap

Last updated: 2026-04-06

## Completed

- **Core system**: Outrights (win, T10, T20, MC), matchups, 3-balls
- **Backtesting & calibration**: 278-event OAD backtest, 99-event matchup backtest, dead-heat analysis
- **Kalshi integration**: API client, odds conversion, tournament matching, pipeline merge, dead-heat bypass, workflow integration (8 sections, 304 tests)
- **Discord bot**: /status, /bankroll, /scan, /place, /live, /clv, /settle commands
- **Data pipeline**: DG API pull, player normalization, Supabase logging
- **Settlement**: Auto-settlement, CLV tracking, ROI by market/book
- **Discord alerts**: Scheduled pre-tournament and pre-round scans, alert tiers (high-edge @mention vs silent post), edge-gone re-check notifications
- **Live round monitoring**: DG live model integration, exchange-only edge detection during rounds, configurable polling interval (15 min)
- **Live validation**: Full pipeline validated against real Masters 2026 data (Kalshi, Polymarket, ProphetX)
- **Prediction markets**: Polymarket (Gamma API + CLOB) and ProphetX API clients, tournament matching, pipeline merge (11 sections, 579 total tests)
- **Cross-book arbitrage**: Arbitrage detection across books for matchups and 3-balls
- **Post-tournament summary**: Automated performance summary posted to Discord after tournament completion

---

## Next Up

### 1. Bankroll & Kelly Sizing Refinements
**Priority: Medium** | Effort: Low-Medium

- Track actual P&L vs expected P&L over time
- Fractional Kelly ramp (e.g., start at 0.25 Kelly, increase with sample size)
- Drawdown alerts via Discord when bankroll drops below threshold
- Correlation-aware portfolio Kelly (account for overlapping player exposure)

### 2. Additional Sportsbooks
**Priority: Medium** | Effort: Medium

Expand beyond DG's aggregated feed:
- Direct Pinnacle API (sharpest lines, better CLV benchmark)
- PrizePicks / Underdog for player props
- Integrate as additional book columns in the existing pipeline

### 3. Dashboard / Web UI
**Priority: Low** | Effort: High

- Web dashboard for monitoring edges, bankroll curve, historical performance
- Visualize ROI by market, book, time period
- Alert configuration UI
- Could be a simple Streamlit app or full Next.js build

### 4. Backtest Expansion
**Priority: Low** | Effort: Medium

- Backtest Kalshi-style dead-heat advantage historically
- Simulate bankroll growth with different Kelly fractions
- Add more granular market analysis (e.g., T5, FRL)
