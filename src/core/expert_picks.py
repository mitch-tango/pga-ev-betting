"""Expert picks extraction and consensus signal.

Uses Claude API (Haiku) to extract structured betting picks from
expert articles and YouTube transcripts, then aggregates into a
consensus signal per player.

Like the course-fit signal, this is Phase 1 (data collection only) —
the expert signal annotates candidates without modifying probabilities
or sizing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher

import config

logger = logging.getLogger(__name__)

# ── Extraction prompt ─────────────────────────────────────────────

_EXTRACT_PROMPT = """\
You are analyzing a golf betting article or video transcript. Extract two types of player signals:

1. **EXPLICIT PICKS**: Where the author clearly recommends betting on or fading a player.
2. **IMPLIED SIGNALS**: Where the author's analysis strongly suggests a player is well-suited or poorly-suited for the tournament, even without a direct betting recommendation.

For each signal, return a JSON object with these fields:
- "player_name": Full player name (e.g., "Scottie Scheffler")
- "market": One of "win", "top_5", "top_10", "top_20", "make_cut", "matchup", "first_round_leader", "general"
- "sentiment": One of "strong_positive" (lock/love/top pick), "positive" (like/lean/favorable analysis), "negative" (avoid/concerns/poor fit), "fade" (explicitly bet against)
- "confidence": One of "high" (stated conviction or overwhelming evidence), "medium" (standard pick or clear analytical lean), "low" (flier/dart/mild lean)
- "pick_type": "explicit" (direct recommendation) or "implied" (derived from analysis)
- "reasoning": One sentence summarizing why (e.g., "Elite ball-striker who dominates long courses")

Rules for EXPLICIT picks:
- "I like Scheffler this week" = explicit positive
- "Stay away from Rahm" or "Fade Rahm" = explicit negative/fade
- "Top pick" or "lock" = explicit strong_positive with high confidence
- "Sleeper" or "longshot play" = explicit positive with low confidence

Rules for IMPLIED signals:
- Author highlights a player's elite course-fit stats AND recent form → implied positive
- "Scheffler enters with more questions than any point in recent memory" → implied negative, low confidence
- "McIlroy's ball-striking is trending in the right direction" → implied positive, medium confidence
- Player mentioned repeatedly in favorable contexts throughout the article → implied positive
- General statistical mentions without clear directional lean → skip (do not extract)
- Only extract implied signals when the author's tone clearly favors or disfavors a player

Return a JSON array. If no clear signals are found, return [].

