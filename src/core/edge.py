from __future__ import annotations

"""
Edge calculator — the core of the betting system.

Takes odds data from DG API (outrights + matchups), computes blended
probabilities, identifies +EV opportunities, and sizes bets with
Kelly criterion + correlation haircut.

Three modes:
1. Placement edges (T5, T10, T20, MC, win)
2. Matchup edges (tournament H2H, round H2H)
3. 3-ball edges

Each mode outputs a list of CandidateBet dicts sorted by edge descending,
ready for insertion into the candidate_bets Supabase table.
"""

from dataclasses import dataclass, asdict
from typing import Any

import logging

from src.core.devig import (
    parse_american_odds, american_to_decimal, decimal_to_american,
    implied_prob_to_decimal, power_devig, devig_independent,
    devig_two_way, devig_three_way,
    binary_price_to_decimal,
)
from src.core.blend import blend_probabilities, build_book_consensus
from src.core.kelly import kelly_stake, get_correlation_haircut
from src.core.settlement import adjust_edge_for_deadheat
import config

logger = logging.getLogger(__name__)


@dataclass
class CandidateBet:
    """A candidate +EV bet identified by the edge calculator."""
    market_type: str
    player_name: str
    player_dg_id: str | None = None
    player_id: str | None = None  # Supabase players.id (set by resolve step)
    opponent_name: str | None = None
    opponent_dg_id: str | None = None
    opponent_id: str | None = None
    opponent_2_name: str | None = None
    opponent_2_dg_id: str | None = None
    opponent_2_id: str | None = None
    round_number: int | None = None

    # Probabilities
    dg_prob: float = 0.0
    book_consensus_prob: float | None = None
    your_prob: float = 0.0

    # Best available line
    best_book: str = ""
    best_odds_decimal: float = 0.0
    best_odds_american: str = ""
    best_implied_prob: float = 0.0

    # Edge & sizing
    raw_edge: float = 0.0
    deadheat_adj: float = 0.0
    edge: float = 0.0
    kelly_fraction: float | None = None
    correlation_haircut: float = 1.0
    suggested_stake: float = 0.0

    # All book odds
    all_book_odds: dict | None = None

    def to_db_dict(self, tournament_id: str, scan_type: str) -> dict:
        """Convert to dict suitable for Supabase insertion."""
        d = {
            "tournament_id": tournament_id,
            "scan_type": scan_type,
            "market_type": self.market_type,
            "player_name": self.player_name,
            "dg_prob": self.dg_prob,
            "book_consensus_prob": self.book_consensus_prob,
            "your_prob": self.your_prob,
            "best_book": self.best_book,
            "best_odds_decimal": self.best_odds_decimal,
            "best_odds_american": self.best_odds_american,
            "best_implied_prob": self.best_implied_prob,
            "raw_edge": self.raw_edge,
            "deadheat_adj": self.deadheat_adj,
            "edge": self.edge,
            "kelly_fraction": self.kelly_fraction,
            "correlation_haircut": self.correlation_haircut,
            "suggested_stake": self.suggested_stake,
            "all_book_odds": self.all_book_odds,
            "status": "pending",
        }
        if self.player_id:
            d["player_id"] = self.player_id
        if self.opponent_name:
            d["opponent_name"] = self.opponent_name
        if self.opponent_id:
            d["opponent_id"] = self.opponent_id
        if self.opponent_2_name:
            d["opponent_2_name"] = self.opponent_2_name
        if self.opponent_2_id:
            d["opponent_2_id"] = self.opponent_2_id
        if self.round_number is not None:
            d["round_number"] = self.round_number
        return d


