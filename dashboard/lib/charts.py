"""Plotly figure builders for the PGA +EV Dashboard."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from lib.theme import CHART_COLORS, COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_NEUTRAL


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


def build_pnl_curve(cumulative_pnl: list[dict]) -> go.Figure | None:
    """Line chart of cumulative P&L over time."""
    if not cumulative_pnl:
        return None

    dates = [d["date"] for d in cumulative_pnl]
    values = [d["cumulative_pnl"] for d in cumulative_pnl]
    color = COLOR_POSITIVE if values[-1] >= 0 else COLOR_NEGATIVE

    fig = go.Figure(
        data=[go.Scatter(x=dates, y=values, mode="lines", line=dict(color=color))]
    )
    fig.add_hline(y=0, line_dash="dash", line_color=COLOR_NEUTRAL)
    _apply_common_layout(fig)
    fig.update_layout(yaxis=dict(tickprefix="$"))
    return fig


def build_edge_histogram(bets: list[dict]) -> go.Figure | None:
    """Histogram of edge values, colored by sign."""
    if not bets:
        return None

    edges = [b["edge"] for b in bets]
    pos = [e * 100 for e in edges if e >= 0]
    neg = [e * 100 for e in edges if e < 0]

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=pos, marker_color=COLOR_POSITIVE, name="Positive"))
    fig.add_trace(go.Histogram(x=neg, marker_color=COLOR_NEGATIVE, name="Negative"))
    fig.add_vline(x=0, line_dash="dash", line_color=COLOR_NEUTRAL)
    _apply_common_layout(fig)
    fig.update_layout(barmode="overlay", xaxis=dict(ticksuffix="%"))
    return fig


def build_bankroll_drawdown(bankroll_data: list[dict], drawdown_data: list[dict]) -> go.Figure | None:
    """Two-panel chart: bankroll equity curve (top) and drawdown (bottom)."""
    if not bankroll_data and not drawdown_data:
        return None

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.03,
    )
    fig.add_trace(
        go.Scatter(
            x=[d["entry_date"] for d in bankroll_data],
            y=[d["running_balance"] for d in bankroll_data],
            mode="lines", line=dict(color=CHART_COLORS[0]), name="Balance",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[d["entry_date"] for d in drawdown_data],
            y=[d["drawdown_pct"] for d in drawdown_data],
            mode="lines", fill="tozeroy",
            line=dict(color=COLOR_NEGATIVE), name="Drawdown",
        ),
        row=2, col=1,
    )
    _apply_common_layout(fig)
    fig.update_layout(
        yaxis=dict(tickprefix="$"),
        yaxis2=dict(ticksuffix="%", title_font=dict(color="#E0E0E0"), tickfont=dict(color="#E0E0E0")),
    )
    return fig


def build_weekly_exposure(exposure_data: list[dict]) -> go.Figure | None:
    """Bar chart of weekly exposure with bet count line overlay."""
    if not exposure_data:
        return None

    weeks = [d["week"] for d in exposure_data]
    exposure = [d["total_exposure"] for d in exposure_data]
    bets_placed = [d["bets_placed"] for d in exposure_data]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=weeks, y=exposure, marker_color=CHART_COLORS[0], name="Exposure"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=weeks, y=bets_placed, mode="lines+markers",
                   line=dict(color=CHART_COLORS[2]), name="Bets", yaxis="y2"),
        secondary_y=True,
    )
    _apply_common_layout(fig)
    fig.update_layout(
        yaxis=dict(tickprefix="$"),
        yaxis2=dict(title_font=dict(color="#E0E0E0"), tickfont=dict(color="#E0E0E0")),
    )
    return fig


def build_clv_trend(clv_data: list[dict]) -> go.Figure | None:
    """Line chart of weekly average CLV percentage."""
    if not clv_data:
        return None

    weeks = [d["week"] for d in clv_data]
    values = [d["avg_clv_pct"] for d in clv_data]
    color = COLOR_POSITIVE if values[-1] >= 0 else COLOR_NEGATIVE

    fig = go.Figure(
        data=[go.Scatter(x=weeks, y=values, mode="lines", line=dict(color=color))]
    )
    fig.add_hline(y=0, line_dash="dash", line_color=COLOR_NEUTRAL)
    _apply_common_layout(fig)
    fig.update_layout(yaxis=dict(ticksuffix="%"))
    return fig


def build_calibration(calibration_data: list[dict]) -> go.Figure | None:
    """Scatter plot comparing predicted vs actual hit rates."""
    if not calibration_data:
        return None

    predicted = [d["avg_predicted_pct"] for d in calibration_data]
    actual = [d["actual_hit_pct"] for d in calibration_data]
    n_values = [d["n"] for d in calibration_data]
    labels = [d["prob_bucket"] for d in calibration_data]

    fig = go.Figure(
        data=[go.Scatter(
            x=predicted, y=actual, mode="markers",
            marker=dict(
                size=n_values,
                sizemode="area",
                sizeref=2.0 * max(n_values) / (40.0 ** 2),
                color=CHART_COLORS[0],
            ),
            text=labels,
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Predicted: %{x:.1f}%<br>"
                "Actual: %{y:.1f}%<br>"
                "n=%{marker.size}<extra></extra>"
            ),
        )]
    )
    fig.add_shape(
        type="line", x0=0, y0=0, x1=100, y1=100,
        line=dict(dash="dash", color=COLOR_NEUTRAL),
    )
    _apply_common_layout(fig)
    fig.update_layout(
        xaxis=dict(ticksuffix="%", title="Predicted Probability"),
        yaxis=dict(ticksuffix="%", title="Actual Hit Rate"),
    )
    return fig


def build_roi_by_edge_tier(tier_data: list[dict]) -> go.Figure | None:
    """Bar+line chart showing ROI and bet count by edge tier."""
    if not tier_data:
        return None

    tiers = [d["edge_tier"] for d in tier_data]
    roi_values = [d["roi_pct"] for d in tier_data]
    bet_counts = [d["total_bets"] for d in tier_data]
    colors = [COLOR_POSITIVE if r >= 0 else COLOR_NEGATIVE for r in roi_values]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=tiers, y=roi_values, marker_color=colors, name="ROI %"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=tiers, y=bet_counts, mode="lines+markers",
                   line=dict(color=CHART_COLORS[2]), name="Bet Count", yaxis="y2"),
        secondary_y=True,
    )
    fig.add_hline(y=0, line_dash="dash", line_color=COLOR_NEUTRAL, secondary_y=False)
    _apply_common_layout(fig)
    fig.update_layout(
        yaxis=dict(ticksuffix="%"),
        yaxis2=dict(title_font=dict(color="#E0E0E0"), tickfont=dict(color="#E0E0E0")),
    )
    return fig
