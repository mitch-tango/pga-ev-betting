from __future__ import annotations

"""
Kelly criterion sizing with correlation haircut.

Implements fractional Kelly for bet sizing with:
- Configurable Kelly fraction (default: quarter-Kelly = 0.25)
- Correlation haircut for same-player bets (Amendment #1)
- Exposure limits: per-bet, per-player, per-tournament, per-week
"""

import config


def kelly_stake(edge: float, decimal_odds: float, bankroll: float,
                kelly_fraction: float | None = None,
                max_bet_pct: float | None = None,
                correlation_haircut: float = 1.0) -> float:
    """Compute stake using fractional Kelly criterion with correlation adjustment.

    Kelly % = edge / (decimal_odds - 1)
    Stake = bankroll x Kelly% x kelly_fraction x correlation_haircut
    Capped at max_bet_pct x bankroll

    Args:
        edge: your_prob - implied_prob (e.g., 0.05 for 5%)
        decimal_odds: decimal odds at the book (e.g., 3.20)
        bankroll: current bankroll in dollars
        kelly_fraction: fraction of Kelly to use (default from config)
        max_bet_pct: max single bet as pct of bankroll (default from config)
        correlation_haircut: multiplier for correlated bets (1.0/0.5/0.25/0.125)

    Returns:
        stake in dollars (rounded to nearest $1), minimum $0
    """
    if edge <= 0 or decimal_odds <= 1.0 or bankroll <= 0:
        return 0.0

    kf = kelly_fraction if kelly_fraction is not None else config.KELLY_FRACTION
    mbp = max_bet_pct if max_bet_pct is not None else config.MAX_SINGLE_BET_PCT

    kelly_pct = edge / (decimal_odds - 1.0)
    raw_stake = bankroll * kelly_pct * kf * correlation_haircut
    max_stake = bankroll * mbp

    stake = min(raw_stake, max_stake)
    return max(round(stake, 0), 0.0)


def get_correlation_haircut(player_name: str,
                            existing_bets: list[dict]) -> float:
    """Determine the correlation haircut for a new bet on this player.

    Counts how many existing bets involve the same player (as primary
    or as opponent in matchups) and returns the appropriate haircut.

    Args:
        player_name: canonical player name
        existing_bets: list of bet dicts with 'player_name',
                       'opponent_name', 'opponent_2_name' keys

    Returns:
        Haircut multiplier: 1.0 (first bet), 0.5, 0.25, 0.125 (4th+)
    """
    name_lower = player_name.lower().strip()
    count = 0

    for bet in existing_bets:
        bet_players = [
            (bet.get("player_name") or "").lower().strip(),
            (bet.get("opponent_name") or "").lower().strip(),
            (bet.get("opponent_2_name") or "").lower().strip(),
        ]
        if name_lower in bet_players:
            count += 1

    haircuts = config.CORRELATION_HAIRCUT
    if count >= len(haircuts):
        return haircuts[-1]
    return haircuts[count]


def check_exposure(candidate_stake: float,
                   player_name: str,
                   tournament_id: str,
                   bankroll: float,
                   existing_bets: list[dict]) -> dict:
    """Check whether a candidate bet passes all exposure limits.

    Args:
        candidate_stake: proposed stake for the new bet
        player_name: canonical player name
        tournament_id: tournament identifier
        bankroll: current bankroll
        existing_bets: list of existing open bets with keys:
            'stake', 'player_name', 'opponent_name',
            'opponent_2_name', 'tournament_id', 'bet_timestamp'

    Returns:
        {
            "approved": bool,
            "stake": float (may be reduced),
            "warnings": list[str],
            "blocked_by": str or None
        }
    """
    warnings = []
    approved = True
    adjusted_stake = candidate_stake
    blocked_by = None

    # Weekly exposure
    weekly_total = sum(b.get("stake", 0) for b in existing_bets)
    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
    if weekly_total + candidate_stake > weekly_limit:
        remaining = max(0, weekly_limit - weekly_total)
        if remaining <= 0:
            approved = False
            blocked_by = "weekly_exposure"
            warnings.append(
                f"Weekly limit reached: ${weekly_total:.0f} / ${weekly_limit:.0f}"
            )
        else:
            adjusted_stake = min(adjusted_stake, remaining)
            warnings.append(
                f"Stake reduced to ${adjusted_stake:.0f} (weekly limit)"
            )

    # Per-player exposure
    name_lower = player_name.lower().strip()
    player_total = sum(
        b.get("stake", 0) for b in existing_bets
        if name_lower in [
            (b.get("player_name") or "").lower().strip(),
            (b.get("opponent_name") or "").lower().strip(),
            (b.get("opponent_2_name") or "").lower().strip(),
        ]
    )
    player_limit = bankroll * config.MAX_PLAYER_EXPOSURE_PCT
    if player_total + adjusted_stake > player_limit:
        remaining = max(0, player_limit - player_total)
        if remaining <= 0:
            approved = False
            blocked_by = blocked_by or "player_exposure"
            warnings.append(
                f"Player limit reached for {player_name}: "
                f"${player_total:.0f} / ${player_limit:.0f}"
            )
        else:
            adjusted_stake = min(adjusted_stake, remaining)
            warnings.append(
                f"Stake reduced to ${adjusted_stake:.0f} (player limit)"
            )

    # Per-tournament exposure
    tournament_total = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    )
    tournament_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT
    if tournament_total + adjusted_stake > tournament_limit:
        remaining = max(0, tournament_limit - tournament_total)
        if remaining <= 0:
            approved = False
            blocked_by = blocked_by or "tournament_exposure"
            warnings.append(
                f"Tournament limit reached: "
                f"${tournament_total:.0f} / ${tournament_limit:.0f}"
            )
        else:
            adjusted_stake = min(adjusted_stake, remaining)
            warnings.append(
                f"Stake reduced to ${adjusted_stake:.0f} (tournament limit)"
            )

    return {
        "approved": approved,
        "stake": adjusted_stake if approved else 0.0,
        "warnings": warnings,
        "blocked_by": blocked_by,
    }
