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

- **Dashboard / Web UI**: Streamlit app with 4 pages (Active Bets, Performance, Bankroll, Model Health); Supabase data layer with cached queries; Plotly charts for P&L curves, calibration, CLV trends, edge tier analysis; deployed on Streamlit Cloud

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

**Phase 1 — Backtest re-analysis: COMPLETE**
- Built `scripts/analyze_weights.py` with tranche segmentation (matchups + outrights)
- Swept DG/books blend weights per (market_type × tranche) using log-loss on 278-event OAD backtest (30K+ player-events per market) and 99-event matchup backtest (19,901 records)
- Per-book leave-one-out: all 7 books contribute to consensus (Betcris most valuable, DraftKings least)
- Per-book sharpness by tranche: paired comparison showed no significant accuracy differences between books for same players — apparent DK/FD "sharpness" was a field-size artifact
- Temporal stability validated: split 2020-2022 vs 2023-2026 to ensure weights are consistent across periods. Win market tranche weights were unstable and NOT implemented.
- Historical outright odds pulled for T10 and make-cut via `scripts/pull_oad_outrights.py`

**Phase 1 results — implemented tranche-specific weights:**

| Market | Favorite | Mid | Longshot | Previous |
|--------|----------|-----|----------|----------|
| T10/T20 | 100% DG | 55% DG | 45% DG | 55% global |
| Matchup | 60% DG | 30% DG | 0% DG | 20% global |
| Make Cut | 80% DG (global, raised) | | | 35% global |
| Win | 35% DG (unchanged) | | | 35% global |

Win market: tranche weights were temporally unstable (0% → 65% DG across periods). Kept global 35%.

**Phase 1 — Validation items: COMPLETE** (2026-04-06)
- Bootstrap CI on T10/T20 favorite tranche: 100% DG significantly better than 80%/70%/55% (all 95% CIs exclude zero, P>99.8%, holds under clustered bootstrap by event)
- Make-cut deep dive: 35%→80% confirmed via 5-fold CV (80% DG wins all folds, avg train-optimal 86% DG), temporal stability (75% in 2020-22, 95% in 2023-26), not a coverage artifact. Note: advantage narrows for events with 3+ book quotes — DG dominance partly reflects thin book coverage in make-cut markets
- Full results: `scripts/blend_weight_validation_results.md`
- Validation script: `scripts/validate_blend_weights.py`

**Phase 2 — SQL views for ongoing monitoring** (deploy now, auto-populate):
- `v_roi_by_tranche` — performance by favorites/mid/longshots
- `v_book_attribution` — per-book contribution to edge detection
- `v_clv_by_tranche` — CLV trends segmented by player tier

**Phase 3 — Live evaluation** (activates at ~50 settled bets):
- Same analysis on `candidate_bets` + `bets` tables using live data
- Compare live tranche-specific performance against backtest predictions
- Evaluate prediction market (Kalshi/Polymarket/ProphetX) consensus contribution (not in backtest data — requires live candidates with `all_book_odds` JSONB)
- Produce updated weight recommendations with bootstrap confidence intervals

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

### 4. Live Edge Calibration
**Priority: High** | Effort: Medium

The current 8% live edge threshold is a blunt guard against stale sportsbook odds during rounds. A data-driven threshold would capture more live edges without increasing false positives.

**Phase 1 — Historical analysis** (after accumulating live scan data):
- Compare DG live model predictions vs actual outcomes for edges detected during rounds
- Measure: how quickly do sportsbook odds go stale after DG updates? (5 min? 30 min?)
- Segment by market type — matchups may have different staleness profiles than outrights
- Analyze: at what edge threshold does live ROI turn positive? (currently assumed 8%)

**Phase 2 — Dynamic threshold** (if Phase 1 shows variance):
- Replace fixed 8% with market-specific live thresholds
- Consider time-of-day factor (early round = fresher lines vs mid-round)
- Add staleness metric: time since last DG update vs time since last book line move

**Phase 3 — Exchange arbitrage optimization:**
- Kalshi/Polymarket update faster than sportsbooks during live play
- Measure exchange-vs-sportsbook staleness differential
- Potentially lower exchange-only threshold below 8%

**Open questions:**
- How many live scans needed for statistical significance?
- Should the threshold vary by round (R1-R2 vs weekend)?

### 5. Backtest Expansion
**Priority: Low** | Effort: Medium

- Backtest Kalshi-style dead-heat advantage historically
- Simulate bankroll growth with different Kelly fractions
- Add more granular market analysis (e.g., T5, FRL)
