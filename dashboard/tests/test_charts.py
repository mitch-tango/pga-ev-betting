"""Tests for dashboard.lib.charts — Plotly figure builders."""

import plotly.graph_objects as go
import plotly.io as pio

from lib.charts import build_exposure_by_market


SAMPLE_BETS = [
    {"market_type": "matchup", "stake": 25.0},
    {"market_type": "matchup", "stake": 30.0},
    {"market_type": "outright", "stake": 10.0},
    {"market_type": "placement", "stake": 15.0},
]


def test_build_exposure_by_market_returns_figure():
    fig = build_exposure_by_market(SAMPLE_BETS)
    assert isinstance(fig, go.Figure)


def test_build_exposure_by_market_horizontal_bars():
    fig = build_exposure_by_market(SAMPLE_BETS)
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    assert len(bar_traces) >= 1
    assert bar_traces[0].orientation == "h"


def test_build_exposure_by_market_empty_list_returns_none():
    assert build_exposure_by_market([]) is None


def test_build_exposure_by_market_zero_stakes_returns_none():
    bets = [{"market_type": "matchup", "stake": 0.0}]
    assert build_exposure_by_market(bets) is None


def test_build_exposure_by_market_correct_labels():
    fig = build_exposure_by_market(SAMPLE_BETS)
    bar_trace = [t for t in fig.data if isinstance(t, go.Bar)][0]
    labels = list(bar_trace.y)
    assert set(labels) == {"matchup", "outright", "placement"}


def test_build_exposure_by_market_sorted_descending():
    fig = build_exposure_by_market(SAMPLE_BETS)
    bar_trace = [t for t in fig.data if isinstance(t, go.Bar)][0]
    labels = list(bar_trace.y)
    # matchup=55, placement=15, outright=10
    assert labels == ["matchup", "placement", "outright"]


def test_build_exposure_by_market_correct_values():
    fig = build_exposure_by_market(SAMPLE_BETS)
    bar_trace = [t for t in fig.data if isinstance(t, go.Bar)][0]
    values = list(bar_trace.x)
    assert values == [55.0, 15.0, 10.0]


def test_build_exposure_by_market_compact_margins():
    fig = build_exposure_by_market(SAMPLE_BETS)
    m = fig.layout.margin
    assert m.l == 10
    assert m.r == 10
    assert m.t == 40
    assert m.b == 10


def test_build_exposure_by_market_serializable():
    fig = build_exposure_by_market(SAMPLE_BETS)
    json_str = pio.to_json(fig)
    assert isinstance(json_str, str)
    assert len(json_str) > 0
