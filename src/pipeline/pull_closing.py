from __future__ import annotations

"""
Closing odds capture for CLV tracking.

Pulls the same outright and matchup odds right before tournament/round start.
These become the "closing line" for computing CLV on placed bets.
"""

import logging
from datetime import datetime, timedelta, timezone

from src.api.datagolf import DataGolfClient
from src.core.devig import american_to_decimal, parse_american_odds

log = logging.getLogger(__name__)


def pull_closing_outrights(tournament_slug: str | None = None,
                            tour: str = "pga") -> dict[str, list[dict]]:
    """Pull closing outright odds for all placement markets.

    Same as pull_outrights but tagged as 'closing' snapshots.
    """
    from src.pipeline.pull_outrights import pull_all_outrights
    return pull_all_outrights(tournament_slug, tour)


def pull_closing_matchups(tournament_slug: str | None = None,
                           tour: str = "pga") -> dict:
    """Pull closing matchup odds."""
    from src.pipeline.pull_matchups import (
        pull_round_matchups, pull_3balls
    )
    return {
        "round_matchups": pull_round_matchups(tournament_slug, tour),
        "3_balls": pull_3balls(tournament_slug, tour),
    }


def pull_closing_tournament_matchups(tournament_slug: str | None = None,
                                      tour: str = "pga") -> list[dict]:
    """Pull tournament-long matchup odds for closing-line capture.

    Tournament matchups resolve after 4 rounds, so "closing" for this
    market means the line at R1 tee time — captured once per tournament
    on Thursday morning.
    """
    from src.pipeline.pull_matchups import pull_tournament_matchups
    return pull_tournament_matchups(tournament_slug, tour)


def build_closing_snapshots(outrights: dict[str, list[dict]],
                             tournament_id: str | None) -> list[dict]:
    """Convert outright odds data into snapshot records for Supabase.

    Args:
        outrights: {"top_20": [player_records], ...}
        tournament_id: UUID of the tournament

    Returns:
        List of snapshot dicts ready for odds_snapshots table
    """
    market_map = {
        "win": "win", "top_10": "t10",
        "top_20": "t20", "make_cut": "make_cut",
    }
    now = datetime.now(timezone.utc).isoformat()
    snapshots = []

    for dg_market, records in outrights.items():
        market_type = market_map.get(dg_market, dg_market)
        if not isinstance(records, list):
            continue

        for player in records:
            player_name = player.get("player_name", "").strip().strip('"')
            dg_id = str(player.get("dg_id", ""))

            # Extract DG probability
            dg_data = player.get("datagolf", {})
            if isinstance(dg_data, dict):
                dg_odds_str = str(dg_data.get("baseline_history_fit") or
                                  dg_data.get("baseline") or "")
            else:
                dg_odds_str = str(dg_data or "")
            dg_prob = parse_american_odds(dg_odds_str)

            # Collect all book odds
            skip_keys = {"player_name", "dg_id", "datagolf", "dk_salary",
                         "dk_ownership", "early_late", "tee_time",
                         "r1_teetime", "event_name"}
            book_odds = {}
            for key, val in player.items():
                if key in skip_keys:
                    continue
                if isinstance(val, str) and (val.startswith("+") or val.startswith("-")):
                    book_odds[key] = val

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": market_type,
                "player_name": player_name,
                "player_dg_id": dg_id,
                "dg_prob": dg_prob,
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id

            snapshots.append(snapshot)

    return snapshots


