# Question Triage: Answerable Now vs. Needs Data

Last updated: 2026-04-06 (Gap A partially resolved same day)

Sources: `model-improvement-questions.md`, `profitability-audit-checklist.md`

---

## Part 1: Answerable With Existing Data

These can be answered today by querying Supabase, re-running existing scripts, or reading the codebase. No new instrumentation needed.

### Research Validity (re-run and verify)

- Can the main backtests be rerun today and reproduce the same high-level conclusions?
- Can the blend-weight validation be rerun today and reproduce the same conclusions?
- Were the current weights selected on training data and evaluated on held-out or temporally separated data?
- Did any live-only assumptions leak into pre-tournament calibration?
- Are the reported improvements large enough to matter economically, not just statistically?
- Which findings are robust across time splits, and which are fragile?
- Does the full test suite run cleanly under a pinned supported Python version?

**How:** `python scripts/run_backtest.py --all`, `python scripts/validate_blend_weights.py --analysis all`, `pytest`

### Live Proof (query settled bets)

- How many settled bets do we have overall?
- How many settled bets do we have by is_live, market_type, book, and tranche?
- Is realized ROI positive overall?
- Is realized ROI positive in the largest segments?
- Are realized drawdowns acceptable relative to the current Kelly and exposure rules?

**How:** Use existing views `v_roi_by_market`, `v_roi_by_book`, `v_roi_by_edge_tier`, `v_bankroll_curve`. Basic SQL against `bets where outcome is not null`.

### CLV (partial — depends on coverage)

- What percentage of settled bets have valid clv populated?
- Is average CLV positive overall?
- Is average CLV positive in the largest segments?
- Are higher-edge buckets producing better CLV and ROI than lower-edge buckets?

**How:** `v_clv_weekly`, `v_clv_by_tranche`, plus the coverage check:
```sql
select count(*) as total, count(*) filter (where clv is not null) as has_clv
from bets where outcome is not null;
```
**Caveat:** If CLV coverage is low (<70%), the CLV answers are directional but not trustworthy. That becomes a data gap (see Part 2).

### Segmentation (query existing fields)

- Should we treat the five segments as separate businesses?
- Is one small segment responsible for most of the P&L?

**How:** `is_live`, `market_type`, and `book` are all stored on `bets`. The segmentation SQL from the audit checklist works today.

### Settlement & Book Rules

- Are settlement rules correct for every supported book x market_type pair?

**How:** Read `book_rules` table and cross-check against `src/core/settlement.py` logic. Code review, not data collection.

### Risk (query existing data)

- Are quarter-Kelly and the current exposure caps producing acceptable volatility?
- Is performance still attractive after accounting for bankroll concentration and correlated player exposure?

**How:** `v_bankroll_curve`, `v_weekly_exposure`, plus manual drawdown analysis from `bankroll_ledger`.

### Prediction Markets (partial)

- Are fee-adjusted ask prices, not midpoints, being used consistently in evaluation?
- Are liquidity and spread filters strong enough to prevent fake edges?

**How:** Code review of `pull_kalshi.py`, `pull_polymarket.py`, `pull_prophetx.py`. These are implementation questions, not data questions.

### Course-Fit Signal Validation

- Can we backtest whether Betsperts SG signals improve on raw DG probabilities?

**How:** Historical DG predictions exist in `data/raw/backtest/predictions/` (103 tournaments). Betsperts data can be pulled per-tournament. This is a new analysis script, not a new data source.

---

## Part 2: Not Answerable — Needs Additional Data

### Gap A: Candidate-to-Bet Linkage (PARTIALLY SOLVED)

**Status:** Core wiring is complete as of 2026-04-06. Linkage is wired in for normal flows, but is still conditional on tournament context in live/preround — if no tournament is detected from existing bets and `--tournament` is not provided, bets will still be logged with `candidate_id=None`. This is intentional: live/preround are time-sensitive workflows where blocking bet placement over a metadata gap is worse than degraded tracking.

**What's working now:**

