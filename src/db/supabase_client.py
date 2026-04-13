from __future__ import annotations

"""
Supabase interface for the PGA +EV Betting System.

All database operations: tournaments, candidates, bets, bankroll,
odds snapshots, players, and analytics views.
"""

from datetime import datetime, timezone

from supabase import create_client, Client

import config


def get_client() -> Client:
    """Create and return a Supabase client."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


_client: Client | None = None


def client() -> Client:
    """Singleton Supabase client."""
    global _client
    if _client is None:
        _client = get_client()
    return _client


# ---- Tournaments ----

def upsert_tournament(tournament_name: str, start_date: str, purse: int,
                      dg_event_id: str | None = None, season: int | None = None,
                      is_signature: bool = False, is_no_cut: bool = False,
                      putting_surface: str | None = None) -> dict:
    """Insert or update a tournament. Returns the tournament record."""
    data = {
        "tournament_name": tournament_name,
        "start_date": start_date,
        "purse": purse,
        "is_signature": is_signature,
        "is_no_cut": is_no_cut,
    }
    if dg_event_id:
        data["dg_event_id"] = dg_event_id
    if season:
        data["season"] = season
    if putting_surface:
        data["putting_surface"] = putting_surface

    result = client().table("tournaments").upsert(
        data, on_conflict="dg_event_id,season"
    ).execute()
    return result.data[0] if result.data else {}


def get_tournament(dg_event_id: str, season: int) -> dict | None:
    """Look up a tournament by DG event ID and season."""
    result = client().table("tournaments").select("*").eq(
        "dg_event_id", dg_event_id
    ).eq("season", season).limit(1).execute()
    return result.data[0] if result.data else None


def get_tournament_by_id(tournament_id: str) -> dict | None:
    """Look up a tournament by UUID."""
    result = client().table("tournaments").select("*").eq(
        "id", tournament_id
    ).limit(1).execute()
    return result.data[0] if result.data else None


# ---- Candidate Bets ----

def insert_candidates(candidates: list[dict]) -> list[dict]:
    """Batch insert candidate bets from edge calculator output.

    Args:
        candidates: list of dicts with keys matching candidate_bets schema

    Returns:
        list of inserted records with IDs
    """
    if not candidates:
        return []
    result = client().table("candidate_bets").insert(candidates).execute()
    return result.data


def persist_candidates(candidates, tournament_id: str | None,
                       scan_type: str) -> int:
    """Insert a batch of CandidateBet objects and attach their new DB ids.

    Mutates each candidate in place by setting ``candidate_id`` to the row
    id returned by Supabase, so downstream placement flows (e.g. Discord
    ``/place``) can link the resulting ``bets`` row back to the candidate.
    Matching is done by (player_name, market_type, opponent_name,
    opponent_2_name, round_number), which is unique within a single scan
    because ``calculate_*_edges`` dedupes on that key.

    Returns the number of rows successfully inserted.
    """
    if not candidates or not tournament_id:
        return 0

    rows = [c.to_db_dict(tournament_id, scan_type) for c in candidates]
    inserted = insert_candidates(rows)

    lookup = {
        (r["player_name"], r["market_type"],
         r.get("opponent_name") or "",
         r.get("opponent_2_name") or "",
         r.get("round_number")): r["id"]
        for r in inserted
    }
    for c in candidates:
        key = (c.player_name, c.market_type,
               c.opponent_name or "",
               c.opponent_2_name or "",
               c.round_number)
        cid = lookup.get(key)
        if cid:
            c.candidate_id = cid
    return len(inserted)


def update_candidate_status(candidate_id: str, status: str,
                            skip_reason: str | None = None) -> dict:
    """Update a candidate's status (pending -> placed/skipped/expired)."""
    data = {"status": status}
    if skip_reason:
        data["skip_reason"] = skip_reason
    result = client().table("candidate_bets").update(data).eq(
        "id", candidate_id
    ).execute()
    return result.data[0] if result.data else {}


def get_pending_candidates(tournament_id: str) -> list[dict]:
    """Get all pending candidates for a tournament."""
    result = client().table("candidate_bets").select("*").eq(
        "tournament_id", tournament_id
    ).eq("status", "pending").order("edge", desc=True).execute()
    return result.data


# ---- Bets ----

