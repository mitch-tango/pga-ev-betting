"""
Calcutta Auction Pricing for the Masters Tournament

Derives fair-value pricing for each player as a % of the pot,
using composite odds (blended DG model + sportsbook consensus)
and the specific Calcutta payout structure.

Methodology:
- P(1st) = win_composite
- P(2nd-10th) distributed uniformly = (t10_composite - win_composite) / 9
  (Uniform within top-10 conditional on not winning is a reasonable
   approximation — positional distribution within top-10 is relatively flat)
- EV = sum of P(position_k) * payout(position_k) for k=1..10
"""

import csv
import sys
from pathlib import Path

PAYOUTS = {
    1: 0.41,
    2: 0.19,
    3: 0.10,
    4: 0.06,
    5: 0.04,
    6: 0.035,
    7: 0.03,
    8: 0.025,
    9: 0.02,
    10: 0.015,
}

TOTAL_PAYOUT = sum(PAYOUTS.values())  # 0.925
PAYOUT_2_TO_10 = sum(v for k, v in PAYOUTS.items() if k >= 2)  # 0.515


def load_composite_odds(csv_path):
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
            players.append({
                "name": name,
                "p_win": win,
                "p_t10": t10,
                "p_t20": t20,
                "p_mc": mc,
                "coursefit": coursefit,
                "expert": expert,
            })
    return players


def compute_calcutta_ev(players):
    """Compute expected value as % of pot for each player."""
    for p in players:
        p_1st = p["p_win"]
        p_2_to_10 = max(p["p_t10"] - p["p_win"], 0)
        p_each_2_to_10 = p_2_to_10 / 9.0

        ev = p_1st * PAYOUTS[1]
        for k in range(2, 11):
            ev += p_each_2_to_10 * PAYOUTS[k]

        p["ev_pct"] = ev * 100  # as percentage of pot
        p["p_2_to_10"] = p_2_to_10

    return players


def print_results(players):
    # Sort by EV descending
    players.sort(key=lambda x: x["ev_pct"], reverse=True)

    total_ev = sum(p["ev_pct"] for p in players)

    print(f"{'':>3} {'Player':<28} {'Win%':>7} {'T10%':>7} {'Fair Value':>10} {'Norm%':>7} {'CF':>5} {'Exp':>5}")
    print("-" * 85)

    for i, p in enumerate(players, 1):
        norm_pct = (p["ev_pct"] / total_ev) * 100 if total_ev > 0 else 0
        print(
            f"{i:>3} {p['name']:<28} {p['p_win']*100:>6.2f}% {p['p_t10']*100:>6.1f}% "
            f"{p['ev_pct']:>9.3f}% {norm_pct:>6.2f}% {p['coursefit']:>5} {p['expert']:>5}"
        )

    print("-" * 85)
    print(f"    {'TOTAL':<28} {'':>7} {'':>7} {total_ev:>9.3f}% {100.00:>6.2f}%")
    print(f"\n    Total payout structure = {TOTAL_PAYOUT*100:.1f}% of pot (house keeps {(1-TOTAL_PAYOUT)*100:.1f}%)")
    print(f"    'Fair Value' = expected return as % of pot (sums to ~{TOTAL_PAYOUT*100:.1f}%)")
    print(f"    'Norm%' = normalized to 100% (what you'd expect to pay in an efficient auction)")

    # Print tiers
    print("\n\n=== PRICING TIERS ===\n")
    tiers = [
        ("ELITE (>5% of pot)", lambda p: p["ev_pct"] > 5),
        ("PREMIUM (2-5%)", lambda p: 2 <= p["ev_pct"] <= 5),
        ("MID-TIER (1-2%)", lambda p: 1 <= p["ev_pct"] < 2),
        ("VALUE (0.3-1%)", lambda p: 0.3 <= p["ev_pct"] < 1),
        ("LONG SHOTS (<0.3%)", lambda p: p["ev_pct"] < 0.3),
    ]

    for label, filt in tiers:
        tier_players = [p for p in players if filt(p)]
        if tier_players:
            tier_total = sum(p["ev_pct"] for p in tier_players)
            norm_total = (tier_total / total_ev) * 100
            print(f"  {label} — {len(tier_players)} players, {norm_total:.1f}% of auction value")
            for p in tier_players:
                norm = (p["ev_pct"] / total_ev) * 100
                print(f"    {p['name']:<28} Fair: {p['ev_pct']:.3f}%  Norm: {norm:.2f}%")
            print()


def print_dollar_example(players, pot_size=1000):
    """Print dollar values for a given pot size."""
    total_ev = sum(p["ev_pct"] for p in players)
    players.sort(key=lambda x: x["ev_pct"], reverse=True)

    print(f"\n=== DOLLAR VALUES (assuming ${pot_size:,} pot) ===\n")
    print(f"{'':>3} {'Player':<28} {'Max Bid':>10} {'Target Bid':>10}")
    print("-" * 55)

    for i, p in enumerate(players, 1):
        fair_dollar = (p["ev_pct"] / 100) * pot_size
        target = fair_dollar * 0.75  # aim to pay 75% of fair value for +EV
        if fair_dollar >= 1.0:
            print(f"{i:>3} {p['name']:<28} ${fair_dollar:>8.2f} ${target:>8.2f}")

    print(f"\n    Max Bid = fair value (break-even price)")
    print(f"    Target Bid = 75% of fair value (your +EV sweet spot)")


if __name__ == "__main__":
    csv_path = Path(__file__).parent.parent / "composite_odds_masters_tournament.csv"
    players = load_composite_odds(csv_path)
    players = compute_calcutta_ev(players)
    print_results(players)

    # Also print dollar example
    print_dollar_example(players)