def calculate_placement_edges(
    outrights_data: dict,
    market_type: str,
    is_signature: bool = False,
    bankroll: float = 1000.0,
    existing_bets: list[dict] | None = None,
    exchange_only: bool = False,
) -> list[CandidateBet]:
    """Calculate +EV placement edges from outright odds data.

    Args:
        outrights_data: Response from DG /betting-tools/outrights endpoint.
            Contains DG model odds + book odds for each player.
        market_type: "win", "t5", "t10", "t20", "make_cut"
        is_signature: True for $20M+ events
        bankroll: current bankroll for Kelly sizing
        existing_bets: list of existing bets (for correlation haircut)
        exchange_only: If True, only consider public exchanges (not sportsbooks)
            for best-book selection. Sportsbook odds still contribute to
            book consensus but cannot be the bettable line. Use during live
            periods when sportsbook outright boards are stale.

    Returns:
        List of CandidateBet sorted by edge descending
    """
    existing_bets = existing_bets or []
    min_edge = config.MIN_EDGE.get(market_type, 0.03)
    candidates = []

    # The outrights endpoint returns a list of player records
    # Each record has DG odds and book odds columns
    if not isinstance(outrights_data, list):
        return []

    # Step 1: Identify book columns in the data
    # Live API format: each player has book names as direct keys
    # (e.g., "draftkings": "-370", "fanduel": "-350")
    # DG odds are nested: "datagolf": {"baseline": ..., "baseline_history_fit": ...}
    SKIP_KEYS = {"player_name", "dg_id", "datagolf", "dk_salary", "dk_ownership",
                 "early_late", "tee_time", "r1_teetime", "event_name"}
    books_in_data = set()
    for player in outrights_data:
        for key in player.keys():
            if key in SKIP_KEYS:
                continue
            val = player[key]
            # Book odds are strings like "-370" or "+250"
            if isinstance(val, str) and (val.startswith("+") or val.startswith("-")):
                books_in_data.add(key)

    # In exchange-only mode, restrict to public exchanges for both consensus
    # and best-book selection.  Sportsbook outright odds go stale during live
    # play and would pollute the blended probability.
    if exchange_only:
        books_in_data = books_in_data & config.EXCHANGE_BOOKS

    # Step 2: De-vig each book's full field
    book_devigged = {}
    for book in books_in_data:
        raw_probs = []
        for player in outrights_data:
            odds_str = str(player.get(book, ""))
            p = parse_american_odds(odds_str)
            raw_probs.append(p)

        valid_count = sum(1 for p in raw_probs if p is not None and p > 0)
        if valid_count >= 10:
            if market_type == "win":
                devigged = power_devig(raw_probs)
            else:
                # Placement markets: use independent de-vig
                expected = {"t5": 5, "t10": 10, "t20": 20,
                            "make_cut": 65}.get(market_type, 20)
                devigged = devig_independent(raw_probs, expected, len(raw_probs))
            book_devigged[book] = devigged

    # Step 3: For each player, compute blended probability and find edges
    for i, player in enumerate(outrights_data):
        player_name = player.get("player_name", "").strip().strip('"')
        dg_id = str(player.get("dg_id", ""))
        field_rank = i + 1  # Use position in DG's sorted list as proxy for rank

        # DG probability — handle nested format
        dg_data = player.get("datagolf", {})
        if isinstance(dg_data, dict):
            # Prefer baseline_history_fit, fall back to baseline
            dg_odds_str = str(dg_data.get("baseline_history_fit") or
                              dg_data.get("baseline") or "")
        else:
            dg_odds_str = str(dg_data or "")
        dg_prob = parse_american_odds(dg_odds_str)
        if dg_prob is None or dg_prob <= 0:
            continue

        # Book consensus
        player_book_probs = {}
        for book, devigged_list in book_devigged.items():
            if i < len(devigged_list) and devigged_list[i] is not None:
                player_book_probs[book] = devigged_list[i]

        book_consensus = build_book_consensus(player_book_probs, market_type)

        # Blended probability
        your_prob = blend_probabilities(
            dg_prob, book_consensus, market_type,
            is_signature=is_signature,
            player_field_rank=int(field_rank) if field_rank else None,
        )
        if your_prob is None or your_prob <= 0:
            continue

        # Find the best book by adjusted edge (per-book dead-heat adjustment)
        best_adjusted_edge = -1
        best_book = ""
        best_book_prob = 0
        best_decimal = 0
        best_raw_edge = 0
        best_dh_adj = 0.0
        all_odds = {}

        for book, devigged_list in book_devigged.items():
            if i >= len(devigged_list) or devigged_list[i] is None:
                continue
            book_prob = devigged_list[i]
            if book_prob <= 0 or book_prob >= 1:
                continue

            raw_edge = your_prob - book_prob

            # For prediction markets with ask-based pricing, use the
            # _{book}_ask_prob value for bettable decimal (actual cost).
            # This covers kalshi, polymarket, prophetx, and any future market.
            ask_key = f"_{book}_ask_prob"
            ask_val = player.get(ask_key)
            if (ask_val is not None
                    and isinstance(ask_val, (int, float))
                    and not isinstance(ask_val, bool)
                    and 0 < float(ask_val) < 1):
                bettable_decimal = binary_price_to_decimal(str(ask_val))
                all_odds[book] = bettable_decimal
            else:
                if ask_val is not None:
                    logger.warning(
                        "Invalid %s value %r for %s, using standard pricing",
                        ask_key, ask_val, player.get("player_name", "unknown"))
                bettable_decimal = implied_prob_to_decimal(book_prob)
                all_odds[book] = american_to_decimal(str(player.get(book, "")))

            # Per-book dead-heat adjustment: binary contract markets
            # pay full value on ties, so no DH reduction needed
            if book in config.NO_DEADHEAT_BOOKS:
                adj_edge = raw_edge
                dh_adj = 0.0
            else:
                adj_edge, dh_adj = adjust_edge_for_deadheat(
                    raw_edge, market_type, bettable_decimal)

            if adj_edge > best_adjusted_edge:
                best_adjusted_edge = adj_edge
                best_book = book
                best_book_prob = book_prob
                best_decimal = bettable_decimal
                best_raw_edge = raw_edge
                best_dh_adj = dh_adj

        if best_adjusted_edge <= 0 or best_decimal is None:
            continue

        if best_adjusted_edge < min_edge:
            continue

        # Correlation haircut
        haircut = get_correlation_haircut(player_name, existing_bets)

        # Kelly sizing
        stake = kelly_stake(
            best_adjusted_edge, best_decimal, bankroll,
            correlation_haircut=haircut,
        )

        if stake < 1:
            continue

        candidates.append(CandidateBet(
            market_type=market_type,
            player_name=player_name,
            player_dg_id=dg_id,
            dg_prob=round(dg_prob, 4),
            book_consensus_prob=round(book_consensus, 4) if book_consensus else None,
            your_prob=round(your_prob, 4),
            best_book=best_book,
            best_odds_decimal=round(best_decimal, 4),
            best_odds_american=decimal_to_american(best_decimal),
            best_implied_prob=round(best_book_prob, 4),
            raw_edge=round(best_raw_edge, 4),
            deadheat_adj=round(best_dh_adj, 4),
            edge=round(best_adjusted_edge, 4),
            kelly_fraction=round(best_adjusted_edge / (best_decimal - 1), 4)
                if best_decimal > 1 else None,
            correlation_haircut=haircut,
            suggested_stake=stake,
            all_book_odds=all_odds if all_odds else None,
        ))

    # Sort by edge descending
    candidates.sort(key=lambda c: c.edge, reverse=True)
    return candidates


