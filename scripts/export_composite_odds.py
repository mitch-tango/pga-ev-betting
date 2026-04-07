#!/usr/bin/env python3
from __future__ import annotations

"""
Export composite de-vigged odds for all players across W, T10, T20, Make Cut.

Pulls current odds from DG API, de-vigs each book, builds weighted book
consensus, blends with DG model, and writes a CSV.

Usage:
    python scripts/export_composite_odds.py [--tour pga] [--output odds.csv]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
from collections import defaultdict

from src.pipeline.pull_outrights import pull_all_outrights
from src.core.devig import parse_american_odds, power_devig, devig_independent
from src.core.blend import build_book_consensus, blend_probabilities, classify_tranche
import config


MARKET_MAP = {
    "win": "win",
    "top_10": "t10",
    "top_20": "t20",
    "make_cut": "make_cut",
}

SKIP_KEYS = {
    "player_name", "dg_id", "datagolf", "dk_salary", "dk_ownership",
    "early_late", "tee_time", "r1_teetime", "event_name",
}


def compute_composite_probs(outrights_data: list[dict], market_type: str,
                            win_outrights_data: list[dict] | None = None,
                            ) -> dict[str, dict]:
    """Compute DG, book consensus, and blended probs for every player.

    Returns {player_name: {"dg_id": ..., "dg_prob": ..., "book_consensus": ..., "composite": ...}}
    """
    if not isinstance(outrights_data, list) or not outrights_data:
        return {}

    # Build win-prob lookup for tranche classification
    player_win_probs = {}
    win_source = win_outrights_data if market_type != "win" else outrights_data
    if win_source and isinstance(win_source, list):
        for p in win_source:
            dg_id = str(p.get("dg_id", ""))
            dg_data = p.get("datagolf", {})
            if isinstance(dg_data, dict):
                odds_str = str(dg_data.get("baseline_history_fit") or
                               dg_data.get("baseline") or "")
            else:
                odds_str = str(dg_data or "")
            prob = parse_american_odds(odds_str)
            if prob and prob > 0:
                player_win_probs[dg_id] = prob

    # Identify books in data
    books_in_data = set()
    for player in outrights_data:
        for key in player.keys():
            if key in SKIP_KEYS:
                continue
            val = player[key]
            if isinstance(val, str) and (val.startswith("+") or val.startswith("-")):
                books_in_data.add(key)

    # For make_cut, compute expected outcomes from DG model
    mc_expected = 65
    if market_type == "make_cut":
        dg_mc_sum = 0.0
        for player in outrights_data:
            dg_data = player.get("datagolf", {})
            if isinstance(dg_data, dict):
                dg_odds_str = str(dg_data.get("baseline_history_fit") or
                                  dg_data.get("baseline") or "")
            else:
                dg_odds_str = str(dg_data or "")
            dg_p = parse_american_odds(dg_odds_str)
            if dg_p is not None and dg_p > 0:
                dg_mc_sum += dg_p
        if dg_mc_sum > 0:
            mc_expected = dg_mc_sum

    # De-vig each book's full field
    book_devigged = {}
    for book in books_in_data:
        raw_probs = []
        for player in outrights_data:
            odds_str = str(player.get(book, ""))
            p = parse_american_odds(odds_str)
            raw_probs.append(p)

        valid_count = sum(1 for p in raw_probs if p is not None and p > 0)
        if valid_count >= 10:
            if market_type == "win":
                devigged = power_devig(raw_probs)
            else:
                expected = {"t5": 5, "t10": 10, "t20": 20}.get(market_type, 20)
                if market_type == "make_cut":
                    expected = mc_expected
                devigged = devig_independent(raw_probs, expected, len(raw_probs))
            book_devigged[book] = devigged

    # For each player, compute composite probability
    results = {}
    for i, player in enumerate(outrights_data):
        player_name = player.get("player_name", "").strip().strip('"')
        dg_id = str(player.get("dg_id", ""))
        field_rank = i + 1

        dg_data = player.get("datagolf", {})
        if isinstance(dg_data, dict):
            dg_odds_str = str(dg_data.get("baseline_history_fit") or
                              dg_data.get("baseline") or "")
        else:
            dg_odds_str = str(dg_data or "")
        dg_prob = parse_american_odds(dg_odds_str)
        if dg_prob is None or dg_prob <= 0:
            continue

        # Book consensus
        player_book_probs = {}
        for book, devigged_list in book_devigged.items():
            if i < len(devigged_list) and devigged_list[i] is not None:
                player_book_probs[book] = devigged_list[i]

        book_consensus = build_book_consensus(player_book_probs, market_type)

        # Tranche classification
        player_tranche = None
        player_win_prob = player_win_probs.get(dg_id, 0)
        if player_win_prob > 0:
            player_tranche = classify_tranche(player_win_prob)

        # Blended composite
        composite = blend_probabilities(
            dg_prob, book_consensus, market_type,
            player_field_rank=field_rank,
            tranche=player_tranche,
        )

        results[player_name] = {
            "dg_id": dg_id,
            "dg_prob": round(dg_prob, 6),
            "book_consensus": round(book_consensus, 6) if book_consensus else None,
            "composite": round(composite, 6) if composite else None,
        }

    return results


def _compute_coursefit_signals_for_field(
    event_name: str,
    tournament_slug: str | None,
    all_players: dict[str, dict],
) -> dict[str, str]:
    """Pull Betsperts SG data and compute coursefit signal for every player.

    Returns {player_name: signal_label} where label is [++], [+], [-], [--], [?].
    """
    from src.core.coursefit import (
        pull_coursefit_data, match_betsperts_to_dg,
        _classify_agreement, _PROFILES, _DEFAULT_PROFILE,
        _FORM_MIN_ROUNDS, _BASELINE_MIN_ROUNDS,
        SIGNAL_LABELS,
    )

    if not getattr(config, "BETSPERTS_ENABLED", False):
        print("  Betsperts: disabled")
        return {}

    print("Pulling Betsperts course-fit data...")
    try:
        coursefit_raw = pull_coursefit_data(event_name, tournament_slug)
    except Exception as e:
        print(f"  Warning: Betsperts unavailable ({e})")
        return {}

    if not coursefit_raw:
        print("  Betsperts: no coursefit data returned")
        return {}

    print(f"  Betsperts: {len(coursefit_raw)} players with SG data")

    dg_names = list(all_players.keys())
    matched = match_betsperts_to_dg(list(coursefit_raw.values()), dg_names)

    # Rank all players by composite score
    all_composite = [
        (name, d["sg_composite"])
        for name, d in coursefit_raw.items()
        if d.get("sg_composite") is not None
    ]
    all_composite.sort(key=lambda x: x[1], reverse=True)
    field_size = len(all_composite)
    composite_rank_map = {name: rank + 1 for rank, (name, _) in enumerate(all_composite)}

    # Build DG win probability rank from all_players
    dg_win_probs = {
        name: data.get("win_composite") or data.get("win_dg") or 0
        for name, data in all_players.items()
    }
    dg_sorted = sorted(dg_win_probs.items(), key=lambda x: x[1], reverse=True)
    dg_field_size = len(dg_sorted)
    dg_rank_map = {name: rank + 1 for rank, (name, _) in enumerate(dg_sorted)}

    signals = {}
    for dg_name in dg_names:
        bp_record = matched.get(dg_name)
        if not bp_record:
            continue

        bp_name = bp_record["playerName"]
        form_rounds = bp_record.get("form_rounds")
        baseline_rounds = bp_record.get("baseline_rounds")
        composite = bp_record.get("sg_composite")
        composite_rank = composite_rank_map.get(bp_name)

        form_ok = form_rounds is not None and form_rounds >= _FORM_MIN_ROUNDS
        baseline_ok = baseline_rounds is not None and baseline_rounds >= _BASELINE_MIN_ROUNDS

        if not form_ok or not baseline_ok:
            signals[dg_name] = SIGNAL_LABELS.get("low_sample", "[?]")
            continue

        if composite is None or composite_rank is None:
            continue

        dg_rank = dg_rank_map.get(dg_name)
        if dg_rank is None:
            continue

        sg_pct = (composite_rank - 1) / max(field_size - 1, 1)
        dg_pct = (dg_rank - 1) / max(dg_field_size - 1, 1)
        signal = _classify_agreement(sg_pct, dg_pct)
        signals[dg_name] = SIGNAL_LABELS.get(signal, "")

    enriched = sum(1 for v in signals.values() if v)
    print(f"  Course-fit: {enriched}/{len(dg_names)} players classified")
    return signals


def main():
    parser = argparse.ArgumentParser(description="Export composite de-vigged odds")
    parser.add_argument("--tour", default="pga", help="Tour (default: pga)")
    parser.add_argument("--tournament", default=None, help="Tournament slug")
    parser.add_argument("--output", "-o", default=None,
                        help="Output CSV path (default: composite_odds_<event>.csv)")
    parser.add_argument("--no-coursefit", action="store_true",
                        help="Skip Betsperts coursefit pull")
    args = parser.parse_args()

    print("Pulling outright odds from DG API...")
    outrights = pull_all_outrights(args.tournament, args.tour)

    event_name = outrights.get("_event_name", "unknown")
    print(f"Event: {event_name}")

    if outrights.get("_is_live"):
        print("Warning: tournament is LIVE — DG baseline model may not be available.")

    # Compute composite probs for each market
    all_players = defaultdict(lambda: {"dg_id": ""})

    win_data = outrights.get("win", [])

    for dg_market, our_market in MARKET_MAP.items():
        data = outrights.get(dg_market, [])
        if not data:
            print(f"  {our_market}: no data")
            continue

        probs = compute_composite_probs(
            data, our_market,
            win_outrights_data=win_data if our_market != "win" else None,
        )
        print(f"  {our_market}: {len(probs)} players")

        for player_name, info in probs.items():
            all_players[player_name]["dg_id"] = info["dg_id"]
            all_players[player_name][f"{our_market}_dg"] = info["dg_prob"]
            all_players[player_name][f"{our_market}_book_consensus"] = info["book_consensus"]
            all_players[player_name][f"{our_market}_composite"] = info["composite"]

    # Pull coursefit signals
    coursefit_signals = {}
    if not args.no_coursefit:
        coursefit_signals = _compute_coursefit_signals_for_field(
            event_name, args.tournament, all_players,
        )

    # Pull expert pick signals from cached content + transcript files
    expert_signal_map = {}
    tournament_slug = args.tournament or event_name.lower().replace(" ", "-").replace("'", "")
    print("Loading expert picks...")
    try:
        from pathlib import Path
        from src.api.experts import fetch_all_expert_content, ExpertContent
        from src.core.expert_picks import extract_all_picks, compute_expert_signals, SIGNAL_LABELS

        content = fetch_all_expert_content(event_name, tournament_slug=tournament_slug)

        # Also load YouTube transcripts from experts/<slug>/ directory
        experts_dir = Path("experts/masters")
        if not experts_dir.exists():
            # Try slug-based path
            slug = event_name.lower().replace(" ", "-").replace("'", "")
            experts_dir = Path("experts") / slug
        if experts_dir.exists():
            for tf in sorted(experts_dir.iterdir()):
                if tf.is_file() and not tf.name.startswith("."):
                    text = tf.read_text(encoding="utf-8", errors="replace")
                    if len(text) < 200:
                        continue
                    source = tf.stem.replace("yt-", "youtube:")
                    content.append(ExpertContent(
                        source=source,
                        author=source,
                        title=tf.stem,
                        url="",
                        text=text,
                        published_date="2026-04-07",
                        content_type="youtube_transcript" if "yt-" in tf.name else "article",
                    ))
                    print(f"  Loaded transcript: {tf.name} ({len(text):,} chars)")

        if content:
            print(f"  Expert content: {len(content)} sources total")
            picks = extract_all_picks(content)
            if picks:
                print(f"  Extracted {len(picks)} picks via Claude")
                field_names = list(all_players.keys())
                signals = compute_expert_signals(picks, field_names)
                for player_name, sig in signals.items():
                    expert_signal_map[player_name] = SIGNAL_LABELS.get(sig["signal"], "")
                print(f"  Expert signals: {len(expert_signal_map)} players classified")
            else:
                print("  No picks extracted")
        else:
            print("  No expert content available")
    except Exception as e:
        print(f"  Warning: Expert picks unavailable ({e})")

    # Apply signals to player data
    for player_name in all_players:
        all_players[player_name]["coursefit"] = coursefit_signals.get(player_name, "")
        all_players[player_name]["expert_picks"] = expert_signal_map.get(player_name, "")

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        slug = event_name.lower().replace(" ", "_").replace("'", "")
        output_path = f"composite_odds_{slug}.csv"

    # Write CSV
    fieldnames = [
        "player_name", "dg_id",
        "win_dg", "win_book_consensus", "win_composite",
        "t10_dg", "t10_book_consensus", "t10_composite",
        "t20_dg", "t20_book_consensus", "t20_composite",
        "make_cut_dg", "make_cut_book_consensus", "make_cut_composite",
        "coursefit", "expert_picks",
    ]

    # Sort by win composite prob descending (favorites first)
    sorted_players = sorted(
        all_players.items(),
        key=lambda x: x[1].get("win_composite") or 0,
        reverse=True,
    )

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for player_name, data in sorted_players:
            row = {"player_name": player_name, "dg_id": data.get("dg_id", "")}
            for field in fieldnames[2:]:
                row[field] = data.get(field, "")
            writer.writerow(row)

    print(f"\nWrote {len(sorted_players)} players to {output_path}")


if __name__ == "__main__":
    main()
