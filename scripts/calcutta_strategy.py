"""
Calcutta Portfolio Strategy for ~10 team auction.

Analyzes coverage probability, optimal tier allocation,
and identifies target players vs. let-go players.
"""

import csv
from pathlib import Path
from itertools import combinations
import math

PAYOUTS = {1: 0.41, 2: 0.19, 3: 0.10, 4: 0.06, 5: 0.04,
           6: 0.035, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.015}


def load_players(csv_path):
    players = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["player_name"].strip().strip('"')
            win = float(row["win_composite"]) if row["win_composite"] else 0.0
            t10 = float(row["t10_composite"]) if row["t10_composite"] else 0.0
            t20 = float(row["t20_composite"]) if row["t20_composite"] else 0.0
            mc = float(row["make_cut_composite"]) if row["make_cut_composite"] else 0.0
            coursefit = row.get("coursefit", "").strip()
            expert = row.get("expert_picks", "").strip()

            p_1st = win
            p_2_to_10 = max(t10 - win, 0)
            p_each = p_2_to_10 / 9.0
            ev = p_1st * PAYOUTS[1]
            for k in range(2, 11):
                ev += p_each * PAYOUTS[k]

            players.append({
                "name": name,
                "p_win": win,
                "p_t10": t10,
                "p_t20": t20,
                "p_mc": mc,
                "ev_pct": ev * 100,
                "coursefit": coursefit,
                "expert": expert,
            })
    players.sort(key=lambda x: x["ev_pct"], reverse=True)
    total_ev = sum(p["ev_pct"] for p in players)
    for p in players:
        p["norm_pct"] = (p["ev_pct"] / total_ev) * 100
    return players


def coverage_analysis(players):
    """Analyze probability of having at least one top-10 finisher for various portfolio strategies."""
    print("=" * 80)
    print("COVERAGE ANALYSIS: P(at least one of your players finishes top 10)")
    print("=" * 80)

    # Define tier boundaries
    elite = [p for p in players if p["norm_pct"] > 5]       # ~1 player
    premium = [p for p in players if 2 <= p["norm_pct"] <= 5]  # ~10 players
    mid = [p for p in players if 1 <= p["norm_pct"] < 2]      # ~20 players
    value = [p for p in players if 0.3 <= p["norm_pct"] < 1]   # ~32 players
    longshot = [p for p in players if p["norm_pct"] < 0.3]     # ~27 players

    print(f"\nTier sizes: Elite={len(elite)}, Premium={len(premium)}, Mid={len(mid)}, Value={len(value)}, Longshot={len(longshot)}")

    # Strategy scenarios (num from each tier)
    scenarios = [
        ("All-in on stars",     {"elite": 1, "premium": 3, "mid": 2, "value": 2, "longshot": 1}),
        ("Balanced",            {"elite": 0, "premium": 2, "mid": 4, "value": 2, "longshot": 1}),
        ("Mid-heavy value",     {"elite": 0, "premium": 1, "mid": 5, "value": 2, "longshot": 1}),
        ("Deep value",          {"elite": 0, "premium": 1, "mid": 3, "value": 4, "longshot": 1}),
        ("Spread the field",    {"elite": 0, "premium": 0, "mid": 4, "value": 4, "longshot": 1}),
    ]

    tier_map = {"elite": elite, "premium": premium, "mid": mid, "value": value, "longshot": longshot}

    print(f"\n{'Strategy':<25} {'Players':>3} {'P(>=1 T10)':>12} {'Expected EV':>12} {'Approx Cost':>12} {'Budget%':>8}")
    print("-" * 78)

    for name, alloc in scenarios:
        # Take top N from each tier by EV
        portfolio = []
        for tier_name, count in alloc.items():
            tier_players = tier_map[tier_name]
            portfolio.extend(tier_players[:count])

        n = len(portfolio)

        # P(at least one top 10) = 1 - product(1 - p_t10_i)
        p_none_t10 = 1.0
        for p in portfolio:
            p_none_t10 *= (1 - p["p_t10"])
        p_at_least_one_t10 = 1 - p_none_t10

        total_ev = sum(p["ev_pct"] for p in portfolio)
        total_norm = sum(p["norm_pct"] for p in portfolio)

        print(f"{name:<25} {n:>3}   {p_at_least_one_t10*100:>9.1f}%   {total_ev:>9.3f}%   {total_norm:>9.1f}%   {total_norm:>6.1f}%")

    return elite, premium, mid, value, longshot


