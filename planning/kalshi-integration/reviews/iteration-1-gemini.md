# Gemini Review

**Model:** gemini-3-pro-preview
**Generated:** 2026-04-05T07:55:09.512524

---

This is a well-structured and comprehensive implementation plan. The pipeline design, separation of concerns, and graceful degradation strategies are excellent. 

However, looking at this through the lens of a senior architect and quantitative bettor, there are **critical mathematical and market micro-structure flaws** that will result in inaccurate consensus blending, massively inflated EV calculations, and catastrophic false positives during live tournaments.

Here is my unconstrained assessment, broken down by severity.

---

### 🚨 1. Critical Footguns & Mathematical Flaws

**A. Using Ask Price for Consensus Blending (Ref: Sec 5.1 & 6.2)**
* **The Problem:** The plan states: *"Read `yes_ask_dollars` as implied probability... Kalshi prices for a full outright field will sum to approximately 1.0 (no vig), the power de-vig will find k ≈ 1.0."*
This is fundamentally incorrect. The `yes_ask` is the price *you buy at*, which includes the market maker's spread. If a golfer's true probability is 5%, the bid might be $0.04 and the ask $0.06. If you sum the *Ask* prices for a 150-man golf field, it will sum to roughly **105% to 115%**, not 1.0. 
* **The Footgun:** If you pass Ask-derived American odds into your devigger, it will treat the spread as vig, apply the power method, and artificially suppress Kalshi's consensus probability.
* **The Fix:** You must decouple the "consensus signal" from the "bettable line."
    * For **Consensus Blending:** Use the Midpoint `(yes_bid + yes_ask) / 2` to represent Kalshi's true implied probability. 
    * For **Edge/Bettable evaluation:** Use the `yes_ask` to calculate the edge and payout. 

