"""Unit tests for NoVig edge computation.

Tests the direct-edge path used by the /novig screenshot MVP. Covers:
- Yes/No side math on outrights
- Matchup orientation handling (p1p2 vs p2p1)
- Player name matching (First Last <-> Last, First via start_merger)
- Missing-player reporting
- Qualify/sub-threshold gating
- Both-sides-none handling (unavailable NoVig cells)
"""

from __future__ import annotations

from src.core.novig_edge import (
    NovigMissingPlayer,
    _compute_outright_candidate,
    _extract_dg_prob,
    _find_dg_matchup,
    _find_dg_player,
    evaluate_novig_lines,
)
from src.core.novig_vision import NovigMatchupLine, NovigOutrightLine


# ── DG fixture builders ──────────────────────────────────────────────


def _dg_outright_record(
    player_name: str,
    dg_american: str,
    dg_id: int = 1001,
) -> dict:
    return {
        "player_name": player_name,  # "Last, First" as DG returns it
        "dg_id": dg_id,
        "datagolf": {"baseline_history_fit": dg_american},
    }


def _dg_matchup_record(
    p1: str, p2: str,
    p1_dg_odds: str, p2_dg_odds: str,
) -> dict:
    return {
        "p1_player_name": p1,
        "p2_player_name": p2,
        "p1_dg_id": 1,
        "p2_dg_id": 2,
        "odds": {
            "datagolf": {"p1": p1_dg_odds, "p2": p2_dg_odds},
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────


class TestFindDgPlayer:

    def test_matches_first_last_to_last_first(self):
        records = [
            _dg_outright_record("Scheffler, Scottie", "+100"),
            _dg_outright_record("McIlroy, Rory", "+150"),
        ]
        rec = _find_dg_player("Scottie Scheffler", records)
        assert rec is not None
        assert rec["player_name"] == "Scheffler, Scottie"

    def test_no_match_returns_none(self):
        records = [_dg_outright_record("Scheffler, Scottie", "+100")]
        assert _find_dg_player("Someone Else", records) is None


class TestExtractDgProb:

    def test_baseline_history_fit_preferred(self):
        rec = {
            "datagolf": {"baseline_history_fit": "+150", "baseline": "+200"},
        }
        p = _extract_dg_prob(rec)
        assert p is not None
        assert 0.39 < p < 0.41

    def test_fallback_to_baseline(self):
        rec = {"datagolf": {"baseline": "+100"}}
        p = _extract_dg_prob(rec)
        assert p is not None
        assert 0.49 < p < 0.51

    def test_missing_returns_none(self):
        assert _extract_dg_prob({}) is None
        assert _extract_dg_prob({"datagolf": {}}) is None


# ── Outright edge math ───────────────────────────────────────────────


class TestOutrightCandidate:

    def _line(self, yes: str | None, no: str | None, mkt: str = "t20"):
        return NovigOutrightLine(
            market_type=mkt,
            player_name="Rory McIlroy",
            yes_odds_american=yes,
            no_odds_american=no,
        )

    def _dg(self):
        return _dg_outright_record("McIlroy, Rory", "+150")

    def test_yes_side_positive_edge(self):
        # DG +150 -> ~40% prob. NoVig Yes at +200 -> ~33% implied.
        # Edge ~ +7% → well above T20 threshold.
        line = self._line(yes="+200", no="-300")
        cand = _compute_outright_candidate(
            line=line, side="yes", dg_player=self._dg(),
            dg_prob=0.40, bankroll=1000,
        )
        assert cand is not None
        assert cand.market_type == "t20"
        assert cand.best_book == "novig"
        assert cand.best_odds_american == "+200"
        assert round(cand.edge, 3) == round(0.40 - (1 / 3.0), 3)
        assert cand.qualifies is True
        assert cand.suggested_stake > 0

    def test_no_side_inverts_probability(self):
        # DG prob = 0.40 → implied "No" prob = 0.60.
        # NoVig No at +100 (decimal 2.0) → 50% implied.
        # Edge = 0.60 - 0.50 = +10%
        line = self._line(yes="-200", no="+100")
        cand = _compute_outright_candidate(
            line=line, side="no", dg_player=self._dg(),
            dg_prob=0.40, bankroll=1000,
        )
        assert cand is not None
        assert cand.market_type == "t20 NO"   # display suffix
        assert round(cand.edge, 4) == round(0.60 - 0.50, 4)
        assert cand.your_prob == 0.60
        assert cand.qualifies is True

    def test_unavailable_side_is_none(self):
        line = self._line(yes="-200", no=None)
        cand = _compute_outright_candidate(
            line=line, side="no", dg_player=self._dg(),
            dg_prob=0.40, bankroll=1000,
        )
        assert cand is None

    def test_sub_threshold_edge_info_only(self):
        # DG +150 -> 40%. Yes at -150 (decimal 1.667) -> 60% implied.
        # Edge = -20%, info-only.
        line = self._line(yes="-150", no="+130")
        cand = _compute_outright_candidate(
            line=line, side="yes", dg_player=self._dg(),
            dg_prob=0.40, bankroll=1000,
        )
        assert cand is not None
        assert cand.qualifies is False
        assert cand.suggested_stake == 0

    def test_extreme_dg_prob_rejected(self):
        """DG prob of 0 or 1 would crash Kelly — the function should
        return None rather than inventing a result."""
        line = self._line(yes="+200", no="-300")
        assert _compute_outright_candidate(
            line=line, side="yes", dg_player=self._dg(),
            dg_prob=0.0, bankroll=1000,
        ) is None
        assert _compute_outright_candidate(
            line=line, side="yes", dg_player=self._dg(),
            dg_prob=1.0, bankroll=1000,
        ) is None


# ── Matchup orientation ──────────────────────────────────────────────


class TestFindDgMatchup:

    def test_same_order_orientation(self):
        matchups = [
            _dg_matchup_record(
                "Scheffler, Scottie", "McIlroy, Rory", "-120", "+100",
            ),
        ]
        found = _find_dg_matchup(
            "Scottie Scheffler", "Rory McIlroy", matchups,
        )
        assert found is not None
        rec, orient = found
        assert orient == "p1p2"

    def test_swapped_order_orientation(self):
        matchups = [
            _dg_matchup_record(
                "Scheffler, Scottie", "McIlroy, Rory", "-120", "+100",
            ),
        ]
        found = _find_dg_matchup(
            "Rory McIlroy", "Scottie Scheffler", matchups,
        )
        assert found is not None
        _, orient = found
        assert orient == "p2p1"

    def test_not_in_matchups_returns_none(self):
        matchups = [
            _dg_matchup_record(
                "Scheffler, Scottie", "McIlroy, Rory", "-120", "+100",
            ),
        ]
        found = _find_dg_matchup("A Player", "B Player", matchups)
        assert found is None


# ── evaluate_novig_lines orchestration ───────────────────────────────


class TestEvaluateNovigLines:

    def test_outright_both_sides_produced(self):
        dg_outrights = {
            "top_20": [_dg_outright_record("McIlroy, Rory", "+150")],
        }
        lines = [NovigOutrightLine(
            market_type="t20",
            player_name="Rory McIlroy",
            yes_odds_american="+200",
            no_odds_american="-150",
        )]
        candidates, missing = evaluate_novig_lines(
            outright_lines=lines,
            matchup_lines=[],
            dg_outrights=dg_outrights,
            dg_matchups=[],
        )
        # One candidate per side
        assert len(candidates) == 2
        markets = {c.market_type for c in candidates}
        assert markets == {"t20", "t20 NO"}
        assert not missing

    def test_unmatched_player_reported(self):
        dg_outrights = {
            "top_20": [_dg_outright_record("McIlroy, Rory", "+150")],
        }
        lines = [NovigOutrightLine(
            market_type="t20",
            player_name="Nonexistent Player",
            yes_odds_american="+500", no_odds_american="-1000",
        )]
        candidates, missing = evaluate_novig_lines(
            outright_lines=lines, matchup_lines=[],
            dg_outrights=dg_outrights, dg_matchups=[],
        )
        assert candidates == []
        assert len(missing) == 1
        assert missing[0].player_name == "Nonexistent Player"
        assert "t20" in missing[0].source

    def test_missing_dg_key_reported(self):
        """If the user captures a T5 board but DG only has win/T10/T20,
        the line can't be evaluated — report as missing."""
        lines = [NovigOutrightLine(
            market_type="t5",
            player_name="Scottie Scheffler",
            yes_odds_american="+400", no_odds_american="-600",
        )]
        candidates, missing = evaluate_novig_lines(
            outright_lines=lines, matchup_lines=[],
            dg_outrights={"top_20": []},
            dg_matchups=[],
        )
        assert candidates == []
        assert len(missing) == 1
        assert "t5" in missing[0].source

    def test_matchup_produces_two_candidates(self):
        dg_matchups = [
            _dg_matchup_record(
                "Scheffler, Scottie", "McIlroy, Rory",
                "-150", "+130",
            ),
        ]
        lines = [NovigMatchupLine(
            market_type="tournament_matchup",
            player1_name="Scottie Scheffler",
            player1_odds_american="-140",
            player2_name="Rory McIlroy",
            player2_odds_american="+140",
        )]
        candidates, missing = evaluate_novig_lines(
            outright_lines=[], matchup_lines=lines,
            dg_outrights={}, dg_matchups=dg_matchups,
        )
        assert len(candidates) == 2
        # Each side sees the other as opponent
        players = {c.player_name for c in candidates}
        assert "Scheffler, Scottie" in players
        assert "McIlroy, Rory" in players
        for c in candidates:
            assert c.best_book == "novig"
            assert c.market_type == "tournament_matchup"

    def test_round_matchup_routes_to_round_matchup_list(self):
        """Round matchups go to dg_round_matchups, not dg_matchups."""
        round_list = [
            _dg_matchup_record(
                "A Player", "B Player", "-110", "-110",
            ),
        ]
        lines = [NovigMatchupLine(
            market_type="round_matchup",
            player1_name="A Player",
            player1_odds_american="-105",
            player2_name="B Player",
            player2_odds_american="-115",
            round_number=3,
        )]
        candidates, missing = evaluate_novig_lines(
            outright_lines=[], matchup_lines=lines,
            dg_outrights={}, dg_matchups=[],
            dg_round_matchups=round_list,
        )
        assert len(candidates) == 2
        assert all(c.round_number == 3 for c in candidates)

    def test_sorted_by_edge_descending(self):
        dg_outrights = {
            "top_20": [
                _dg_outright_record("Player A", "+150"),
                _dg_outright_record("Player B", "+300"),
            ],
        }
        lines = [
            NovigOutrightLine("t20", "Player A", "+250", "-400"),  # small edge
            NovigOutrightLine("t20", "Player B", "+500", "-1000"),  # big edge
        ]
        candidates, _ = evaluate_novig_lines(
            outright_lines=lines, matchup_lines=[],
            dg_outrights=dg_outrights, dg_matchups=[],
        )
        # Candidates should be sorted by edge desc. The highest-edge
        # one is in position 0.
        assert candidates[0].edge >= candidates[1].edge
