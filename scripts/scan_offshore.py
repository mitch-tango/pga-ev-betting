#!/usr/bin/env python3
"""
Scan offshore sportsbook odds against DG simulation + book consensus.

Parses copy-pasted odds from an offshore book (matchups + placement markets)
and runs the full edge calculation pipeline against them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re
from src.core.devig import (
    parse_american_odds, american_to_decimal, decimal_to_american,
    devig_two_way, devig_independent,
)
from src.core.blend import (
    blend_probabilities, build_book_consensus, classify_tranche,
    get_blend_weights,
)
from src.core.kelly import kelly_stake, get_correlation_haircut
from src.core.settlement import adjust_edge_for_deadheat
import config


# ── Parsers ──────────────────────────────────────────────────────────────

def _clean_name(raw: str) -> str:
    """UPPERCASE -> Title Case, strip round indicators."""
    name = re.sub(r"\s*\(\d+\w{0,2}\)\s*$", "", raw.strip())
    parts = name.split()
    result = []
    for p in parts:
        up = p.upper()
        if up in ("II", "III", "IV", "JR", "JR.", "SR", "SR."):
            result.append(up)
        else:
            result.append(p.title())
    return " ".join(result)


def parse_matchups(text: str) -> list[dict]:
    """Parse offshore matchup text into pairs."""
    lines = text.splitlines()
    parsed = []
    for line in lines:
        m = re.search(
            r"(\d{4,5})\s+"
            r"(.+?)\s+"
            r"([+-]\d{2,4})\s*$",
            line.strip(),
        )
        if m:
            parsed.append({
                "number": int(m.group(1)),
                "name": _clean_name(m.group(2)),
                "odds": m.group(3),
            })

    matchups = []
    i = 0
    while i + 1 < len(parsed):
        p1, p2 = parsed[i], parsed[i + 1]
        if abs(p1["number"] - p2["number"]) == 1:
            matchups.append({
                "p1_name": p1["name"],
                "p2_name": p2["name"],
                "p1_odds": p1["odds"],
                "p2_odds": p2["odds"],
            })
            i += 2
        else:
            i += 1
    return matchups


def parse_placement_market(text: str) -> tuple[str, list[dict]]:
    """Parse a placement market (T10, T20, T40, MC, win) block.

    Returns (market_type, [{name, odds}, ...])
    """
    # Detect market type from header
    header_lower = text[:500].lower()
    if "odds to win" in header_lower:
        market_type = "win"
    elif "top 10" in header_lower:
        market_type = "t10"
    elif "top 20" in header_lower:
        market_type = "t20"
    elif "top 30" in header_lower:
        market_type = "t30"
    elif "top 40" in header_lower:
        market_type = "t40"
    elif "make the cut" in header_lower or "to make the cut" in header_lower:
        market_type = "make_cut"
    else:
        market_type = "unknown"

    players = []
    for line in text.splitlines():
        line_s = line.strip()
        m = re.search(
            r"\d{4,5}\s+"
            r"(.+?)\s+"
            r"([+-]\d{2,5})\s*$",
            line_s,
        )
        if m:
            name = _clean_name(m.group(1))
            odds = m.group(2)
            if name and odds:
                players.append({"name": name, "odds": odds})

    return market_type, players


# ── DG data pull ─────────────────────────────────────────────────────────

def pull_dg_data():
    """Pull fresh DG outrights + matchups."""
    from src.pipeline.pull_outrights import pull_all_outrights
    from src.pipeline.pull_matchups import pull_tournament_matchups

    print("Pulling DG outrights...")
    outrights = pull_all_outrights("masters-2026", "pga")

    if outrights.get("_is_live"):
        print(f"  WARNING: Tournament is LIVE — DG baseline may be stale")
        print(f"  Notes: {outrights.get('_notes', 'n/a')}")

    for market, data in outrights.items():
        if not market.startswith("_"):
            print(f"  {market}: {len(data) if isinstance(data, list) else 0} players")

    print("Pulling DG matchups...")
    matchups = pull_tournament_matchups("masters-2026", "pga")
    print(f"  Matchups: {len(matchups)}")

    return outrights, matchups


def build_dg_lookup(outrights: dict, market: str) -> dict[str, dict]:
    """Build name -> {dg_prob, dg_id, field_rank} lookup from DG outrights."""
    data = outrights.get(market, [])
    if not isinstance(data, list):
        return {}

    lookup = {}
    for i, player in enumerate(data):
        name = player.get("player_name", "").strip().strip('"')
        dg_id = str(player.get("dg_id", ""))
        dg_data = player.get("datagolf", {})
        if isinstance(dg_data, dict):
            dg_odds_str = str(dg_data.get("baseline_history_fit") or
                              dg_data.get("baseline") or "")
        else:
            dg_odds_str = str(dg_data or "")
        dg_prob = parse_american_odds(dg_odds_str)

        # Book consensus from all books in DG data
        book_probs = {}
        SKIP = {"player_name", "dg_id", "datagolf", "dk_salary", "dk_ownership",
                "early_late", "tee_time", "r1_teetime", "event_name"}
        for key in player.keys():
            if key in SKIP or key.startswith("_"):
                continue
            val = player[key]
            if isinstance(val, str) and (val.startswith("+") or val.startswith("-")):
                bp = parse_american_odds(val)
                if bp and bp > 0:
                    book_probs[key] = bp

        if dg_prob and dg_prob > 0:
            lookup[normalize_name(name)] = {
                "dg_prob": dg_prob,
                "dg_id": dg_id,
                "field_rank": i + 1,
                "book_probs": book_probs,
                "raw_player": player,
            }
    return lookup


def build_dg_matchup_lookup(matchups: list[dict]) -> dict[str, dict]:
    """Build (p1_normalized, p2_normalized) -> matchup lookup from DG matchups."""
    lookup = {}
    for m in matchups:
        p1 = normalize_name(m.get("p1_player_name", ""))
        p2 = normalize_name(m.get("p2_player_name", ""))
        if p1 and p2:
            lookup[(p1, p2)] = m
            lookup[(p2, p1)] = m  # Both orderings
    return lookup


# ── Name matching ────────────────────────────────────────────────────────

ALIASES = {
    "sung-jae im": "sungjae im",
    "sung jae im": "sungjae im",
    "sungjae im": "sungjae im",
    "si woo kim": "si woo kim",
    "j.j. spaun": "j.j. spaun",
    "jj spaun": "j.j. spaun",
    "rasmus neergaard petersen": "rasmus neergaard-petersen",
    "rasmus neergaard-petersen": "rasmus neergaard-petersen",
    "johnny keefer": "john keefer",
    "john keefer": "john keefer",
    "haotong li": "haotong li",
}


def normalize_name(name: str) -> str:
    """Normalize player name for matching.

    Handles both 'First Last' and 'Last, First' formats.
    """
    n = name.lower().strip()
    # Convert "Last, First" -> "first last"
    if "," in n:
        parts = n.split(",", 1)
        n = f"{parts[1].strip()} {parts[0].strip()}"
    return ALIASES.get(n, n)


def find_in_lookup(name: str, lookup: dict) -> dict | None:
    """Find player in DG lookup with fuzzy matching."""
    n = normalize_name(name)
    if n in lookup:
        return lookup[n]
    # Try partial match (last name + first name)
    for key, val in lookup.items():
        if n == key:
            return val
    # Fuzzy: check if all parts of one name appear in the other
    n_parts = set(n.split())
    for key, val in lookup.items():
        k_parts = set(key.split())
        if n_parts == k_parts:
            return val
        # At least last name + first name match
        if len(n_parts & k_parts) >= 2:
            return val
    return None


# ── Matchup Edge Calculation ────────────────────────────────────────────

DISPLAY_MIN_EDGE = config.DISPLAY_MIN_EDGE

# ANSI color codes for terminal output
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def scan_matchups(offshore_matchups, dg_matchup_lookup, dg_win_lookup, bankroll):
    """Scan offshore matchups for edges."""
    results = []
    bet_min_edge = config.MIN_EDGE.get("tournament_matchup", 0.05)

    for mu in offshore_matchups:
        p1_name = mu["p1_name"]
        p2_name = mu["p2_name"]
        p1_odds = mu["p1_odds"]
        p2_odds = mu["p2_odds"]

        # Find DG matchup
        p1_n = normalize_name(p1_name)
        p2_n = normalize_name(p2_name)
        dg_mu = dg_matchup_lookup.get((p1_n, p2_n))

        if not dg_mu:
            # Try reverse
            dg_mu = dg_matchup_lookup.get((p2_n, p1_n))

        if not dg_mu:
            continue

        # DG probabilities
        odds_dict = dg_mu.get("odds", {})
        dg_odds = odds_dict.get("datagolf", {})

        # Figure out which DG player maps to which offshore player
        dg_p1_name = dg_mu.get("p1_player_name", "").lower()
        dg_p2_name = dg_mu.get("p2_player_name", "").lower()

        if normalize_name(dg_p1_name) == p1_n or dg_p1_name == p1_n:
            dg_p1_str = str(dg_odds.get("p1", ""))
            dg_p2_str = str(dg_odds.get("p2", ""))
            swapped = False
        elif normalize_name(dg_p2_name) == p1_n or dg_p2_name == p1_n:
            dg_p1_str = str(dg_odds.get("p2", ""))
            dg_p2_str = str(dg_odds.get("p1", ""))
            swapped = True
        else:
            continue

        dg_p1_raw = parse_american_odds(dg_p1_str)
        dg_p2_raw = parse_american_odds(dg_p2_str)
        if not dg_p1_raw or not dg_p2_raw:
            continue

        dg_p1_fair, dg_p2_fair = devig_two_way(dg_p1_raw, dg_p2_raw)
        if not dg_p1_fair or dg_p1_fair <= 0:
            continue

        # Book consensus from DG's other books
        book_p1_probs = {}
        for book_name, book_odds in odds_dict.items():
            if book_name == "datagolf":
                continue
            if swapped:
                bp1_raw = parse_american_odds(str(book_odds.get("p2", "")))
                bp2_raw = parse_american_odds(str(book_odds.get("p1", "")))
            else:
                bp1_raw = parse_american_odds(str(book_odds.get("p1", "")))
                bp2_raw = parse_american_odds(str(book_odds.get("p2", "")))

            if bp1_raw and bp2_raw:
                bp1_fair, _ = devig_two_way(bp1_raw, bp2_raw)
                if bp1_fair and bp1_fair > 0:
                    book_p1_probs[book_name] = bp1_fair

        if not book_p1_probs:
            book_consensus_p1 = None
        else:
            book_consensus_p1 = sum(book_p1_probs.values()) / len(book_p1_probs)

        # Tranche
        p1_win = (find_in_lookup(p1_name, dg_win_lookup) or {}).get("dg_prob", 0)
        p2_win = (find_in_lookup(p2_name, dg_win_lookup) or {}).get("dg_prob", 0)
        tranche = classify_tranche(max(p1_win, p2_win)) if (p1_win or p2_win) else None

        # Blend
        weights = get_blend_weights("tournament_matchup", tranche=tranche)
        if book_consensus_p1 is not None:
            your_p1 = weights["dg"] * dg_p1_fair + weights["books"] * book_consensus_p1
        else:
            your_p1 = dg_p1_fair
        your_p2 = 1 - your_p1

        # De-vig offshore line
        off_p1_raw = parse_american_odds(p1_odds)
        off_p2_raw = parse_american_odds(p2_odds)
        if not off_p1_raw or not off_p2_raw:
            continue
        off_p1_fair, off_p2_fair = devig_two_way(off_p1_raw, off_p2_raw)

        # Check both sides
        for side_name, your_prob, off_fair, off_odds_str, opp_name in [
            (p1_name, your_p1, off_p1_fair, p1_odds, p2_name),
            (p2_name, your_p2, off_p2_fair, p2_odds, p1_name),
        ]:
            if not off_fair or off_fair <= 0:
                continue
            edge = your_prob - off_fair
            if edge < DISPLAY_MIN_EDGE:
                continue

            dec = american_to_decimal(off_odds_str)
            if not dec or dec <= 1:
                continue

            stake = kelly_stake(edge, dec, bankroll) if edge >= bet_min_edge else 0.0

            results.append({
                "player": side_name,
                "opponent": opp_name,
                "market": "matchup",
                "offshore_odds": off_odds_str,
                "offshore_decimal": dec,
                "offshore_implied": off_fair,
                "dg_prob": your_prob if side_name == p1_name else (1 - your_p1 if side_name == p2_name else 0),
                "your_prob": your_prob,
                "book_consensus": book_consensus_p1 if side_name == p1_name else (1 - book_consensus_p1 if book_consensus_p1 else None),
                "edge": edge,
                "bet_min_edge": bet_min_edge,
                "qualifies": edge >= bet_min_edge,
                "kelly_stake": stake,
                "tranche": tranche,
            })

    results.sort(key=lambda r: r["edge"], reverse=True)
    return results


# ── Placement Edge Calculation ──────────────────────────────────────────

def scan_placement(offshore_players, market_type, dg_lookup, dg_win_lookup, bankroll,
                    mc_expected=None):
    """Scan offshore placement odds for edges."""
    results = []
    bet_min_edge = config.MIN_EDGE.get(market_type, 0.05)

    # Map our market types to DG expected finishers
    expected_map = {"t10": 10, "t20": 20, "t30": 30, "t40": 40, "win": 1}
    if market_type == "make_cut":
        # Use DG model sum if provided, else fall back to 65
        expected = mc_expected if mc_expected else 65
    else:
        expected = expected_map.get(market_type, 20)

    # De-vig the offshore field
    raw_probs = []
    for p in offshore_players:
        prob = parse_american_odds(p["odds"])
        raw_probs.append(prob)

    valid_count = sum(1 for p in raw_probs if p is not None and p > 0)
    if valid_count < 10:
        return []

    if market_type == "win":
        from src.core.devig import power_devig
        devigged = power_devig(raw_probs)
    else:
        devigged = devig_independent(raw_probs, expected, len(offshore_players))

    for i, player in enumerate(offshore_players):
        name = player["name"]
        off_odds = player["odds"]

        if devigged[i] is None or devigged[i] <= 0:
            continue

        off_fair = devigged[i]
        off_decimal = american_to_decimal(off_odds)
        if not off_decimal or off_decimal <= 1:
            continue

        # Find DG data - use correct market lookup
        dg_market_key = {"t10": "top_10", "t20": "top_20", "t30": "top_30",
                         "t40": "top_40", "make_cut": "make_cut", "win": "win"}.get(market_type, market_type)
        dg_info = find_in_lookup(name, dg_lookup)
        if not dg_info:
            continue

        dg_prob = dg_info["dg_prob"]
        field_rank = dg_info["field_rank"]

        # Tranche from win probs
        win_info = find_in_lookup(name, dg_win_lookup)
        win_prob = win_info["dg_prob"] if win_info else 0
        tranche = classify_tranche(win_prob) if win_prob > 0 else None

        # Book consensus from DG's other book odds
        book_probs = dg_info.get("book_probs", {})
        if book_probs:
            bc = build_book_consensus(book_probs, market_type)
        else:
            bc = None

        # Blend
        your_prob = blend_probabilities(
            dg_prob, bc, market_type,
            player_field_rank=field_rank,
            tranche=tranche,
        )
        if not your_prob or your_prob <= 0:
            continue

        # Edge vs offshore de-vigged fair line
        raw_edge = your_prob - off_fair

        # Dead-heat adjustment for placement markets
        if market_type in ("t10", "t20"):
            adj_edge, dh_adj = adjust_edge_for_deadheat(raw_edge, market_type, off_decimal)
        else:
            adj_edge = raw_edge
            dh_adj = 0.0

        if adj_edge < DISPLAY_MIN_EDGE:
            continue

        stake = kelly_stake(adj_edge, off_decimal, bankroll) if adj_edge >= bet_min_edge else 0.0

        results.append({
            "player": name,
            "opponent": None,
            "market": market_type,
            "offshore_odds": off_odds,
            "offshore_decimal": off_decimal,
            "offshore_implied": off_fair,
            "dg_prob": dg_prob,
            "your_prob": your_prob,
            "book_consensus": bc,
            "edge": adj_edge,
            "raw_edge": raw_edge,
            "dh_adj": dh_adj,
            "bet_min_edge": bet_min_edge,
            "qualifies": adj_edge >= bet_min_edge,
            "kelly_stake": stake,
            "tranche": tranche,
        })

    results.sort(key=lambda r: r["edge"], reverse=True)
    return results


# ── Main ────────────────────────────────────────────────────────────────

def main():
    bankroll = 3587.0  # From the sportsbook balance shown

    # Read offshore odds file
    odds_file = Path(__file__).parent.parent / "data/raw/masters-2026/offshore_odds.txt"
    offshore_text = odds_file.read_text()

    # Pull DG data
    outrights, dg_matchups = pull_dg_data()

    # Build lookups
    dg_win_lookup = build_dg_lookup(outrights, "win")
    dg_matchup_lookup = build_dg_matchup_lookup(dg_matchups)

    print(f"\nDG win lookup: {len(dg_win_lookup)} players")
    print(f"DG matchup lookup: {len(dg_matchup_lookup) // 2} matchups")

    # Parse offshore matchups
    offshore_matchups = parse_matchups(offshore_text)
    print(f"Offshore matchups parsed: {len(offshore_matchups)}")

    # Debug: show sample DG matchup names
    if dg_matchups:
        sample_keys = list(dg_matchup_lookup.keys())[:6]
        print(f"  Sample DG matchup keys: {sample_keys}")

    all_results = []

    # ── Matchup scan ──
    print("\n=== MATCHUP SCAN ===")
    matchup_results = scan_matchups(
        offshore_matchups, dg_matchup_lookup, dg_win_lookup, bankroll
    )
    all_results.extend(matchup_results)

    # ── Placement market scans ──
    # Parse the full text for each placement market section
    # Split the input by major section headers
    placement_texts = {
        "win": "",
        "t10": "",
        "t20": "",
        "t30": "",
        "t40": "",
        "make_cut": "",
    }

    # We need the full odds text including placement markets
    # Read from the user's pasted data (stored separately)
    full_odds_file = Path(__file__).parent.parent / "data/raw/masters-2026/offshore_full_odds.txt"
    if full_odds_file.exists():
        full_text = full_odds_file.read_text()
    else:
        full_text = ""

    if full_text:
        # Split into sections based on PGA headers
        sections = re.split(r"(?=PGA - THE MASTERS -)", full_text)
        for section in sections:
            if not section.strip():
                continue
            mtype, players = parse_placement_market(section)
            if mtype != "unknown" and players:
                placement_texts[mtype] = section

                # Build DG lookup for this specific market
                dg_market_key = {"t10": "top_10", "t20": "top_20",
                                 "make_cut": "make_cut", "win": "win"}.get(mtype)
                if dg_market_key:
                    dg_mkt_lookup = build_dg_lookup(outrights, dg_market_key)
                else:
                    dg_mkt_lookup = dg_win_lookup

                # For make_cut, compute event-specific expected outcomes from DG model
                mc_exp = None
                if mtype == "make_cut" and dg_market_key:
                    mc_data = outrights.get(dg_market_key, [])
                    if isinstance(mc_data, list):
                        mc_exp = sum(
                            p for p in (
                                parse_american_odds(
                                    str((pl.get("datagolf", {}) or {}).get("baseline_history_fit") or
                                        (pl.get("datagolf", {}) or {}).get("baseline") or "")
                                ) for pl in mc_data
                            ) if p is not None and p > 0
                        ) or None

                print(f"\n=== {mtype.upper()} SCAN ({len(players)} players) ===")
                placement_results = scan_placement(
                    players, mtype, dg_mkt_lookup, dg_win_lookup, bankroll,
                    mc_expected=mc_exp,
                )
                all_results.extend(placement_results)

    # ── Display results ──
    print(f"\n{'='*94}")
    print(f"  OFFSHORE SPORTSBOOK SCAN — THE MASTERS 2026")
    print(f"  Bankroll: ${bankroll:.0f} | Display floor: {DISPLAY_MIN_EDGE*100:.0f}% edge")
    print(f"  Bet thresholds: " + ", ".join(
        f"{k}={v*100:.0f}%" for k, v in config.MIN_EDGE.items()
    ))
    print(f"  ✓ = edge clears bet threshold (size via Kelly) · · = below threshold (info only)")
    print(f"{'='*94}")

    if not all_results:
        print("\n  No +EV opportunities found above 1% edge.")
        return

    all_results.sort(key=lambda r: r["edge"], reverse=True)

    qualifying = sum(1 for r in all_results if r.get("qualifies"))
    print(f"\n  {len(all_results)} +EV opportunities (≥1% edge); {qualifying} clear bet threshold:\n")
    print(f"  {'':<2} {'#':>3}  {'Player':<22} {'vs':<16} {'Market':<8} "
          f"{'Odds':>7} {'Your%':>6} {'Off%':>6} {'Edge':>6} {'Min':>5} "
          f"{'Stake':>6} {'Tranche':<8}")
    print(f"  {'—'*2} {'—'*3}  {'—'*22} {'—'*16} {'—'*8} {'—'*7} {'—'*6} {'—'*6} "
          f"{'—'*6} {'—'*5} {'—'*6} {'—'*8}")

    for i, r in enumerate(all_results, 1):
        opp = r.get("opponent") or ""
        opp_display = opp[:16] if opp else "—"
        tranche = r.get("tranche") or "—"
        qualifies = r.get("qualifies", False)
        mark = f"{GREEN}✓{RESET}" if qualifies else f"{DIM}·{RESET}"
        bet_min = r.get("bet_min_edge", 0) * 100
        stake_str = f"${r['kelly_stake']:>4.0f}" if qualifies else "   —"
        edge_color = GREEN if qualifies else YELLOW
        edge_str = f"{edge_color}{r['edge']*100:>5.1f}%{RESET}"
        print(f"  {mark}  {i:>3}  {r['player']:<22} {opp_display:<16} {r['market']:<8} "
              f"{r['offshore_odds']:>7} {r['your_prob']*100:>5.1f}% "
              f"{r['offshore_implied']*100:>5.1f}% {edge_str} "
              f"{bet_min:>4.0f}% {stake_str:>6} {tranche:<8}")


if __name__ == "__main__":
    main()
