"""Tests for the stale-matchup filter used by pre-round and live scans."""

from datetime import datetime, timedelta

from src.pipeline.pull_matchups import filter_stale_matchups, _is_player_stale


NOW = datetime(2026, 4, 12, 14, 0)  # 2pm local at the venue
PAST = NOW - timedelta(hours=2)
FUTURE = NOW + timedelta(hours=2)


def _player(*, teetime=None, in_field=True):
    return {"round_teetime": teetime, "in_field_for_round": in_field}


def _lookup(players, current_round=4, now=NOW):
    return {
        "current_round": current_round,
        "now_local": now,
        "players": players,
    }


def _mu(p1: str, p2: str) -> dict:
    return {"p1_dg_id": p1, "p2_dg_id": p2,
            "p1_player_name": f"Player {p1}", "p2_player_name": f"Player {p2}",
            "odds": {}}


def _3ball(p1: str, p2: str, p3: str) -> dict:
    return {"p1_dg_id": p1, "p2_dg_id": p2, "p3_dg_id": p3,
            "p1_player_name": f"P{p1}", "p2_player_name": f"P{p2}",
            "p3_player_name": f"P{p3}", "odds": {}}


class TestIsPlayerStale:
    def test_empty_lookup_keeps_player(self):
        assert _is_player_stale("99999", {}) is False

    def test_not_in_field_keeps_player(self):
        # Player not in the field lookup at all → conservative, not stale.
        lookup = _lookup({"1": _player(teetime=FUTURE)})
        assert _is_player_stale("99999", lookup) is False

    def test_future_teetime_is_fresh(self):
        lookup = _lookup({"1": _player(teetime=FUTURE)})
        assert _is_player_stale("1", lookup) is False

    def test_no_teetime_recorded_is_fresh(self):
        # In the field for this round but tee time wasn't parseable —
        # don't drop, surface the edge.
        lookup = _lookup({"1": _player(teetime=None, in_field=True)})
        assert _is_player_stale("1", lookup) is False

    def test_past_teetime_is_stale(self):
        lookup = _lookup({"1": _player(teetime=PAST)})
        assert _is_player_stale("1", lookup) is True

    def test_teetime_exactly_now_is_stale(self):
        lookup = _lookup({"1": _player(teetime=NOW)})
        assert _is_player_stale("1", lookup) is True

    def test_not_in_field_for_round_is_stale(self):
        # Cut / WD / MDF → no entry for current round in DG teetimes.
        lookup = _lookup({"1": _player(teetime=None, in_field=False)})
        assert _is_player_stale("1", lookup) is True


class TestFilterStaleMatchups:
    def test_empty_field_lookup_passes_through(self):
        matchups = [_mu("1", "2"), _mu("3", "4")]
        assert filter_stale_matchups(matchups, {}) == matchups

    def test_lookup_with_no_players_passes_through(self):
        matchups = [_mu("1", "2")]
        lookup = _lookup({})
        assert filter_stale_matchups(matchups, lookup) == matchups

    def test_empty_matchups_returns_empty(self):
        lookup = _lookup({"1": _player(teetime=FUTURE)})
        assert filter_stale_matchups([], lookup) == []

    def test_drops_stale_p1(self):
        lookup = _lookup({
            "1": _player(teetime=PAST),    # already teed off
            "2": _player(teetime=FUTURE),
            "3": _player(teetime=FUTURE),
            "4": _player(teetime=FUTURE),
        })
        kept = filter_stale_matchups([_mu("1", "2"), _mu("3", "4")], lookup)
        assert len(kept) == 1
        assert kept[0]["p1_dg_id"] == "3"

    def test_drops_stale_p2(self):
        lookup = _lookup({
            "1": _player(teetime=FUTURE),
            "2": _player(teetime=PAST),
        })
        assert filter_stale_matchups([_mu("1", "2")], lookup) == []

    def test_drops_if_one_cut_other_not_started(self):
        """A player who's cut disqualifies the matchup even if the other
        is fresh — book line is dead either way."""
        lookup = _lookup({
            "1": _player(in_field=False),
            "2": _player(teetime=FUTURE),
        })
        assert filter_stale_matchups([_mu("1", "2")], lookup) == []

    def test_keeps_all_fresh_matchups(self):
        lookup = _lookup({
            "1": _player(teetime=FUTURE),
            "2": _player(teetime=FUTURE),
            "3": _player(teetime=FUTURE),
        })
        matchups = [_mu("1", "2"), _mu("2", "3"), _mu("1", "3")]
        kept = filter_stale_matchups(matchups, lookup)
        assert kept == matchups

    def test_three_ball_all_three_players_checked(self):
        lookup = _lookup({
            "1": _player(teetime=FUTURE),
            "2": _player(teetime=FUTURE),
            "3": _player(teetime=PAST),    # on course
            "4": _player(teetime=FUTURE),
            "5": _player(teetime=FUTURE),
            "6": _player(teetime=FUTURE),
        })
        groups = [_3ball("1", "2", "3"), _3ball("4", "5", "6")]
        kept = filter_stale_matchups(groups, lookup, n_players=3)
        assert len(kept) == 1
        assert kept[0]["p1_dg_id"] == "4"

    def test_missing_dg_id_keeps_matchup(self):
        """Defensive: if a matchup record is missing a dg_id, don't drop
        it just because the empty string isn't in the lookup."""
        lookup = _lookup({"1": _player(teetime=FUTURE)})
        mu = {"p1_dg_id": "1", "p2_dg_id": "", "odds": {}}
        assert filter_stale_matchups([mu], lookup) == [mu]
