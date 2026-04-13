"""Unit tests for NoVig screenshot extraction.

Covers the parts that DON'T hit Claude: `_clean_odds`, the
JSON→NovigExtraction transformer `_build_extraction`, and the batch
`merge_extractions` helper. The Claude API call itself is mocked in a
separate test so we can assert the request shape without an API key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.novig_vision import (
    NovigExtraction,
    NovigMatchupLine,
    NovigOutrightLine,
    _build_extraction,
    _clean_odds,
    extract_novig_screenshot,
    merge_extractions,
)


# ── _clean_odds ──────────────────────────────────────────────────────


class TestCleanOdds:

    def test_none_passthrough(self):
        assert _clean_odds(None) is None

    def test_dot_placeholder_is_none(self):
        assert _clean_odds("·") is None
        assert _clean_odds("•") is None

    def test_signed_string_passes_through(self):
        assert _clean_odds("-449") == "-449"
        assert _clean_odds("+313") == "+313"

    def test_unsigned_string_gets_sign(self):
        assert _clean_odds("313") == "+313"
        assert _clean_odds("449") == "+449"

    def test_negative_int_gets_sign(self):
        assert _clean_odds(-449) == "-449"

    def test_positive_int_gets_plus_sign(self):
        assert _clean_odds(313) == "+313"

    def test_whitespace_stripped(self):
        assert _clean_odds("  -449  ") == "-449"

    def test_empty_string_is_none(self):
        assert _clean_odds("") is None

    def test_bad_string_is_none(self):
        assert _clean_odds("nope") is None


# ── _build_extraction ────────────────────────────────────────────────


class TestBuildOutrightExtraction:

    def test_top_20_subtab_maps_to_t20(self):
        data = {
            "tournament_name": "Augusta Golf Tournament",
            "market_tab": "Winner",
            "subtab": "Top 20",
            "round_number": None,
            "outrights": [
                {
                    "player_name": "Xander Schauffele",
                    "yes_odds_american": "-449",
                    "no_odds_american": "+313",
                },
                {
                    "player_name": "Scottie Scheffler",
                    "yes_odds_american": "-413",
                    "no_odds_american": "+303",
                },
            ],
            "matchups": [],
        }
        ext = _build_extraction(data)
        assert ext.tournament_name == "Augusta Golf Tournament"
        assert ext.subtab == "Top 20"
        assert len(ext.outrights) == 2
        assert ext.outrights[0].market_type == "t20"
        assert ext.outrights[0].yes_odds_american == "-449"
        assert ext.outrights[0].no_odds_american == "+313"
        assert not ext.matchups

    def test_outright_winner_subtab_maps_to_win(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Winner",
            "subtab": "Outright Winner",
            "round_number": None,
            "outrights": [
                {"player_name": "Rory McIlroy", "yes_odds_american": "+450",
                 "no_odds_american": "-650"},
            ],
            "matchups": [],
        })
        assert ext.outrights[0].market_type == "win"

    def test_make_the_cut_tab(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "To Make The Cut",
            "subtab": None,
            "round_number": None,
            "outrights": [
                {"player_name": "Max Homa", "yes_odds_american": "-120",
                 "no_odds_american": "+100"},
            ],
            "matchups": [],
        })
        assert ext.outrights[0].market_type == "make_cut"

    def test_dot_placeholder_side_becomes_none(self):
        """A NoVig row with a dot in the No column means that side's
        market is unavailable — should land as None, not a bogus string."""
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Winner",
            "subtab": "Top 10",
            "round_number": None,
            "outrights": [
                {"player_name": "Ryan Gerard", "yes_odds_american": "+478",
                 "no_odds_american": "·"},
            ],
            "matchups": [],
        })
        assert ext.outrights[0].yes_odds_american == "+478"
        assert ext.outrights[0].no_odds_american is None

    def test_empty_player_name_is_skipped(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Winner",
            "subtab": "Top 20",
            "round_number": None,
            "outrights": [
                {"player_name": "", "yes_odds_american": "+100",
                 "no_odds_american": "-100"},
                {"player_name": "Scottie Scheffler", "yes_odds_american": "-413",
                 "no_odds_american": "+303"},
            ],
            "matchups": [],
        })
        assert len(ext.outrights) == 1
        assert ext.outrights[0].player_name == "Scottie Scheffler"


class TestBuildMatchupExtraction:

    def test_round_number_marks_round_matchup(self):
        ext = _build_extraction({
            "tournament_name": "Augusta Golf Tournament",
            "market_tab": "Matchups",
            "subtab": None,
            "round_number": 4,
            "outrights": [],
            "matchups": [
                {
                    "player1_name": "Shane Lowry",
                    "player1_odds_american": "-102",
                    "player2_name": "Sam Burns",
                    "player2_odds_american": "-109",
                },
                {
                    "player1_name": "Rory McIlroy",
                    "player1_odds_american": "-114",
                    "player2_name": "Cameron Young",
                    "player2_odds_american": "+105",
                },
            ],
        })
        assert len(ext.matchups) == 2
        assert ext.matchups[0].market_type == "round_matchup"
        assert ext.matchups[0].round_number == 4
        assert ext.matchups[0].player1_name == "Shane Lowry"

    def test_no_round_number_means_tournament_matchup(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Matchups",
            "subtab": None,
            "round_number": None,
            "outrights": [],
            "matchups": [
                {"player1_name": "A", "player1_odds_american": "-110",
                 "player2_name": "B", "player2_odds_american": "-110"},
            ],
        })
        assert ext.matchups[0].market_type == "tournament_matchup"
        assert ext.matchups[0].round_number is None

    def test_string_round_number_is_parsed(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Matchups",
            "subtab": None,
            "round_number": "3",
            "outrights": [],
            "matchups": [
                {"player1_name": "A", "player1_odds_american": "-110",
                 "player2_name": "B", "player2_odds_american": "-110"},
            ],
        })
        assert ext.matchups[0].round_number == 3

    def test_matchup_with_missing_odds_is_skipped(self):
        ext = _build_extraction({
            "tournament_name": "X",
            "market_tab": "Matchups",
            "subtab": None,
            "round_number": 2,
            "outrights": [],
            "matchups": [
                {"player1_name": "A", "player1_odds_american": None,
                 "player2_name": "B", "player2_odds_american": "-110"},
                {"player1_name": "C", "player1_odds_american": "-105",
                 "player2_name": "D", "player2_odds_american": "-115"},
            ],
        })
        assert len(ext.matchups) == 1
        assert ext.matchups[0].player1_name == "C"


# ── merge_extractions ────────────────────────────────────────────────


class TestMergeExtractions:

    def test_empty_input_returns_empty(self):
        out, match, name = merge_extractions([])
        assert out == []
        assert match == []
        assert name is None

    def test_batches_preserved(self):
        ext1 = NovigExtraction(
            tournament_name="Augusta Golf Tournament",
            market_tab="Winner", subtab="Top 20", round_number=None,
            outrights=[
                NovigOutrightLine("t20", "A", "-200", "+150"),
            ],
            matchups=[],
        )
        ext2 = NovigExtraction(
            tournament_name="Augusta Golf Tournament",
            market_tab="Matchups", subtab=None, round_number=4,
            outrights=[],
            matchups=[
                NovigMatchupLine("round_matchup", "C", "-110", "D", "-110", 4),
            ],
        )
        outs, ms, name = merge_extractions([ext1, ext2])
        assert len(outs) == 1
        assert len(ms) == 1
        assert name == "Augusta Golf Tournament"

    def test_most_common_tournament_name_wins(self):
        ext_a = NovigExtraction("A", "Winner", "Top 20", None, [], [])
        ext_b = NovigExtraction("B", "Winner", "Top 20", None, [], [])
        ext_a2 = NovigExtraction("A", "Matchups", None, 4, [], [])
        _, _, name = merge_extractions([ext_a, ext_b, ext_a2])
        assert name == "A"


# ── extract_novig_screenshot (mocked Claude) ─────────────────────────


class TestExtractNovigScreenshotMocked:

    def test_no_api_key_returns_none(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "", raising=False)
        result = extract_novig_screenshot(b"fakeimage")
        assert result is None

    @patch("anthropic.Anthropic")
    def test_mocked_call_returns_parsed_extraction(
        self, mock_anthropic_cls, monkeypatch,
    ):
        import config
        monkeypatch.setattr(
            config, "ANTHROPIC_API_KEY", "test-key", raising=False)

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Claude returns well-formed JSON (no markdown fence)
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text=(
            '{"tournament_name": "Augusta Golf Tournament", '
            '"market_tab": "Winner", "subtab": "Top 20", '
            '"round_number": null, "outrights": ['
            '{"player_name": "Xander Schauffele", '
            '"yes_odds_american": "-449", "no_odds_american": "+313"}], '
            '"matchups": []}'
        ))]
        mock_client.messages.create.return_value = fake_response

        result = extract_novig_screenshot(b"fakeimagebytes")
        assert result is not None
        assert result.tournament_name == "Augusta Golf Tournament"
        assert len(result.outrights) == 1
        assert result.outrights[0].market_type == "t20"
        assert result.outrights[0].yes_odds_american == "-449"

        # Request shape: a content list with image block + text block
        call = mock_client.messages.create.call_args
        content = call.kwargs["messages"][0]["content"]
        assert any(c["type"] == "image" for c in content)
        assert any(c["type"] == "text" for c in content)

    @patch("anthropic.Anthropic")
    def test_markdown_fence_is_stripped(
        self, mock_anthropic_cls, monkeypatch,
    ):
        import config
        monkeypatch.setattr(
            config, "ANTHROPIC_API_KEY", "test-key", raising=False)
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Claude sometimes wraps JSON in ```json fences even when told not to
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text=(
            '```json\n'
            '{"tournament_name": "X", "market_tab": "Matchups", '
            '"subtab": null, "round_number": 2, "outrights": [], '
            '"matchups": [{"player1_name": "A", '
            '"player1_odds_american": "-110", "player2_name": "B", '
            '"player2_odds_american": "-110"}]}\n'
            '```'
        ))]
        mock_client.messages.create.return_value = fake_response
        result = extract_novig_screenshot(b"x")
        assert result is not None
        assert len(result.matchups) == 1
        assert result.matchups[0].market_type == "round_matchup"

    @patch("anthropic.Anthropic")
    def test_api_exception_returns_none(
        self, mock_anthropic_cls, monkeypatch,
    ):
        import config
        monkeypatch.setattr(
            config, "ANTHROPIC_API_KEY", "test-key", raising=False)
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("API down")
        assert extract_novig_screenshot(b"x") is None

    @patch("anthropic.Anthropic")
    def test_invalid_json_returns_none(
        self, mock_anthropic_cls, monkeypatch,
    ):
        import config
        monkeypatch.setattr(
            config, "ANTHROPIC_API_KEY", "test-key", raising=False)
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="not json")]
        mock_client.messages.create.return_value = fake_response
        assert extract_novig_screenshot(b"x") is None
