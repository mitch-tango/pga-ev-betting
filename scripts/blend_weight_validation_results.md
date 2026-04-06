# Blend-Weight Validation Results

Date: 2026-04-06
Script: `scripts/validate_blend_weights.py`
Data: OAD 278-event backtest (2020-2026), outright odds from 5 books

---

## 1. T10/T20 Favorite Tranche — Bootstrap Confidence Intervals

**Question:** Is 100% DG for T10/T20 favorites (N=593/559) significantly better than 70-80% DG, or overfitting to a small sample?

**Method:** 5,000-iteration bootstrap on log-loss, both standard (resample player-events) and clustered (resample by event to handle within-event correlation). Compared 100% DG against 80%, 70%, and 55% (old global weight).

### T10 Favorites (N=593, 227 events)

- Actual hit rate: 49.8%
- Avg DG prob: 43.6%, Avg book prob: 39.7%

| Comparison | Mean ΔLL | 95% CI | P(100%DG wins) |
|---|---|---|---|
| 100% vs 80% DG | +0.0033 | [+0.0017, +0.0050] | 100.0% |
| 100% vs 70% DG | +0.0052 | [+0.0027, +0.0076] | 100.0% |
| 100% vs 55% DG (old) | +0.0081 | [+0.0044, +0.0118] | 100.0% |

Clustered bootstrap (resample events, not players) gives nearly identical results — within-event correlation is not inflating significance.

### T20 Favorites (N=559, 222 events)

- Actual hit rate: 65.3%
- Avg DG prob: 60.1%, Avg book prob: 55.1%

| Comparison | Mean ΔLL | 95% CI | P(100%DG wins) |
|---|---|---|---|
| 100% vs 80% DG | +0.0031 | [+0.0010, +0.0051] | 99.8% |
| 100% vs 70% DG | +0.0049 | [+0.0018, +0.0079] | 99.8% |
| 100% vs 55% DG (old) | +0.0078 | [+0.0033, +0.0124] | 99.9% |

### Conclusion

**100% DG for T10/T20 favorites is statistically justified.** All 95% CIs exclude zero. The effect is consistent across both standard and clustered bootstrap, and across both T10 and T20 markets. Not overfitting.

**Interpretation:** For well-known players (win prob >= 5%), DG's model has enough data to produce probabilities that are strictly better-calibrated than any book blend. Books add noise rather than information for this tier.

---

## 2. Make-Cut — Deep Dive on 35% → 80% DG Revision

**Question:** Is the global shift from 35% to 80% DG for make-cut an artifact of different data coverage between the original OAD calibration and this outright odds analysis?

**Dataset:** 13,296 player-events across 199 events (2020-2026), 776 unique players.

### Cross-Validation (5-fold, by event)

| Fold | Train Optimal | Test LL @ best | Test LL @ 35% | Test LL @ 80% |
|---|---|---|---|---|
| 1 | 90% DG | 0.622126 | 0.622253 | 0.621909 |
| 2 | 90% DG | 0.618362 | 0.618441 | 0.618130 |
| 3 | 80% DG | 0.617554 | 0.620940 | 0.617554 |
| 4 | 85% DG | 0.620161 | 0.621730 | 0.620184 |
| 5 | 85% DG | 0.617113 | 0.618818 | 0.617166 |
| **Avg** | **86% DG** | **0.619063** | **0.620437** | **0.618989** |

80% DG beats 35% DG on held-out data in all 5 folds. Average train-optimal is 86% DG.

### Temporal Stability

| Period | N | Optimal DG% | LL @ 35% | LL @ 80% |
|---|---|---|---|---|
| 2020-2022 | 6,727 | 75% | 0.631679 | 0.630948 |
| 2023-2026 | 6,569 | 95% | 0.608786 | 0.606495 |

Both periods favor high DG weight over 35%. The optimal drifts upward in the later period (more DG data = better model?), but 80% is comfortably inside the good range for both.

### Per-Event Sign Test

80% DG wins 105/199 events (53%), sign test p=0.48. Event-level differences are small and noisy — neither weight dominates decisively on a per-event basis.

### Book-Count Sensitivity

| Filter | N | LL @ 35% | LL @ 80% | Winner |
|---|---|---|---|---|
| >= 1 book | 13,296 | 0.620368 | 0.618867 | 80% DG |
| >= 3 books | 2,461 | 0.564817 | 0.565711 | 35% DG |

**Notable finding:** When restricting to player-events with >= 3 book quotes (better consensus quality), 35% DG slightly edges out. The 80% DG advantage is concentrated in sparse-book events where the book consensus is noisy/unreliable.

### Conclusion

**The 35% → 80% revision is not a data coverage artifact.** Cross-validation confirms it generalizes, and the direction is consistent across time periods. However:

1. The improvement is modest (ΔLL ≈ 0.0015 on held-out data)
2. The true optimal is in the 75-95% DG range; 80% is a reasonable midpoint
3. DG's advantage is partly driven by events with thin book coverage — when book consensus is based on 3+ books, the gap narrows or disappears
4. This suggests the make-cut market has less book consensus value overall, not that the original 35% was miscalibrated per se

**Current setting of 80% DG is validated.** No change needed.

---

## Summary of Implemented Weights (confirmed)

| Market | Favorite | Mid | Longshot | Status |
|---|---|---|---|---|
| T10/T20 | 100% DG | 55% DG | 45% DG | **Validated** (bootstrap CI) |
| Matchup | 60% DG | 30% DG | 0% DG | Validated (prior analysis) |
| Make Cut | 80% DG (global) | — | — | **Validated** (CV, temporal) |
| Win | 35% DG (global) | — | — | Unchanged (temporally unstable) |