- `run_pretournament.py` always resolves or creates a tournament record (including fallback when DG event ID is missing)
- `run_preround.py` and `run_live_check.py` insert candidates when tournament context is available, with fallback creation from `--tournament` flag
- `candidate_id` is passed through to `insert_bet()` and triggers `update_candidate_status("placed")`
- Skipped/unselected candidates are marked with `status='skipped'` and `skip_reason`
- `candidate_bets` stores full probability breakdown: `dg_prob`, `book_consensus_prob`, `your_prob`, `tranche`, `all_book_odds` (JSONB)
- Malformed input early returns mark all candidates as skipped (no stuck-pending records)

**Known limitation:** When live/preround run without tournament context and without `--tournament`, bets proceed but with no candidate linkage. A warning is printed. This is acceptable for operational continuity but means linkage coverage will be <100% in practice.

**Remaining work:**

- Backfill: existing bets where `candidate_id is null` need a fuzzy-match backfill on (tournament_id, player_name, market_type, bet_timestamp ≈ scan_timestamp)
- Monitoring: add a monthly check to verify linkage stays healthy:
  ```sql
  select count(*) filter (where candidate_id is null) as unlinked
  from bets where bet_timestamp > '2026-04-07';
  ```
- End-to-end testing: the interactive + DB-backed paths don't yet have automated tests covering candidate serialization, lookup matching, or status transitions

### Gap B: Closing Odds Coverage (PARTIALLY SOLVED)

**Status:** `run_closing_odds.py` now pulls prediction market closing odds (Kalshi, Polymarket, ProphetX) alongside DG sportsbook odds. Matchup closing capture auto-detects round days (Thu-Sun) instead of requiring `--matchups`. A `v_clv_coverage` monitoring view is defined in schema.sql.

**What's working now:**

- Prediction market odds (Kalshi outrights + matchups, Polymarket outrights, ProphetX outrights + matchups) are merged into closing snapshots
- Matchup/3-ball closing capture runs automatically on Thu-Sun
- `v_clv_coverage` view shows weekly CLV coverage percentage

**Remaining work:**

- **Automation** — Schedule `run_closing_odds.py` via cron to run ~30 min before each round's first tee time (typically 7:00-7:30am ET Thu-Sun). This is the last manual step.
- **Deploy `v_clv_coverage` view** — Run the new view definition in Supabase SQL Editor

### Gap C: Execution Slippage Tracking (SOLVED)

**Status:** Two new views defined in schema.sql:

- `v_execution_slippage` — Compares scanned vs. placed odds by market/book/is_live. Shows avg probability slippage, % of bets at worse odds, and avg odds change %.
- `v_candidate_fill_rate` — Shows placed/skipped/pending counts by scan_type and market_type, with fill rate % and avg edge for placed vs. skipped candidates.

**Remaining work:**

- **Deploy views** — Run the new view definitions in Supabase SQL Editor
- Candidate skip tracking now piggybacks on Gap A (skipped candidates get `skip_reason` populated)

### Gap D: DG-Only / Books-Only Ablation Probabilities (SOLVED BY GAP A)

**Status:** Now that Gap A wiring is in place, `dg_prob` and `book_consensus_prob` are written to `candidate_bets` via `to_db_dict()` at scan time. For bets placed going forward with candidate linkage, ablation data is available. Historical bets without `candidate_id` will need the backfill described in Gap A.

**Questions this blocks:**

- If we rerun as current_blend / dg_only / books_only, which wins by CLV, ROI, and calibration?
- In win markets, does removing books hurt materially?
- In matchup longshots, does DG add signal or mostly add noise?
- All live-specific DG vs exchange ablation questions

**Fix plan:**

Fully solved by Gap A — once `insert_candidates()` is called, `dg_prob` and `book_consensus_prob` are both written. No additional schema changes needed.

### Gap E: Live Threshold Optimization Data

**What's missing:** To answer whether 8% is the right live threshold, or whether it should vary by market type / round / time of day, we need enough settled live bets with `edge`, `clv`, and `outcome` — segmented by round and approximate time.

**Questions this blocks:**

- Is the current 8% live threshold too high, too low, or roughly correct?
- Does the optimal live threshold differ by market type?
- Does the optimal live threshold differ by round or time of day?
- How much of the live edge is really stale-line capture rather than stable predictive edge?

**Fix plan:**

