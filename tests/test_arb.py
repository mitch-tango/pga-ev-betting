"""Unit tests for arbitrage helpers."""

from __future__ import annotations

from src.core.arb import (
    ArbLeg,
    ArbOpportunity,
    arb_legs_to_candidates,
)
from src.core.edge import CandidateBet
import config


def _make_arb_2leg() -> ArbOpportunity:
    return ArbOpportunity(
        market_type="round_matchup",
        legs=[
            ArbLeg(player="Scheffler, Scottie", book="fanduel",
                   odds_decimal=2.10, implied_prob=1 / 2.10),
            ArbLeg(player="Rahm, Jon", book="draftkings",
                   odds_decimal=2.05, implied_prob=1 / 2.05),
        ],
        combined_implied=round(1 / 2.10 + 1 / 2.05, 6),
        margin=round(1.0 - (1 / 2.10 + 1 / 2.05), 6),
        round_number=2,
    )


def _make_arb_3ball() -> ArbOpportunity:
    return ArbOpportunity(
        market_type="3_ball",
        legs=[
            ArbLeg(player="McIlroy, Rory", book="caesars",
                   odds_decimal=3.20, implied_prob=1 / 3.20),
            ArbLeg(player="Morikawa, Collin", book="betmgm",
                   odds_decimal=3.50, implied_prob=1 / 3.50),
            ArbLeg(player="Cantlay, Patrick", book="fanduel",
                   odds_decimal=3.80, implied_prob=1 / 3.80),
        ],
        combined_implied=round(1 / 3.20 + 1 / 3.50 + 1 / 3.80, 6),
        margin=round(1.0 - (1 / 3.20 + 1 / 3.50 + 1 / 3.80), 6),
        round_number=3,
        settlement_warning="tie: caesars=dead_heat vs betmgm=full_pay",
    )


def test_arb_legs_to_candidates_empty():
    assert arb_legs_to_candidates([]) == []


def test_arb_legs_to_candidates_2leg_fields():
    arb = _make_arb_2leg()
    cands = arb_legs_to_candidates([arb])

    assert len(cands) == 2
    p1, p2 = cands

    assert p1.player_name == "Scheffler, Scottie"
    assert p1.opponent_name == "Rahm, Jon"
    assert p1.opponent_2_name is None
    assert p1.market_type == "round_matchup"
    assert p1.round_number == 2
    assert p1.best_book == "fanduel"
    assert p1.best_odds_decimal == 2.10
    assert p1.qualifies is True
    assert p1.edge == arb.margin
    assert p1.your_prob == p1.best_implied_prob  # no fake "my prob"
    assert p1.kelly_fraction is None

    # Stake was populated by size_arb() during the helper call
    assert p1.suggested_stake > 0
    assert p2.suggested_stake > 0

    # Symmetric opponent wiring — each leg names the other as opponent,
    # keeping the persist_candidates dedupe key unique within the batch.
    assert p2.player_name == "Rahm, Jon"
    assert p2.opponent_name == "Scheffler, Scottie"


def test_arb_legs_to_candidates_3ball_opponents():
    arb = _make_arb_3ball()
    cands = arb_legs_to_candidates([arb])

    assert len(cands) == 3
    players = [c.player_name for c in cands]
    assert players == [
        "McIlroy, Rory", "Morikawa, Collin", "Cantlay, Patrick"
    ]

    # Leg 0: opponents are legs 1 and 2
    assert cands[0].opponent_name == "Morikawa, Collin"
    assert cands[0].opponent_2_name == "Cantlay, Patrick"
    # Leg 1: opponents are legs 0 and 2
    assert cands[1].opponent_name == "McIlroy, Rory"
    assert cands[1].opponent_2_name == "Cantlay, Patrick"
    # Leg 2: opponents are legs 0 and 1
    assert cands[2].opponent_name == "McIlroy, Rory"
    assert cands[2].opponent_2_name == "Morikawa, Collin"

    # All legs share the same market + round
    for c in cands:
        assert c.market_type == "3_ball"
        assert c.round_number == 3


def test_arb_legs_to_candidates_preserves_metadata_in_all_book_odds():
    arb = _make_arb_3ball()
    cands = arb_legs_to_candidates([arb])

    for idx, c in enumerate(cands):
        meta = c.all_book_odds
        assert isinstance(meta, dict)
        assert meta["arb_margin"] == arb.margin
        assert meta["arb_settlement_warning"] == arb.settlement_warning
        assert meta["arb_leg_index"] == idx
        assert len(meta["arb_legs"]) == 3
        # Sibling metadata lets /place reconstruct the full opportunity
        for sib in meta["arb_legs"]:
            assert set(sib.keys()) == {
                "player", "book", "odds_decimal", "stake",
            }
            assert sib["stake"] > 0


def test_arb_legs_to_candidates_dedupe_key_uniqueness():
    """persist_candidates dedupes batches by (player, market, opp, opp2, round).
    Within a single arb, each leg must have a unique key so no leg gets
    dropped on insert.
    """
    arb = _make_arb_3ball()
    cands = arb_legs_to_candidates([arb])
    keys = {
        (c.player_name, c.market_type,
         c.opponent_name or "", c.opponent_2_name or "",
         c.round_number)
        for c in cands
    }
    assert len(keys) == len(cands)


def test_arb_legs_to_candidates_sizes_using_config_default():
    """Stakes should match `total_return / odds_decimal` (rounded), so
    the candidate's suggested_stake matches what the scan embed displays.
    """
    arb = _make_arb_2leg()
    cands = arb_legs_to_candidates([arb])
    ret = config.ARB_DEFAULT_RETURN
    assert cands[0].suggested_stake == round(ret / 2.10, 2)
    assert cands[1].suggested_stake == round(ret / 2.05, 2)


def test_arb_legs_to_candidates_custom_total_return():
    arb = _make_arb_2leg()
    cands = arb_legs_to_candidates([arb], total_return=500.0)
    assert cands[0].suggested_stake == round(500.0 / 2.10, 2)
    assert cands[1].suggested_stake == round(500.0 / 2.05, 2)


def test_arb_legs_are_candidatebet_instances():
    arb = _make_arb_2leg()
    cands = arb_legs_to_candidates([arb])
    assert all(isinstance(c, CandidateBet) for c in cands)