def insert_bet(candidate_id: str | None, tournament_id: str,
               market_type: str, player_name: str, book: str,
               odds_at_bet_decimal: float, implied_prob_at_bet: float,
               your_prob: float, edge: float, stake: float,
               scanned_odds_decimal: float | None = None,
               odds_at_bet_american: str | None = None,
               player_id: str | None = None,
               opponent_name: str | None = None,
               opponent_id: str | None = None,
               opponent_2_name: str | None = None,
               opponent_2_id: str | None = None,
               round_number: int | None = None,
               is_live: bool = False,
               correlation_haircut: float = 1.0,
               notes: str | None = None) -> dict:
    """Insert a placed bet and update bankroll ledger."""
    data = {
        "tournament_id": tournament_id,
        "market_type": market_type,
        "player_name": player_name,
        "book": book,
        "odds_at_bet_decimal": odds_at_bet_decimal,
        "implied_prob_at_bet": implied_prob_at_bet,
        "your_prob": your_prob,
        "edge": edge,
        "stake": stake,
        "is_live": is_live,
        "correlation_haircut": correlation_haircut,
    }
    if candidate_id:
        data["candidate_id"] = candidate_id
    if scanned_odds_decimal:
        data["scanned_odds_decimal"] = scanned_odds_decimal
    if odds_at_bet_american:
        data["odds_at_bet_american"] = odds_at_bet_american
    if player_id:
        data["player_id"] = player_id
    if opponent_name:
        data["opponent_name"] = opponent_name
    if opponent_id:
        data["opponent_id"] = opponent_id
    if opponent_2_name:
        data["opponent_2_name"] = opponent_2_name
    if opponent_2_id:
        data["opponent_2_id"] = opponent_2_id
    if round_number is not None:
        data["round_number"] = round_number
    if notes:
        data["notes"] = notes

    result = client().table("bets").insert(data).execute()
    bet = result.data[0] if result.data else {}

    # Update candidate status if linked
    if candidate_id:
        update_candidate_status(candidate_id, "placed")

    # Add bankroll ledger entry
    if bet:
        current_balance = get_bankroll()
        insert_ledger_entry(
            entry_type="bet_placed",
            amount=-stake,
            running_balance=current_balance - stake,
            bet_id=bet["id"],
        )

    return bet


