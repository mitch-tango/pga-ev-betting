"""Direct edge computation for NoVig screenshot-extracted lines.

MVP scope (see roadmap: NoVig screenshot ingestion — MVP):
- Takes NovigOutrightLine / NovigMatchupLine from novig_vision
- Matches players against a fresh DG pull by name
- Computes edge directly vs DG model (raw `baseline_history_fit` probs)
- Emits display-only CandidateBet rows (not persisted to `candidate_bets`)
- Supports both Yes and No sides on outrights

Why direct-edge and not `calculate_placement_edges`?
- NoVig is the sole book in play here, so the standard DG+books blend
  would collapse to "compare NoVig to DG" anyway.
- No side isn't supported by the existing placement edge path (would
  require DB schema + settlement changes). Direct computation sidesteps
  that until v2 persistence work is prioritized.
- Correlation haircut / course-fit / expert-picks are deferred to v2;
  the MVP is a decision-support read, not a full Kelly-sized candidate.

Name matching reuses `_names_match` from `src.parsers.start_merger`
which already solves "First Last" (NoVig) vs "Last, First" (DG).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import config
from src.core.devig import american_to_decimal, parse_american_odds
from src.core.edge import CandidateBet
from src.core.kelly import kelly_stake
from src.parsers.start_merger import _names_match, _normalize_for_match
from src.core.novig_vision import NovigMatchupLine, NovigOutrightLine

logger = logging.getLogger(__name__)


@dataclass
class NovigMissingPlayer:
    """A NoVig line that didn't match any DG record.

    Reported back to the user so they can spot extraction errors
    (wrong spelling, Claude misread a name) vs genuine roster misses
    (LIV player not in the DG field).
    """
    source: str            # "outright:t20" | "matchup:round_matchup" etc.
    player_name: str
    nearest_match: str | None = None


# ── Outrights ─────────────────────────────────────────────────────────


def _find_dg_player(
    novig_name: str,
    dg_records: list[dict],
) -> dict | None:
    """Find the DG outrights record for a NoVig-formatted player name."""
    for rec in dg_records:
        dg_name = rec.get("player_name", "")
        if not dg_name:
            continue
        if _names_match(novig_name, dg_name):
            return rec
    return None


def _extract_dg_prob(player_record: dict) -> float | None:
    """Pull the DG baseline probability out of a DG outright record.

    DG uses American-odds strings under the `datagolf` key; the edge
    pipeline elsewhere also keys off `baseline_history_fit`, falling
    back to `baseline`.
    """
    dg_data = player_record.get("datagolf", {})
    if not isinstance(dg_data, dict):
        return None
    odds_str = str(
        dg_data.get("baseline_history_fit")
        or dg_data.get("baseline")
        or ""
    )
    if not odds_str:
        return None
    return parse_american_odds(odds_str)


def _compute_outright_candidate(
    line: NovigOutrightLine,
    side: str,               # "yes" | "no"
    dg_player: dict,
    dg_prob: float,
    bankroll: float,
) -> CandidateBet | None:
    """Build a display CandidateBet for one side of a NoVig outright line.

    For side="yes": your_prob = DG prob, odds = yes_odds.
    For side="no":  your_prob = 1 - DG prob, odds = no_odds.
    """
    odds_str = (
        line.yes_odds_american if side == "yes"
        else line.no_odds_american
    )
    if not odds_str:
        return None

    decimal_odds = american_to_decimal(odds_str)
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    implied = 1.0 / decimal_odds

    your_prob = dg_prob if side == "yes" else max(0.0, 1.0 - dg_prob)
    edge = your_prob - implied
    if your_prob <= 0 or your_prob >= 1:
        return None

    bet_min_edge = config.MIN_EDGE.get(line.market_type, 0.03)
    qualifies = edge >= bet_min_edge

    suggested_stake = 0.0
    kelly_fraction = None
    if qualifies:
        suggested_stake = kelly_stake(
            edge=edge,
            decimal_odds=decimal_odds,
            bankroll=bankroll,
        )
        # Store the fraction of bankroll for display symmetry with the
        # main pipeline.
        kelly_fraction = suggested_stake / bankroll if bankroll > 0 else None

    # Encode side in the display market_type so `_render_candidates_image`
    # shows it clearly without needing a schema field. "t20" -> "t20" for
    # Yes, "t20 NO" for No.
    display_market = (
        line.market_type if side == "yes"
        else f"{line.market_type} NO"
    )

    return CandidateBet(
        market_type=display_market,
        player_name=dg_player.get("player_name", line.player_name),
        player_dg_id=str(dg_player.get("dg_id", "")) or None,
        dg_prob=dg_prob,
        your_prob=your_prob,
        best_book="novig",
        best_odds_decimal=decimal_odds,
        best_odds_american=odds_str,
        best_implied_prob=implied,
        raw_edge=edge,
        edge=edge,
        kelly_fraction=kelly_fraction,
        correlation_haircut=1.0,
        suggested_stake=round(suggested_stake, 2),
        bet_min_edge=bet_min_edge,
        qualifies=qualifies,
    )


# ── Matchups ──────────────────────────────────────────────────────────


def _find_dg_matchup(
    p1_novig: str,
    p2_novig: str,
    dg_matchups: list[dict],
) -> tuple[dict, str] | None:
    """Locate the DG matchup record that contains both NoVig players.

    Returns (matchup_record, orientation) where orientation is "p1p2"
    if NoVig p1 matches DG p1, "p2p1" if swapped, else None.
    """
    for m in dg_matchups:
        dg_p1 = m.get("p1_player_name", "")
        dg_p2 = m.get("p2_player_name", "")
        if _names_match(p1_novig, dg_p1) and _names_match(p2_novig, dg_p2):
            return m, "p1p2"
        if _names_match(p1_novig, dg_p2) and _names_match(p2_novig, dg_p1):
            return m, "p2p1"
    return None


def _extract_dg_matchup_prob(
    matchup: dict,
    orientation: str,
) -> tuple[float | None, float | None]:
    """Pull p1/p2 DG-model probabilities out of a DG matchup record.

    DG matchup records carry the model's own p1/p2 price under
    odds.datagolf as American-odds strings. We convert to implied
    probabilities and renormalize so the pair sums to 1 (since the
    DG price already excludes vig, this is usually a no-op).
    """
    dg_odds = matchup.get("odds", {}).get("datagolf", {})
    if not isinstance(dg_odds, dict):
        return None, None
    p1_str = str(dg_odds.get("p1") or "")
    p2_str = str(dg_odds.get("p2") or "")
    p1_prob = parse_american_odds(p1_str) if p1_str else None
    p2_prob = parse_american_odds(p2_str) if p2_str else None
    if p1_prob is None or p2_prob is None:
        return None, None

    total = p1_prob + p2_prob
    if total > 0:
        p1_prob /= total
        p2_prob /= total

    if orientation == "p2p1":
        # Matchup was found with players swapped relative to NoVig's
        # display order — return DG probs aligned to NoVig's p1/p2.
        return p2_prob, p1_prob
    return p1_prob, p2_prob


def _compute_matchup_candidate(
    player_name: str,
    player_name_dg: str,
    opponent_name_dg: str,
    odds_str: str,
    your_prob: float,
    market_type: str,
    round_number: int | None,
    bankroll: float,
) -> CandidateBet | None:
    decimal_odds = american_to_decimal(odds_str)
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    implied = 1.0 / decimal_odds
    edge = your_prob - implied

    bet_min_edge = config.MIN_EDGE.get(market_type, 0.03)
    qualifies = edge >= bet_min_edge

    suggested_stake = 0.0
    kelly_fraction = None
    if qualifies:
        suggested_stake = kelly_stake(
            edge=edge,
            decimal_odds=decimal_odds,
            bankroll=bankroll,
        )
        kelly_fraction = suggested_stake / bankroll if bankroll > 0 else None

    return CandidateBet(
        market_type=market_type,
        player_name=player_name_dg,
        opponent_name=opponent_name_dg,
        round_number=round_number,
        dg_prob=your_prob,
        your_prob=your_prob,
        best_book="novig",
        best_odds_decimal=decimal_odds,
        best_odds_american=odds_str,
        best_implied_prob=implied,
        raw_edge=edge,
        edge=edge,
        kelly_fraction=kelly_fraction,
        correlation_haircut=1.0,
        suggested_stake=round(suggested_stake, 2),
        bet_min_edge=bet_min_edge,
        qualifies=qualifies,
    )


# ── Top-level orchestration ──────────────────────────────────────────


def evaluate_novig_lines(
    outright_lines: list[NovigOutrightLine],
    matchup_lines: list[NovigMatchupLine],
    dg_outrights: dict,        # {"win": [...], "top_10": [...], ...}
    dg_matchups: list[dict],   # tournament or round matchup list
    dg_round_matchups: list[dict] | None = None,
    bankroll: float = 1000.0,
) -> tuple[list[CandidateBet], list[NovigMissingPlayer]]:
    """Evaluate a batch of extracted NoVig lines against DG model probs.

    Returns (candidates, missing). Candidates are sorted by edge
    descending; `missing` lists lines where the player couldn't be
    matched to any DG record so the user can spot extraction errors.

    `dg_outrights` is the same dict shape pulled by
    `src.pipeline.pull_outrights.pull_all_outrights`. `dg_matchups` is
    tournament-long matchups; `dg_round_matchups` is per-round
    matchups (if the user captured a round screen). Either or both
    can be empty.
    """
    candidates: list[CandidateBet] = []
    missing: list[NovigMissingPlayer] = []

    # --- Outrights ---
    # Map our internal market_type back to DG's outrights key
    internal_to_dg_key = {
        "win": "win",
        "t5": "top_5",
        "t10": "top_10",
        "t20": "top_20",
        "make_cut": "make_cut",
    }

    for line in outright_lines:
        dg_key = internal_to_dg_key.get(line.market_type)
        dg_records = dg_outrights.get(dg_key) if dg_key else None
        if not isinstance(dg_records, list) or not dg_records:
            missing.append(NovigMissingPlayer(
                source=f"outright:{line.market_type}",
                player_name=line.player_name,
                nearest_match=None,
            ))
            continue

        dg_player = _find_dg_player(line.player_name, dg_records)
        if not dg_player:
            missing.append(NovigMissingPlayer(
                source=f"outright:{line.market_type}",
                player_name=line.player_name,
            ))
            continue

        dg_prob = _extract_dg_prob(dg_player)
        if dg_prob is None:
            logger.info("No DG baseline prob for %s", line.player_name)
            continue

        for side in ("yes", "no"):
            cand = _compute_outright_candidate(
                line=line, side=side,
                dg_player=dg_player, dg_prob=dg_prob,
                bankroll=bankroll,
            )
            if cand is not None:
                candidates.append(cand)

    # --- Matchups ---
    for line in matchup_lines:
        dg_list = (
            dg_round_matchups
            if line.market_type == "round_matchup"
            else dg_matchups
        ) or []
        found = _find_dg_matchup(
            line.player1_name, line.player2_name, dg_list,
        )
        if found is None:
            missing.append(NovigMissingPlayer(
                source=f"matchup:{line.market_type}",
                player_name=f"{line.player1_name} vs {line.player2_name}",
            ))
            continue
        matchup_rec, orientation = found
        p1_prob, p2_prob = _extract_dg_matchup_prob(matchup_rec, orientation)
        if p1_prob is None or p2_prob is None:
            continue

        dg_p1_name = matchup_rec.get("p1_player_name", line.player1_name)
        dg_p2_name = matchup_rec.get("p2_player_name", line.player2_name)

        if orientation == "p2p1":
            dg_p1_name, dg_p2_name = dg_p2_name, dg_p1_name

        # Player 1 side
        c1 = _compute_matchup_candidate(
            player_name=line.player1_name,
            player_name_dg=dg_p1_name,
            opponent_name_dg=dg_p2_name,
            odds_str=line.player1_odds_american,
            your_prob=p1_prob,
            market_type=line.market_type,
            round_number=line.round_number,
            bankroll=bankroll,
        )
        if c1 is not None:
            candidates.append(c1)

        # Player 2 side
        c2 = _compute_matchup_candidate(
            player_name=line.player2_name,
            player_name_dg=dg_p2_name,
            opponent_name_dg=dg_p1_name,
            odds_str=line.player2_odds_american,
            your_prob=p2_prob,
            market_type=line.market_type,
            round_number=line.round_number,
            bankroll=bankroll,
        )
        if c2 is not None:
            candidates.append(c2)

    candidates.sort(key=lambda c: c.edge, reverse=True)
    return candidates, missing
