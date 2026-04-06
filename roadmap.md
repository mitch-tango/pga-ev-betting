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
- **Betsperts Golf integration**: API client for undocumented ShotLink-powered SG data; dual-window course-fit signal (12r form for ball-striking, 50r baseline for short game); course difficulty weighting (SG categories weighted by course-specific difficulty ratings); candidate annotation with [++]/[+]/[-]/[--] agreement signals; Discord `/coursefit` and `/fieldsg` commands
- **Expert picks signal**: YouTube transcript extraction (Rick Gehman, Pat Mayo, Betsperts) + Claude API (Haiku) pick extraction; aggregated consensus signal per player with sentiment scoring; candidate annotation with EP column; Discord `/expertpicks` command; Betsperts article support via cached text files

---

## Next Up

### 0. Course-Fit Signal → Kelly Modifier
**Priority: High** | Effort: Low-Medium

The Betsperts course-fit signal is currently display-only annotation on candidate bets. The plan is to graduate it to a Kelly confidence modifier once we have enough logged data to validate it.

**Phase 1 — Data collection (current, in progress):**
- Every candidate bet is annotated with `coursefit_signal` (strong_confirm → strong_contradict) and logged to Supabase with `coursefit_sg_data` JSONB
- Course-weighted composite score uses dual-window SG data (form: last 12 rounds for OTT/APP/T2G; baseline: last 50 rounds for ARG/P) with difficulty-based category weights per course
- 8 course profiles built (Masters, Memorial, US Open, Open, PGA, Players, API, RBC Heritage); remaining PGA Tour venues to be added from Betsperts course stats pages
- Betsperts session key requires periodic refresh when it expires

**Phase 2 — Validation analysis (after 3-5 tournaments of logged data):**
- Analyze `candidate_bets` table: compare actual bet outcomes for `coursefit_signal = 'strong_confirm'` vs `'strong_contradict'`
- Measure: win rate, ROI, CLV by signal classification
- Determine if the signal is predictive beyond what DG already captures
- Key question: does course-fit agreement correlate with bet success, or is it just noise?

**Phase 3 — Kelly modifier (if Phase 2 validates):**
- Add `COURSEFIT_KELLY_BETA` config parameter (e.g., 0.10-0.15)
- Compute Kelly multiplier: `modifier = 1.0 + beta * agreement_score` where agreement_score maps strong_confirm → +1, confirm → +0.5, contradict → -0.5, strong_contradict → -1
- Apply as multiplier on Kelly fraction alongside existing correlation haircut
- Bounded risk: only affects sizing, not edge detection or probability model
- Can be disabled by setting beta to 0

**Open questions:**
- Are 3-5 tournaments enough data, or do we need a full season?
- Should the modifier also apply to matchup bets, or outrights only?
- Should we weight the modifier by the player's sample size (more rounds = more confident signal)?


### 0b. Expert Picks Signal → Validation
**Priority: High** | Effort: Low

Expert picks consensus signal is currently display-only. Same graduation path as course-fit.

**Phase 1 — Data collection (current, in progress):**
- YouTube transcripts from Rick Gehman, Pat Mayo, Betsperts Golf extracted via `youtube-transcript-api`
- Claude Haiku extracts structured picks (player, market, sentiment, confidence, reasoning)
- Aggregated into consensus score per player, logged to Supabase with `expert_signal` and `expert_data` JSONB
- Betsperts articles supported via cached text files (client-rendered site requires browser or manual save)
- Discord `/expertpicks` command for on-demand analysis (~$0.16/tournament in API costs)

**Phase 2 — Validation (after 3-5 tournaments):**
- Analyze: do expert-consensus-confirmed bets outperform expert-consensus-contradicted bets?
- Track per-expert accuracy: which sources have actual signal vs. noise?
- Determine if expert consensus is independent of (or redundant with) the DG model

**Phase 3 — If validated:**
- Add as second Kelly modifier alongside course-fit
- Or use as a qualitative tiebreaker for borderline edge decisions

### 1. Weight & Sportsbook Evaluation
**Priority: High** | Effort: Medium

Systematic analysis of DG/sportsbook blend weights and per-book value across all bet types, segmented by player tranche (favorites, mid-tier, longshots).

**Phase 1 — Backtest re-analysis** (run now, no live data needed):
- Build `scripts/analyze_weights.py` with tranche segmentation
- Re-analyze 20K matchup backtest records: sweep DG/books blend weights per (market_type × tranche), measure Brier score, log-loss, and simulated ROI
- Per-book leave-one-out: recompute consensus dropping each book to measure marginal contribution to calibration
- Per-book line softness: how often each book is `best_book` and ROI when bet there
- Tranche definition: favorites (DG win prob ≥ 5%), mid-tier (1–5%), longshots (< 1%)
- Output recommended tranche-specific weights + sportsbook value ranking

**Phase 2 — SQL views for ongoing monitoring** (deploy now, auto-populate):
- `v_roi_by_tranche` — performance by favorites/mid/longshots
- `v_book_attribution` — per-book contribution to edge detection
- `v_clv_by_tranche` — CLV trends segmented by player tier

**Phase 3 — Live evaluation** (activates at ~50 settled bets):
- Same analysis on `candidate_bets` + `bets` tables using live data
- Compare live tranche-specific performance against backtest predictions
- Evaluate prediction market (Kalshi/Polymarket/ProphetX) consensus contribution (not in backtest data — requires live candidates with `all_book_odds` JSONB)
- Produce updated weight recommendations with bootstrap confidence intervals

**Open questions to resolve:**
- Does DG's OAD historical archive provide player-level predicted probs + actual finishes? If so, extend tranche analysis beyond matchups into win/placement/make-cut
- Should `deep_field` threshold (rank 61+) be higher or lower? Tranche analysis will inform this
- Consider tranche-aware config structure: `"win": {"favorite": {...}, "mid": {...}, "longshot": {...}}`

### 2. Bankroll & Kelly Sizing Refinements

**Priority: Medium** | Effort: Low-Medium

- Track actual P&L vs expected P&L over time
- Fractional Kelly ramp (e.g., start at 0.25 Kelly, increase with sample size)
- Drawdown alerts via Discord when bankroll drops below threshold
- Correlation-aware portfolio Kelly (account for overlapping player exposure)

### 3. Additional Sportsbooks
**Priority: Medium** | Effort: Medium

Expand beyond DG's aggregated feed:
- Direct Pinnacle API (sharpest lines, better CLV benchmark)
- PrizePicks / Underdog for player props
- Integrate as additional book columns in the existing pipeline

### 4. Dashboard / Web UI
**Priority: Low** | Effort: High

- Web dashboard for monitoring edges, bankroll curve, historical performance
- Visualize ROI by market, book, time period
- Alert configuration UI
- Could be a simple Streamlit app or full Next.js build

### 5. Backtest Expansion
**Priority: Low** | Effort: Medium

- Backtest Kalshi-style dead-heat advantage historically
- Simulate bankroll growth with different Kelly fractions
- Add more granular market analysis (e.g., T5, FRL)