def update_bet_closing(bet_id: str, closing_odds_decimal: float,
                       closing_implied_prob: float) -> dict:
    """Update a bet with closing odds and compute CLV."""
    # Get the bet to compute CLV
    bet_result = client().table("bets").select("implied_prob_at_bet").eq(
        "id", bet_id
    ).limit(1).execute()

    clv = None
    if bet_result.data:
        opening = bet_result.data[0]["implied_prob_at_bet"]
        clv = closing_implied_prob - opening

    data = {
        "closing_odds_decimal": closing_odds_decimal,
        "closing_implied_prob": closing_implied_prob,
        "clv": clv,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = client().table("bets").update(data).eq("id", bet_id).execute()
    return result.data[0] if result.data else {}


def settle_bet(bet_id: str, outcome: str, settlement_rule: str,
               payout: float, pnl: float,
               actual_finish: str | None = None,
               opponent_finish: str | None = None) -> dict:
    """Settle a bet with outcome and P&L. Updates bankroll ledger."""
    data = {
        "outcome": outcome,
        "settlement_rule": settlement_rule,
        "payout": payout,
        "pnl": pnl,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if actual_finish:
        data["actual_finish"] = actual_finish
    if opponent_finish:
        data["opponent_finish"] = opponent_finish

    result = client().table("bets").update(data).eq("id", bet_id).execute()

    # Add bankroll ledger entry for settlement
    if payout > 0:
        current_balance = get_bankroll()
        insert_ledger_entry(
            entry_type="bet_settled",
            amount=payout,
            running_balance=current_balance + payout,
            bet_id=bet_id,
            notes=f"{outcome} — {settlement_rule}",
        )

    return result.data[0] if result.data else {}


def get_unsettled_bets(tournament_id: str) -> list[dict]:
    """Get all unsettled bets for a tournament."""
    result = client().table("bets").select("*").eq(
        "tournament_id", tournament_id
    ).is_("outcome", "null").execute()
    return result.data


def get_open_bets_for_week() -> list[dict]:
    """Get all bets placed this week (for exposure checks)."""
    # Get bets from the last 7 days
    from datetime import timedelta
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    result = client().table("bets").select("*").gte(
        "bet_timestamp", week_ago
    ).execute()
    return result.data


def get_bets_for_tournament(tournament_id: str) -> list[dict]:
    """Get all bets for a tournament."""
    result = client().table("bets").select("*").eq(
        "tournament_id", tournament_id
    ).execute()
    return result.data


# ---- Bankroll Ledger ----

def get_bankroll() -> float:
    """Get the current bankroll balance from the latest ledger entry."""
    result = client().table("bankroll_ledger").select(
        "running_balance"
    ).order("entry_date", desc=True).limit(1).execute()

    if result.data:
        return result.data[0]["running_balance"]
    return 0.0


def insert_ledger_entry(entry_type: str, amount: float,
                        running_balance: float,
                        bet_id: str | None = None,
                        notes: str | None = None) -> dict:
    """Insert a bankroll ledger entry."""
    data = {
        "entry_type": entry_type,
        "amount": amount,
        "running_balance": running_balance,
    }
    if bet_id:
        data["bet_id"] = bet_id
    if notes:
        data["notes"] = notes

    result = client().table("bankroll_ledger").insert(data).execute()
    return result.data[0] if result.data else {}


def initialize_bankroll(amount: float) -> dict:
    """Create the initial bankroll deposit."""
    return insert_ledger_entry(
        entry_type="deposit",
        amount=amount,
        running_balance=amount,
        notes="Initial bankroll deposit",
    )


# ---- Odds Snapshots ----

def insert_odds_snapshots(snapshots: list[dict]) -> list[dict]:
    """Batch insert odds snapshots (for CLV tracking)."""
    if not snapshots:
        return []
    result = client().table("odds_snapshots").insert(snapshots).execute()
    return result.data


def get_closing_snapshot(tournament_id: str, market_type: str,
                         player_name: str) -> dict | None:
    """Get the closing odds snapshot for a specific bet."""
    result = client().table("odds_snapshots").select("*").eq(
        "tournament_id", tournament_id
    ).eq("market_type", market_type).eq(
        "player_name", player_name
    ).eq("snapshot_type", "closing").order(
        "snapshot_timestamp", desc=True
    ).limit(1).execute()
    return result.data[0] if result.data else None


# ---- Players ----

def get_or_create_player(canonical_name: str,
                         dg_id: str | None = None) -> dict:
    """Get existing player or create new one."""
    # Try by dg_id first (most reliable)
    if dg_id:
        result = client().table("players").select("*").eq(
            "dg_id", dg_id
        ).limit(1).execute()
        if result.data:
            return result.data[0]

    # Try by canonical name
    result = client().table("players").select("*").eq(
        "canonical_name", canonical_name
    ).limit(1).execute()
    if result.data:
        return result.data[0]

    # Create new
    data = {"canonical_name": canonical_name}
    if dg_id:
        data["dg_id"] = dg_id

    result = client().table("players").insert(data).execute()
    return result.data[0] if result.data else {}


def add_player_alias(player_id: str, source: str, source_name: str) -> dict:
    """Add a name alias for a player at a specific book/source."""
    data = {
        "player_id": player_id,
        "source": source,
        "source_name": source_name,
    }
    result = client().table("player_aliases").upsert(
        data, on_conflict="source,source_name"
    ).execute()
    return result.data[0] if result.data else {}


def lookup_player_by_alias(source: str, source_name: str) -> dict | None:
    """Look up a player by their book-specific name."""
    result = client().table("player_aliases").select(
        "*, players(*)"
    ).eq("source", source).eq("source_name", source_name).limit(1).execute()

    if result.data:
        alias = result.data[0]
        return alias.get("players")
    return None


# ---- Book Rules ----

def get_book_rule(book: str, market_type: str) -> dict | None:
    """Look up settlement rules for a specific book and market."""
    result = client().table("book_rules").select("*").eq(
        "book", book
    ).eq("market_type", market_type).limit(1).execute()
    return result.data[0] if result.data else None


# ---- Analytics ----

def get_roi_by_market() -> list[dict]:
    """Query the v_roi_by_market view."""
    result = client().table("v_roi_by_market").select("*").execute()
    return result.data


def get_roi_by_book() -> list[dict]:
    """Query the v_roi_by_book view."""
    result = client().table("v_roi_by_book").select("*").execute()
    return result.data


def get_roi_by_edge_tier() -> list[dict]:
    """Query the v_roi_by_edge_tier view."""
    result = client().table("v_roi_by_edge_tier").select("*").execute()
    return result.data


def get_clv_weekly() -> list[dict]:
    """Query the v_clv_weekly view."""
    result = client().table("v_clv_weekly").select("*").execute()
    return result.data


def get_calibration() -> list[dict]:
    """Query the v_calibration view."""
    result = client().table("v_calibration").select("*").execute()
    return result.data


def get_bankroll_curve() -> list[dict]:
    """Query the v_bankroll_curve view."""
    result = client().table("v_bankroll_curve").select("*").execute()
    return result.data


def get_weekly_exposure() -> list[dict]:
    """Query the v_weekly_exposure view."""
    result = client().table("v_weekly_exposure").select("*").execute()
    return result.data


def get_roi_by_tranche() -> list[dict]:
    """Query the v_roi_by_tranche view."""
    result = client().table("v_roi_by_tranche").select("*").execute()
    return result.data


def get_book_attribution() -> list[dict]:
    """Query the v_book_attribution view."""
    result = client().table("v_book_attribution").select("*").execute()
    return result.data


def get_clv_by_tranche() -> list[dict]:
    """Query the v_clv_by_tranche view."""
    result = client().table("v_clv_by_tranche").select("*").execute()
    return result.data


def get_clv_coverage() -> list[dict]:
    """Query the v_clv_coverage view."""
    result = client().table("v_clv_coverage").select("*").execute()
    return result.data


def get_execution_slippage() -> list[dict]:
    """Query the v_execution_slippage view."""
    result = client().table("v_execution_slippage").select("*").execute()
    return result.data


def get_candidate_fill_rate() -> list[dict]:
    """Query the v_candidate_fill_rate view."""
    result = client().table("v_candidate_fill_rate").select("*").execute()
    return result.data
