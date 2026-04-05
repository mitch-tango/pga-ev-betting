# Integration Notes — External Review Feedback

## Suggestions INTEGRATED

### 1. Use midpoint for consensus, ask for edge (Both reviewers)
**What:** Use `(yes_bid + yes_ask) / 2` as Kalshi's consensus probability signal. Use raw `yes_ask` for bettable edge calculation.
**Why:** Both reviewers correctly identified that ask prices include the spread. Summing ask prices across a 150-player field will exceed 1.0, causing the power devig to incorrectly compress Kalshi probabilities. Midpoint is a better estimate of "true" market probability.
**Impact:** Changes sections 5.1, 5.2, 6.2 of the plan. Need to fetch both bid and ask for each market.

### 2. Add bid-ask spread filter alongside OI (Both reviewers)
**What:** Add a max spread threshold (e.g., $0.05) as an additional liquidity filter beyond OI.
**Why:** OI can be high with an empty or wide orderbook. A tight spread is a better signal of actionable liquidity.
**Impact:** Add `KALSHI_MAX_SPREAD = 0.05` to config. Filter logic in pull_kalshi.py.

### 3. Block stale Kalshi tournament markets in pre-round runs (Gemini)
**What:** During `run_preround.py` (mid-tournament), only pull Kalshi data if live DG predictions are also being used. Don't compare live Kalshi prices against stale pre-tournament DG model.
**Why:** Kalshi tournament-long markets trade live during the event. Comparing live prices to stale pre-tournament DG probs would create massive false positive edges.
**Impact:** Changes section 8.2. Pre-round runs skip Kalshi tournament markets unless paired with live DG data.

### 4. Validate price units (OpenAI)
**What:** Assert Kalshi prices are in the 0–1 range. If values are 0–100, divide by 100.
**Why:** Protects against API format changes or misinterpretation of units.
**Impact:** Small validation step in the client or pipeline module.

### 5. Avoid per-market orderbook calls — use bulk endpoint (Both reviewers)
**What:** Check if `GET /markets?event_ticker={ticker}` returns bid/ask in the response. Only call individual orderbook endpoints for markets that pass initial filtering.
**Why:** 150 players × 3 markets = 450 individual calls would be slow and risk rate limits.
**Impact:** Changes section 3.2 and 5.1. Prioritize bulk market data; orderbook only for final candidates.

### 6. Kalshi dead-heat rules for T10/T20 (Gemini)
**What:** Investigate and document Kalshi's actual dead-heat settlement for top-N markets rather than assuming void.
**Why:** Golf T10/T20 ties are common. Kalshi likely settles YES if player finishes T10 or better (including ties), not void.
**Impact:** Updates section 7. Need to verify actual Kalshi contract language. Most likely: T10 settles YES if official finish position is 10 or better (ties included = YES), so `tie_rule` should be `'win'` not `'void'`.

## Suggestions NOT integrated

### Leave-one-out consensus for edge calculation (OpenAI #15)
**Why not:** The existing system already computes edge as `your_prob - book_implied` where `your_prob` is the blend of DG model + book consensus. This "circularity" exists for all books (DK's probability influences consensus which is then compared against DK's line). It's a deliberate design choice — the consensus represents the market's best estimate, and edge is found vs individual book deviations from that consensus. Changing this for Kalshi alone would be inconsistent.

### Kalshi-specific EV calc with fees (OpenAI #10, Gemini #1C)
**Why not:** Kalshi fees are currently $0 for most markets or minimal (and vary by tier). The system already doesn't account for sportsbook juice on the bet side (edge is computed against de-vigged fair prob, not the actual offered line). Adding fee adjustments for one book would be inconsistent. If fees become material, this can be added later as a config parameter.

### Replace American-odds-string injection with first-class probability representation (OpenAI #2)
**Why not:** This would require refactoring edge.py's book discovery mechanism, which is currently well-tested and stable. The American odds conversion approach, while inelegant, works correctly because: (a) midpoint probabilities converted to American and back lose minimal precision, (b) the devig step on vig-free data is a near-identity operation. The risk of introducing bugs in a refactor outweighs the elegance gain. Can be revisited later.

### KalshiMarketSnapshot normalized schema (OpenAI suggestion)
**Why not:** Over-engineering for this stage. The existing pipeline uses simple dicts. Adding a dedicated dataclass/schema for Kalshi would be inconsistent with how DG data flows through the system.

### Store per-market Kalshi rules text (OpenAI #9)
**Why not:** The book_rules table already handles this. We'll verify actual Kalshi rules and store them there. No need for per-bet rule text storage.

### Thread-safe token bucket rate limiter (Gemini #4B, OpenAI #12)
**Why not:** The system is single-threaded. Pipeline runs are sequential (pull DG, then pull Kalshi). A simple sleep-based rate limiter is sufficient. Can upgrade if parallelization is added later.
