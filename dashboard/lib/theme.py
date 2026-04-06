"""Color palette and formatting helpers for the PGA +EV Dashboard.

Bloomberg-inspired dark theme palette with green for positive values
and muted warm gray for negative values (avoids red per user preference).
"""
from __future__ import annotations

# Color constants
COLOR_POSITIVE: str = "#00C853"
COLOR_NEGATIVE: str = "#9E9E9E"
COLOR_NEUTRAL: str = "#616161"

# Chart color palette: distinguishable colors for dark backgrounds
CHART_COLORS: list[str] = [
    "#4A90D9",  # Blue
    "#50C878",  # Emerald
    "#FF8C42",  # Orange
    "#9B59B6",  # Purple
    "#26A69A",  # Teal
    "#E67E22",  # Dark orange
    "#5DADE2",  # Light blue
    "#F39C12",  # Gold
]


def format_american_odds(decimal_odds: float) -> str:
    """Convert decimal odds to American format string."""
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")
    if decimal_odds >= 2.0:
        american = round((decimal_odds - 1) * 100)
        return f"+{american}"
    else:
        american = round(-100 / (decimal_odds - 1))
        return str(american)


def format_currency(amount: float) -> str:
    """Format as currency with sign."""
    if amount < 0:
        return f"-${abs(amount):.2f}"
    return f"${amount:.2f}"


def format_percentage(value: float | None) -> str:
    """Format as percentage with sign and one decimal place."""
    if value is None:
        return "\u2014"
    pct = value * 100
    if pct > 0:
        return f"+{pct:.1f}%"
    return f"{pct:.1f}%"


def color_value(value: float) -> str:
    """Return color constant based on sign of value."""
    if value > 0:
        return COLOR_POSITIVE
    elif value < 0:
        return COLOR_NEGATIVE
    return COLOR_NEUTRAL
