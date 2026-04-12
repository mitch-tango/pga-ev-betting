"""
Deep sentiment divergence analysis for Calcutta auction.

Compares DG model vs. book consensus to identify where
"sharp" pricing disagrees with "public" pricing.

In a Calcutta, your opponents bid like the public — so
DG-favored / book-faded players are your edge.
"""

import csv
from pathlib import Path

PAYOUTS = {1: 0.41, 2: 0.19, 3: 0.10, 4: 0.06, 5: 0.04,
           6: 0.035, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.015}


def load_players(csv_path):
    players = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["player_name"].strip().strip('"')

            def flt(key):
                v = row.get(key, "")
                return float(v) if v else 0.0

            p = {
                "name": name,
                "win_dg": flt("win_dg"),
                "win_book": flt("win_book_consensus"),
                "win_comp": flt("win_composite"),
                "t10_dg": flt("t10_dg"),
                "t10_book": flt("t10_book_consensus"),
                "t10_comp": flt("t10_composite"),
                "t20_dg": flt("t20_dg"),
                "t20_book": flt("t20_book_consensus"),
                "t20_comp": flt("t20_composite"),
                "mc_dg": flt("make_cut_dg"),
                "mc_book": flt("make_cut_book_consensus"),
                "mc_comp": flt("make_cut_composite"),
                "coursefit": row.get("coursefit", "").strip(),
                "expert": row.get("expert_picks", "").strip(),
            }

            # Compute EVs for DG model, book consensus, and composite
            for prefix, wsuf, tsuf in [("ev_dg", "win_dg", "t10_dg"),
                                        ("ev_book", "win_book", "t10_book"),
                                        ("ev_comp", "win_comp", "t10_comp")]:
                pw = p[wsuf]
                pt = p[tsuf]
                p2_10 = max(pt - pw, 0) / 9.0
                ev = pw * PAYOUTS[1] + sum(p2_10 * PAYOUTS[k] for k in range(2, 11))
                p[prefix] = ev * 100

            # Divergence metrics
            if p["win_book"] > 0:
                p["win_dg_vs_book"] = (p["win_dg"] - p["win_book"]) / p["win_book"] * 100
            else:
                p["win_dg_vs_book"] = 0

            if p["t10_book"] > 0:
                p["t10_dg_vs_book"] = (p["t10_dg"] - p["t10_book"]) / p["t10_book"] * 100
            else:
                p["t10_dg_vs_book"] = 0

            if p["ev_book"] > 0:
                p["ev_dg_vs_book"] = (p["ev_dg"] - p["ev_book"]) / p["ev_book"] * 100
            else:
                p["ev_dg_vs_book"] = 0

            players.append(p)

    players.sort(key=lambda x: x["ev_comp"], reverse=True)
    return players


def print_divergence_table(players):
    """Show where DG model disagrees with books — the crowd will behave like books."""
    print("=" * 100)
    print("MODEL vs. CROWD: Where DataGolf disagrees with sportsbook consensus")
    print("=" * 100)
    print()
    print("In a Calcutta, your opponents price players like casual bettors (≈ book consensus).")
    print("The DG model is sharper. Where DG > Books, the crowd UNDERVALUES the player.")
    print("Where DG < Books, the crowd OVERVALUES the player.")
    print()

    # Filter to players with meaningful EV
    relevant = [p for p in players if p["ev_comp"] > 0.15]

    print(f"{'':>3} {'Player':<26} {'Win DG':>7} {'Win Bk':>7} {'Δ Win':>7} {'T10 DG':>7} {'T10 Bk':>7} {'Δ T10':>7} {'Signal':>12}")
    print("-" * 100)

    for i, p in enumerate(relevant, 1):
        win_delta = (p["win_dg"] - p["win_book"]) * 100
        t10_delta = (p["t10_dg"] - p["t10_book"]) * 100

        # Classify signal
        if win_delta > 0.3 and t10_delta > 2:
            signal = "STRONG BUY"
        elif win_delta > 0.1 and t10_delta > 1:
            signal = "BUY"
        elif win_delta < -0.3 and t10_delta < -2:
            signal = "STRONG SELL"
        elif win_delta < -0.1 and t10_delta < -1:
            signal = "SELL"
        else:
            signal = "HOLD"

        print(f"{i:>3} {p['name']:<26} {p['win_dg']*100:>6.2f}% {p['win_book']*100:>6.2f}% {win_delta:>+6.2f}% "
              f"{p['t10_dg']*100:>6.1f}% {p['t10_book']*100:>6.1f}% {t10_delta:>+5.1f}% {signal:>12}")

    print()


