# Interview Transcript: Polymarket & ProphetX Integration

## Q1: ProphetX API Access
**Q:** ProphetX requires email/password auth and may need an affiliate/partner relationship. Do you already have ProphetX API credentials, or should we build the client speculatively?
**A:** I have ProphetX credentials.

## Q2: Polymarket Liquidity Thresholds
**Q:** Polymarket golf liquidity can be thin (some contracts show $0-$46 volume). What minimum liquidity/volume thresholds should we use?
**A:** Match Kalshi thresholds (OI >= 100, spread <= $0.05).

## Q3: Polymarket Top 5 Markets
**Q:** Polymarket offers Top 5 markets in addition to Win/T10/T20. Should we integrate T5 as well?
**A:** Stick to Win/T10/T20 only. Match the existing pipeline scope.

## Q4: ProphetX Odds Format
**Q:** Does ProphetX return American odds or binary contract prices (0-1)?
**A:** Not sure yet — will need to check once we start hitting the API.

## Q5: ProphetX Market Scope
**Q:** Which ProphetX markets should we prioritize integrating?
**A:** Whatever they offer — discover available markets dynamically and integrate all.

## Q6: Book Weights
**Q:** Should Polymarket and ProphetX start with the same weights as Kalshi, or lower?
**A:** Start at weight 1 for everything. Conservative — earn higher weight after validation.

## Q7: Credential Storage
**Q:** How should ProphetX credentials be stored?
**A:** Whatever the project already uses — follow existing secret management pattern.

## Q8: Client Architecture
**Q:** Should we build a shared base class for prediction market clients, or keep them self-contained?
**A:** Up to you — use best judgment on code reuse.
