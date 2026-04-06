import pytest

from lib.theme import (
    COLOR_NEGATIVE,
    COLOR_NEUTRAL,
    COLOR_POSITIVE,
    color_value,
    format_american_odds,
    format_currency,
    format_percentage,
)


class TestFormatAmericanOdds:
    def test_underdog(self):
        assert format_american_odds(2.5) == "+150"

    def test_favorite(self):
        assert format_american_odds(1.5) == "-200"

    def test_even_money(self):
        assert format_american_odds(2.0) == "+100"

    def test_invalid_odds_raises(self):
        with pytest.raises(ValueError):
            format_american_odds(1.0)

    def test_below_one_raises(self):
        with pytest.raises(ValueError):
            format_american_odds(0.5)


class TestFormatCurrency:
    def test_positive(self):
        assert format_currency(25.0) == "$25.00"

    def test_negative(self):
        assert format_currency(-12.5) == "-$12.50"

    def test_zero(self):
        assert format_currency(0) == "$0.00"


class TestFormatPercentage:
    def test_positive(self):
        assert format_percentage(0.05) == "+5.0%"

    def test_negative(self):
        assert format_percentage(-0.03) == "-3.0%"

    def test_none(self):
        assert format_percentage(None) == "\u2014"


class TestColorValue:
    def test_positive(self):
        assert color_value(1.5) == COLOR_POSITIVE

    def test_negative(self):
        assert color_value(-0.5) == COLOR_NEGATIVE

    def test_zero(self):
        assert color_value(0) == COLOR_NEUTRAL
