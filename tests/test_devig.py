"""Unit tests for src/core/devig.py"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.devig import (
    parse_american_odds,
    american_to_decimal,
    decimal_to_american,
    implied_prob_to_decimal,
    decimal_to_implied_prob,
    power_devig,
    devig_independent,
    devig_two_way,
    devig_three_way,
    kalshi_price_to_american,
    kalshi_price_to_decimal,
    kalshi_midpoint,
)


class TestParseAmericanOdds:
    def test_positive_odds(self):
        assert abs(parse_american_odds("+200") - 1/3) < 0.001

    def test_negative_odds(self):
        assert abs(parse_american_odds("-200") - 2/3) < 0.001

    def test_even_money(self):
        assert abs(parse_american_odds("+100") - 0.5) < 0.001

    def test_heavy_favorite(self):
        assert abs(parse_american_odds("-1000") - 10/11) < 0.001

    def test_big_longshot(self):
        assert abs(parse_american_odds("+5000") - 100/5100) < 0.001

    def test_none_input(self):
        assert parse_american_odds(None) is None

    def test_empty_string(self):
        assert parse_american_odds("") is None

    def test_inf(self):
        assert parse_american_odds("Inf") is None

    def test_na(self):
        assert parse_american_odds("N/A") is None

    def test_quoted_odds(self):
        assert abs(parse_american_odds('""+220""') - 0.0) > 0  # Should handle quotes
        result = parse_american_odds('"+220"')
        assert result is not None
        assert abs(result - 100/320) < 0.001

    def test_no_sign_positive(self):
        result = parse_american_odds("220")
        assert result is not None
        assert abs(result - 100/320) < 0.001


class TestAmericanToDecimal:
    def test_positive_odds(self):
        assert abs(american_to_decimal("+200") - 3.0) < 0.001

    def test_negative_odds(self):
        assert abs(american_to_decimal("-200") - 1.5) < 0.001

    def test_even_money(self):
        assert abs(american_to_decimal("+100") - 2.0) < 0.001

    def test_none(self):
        assert american_to_decimal(None) is None

    def test_heavy_favorite(self):
        result = american_to_decimal("-500")
        assert abs(result - 1.2) < 0.001


class TestDecimalToAmerican:
    def test_positive(self):
        assert decimal_to_american(3.0) == "+200"

    def test_negative(self):
        assert decimal_to_american(1.5) == "-200"

    def test_even(self):
        assert decimal_to_american(2.0) == "+100"

    def test_invalid(self):
        assert decimal_to_american(1.0) == ""
        assert decimal_to_american(0.5) == ""
        assert decimal_to_american(None) == ""


class TestImpliedProbConversion:
    def test_prob_to_decimal(self):
        assert abs(implied_prob_to_decimal(0.5) - 2.0) < 0.001

    def test_decimal_to_prob(self):
        assert abs(decimal_to_implied_prob(2.0) - 0.5) < 0.001

    def test_roundtrip(self):
        prob = 0.35
        decimal = implied_prob_to_decimal(prob)
        back = decimal_to_implied_prob(decimal)
        assert abs(back - prob) < 0.0001

    def test_edge_cases(self):
        assert implied_prob_to_decimal(0) is None
        assert implied_prob_to_decimal(1.0) is None
        assert implied_prob_to_decimal(None) is None
        assert decimal_to_implied_prob(0) is None
        assert decimal_to_implied_prob(None) is None


class TestPowerDevig:
    def test_already_fair(self):
        probs = [0.5, 0.3, 0.2]
        result = power_devig(probs)
        for r, p in zip(result, probs):
            assert abs(r - p) < 0.001

    def test_removes_vig(self):
        # Typical overround: sum > 1
        probs = [0.55, 0.35, 0.15]  # sum = 1.05
        result = power_devig(probs)
        total = sum(r for r in result if r is not None)
        assert abs(total - 1.0) < 0.001

    def test_preserves_ordering(self):
        probs = [0.60, 0.25, 0.10, 0.08, 0.05]  # sum = 1.08
        result = power_devig(probs)
        for i in range(len(result) - 1):
            assert result[i] >= result[i + 1]

    def test_handles_none(self):
        probs = [0.55, None, 0.35, None, 0.15]
        result = power_devig(probs)
        assert result[1] is None
        assert result[3] is None
        valid = [r for r in result if r is not None]
        assert abs(sum(valid) - 1.0) < 0.001

    def test_empty_list(self):
        assert power_devig([]) == []

    def test_all_none(self):
        result = power_devig([None, None, None])
        assert result == [None, None, None]

    def test_favorite_longshot_bias_correction(self):
        # Power devig should shrink longshots more than favorites
        probs = [0.52, 0.30, 0.15, 0.08, 0.03]  # sum = 1.08
        result = power_devig(probs)

        # Favorite's reduction should be proportionally smaller
        fav_reduction = (probs[0] - result[0]) / probs[0]
        long_reduction = (probs[4] - result[4]) / probs[4]
        assert long_reduction > fav_reduction

    def test_realistic_golf_field(self):
        # Simulate 20 players with realistic win probabilities
        probs = [0.12, 0.09, 0.08, 0.07, 0.065, 0.06, 0.055, 0.05,
                 0.045, 0.04, 0.035, 0.03, 0.025, 0.02, 0.018, 0.015,
                 0.012, 0.01, 0.008, 0.005]
        # Add vig: multiply all by ~1.08
        vigged = [p * 1.08 for p in probs]
        result = power_devig(vigged)
        total = sum(r for r in result if r is not None)
        assert abs(total - 1.0) < 0.001


class TestDevigIndependent:
    def test_removes_overround(self):
        # 10 players for T5, expected 5 outcomes
        probs = [0.70, 0.60, 0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15]
        # Sum = 3.95, but expected = 5 (wait, sum < expected means no vig)
        # Let's use overround scenario
        probs2 = [0.75, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30, 0.25]
        # Sum = 4.80, expected = 5 → no vig in this direction
        # For T20 with vig:
        probs3 = [0.90, 0.85, 0.80, 0.75, 0.70]  # sum = 4.0, expected = 3
        result = devig_independent(probs3, 3)
        total = sum(r for r in result if r is not None)
        assert abs(total - 3.0) < 0.01

    def test_no_vig(self):
        probs = [0.5, 0.3, 0.2]  # sum = 1.0, expected = 1
        result = devig_independent(probs, 1.0)
        for r, p in zip(result, probs):
            assert abs(r - p) < 0.001

    def test_handles_none(self):
        probs = [0.90, None, 0.80, 0.75]
        result = devig_independent(probs, 2.0)
        assert result[1] is None


class TestDevigTwoWay:
    def test_removes_vig(self):
        # Matchup with vig: A at 55%, B at 50% (sum = 1.05)
        a, b = devig_two_way(0.55, 0.50)
        assert abs(a + b - 1.0) < 0.001

    def test_preserves_none(self):
        a, b = devig_two_way(None, 0.5)
        assert a is None


class TestDevigThreeWay:
    def test_removes_vig(self):
        a, b, c = devig_three_way(0.40, 0.35, 0.30)  # sum = 1.05
        assert abs(a + b + c - 1.0) < 0.001

    def test_preserves_none(self):
        a, b, c = devig_three_way(0.40, None, 0.30)
        assert b is None


# ---- Kalshi Odds Conversion Tests ----

class TestKalshiPriceToAmerican:
    def test_longshot(self):
        # (1 - 0.06) / 0.06 * 100 = 1566.67, rounds to 1567
        assert kalshi_price_to_american('0.06') == '+1567'

    def test_favorite(self):
        # 0.55 / 0.45 * 100 = 122.22, rounds to 122
        assert kalshi_price_to_american('0.55') == '-122'

    def test_even_money(self):
        assert kalshi_price_to_american('0.50') == '+100'

    def test_extreme_longshot(self):
        assert kalshi_price_to_american('0.01') == '+9900'

    def test_heavy_favorite(self):
        assert kalshi_price_to_american('0.95') == '-1900'

    def test_result_format(self):
        result = kalshi_price_to_american('0.30')
        assert result.startswith('+') or result.startswith('-')
        # Should be integer string (no decimals)
        sign = result[0]
        assert result[1:].isdigit()

    def test_none_input(self):
        assert kalshi_price_to_american(None) == ''

    def test_empty_string(self):
        assert kalshi_price_to_american('') == ''

    def test_invalid_range(self):
        assert kalshi_price_to_american('0.0') == ''
        assert kalshi_price_to_american('1.0') == ''
        assert kalshi_price_to_american('-0.5') == ''
        assert kalshi_price_to_american('1.5') == ''


class TestKalshiPriceToDecimal:
    def test_longshot(self):
        result = kalshi_price_to_decimal('0.06')
        assert abs(result - 16.667) < 0.01

    def test_slight_favorite(self):
        result = kalshi_price_to_decimal('0.55')
        assert abs(result - 1.818) < 0.01

    def test_even_money(self):
        result = kalshi_price_to_decimal('0.50')
        assert result == 2.0

    def test_zero_price(self):
        assert kalshi_price_to_decimal('0.0') is None

    def test_one_price(self):
        assert kalshi_price_to_decimal('1.0') is None

    def test_non_numeric(self):
        assert kalshi_price_to_decimal('abc') is None

    def test_empty_string(self):
        assert kalshi_price_to_decimal('') is None

    def test_none_input(self):
        assert kalshi_price_to_decimal(None) is None


class TestKalshiMidpoint:
    def test_basic(self):
        result = kalshi_midpoint('0.04', '0.06')
        assert abs(result - 0.05) < 0.0001

    def test_tight_spread(self):
        result = kalshi_midpoint('0.50', '0.52')
        assert abs(result - 0.51) < 0.0001

    def test_none_bid(self):
        assert kalshi_midpoint(None, '0.06') is None

    def test_none_ask(self):
        assert kalshi_midpoint('0.04', None) is None

    def test_both_empty(self):
        assert kalshi_midpoint('', '') is None

    def test_bid_exceeds_one(self):
        assert kalshi_midpoint('1.5', '0.06') is None

    def test_ask_exceeds_one(self):
        assert kalshi_midpoint('0.04', '2.0') is None


class TestKalshiRoundTrip:
    def test_roundtrip_longshot(self):
        american = kalshi_price_to_american('0.06')
        recovered = parse_american_odds(american)
        assert abs(recovered - 0.06) < 0.002

    def test_roundtrip_favorite(self):
        american = kalshi_price_to_american('0.55')
        recovered = parse_american_odds(american)
        assert abs(recovered - 0.55) < 0.002

    def test_roundtrip_even(self):
        american = kalshi_price_to_american('0.50')
        recovered = parse_american_odds(american)
        assert abs(recovered - 0.50) < 0.001

    def test_roundtrip_extreme_longshot(self):
        american = kalshi_price_to_american('0.01')
        recovered = parse_american_odds(american)
        assert abs(recovered - 0.01) < 0.001

    def test_roundtrip_heavy_favorite(self):
        american = kalshi_price_to_american('0.95')
        recovered = parse_american_odds(american)
        assert abs(recovered - 0.95) < 0.002