def print_buys_and_sells(players):
    relevant = [p for p in players if p["ev_comp"] > 0.15]

    # Compute signals
    for p in relevant:
        win_delta = (p["win_dg"] - p["win_book"]) * 100
        t10_delta = (p["t10_dg"] - p["t10_book"]) * 100
        p["win_delta"] = win_delta
        p["t10_delta"] = t10_delta

    print("\n" + "=" * 100)
    print("TOP BUYS: DG model says these are BETTER than the crowd thinks")
    print("=" * 100)
    print("(Crowd will underprice these — bid aggressively)\n")

    # Sort by t10 divergence (DG higher than books)
    buys = sorted([p for p in relevant if p["t10_delta"] > 1.5], key=lambda x: x["t10_delta"], reverse=True)

    print(f"{'':>3} {'Player':<26} {'DG Win':>7} {'Bk Win':>7} {'Δ Win':>7}  {'DG T10':>7} {'Bk T10':>7} {'Δ T10':>7}  {'CF':>5} {'Exp':>5}")
    print("-" * 100)
    for i, p in enumerate(buys[:15], 1):
        print(f"{i:>3} {p['name']:<26} {p['win_dg']*100:>6.2f}% {p['win_book']*100:>6.2f}% {p['win_delta']:>+6.2f}%  "
              f"{p['t10_dg']*100:>6.1f}% {p['t10_book']*100:>6.1f}% {p['t10_delta']:>+5.1f}%  {p['coursefit']:>5} {p['expert']:>5}")

    print("\n\n" + "=" * 100)
    print("TOP SELLS: DG model says these are WORSE than the crowd thinks")
    print("=" * 100)
    print("(Crowd will overprice these — let someone else buy them)\n")

    sells = sorted([p for p in relevant if p["t10_delta"] < -1.5], key=lambda x: x["t10_delta"])

    print(f"{'':>3} {'Player':<26} {'DG Win':>7} {'Bk Win':>7} {'Δ Win':>7}  {'DG T10':>7} {'Bk T10':>7} {'Δ T10':>7}  {'CF':>5} {'Exp':>5}")
    print("-" * 100)
    for i, p in enumerate(sells[:15], 1):
        print(f"{i:>3} {p['name']:<26} {p['win_dg']*100:>6.2f}% {p['win_book']*100:>6.2f}% {p['win_delta']:>+6.2f}%  "
              f"{p['t10_dg']*100:>6.1f}% {p['t10_book']*100:>6.1f}% {p['t10_delta']:>+5.1f}%  {p['coursefit']:>5} {p['expert']:>5}")


def print_coursefit_edge(players):
    """Players with strong coursefit that the model may not fully capture."""
    print("\n\n" + "=" * 100)
    print("COURSEFIT + EXPERT OVERLAY: Qualitative edge the model may underweight")
    print("=" * 100)
    print()
    print("[++] coursefit = strong historical/statistical fit to Augusta")
    print("[++] expert = multiple expert sources picking this player")
    print()

    relevant = [p for p in players if p["ev_comp"] > 0.15]

    # Double-plus on both
    double_plus = [p for p in relevant if "[++]" in p["coursefit"] and "[++]" in p["expert"]]
    if double_plus:
        print("--- DOUBLE PLUS: [++] coursefit AND [++] expert picks ---")
        print(f"{'':>3} {'Player':<26} {'Fair%':>7} {'DG vs Bk':>10} {'Note'}")
        print("-" * 80)
        for p in double_plus:
            fair = p["ev_comp"] / sum(x["ev_comp"] for x in players) * 100
            note = ""
            if p["t10_delta"] > 1:
                note = "MODEL ALSO LIKES — strong buy"
            elif p["t10_delta"] < -1:
                note = "Model disagrees — proceed with caution"
            else:
                note = "Model neutral — coursefit/expert gives extra edge"
            print(f"    {p['name']:<26} {fair:>6.2f}% {p['t10_delta']:>+5.1f}% T10  {note}")
        print()

    # Strong coursefit, overlooked by experts
    cf_no_expert = [p for p in relevant if "[++]" in p["coursefit"] and ("[++]" not in p["expert"] and "[+]" not in p["expert"])]
    if cf_no_expert:
        print("--- HIDDEN COURSEFIT: [++] coursefit but NOT expert-picked (true sleepers) ---")
        print(f"{'':>3} {'Player':<26} {'Fair%':>7} {'DG vs Bk':>10}")
        print("-" * 60)
        for p in cf_no_expert:
            fair = p["ev_comp"] / sum(x["ev_comp"] for x in players) * 100
            print(f"    {p['name']:<26} {fair:>6.2f}% {p['t10_delta']:>+5.1f}% T10")
        print()

    # Expert picks that LACK coursefit
    expert_no_cf = [p for p in relevant if "[++]" in p["expert"] and ("[++]" not in p["coursefit"])]
    if expert_no_cf:
        print("--- EXPERT HYPE WITHOUT COURSEFIT: experts like them but Augusta data doesn't ---")
        print("(These may get bid up on expert buzz but lack the statistical backing)")
        print(f"{'':>3} {'Player':<26} {'Fair%':>7} {'CF':>5} {'DG vs Bk':>10}")
        print("-" * 65)
        for p in expert_no_cf:
            fair = p["ev_comp"] / sum(x["ev_comp"] for x in players) * 100
            print(f"    {p['name']:<26} {fair:>6.2f}% {p['coursefit']:>5} {p['t10_delta']:>+5.1f}% T10")
        print()


