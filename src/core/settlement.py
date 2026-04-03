from __future__ import annotations

"""
Dead-heat rules and book-specific settlement logic (Amendment #2).

Handles:
- Dead-heat reduction for placement ties (T5/T10/T20)
- Push/void for matchup ties and withdrawals
- Book-specific settlement rule lookup
- Edge adjustment for expected dead-heat frequency
"""

import config


# Expected dead-heat frequency by market type (conservative estimates).
# Will be refined by the dead-heat backtest (Phase 1.5).
DEADHEAT_FREQUENCY = {
    "t5": 0.06,    # ~6% of T5 bets hit dead-heat
    "t10": 0.09,   # ~9%
    "t20": 0.13,   # ~13%
}


def adjust_edge_for_deadheat(raw_edge: float, market_type: str,
                              decimal_odds: float) -> tuple[float, float]:
    """Adjust raw edge to account for expected dead-heat reduction.

    When a player ties at the cutoff position (e.g., T19 with 3 players
    tied for a T20 bet), books apply dead-heat reduction: payout is
    reduced proportionally.

    The average impact depends on:
    - How often dead-heats occur at this cutoff (frequency)
    - How many players typically tie (usually 2-4)
    - The odds (higher odds = larger absolute reduction)

    This applies a conservative average reduction from config.

    Args:
        raw_edge: your_prob - implied_prob (before dead-heat)
        market_type: 't5', 't10', 't20' (only these have dead-heat risk)
        decimal_odds: the decimal odds being bet

    Returns:
        (adjusted_edge, deadheat_adjustment)
        deadheat_adjustment is negative (reduces edge)
    """
    if market_type not in config.DEADHEAT_AVG_REDUCTION:
        return (raw_edge, 0.0)

    reduction = config.DEADHEAT_AVG_REDUCTION[market_type]
    adjusted = raw_edge - reduction

    return (adjusted, -reduction)


def settle_placement_bet(actual_finish: int, threshold: int,
                          stake: float, decimal_odds: float,
                          tied_at_cutoff: int = 1,
                          tie_rule: str = "dead_heat") -> dict:
    """Settle a placement bet (T5/T10/T20/MC/win).

    Args:
        actual_finish: player's actual finish position (1-based)
        threshold: market threshold (5 for T5, 10 for T10, etc.)
        stake: dollar amount wagered
        decimal_odds: decimal odds at bet time
        tied_at_cutoff: number of players tied at the cutoff position
                        (1 = no dead-heat, 2+ = dead-heat applies)
        tie_rule: "dead_heat" (standard), "push", or "ties_lose"

    Returns:
        {"outcome": str, "settlement_rule": str, "payout": float, "pnl": float}
    """
    # Clear win (finished above cutoff, no dead-heat issue)
    if actual_finish < threshold or (actual_finish <= threshold and tied_at_cutoff <= 1):
        if actual_finish <= threshold:
            payout = stake * decimal_odds
            return {
                "outcome": "win",
                "settlement_rule": "standard",
                "payout": round(payout, 2),
                "pnl": round(payout - stake, 2),
            }

    # Dead-heat at cutoff
    if actual_finish == threshold and tied_at_cutoff > 1:
        # How many of the tied players "fit" inside the threshold?
        # E.g., T20 with 3 tied at 19th: all 3 are within T20, no dead-heat.
        # T20 with 3 tied at 20th: depends on how many spots are left.
        # Standard dead-heat: reduce stake proportionally.
        if tie_rule == "dead_heat":
            # Standard dead-heat reduction
            effective_stake = stake / tied_at_cutoff
            payout = effective_stake * decimal_odds
            return {
                "outcome": "half_win",
                "settlement_rule": "dead_heat",
                "payout": round(payout, 2),
                "pnl": round(payout - stake, 2),
            }
        elif tie_rule == "push":
            return {
                "outcome": "push",
                "settlement_rule": "push",
                "payout": round(stake, 2),
                "pnl": 0.0,
            }
        elif tie_rule == "ties_lose":
            return {
                "outcome": "loss",
                "settlement_rule": "ties_lose",
                "payout": 0.0,
                "pnl": round(-stake, 2),
            }

    # Clear loss (finished below threshold)
    return {
        "outcome": "loss",
        "settlement_rule": "standard",
        "payout": 0.0,
        "pnl": round(-stake, 2),
    }


