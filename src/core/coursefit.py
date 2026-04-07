"""Course-fit signal from Betsperts Golf SG data.

Uses a dual-window approach:
  - **Form window** (last 12 rounds): SG:OTT, SG:APP, SG:T2G — ball-striking
    metrics that are skill-driven and where recency matters most.
  - **Baseline window** (last 50 rounds): SG:P, SG:ARG — noisy short-term
    metrics that need larger samples to stabilize.  No grass-type filtering
    per DataGolf's analysis that signal/noise is too low for putting by
    surface (would need 50+ rounds per surface to detect ~0.3 stroke effect,
    confounded by skill changes over time).

Course difficulty ratings (from Betsperts course stats pages) determine
**which SG categories get weighted more** in the composite score.  E.g.,
at Augusta where SG:APP is "Very Difficult", approach gains are weighted
higher than at an easy-approach course.

Signals are purely informational in Phase 1 — they annotate candidates
without modifying probabilities or sizing.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from src.api.betsperts import BetspertsClient
import config

logger = logging.getLogger(__name__)


# ── Course difficulty profiles ────────────────────────────────────
# Difficulty ratings from Betsperts course stats pages.
# Scale: 1 (Very Easy) → 5 (Very Difficult).
# These determine how much each SG category matters at a given course.

_DIFFICULTY_SCALE = {
    "Very Easy": 1, "Easy": 2, "Average": 3, "Difficult": 4, "Very Difficult": 5,
}

# SG category weights derived from course difficulty.
# Higher difficulty → the category is more separating → weight it more.
# Default weights (all Average = 3) give equal weighting.
COURSE_PROFILES: dict[str, dict] = getattr(config, "COURSE_PROFILES", {})

_BUILTIN_PROFILES = {
    "Masters Tournament": {
        "sg_ott": "Easy",        # Wide fairways, not punishing OTT
        "sg_app": "Very Difficult",  # Tricky greens complexes, elite iron play required
        "sg_arg": "Very Difficult",  # Premium on scrambling
        "sg_p": "Average",           # Fast greens but poor discriminator — every champ since 2021 had P as worst category
        "course_length": "Long",
        "course_par": 72,
    },
    "the Memorial Tournament presented by Workday": {
        "sg_ott": "Difficult",
        "sg_app": "Very Difficult",
        "sg_arg": "Difficult",
        "sg_p": "Difficult",
        "course_length": "Long",
        "course_par": 72,
    },
    "U.S. Open": {
        "sg_ott": "Very Difficult",
        "sg_app": "Very Difficult",
        "sg_arg": "Difficult",
        "sg_p": "Difficult",
        "course_length": "Very Long",
        "course_par": 70,
    },
    "The Open Championship": {
        "sg_ott": "Difficult",
        "sg_app": "Difficult",
        "sg_arg": "Very Difficult",
        "sg_p": "Difficult",
        "course_length": "Long",
        "course_par": 72,
    },
    "PGA Championship": {
        "sg_ott": "Difficult",
        "sg_app": "Difficult",
        "sg_arg": "Difficult",
        "sg_p": "Difficult",
        "course_length": "Long",
        "course_par": 72,
    },
    "THE PLAYERS Championship": {
        "sg_ott": "Average",
        "sg_app": "Difficult",
        "sg_arg": "Difficult",
        "sg_p": "Very Difficult",
        "course_length": "Average",
        "course_par": 72,
    },
    "Arnold Palmer Invitational presented by Mastercard": {
        "sg_ott": "Average",
        "sg_app": "Difficult",
        "sg_arg": "Difficult",
        "sg_p": "Average",
        "course_length": "Average",
        "course_par": 72,
    },
    "RBC Heritage": {
        "sg_ott": "Easy",
        "sg_app": "Average",
        "sg_arg": "Average",
        "sg_p": "Average",
        "course_length": "Short",
        "course_par": 71,
    },
}

_PROFILES = {**_BUILTIN_PROFILES, **COURSE_PROFILES}

# Default profile when course not in lookup
_DEFAULT_PROFILE = {
    "sg_ott": "Average", "sg_app": "Average",
    "sg_arg": "Average", "sg_p": "Average",
}

# Minimum rounds for each window
_FORM_MIN_ROUNDS = 8
_BASELINE_MIN_ROUNDS = getattr(config, "COURSEFIT_MIN_ROUNDS", 20)


# ── Name matching ─────────────────────────────────────────────────

def _normalize(name: str) -> str:
    name = name.lower().strip()
    # Convert "Last, First" → "first last" for consistent matching
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}" if len(parts) == 2 and parts[1] else name
    return " ".join(name.split())


def _names_match(a: str, b: str, threshold: float = 0.80) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    parts_a = na.split()
    parts_b = nb.split()
    if parts_a and parts_b and parts_a[-1] == parts_b[-1]:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def match_betsperts_to_dg(
    betsperts_players: list[dict],
    dg_player_names: list[str],
) -> dict[str, dict]:
    """Match Betsperts player records to DG player names."""
    matched: dict[str, dict] = {}
    bp_by_name = {_normalize(p["playerName"]): p for p in betsperts_players}

    for dg_name in dg_player_names:
        norm_dg = _normalize(dg_name)
        if norm_dg in bp_by_name:
            matched[dg_name] = bp_by_name[norm_dg]
            continue
        for bp_name, bp_record in bp_by_name.items():
            if _names_match(norm_dg, bp_name):
                matched[dg_name] = bp_record
                break

    return matched


# ── Data pulling ──────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_sg_records(players: list[dict]) -> dict[str, dict]:
    """Parse Betsperts player list into a normalized dict keyed by name."""
    result = {}
    for p in players:
        name = p.get("playerName", "")
        if not name:
            continue
        result[name] = {
            "sg_tot": _safe_float(p.get("SG:TOT")),
            "sg_t2g": _safe_float(p.get("SG:T2G")),
            "sg_ott": _safe_float(p.get("SG:OTT")),
            "sg_app": _safe_float(p.get("SG:APP")),
            "sg_arg": _safe_float(p.get("SG:ARG")),
            "sg_p": _safe_float(p.get("SG:P")),
            "rounds": _safe_int(p.get("Rounds")),
            "player_num": p.get("player_num"),
            "playerName": name,
        }
    return result


def _pull_dg_skill_ratings(tournament_slug: str | None = None) -> dict[str, dict]:
    """Pull SG category ratings from DataGolf's skill-ratings endpoint.

    Returns dict keyed by DG player_name (Last, First) → {sg_ott, sg_app,
    sg_arg, sg_p, sg_total}.  DG tracks all tours (PGA + LIV + DP World)
    so this covers players missing from Betsperts ShotLink data.
    """
    from src.api.datagolf import DataGolfClient

    dg = DataGolfClient()
    result = dg.get_skill_ratings(tournament_slug=tournament_slug)
    if result["status"] != "ok":
        logger.warning("DG skill-ratings pull failed: %s", result.get("message"))
        return {}

    data = result["data"]
    players = data.get("players", []) if isinstance(data, dict) else []

    lookup = {}
    for p in players:
        name = p.get("player_name", "")
        if not name:
            continue
        lookup[name] = {
            "sg_ott": _safe_float(p.get("sg_ott")),
            "sg_app": _safe_float(p.get("sg_app")),
            "sg_arg": _safe_float(p.get("sg_arg")),
            "sg_p": _safe_float(p.get("sg_putt")),
            "sg_total": _safe_float(p.get("sg_total")),
            "dg_id": p.get("dg_id"),
        }

    logger.info("DG skill-ratings: %d players loaded", len(lookup))
    return lookup


def pull_coursefit_data(
    tournament_name: str,
    tournament_slug: str | None = None,
) -> dict[str, dict]:
    """Pull dual-window SG data for a tournament field.

    Makes two Betsperts API calls:
      1. Form window (last 12 rounds, unfiltered) → SG:OTT, SG:APP, SG:T2G
      2. Baseline window (last 50 rounds, unfiltered) → SG:P, SG:ARG

    Players with insufficient Betsperts rounds (e.g., LIV players with
    limited ShotLink data) are backfilled from DataGolf's skill-ratings
    endpoint, which tracks all tours.

    Returns dict keyed by Betsperts playerName → merged record with all
    SG categories from the appropriate window, plus course-weighted composite.
    """
    try:
        client = BetspertsClient()
    except ValueError as e:
        logger.warning("Betsperts client init failed: %s", e)
        return {}

    if not client.check_session():
        logger.warning("Betsperts session expired — skipping coursefit")
        return {}

    # Pull form window: recent ball-striking (last 12 rounds)
    logger.info("Pulling Betsperts form window (last 12 rounds) for %s", tournament_name)
    form_players = client.get_field_sg_averages(
        tournament_name,
        time_frame="6 Months",
        last_n_rounds=12,
        tournament_slug=tournament_slug,
    )

    # Pull baseline window: putting/short game (last 50 rounds)
    logger.info("Pulling Betsperts baseline window (last 50 rounds) for %s", tournament_name)
    baseline_players = client.get_field_sg_averages(
        tournament_name,
        time_frame="12 Months",
        last_n_rounds=50,
        tournament_slug=tournament_slug,
    )

    if not form_players and not baseline_players:
        return {}

    form_data = _parse_sg_records(form_players or [])
    baseline_data = _parse_sg_records(baseline_players or [])

    # Pull DG skill ratings as fallback for low-sample players
    dg_sg = _pull_dg_skill_ratings(tournament_slug)

    # Merge: ball-striking from form window, short game from baseline
    profile = _PROFILES.get(tournament_name, _DEFAULT_PROFILE)
    all_names = set(form_data.keys()) | set(baseline_data.keys())

    merged = {}
    dg_backfill_count = 0
    for name in all_names:
        form = form_data.get(name, {})
        baseline = baseline_data.get(name, {})

        # Ball-striking from form window (recent)
        sg_ott = form.get("sg_ott")
        sg_app = form.get("sg_app")
        sg_t2g = form.get("sg_t2g")
        form_rounds = form.get("rounds")

        # Short game from baseline window (larger sample)
        sg_arg = baseline.get("sg_arg")
        sg_p = baseline.get("sg_p")
        baseline_rounds = baseline.get("rounds")

        # DG backfill: if either window has insufficient rounds, fill
        # missing SG categories from DG skill ratings.  DG names use
        # "Last, First" format; Betsperts uses "First Last" — try both.
        form_ok = form_rounds is not None and form_rounds >= _FORM_MIN_ROUNDS
        baseline_ok = baseline_rounds is not None and baseline_rounds >= _BASELINE_MIN_ROUNDS
        needs_backfill = not form_ok or not baseline_ok

        dg_source = None
        if needs_backfill and dg_sg:
            # Try matching: Betsperts "First Last" → DG "Last, First"
            dg_source = _match_dg_sg(name, dg_sg)

        if dg_source:
            if not form_ok:
                sg_ott = sg_ott if sg_ott is not None else dg_source.get("sg_ott")
                sg_app = sg_app if sg_app is not None else dg_source.get("sg_app")
                # DG doesn't provide T2G directly; compute if we have components
                if sg_t2g is None and sg_ott is not None and sg_app is not None:
                    sg_t2g = sg_ott + sg_app
                # Set round count to threshold so signal pipeline accepts it
                form_rounds = max(form_rounds or 0, _FORM_MIN_ROUNDS)
            if not baseline_ok:
                sg_arg = sg_arg if sg_arg is not None else dg_source.get("sg_arg")
                sg_p = sg_p if sg_p is not None else dg_source.get("sg_p")
                baseline_rounds = max(baseline_rounds or 0, _BASELINE_MIN_ROUNDS)
            dg_backfill_count += 1

        # Compute course-weighted composite
        composite = _compute_weighted_composite(
            sg_ott, sg_app, sg_arg, sg_p, profile
        )

        merged[name] = {
            "playerName": name,
            "player_num": form.get("player_num") or baseline.get("player_num"),
            # From form window (or DG backfill)
            "sg_ott": sg_ott,
            "sg_app": sg_app,
            "sg_t2g": sg_t2g,
            "form_rounds": form_rounds,
            # From baseline window (or DG backfill)
            "sg_arg": sg_arg,
            "sg_p": sg_p,
            "baseline_rounds": baseline_rounds,
            # Composite
            "sg_composite": composite,
            "rounds": form_rounds,  # Use form rounds as the binding sample
            "dg_backfill": dg_source is not None,
        }

    if dg_backfill_count:
        logger.info("DG backfill: %d players supplemented with skill-ratings",
                     dg_backfill_count)

    return merged


def _match_dg_sg(betsperts_name: str, dg_sg: dict[str, dict]) -> dict | None:
    """Match a Betsperts player name to the DG skill-ratings lookup.

    Betsperts uses "First Last", DG uses "Last, First".
    """
    # Direct match (unlikely but cheap)
    if betsperts_name in dg_sg:
        return dg_sg[betsperts_name]

    # Convert "First Last" → "Last, First" and try
    norm = _normalize(betsperts_name)
    parts = norm.split()
    if len(parts) >= 2:
        # Try "Last, First" format
        last_first = f"{parts[-1]}, {' '.join(parts[:-1])}"
        for dg_name, data in dg_sg.items():
            if _normalize(dg_name) == last_first:
                return data

    # Fuzzy fallback: last name match
    for dg_name, data in dg_sg.items():
        if _names_match(betsperts_name, dg_name):
            return data

    return None


def _compute_weighted_composite(
    sg_ott: float | None,
    sg_app: float | None,
    sg_arg: float | None,
    sg_p: float | None,
    profile: dict,
) -> float | None:
    """Compute a course-difficulty-weighted SG composite.

    Higher difficulty for a category → higher weight in the composite.
    This means a player who excels in approach play gets a bigger boost
    at courses where approach is "Very Difficult" (like Augusta).
    """
    components = []
    total_weight = 0

    for sg_val, key in [(sg_ott, "sg_ott"), (sg_app, "sg_app"),
                        (sg_arg, "sg_arg"), (sg_p, "sg_p")]:
        if sg_val is None:
            continue
        difficulty = profile.get(key, "Average")
        weight = _DIFFICULTY_SCALE.get(difficulty, 3)
        components.append(sg_val * weight)
        total_weight += weight

    if total_weight == 0:
        return None

    return sum(components) / total_weight


# ── Signal computation ────────────────────────────────────────────

def compute_coursefit_signals(
    betsperts_data: dict[str, dict],
    candidates: list,
) -> dict[str, dict]:
    """Compute course-fit classification for each candidate player.

    Uses the course-weighted composite score for ranking, then compares
    to DG probability rank to classify agreement.
    """
    if not betsperts_data:
        return {}

    dg_names = list({c.player_name for c in candidates})
    matched = match_betsperts_to_dg(list(betsperts_data.values()), dg_names)

    # Rank all players by composite score (descending)
    all_composite = [
        (name, d["sg_composite"])
        for name, d in betsperts_data.items()
        if d.get("sg_composite") is not None
    ]
    all_composite.sort(key=lambda x: x[1], reverse=True)
    field_size = len(all_composite)
    composite_rank_map = {name: rank + 1 for rank, (name, _) in enumerate(all_composite)}

    # Build DG probability rank
    dg_prob_by_player: dict[str, float] = {}
    for c in candidates:
        if c.player_name not in dg_prob_by_player:
            dg_prob_by_player[c.player_name] = c.dg_prob
        else:
            dg_prob_by_player[c.player_name] = max(
                dg_prob_by_player[c.player_name], c.dg_prob
            )

    dg_sorted = sorted(dg_prob_by_player.items(), key=lambda x: x[1], reverse=True)
    dg_field_size = len(dg_sorted)
    dg_rank_map = {name: rank + 1 for rank, (name, _) in enumerate(dg_sorted)}

    # Compute signals
    signals: dict[str, dict] = {}
    for dg_name in dg_names:
        bp_record = matched.get(dg_name)
        if not bp_record:
            continue

        bp_name = bp_record["playerName"]
        form_rounds = bp_record.get("form_rounds")
        baseline_rounds = bp_record.get("baseline_rounds")
        composite = bp_record.get("sg_composite")
        composite_rank = composite_rank_map.get(bp_name)

        # Low sample: need minimum rounds in both windows
        form_ok = form_rounds is not None and form_rounds >= _FORM_MIN_ROUNDS
        baseline_ok = baseline_rounds is not None and baseline_rounds >= _BASELINE_MIN_ROUNDS

        if not form_ok or not baseline_ok:
            signals[dg_name] = {
                "signal": "low_sample",
                "sg_composite": composite,
                "sg_rank": composite_rank,
                "form_rounds": form_rounds,
                "baseline_rounds": baseline_rounds,
                "field_size": field_size,
                **_extract_sg(bp_record),
            }
            continue

        if composite is None or composite_rank is None:
            continue

        dg_rank = dg_rank_map.get(dg_name)
        if dg_rank is None:
            continue

        sg_pct = (composite_rank - 1) / max(field_size - 1, 1)
        dg_pct = (dg_rank - 1) / max(dg_field_size - 1, 1)
        signal = _classify_agreement(sg_pct, dg_pct)

        signals[dg_name] = {
            "signal": signal,
            "sg_composite": composite,
            "sg_rank": composite_rank,
            "form_rounds": form_rounds,
            "baseline_rounds": baseline_rounds,
            "field_size": field_size,
            **_extract_sg(bp_record),
        }

    return signals


def _extract_sg(record: dict) -> dict:
    """Extract SG values for logging/display."""
    return {
        "sg_ott": record.get("sg_ott"),
        "sg_app": record.get("sg_app"),
        "sg_arg": record.get("sg_arg"),
        "sg_p": record.get("sg_p"),
        "sg_t2g": record.get("sg_t2g"),
    }


def _classify_agreement(sg_pct: float, dg_pct: float) -> str:
    """Classify agreement between composite SG rank and DG probability rank."""
    if sg_pct <= 0.25 and dg_pct <= 0.25:
        return "strong_confirm"
    if sg_pct >= 0.75 and dg_pct >= 0.75:
        return "strong_confirm"
    if (sg_pct <= 0.50) == (dg_pct <= 0.50):
        return "confirm"
    if (sg_pct <= 0.25 and dg_pct >= 0.75) or (sg_pct >= 0.75 and dg_pct <= 0.25):
        return "strong_contradict"
    return "contradict"


# ── Enrichment ────────────────────────────────────────────────────

def enrich_candidates_with_coursefit(
    candidates: list,
    coursefit_signals: dict[str, dict],
) -> None:
    """Set coursefit fields on CandidateBet objects (mutates in place)."""
    for c in candidates:
        sig = coursefit_signals.get(c.player_name)
        if not sig:
            continue
        c.coursefit_signal = sig["signal"]
        c.coursefit_sg_tot = sig.get("sg_composite")
        c.coursefit_sg_rank = sig.get("sg_rank")
        c.coursefit_rounds = sig.get("form_rounds")


# ── Display helpers ───────────────────────────────────────────────

SIGNAL_LABELS = {
    "strong_confirm": "[++]",
    "confirm": " [+]",
    "neutral": " [~]",
    "contradict": " [-]",
    "strong_contradict": "[--]",
    "low_sample": " [?]",
}


def format_signal(signal: str | None) -> str:
    if not signal:
        return "    "
    return SIGNAL_LABELS.get(signal, "    ")


def format_coursefit_card(
    player_name: str,
    data: dict,
    tournament_name: str | None = None,
) -> str:
    """Format a detailed course-fit card for Discord or CLI."""
    lines = [f"**{player_name}**"]

    if tournament_name:
        profile = _PROFILES.get(tournament_name)
        if profile:
            difficulties = [
                f"OTT:{profile.get('sg_ott', '?')}",
                f"APP:{profile.get('sg_app', '?')}",
                f"ARG:{profile.get('sg_arg', '?')}",
                f"P:{profile.get('sg_p', '?')}",
            ]
            lines.append(f"_{tournament_name}_ — {', '.join(difficulties)}")
        else:
            lines.append(f"_{tournament_name}_ — default weights")

    # Form window (ball-striking)
    form_parts = []
    for label, key in [("OTT", "sg_ott"), ("APP", "sg_app"), ("T2G", "sg_t2g")]:
        val = data.get(key)
        if val is not None:
            sign = "+" if val >= 0 else ""
            form_parts.append(f"SG:{label} {sign}{val:.2f}")
    form_rds = data.get("form_rounds", "?")
    lines.append(f"Form ({form_rds}r): {' | '.join(form_parts) or 'N/A'}")

    # Baseline window (short game)
    base_parts = []
    for label, key in [("ARG", "sg_arg"), ("P", "sg_p")]:
        val = data.get(key)
        if val is not None:
            sign = "+" if val >= 0 else ""
            base_parts.append(f"SG:{label} {sign}{val:.2f}")
    base_rds = data.get("baseline_rounds", "?")
    lines.append(f"Baseline ({base_rds}r): {' | '.join(base_parts) or 'N/A'}")

    # Composite
    comp = data.get("sg_composite")
    if comp is not None:
        sign = "+" if comp >= 0 else ""
        rank = data.get("sg_rank", "?")
        field = data.get("field_size", "?")
        lines.append(f"Weighted composite: {sign}{comp:.2f} | Rank: {rank}/{field}")

    return "\n".join(lines)