def build_closing_matchup_snapshots(
    round_matchups: list[dict],
    three_balls: list[dict],
    tournament_id: str | None,
    tournament_matchups: list[dict] | None = None,
) -> list[dict]:
    """Convert matchup/3-ball odds into closing snapshot records.

    DG matchup format: {"p1_player_name": ..., "p2_player_name": ...,
                        "odds": {"book": {"p1": "-130", "p2": "+110"}, ...}}

    Tournament-long matchups use the same shape but their "closing" line
    is the R1-tee-time quote (captured once on Thursday), not a per-round
    quote. They are tagged with market_type='tournament_matchup'.
    """
    now = datetime.now(timezone.utc).isoformat()
    snapshots = []

    for m in round_matchups:
        odds_by_book = m.get("odds", {})
        for side in ("p1", "p2"):
            player_name = m.get(f"{side}_player_name", "").strip()
            if not player_name:
                continue
            opponent = "p2" if side == "p1" else "p1"

            book_odds = {}
            for book_name, book_data in odds_by_book.items():
                if isinstance(book_data, dict) and side in book_data:
                    book_odds[book_name] = book_data[side]

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": "round_matchup",
                "player_name": player_name,
                "player_dg_id": str(m.get(f"{side}_dg_id", "")),
                "opponent_name": m.get(f"{opponent}_player_name", ""),
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id
            snapshots.append(snapshot)

    for m in (tournament_matchups or []):
        odds_by_book = m.get("odds", {})
        for side in ("p1", "p2"):
            player_name = m.get(f"{side}_player_name", "").strip()
            if not player_name:
                continue
            opponent = "p2" if side == "p1" else "p1"

            book_odds = {}
            for book_name, book_data in odds_by_book.items():
                if isinstance(book_data, dict) and side in book_data:
                    book_odds[book_name] = book_data[side]

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": "tournament_matchup",
                "player_name": player_name,
                "player_dg_id": str(m.get(f"{side}_dg_id", "")),
                "opponent_name": m.get(f"{opponent}_player_name", ""),
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id
            snapshots.append(snapshot)

    for tb in three_balls:
        odds_by_book = tb.get("odds", {})
        for side in ("p1", "p2", "p3"):
            player_name = tb.get(f"{side}_player_name", "").strip()
            if not player_name:
                continue

            book_odds = {}
            for book_name, book_data in odds_by_book.items():
                if isinstance(book_data, dict) and side in book_data:
                    book_odds[book_name] = book_data[side]

            snapshot = {
                "snapshot_type": "closing",
                "snapshot_timestamp": now,
                "market_type": "3_ball",
                "player_name": player_name,
                "player_dg_id": str(tb.get(f"{side}_dg_id", "")),
                "book_odds": book_odds if book_odds else None,
            }
            if tournament_id:
                snapshot["tournament_id"] = tournament_id
            snapshots.append(snapshot)

    return snapshots


def detect_tournament_id(
    outrights: dict,
    cli_override: str | None = None,
) -> str | None:
    """Auto-detect tournament ID, matching run_pretournament/run_preround flow.

    Priority:
    1. Explicit override
    2. DG event ID from outrights data -> DB lookup
    3. Most recent tournament_id from this week's bets
    """
    from src.db import supabase_client as db

    if cli_override:
        log.info("Using override tournament_id: %s", cli_override)
        return cli_override

    event_name = outrights.get("_event_name")
    if event_name:
        dg_event_id = DataGolfClient().resolve_event_id(event_name)
        if dg_event_id:
            season = datetime.now().year
            existing = db.get_tournament(dg_event_id, season)
            if existing:
                log.info("Auto-detected tournament: %s (from DG event ID)",
                         existing.get("tournament_name"))
                return existing["id"]

    existing_bets = db.get_open_bets_for_week()
    for b in sorted(existing_bets, key=lambda x: x.get("bet_timestamp", ""),
                    reverse=True):
        if b.get("tournament_id"):
            t = db.get_tournament_by_id(b["tournament_id"])
            name = (t.get("tournament_name", b["tournament_id"])
                    if t else b["tournament_id"])
            log.info("Auto-detected tournament: %s (from this week's bets)",
                     name)
            return b["tournament_id"]

    log.warning("Could not detect tournament_id — CLV matching will be skipped")
    return None


def match_closing_to_bets(
    snapshots: list[dict],
    tournament_id: str | None,
) -> int:
    """Match closing odds to placed bets and compute CLV.

    For each unsettled bet without CLV already recorded, find the
    matching closing snapshot (by market_type + player_name) and update
    the bet row with closing odds + closing implied prob. Returns the
    number of bets updated.
    """
    from src.db import supabase_client as db

    if not tournament_id:
        log.info("No tournament_id — skipping CLV matching")
        return 0

    bets = db.get_unsettled_bets(tournament_id)
    if not bets:
        log.info("No unsettled bets to match")
        return 0

    snapshot_lookup: dict[tuple[str, str], dict] = {}
    for snap in snapshots:
        key = (snap["market_type"], snap["player_name"].lower().strip())
        snapshot_lookup[key] = snap

    matched = 0
    for bet in bets:
        if bet.get("clv") is not None:
            continue
        market = bet["market_type"]
        player = bet["player_name"].lower().strip()
        snap = snapshot_lookup.get((market, player))
        if not snap:
            continue

        book = bet["book"]
        closing_odds_str = (snap.get("book_odds") or {}).get(book)
        if not closing_odds_str:
            continue

        closing_implied = parse_american_odds(closing_odds_str)
        if closing_implied is None:
            continue
        closing_decimal = american_to_decimal(closing_odds_str)

        db.update_bet_closing(
            bet_id=bet["id"],
            closing_odds_decimal=closing_decimal,
            closing_implied_prob=closing_implied,
        )
        matched += 1

    return matched