def sentiment_analysis(players):
    """Flag players where model value diverges from likely auction sentiment."""
    print("\n\n" + "=" * 80)
    print("AUCTION SENTIMENT ANALYSIS: Where model disagrees with crowd")
    print("=" * 80)

    print("\n--- LIKELY OVERBID (let others overpay) ---")
    print("These players will attract disproportionate bidding due to name/storyline:\n")

    overbids = [
        ("Scheffler, Scottie", "Defending champion, obvious #1. Everyone knows he's the best — price will exceed fair value."),
        ("Rahm, Jon", "Big name, LIV storyline returning to Augusta. Emotional bidders will push him up."),
        ("DeChambeau, Bryson", "Fan favorite, social media star. Casual bettors love him. Book odds already higher than DG model."),
        ("Koepka, Brooks", "Major pedigree drives name-brand premium. Model has him at 1.3% win — books at 1.6%."),
        ("Reed, Patrick", "Former Masters champ. [++] coursefit and expert picks will inflate his price beyond 1.6% fair value."),
        ("Johnson, Dustin", "Former #1, Masters winner. Name far exceeds current form. Worth 0.28% but will sell for more."),
        ("Garcia, Sergio", "2017 Masters champ, Augusta nostalgia. Worth 0.23% but name recognition inflates."),
        ("Spieth, Jordan", "Masters storyline player. Always gets bid up at Augusta-themed auctions."),
    ]

    for name, reason in overbids:
        p = next((x for x in players if x["name"] == name), None)
        if p:
            print(f"  {name:<28} Fair: {p['norm_pct']:.2f}%  |  {reason}")

    print("\n\n--- TARGET AGGRESSIVELY (under-the-radar value) ---")
    print("These players offer strong EV but won't attract emotional bidding:\n")

    targets = [
        ("Fitzpatrick, Matt", "US Open champ, elite ball-striker, [++] coursefit. Not flashy enough to get bid up. 3.34% value."),
        ("Fleetwood, Tommy", "#8 in EV, [++] coursefit AND expert picks. Quietly elite Augusta form. Should be a top target."),
        ("Young, Cameron", "Massive talent, [++] coursefit + experts. 3.03% value — unlikely to get bid to that level."),
        ("Matsuyama, Hideki", "2021 Masters champ but less name recognition in US auctions. 2.83% value often goes cheap."),
        ("Kim, Si Woo", "Nobody's favorite player but 1.85% value with strong Augusta history. Classic auction sleeper."),
        ("Henley, Russell", "1.82% value, [+] coursefit. Anonymous enough to slip through cheaply."),
        ("MacIntyre, Robert", "2.47% value, [++] coursefit. Rising star but not yet a household name in Calcuttas."),
        ("Lee, Min Woo", "2.31% value, [++] coursefit, [+] experts. Casual bettors don't know him."),
        ("Hojgaard, Nicolai", "1.34% value, [++] coursefit AND [++] expert picks. Complete unknown in most auctions."),
        ("Knapp, Jake", "[++] coursefit at 1.36% value. Long hitter suits Augusta. Will go cheap."),
        ("Spaun, J.J.", "1.23% value, nobody will fight you for him."),
    ]

    for name, reason in targets:
        p = next((x for x in players if x["name"] == name), None)
        if p:
            print(f"  {name:<28} Fair: {p['norm_pct']:.2f}%  |  {reason}")

    print("\n\n--- FAIR-PRICED (buy at or near fair value) ---")
    print("Good players that will sell near fair value — fine to own but don't overpay:\n")

    fair = [
        ("McIlroy, Rory", "Everyone knows he's great, will sell near 4.6% fair value. Fine to own, just don't chase."),
        ("Schauffele, Xander", "Similar — accurately priced by most rooms. Good player at fair price."),
        ("Aberg, Ludvig", "Young star getting hype but model supports it. Will sell near fair value."),
        ("Morikawa, Collin", "Solid but unexciting. Usually sells near fair value."),
    ]

    for name, reason in fair:
        p = next((x for x in players if x["name"] == name), None)
        if p:
            print(f"  {name:<28} Fair: {p['norm_pct']:.2f}%  |  {reason}")