def calculate_matchup_edges(
    matchups_data: list[dict],
    is_signature: bool = False,
    bankroll: float = 1000.0,
    existing_bets: list[dict] | None = None,
    market_type: str = "tournament_matchup",
) -> list[CandidateBet]:
    """Calculate +EV edges from matchup odds data.

    Args:
        matchups_data: List of matchup records from DG /betting-tools/matchups.
            Each record has odds from DG + multiple books for a pair of players.
        is_signature: True for $20M+ events
        bankroll: current bankroll
        existing_bets: for correlation haircut
        market_type: "tournament_matchup" or "round_matchup"

    Returns:
        List of CandidateBet sorted by edge descending
    """
    existing_bets = existing_bets or []
    min_edge = config.MIN_EDGE.get(market_type, 0.05)
    candidates = []

    # Get blend weights for matchups
    blend_weights = config.BLEND_WEIGHTS.get("matchup", {"dg": 1.0, "books": 0.0})

    for matchup in matchups_data:
        odds_dict = matchup.get("odds", {})
        p1_name = matchup.get("p1_player_name", "")
        p2_name = matchup.get("p2_player_name", "")
        p1_dg_id = str(matchup.get("p1_dg_id", ""))
        p2_dg_id = str(matchup.get("p2_dg_id", ""))

        # DG model probability
        dg_odds = odds_dict.get("datagolf", {})
        dg_p1_str = str(dg_odds.get("p1", ""))
        dg_p2_str = str(dg_odds.get("p2", ""))
        dg_p1_raw = parse_american_odds(dg_p1_str)
        dg_p2_raw = parse_american_odds(dg_p2_str)

        if dg_p1_raw is None or dg_p2_raw is None:
            continue

        dg_p1, dg_p2 = devig_two_way(dg_p1_raw, dg_p2_raw)
        if dg_p1 is None or dg_p1 <= 0 or dg_p1 >= 1:
            continue

        # Book odds
        all_book_odds = {}
        for book_name, book_odds in odds_dict.items():
            if book_name == "datagolf":
                continue

            bp1_raw = parse_american_odds(str(book_odds.get("p1", "")))
            bp2_raw = parse_american_odds(str(book_odds.get("p2", "")))

            if bp1_raw is None or bp2_raw is None:
                continue

            bp1_fair, bp2_fair = devig_two_way(bp1_raw, bp2_raw)
            if bp1_fair is None:
                continue

            # Store the actual offered odds (not de-vigged) for betting
            p1_decimal = american_to_decimal(str(book_odds.get("p1", "")))
            p2_decimal = american_to_decimal(str(book_odds.get("p2", "")))

            all_book_odds[book_name] = {
                "p1_fair": bp1_fair,
                "p2_fair": bp2_fair,
                "p1_decimal": p1_decimal,
                "p2_decimal": p2_decimal,
            }

        if not all_book_odds:
            continue

        # Book consensus for blending (exclude Kalshi — prediction market,
        # not a sportsbook; included for edge evaluation only)
        book_p1_probs = {b: d["p1_fair"] for b, d in all_book_odds.items()
                         if b != "kalshi"}
        if not book_p1_probs:
            continue
        book_consensus_p1 = sum(book_p1_probs.values()) / len(book_p1_probs)

        # Blend
        your_p1 = blend_weights["dg"] * dg_p1 + blend_weights["books"] * book_consensus_p1
        your_p2 = 1 - your_p1

        # Check both sides for edges
        for side, (your_prob, player_name, player_id, opp_name, opp_id, prob_key, odds_key) in [
            ("p1", (your_p1, p1_name, p1_dg_id, p2_name, p2_dg_id, "p1_fair", "p1_decimal")),
            ("p2", (your_p2, p2_name, p2_dg_id, p1_name, p1_dg_id, "p2_fair", "p2_decimal")),
        ]:
            best_edge = -1
            best_book = ""
            best_book_prob = 0
            best_decimal = 0

            for book_name, book_data in all_book_odds.items():
                book_prob = book_data[prob_key]
                decimal_odds = book_data[odds_key]

                if book_prob is None or book_prob <= 0 or decimal_odds is None:
                    continue

                edge = your_prob - book_prob
                if edge > best_edge:
                    best_edge = edge
                    best_book = book_name
                    best_book_prob = book_prob
                    best_decimal = decimal_odds

            if best_edge < min_edge or best_decimal is None or best_decimal <= 1:
                continue

            haircut = get_correlation_haircut(player_name, existing_bets)
            stake = kelly_stake(best_edge, best_decimal, bankroll,
                                correlation_haircut=haircut)

            if stake < 1:
                continue

            display_odds = {b: d.get(odds_key) for b, d in all_book_odds.items()}

            candidates.append(CandidateBet(
                market_type=market_type,
                player_name=player_name,
                player_dg_id=player_id,
                opponent_name=opp_name,
                opponent_dg_id=opp_id,
                dg_prob=round(dg_p1 if side == "p1" else dg_p2, 4),
                book_consensus_prob=round(
                    book_consensus_p1 if side == "p1" else 1 - book_consensus_p1, 4),
                your_prob=round(your_prob, 4),
                best_book=best_book,
                best_odds_decimal=round(best_decimal, 4),
                best_odds_american=decimal_to_american(best_decimal),
                best_implied_prob=round(best_book_prob, 4),
                raw_edge=round(best_edge, 4),
                deadheat_adj=0.0,
                edge=round(best_edge, 4),
                kelly_fraction=round(best_edge / (best_decimal - 1), 4)
                    if best_decimal > 1 else None,
                correlation_haircut=haircut,
                suggested_stake=stake,
                all_book_odds=display_odds,
            ))

    candidates.sort(key=lambda c: c.edge, reverse=True)
    return candidates


