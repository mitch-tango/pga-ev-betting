from __future__ import annotations

"""
Arbitrage detection across sportsbooks.

Scans matchup and 3-ball odds for cross-book arbitrage opportunities
where the combined implied probability sums to < 1.0 (guaranteed profit).

Runs alongside the existing +EV edge detection — same data, separate output.
"""

from dataclasses import dataclass, field
from itertools import product

from src.core.devig import parse_american_odds, american_to_decimal, decimal_to_american
from src.core.edge import CandidateBet
from src.db import supabase_client as db
import config


@dataclass
class ArbLeg:
    """One leg of an arbitrage opportunity."""
    player: str
    book: str
    odds_decimal: float
    implied_prob: float  # 1 / odds_decimal
    stake: float = 0.0   # Filled by size_arb()


@dataclass
class ArbOpportunity:
    """A detected cross-book arbitrage opportunity."""
    market_type: str          # tournament_matchup, round_matchup, 3_ball
    legs: list[ArbLeg]
    combined_implied: float   # Sum of implied probs (< 1.0 = arb)
    margin: float             # 1.0 - combined_implied (profit %)
    round_number: int | None = None
    settlement_warning: str | None = None  # Set if tie/WD rules differ


def detect_matchup_arbs(
    matchups_data: list[dict],
    market_type: str = "tournament_matchup",
    round_number: int | None = None,
) -> list[ArbOpportunity]:
    """Detect arbitrage opportunities in matchup odds across books.

    For each matchup, checks every combination of (book_for_p1, book_for_p2)
    to find cross-book arbs where 1/odds_p1 + 1/odds_p2 < 1.

    Args:
        matchups_data: List of matchup records from DG API.
        market_type: "tournament_matchup" or "round_matchup"
        round_number: Round number (for display)

    Returns:
        List of ArbOpportunity sorted by margin descending.
    """
    min_margin = config.ARB_MIN_MARGIN
    arbs = []

    for matchup in matchups_data:
        odds_dict = matchup.get("odds", {})
        p1_name = matchup.get("p1_player_name", "")
        p2_name = matchup.get("p2_player_name", "")

        # Collect bettable (raw, not de-vigged) decimal odds per book
        book_odds = {}  # {book: {"p1": decimal, "p2": decimal}}
        for book_name, book_data in odds_dict.items():
            if book_name == "datagolf":
                continue

            p1_dec = american_to_decimal(str(book_data.get("p1", "")))
            p2_dec = american_to_decimal(str(book_data.get("p2", "")))

            if p1_dec is not None and p1_dec > 1 and p2_dec is not None and p2_dec > 1:
                book_odds[book_name] = {"p1": p1_dec, "p2": p2_dec}

        if len(book_odds) < 2:
            continue

        books = list(book_odds.keys())

        # Check all cross-book combinations for p1 @ book_a, p2 @ book_b
        for book_a, book_b in product(books, books):
            if book_a == book_b:
                continue

            p1_dec = book_odds[book_a]["p1"]
            p2_dec = book_odds[book_b]["p2"]

            combined = (1.0 / p1_dec) + (1.0 / p2_dec)

            if combined < 1.0:
                margin = 1.0 - combined
                if margin < min_margin:
                    continue

                warning = _check_settlement_mismatch(
                    book_a, book_b, market_type)

                arbs.append(ArbOpportunity(
                    market_type=market_type,
                    legs=[
                        ArbLeg(player=p1_name, book=book_a,
                               odds_decimal=p1_dec,
                               implied_prob=1.0 / p1_dec),
                        ArbLeg(player=p2_name, book=book_b,
                               odds_decimal=p2_dec,
                               implied_prob=1.0 / p2_dec),
                    ],
                    combined_implied=round(combined, 6),
                    margin=round(margin, 6),
                    round_number=round_number,
                    settlement_warning=warning,
                ))

    # Deduplicate: keep only the best margin per player pair
    arbs = _dedupe_arbs(arbs)
    arbs.sort(key=lambda a: a.margin, reverse=True)
    return arbs


