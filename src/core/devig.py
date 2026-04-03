from __future__ import annotations

"""
Odds parsing, conversion, and de-vigging.

Ported from OAD system (compute_ev.py, dg_vs_books_analysis.py) with additions
for decimal odds conversion and independent-market de-vig.

De-vig methods:
- Power method (primary): finds exponent k where sum(p_i^k) = 1.
  Corrects for favorite-longshot bias. Validated via 35,064 player-event backtest.
- Independent method: for placement markets (T20, T10, etc.) where each line
  is a separate yes/no bet, not mutually exclusive.
"""


def parse_american_odds(odds_str: str) -> float | None:
    """Convert American odds string to raw implied probability.

    Examples:
        "+220"  -> 0.3125
        "-150"  -> 0.6
        "Inf"   -> None
    """
    if not odds_str or not isinstance(odds_str, str):
        return None

    s = odds_str.strip().strip('"')
    if s in ("", "Inf", "N/A", "n/a", "-"):
        return None

    try:
        if s.startswith("+"):
            odds = float(s[1:])
            if odds <= 0:
                return None
            return 100.0 / (odds + 100.0)
        elif s.startswith("-"):
            odds = abs(float(s[1:]))
            if odds <= 0:
                return None
            return odds / (odds + 100.0)
        else:
            odds = float(s)
            if odds > 0:
                return 100.0 / (odds + 100.0)
            elif odds < 0:
                return abs(odds) / (abs(odds) + 100.0)
            else:
                return None
    except (ValueError, ZeroDivisionError):
        return None


def american_to_decimal(odds_str: str) -> float | None:
    """Convert American odds string to decimal odds.

    Examples:
        "+220"  -> 3.20
        "-150"  -> 1.6667
    """
    if not odds_str or not isinstance(odds_str, str):
        return None

    s = odds_str.strip().strip('"')
    if s in ("", "Inf", "N/A", "n/a", "-"):
        return None

    try:
        if s.startswith("+"):
            odds = float(s[1:])
            return (odds / 100.0) + 1.0
        elif s.startswith("-"):
            odds = abs(float(s[1:]))
            if odds == 0:
                return None
            return (100.0 / odds) + 1.0
        else:
            odds = float(s)
            if odds > 0:
                return (odds / 100.0) + 1.0
            elif odds < 0:
                odds = abs(odds)
                if odds == 0:
                    return None
                return (100.0 / odds) + 1.0
            else:
                return None
    except (ValueError, ZeroDivisionError):
        return None


def decimal_to_american(decimal_odds: float) -> str:
    """Convert decimal odds to American odds string.

    Examples:
        3.20   -> "+220"
        1.6667 -> "-150"
    """
    if decimal_odds is None or decimal_odds <= 1.0:
        return ""

    if decimal_odds >= 2.0:
        american = (decimal_odds - 1.0) * 100.0
        return f"+{american:.0f}"
    else:
        american = 100.0 / (decimal_odds - 1.0)
        return f"-{american:.0f}"


def implied_prob_to_decimal(prob: float) -> float | None:
    """Convert implied probability to decimal odds.

    Example: 0.3125 -> 3.20
    """
    if prob is None or prob <= 0 or prob >= 1.0:
        return None
    return 1.0 / prob


def decimal_to_implied_prob(decimal_odds: float) -> float | None:
    """Convert decimal odds to implied probability.

    Example: 3.20 -> 0.3125
    """
    if decimal_odds is None or decimal_odds <= 0:
        return None
    return 1.0 / decimal_odds


def power_devig(raw_probs: list[float | None]) -> list[float | None]:
    """De-vig using the power method: find k where sum(p_i^k) = 1.

    The power method corrects for favorite-longshot bias by finding an
    exponent that properly rescales the probability distribution. Longshot
    probabilities are shrunk proportionally more than favorites.

    Empirical backtest (35,064 player-events, 2020-2026) confirmed this
    produces the best-calibrated probabilities (log-loss 0.038833 vs
    0.038903 for multiplicative method).

    Args:
        raw_probs: list of raw implied probabilities (sum > 1 due to vig).
                   None entries are preserved as-is.

    Returns:
        list of de-vigged probabilities (sum ≈ 1.0)
    """
    valid = [(i, p) for i, p in enumerate(raw_probs) if p is not None and p > 0]

    if not valid:
        return list(raw_probs)

    total = sum(p for _, p in valid)
    if abs(total - 1.0) < 0.001:
        return list(raw_probs)  # Already fair

    # Bisection to find k
    k_low, k_high = 0.5, 3.0
    for _ in range(200):
        k_mid = (k_low + k_high) / 2.0
        s = sum(p ** k_mid for _, p in valid)
        if s > 1.0:
            k_low = k_mid
        else:
            k_high = k_mid
        if abs(s - 1.0) < 1e-10:
            break

    k = (k_low + k_high) / 2.0
    result = list(raw_probs)
    for i, p in valid:
        result[i] = p ** k

    return result


def devig_independent(raw_probs: list[float | None],
                      expected_outcomes: float,
                      field_size: int | None = None) -> list[float | None]:
    """De-vig for independent-outcome markets (T20, T10, T5, make-cut).

    Each line is a separate yes/no bet. The vig is baked into each line
    individually. We estimate the per-line vig from the aggregate
    overround and remove it uniformly (multiplicative scaling).

    Args:
        raw_probs: list of raw implied probabilities for each player
        expected_outcomes: expected number of "yes" outcomes (e.g., 20 for T20)
        field_size: total number of players (optional, for validation)

    Returns:
        list of de-vigged probabilities
    """
    valid = [(i, p) for i, p in enumerate(raw_probs) if p is not None and p > 0]

    if not valid:
        return list(raw_probs)

    total = sum(p for _, p in valid)
    if total <= expected_outcomes:
        return list(raw_probs)  # No vig detected

    scale = expected_outcomes / total
    result = list(raw_probs)
    for i, p in valid:
        result[i] = p * scale

    return result


def devig_two_way(prob_yes: float, prob_no: float) -> tuple[float, float]:
    """De-vig a two-way market (e.g., make-cut yes/no, matchup A/B).

    Uses power method on the two-outcome market.

    Returns:
        (devigged_yes, devigged_no)
    """
    if prob_yes is None or prob_no is None:
        return (prob_yes, prob_no)

    total = prob_yes + prob_no
    if abs(total - 1.0) < 0.001:
        return (prob_yes, prob_no)

    result = power_devig([prob_yes, prob_no])
    return (result[0], result[1])


def devig_three_way(prob_a: float, prob_b: float, prob_c: float) -> tuple[float, float, float]:
    """De-vig a three-way market (e.g., 3-ball).

    Uses power method on the three-outcome market.

    Returns:
        (devigged_a, devigged_b, devigged_c)
    """
    if any(p is None for p in [prob_a, prob_b, prob_c]):
        return (prob_a, prob_b, prob_c)

    result = power_devig([prob_a, prob_b, prob_c])
    return (result[0], result[1], result[2])