def calculate_3ball_edges(
    three_ball_data: list[dict],
    bankroll: float = 1000.0,
    existing_bets: list[dict] | None = None,
    round_number: int | None = None,
) -> list[CandidateBet]:
    """Calculate +EV edges from 3-ball odds data.

    Args:
        three_ball_data: List of 3-ball records from DG /betting-tools/matchups
            with market=3_balls. Each has DG + book odds for 3 players.
        bankroll: current bankroll
        existing_bets: for correlation haircut
        round_number: which round (1-4)

    Returns:
        List of CandidateBet sorted by edge descending
    """
    existing_bets = existing_bets or []
    min_edge = config.MIN_EDGE.get("3_ball", 0.05)
    candidates = []

    for group in three_ball_data:
        odds_dict = group.get("odds", {})
        players = []
        for p_key in ["p1", "p2", "p3"]:
            players.append({
                "key": p_key,
                "name": group.get(f"{p_key}_player_name", ""),
                "dg_id": str(group.get(f"{p_key}_dg_id", "")),
            })

        # DG probabilities
        dg_odds = odds_dict.get("datagolf", {})
        dg_raws = []
        for p in players:
            raw = parse_american_odds(str(dg_odds.get(p["key"], "")))
            dg_raws.append(raw)

        if any(r is None for r in dg_raws):
            continue

        dg_fair = devig_three_way(*dg_raws)
        if any(f is None or f <= 0 for f in dg_fair):
            continue

        # Book odds
        all_book_data = {}
        for book_name, book_odds in odds_dict.items():
            if book_name == "datagolf":
                continue

            b_raws = []
            for p in players:
                raw = parse_american_odds(str(book_odds.get(p["key"], "")))
                b_raws.append(raw)

            if any(r is None for r in b_raws):
                continue

            b_fair = devig_three_way(*b_raws)
            if any(f is None for f in b_fair):
                continue

            decimals = []
            for p in players:
                d = american_to_decimal(str(book_odds.get(p["key"], "")))
                decimals.append(d)

            all_book_data[book_name] = {
                "fair": b_fair,
                "decimal": decimals,
            }

        if not all_book_data:
            continue

        # Check each player for an edge
        for idx, player in enumerate(players):
            dg_prob = dg_fair[idx]

            # Book consensus for this player
            book_probs = [d["fair"][idx] for d in all_book_data.values()]
            book_consensus = sum(book_probs) / len(book_probs)

            # Blend (100% DG for now)
            your_prob = config.BLEND_WEIGHTS["three_ball"]["dg"] * dg_prob + \
                        config.BLEND_WEIGHTS["three_ball"]["books"] * book_consensus

            # Find best edge
            best_edge = -1
            best_book = ""
            best_book_prob = 0
            best_decimal = 0

            for book_name, book_data in all_book_data.items():
                bp = book_data["fair"][idx]
                dec = book_data["decimal"][idx]
                if bp is None or bp <= 0 or dec is None or dec <= 1:
                    continue

                edge = your_prob - bp
                if edge > best_edge:
                    best_edge = edge
                    best_book = book_name
                    best_book_prob = bp
                    best_decimal = dec

            if best_edge < min_edge:
                continue

            # Other two players are opponents
            opps = [p for j, p in enumerate(players) if j != idx]

            haircut = get_correlation_haircut(player["name"], existing_bets)
            stake = kelly_stake(best_edge, best_decimal, bankroll,
                                correlation_haircut=haircut)

            if stake < 1:
                continue

            display_odds = {b: d["decimal"][idx] for b, d in all_book_data.items()}

            candidates.append(CandidateBet(
                market_type="3_ball",
                player_name=player["name"],
                player_dg_id=player["dg_id"],
                opponent_name=opps[0]["name"],
                opponent_dg_id=opps[0]["dg_id"],
                opponent_2_name=opps[1]["name"],
                opponent_2_dg_id=opps[1]["dg_id"],
                round_number=round_number,
                dg_prob=round(dg_prob, 4),
                book_consensus_prob=round(book_consensus, 4),
                your_prob=round(your_prob, 4),
                best_book=best_book,
                best_odds_decimal=round(best_decimal, 4),
                best_odds_american=decimal_to_american(best_decimal),
                best_implied_prob=round(best_book_prob, 4),
                raw_edge=round(best_edge, 4),
                deadheat_adj=0.0,
                edge=round(best_edge, 4),
                kelly_fraction=round(best_edge / (best_decimal - 1), 4)
                    if best_decimal > 1 else None,
                correlation_haircut=haircut,
                suggested_stake=stake,
                all_book_odds=display_odds,
            ))

    candidates.sort(key=lambda c: c.edge, reverse=True)
    return candidates
