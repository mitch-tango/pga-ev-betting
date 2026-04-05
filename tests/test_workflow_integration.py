"""Tests for workflow integration with prediction markets (section 10).

Tests that Polymarket and ProphetX blocks are properly gated by
config flags, handle failures gracefully, and integrate into
the existing DG + Kalshi pipeline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── run_pretournament.py integration ─��──────────────────────────────


class TestPretournamentPolymarket:
    """Polymarket block in pretournament workflow."""

    @patch("config.POLYMARKET_ENABLED", True)
    @patch("scripts.run_pretournament.pull_polymarket_outrights")
    @patch("scripts.run_pretournament.merge_polymarket_into_outrights")
    def test_polymarket_runs_when_enabled(self, mock_merge, mock_pull):
        mock_pull.return_value = {"win": [{"player_name": "Test", "polymarket_mid_prob": 0.2}]}

        from scripts.run_pretournament import _pull_polymarket_block
        outrights = {"win": [{"player_name": "Test"}]}
        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_called_once()
        mock_merge.assert_called_once()

    @patch("config.POLYMARKET_ENABLED", False)
    @patch("scripts.run_pretournament.pull_polymarket_outrights")
    def test_polymarket_skips_when_disabled(self, mock_pull):
        from scripts.run_pretournament import _pull_polymarket_block
        outrights = {"win": [{"player_name": "Test"}]}
        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_not_called()

    @patch("config.POLYMARKET_ENABLED", True)
    @patch("scripts.run_pretournament.pull_polymarket_outrights", side_effect=Exception("API down"))
    def test_polymarket_failure_continues(self, mock_pull):
        from scripts.run_pretournament import _pull_polymarket_block
        outrights = {"win": [{"player_name": "Test"}]}
        # Should not raise
        _pull_polymarket_block(outrights, "The Masters", "2026-04-09", "2026-04-12")


class TestPretournamentProphetX:
    """ProphetX block in pretournament workflow."""

    @patch("config.PROPHETX_ENABLED", True)
    @patch("scripts.run_pretournament.pull_prophetx_outrights")
    @patch("scripts.run_pretournament.pull_prophetx_matchups")
    @patch("scripts.run_pretournament.merge_prophetx_into_outrights")
    @patch("scripts.run_pretournament.merge_prophetx_into_matchups")
    def test_prophetx_runs_when_enabled(
        self, mock_merge_m, mock_merge_o, mock_pull_m, mock_pull_o,
    ):
        mock_pull_o.return_value = {"win": [{"player_name": "Test"}]}
        mock_pull_m.return_value = [{"p1_name": "A", "p2_name": "B"}]

        from scripts.run_pretournament import _pull_prophetx_block
        outrights = {"win": [{"player_name": "Test"}]}
        matchups = []
        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull_o.assert_called_once()
        mock_pull_m.assert_called_once()

    @patch("config.PROPHETX_ENABLED", False)
    @patch("scripts.run_pretournament.pull_prophetx_outrights")
    def test_prophetx_skips_when_disabled(self, mock_pull):
        from scripts.run_pretournament import _pull_prophetx_block
        outrights = {"win": []}
        matchups = []
        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_not_called()

    @patch("config.PROPHETX_ENABLED", True)
    @patch("scripts.run_pretournament.pull_prophetx_outrights", side_effect=Exception("Auth fail"))
    def test_prophetx_failure_continues(self, mock_pull):
        from scripts.run_pretournament import _pull_prophetx_block
        outrights = {"win": []}
        matchups = []
        # Should not raise
        _pull_prophetx_block(outrights, matchups, "The Masters", "2026-04-09", "2026-04-12")


# ── run_preround.py integration ─────────────────────────────────────


class TestPreroundProphetX:
    """ProphetX matchup block in preround workflow."""

    @patch("config.PROPHETX_ENABLED", True)
    @patch("scripts.run_preround.pull_prophetx_matchups")
    @patch("scripts.run_preround.merge_prophetx_into_matchups")
    def test_prophetx_matchups_merged(self, mock_merge, mock_pull):
        mock_pull.return_value = [{"p1_name": "A", "p2_name": "B", "p1_prob": 0.55, "p2_prob": 0.45}]

        from scripts.run_preround import _pull_prophetx_matchup_block
        matchups = [{"p1_player_name": "A", "p2_player_name": "B", "odds": {}}]
        _pull_prophetx_matchup_block(matchups, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_called_once()
        mock_merge.assert_called_once()

    @patch("config.PROPHETX_ENABLED", False)
    @patch("scripts.run_preround.pull_prophetx_matchups")
    def test_prophetx_skips_when_disabled(self, mock_pull):
        from scripts.run_preround import _pull_prophetx_matchup_block
        matchups = []
        _pull_prophetx_matchup_block(matchups, "The Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_not_called()


# ── pull_live_edges.py integration ─���────────────────────────────────


class TestLiveEdgesIntegration:
    """Prediction market blocks in live edge pipeline."""

    @patch("config.POLYMARKET_ENABLED", True)
    @patch("src.pipeline.pull_live_edges.pull_polymarket_outrights")
    @patch("src.pipeline.pull_live_edges.merge_polymarket_into_outrights")
    def test_polymarket_merged_in_live(self, mock_merge, mock_pull):
        mock_pull.return_value = {"win": [{"player_name": "Test"}]}

        from src.pipeline.pull_live_edges import _pull_polymarket_block
        outrights = {"win": []}
        stats = {}
        _pull_polymarket_block(outrights, stats, "Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_called_once()
        assert stats.get("polymarket_merged") is True

    @patch("config.PROPHETX_ENABLED", True)
    @patch("src.pipeline.pull_live_edges.pull_prophetx_outrights")
    @patch("src.pipeline.pull_live_edges.merge_prophetx_into_outrights")
    def test_prophetx_merged_in_live(self, mock_merge, mock_pull):
        mock_pull.return_value = {"win": [{"player_name": "Test"}]}

        from src.pipeline.pull_live_edges import _pull_prophetx_block
        outrights = {"win": []}
        matchups = []
        stats = {}
        _pull_prophetx_block(outrights, matchups, stats, "Masters", "2026-04-09", "2026-04-12")

        mock_pull.assert_called_once()
        assert stats.get("prophetx_merged") is True

    @patch("config.POLYMARKET_ENABLED", True)
    @patch("src.pipeline.pull_live_edges.pull_polymarket_outrights", side_effect=Exception("fail"))
    def test_polymarket_failure_tracked_in_stats(self, mock_pull):
        from src.pipeline.pull_live_edges import _pull_polymarket_block
        outrights = {"win": []}
        stats = {}
        _pull_polymarket_block(outrights, stats, "Masters", "2026-04-09", "2026-04-12")

        assert "polymarket_error" in stats


# ── DG-only regression ─────────────────────────────────────��────────


class TestDGOnlyRegression:
    """Pipeline works with all prediction markets disabled/failing."""

    @patch("config.POLYMARKET_ENABLED", False)
    @patch("config.PROPHETX_ENABLED", False)
    def test_pretournament_blocks_skip_cleanly(self):
        from scripts.run_pretournament import _pull_polymarket_block, _pull_prophetx_block
        outrights = {"win": [{"player_name": "Test"}]}
        matchups = []

        # Both should complete without error
        _pull_polymarket_block(outrights, "Test", "2026-01-01", "2026-01-04")
        _pull_prophetx_block(outrights, matchups, "Test", "2026-01-01", "2026-01-04")

        # Outrights should be unmodified
        assert outrights == {"win": [{"player_name": "Test"}]}