def recommended_portfolio(players):
    """Build a recommended ~9 player portfolio."""
    print("\n\n" + "=" * 80)
    print("RECOMMENDED PORTFOLIO (9 players)")
    print("=" * 80)

    targets = [
        "Fleetwood, Tommy",      # Premium - undervalued
        "Young, Cameron",         # Premium - undervalued
        "Matsuyama, Hideki",      # Premium - goes cheap
        "MacIntyre, Robert",      # Mid - rising, unknown
        "Kim, Si Woo",            # Mid - Augusta sleeper
        "Henley, Russell",        # Mid - anonymous value
        "Hojgaard, Nicolai",      # Mid - double plus
        "Knapp, Jake",            # Mid - coursefit value
        "Spaun, J.J.",            # Mid - nobody wants him
    ]

    portfolio = []
    for name in targets:
        p = next((x for x in players if x["name"] == name), None)
        if p:
            portfolio.append(p)

    p_none_t10 = 1.0
    p_none_t20 = 1.0
    p_none_win = 1.0
    total_norm = 0
    total_ev = 0

    print(f"\n{'':>3} {'Player':<28} {'Win%':>7} {'T10%':>7} {'Norm%':>7} {'CF':>5} {'Exp':>5}")
    print("-" * 65)

    for i, p in enumerate(portfolio, 1):
        print(f"{i:>3} {p['name']:<28} {p['p_win']*100:>6.2f}% {p['p_t10']*100:>6.1f}% {p['norm_pct']:>6.2f}% {p['coursefit']:>5} {p['expert']:>5}")
        p_none_t10 *= (1 - p["p_t10"])
        p_none_t20 *= (1 - p["p_t20"])
        p_none_win *= (1 - p["p_win"])
        total_norm += p["norm_pct"]
        total_ev += p["ev_pct"]

    print("-" * 65)
    print(f"\n  Portfolio stats:")
    print(f"    Total fair value (Norm%):        {total_norm:.1f}% of pot")
    print(f"    P(at least one winner):          {(1-p_none_win)*100:.1f}%")
    print(f"    P(at least one top 10):          {(1-p_none_t10)*100:.1f}%")
    print(f"    P(at least one top 20):          {(1-p_none_t20)*100:.1f}%")
    print(f"    Target spend (75% of fair):      {total_norm*0.75:.1f}% of pot")

    print(f"\n  Strategy: Acquire this group for ~{total_norm*0.70:.0f}-{total_norm*0.80:.0f}% of their combined fair value.")
    print(f"  You're buying {len(portfolio)} players worth {total_norm:.1f}% at auction, targeting ~{total_norm*0.75:.1f}% spend.")
    print(f"  That leaves ~{100 - total_norm*0.75:.0f}% of your budget for opportunistic adds.\n")

    # Alternate: what if you grab one star
    print("  ALTERNATE: Swap in one star if price is right")
    alt_adds = ["Fitzpatrick, Matt", "Schauffele, Xander", "McIlroy, Rory"]
    for name in alt_adds:
        p = next((x for x in players if x["name"] == name), None)
        if p:
            # Replace the lowest-EV player
            drop = portfolio[-1]
            new_cost = total_norm - drop["norm_pct"] + p["norm_pct"]
            new_p_none = p_none_t10 / (1 - drop["p_t10"]) * (1 - p["p_t10"])
            print(f"    + {name:<24} (drop {drop['name']}) -> T10 coverage: {(1-new_p_none)*100:.1f}%, cost: {new_cost:.1f}%")


def price_ceilings(players):
    """Print max bid prices for each player."""
    print("\n\n" + "=" * 80)
    print("PRICE CEILINGS (% of pot — do NOT exceed these)")
    print("=" * 80)
    print(f"\n{'':>3} {'Player':<28} {'Fair%':>7} {'Max Bid%':>9} {'Walk Away':>10}")
    print("-" * 62)

    for i, p in enumerate(players[:50], 1):
        fair = p["norm_pct"]
        max_bid = fair * 1.0    # 100% of fair = break even
        walk = fair * 0.85      # walk away above 85% -- still some edge but marginal
        print(f"{i:>3} {p['name']:<28} {fair:>6.2f}% {max_bid:>8.2f}% {walk:>9.2f}%")


if __name__ == "__main__":
    csv_path = Path(__file__).parent.parent / "composite_odds_masters_tournament.csv"
    players = load_players(csv_path)

    elite, premium, mid, value, longshot = coverage_analysis(players)
    sentiment_analysis(players)
    recommended_portfolio(players)
    price_ceilings(players)