1. **Round number is already tracked** on `candidate_bets.round_number` and can be joined to bets via Gap A linkage
2. **Time of day** — `bet_timestamp` already exists on `bets`; extract hour for time-of-day analysis
3. **Stale-line detection** — Compare `scanned_odds_decimal` to the exchange mid-market at scan time. If a sportsbook price is far from exchange consensus, the edge may be stale-line, not predictive. This requires storing `exchange_mid_at_scan` — a new field on `candidate_bets`
4. **Minimum sample:** Need ~100+ settled live bets before this analysis is meaningful

**Effort:** Small — add `exchange_mid_at_scan` to candidate_bets insert; rest is analysis once data accumulates.

### Gap F: Prediction Market Separate Evaluation

**What's missing:** Prediction market bets are in `bets` with `book` set to kalshi/polymarket/prophetx, but there's no dedicated reporting cut, no separate threshold tuning, and no fee-adjusted CLV.

**Questions this blocks:**

- Should prediction-market thresholds be tuned separately from sportsbook thresholds?
- Do Kalshi, Polymarket, and ProphetX behave similarly enough to share one threshold?
- Are prediction markets helping consensus formation, or should they mostly be treated as execution venues?

**Fix plan:**

1. **Segment view** — Add prediction market segment to the business-segment SQL (already defined in audit checklist)
2. **Fee-adjusted CLV** — For prediction markets, CLV should account for taker fees. Add a `fee_adjusted_clv` computed column or view:
   ```sql
   case when book in ('kalshi','polymarket','prophetx')
     then clv - 0.002  -- approximate taker fee
     else clv
   end as fee_adjusted_clv
   ```
3. **Separate threshold config** — Once there are 50+ settled prediction market bets, evaluate whether the sportsbook thresholds are right for exchanges

**Effort:** Minimal — one view + optional config split later.

### Gap G: Start "Including Ties" Placement Product

**What's missing:** Start offers two placement products: (1) standard dead-heat rules and (2) "including ties" where a T20 shared among five players still pays full value with no dead-heat reduction. The current pipeline treats Start as a dead-heat book. The "including ties" product is structurally identical to Kalshi/Polymarket binary contracts — it should settle the same way (full payout, no reduction).

**Questions this blocks:**

- Is there +EV in the "including ties" product that we're leaving on the table?
- Should Start "including ties" be modeled as a separate book entry (e.g., `start_incl_ties`) with `tie_rule="win"` like Kalshi?
- How do "including ties" odds compare to dead-heat odds at Start — is the juice difference consistent enough to derive one from the other?
- Can we use the "including ties" odds as an additional signal for binary-settlement probability (alongside Kalshi/Polymarket)?

**Fix plan:**

1. **Parser support** — Extend Start parser to distinguish the two products (likely different market IDs or labels on the site)
2. **Config** — Add `start_incl_ties` to `NO_DEADHEAT_BOOKS` and `BOOK_WEIGHTS` with appropriate weight
3. **Edge calc** — Route `start_incl_ties` through the no-dead-heat path (same as Kalshi/Polymarket)
4. **Evaluation** — Compare edges from both Start products over ~50+ placement bets to determine which is more profitable

**Effort:** Medium — parser + config + edge routing changes, plus data collection period.

### Gap H: Placement Market Vig vs Edge Viability

**Investigation update (2026-04-07):** Re-ran Gap H against the cached Masters snapshot in `data/raw/masters-2026/2026-04-06_2212/*.json` plus `data/raw/masters-2026/start_odds_2026-04-07.txt`.

**Bottom line:**