**B. The "Pre-Round" Live Odds Disaster (Ref: Sec 8.2 & 6.4)**
* **The Problem:** The plan mentions pulling Kalshi matchup data during `run_preround.py`. Pre-round pulls happen *during* the tournament (e.g., Thursday night for Friday's round). Kalshi tournament matchups trade *live* during the event.
* **The Footgun:** If your DataGolf probabilities are static pre-tournament models, comparing them against Kalshi's live mid-tournament prices will create massive false positives. For example, if Golfer A shoots a 62 on Thursday, his Kalshi Win/Matchup Ask price will skyrocket. Your system will compare this new price to the stale DG pre-tournament probability and flag a massive +EV bet on the other golfer. 
* **The Fix:** Ensure that Kalshi tournament-long markets (Win, T10, T20, Tournament Matchup) are **only** pulled pre-tournament, or ensure your DataGolf model update pipeline fetches live/in-play probabilities before comparing them to Kalshi.

**C. Ignoring Trading Fees in Edge Calculation (Ref: Sec 9 & 6.3)**
* **The Problem:** Kalshi charges a trading fee (often a percentage of the contract size or maximum ROI). 
* **The Footgun:** If your system calculates EV based purely on the `yes_ask`, it will overstate the edge. A 3% edge on a $0.50 contract might be completely wiped out by Kalshi's fees.
* **The Fix:** The conversion utility in Section 9 `kalshi_price_to_decimal` must subtract the effective fee tier from the payout before converting to decimal odds. 

---

### ⚠️ 2. Architectural & Market Micro-Structure Issues

**A. "Open Interest" is a Trap for Liquidity (Ref: Sec 5.1 & 10)**
* **The Problem:** The plan filters out markets where `open_interest < 100`. 
* **The Reality:** Open Interest just means contracts are currently held by traders. It tells you *nothing* about the current orderbook. A market could have an OI of 10,000 but an empty orderbook (or an absurd spread like Bid $0.01 / Ask $0.99) right now.
* **The Fix:** Filter by **Bid-Ask Spread** and **Top-of-Book Volume**. If you want to bet $20, you need `yes_ask_size >= 20` and `(yes_ask - yes_bid) <= $0.05`. If the ask size is only 5 contracts ($5), placing a larger bet will sweep the book to worse prices, ruining your +EV.

**B. API Endpoint Inefficiency (Ref: Sec 3.2)**
* **The Problem:** Getting top-of-book prices (the Bid/Ask) often requires hitting `/markets/{ticker}/orderbook` in Kalshi's architecture. If you have 150 golfers $\times$ 3 markets (Win, T10, T20) = 450 endpoints. At a conservative 10 req/sec limit, this adds 45 seconds to your pipeline.
* **The Fix:** Verify if `GET /markets?event_ticker={ticker}` returns real-time `yes_bid` and `yes_ask` in its payload. If it does, great. If it only returns static market definitions, you need to use Kalshi's Batched API or Websocket feeds, otherwise, the pipeline will become noticeably sluggish.

---

### 🔍 3. Edge Cases & Schema Deficiencies

**A. Date-Based Event Matching Fragility (Ref: Sec 4.1)**
* **The Problem:** Matching Kalshi events by "expires within the tournament week" is dangerous. Golf tournaments routinely get delayed to Monday due to weather (e.g., Cognizant Classic, Waste Management). Kalshi markets often have dynamic expirations or are set to "Dec 31" as placeholders until the tournament is scheduled.
* **The Fix:** Match on the `expected_expiration_time` falling strictly between `tournament_start_date` and `tournament_start_date + 7 days`. Add a fallback safety check: ensure the string "PGA" or the tournament name exists in the event title to avoid accidentally matching a LIV Golf or DP World Tour event happening on the same weekend.

**B. Incorrect Settlement Rules for Dead Heats (Ref: Sec 7)**
* **The Problem:** The schema states `tie_rule: 'void'` for T10 and T20 markets. 
* **The Reality:** Golf Top 10/20 markets are notorious for dead heats. Kalshi does *not* void these. They usually settle using fractional payouts (e.g., if 3 players tie for 10th, the YES contract settles at $0.33, or specific rules apply based on the contract language).
* **The Fix:** Update the database schema to reflect fractional dead-heat rules. More importantly, ensure your EV calculator understands that a $0.06 Ask price doesn't guarantee a $1 payout if a dead heat occurs.

---

### 📝 4. Unclear or Missing Requirements

**A. Odds Conversion Math (Ref: Sec 9)**
The conversion logic in the prompt description is slightly ambiguous. To be absolutely precise in your code:
* **Ask to Decimal:** `1 / yes_ask` (e.g., 1 / 0.06 = 16.666).
* **Ask to American:** 
    * If `yes_ask < 0.50`: `+` followed by `((1 / yes_ask) - 1) * 100` (e.g., 0.06 -> +1566.67).
    * If `yes_ask > 0.50`: `-` followed by `(yes_ask / (1 - yes_ask)) * 100` (e.g., 0.55 -> -122.22).
Make sure to round to standard integers for the American strings so the DataGolf edge parser doesn't break on floats like `+1566.66`.

**B. Missing: API Rate Limit Strategy**
The plan states "100ms between calls (conservative vs 20/sec limit)". 
Kalshi's rate limits are measured in rolling windows (often 10/sec or 20/sec per IP, and heavily punished if exceeded). A simple `time.sleep(0.1)` is not thread-safe if you eventually parallelize your pullers (`pull_outrights` and `pull_matchups` running concurrently). Use a proper global token bucket or a semaphore for Kalshi API requests.

### Summary of Actionable Changes to the Plan:
1. **Change Section 5.1/6.2:** Extract `yes_bid` and `yes_ask`. Use `(Bid+Ask)/2` to generate the American odds passed into the Devigger for the Consensus model.
2. **Change Section 5.2/6.3:** Pass the raw `yes_ask` (adjusted for fees) to the Edge Calculator for EV evaluation.
3. **Change Section 8.2:** Explicitly block pulling Kalshi pre-tournament markets during the `pre_round` (mid-tournament) runs unless live DataGolf models are being used.
4. **Change Section 10:** Change the liquidity filter from `open_interest` to `yes_ask_size >= MIN_BET_SIZE`.
5. **Change Section 7:** Correct the dead heat rules for T10/T20 in the database schema.