def run_closing_capture(
    *,
    tour: str = "pga",
    tournament_slug: str | None = None,
    tournament_id_override: str | None = None,
    capture_matchups: bool = True,
    capture_tournament_matchups: bool = False,
) -> dict:
    """Full closing-odds capture pipeline — shared by CLI + Discord bot.

    Orchestrates: pull outrights (DG + Kalshi/Polymarket/ProphetX merges)
    → detect tournament → build outright snapshots → optional round /
    tournament matchup pulls with Kalshi/ProphetX merges → build matchup
    snapshots → store all in Supabase → match to placed bets and compute
    CLV. Returns a summary dict suitable for CLI printing or Discord
    embed rendering.

    `capture_tournament_matchups` is a deliberate kwarg (not auto-
    detected here) so callers can gate it to Thursday in their own
    scheduling logic — see bot `_scheduled_alerts` and the CLI
    `run_closing_odds.py` argparse block.

    Returns:
        {
            "tournament_id": str | None,
            "tournament_name": str,
            "outright_snapshots": int,
            "round_matchup_snapshots": int,
            "three_ball_snapshots": int,
            "tournament_matchup_snapshots": int,
            "total_snapshots_stored": int,
            "bets_matched": int,
            "avg_clv_pct": float | None,
            "positive_clv": int,
            "clv_bets_total": int,
            "bankroll": float,
            "captured_matchups": bool,
            "captured_tournament_matchups": bool,
            "errors": list[str],
        }
    """
    from src.db import supabase_client as db
    from src.pipeline.pull_kalshi import (
        pull_kalshi_outrights, pull_kalshi_matchups,
        merge_kalshi_into_outrights, merge_kalshi_into_matchups,
    )
    from src.pipeline.pull_polymarket import (
        pull_polymarket_outrights, merge_polymarket_into_outrights,
    )
    from src.pipeline.pull_prophetx import (
        pull_prophetx_outrights, pull_prophetx_matchups,
        merge_prophetx_into_outrights, merge_prophetx_into_matchups,
    )
    import config

    errors: list[str] = []

    outrights = pull_closing_outrights(tournament_slug, tour)
    tournament_name = outrights.get("_event_name", "") or ""

    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")

    # --- Merge prediction markets into outrights ---
    if tournament_name:
        try:
            k_out = pull_kalshi_outrights(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if any(len(v) > 0 for v in k_out.values()):
                merge_kalshi_into_outrights(outrights, k_out)
        except Exception as e:
            errors.append(f"kalshi_outrights:{type(e).__name__}")
            log.warning("Kalshi outrights unavailable: %s", e)

    if getattr(config, "POLYMARKET_ENABLED", False) and tournament_name:
        try:
            pm_out = pull_polymarket_outrights(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if any(len(v) > 0 for v in pm_out.values()):
                merge_polymarket_into_outrights(outrights, pm_out)
        except Exception as e:
            errors.append(f"polymarket_outrights:{type(e).__name__}")
            log.warning("Polymarket outrights unavailable: %s", e)

    if getattr(config, "PROPHETX_ENABLED", False) and tournament_name:
        try:
            px_out = pull_prophetx_outrights(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if any(len(v) > 0 for v in px_out.values()):
                merge_prophetx_into_outrights(outrights, px_out)
        except Exception as e:
            errors.append(f"prophetx_outrights:{type(e).__name__}")
            log.warning("ProphetX outrights unavailable: %s", e)

    tournament_id = detect_tournament_id(outrights, tournament_id_override)

    outright_snapshots = build_closing_snapshots(outrights, tournament_id)

    # --- Matchup pulls ---
    round_matchups: list[dict] = []
    three_balls: list[dict] = []
    tournament_matchups: list[dict] = []

    if capture_matchups:
        matchup_data = pull_closing_matchups(tournament_slug, tour)
        round_matchups = matchup_data.get("round_matchups", [])
        three_balls = matchup_data.get("3_balls", [])

    if capture_tournament_matchups:
        tournament_matchups = pull_closing_tournament_matchups(
            tournament_slug, tour,
        )

    if (capture_matchups or capture_tournament_matchups) and tournament_name:
        try:
            k_match = pull_kalshi_matchups(
                tournament_name, today, end_date,
                tournament_slug=tournament_slug,
            )
            if k_match:
                if round_matchups:
                    merge_kalshi_into_matchups(round_matchups, k_match)
                if tournament_matchups:
                    merge_kalshi_into_matchups(tournament_matchups, k_match)
        except Exception as e:
            errors.append(f"kalshi_matchups:{type(e).__name__}")
            log.warning("Kalshi matchups unavailable: %s", e)

        if getattr(config, "PROPHETX_ENABLED", False):
            try:
                px_match = pull_prophetx_matchups(
                    tournament_name, today, end_date,
                    tournament_slug=tournament_slug,
                )
                if px_match:
                    if round_matchups:
                        merge_prophetx_into_matchups(round_matchups, px_match)
                    if tournament_matchups:
                        merge_prophetx_into_matchups(tournament_matchups, px_match)
            except Exception as e:
                errors.append(f"prophetx_matchups:{type(e).__name__}")
                log.warning("ProphetX matchups unavailable: %s", e)

    matchup_snapshots: list[dict] = []
    if capture_matchups or capture_tournament_matchups:
        matchup_snapshots = build_closing_matchup_snapshots(
            round_matchups, three_balls, tournament_id,
            tournament_matchups=tournament_matchups,
        )

    all_snapshots = outright_snapshots + matchup_snapshots

    stored_count = 0
    if all_snapshots:
        try:
            stored = db.insert_odds_snapshots(all_snapshots)
            stored_count = len(stored or [])
        except Exception as e:
            errors.append(f"insert_snapshots:{type(e).__name__}")
            log.error("Failed to store snapshots: %s", e)

    # CLV matching
    bets_matched = 0
    try:
        bets_matched = match_closing_to_bets(all_snapshots, tournament_id)
    except Exception as e:
        errors.append(f"match_clv:{type(e).__name__}")
        log.error("CLV matching failed: %s", e)

    # Summary CLV stats for the tournament (all bets, not just matched)
    avg_clv_pct: float | None = None
    positive_clv = 0
    clv_bets_total = 0
    if tournament_id:
        try:
            all_bets = db.get_bets_for_tournament(tournament_id)
            clv_bets = [b for b in all_bets if b.get("clv") is not None]
            clv_bets_total = len(clv_bets)
            if clv_bets:
                avg_clv_pct = sum(b["clv"] for b in clv_bets) / len(clv_bets) * 100
                positive_clv = sum(1 for b in clv_bets if b["clv"] > 0)
        except Exception as e:
            errors.append(f"clv_summary:{type(e).__name__}")
            log.warning("CLV summary query failed: %s", e)

    # Counts by market type from the snapshots we actually built
    n_round = sum(1 for s in matchup_snapshots
                  if s["market_type"] == "round_matchup")
    n_three = sum(1 for s in matchup_snapshots
                  if s["market_type"] == "3_ball")
    n_tourn = sum(1 for s in matchup_snapshots
                  if s["market_type"] == "tournament_matchup")

    try:
        bankroll = db.get_bankroll()
    except Exception:
        bankroll = 0.0

    return {
        "tournament_id": tournament_id,
        "tournament_name": tournament_name or "Unknown",
        "outright_snapshots": len(outright_snapshots),
        "round_matchup_snapshots": n_round,
        "three_ball_snapshots": n_three,
        "tournament_matchup_snapshots": n_tourn,
        "total_snapshots_stored": stored_count,
        "bets_matched": bets_matched,
        "avg_clv_pct": avg_clv_pct,
        "positive_clv": positive_clv,
        "clv_bets_total": clv_bets_total,
        "bankroll": bankroll,
        "captured_matchups": capture_matchups,
        "captured_tournament_matchups": capture_tournament_matchups,
        "errors": errors,
    }