Content to analyze:
{content}"""


# ── Data models ───────────────────────────────────────────────────

@dataclass
class ExpertPick:
    source: str
    author: str
    player_name: str
    market: str
    sentiment: str
    confidence: str
    reasoning: str
    url: str
    pick_type: str = "explicit"  # "explicit" or "implied"


# Sentiment scores for aggregation
_SENTIMENT_SCORES = {
    "strong_positive": 2.0,
    "positive": 1.0,
    "negative": -1.0,
    "fade": -2.0,
}

_CONFIDENCE_MULTIPLIERS = {
    "high": 1.5,
    "medium": 1.0,
    "low": 0.5,
}

_PICK_TYPE_MULTIPLIERS = {
    "explicit": 1.0,
    "implied": 0.5,  # Implied signals count half as much as explicit picks
}


# ── LLM Extraction ───────────────────────────────────────────────

def extract_picks_from_content(
    content_text: str,
    source: str,
    author: str,
    url: str,
    max_content_chars: int = 30000,
) -> list[ExpertPick]:
    """Extract structured picks from expert content using Claude API.

    Uses Haiku for fast, cheap extraction (~$0.01-0.03 per article).
    """
    api_key = getattr(config, "ANTHROPIC_API_KEY", None)
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — cannot extract expert picks")
        return []

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed")
        return []

    # Truncate very long transcripts
    text = content_text[:max_content_chars]

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": _EXTRACT_PROMPT.format(content=text),
            }],
        )

        response_text = message.content[0].text.strip()

        # Parse JSON from response (handle markdown code blocks)
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()

        picks_data = json.loads(response_text)

        picks = []
        for p in picks_data:
            picks.append(ExpertPick(
                source=source,
                author=author,
                player_name=p.get("player_name", ""),
                market=p.get("market", "general"),
                sentiment=p.get("sentiment", "positive"),
                confidence=p.get("confidence", "medium"),
                reasoning=p.get("reasoning", ""),
                url=url,
                pick_type=p.get("pick_type", "explicit"),
            ))

        logger.info("Extracted %d picks from %s (%s)", len(picks), source, author)
        return picks

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        return []
    except Exception as e:
        logger.warning("LLM extraction failed for %s: %s", source, e)
        return []


def extract_all_picks(
    expert_content: list,
) -> list[ExpertPick]:
    """Extract picks from all expert content items."""
    all_picks = []
    for content in expert_content:
        picks = extract_picks_from_content(
            content.text,
            source=content.source,
            author=content.author,
            url=content.url,
        )
        all_picks.extend(picks)
    return all_picks


# ── Name matching ─────────────────────────────────────────────────

def _normalize(name: str) -> str:
    name = name.lower().strip()
    # Convert "Last, First" → "first last" for consistent matching
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            name = f"{parts[1]} {parts[0]}"
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


def _match_pick_to_field(
    pick_name: str,
    field_names: list[str],
) -> str | None:
    """Match an expert-mentioned player name to a DG field name."""
    norm_pick = _normalize(pick_name)
    for field_name in field_names:
        if _names_match(norm_pick, _normalize(field_name)):
            return field_name
    return None


# ── Consensus Signal ──────────────────────────────────────────────

def compute_expert_signals(
    picks: list[ExpertPick],
    field_names: list[str],
) -> dict[str, dict]:
    """Aggregate expert picks into a consensus signal per player.

    Returns dict keyed by DG player_name → {signal, score, pick_count, picks}
    """
    # Match picks to field and group by player
    player_picks: dict[str, list[ExpertPick]] = {}
    for pick in picks:
        matched_name = _match_pick_to_field(pick.player_name, field_names)
        if matched_name:
            player_picks.setdefault(matched_name, []).append(pick)
        else:
            logger.debug("Expert pick '%s' not matched to field", pick.player_name)

    # Compute consensus for each player
    signals: dict[str, dict] = {}
    for player_name, player_pick_list in player_picks.items():
        score = 0.0
        for pick in player_pick_list:
            sentiment_score = _SENTIMENT_SCORES.get(pick.sentiment, 0)
            confidence_mult = _CONFIDENCE_MULTIPLIERS.get(pick.confidence, 1.0)
            type_mult = _PICK_TYPE_MULTIPLIERS.get(pick.pick_type, 1.0)
            score += sentiment_score * confidence_mult * type_mult

        pick_count = len(player_pick_list)
        signal = _classify_score(score)

        signals[player_name] = {
            "signal": signal,
            "score": round(score, 1),
            "pick_count": pick_count,
            "picks": [
                {
                    "source": p.source,
                    "author": p.author,
                    "sentiment": p.sentiment,
                    "confidence": p.confidence,
                    "market": p.market,
                    "reasoning": p.reasoning,
                    "pick_type": p.pick_type,
                }
                for p in player_pick_list
            ],
        }

    return signals


def _classify_score(score: float) -> str:
    if score >= 3.0:
        return "strong_confirm"
    if score > 0:
        return "confirm"
    if score == 0:
        return "neutral"
    if score <= -3.0:
        return "strong_contradict"
    return "contradict"


# ── Enrichment ────────────────────────────────────────────────────

def enrich_candidates_with_expert_picks(
    candidates: list,
    expert_signals: dict[str, dict],
) -> None:
    """Set expert pick fields on CandidateBet objects (mutates in place)."""
    for c in candidates:
        sig = expert_signals.get(c.player_name)
        if not sig:
            continue
        c.expert_signal = sig["signal"]
        c.expert_score = sig["score"]
        c.expert_pick_count = sig["pick_count"]


def load_cached_expert_signals(
    tournament_name: str | None,
    tournament_slug: str | None = None,
) -> dict[str, dict]:
    """Load pre-extracted expert signals for a tournament.

    Signals are generated offline (see `scripts/ingest_oad_experts.py`) and
    saved to `data/raw/{slug}/expert_signals.json`. Scan paths call this
    helper on the hot path — no LLM call, just a JSON read.

    Returns {} if nothing cached or tournament identifier missing.
    """
    import json
    from pathlib import Path

    slug = tournament_slug
    if not slug and tournament_name:
        slug = tournament_name.lower().replace(" ", "-")
    if not slug:
        return {}

    path = Path("data/raw") / slug / "expert_signals.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to load cached expert signals from %s: %s", path, e)
        return {}


def enrich_candidates_from_cache(
    candidates: list,
    tournament_name: str | None,
    tournament_slug: str | None = None,
) -> int:
    """Load cached expert signals and enrich candidates. Returns enriched count."""
    if not candidates:
        return 0
    signals = load_cached_expert_signals(tournament_name, tournament_slug)
    if not signals:
        return 0
    enrich_candidates_with_expert_picks(candidates, signals)
    return sum(1 for c in candidates if c.expert_signal)


# ── Display ───────────────────────────────────────────────────────

SIGNAL_LABELS = {
    "strong_confirm": "[++]",
    "confirm": " [+]",
    "neutral": " [~]",
    "contradict": " [-]",
    "strong_contradict": "[--]",
}


def format_signal(signal: str | None) -> str:
    if not signal:
        return "    "
    return SIGNAL_LABELS.get(signal, "    ")


def format_expert_summary(
    expert_signals: dict[str, dict],
    sources: list | None = None,
) -> str:
    """Format expert consensus summary for display."""
    if not expert_signals:
        return "No expert picks found."

    # Sort by score descending
    sorted_players = sorted(
        expert_signals.items(),
        key=lambda x: x[1]["score"],
        reverse=True,
    )

    lines = []

    # Bullish picks
    bullish = [(n, s) for n, s in sorted_players if s["score"] > 0]
    if bullish:
        lines.append("**Bullish:**")
        for name, sig in bullish[:10]:
            label = SIGNAL_LABELS.get(sig["signal"], "")
            sources_str = ", ".join(
                p["author"] for p in sig["picks"]
            )
            lines.append(
                f"  {name:<22s} {sig['pick_count']} picks  "
                f"score: {sig['score']:+.1f}  {label}  ({sources_str})"
            )

    # Fades
    bearish = [(n, s) for n, s in sorted_players if s["score"] < 0]
    if bearish:
        lines.append("\n**Fades:**")
        for name, sig in bearish[:5]:
            label = SIGNAL_LABELS.get(sig["signal"], "")
            sources_str = ", ".join(
                p["author"] for p in sig["picks"]
            )
            lines.append(
                f"  {name:<22s} {sig['pick_count']} picks  "
                f"score: {sig['score']:+.1f}  {label}  ({sources_str})"
            )

    return "\n".join(lines)
