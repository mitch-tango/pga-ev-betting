"""Tests for closing-odds snapshot builders.

Focus is the tournament_matchup branch added to support CLV for
tournament-long H2H bets, but the round_matchup branch is also
covered here so the builder has regression coverage.
"""

from __future__ import annotations

from src.pipeline.pull_closing import build_closing_matchup_snapshots


def _round_matchup() -> dict:
    return {
        "p1_player_name": "Scheffler, Scottie",
        "p2_player_name": "Rahm, Jon",
        "p1_dg_id": 1001,
        "p2_dg_id": 1002,
        "odds": {
            "datagolf": {"p1": "-130", "p2": "+110"},
            "fanduel":  {"p1": "-125", "p2": "+105"},
            "draftkings": {"p1": "-120", "p2": "+100"},
        },
    }


def _tournament_matchup() -> dict:
    return {
        "p1_player_name": "McIlroy, Rory",
        "p2_player_name": "Morikawa, Collin",
        "p1_dg_id": 2001,
        "p2_dg_id": 2002,
        "odds": {
            "datagolf": {"p1": "-110", "p2": "-110"},
            "bovada":   {"p1": "-115", "p2": "-105"},
            "fanduel":  {"p1": "-108", "p2": "-112"},
        },
    }


def test_build_closing_matchup_snapshots_round_matchup_only():
    snaps = build_closing_matchup_snapshots(
        round_matchups=[_round_matchup()],
        three_balls=[],
        tournament_id="t-abc",
    )
    # One snapshot per side
    assert len(snaps) == 2
    assert {s["market_type"] for s in snaps} == {"round_matchup"}
    assert all(s["tournament_id"] == "t-abc" for s in snaps)


def test_build_closing_matchup_snapshots_tournament_matchup_tagging():
    snaps = build_closing_matchup_snapshots(
        round_matchups=[],
        three_balls=[],
        tournament_id="t-abc",
        tournament_matchups=[_tournament_matchup()],
    )
    assert len(snaps) == 2
    # Market type is tagged correctly so CLV matcher finds it
    assert all(s["market_type"] == "tournament_matchup" for s in snaps)

    # Each side carries the opponent name — needed for matcher keying
    # and for analytics that reconstruct pairs.
    by_player = {s["player_name"]: s for s in snaps}
    assert by_player["McIlroy, Rory"]["opponent_name"] == "Morikawa, Collin"
    assert by_player["Morikawa, Collin"]["opponent_name"] == "McIlroy, Rory"

    # Book odds are aligned to the correct side (p1 vs p2)
    mcilroy = by_player["McIlroy, Rory"]
    assert mcilroy["book_odds"]["datagolf"] == "-110"
    assert mcilroy["book_odds"]["bovada"] == "-115"
    assert mcilroy["book_odds"]["fanduel"] == "-108"

    morikawa = by_player["Morikawa, Collin"]
    assert morikawa["book_odds"]["datagolf"] == "-110"
    assert morikawa["book_odds"]["bovada"] == "-105"
    assert morikawa["book_odds"]["fanduel"] == "-112"


def test_build_closing_matchup_snapshots_mixed_round_and_tournament():
    """Round and tournament matchups can coexist in one build call
    (Thursday run captures both)."""
    snaps = build_closing_matchup_snapshots(
        round_matchups=[_round_matchup()],
        three_balls=[],
        tournament_id="t-abc",
        tournament_matchups=[_tournament_matchup()],
    )
    # 2 round + 2 tournament
    assert len(snaps) == 4
    by_type: dict[str, int] = {}
    for s in snaps:
        by_type[s["market_type"]] = by_type.get(s["market_type"], 0) + 1
    assert by_type == {"round_matchup": 2, "tournament_matchup": 2}


def test_build_closing_matchup_snapshots_empty_inputs():
    assert build_closing_matchup_snapshots(
        round_matchups=[], three_balls=[], tournament_id="t-abc",
    ) == []
    assert build_closing_matchup_snapshots(
        round_matchups=[], three_balls=[], tournament_id="t-abc",
        tournament_matchups=None,
    ) == []
    assert build_closing_matchup_snapshots(
        round_matchups=[], three_balls=[], tournament_id="t-abc",
        tournament_matchups=[],
    ) == []


def test_build_closing_matchup_snapshots_missing_player_name_skipped():
    """A matchup row with a blank player name on one side should still
    produce a snapshot for the other side."""
    bad = {
        "p1_player_name": "",   # empty
        "p2_player_name": "Rahm, Jon",
        "odds": {"fanduel": {"p1": "-125", "p2": "+105"}},
    }
    snaps = build_closing_matchup_snapshots(
        round_matchups=[],
        three_balls=[],
        tournament_id="t-abc",
        tournament_matchups=[bad],
    )
    assert len(snaps) == 1
    assert snaps[0]["player_name"] == "Rahm, Jon"
    assert snaps[0]["market_type"] == "tournament_matchup"
