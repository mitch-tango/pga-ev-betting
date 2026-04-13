# PGA +EV Betting System — Roadmap

Last updated: 2026-04-13 (post-Masters audit resolved — P0/P1 shipped; P3 arb-legs + dead-heat exemptions shipped)

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
- **Candidate lifecycle tracking**: All candidates inserted to DB before placement, linked to bets via candidate_id, skip reasons tracked. Monitoring views: v_clv_coverage, v_execution_slippage, v_candidate_fill_rate. *(Note: originally shipped only in CLI scripts; Discord `/scan` → `/place` silently hardcoded `candidate_id=None`. Fixed 2026-04-13 — see "Post-Masters fixes" below.)*
- **Settlement pipeline**: Archive-first results fetch (`pull_results.fetch_archived_results`) so completed tournaments remain settleable after DG field-updates rolls to next week; cut-opponent matchup handling (treats a cut opponent as a loss for the active player, not a WD-void); startup settlement catch-up in `_scheduled_alerts` so missed Sun 10pm runs recover on next bot restart. *(2026-04-13)*

---

## Post-Masters Fixes (shipped 2026-04-13)

The Masters post-mortem (2026-04-12) found two silent failures that the
roadmap had marked "Completed." Both are now fixed.

**P0 — Candidate→bet linkage was broken in the Discord path.** The CLI
scripts (`scripts/run_pretournament.py` et al) correctly inserted candidates
and linked `bets.candidate_id` on `/place`, but the Discord `/scan` path
cached candidates only in memory and `/place` hardcoded `candidate_id=None`.
Every bet the user had ever placed via Discord was landing unlinked,
blocking every downstream validation phase.

- Commit `e98697a`: added `CandidateBet.candidate_id`, a
  `db.persist_candidates()` helper that inserts a batch and mutates each
  candidate in place with its new row id, wired it into all four bot scan
  paths (`_run_pretournament_scan`, `_run_preround_scan`, `_live_monitor_loop`,
  `/monitor once`), and fixed `/place` to pass the linked id.
- Backfilled 9/13 existing Masters bets (matched scan-captured candidates
  by player/market/opponents/round). The 4 unlinked bets were NoVig
  outrights placed manually with no scan counterpart — stay unlinked,
  which is expected (see memory: "NoVig bets are logged manually").

**P1 — Auto-settlement had two compounding failures.** The bot was offline
at Sun 10pm ET when the scheduled settlement hook was supposed to fire, AND
the code only read from DG's live `field-updates` endpoint, which had
already rolled over to RBC Heritage by Monday morning, making Masters
results structurally unreachable through `/settle`.

- Recovery: one-off script against DG's `historical-odds/outrights` archive
  settled all 13 bets (8 wins, 5 losses, session P&L +$21.68, bankroll
  $853 → $1,061.68).
- Commit `84a80b7`: `pull_results.fetch_archived_results()` pulls from the
  historical archive and returns the same shape as `fetch_results()` so the
  downstream match/settle code is unchanged. `_run_settlement` groups bets
  by `tournament_id` and resolves results per-tournament via a new
  `_results_for_tournament` helper that prefers the archive and falls back
  to `fetch_results()` only when the event isn't archived yet. Cut-opponent
  matchups no longer void via `wd_rule` (the original code treated any
  `status != 'active'` as `pos=None` and let `settle_matchup_bet` apply the
  WD void — wrong, because making the cut is a normal result). Added a
  startup settlement sweep to `_scheduled_alerts` so a missed Sunday 10pm
  run recovers on next bot restart, not the next tournament week.

**P2 — Live monitoring volume.** Still open as a post-mortem item for
the next tournament; the heartbeat + staleness fixes are shipped but
unvalidated against a second data point. Revisit at end of RBC Heritage.

**Snapshot after fixes (2026-04-13):**
- `candidate_bets`: 68 rows (unchanged), 9 now correctly marked `status='placed'`
- `bets`: 13 rows, **all 13 settled**, 9 linked to candidates
- Session P&L on Masters: +$21.68 | Bankroll: $1,061.68
- Discord bot restarted on new code (PID confirmed post-restart); startup catch-up ran once as a no-op

---

## Quick Wins / To-Do

