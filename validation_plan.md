# PGA +EV System — Validation Plan

Last updated: 2026-04-13

A consolidated checklist for validating the system after the post-Masters
audit and the subsequent P3 work (market-aware dead-heat exemptions,
arb-legs as placeable candidates). Phases are data-gated — anything
below Phase 1 is on a timer, not a schedule.

Scope note: this document covers **testing what's already shipped**.
Ongoing priorities (P4 course profiles, NoVig integration, all
awaiting-data items) live in `roadmap.md` and are intentionally not
duplicated here.

---

## Phase 1 — Pre-RBC bench checks (week of 2026-04-13)

Goal: validate recently shipped code against current DB + DG state
*before* RBC Heritage is live, so Phase 2 produces clean signal instead
of mixed code/data failures.

- [ ] **1.1 Arb-legs smoke test**
  - Run `_run_pretournament_scan("pga")` (or equivalent CLI) against
    whatever DG has cued up.
  - Expect: if the pulled matchups contain any cross-book arbs,
    `candidate_bets` gets new rows with `scan_type='pretournament_arb'`.
  - Verify: each row's `all_book_odds` JSONB contains `arb_margin`,
    `arb_legs`, `arb_leg_index`, `arb_settlement_warning`.
  - Verify: sibling legs of the same arb have distinct dedupe keys
    (`player_name` + `opponent_name` differ), so nothing was dropped
    by `persist_candidates` dedupe.
  - Fallback if no arbs detected live: the unit tests in
    `tests/test_arb.py` already cover the mapping; flag "no live data
    yet, rely on unit coverage" and revisit in Phase 2.

- [ ] **1.2 Dead-heat exemption spot check**
  - Pull recent `candidate_bets` rows for `market_type IN ('t10','t20')`
    grouped by `best_book`.
  - Compare exempt-book representation (BetMGM, Pinnacle, ProphetX) to
    a pre-`cdfe66e` baseline (pick a March scan from the same market).
  - Expect: more candidates surfacing from exempt books post-fix,
    because the flat dead-heat haircut is no longer suppressing them.

- [ ] **1.3 Monitoring views populate**
  - Query `v_clv_coverage`, `v_execution_slippage`,
    `v_candidate_fill_rate` — the three views added with the candidate
    lifecycle work.
  - Expect: rows return, NULL joins only where legitimately expected
    (e.g., NoVig manually-logged bets with `candidate_id IS NULL`).
  - Flag: any unexpected NULL linkage from Discord-placed bets (the P0
    fix from `e98697a` should have closed this).