def detect_3ball_arbs(
    three_ball_data: list[dict],
    round_number: int | None = None,
) -> list[ArbOpportunity]:
    """Detect arbitrage in 3-ball odds across books.

    Checks all permutations of (book_p1, book_p2, book_p3) for arbs.

    Args:
        three_ball_data: List of 3-ball records from DG API.
        round_number: Round number (for display)

    Returns:
        List of ArbOpportunity sorted by margin descending.
    """
    min_margin = config.ARB_MIN_MARGIN
    arbs = []

    for group in three_ball_data:
        odds_dict = group.get("odds", {})
        players = [
            group.get("p1_player_name", ""),
            group.get("p2_player_name", ""),
            group.get("p3_player_name", ""),
        ]

        # Collect odds per book
        book_odds = {}  # {book: [p1_dec, p2_dec, p3_dec]}
        for book_name, book_data in odds_dict.items():
            if book_name == "datagolf":
                continue

            decimals = []
            for key in ["p1", "p2", "p3"]:
                d = american_to_decimal(str(book_data.get(key, "")))
                decimals.append(d)

            if all(d is not None and d > 1 for d in decimals):
                book_odds[book_name] = decimals

        if len(book_odds) < 2:
            continue

        books = list(book_odds.keys())

        # Check all cross-book permutations
        for combo in product(books, books, books):
            # Need at least 2 different books for a cross-book arb
            if len(set(combo)) < 2:
                continue

            combined = sum(
                1.0 / book_odds[combo[i]][i] for i in range(3)
            )

            if combined < 1.0:
                margin = 1.0 - combined
                if margin < min_margin:
                    continue

                legs = []
                for i in range(3):
                    dec = book_odds[combo[i]][i]
                    legs.append(ArbLeg(
                        player=players[i],
                        book=combo[i],
                        odds_decimal=dec,
                        implied_prob=1.0 / dec,
                    ))

                arbs.append(ArbOpportunity(
                    market_type="3_ball",
                    legs=legs,
                    combined_implied=round(combined, 6),
                    margin=round(margin, 6),
                    round_number=round_number,
                ))

    arbs = _dedupe_arbs(arbs)
    arbs.sort(key=lambda a: a.margin, reverse=True)
    return arbs


def arb_legs_to_candidates(
    arbs: list[ArbOpportunity],
    total_return: float | None = None,
) -> list[CandidateBet]:
    """Flatten detected arbs into per-leg CandidateBet rows.

    Each leg becomes a standalone candidate so it can be persisted to
    `candidate_bets` and picked up by Discord `/place` the same way a
    regular +EV candidate is. The full arb (margin, sibling legs,
    settlement warnings) is preserved in `all_book_odds` so placement and
    settlement paths can reconstruct the opportunity a leg belongs to.

    Sizes each arb via `size_arb(total_return)` as a side effect so the
    `suggested_stake` on each returned leg matches what gets displayed in
    the scan embed. Set `qualifies=True` and `edge=margin` so legs clear
    the /place "info-only" gate but analytics that filter by scan_type can
    still separate arb legs from +EV candidates.
    """
    ret = total_return if total_return is not None else config.ARB_DEFAULT_RETURN
    result: list[CandidateBet] = []

    for arb in arbs:
        size_arb(arb, ret)
        total_outlay = sum(leg.stake for leg in arb.legs)
        profit = round(ret - total_outlay, 2)

        leg_meta = [
            {
                "player": leg.player,
                "book": leg.book,
                "odds_decimal": leg.odds_decimal,
                "stake": leg.stake,
            }
            for leg in arb.legs
        ]

        for leg_idx, leg in enumerate(arb.legs):
            others = [
                arb.legs[k].player
                for k in range(len(arb.legs))
                if k != leg_idx
            ]
            opponent_name = others[0] if len(others) >= 1 else None
            opponent_2_name = others[1] if len(others) >= 2 else None

            result.append(CandidateBet(
                market_type=arb.market_type,
                player_name=leg.player,
                opponent_name=opponent_name,
                opponent_2_name=opponent_2_name,
                round_number=arb.round_number,
                your_prob=leg.implied_prob,
                best_book=leg.book,
                best_odds_decimal=leg.odds_decimal,
                best_odds_american=decimal_to_american(leg.odds_decimal) or "",
                best_implied_prob=leg.implied_prob,
                raw_edge=arb.margin,
                edge=arb.margin,
                suggested_stake=leg.stake,
                kelly_fraction=None,
                correlation_haircut=1.0,
                qualifies=True,
                bet_min_edge=0.0,
                all_book_odds={
                    "arb_margin": arb.margin,
                    "arb_combined_implied": arb.combined_implied,
                    "arb_profit": profit,
                    "arb_total_return": ret,
                    "arb_settlement_warning": arb.settlement_warning,
                    "arb_legs": leg_meta,
                    "arb_leg_index": leg_idx,
                },
            ))

    return result