- [x] **[P3] Market-aware dead-heat exemptions** — shipped 2026-04-13 (`cdfe66e`). Replaced flat `NO_DEADHEAT_BOOKS` with `NO_DEADHEAT_BOOKS_BY_MARKET`. Added BetMGM, Pinnacle, ProphetX to the placement-market exempt set (book_rules says they all pay ties in full but code was still haircutting them). On a T20 5% raw edge that's a 3.8pp restoration, which flips those candidates from "suppressed below threshold" to "surface as real edges."
- [x] **[P3] Arb legs as placeable candidates** — shipped 2026-04-13. New `arb_legs_to_candidates()` helper in `src/core/arb.py` flattens each detected arb into per-leg `CandidateBet` rows (stakes populated via `size_arb`, sibling-leg metadata preserved in `all_book_odds`). Pretournament and preround scans persist legs with distinct `pretournament_arb` / `preround_arb` scan_types so +EV analytics views stay uncontaminated. Arb legs are appended to `bot.last_scan` so `/place <N>` targets a leg the same way as a +EV candidate; the scan image's arb table shows a `Legs` column with the continuing leg numbers (e.g., `11+12`). `/place` success embed now reminds the user about remaining sibling legs they still need to place. 8 new tests in `tests/test_arb.py`.
- [x] **[P3] NoVig direct API integration** — dropped 2026-04-13. NoVig's developer API requires a $30k deposit to unlock OAuth credentials, which isn't viable at the current bankroll. Replaced by NoVig screenshot ingestion (see items below).
- [ ] **[P2] NoVig screenshot ingestion — MVP (in progress)** — On-demand `/novig` Discord command accepting up to 10 attachments. Claude Haiku vision extracts structured lines (market_type, side, player, odds, opponent). Auto live-vs-pretournament routing, fuzzy tournament matching with disambiguation, Yes + No side edge computation for outrights, matchups supported. Markets: Winner, Top 5, Top 10, Top 20, Make Cut, Tournament/Round Matchups. **MVP skips persistence** — computes edges directly against DG model and returns a rendered embed; user continues to log placed NoVig bets manually via Supabase (per existing memory note). Code structured so v2 persistence work is additive, not a rewrite.
- [ ] **[P3] NoVig screenshot ingestion — v2 (full pipeline integration)** — Everything the MVP skips, broken out so we can defer until the MVP proves the screenshot flow is worth integrating:
  - DB schema migration: add `side: str` column to `candidate_bets` and `bets` (for Yes/No exchange sides).
  - `CandidateBet.side` field + `to_db_dict` + every downstream consumer (edge calc, display, settlement) updated to respect side.
  - Settlement logic: a "No T20" bet wins when the player finishes OUTSIDE top-20; same inversion for each placement market. Needs test coverage parallel to existing `settle_*` tests.
  - Synthetic `book="novig"` injection into the live DG pull so the existing pipeline (course-fit, expert-picks, correlation haircut, Kelly sizing) applies to NoVig lines automatically rather than being recomputed directly.
  - `candidate_bets` persistence with `scan_type="novig_screenshot"` (plus `_live_` variant during rounds). Same supersede-prior pattern as the pretournament/preround scans.
  - `/place <N>` integration so screenshot-extracted lines become placeable candidates, mutating `bot.last_scan` the same way a `/scan` does.
  - Analytics view segmentation: exclude `*_screenshot` scan_types from the +EV ROI / calibration views by default; add a separate NoVig-only ROI view.
  - Settlement-time reminder embed for NoVig bets ("bet placed at NoVig exchange — remember to settle manually if auto-settle doesn't match by player name").
  - **Trigger for starting v2**: user has used the MVP enough to confirm the extraction + edge-surface is reliable and that persistence would remove real friction (vs. continuing the current manual logging pattern).
- [ ] **[P4] Expand course profiles** — Only 8 of ~40+ PGA Tour venues have profiles. Build profiles for upcoming tournament venues using Betsperts course stats pages. Improves course-fit signal quality for data collection phase. Steady background work; not urgent mid-season.
- [x] **[P0] Fix candidate→bet linkage** — shipped 2026-04-13 (commit `e98697a`). See "Post-Masters Fixes" above.
- [x] **[P1] Masters auto-settlement recovered + permanent fixes** — shipped 2026-04-13 (commit `84a80b7`). See "Post-Masters Fixes" above.
- [x] **Run `scripts/status.py` health check** — Done via direct Supabase query 2026-04-12.
- [x] **Verify candidate lifecycle end-to-end** — Done 2026-04-12; broken; now fixed.
- [x] **Book settlement rules** — Loaded 78 rules across 14 books/exchanges into Supabase. Start rules still unknown (no public page).

**Things explicitly NOT next, even though they're tempting:**
- Course-fit / expert-picks Kelly modifier **validation** — still needs 3-5 tournaments of joinable data. The P0 fix unblocks this for *new* tournaments but doesn't retroactively help the Masters (9 linked is fine for a first data point, not enough for validation).
- Live edge calibration / dynamic threshold — same data dependency, plus still only 2 live candidates in the DB.
- Pinnacle / PrizePicks direct integrations — niche marginal value.

---

## Next Up (awaiting data)

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

#### 3a. NoVig integration — dropped 2026-04-13

NoVig's developer API requires a $30k deposit on the platform to unlock
OAuth credentials. Not viable at the current bankroll ($1,000). Plan
archived rather than preserved here — see git history before 2026-04-13
if it becomes relevant later (if NoVig drops the deposit floor or if
bankroll grows enough to justify it).

The Odds API was reconsidered and still rejected for the same reason as
before: golf coverage is winner-only, no placement markets or matchups,
so it would not close the NoVig gap.

Lighter substitute options currently under consideration:
- On-demand `/evaluate` Discord command — user types in a NoVig line for
  a specific player + market, bot returns edge / your_prob / suggested
  stake against the DG model. Evaluates single lines, doesn't try to
  mirror the NoVig board.
- Manual `/novig` bulk entry — user types multiple NoVig lines in one
  command, system creates candidate_bets tagged `book=novig` and runs
  the full edge pipeline. More complete but higher per-scan effort.

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
