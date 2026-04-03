from __future__ import annotations

"""
Player name normalization across DataGolf and sportsbooks.

Handles the reality that "Hideki Matsuyama" in DG might be
"H. Matsuyama" on DraftKings and "Matsuyama, Hideki" on Bovada.

Uses a players table (canonical names) + player_aliases table
(source-specific mappings) in Supabase. Falls back to fuzzy
matching when an exact alias isn't found.
"""

import re
from difflib import SequenceMatcher

from src.db import supabase_client as db


def normalize_name(name: str) -> str:
    """Basic name normalization: strip, collapse whitespace, title case.

    Does NOT try to be clever about name formats — just cleans up
    the raw string for comparison.
    """
    if not name:
        return ""
    # Strip quotes, whitespace
    name = name.strip().strip('"').strip("'")
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)
    # Remove trailing/leading punctuation
    name = name.strip(".,;:")
    return name


def _name_parts(name: str) -> tuple[str, str]:
    """Split a name into (first, last) handling various formats.

    Handles:
        "Hideki Matsuyama" -> ("hideki", "matsuyama")
        "H. Matsuyama"     -> ("h", "matsuyama")
        "Matsuyama, Hideki" -> ("hideki", "matsuyama")
        "Matsuyama"         -> ("", "matsuyama")
    """
    name = normalize_name(name).lower()

    # "Last, First" format
    if "," in name:
        parts = name.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ""
        return (first, last)

    parts = name.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    elif len(parts) == 1:
        return ("", parts[0])
    return ("", "")


def _names_match(name_a: str, name_b: str) -> float:
    """Score how well two player names match (0.0 to 1.0).

    Uses last-name exact match + first-name fuzzy matching to handle
    "Hideki" vs "H." cases.
    """
    first_a, last_a = _name_parts(name_a)
    first_b, last_b = _name_parts(name_b)

    # Last names must match (exact or very close)
    if last_a != last_b:
        last_sim = SequenceMatcher(None, last_a, last_b).ratio()
        if last_sim < 0.85:
            return 0.0
        # Close but not exact last name (e.g., typo)
        last_score = last_sim
    else:
        last_score = 1.0

    # First name matching
    if not first_a or not first_b:
        # One name is missing first name — last name match is enough
        first_score = 0.7
    elif first_a == first_b:
        first_score = 1.0
    elif first_a[0] == first_b[0]:
        # First initial matches (e.g., "H." vs "Hideki")
        if len(first_a) <= 2 or len(first_b) <= 2:
            first_score = 0.85  # Initial match
        else:
            first_score = SequenceMatcher(None, first_a, first_b).ratio()
    else:
        first_score = SequenceMatcher(None, first_a, first_b).ratio()

    # Weight: 60% last name, 40% first name
    return 0.6 * last_score + 0.4 * first_score


def resolve_player(name: str, source: str,
                   dg_id: str | None = None,
                   auto_create: bool = True) -> dict | None:
    """Resolve a player name from a specific source to a canonical player record.

    Lookup order:
    1. Exact alias match (source + source_name)
    2. DG ID match (if provided)
    3. Exact canonical name match
    4. Fuzzy match against existing players (threshold > 0.85)
    5. Auto-create new player (if auto_create=True)

    Args:
        name: player name as it appears in the source
        source: data source ("datagolf", "draftkings", "fanduel", etc.)
        dg_id: DataGolf player ID (if available)
        auto_create: create new player if not found

    Returns:
        player dict from database, or None if not found and auto_create=False
    """
    clean_name = normalize_name(name)
    if not clean_name:
        return None

    # 1. Exact alias lookup
    player = db.lookup_player_by_alias(source, clean_name)
    if player:
        return player

    # 2. DG ID lookup
    if dg_id:
        player = db.get_or_create_player(clean_name, dg_id=dg_id)
        # Also save this source alias for future lookups
        db.add_player_alias(player["id"], source, clean_name)
        return player

    # 3. Exact canonical name match
    from supabase import create_client
    sb = db.client()
    result = sb.table("players").select("*").eq(
        "canonical_name", clean_name
    ).limit(1).execute()
    if result.data:
        player = result.data[0]
        db.add_player_alias(player["id"], source, clean_name)
        return player

    # 4. Fuzzy match against existing players
    all_players = sb.table("players").select("id, canonical_name").execute()
    best_match = None
    best_score = 0.0

    for candidate in all_players.data:
        score = _names_match(clean_name, candidate["canonical_name"])
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_match and best_score >= 0.85:
        # Get full record
        full = sb.table("players").select("*").eq(
            "id", best_match["id"]
        ).limit(1).execute()
        if full.data:
            player = full.data[0]
            # Save alias for future fast lookups
            db.add_player_alias(player["id"], source, clean_name)
            return player

    # 5. Auto-create
    if auto_create:
        player = db.get_or_create_player(clean_name)
        db.add_player_alias(player["id"], source, clean_name)
        return player

    return None


def bulk_resolve_players(names_with_source: list[dict],
                         auto_create: bool = True) -> dict[str, dict]:
    """Resolve multiple player names in batch.

    Args:
        names_with_source: list of {"name": str, "source": str, "dg_id": str|None}

    Returns:
        {"original_name": player_dict, ...}
    """
    results = {}
    for entry in names_with_source:
        player = resolve_player(
            name=entry["name"],
            source=entry["source"],
            dg_id=entry.get("dg_id"),
            auto_create=auto_create,
        )
        results[entry["name"]] = player
    return results


def resolve_candidates(candidates: list, source: str = "datagolf") -> list:
    """Resolve player names on a list of CandidateBet objects.

    Sets player_id, opponent_id, opponent_2_id on each candidate
    by looking up (or creating) canonical player records via the
    players + player_aliases tables.

    This builds the alias database over time — each new name
    from a source gets recorded for instant future lookup.

    Args:
        candidates: list of CandidateBet dataclass instances
        source: data source for these names (default "datagolf")

    Returns:
        The same list, mutated with player IDs set.
    """
    # Collect unique names to resolve
    names_to_resolve = {}
    for c in candidates:
        key = (c.player_name, c.player_dg_id)
        if key not in names_to_resolve:
            names_to_resolve[key] = {"name": c.player_name, "source": source,
                                      "dg_id": c.player_dg_id}
        if c.opponent_name:
            okey = (c.opponent_name, c.opponent_dg_id)
            if okey not in names_to_resolve:
                names_to_resolve[okey] = {"name": c.opponent_name, "source": source,
                                           "dg_id": c.opponent_dg_id}
        if c.opponent_2_name:
            o2key = (c.opponent_2_name, c.opponent_2_dg_id)
            if o2key not in names_to_resolve:
                names_to_resolve[o2key] = {"name": c.opponent_2_name, "source": source,
                                            "dg_id": c.opponent_2_dg_id}

    # Resolve all unique names
    resolved = {}
    for key, entry in names_to_resolve.items():
        player = resolve_player(
            name=entry["name"], source=entry["source"],
            dg_id=entry.get("dg_id"), auto_create=True,
        )
        if player:
            resolved[key] = player["id"]

    # Assign IDs back to candidates
    for c in candidates:
        c.player_id = resolved.get((c.player_name, c.player_dg_id))
        if c.opponent_name:
            c.opponent_id = resolved.get((c.opponent_name, c.opponent_dg_id))
        if c.opponent_2_name:
            c.opponent_2_id = resolved.get((c.opponent_2_name, c.opponent_2_dg_id))

    return candidates
