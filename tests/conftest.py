"""Shared test fixture factories for prediction market data."""

from __future__ import annotations

import json
import uuid

import pytest


# ---------------------------------------------------------------------------
# Polymarket factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_polymarket_event():
    """Factory for Gamma API event dicts."""

    def _make(title: str, start_date: str, end_date: str,
              markets: list[dict] | None = None) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "title": title,
            "slug": title.lower().replace(" ", "-"),
            "startDate": start_date,
            "endDate": end_date,
            "markets": markets or [],
        }

    return _make


@pytest.fixture
def make_polymarket_market():
    """Factory for a single Polymarket market dict."""

    def _make(
        question: str,
        slug: str,
        outcome_prices: list[float],
        clob_token_ids: list[str],
        volume: float = 500.0,
        outcomes: list[str] | None = None,
    ) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "question": question,
            "slug": slug,
            "outcomePrices": json.dumps(outcome_prices),
            "clobTokenIds": json.dumps(clob_token_ids),
            "volume": volume,
            "outcomes": json.dumps(outcomes or ["Yes", "No"]),
            "marketType": "binary",
            "liquidity": volume * 0.5,
        }

    return _make


@pytest.fixture
def make_polymarket_books_response():
    """Factory for CLOB /books response for one token."""

    def _make(token_id: str, best_bid: float, best_ask: float) -> dict:
        return {
            token_id: {
                "bids": [{"price": str(best_bid), "size": "100"}],
                "asks": [{"price": str(best_ask), "size": "100"}],
            }
        }

    return _make


# ---------------------------------------------------------------------------
# ProphetX factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_prophetx_event():
    """Factory for ProphetX event dicts."""

    def _make(name: str, start_date: str, event_id: str | None = None) -> dict:
        return {
            "id": event_id or str(uuid.uuid4()),
            "name": name,
            "start_date": start_date,
            "end_date": start_date,  # same day default
        }

    return _make


@pytest.fixture
def make_prophetx_market():
    """Factory for ProphetX market dicts."""

    def _make(
        line_id: str,
        competitors: list[dict],
        odds: int | float | str,
        market_type: str = "moneyline",
        sub_type: str = "outrights",
    ) -> dict:
        return {
            "line_id": line_id,
            "market_type": market_type,
            "sub_type": sub_type,
            "competitors": competitors,
            "odds": odds,
        }

    return _make


@pytest.fixture
def make_prophetx_matchup_market():
    """Convenience factory for ProphetX 2-competitor matchup markets."""

    def _make(
        line_id: str,
        player1: str,
        player2: str,
        p1_odds: int | float,
        p2_odds: int | float,
    ) -> dict:
        return {
            "line_id": line_id,
            "market_type": "moneyline",
            "sub_type": "matchup",
            "competitors": [
                {"competitor_name": player1, "odds": p1_odds},
                {"competitor_name": player2, "odds": p2_odds},
            ],
            "odds": None,
        }

    return _make
