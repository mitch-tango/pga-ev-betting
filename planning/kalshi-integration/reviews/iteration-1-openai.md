# Openai Review

**Model:** gpt-5.2
**Generated:** 2026-04-05T07:55:09.511615

---

## High-impact footguns / edge cases

### 1) “No devig needed” is not actually true for Kalshi best-bid/ask
**Refs:** §1 Key Differences, §5.1 processing (“Read `yes_ask_dollars` as implied probability”), §6.2 De-vig bypass rationale  
- Using **ask** (or **bid**) as “the probability” will bias edges because bid/ask includes spread + fees + microstructure. For a fair implied probability proxy you typically want:
  - **mid** = (best_bid + best_ask)/2 (if available), or
  - use **last trade** price, or
  - compute an implied probability from the *full orderbook* at your intended size.
- Also “YES + NO ≈ 1.00” can be false at the top-of-book due to spread and discrete ticks; it may be **< 1** (crossed?) or **> 1**. Treating ask as probability will systematically understate/overstate.
**Actionable fix:** define a pricing policy per market:
- `kalshi_prob = mid_price` when both sides exist, else fall back to last_price, else skip.
- For “bettable outlet” recommendations, compute **effective fill price for size** (walk the book) or at least flag “thin” markets and use top-of-book only if OI+top size exceed a threshold.

### 2) Converting to American strings to “fit” discovery is brittle and can corrupt semantics
**Refs:** §5.2 Strategy A, §6.2 “no special handling needed”  
- You’re forcing a **probability market** into an **odds-string interface** to avoid touching `edge.py`. That’s a classic integration footgun:
  - rounding to whole American odds loses information (esp. longshots)
  - implied prob ↔ American conversions are nonlinear; your later devig/blend steps may reintroduce distortions
  - string detection (“starts with + or -”) is fragile and invites future bugs
**Actionable fix:** add a first-class representation in the pipeline: store **implied_probabilities** per book and only convert for display. Refactor discovery to look for explicit book keys, not string prefixes. If you can’t refactor now, at least:
- keep an additional `kalshi_prob_raw` float alongside the American string and ensure downstream uses the float when available.

### 3) Market-type devig assumptions can break badly for top10/top20
**Refs:** §6.2 “independent de-vig will scale by ~1.0”  
- For placement markets, Kalshi contracts are **not a partition of outcomes**. Top10 for each player overlaps heavily; the sum of probabilities across players can be >> 1.  
- Any devig method that assumes a field with overround properties may behave unpredictably if you “devig a set” that doesn’t correspond to mutually exclusive outcomes.
**Actionable fix:** do **not** run field-level devig/normalization on Kalshi top-N prices at all. Treat each contract as already an implied probability estimate and blend with DG model directly (if you want) using a weighting scheme that doesn’t require the “sum to 1” assumption.

### 4) H2H “two contracts per event” assumption is likely wrong
**Refs:** §5.1 matchups step 2  
- Kalshi may model H2H as:
  - one market with outcomes/yes-no, or
  - multiple markets, or
  - one market per player, or
  - include “tie”/“push” resolution differently per contract.
Assuming exactly two contracts and mapping them to p1/p2 is fragile.
**Actionable fix:** implement matchup parsing against the actual schema: use explicit fields (`market_type`, `yes/no`, `outcomes`, `strike`, etc.). Add validation: if you can’t identify exactly two complementary outcomes, skip that matchup.

### 5) Open interest is a weak liquidity filter
**Refs:** §5.1 OI filter, §10  
- OI can be high while the **orderbook is empty** or wide; or OI low but tight and tradable for small size.
**Actionable fix:** incorporate at least one of:
- best bid/ask availability
- bid-ask spread threshold (e.g., max 3–5¢)
- top-of-book size >= min_size
- “market is tradable” flag if API provides it

### 6) Tournament matching by “expiration within the week” can mislink events
**Refs:** §4.1  
- There can be multiple PGA-related events open (winner/top10/top20/H2H) with similar expiration.
- Rescheduled tournaments, timezone issues, and settlement-time offsets can push `expected_expiration_time` outside “tournament week”.
- Majors or alternative tours could collide if series tickers aren’t perfectly isolated.
**Actionable fix:** build a deterministic matching key:
- prefer event metadata: course/location/tournament id if available
- otherwise: parse “PGA Tour: {Tournament Name} …” and match normalized tournament names first, then use date as tie-breaker
- store last successful mapping `{dg_tournament_id -> kalshi_event_ticker}` in DB for reuse and audit.

---

## Missing considerations / unclear requirements

### 7) “No API key” may be wrong or may change; also base URL looks suspicious
**Refs:** §3.1, §6.1 `KALSHI_BASE_URL = https://api.elections.kalshi.com/trade-api/v2`  
- The elections subdomain + `/trade-api/v2` may not be the stable canonical endpoint for all products (and could enforce auth or different limits).
**Actionable fix:** confirm official base URL(s) for market data, document versioning, and make it configurable per environment. Add a healthcheck endpoint test in CI.

