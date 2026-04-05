# Interview Transcript

## Q1. Kalshi as a bettable book vs. consensus-only signal?

Should Kalshi be a book you'd actually place bets on, or purely a consensus signal?

**Answer:** Kalshi is a bettable book — user has funds there. The system should recommend bets on Kalshi just like any other sportsbook.

## Q2. Bid-ask spread handling

How should we handle the bid-ask spread for implied probability?

**Answer:** Use the ask price (cost to buy YES) as the implied probability. No midpoint or other adjustment.

## Q3. Tournament matching

How should we match Kalshi events to DataGolf tournaments?

**Answer:** Deferred to implementation. Decision: use date-based matching — pull all open KXPGATOUR events and match by tournament date range to the current DG tournament week.

## Q4. Liquidity threshold

Should we set a minimum volume/open interest threshold?

**Answer:** Yes. Set minimum at **100 contracts open interest**. Below this threshold, ignore the player's Kalshi price. Can be tuned after seeing real data.

## Q5. Kalshi settlement rules

Kalshi binary contracts settle $1/$0, withdrawals void. Model as simple void/void in book_rules.

**Answer:** Confirmed — that covers it. `('kalshi', 'win', 'void', 'void', NULL)` pattern for all markets.

## Q6. Matchup priority

With Kalshi H2H matchups available, should we blend into matchup consensus?

**Answer:** No. Keep matchups at 100% DG model. Use Kalshi H2H only as a bettable outlet when DG shows edge — do not blend Kalshi into the matchup probability model.

## Q7. Polling frequency

How often should we pull Kalshi prices?

**Answer:** Same cadence as DataGolf — during pre-tournament and pre-round pipeline runs only. No independent polling.

## Q8. Error handling & graceful degradation

What happens when Kalshi API is down or has no golf events?

**Answer:** Proceed without Kalshi data and log a warning. Do not halt the pipeline.

## Q9. Kalshi in the Discord bot

Should Kalshi appear in all bot commands?

**Answer:** Yes — `/scan` (as a possible Best Book), `/place` (log Kalshi bets), `/status` (by-book ROI breakdown), and all other relevant commands.

## Q10. Polymarket TODO scope

How much scaffolding for future Polymarket integration?

**Answer:** Just code comments/TODOs in relevant files. No stub modules or class skeletons.
