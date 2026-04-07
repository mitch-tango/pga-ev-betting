from __future__ import annotations

"""
Probability blending — market-specific DG/books weights.

Combines DataGolf model probabilities with sportsbook consensus to produce
the "your probability" estimate used for edge calculation.

Blend weights are calibrated from OAD backtest (278 events, 2020-2026):
- Win market: 35% DG / 65% books (temporally unstable by tranche — keep global)
- Placement (T10/T20): tranche-specific (fav 100/0, mid 55/45, LS 45/55)
- Make-cut: 80% DG / 20% books (DG dominates; stable across periods)
- Matchup: tranche-specific (favorites 60/40, mid 30/70, longshots 0/100)
- Signature events ($20M+): shift toward books (higher volume = sharper lines)
- Deep field (rank 61+): 100% DG (books don't price longshots accurately)
"""

from src.core.devig import power_devig, devig_two_way, devig_three_way
import config


def classify_tranche(win_prob: float) -> str:
    """Classify a player's tranche based on DG win probability.

    Args:
        win_prob: DG model win probability (0-1 scale)

    Returns:
        'favorite', 'mid', or 'longshot'
    """
    if win_prob >= config.TRANCHE_THRESHOLDS["favorite"]:
        return "favorite"
    elif win_prob >= config.TRANCHE_THRESHOLDS["mid"]:
        return "mid"
    return "longshot"


def get_blend_weights(market_type: str, is_signature: bool = False,
                      player_field_rank: int | None = None,
                      tranche: str | None = None) -> dict:
    """Return the appropriate DG/books blend weights for this context.

    Args:
        market_type: 'win', 't5', 't10', 't20', 'make_cut',
                     'tournament_matchup', 'round_matchup', '3_ball'
        is_signature: True for $20M+ purse events
        player_field_rank: Player's rank in the field (for deep-field override)
        tranche: 'favorite', 'mid', or 'longshot' — used for placement
                 and matchup markets to select tranche-specific blend weights

    Returns:
        {"dg": float, "books": float} summing to 1.0
    """
    # Deep field override: 100% DG regardless of market
    if player_field_rank and player_field_rank >= config.DEEP_FIELD_RANK_THRESHOLD:
        return config.BLEND_WEIGHTS["deep_field"]

    # Signature event overrides
    if is_signature:
        if market_type == "win":
            return config.BLEND_WEIGHTS["signature_win"]
        elif market_type in ("t5", "t10", "t20"):
            return config.BLEND_WEIGHTS["signature_placement"]

    # Standard weights by market type
    if market_type == "win":
        return config.BLEND_WEIGHTS["win"]
    elif market_type in ("t5", "t10", "t20"):
        if tranche and tranche in config.PLACEMENT_TRANCHE_WEIGHTS:
            return config.PLACEMENT_TRANCHE_WEIGHTS[tranche]
        return config.BLEND_WEIGHTS["placement"]
    elif market_type == "make_cut":
        if tranche and tranche in config.MAKE_CUT_TRANCHE_WEIGHTS:
            return config.MAKE_CUT_TRANCHE_WEIGHTS[tranche]
        return config.BLEND_WEIGHTS["make_cut"]
    elif market_type in ("tournament_matchup", "round_matchup"):
        if tranche and tranche in config.MATCHUP_TRANCHE_WEIGHTS:
            return config.MATCHUP_TRANCHE_WEIGHTS[tranche]
        return config.BLEND_WEIGHTS["matchup"]
    elif market_type == "3_ball":
        return config.BLEND_WEIGHTS["three_ball"]
    else:
        # Unknown market — default to placement weights
        return config.BLEND_WEIGHTS["placement"]


def blend_probabilities(dg_prob: float | None,
                        book_consensus_prob: float | None,
                        market_type: str,
                        is_signature: bool = False,
                        player_field_rank: int | None = None,
                        tranche: str | None = None) -> float | None:
    """Blend DG and book consensus probabilities using calibrated weights.

    Args:
        dg_prob: DataGolf model probability
        book_consensus_prob: Weighted book consensus (after de-vig)
        market_type: Market type string
        is_signature: True for $20M+ events
        player_field_rank: For deep-field override (rank 61+ -> 100% DG)
        tranche: 'favorite', 'mid', or 'longshot' for matchup markets

    Returns:
        Blended probability, or None if both inputs are None
    """
    if dg_prob is None and book_consensus_prob is None:
        return None

    weights = get_blend_weights(market_type, is_signature, player_field_rank,
                                tranche=tranche)

    if dg_prob is not None and book_consensus_prob is not None:
        return weights["dg"] * dg_prob + weights["books"] * book_consensus_prob
    elif dg_prob is not None:
        return dg_prob
    else:
        return book_consensus_prob


def build_book_consensus(book_probs: dict[str, float | None],
                         market_type: str) -> float | None:
    """Build weighted book consensus from multiple books' de-vigged probabilities.

    Args:
        book_probs: {"pinnacle": 0.045, "draftkings": 0.052, ...}
                    Values are de-vigged implied probabilities per book.
        market_type: Determines weighting scheme (win/MC use sharp 2x,
                     placement uses equal weight)

    Returns:
        Weighted consensus probability, or None if no valid books
    """
    # Determine which weight set to use
    if market_type == "win":
        weight_config = config.BOOK_WEIGHTS.get("win", {})
    elif market_type == "make_cut":
        weight_config = config.BOOK_WEIGHTS.get("make_cut", {})
    elif market_type in ("t5", "t10", "t20"):
        weight_config = config.BOOK_WEIGHTS.get("placement", {})
    else:
        weight_config = config.BOOK_WEIGHTS.get("placement", {})

    weighted_sum = 0.0
    weight_sum = 0.0

    for book_name, prob in book_probs.items():
        if prob is None or prob <= 0:
            continue

        book_key = book_name.lower().strip()
        weight = weight_config.get(book_key, 1)  # Default to 1 if book unknown

        weighted_sum += weight * prob
        weight_sum += weight

    if weight_sum <= 0:
        return None

    return weighted_sum / weight_sum


def build_book_consensus_for_field(
    field_book_probs: dict[str, dict[str, float | None]],
    market_type: str
) -> dict[str, float | None]:
    """Build book consensus for every player in the field.

    Args:
        field_book_probs: {
            "player_name": {"pinnacle": 0.045, "draftkings": 0.052, ...},
            ...
        }
        market_type: Market type for weight selection

    Returns:
        {"player_name": consensus_prob, ...}
    """
    return {
        player: build_book_consensus(books, market_type)
        for player, books in field_book_probs.items()
    }