def settle_matchup_bet(player_finish: int | None,
                        opponent_finish: int | None,
                        stake: float, decimal_odds: float,
                        tie_rule: str = "push",
                        wd_rule: str = "void") -> dict:
    """Settle a head-to-head matchup bet.

    Args:
        player_finish: your player's finish (None if WD/DQ)
        opponent_finish: opponent's finish (None if WD/DQ)
        stake: dollar amount wagered
        decimal_odds: decimal odds at bet time
        tie_rule: "push" (most books) or "dead_heat"
        wd_rule: "void" (most books) or "loss"

    Returns:
        {"outcome": str, "settlement_rule": str, "payout": float, "pnl": float}
    """
    # Handle withdrawals
    if player_finish is None or opponent_finish is None:
        if wd_rule == "void":
            return {
                "outcome": "void",
                "settlement_rule": "void_wd",
                "payout": round(stake, 2),
                "pnl": 0.0,
            }
        elif wd_rule == "loss":
            if player_finish is None:
                return {
                    "outcome": "loss",
                    "settlement_rule": "wd_loss",
                    "payout": 0.0,
                    "pnl": round(-stake, 2),
                }
            else:
                payout = stake * decimal_odds
                return {
                    "outcome": "win",
                    "settlement_rule": "opponent_wd",
                    "payout": round(payout, 2),
                    "pnl": round(payout - stake, 2),
                }

    # Tie
    if player_finish == opponent_finish:
        if tie_rule == "push":
            return {
                "outcome": "push",
                "settlement_rule": "push",
                "payout": round(stake, 2),
                "pnl": 0.0,
            }
        elif tie_rule == "dead_heat":
            effective_stake = stake / 2
            payout = effective_stake * decimal_odds
            return {
                "outcome": "half_win",
                "settlement_rule": "dead_heat",
                "payout": round(payout, 2),
                "pnl": round(payout - stake, 2),
            }

    # Win (lower finish = better)
    if player_finish < opponent_finish:
        payout = stake * decimal_odds
        return {
            "outcome": "win",
            "settlement_rule": "standard",
            "payout": round(payout, 2),
            "pnl": round(payout - stake, 2),
        }

    # Loss
    return {
        "outcome": "loss",
        "settlement_rule": "standard",
        "payout": 0.0,
        "pnl": round(-stake, 2),
    }


def settle_3ball_bet(player_score: int | None,
                      opp1_score: int | None,
                      opp2_score: int | None,
                      stake: float, decimal_odds: float,
                      tie_rule: str = "dead_heat",
                      wd_rule: str = "void") -> dict:
    """Settle a 3-ball bet (lowest round score wins).

    Args:
        player_score: your player's round score (None if WD)
        opp1_score: opponent 1's round score
        opp2_score: opponent 2's round score
        stake: dollar amount wagered
        decimal_odds: decimal odds at bet time
        tie_rule: "dead_heat" (standard for 3-balls)
        wd_rule: "void" or "loss"

    Returns:
        {"outcome": str, "settlement_rule": str, "payout": float, "pnl": float}
    """
    # Handle withdrawals
    scores = [player_score, opp1_score, opp2_score]
    if player_score is None:
        if wd_rule == "void":
            return {
                "outcome": "void",
                "settlement_rule": "void_wd",
                "payout": round(stake, 2),
                "pnl": 0.0,
            }
        else:
            return {
                "outcome": "loss",
                "settlement_rule": "wd_loss",
                "payout": 0.0,
                "pnl": round(-stake, 2),
            }

    valid_scores = [s for s in scores if s is not None]
    min_score = min(valid_scores)

    # Player didn't have the lowest score
    if player_score > min_score:
        return {
            "outcome": "loss",
            "settlement_rule": "standard",
            "payout": 0.0,
            "pnl": round(-stake, 2),
        }

    # Player tied for lowest
    tied_count = sum(1 for s in valid_scores if s == min_score)

    if tied_count == 1:
        # Outright win
        payout = stake * decimal_odds
        return {
            "outcome": "win",
            "settlement_rule": "standard",
            "payout": round(payout, 2),
            "pnl": round(payout - stake, 2),
        }
    else:
        # Dead-heat
        if tie_rule == "dead_heat":
            effective_stake = stake / tied_count
            payout = effective_stake * decimal_odds
            return {
                "outcome": "half_win",
                "settlement_rule": "dead_heat",
                "payout": round(payout, 2),
                "pnl": round(payout - stake, 2),
            }
        elif tie_rule == "push":
            return {
                "outcome": "push",
                "settlement_rule": "push",
                "payout": round(stake, 2),
                "pnl": 0.0,
            }

    return {
        "outcome": "loss",
        "settlement_rule": "standard",
        "payout": 0.0,
        "pnl": round(-stake, 2),
    }
