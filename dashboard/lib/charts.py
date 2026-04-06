"""Plotly figure builders for the PGA +EV Dashboard."""
from __future__ import annotations

import plotly.graph_objects as go

from lib.theme import CHART_COLORS


def _apply_common_layout(fig: go.Figure) -> go.Figure:
    """Apply shared layout conventions to a Plotly figure."""
    fig.update_layout(
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5
        ),
        font=dict(color="#E0E0E0"),
    )
    return fig


def build_exposure_by_market(bets: list[dict]) -> go.Figure | None:
    """Build a horizontal bar chart showing total stake by market type.

    Returns None if bets is empty.
    """
    if not bets:
        return None

    # Aggregate stakes by market type
    stakes: dict[str, float] = {}
    for bet in bets:
        mt = bet["market_type"]
        stakes[mt] = stakes.get(mt, 0.0) + bet["stake"]

    # Return None if no positive exposure
    if not any(v > 0 for v in stakes.values()):
        return None

    # Sort by total stake descending
    sorted_items = sorted(stakes.items(), key=lambda x: x[1], reverse=True)
    labels = [item[0] for item in sorted_items]
    values = [item[1] for item in sorted_items]

    # Assign colors from palette
    colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(labels))]

    fig = go.Figure(
        data=[
            go.Bar(
                y=labels,
                x=values,
                orientation="h",
                marker_color=colors,
            )
        ]
    )

    _apply_common_layout(fig)

    fig.update_layout(
        title_text="Exposure by Market Type",
        xaxis=dict(tickprefix="$", showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
        yaxis=dict(showgrid=False),
    )
    return fig
