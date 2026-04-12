"""Tests for the stale-matchup filter used by pre-round and live scans."""

from src.pipeline.pull_matchups import filter_stale_matchups, _is_player_stale


def _mu(p1: str, p2: str) -> dict:
    return {"p1_dg_id": p1, "p2_dg_id": p2,
            "p1_player_name": f"Player {p1}", "p2_player_name": f"Player {p2}",
            "odds": {}}


def _3ball(p1: str, p2: str, p3: str) -> dict:
    return {"p1_dg_id": p1, "p2_dg_id": p2, "p3_dg_id": p3,
            "p1_player_name": f"P{p1}", "p2_player_name": f"P{p2}",
            "p3_player_name": f"P{p3}", "odds": {}}


class TestIsPlayerStale:
    def test_not_in_field_keeps_player(self):
        assert _is_player_stale("99999", {}) is False

    def test_active_not_started_is_fresh(self):
        lookup = {"1": {"thru": None, "status": "active"}}
        assert _is_player_stale("1", lookup) is False

    def test_empty_thru_is_fresh(self):
        lookup = {"1": {"thru": "", "status": "active"}}
        assert _is_player_stale("1", lookup) is False

    def test_numeric_thru_string_is_stale(self):
        lookup = {"1": {"thru": "5", "status": "active"}}
        assert _is_player_stale("1", lookup) is True

    def test_numeric_thru_int_is_stale(self):
        lookup = {"1": {"thru": 12, "status": "active"}}
        assert _is_player_stale("1", lookup) is True

    def test_finished_round_is_stale(self):
        lookup = {"1": {"thru": "F", "status": "active"}}
        assert _is_player_stale("1", lookup) is True

    def test_cut_is_stale(self):
        lookup = {"1": {"thru": None, "status": "cut"}}
        assert _is_player_stale("1", lookup) is True

    def test_wd_is_stale(self):
        lookup = {"1": {"thru": None, "status": "wd"}}
        assert _is_player_stale("1", lookup) is True

    def test_mdf_treated_as_cut(self):
        lookup = {"1": {"thru": None, "status": "mdf"}}
        assert _is_player_stale("1", lookup) is True


class TestFilterStaleMatchups:
    def test_empty_field_lookup_passes_through(self):
        matchups = [_mu("1", "2"), _mu("3", "4")]
        assert filter_stale_matchups(matchups, {}) == matchups

    def test_empty_matchups_returns_empty(self):
        assert filter_stale_matchups([], {"1": {"thru": None, "status": "active"}}) == []

    def test_drops_stale_p1(self):
        lookup = {
            "1": {"thru": "5", "status": "active"},  # on course
            "2": {"thru": None, "status": "active"},
            "3": {"thru": None, "status": "active"},
            "4": {"thru": None, "status": "active"},
        }
        kept = filter_stale_matchups([_mu("1", "2"), _mu("3", "4")], lookup)
        assert len(kept) == 1
        assert kept[0]["p1_dg_id"] == "3"

    def test_drops_stale_p2(self):
        lookup = {
            "1": {"thru": None, "status": "active"},
            "2": {"thru": "F", "status": "active"},  # finished this round
        }
        kept = filter_stale_matchups([_mu("1", "2")], lookup)
        assert kept == []

    def test_drops_if_one_finished_other_not_started(self):
        """A finished player disqualifies the matchup even if the
        other hasn't teed off (book line is stale for the half-played pair)."""
        lookup = {
            "1": {"thru": "F", "status": "active"},
            "2": {"thru": None, "status": "active"},
        }
        kept = filter_stale_matchups([_mu("1", "2")], lookup)
        assert kept == []

    def test_keeps_all_fresh_matchups(self):
        lookup = {
            "1": {"thru": None, "status": "active"},
            "2": {"thru": "", "status": "active"},
            "3": {"thru": None, "status": "active"},
        }
        matchups = [_mu("1", "2"), _mu("2", "3"), _mu("1", "3")]
        kept = filter_stale_matchups(matchups, lookup)
        assert kept == matchups

    def test_three_ball_all_three_players_checked(self):
        lookup = {
            "1": {"thru": None, "status": "active"},
            "2": {"thru": None, "status": "active"},
            "3": {"thru": "7", "status": "active"},  # on course
            "4": {"thru": None, "status": "active"},
            "5": {"thru": None, "status": "active"},
            "6": {"thru": None, "status": "active"},
        }
        groups = [_3ball("1", "2", "3"), _3ball("4", "5", "6")]
        kept = filter_stale_matchups(groups, lookup, n_players=3)
        assert len(kept) == 1
        assert kept[0]["p1_dg_id"] == "4"

    def test_missing_dg_id_keeps_matchup(self):
        """Defensive: if a matchup record is missing a dg_id, don't drop
        it just because the empty string isn't in the lookup."""
        lookup = {"1": {"thru": None, "status": "active"}}
        mu = {"p1_dg_id": "1", "p2_dg_id": "", "odds": {}}
        assert filter_stale_matchups([mu], lookup) == [mu]