def print_composite_summary(players):
    """Final cheat sheet combining all signals."""
    print("\n\n" + "=" * 100)
    print("FINAL CHEAT SHEET: Combined Signal Strength")
    print("=" * 100)
    print()
    print("Scoring: +1 each for DG>Books (win), DG>Books (T10), [++]coursefit, [++]expert, [+]coursefit, [+]expert")
    print("         -1 each for DG<Books (win), DG<Books (T10), [-]coursefit")
    print()

    relevant = [p for p in players if p["ev_comp"] > 0.10]
    total_ev = sum(p["ev_comp"] for p in players)

    for p in relevant:
        score = 0
        reasons = []
        win_delta = (p["win_dg"] - p["win_book"]) * 100
        t10_delta = (p["t10_dg"] - p["t10_book"]) * 100
        p["win_delta"] = win_delta
        p["t10_delta"] = t10_delta

        # DG vs books divergence
        if p["win_delta"] > 0.2:
            score += 1; reasons.append("DG>Bk win")
        elif p["win_delta"] < -0.2:
            score -= 1; reasons.append("DG<Bk win")

        if p["t10_delta"] > 2:
            score += 1; reasons.append("DG>Bk T10")
        elif p["t10_delta"] < -2:
            score -= 1; reasons.append("DG<Bk T10")

        # Coursefit
        if "[++]" in p["coursefit"]:
            score += 1; reasons.append("CF++")
        elif "[+]" in p["coursefit"]:
            score += 0.5; reasons.append("CF+")
        elif "[-]" in p["coursefit"]:
            score -= 0.5; reasons.append("CF-")

        # Expert
        if "[++]" in p["expert"]:
            score += 1; reasons.append("Exp++")
        elif "[+]" in p["expert"]:
            score += 0.5; reasons.append("Exp+")
        elif "[-]" in p["expert"]:
            score -= 0.5; reasons.append("Exp-")
        elif "[~]" in p["expert"]:
            pass  # neutral

        p["signal_score"] = score
        p["signal_reasons"] = reasons
        p["fair_pct"] = p["ev_comp"] / total_ev * 100

    # Sort by signal score, then by EV
    relevant.sort(key=lambda x: (-x["signal_score"], -x["ev_comp"]))

    print(f"{'':>3} {'Player':<26} {'Fair%':>7} {'Score':>6} {'Signals'}")
    print("-" * 90)

    for i, p in enumerate(relevant, 1):
        score_str = f"{p['signal_score']:>+5.1f}"
        reasons_str = ", ".join(p["signal_reasons"])

        # Color-code with text marker
        if p["signal_score"] >= 2:
            marker = ">>>"
        elif p["signal_score"] >= 1:
            marker = " >>"
        elif p["signal_score"] <= -1.5:
            marker = "  X"
        elif p["signal_score"] <= -0.5:
            marker = "  x"
        else:
            marker = "   "

        print(f"{marker} {p['name']:<26} {p['fair_pct']:>6.2f}% {score_str}  {reasons_str}")


if __name__ == "__main__":
    csv_path = Path(__file__).parent.parent / "composite_odds_masters_tournament.csv"
    players = load_players(csv_path)
    print_divergence_table(players)
    print_buys_and_sells(players)
    print_coursefit_edge(players)
    print_composite_summary(players)