### 8) Price field names and units are assumed, not validated
**Refs:** §5.1 “Read `yes_ask_dollars`”, §9 conversion functions  
- Kalshi commonly uses cents or dollars depending on field; sometimes integer cents. If you misinterpret 6 as $0.06 you’ll create absurd implied probabilities.
**Actionable fix:** implement strict schema validation:
- assert 0 <= price <= 1 if using dollars; if 0–100 treat as cents and divide by 100.
- log and skip if out of range.

### 9) “WD = void” and tie rules are assumed; settlements vary by contract
**Refs:** §7 note  
- If your ROI and realized P/L rely on settlement rules, wrong assumptions will poison evaluation and bankroll tracking.
**Actionable fix:** store per-market rule metadata from Kalshi if provided, or at minimum store the **market ticker and raw rules text** with each recommendation so settlement can be reconciled later.

### 10) Size, bankroll, and fees are not considered in EV/edge
**Refs:** globally; Kalshi differs materially  
- Kalshi fees and the inability to always fill at ask matter. “Edge” as `your_prob - implied_prob` isn’t enough to estimate expected profit.
**Actionable fix:** introduce a Kalshi-specific EV calc:
- expected value using **fill price**, **fees**, and a user-configured **order size**
- show “edge” and “EV($)” separately; recommend only if both pass thresholds.

---

## Security / operational vulnerabilities

### 11) Unbounded caching & sensitive data handling
**Refs:** §3.4 caching to disk  
- Raw caching can grow without bound (timestamped directories). Also you may later add authenticated endpoints; caching could accidentally store tokens.
**Actionable fix:** add cache retention (e.g., keep last N runs per tournament) and a scrubber. Ensure cache directory permissions and add a config flag to disable raw caching in production.

### 12) Rate limiting implementation could DDoS yourself under pagination
**Refs:** §3.1 rate limiting, §3.1 pagination  
- With cursor pagination and per-market calls (`get_market`, `get_orderbook`), you can easily exceed 20 rps if you call orderbook per ticker.
**Actionable fix:** design call strategy:
- use bulk endpoints where possible
- avoid per-market orderbook unless needed (e.g., only for candidates passing an initial filter)
- implement a real token bucket shared across threads/processes (if you ever parallelize)

---

## Performance / architecture issues

### 13) N+1 API call risk if you call `get_orderbook` for every market
**Refs:** §3.2 includes `get_orderbook`, §5.1 doesn’t clarify usage volume  
**Actionable fix:** only request orderbooks for:
- markets where price exists + player matched + initial edge > threshold
- top K markets by edge or by DG probability, etc.

### 14) Blending & weights: unclear how Kalshi interacts with DG model
**Refs:** §6.1 adds weights, §6.4 excludes Kalshi from matchup consensus  
- For outrights/placements, the plan implies Kalshi participates in the consensus and therefore affects `your_prob` via blend. For matchups it doesn’t. That asymmetry might be intended, but it’s not justified and can lead to inconsistent user expectations.
**Actionable fix:** explicitly define:
- Does Kalshi influence `your_prob` for win/t10/t20, or is it only a bettable outlet?
- If it influences, how do you avoid circularity (market price influencing your “model” then comparing to same market for edge)?

### 15) Circularity / double-counting risk in edge
**Refs:** §1, §6.3  
- If your_prob includes Kalshi (via consensus blend) and you also evaluate edge vs Kalshi, you reduce apparent edge and can create self-referential signals. Sometimes desired, often not.
**Actionable fix:** when evaluating edge against a given book, compute `your_prob_excluding_that_book` (leave-one-out consensus) or keep a “model-only” probability baseline.

---

## Ambiguities to resolve before implementation

1) **Which Kalshi price do we use** for implied prob and for “best book”: ask, bid, mid, last, or size-adjusted? (Must be specified.)  
2) **Unit normalization**: are prices `0.06`, `6`, or `6¢`? Define accepted formats and validation.  
3) **Market discovery**: confirm series tickers and whether top10/top20 are separate series or separate markets under same event.  
4) **Outcome mapping**: define robust parsing for names and matchup structures; don’t rely on title text patterns only.  
5) **Settlement/void handling**: what’s the minimal accurate data you must persist to reconcile results?

---

## Suggested concrete additions to the plan

- Add a `KalshiMarketSnapshot` normalized internal schema: `{ticker, event_ticker, market_type, player_ids, price_bid, price_ask, price_mid, last, oi, volume, rules_text, ts}`.
- Add a “pricing policy” config:
  - `KALSHI_PRICE_SOURCE = mid|ask|last|size_adjusted`
  - `KALSHI_MAX_SPREAD = 0.05`
  - `KALSHI_MIN_TOP_SIZE = ...`
- Change Strategy A: instead of converting to American strings for discovery, add an explicit `books` structure and update `edge.py` discovery accordingly (or implement a shim that keeps floats).
- Implement leave-one-out consensus when computing edge vs the same book.
- Add integration tests with recorded fixtures (cached Kalshi responses) to lock down parsing/matching and avoid regressions when Kalshi changes schemas.

If you want, I can propose a minimal refactor of `edge.py` that avoids the American-odds-string hack while keeping the rest of the pipeline unchanged.
