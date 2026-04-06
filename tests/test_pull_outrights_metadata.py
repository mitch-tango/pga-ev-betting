"""Tests for pull_outrights staleness metadata (_is_live, _notes, _last_updated)."""

from unittest.mock import patch, MagicMock

from src.pipeline.pull_outrights import pull_all_outrights


def _mock_dg_response(event_name=None, last_updated=None, notes=None, odds=None):
    """Build a DG API response dict."""
    data = {"odds": odds or []}
    if event_name:
        data["event_name"] = event_name
    if last_updated:
        data["last_updated"] = last_updated
    if notes:
        data["notes"] = notes
    return {"status": "ok", "data": data}


class TestStalenessMetadata:
    """pull_all_outrights propagates DG metadata for staleness detection."""

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_is_live_false_when_no_notes(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            event_name="The Masters",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_is_live"] is False

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_is_live_true_when_notes_say_live(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            event_name="The Masters",
            notes="Event is live — baseline model not available",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_is_live"] is True

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_is_live_true_baseline_model_not_available(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            notes="Baseline model not available for this event",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_is_live"] is True

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_is_live_false_normal_notes(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            notes="Updated pre-tournament odds",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_is_live"] is False

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_last_updated_propagated(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            last_updated="2026-04-05 02:35:17 UTC",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_last_updated"] == "2026-04-05 02:35:17 UTC"

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_notes_propagated(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            notes="Some note from DG",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_notes"] == "Some note from DG"

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_event_name_propagated(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = _mock_dg_response(
            event_name="The Masters",
        )
        result = pull_all_outrights(tour="pga")
        assert result["_event_name"] == "The Masters"

    @patch("src.pipeline.pull_outrights.DataGolfClient")
    def test_no_metadata_keys_when_absent(self, mock_cls):
        """When DG returns no metadata, only _is_live should be present."""
        client = MagicMock()
        mock_cls.return_value = client
        client.get_outrights.return_value = {"status": "ok", "data": {"odds": []}}
        result = pull_all_outrights(tour="pga")
        assert "_event_name" not in result
        assert "_last_updated" not in result
        assert "_notes" not in result
        assert result["_is_live"] is False