def size_arb(arb: ArbOpportunity, total_return: float) -> list[ArbLeg]:
    """Calculate stakes for each leg to guarantee total_return.

    Args:
        arb: The arbitrage opportunity
        total_return: Desired guaranteed return (payout from any outcome)

    Returns:
        Updated legs with stake filled in.
        Total outlay = sum of stakes = total_return * combined_implied.
        Guaranteed profit = total_return - total_outlay = total_return * margin.
    """
    for leg in arb.legs:
        leg.stake = round(total_return / leg.odds_decimal, 2)
    return arb.legs


def format_arb_table(arbs: list[ArbOpportunity],
                     default_return: float | None = None) -> str:
    """Format arb opportunities as a text table for CLI or Discord.

    Args:
        arbs: List of arb opportunities
        default_return: If set, show stakes for this guaranteed return amount

    Returns:
        Formatted string
    """
    if not arbs:
        return "No arbitrage opportunities found."

    ret = default_return or config.ARB_DEFAULT_RETURN

    lines = []
    lines.append(
        f"{'#':>2} {'Players':<30} {'Mkt':<8} "
        f"{'Leg1':<18} {'Leg2':<18} {'Margin':>6} {'Profit':>7}"
    )

    for i, arb in enumerate(arbs, 1):
        size_arb(arb, ret)
        total_outlay = sum(leg.stake for leg in arb.legs)
        profit = ret - total_outlay

        # Player names
        names = " v ".join(leg.player.split(",")[0][:14] for leg in arb.legs)

        # Leg details: "book @odds $stake"
        leg_strs = []
        for leg in arb.legs:
            leg_strs.append(f"{leg.book[:8]}${leg.stake:.0f}")

        mkt = arb.market_type
        if arb.round_number:
            mkt = f"R{arb.round_number}H2H" if "matchup" in mkt else f"R{arb.round_number}3B"

        warning = " *" if arb.settlement_warning else ""

        line = (
            f"{i:>2} {names:<30} {mkt:<8} "
            f"{leg_strs[0]:<18} {leg_strs[1]:<18} "
            f"{arb.margin*100:>5.1f}% ${profit:>5.2f}{warning}"
        )
        # 3-ball has a third leg
        if len(leg_strs) > 2:
            line = (
                f"{i:>2} {names:<30} {mkt:<8} "
                f"{arb.margin*100:>5.1f}% ${profit:>5.2f}{warning}"
            )
            for j, leg in enumerate(arb.legs):
                lines.append(f"   Leg {j+1}: {leg.player[:16]} @ "
                             f"{leg.book} {leg.odds_decimal:.2f} "
                             f"${leg.stake:.0f}")
            lines.append(line)
            continue

        lines.append(line)

    # Add settlement warning footnote if any arbs have warnings
    if any(a.settlement_warning for a in arbs):
        lines.append("")
        lines.append("* Settlement rules differ between books:")
        for a in arbs:
            if a.settlement_warning:
                names = " v ".join(leg.player.split(",")[0][:14]
                                   for leg in a.legs)
                lines.append(f"  {names}: {a.settlement_warning}")

    return "\n".join(lines)


# --- Internal helpers ---

def _check_settlement_mismatch(
    book_a: str, book_b: str, market_type: str,
) -> str | None:
    """Check if two books have different tie/WD rules for this market.

    Returns a warning string if rules differ, None if they match.
    """
    try:
        rule_a = db.get_book_rule(book_a, market_type)
        rule_b = db.get_book_rule(book_b, market_type)
    except Exception:
        return "unable to verify settlement rules"

    if rule_a is None or rule_b is None:
        missing = []
        if rule_a is None:
            missing.append(book_a)
        if rule_b is None:
            missing.append(book_b)
        return f"no settlement rules on file for {', '.join(missing)}"

    mismatches = []
    if rule_a.get("tie_rule") != rule_b.get("tie_rule"):
        mismatches.append(
            f"tie: {book_a}={rule_a.get('tie_rule')} vs "
            f"{book_b}={rule_b.get('tie_rule')}"
        )
    if rule_a.get("wd_rule") != rule_b.get("wd_rule"):
        mismatches.append(
            f"WD: {book_a}={rule_a.get('wd_rule')} vs "
            f"{book_b}={rule_b.get('wd_rule')}"
        )

    return "; ".join(mismatches) if mismatches else None


def _dedupe_arbs(arbs: list[ArbOpportunity]) -> list[ArbOpportunity]:
    """Keep only the best-margin arb for each unique set of players."""
    best = {}
    for arb in arbs:
        key = frozenset(leg.player for leg in arb.legs)
        if key not in best or arb.margin > best[key].margin:
            best[key] = arb
    return list(best.values())