- No sportsbook `win`, `t10`, or `t20` edges survive in this snapshot, even at the lowest-vig books.
- The `make_cut` "underround" is mostly an artifact. Two things were wrong at once:
  1. book coverage is incomplete at some books, especially bet365
  2. `devig_independent(... expected_outcomes=65)` is calibrated for a standard PGA Tour cut, but the Masters uses **top 50 and ties** after 36 holes, not 65 and ties ([BetMGM explainer, 2026-04-07](https://sports.betmgm.com/en/blog/pga/masters-cut-line-how-is-the-cut-determined-at-the-masters-bm10/))
- DG's own Masters `make_cut` probabilities sum to `53.60`, which is a much better event-specific expectation than `65.00`.
- When `make_cut` is re-run with `expected_outcomes=53.60` (or `50`), the surviving bet365 make-cut candidates disappear.

#### Q1: Is the make_cut underround real?

**No, not after correcting for both coverage and event cut rules.**

| Book | Lines | Missing | Raw sum | Vs 65 | DG-imputed sum | Vs DG 53.60 |
|---|---:|---:|---:|---:|---:|---:|
| bet365 | 39 | 52 | 30.15 | -53.6% | 54.38 | +1.4% |
| betmgm | 84 | 7 | 54.98 | -15.4% | 56.04 | +4.5% |
| draftkings | 90 | 1 | 57.80 | -11.1% | 57.97 | +8.1% |
| start | 91 | 0 | 58.13 | -10.6% | 58.13 | +8.4% |
| fanduel | 0 | 91 | — | — | — | not in DG make_cut feed |
| bovada | 0 | 91 | — | — | — | not in DG make_cut feed |

- Against the hard-coded `65`, every make-cut board looks like an underround.
- Against the event-correct Masters expectation (`DG sum = 53.60`, roughly consistent with top-50-and-ties), every board becomes a modestly positive-hold market instead.
- Re-running `make_cut` with `expected_outcomes=53.60` or `50` yields **zero** make-cut candidates in this snapshot. The apparent bet365 value was a denominator bug, not true +EV.

#### Q2: Is 30-48% overround normal for golf placement?

**It is normal for retail golf placement boards, but not for standard two-way prop markets.** Compared to a typical two-way market:

- `-110/-110` hold = `4.8%`
- `-120/-120` hold = `9.1%`
- `-130/-130` hold = `13.0%`

So even the best Masters T20 board in this snapshot (`fanduel +13.3%`) is roughly as expensive as a `-130/-130` two-way market, and the worst placement boards are far fatter than that.

**All-books overround (Masters snapshot):**

| Book | Win | T10 | T20 |
|---|---:|---:|---:|
| bet365 | +54.5% (90/91) | +31.2% (90/91) | +30.7% (90/91) |
| betcris | +29.0% (91/91) | +28.0% (91/91) | — |
| betmgm | +45.9% (91/91) | +49.9% (91/91) | +34.0% (91/91) |
| betonline | +23.3% (91/91) | +19.1% (91/91) | +15.9% (91/91) |
| betway | +59.7% (91/91) | +31.3% (91/91) | +28.9% (91/91) |
| bovada | +39.1% (91/91) | +38.5% (90/91) | +33.9% (90/91) |
| caesars | +53.9% (91/91) | +32.1% (91/91) | — |
| draftkings | +40.1% (90/91) | +24.1% (90/91) | +22.1% (90/91) |
| fanduel | +41.4% (91/91) | +15.8% (80/91) | +13.3% (91/91) |
| pinnacle | +23.6% (72/91) | — | — |
| pointsbet | +43.0% (91/91) | +24.6% (91/91) | +14.8% (91/91) |
| skybet | +103.6% (90/91) | — | — |
| start | +21.4% (38/91) | +23.8% (82/91) | +22.1% (91/91) |
| unibet | +35.6% (90/91) | +26.9% (90/91) | +21.8% (90/91) |
| williamhill | +53.7% (91/91) | +31.5% (91/91) | +27.1% (91/91) |

- Sharp-ish books in this snapshot are `betonline` for `win`/`t10`/`t20`, `pinnacle` for `win`, and `fanduel` / `pointsbet` for `t20`.
- Retail `t10`/`t20` holds in the 25-35% range are common here; `30%+` is high but not anomalous for golf placement.

#### Q3: Is the independent de-vig methodology correct?

**Yes for `win`/`t10`/`t20`; not for Masters `make_cut` with `expected_outcomes=65`.**

- `devig_independent()` is already a **multiplicative** de-vig method: `fair_prob = raw_prob * (expected / raw_sum)`.
- `expected_outcomes=10` and `20` are correct for `t10` and `t20`.
- `expected_outcomes=65` is **not** event-aware for majors / special cut rules. That is the real bug.
- A Shin-style method is not a clean fit here because placement yes/no ladders are **not mutually exclusive** markets.

Different de-vig will not rescue T10/T20 anyway:

- T10 must clear about `raw_edge >= 0.104` to survive current thresholds (`0.06` min edge + `0.044` dead-heat reduction).
- T20 must clear about `raw_edge >= 0.098` (`0.06` + `0.038`).
- Best observed raw edges in this snapshot are nowhere close:
  - T10 best raw edge: `+0.0053`
  - T20 best raw edge: `+0.0081`

So the limiting factor is market hold + dead-heat, not the exact de-vig transform.

#### Q4: Which book × market combos produce viable edges?

**None of the sportsbook placement markets are viable in this snapshot once make-cut is corrected.**

- `win`: zero candidates at every sportsbook. Even the sharpest available books (`betonline +23.3%`, `pinnacle +23.6%`, `betcris +29.0%`) still leave best raw edges at ~0.
- `t10`: zero candidates at every sportsbook. Lowest-vig books are `fanduel +15.8%` and `betonline +19.1%`, but best adjusted edges remain negative (`fanduel -0.0414`, `betonline -0.0465`, `betcris -0.0461`).
- `t20`: zero candidates at every sportsbook. Lowest-vig books are `fanduel +13.3%`, `pointsbet +14.8%`, and `betonline +15.9%`, but best adjusted edge is still `fanduel -0.0299`.
- `make_cut`: with current config (`expected=65`), false positives appear at bet365. With corrected expected outcomes (`53.60` or `50`), there are **zero** make-cut candidates in this snapshot.

#### Q5: Should the pipeline dynamically skip high-vig book × market combos?

**Yes, after fixing make-cut expected outcomes.**

Recommended first-pass vig guard:

1. `win`: skip if overround > `30%`
2. `t10`: skip if overround > `20%`
3. `t20`: skip if overround > `18%`
4. `make_cut`: skip if corrected overround > `10%` and only after event-aware denominator / imputation

This keeps the lowest-hold books (`betonline`, `fanduel`, `pointsbet`, sometimes `pinnacle`) while cutting clearly non-bettable retail boards that only add noise to consensus.

#### Action items

1. **Make `make_cut` expected outcomes event-aware** — the Masters should not use `65`. This is a real bug, not a tuning issue.
2. **Add the vig guard** — exclude obviously unusable high-vig book × market combinations before they distort consensus.
3. **Treat Start Gap G separately** — the captured Start file shows standard `TOP 10 FINISH` / `TOP 20 FINISH` headers, not the separate "including ties" product.
4. **For this Masters snapshot, skip all sportsbook `win` / `t10` / `t20` boards.** No viable edges survive, even at the sharpest books.

**Effort:** Small-medium — one make-cut denominator fix plus a book-level vig filter.

---

## Priority Order

| Priority | Gap | Status | Remaining | Unlocks |
|----------|-----|--------|-----------|---------|
| 1 | **A: Candidate-to-bet linkage** | **Done** | Backfill old bets, e2e tests | Ablations, tranche attribution, fill rate |
| 2 | **B: Closing odds automation** | **Mostly done** | Schedule cron job, deploy view | Trustworthy CLV across all bets |
| 3 | **C: Execution slippage view** | **Done** | Deploy views to Supabase | Slippage analysis, fill rate |
| 4 | **D: Ablation probabilities** | **Done** (solved by Gap A) | — | DG vs Books comparison |
| 5 | **E: Live threshold data** | Not started | Add exchange_mid_at_scan field | Live threshold optimization |
| 6 | **F: Prediction market evaluation** | Not started | One segment view | Separate PM reporting |
| 7 | **G: Start "including ties" product** | Not started | Parser + config + edge routing | Capture +EV from binary-style placement at Start |
| 8 | **H: Placement vig vs edge viability** | Investigated | Ship event-aware make_cut denominator + vig guard | Determine which placement markets are actually bettable |

**Gaps A-D are resolved in code.** The remaining deployment steps are: deploy 3 new SQL views to Supabase (`v_clv_coverage`, `v_execution_slippage`, `v_candidate_fill_rate`) and schedule `run_closing_odds.py` via cron. After that, the next real analysis work is Gap E (live threshold optimization) and Gap F (prediction market evaluation), both of which need data to accumulate before they're actionable.