- [ ] **1.4 Bankroll reconciliation**
  - Call `db.get_bankroll()`.
  - Compare against actual offshore sportsbook balance + NoVig balance
    adjusted to the $1,000 real bankroll (see memory:
    `user_bankroll.md`).
  - Expected value after Masters settlement: ~$1,061.68 (+$21.68
    session P&L on $1,040 starting bankroll — check the math matches
    what's in the DB).

- [ ] **1.5 Streamlit dashboard sanity (manual — user)**
  - Load all 4 pages: Active Bets, Performance, Bankroll, Model Health.
  - Expect: Masters bets visible, no broken Plotly charts, no empty
    panels where there should be data.
  - Flag: anything that returns NULL or a broken query — same failure
    modes as 1.3.

**Exit criterion**: all 1.1–1.4 green (or 1.1 explicitly deferred to
Phase 2 with justification). 1.5 is user-verified.

### Phase 1 execution — 2026-04-13

- **1.1 — DEFERRED to Phase 2.** DG rolled Masters to "live" staleness
  guard; RBC field not loaded yet. Unit coverage in `tests/test_arb.py`
  (8 tests) stands in until Tue/Wed. *Related gap surfaced:*
  `scripts/run_pretournament.py` CLI path still calls
  `detect_matchup_arbs` + `format_arb_table` only — no arb-leg
  persistence. See fix item #1 below.
- **1.2 — DEFERRED.** Only 6 T10/T20 candidates in DB (all bet365 /
  polymarket), zero exempt-book rows. Fix effect only observable on
  next real scan. Revisit in Phase 2.
- **1.3 — PASS with two findings.** All three views populate.
  - *Finding A (CLV gap):* `v_clv_coverage` = 8/13 (62%). The linked
    Masters bet `Kitayama, Kurt` on `tournament_matchup` has
    `clv=NULL` because `scripts/run_closing_odds.py` only captures
    `round_matchup` and `3_ball` closing snapshots. `tournament_matchup`
    has no closing-odds path at all, so its CLV is structurally NULL.
    See fix item #2.
  - *Finding B (stale pending):* 40 pretournament + 2 live
    `candidate_bets` rows are stuck at `status='pending'` from
    2026-04-07 through 2026-04-10 Masters scans. Root cause: multiple
    exploratory CLI scans, no auto-expiration of superseded candidates.
    `v_candidate_fill_rate` is permanently underestimating fill rate
    as a result. See fix items #3 and #4.
- **1.4 — PASS.** `db.get_bankroll() = $1,061.68`, exact match to the
  post-Masters expected value in the roadmap.
- **1.5 — user-verified.**

### Phase 1 follow-up fixes (prioritized)

Ordered shortest → longest implementation effort.

- [x] **#3 Stale-pending cleanup (one-shot).** Mark the 40 + 2 stuck
  rows as `skipped` with `skip_reason='superseded_backfill'` so
  `v_candidate_fill_rate` reflects reality.
- [x] **#1 CLI arb persistence.** Port the bot-path arb-leg persistence
  into `scripts/run_pretournament.py` so CLI runs write
  `pretournament_arb` rows too. Same helper already lives in
  `src/core/arb.arb_legs_to_candidates`.
- [x] **#4 Recurring stale-pending prevention.** At the start of each
  scan, auto-expire prior `status='pending'` candidates for the same
  (`tournament_id`, `scan_type`) batch before inserting the new one.
  Applies to both bot and CLI paths.
- [x] **#2 Tournament-matchup CLV.** Chose option (a): extend the
  closing-odds pipeline to snapshot tournament matchups at R1 tee
  time. Added `pull_closing_tournament_matchups` wrapper in
  `src/pipeline/pull_closing.py`; extended
  `build_closing_matchup_snapshots` with a `tournament_matchups` kwarg
  that emits snapshots tagged `market_type='tournament_matchup'` and
  carries the opponent name for matcher keying. In
  `scripts/run_closing_odds.py`, tournament-matchup capture is gated
  to Thursday only (day_of_week == 3) via a dedicated code path —
  independent of the Thu-Sun round-matchup gate — with a
  `--tournament-matchups` flag for missed-Thursday recovery.
  Kalshi + ProphetX H2H data is merged into both round and tournament
  matchup lists when either is captured. CLV matching path
  (`match_closing_to_bets`) required no changes: it keys on
  `(market_type, player_name)` so the new snapshots are picked up
  automatically once stored. 5 new tests in
  `tests/test_closing_snapshots.py` cover the round-only,
  tournament-only, mixed, empty, and missing-player branches.
  **Reason for choice**: matchup volume is expected to grow, so
  exempting tournament_matchup from CLV would cost real signal over
  time. B1 Thursday-gated auto-capture keeps the user's existing
  closing-odds cadence intact. **How to apply**: run
  `scripts/run_closing_odds.py` on Thursday morning before R1 tee
  times; tournament matchups snapshot once, round matchups continue
  to snapshot Thu-Sun as before.

---

## Phase 2 — RBC Heritage live (2026-04-16 to 2026-04-20)

Goal: produce the second clean data point across all recent fixes, with
a real tournament driving the pipeline end-to-end.

- [ ] **2.1 Full lifecycle trace on at least one bet**
  - Scan → embed → `/place` → settlement → CLV.
  - Verify `bets.candidate_id IS NOT NULL` (P0 fix from `e98697a`
    proving itself in the Discord path, not just the backfill).
  - Verify CLV computation populates once the round closes.

- [ ] **2.2a Closing-odds capture (Thu 2026-04-16, 6am ET)**
  - New scheduled task in `_scheduled_alerts` fires at
    `ALERT_CLOSING_HOUR` (6am ET) Thu-Sun. Thursday also captures
    tournament-matchup closing lines (one-shot for the week).
  - Verify Thu run stores outright + round matchup + 3-ball +
    tournament matchup snapshots in `odds_snapshots`.
  - Verify Discord embed posts with counts + CLV summary.
  - Verify Fri-Sun runs omit tournament matchups (no duplicate
    snapshots).
  - Verify startup catch-up fires if bot boots after 6am on a
    tournament day.

- [ ] **2.2 Auto-settlement at Sun 10pm ET (2026-04-19)**
  - Watch the scheduled hook fire.
  - Verify results come from the archive-first path
    (`pull_results.fetch_archived_results`), not the live
    field-updates endpoint.
  - If bot is offline at 10pm, confirm startup catch-up settles on
    next restart rather than waiting for the next tournament week.
  - Cut opponents in matchups: confirm the active player's bet
    resolves to win/loss normally (not `wd_rule` void).

- [ ] **2.3 Live monitor volume (P2)**
  - Track over R1–R4: scan count, alert count, % new-vs-repeat edges,
    heartbeat image cadence.
  - Compare against Masters R1–R4 volume to judge whether the
    heartbeat + staleness fixes changed the signal/noise ratio in the
    intended direction.
  - Decision point: after this tournament, P2 is either closed or
    needs another iteration.

- [ ] **2.3a NoVig `/novig` command end-to-end**
  - First real-world use of the Claude-vision NoVig screenshot flow
    (see roadmap: NoVig screenshot ingestion — MVP).
  - Drop 3-5 real RBC screenshots into the bot, verify extraction
    accuracy against the source images (player names, Yes/No odds,
    market type inference, round number detection for matchups).
  - Verify live-vs-pretournament auto-routing — if triggered during a
    round, DG column should be overridden with live predictions.
  - Verify unmatched-player reports call out extraction errors vs.
    roster misses (LIV players, field qualifiers).
  - Confirm Yes + No side math looks sensible on a few manually-
    checked candidates.
  - Decision point after a few uses: does the MVP cover the decision-
    support need, or do we need the v2 scope (persistence, /place,
    full pipeline with course-fit / expert-picks / correlation)?
    The answer drives whether to start v2 or leave it parked.

- [ ] **2.4 Arb legs in the wild**
  - If any cross-book arbs trigger during scans, confirm:
    - `/place <N>` on a single leg succeeds.
    - Success embed shows the sibling-leg reminder with correct
      book/odds/stake per leg.
    - `candidate_bets` has the full arb persisted with the
      `*_arb` scan_type.
  - If no arbs trigger, this gets deferred to the next tournament —
    don't force a synthetic arb.

- [ ] **2.5 Dead-heat exemption — did it actually fire?**
  - Scan `candidate_bets` during the week for any T10/T20 rows on
    exempt books (BetMGM / Pinnacle / ProphetX) that *would have*
    been below threshold under the old flat-haircut logic.
  - These are the candidates the fix was designed to unblock. Count
    them. Zero is a valid result, but should trigger a "did the fix
    reach production" sanity check.

---

## Phase 3 — Post-RBC retrospective (Mon 2026-04-20)

Goal: convert one week of live data into verdicts.

- [ ] **3.1 P2 live monitoring verdict** — close or iterate.
- [ ] **3.2 Arb leg post-mortem** — spot-check every `*_arb` row
  written during the week for field correctness, even if the user
  didn't place any.
- [ ] **3.3 Candidate→bet link rate** — `v_candidate_fill_rate`
  should show 100% link rate for Discord-placed bets this week.
  Anything less = the P0 fix has an edge case.
- [ ] **3.4 Tournament summary** — did the post-tournament recap
  auto-post to Discord? Accurate aggregates?

---

## Phase 4 — Data-accumulation milestones (not time-gated)

Listed so we know exactly what we're waiting on and don't start early.

| Milestone | Unlocks |
|-----------|---------|
| 3 linked tournaments | Preliminary course-fit + expert-picks signal analysis (noise check, not validation) |
| 5 linked tournaments | Full course-fit + expert-picks validation per roadmap §0/§0b. Decide on Kelly modifier. |
| ~50 settled linked bets | Weight/book evaluation Phase 3 (live tranche analysis) per roadmap §1 |
| ~30 live scan candidates | Live edge calibration Phase 1 per roadmap §4 |

Current state (2026-04-13 post-Masters): 13 settled bets (9 linked),
2 live scan candidates. All four milestones are a long way off — do
not attempt validation work against this sample.
