"""NoVig screenshot → structured market lines via Claude vision.

NoVig's developer API requires a $30k deposit and isn't viable at
current bankroll. This module is the substitute: the user snaps
screenshots of NoVig markets on their phone, drops them into the
Discord `/novig` command, and Claude Haiku extracts the lines as
JSON for the edge calculator.

Supported NoVig screens:
- Winner outrights (Outright Winner, Top 5, Top 10, Top 20 sub-tabs)
- To Make The Cut outrights
- Matchups (tournament matchups or per-round matchups, 2-way)

NoVig is an exchange — outright rows show both a "Yes" and a "No"
side with American odds. Both sides are extracted; the downstream
edge calculator evaluates each side against the DG model (Yes uses
DG_prob directly; No uses 1 - DG_prob).

Scope is intentionally narrow — no FRL / Specials / 3-balls in v1.
Add those when the user starts using them on NoVig.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Literal

import config

logger = logging.getLogger(__name__)


# ── Data models ──────────────────────────────────────────────────────


# Market tab as Claude sees it in the NoVig UI → our internal market_type.
_MARKET_TAB_TO_MARKET = {
    "winner": "win",               # overridden by subtab for Top N
    "to make the cut": "make_cut",
    "matchups": "matchup",
}

# Winner sub-tab → internal market_type
_SUBTAB_TO_MARKET = {
    "outright winner": "win",
    "top 5": "t5",
    "top 10": "t10",
    "top 20": "t20",
}


@dataclass
class NovigOutrightLine:
    """One row of a NoVig outright board.

    `market_type` is the internal short form ("win", "t10", etc.).
    Either `yes_odds_american` or `no_odds_american` can be None if
    that side was unavailable (the NoVig UI shows a dot in that cell).
    """
    market_type: str
    player_name: str
    yes_odds_american: str | None
    no_odds_american: str | None


@dataclass
class NovigMatchupLine:
    """One 2-way matchup row on NoVig.

    `market_type` is "tournament_matchup" or "round_matchup" depending
    on whether a round was indicated in the screen header.
    """
    market_type: str  # "tournament_matchup" | "round_matchup"
    player1_name: str
    player1_odds_american: str
    player2_name: str
    player2_odds_american: str
    round_number: int | None = None


@dataclass
class NovigExtraction:
    """Everything extracted from one NoVig screenshot."""
    tournament_name: str
    market_tab: str                 # raw tab label seen in the UI
    subtab: str | None              # sub-tab label (for Winner tabs)
    round_number: int | None        # for matchup screens
    outrights: list[NovigOutrightLine] = field(default_factory=list)
    matchups: list[NovigMatchupLine] = field(default_factory=list)
    raw_json: dict | None = None    # Claude's raw response, for debugging


# ── Extraction prompt ────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You extract structured betting data from NoVig sportsbook app screenshots.
NoVig is a peer-to-peer exchange — outright boards show both a "Yes" and
a "No" side with American odds per row.

Return ONLY valid JSON matching the schema below. Do not include prose,
markdown fences, or commentary. If a cell shows a dot ("·") instead of
odds, that side is unavailable — return null for that field.

Schema:
{
  "tournament_name": "<string from the event hero header, e.g. 'Augusta Golf Tournament'>",
  "market_tab": "<one of: Winner, To Make The Cut, Matchups, Specials, Other>",
  "subtab": "<one of: Outright Winner, Top 5, Top 10, Top 20, null>",
  "round_number": <integer 1-4 if the screen shows an 'Nth Round Matchups' header, else null>,
  "outrights": [
    {
      "player_name": "<first last, as shown>",
      "yes_odds_american": "<e.g. -449 or +313, include sign; null if unavailable>",
      "no_odds_american": "<same rules as yes_odds_american>"
    }
  ],
  "matchups": [
    {
      "player1_name": "<first last>",
      "player1_odds_american": "<e.g. -102 or +105>",
      "player2_name": "<first last>",
      "player2_odds_american": "<e.g. -102 or +105>"
    }
  ]
}

Rules:
- If the screen is an outrights board (Winner or To Make The Cut tabs),
  fill `outrights` and leave `matchups` as [].
- If the screen is a Matchups board, fill `matchups` and leave
  `outrights` as [].
- `market_tab` is the ACTIVE tab (underlined in orange). `subtab` is
  the active sub-tab under Winner (blue-bordered), or null if not
  applicable.
- Every visible row should be extracted, even if you need to infer a
  player name from a partially obscured row at the bottom. If a row
  is so cut off you can't read the name, skip it rather than guess.
- Player names in "First Last" format, exactly as shown on screen.
- Odds strings must include the "+" or "-" sign. No decimal odds.
- Do not invent data. If the screen shows no outrights and no
  matchups, return empty arrays for both.
"""


def _decode_image_to_b64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("ascii")


def extract_novig_screenshot(
    image_bytes: bytes,
    media_type: str = "image/png",
    model: str = "claude-haiku-4-5-20251001",
) -> NovigExtraction | None:
    """Run Claude Haiku vision extraction on one NoVig screenshot.

    Returns None if Claude isn't configured, the SDK isn't installed,
    or the API call fails. Non-fatal by design — the /novig command
    reports per-image failures in the embed but keeps processing the
    rest of the batch.
    """
    api_key = getattr(config, "ANTHROPIC_API_KEY", None)
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — cannot extract NoVig screenshots")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=3000,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": _decode_image_to_b64(image_bytes),
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract this NoVig screenshot as JSON per the schema.",
                    },
                ],
            }],
        )
    except Exception as e:
        logger.error("Claude vision call failed: %s", e)
        return None

    try:
        raw_text = message.content[0].text.strip()
    except (IndexError, AttributeError):
        logger.error("Claude returned unexpected content shape")
        return None

    # Claude occasionally wraps JSON in a markdown fence even when told
    # not to — strip defensively.
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Claude JSON parse failed: %s | raw: %s", e, raw_text[:500])
        return None

    return _build_extraction(data)


def _build_extraction(data: dict) -> NovigExtraction:
    """Convert the raw Claude JSON dict into a typed NovigExtraction.

    Applies the tab/subtab → internal market_type mapping so downstream
    code can key off `market_type` directly without caring about how
    NoVig labels its tabs.
    """
    tournament_name = (data.get("tournament_name") or "").strip()
    market_tab = (data.get("market_tab") or "").strip()
    subtab = (data.get("subtab") or "").strip() or None
    round_number = data.get("round_number")
    if isinstance(round_number, str):
        try:
            round_number = int(round_number)
        except ValueError:
            round_number = None

    tab_lower = market_tab.lower()
    subtab_lower = subtab.lower() if subtab else None

    outright_lines: list[NovigOutrightLine] = []
    matchup_lines: list[NovigMatchupLine] = []

    raw_outrights = data.get("outrights") or []
    raw_matchups = data.get("matchups") or []

    if raw_outrights:
        if tab_lower == "to make the cut":
            market_type = "make_cut"
        elif subtab_lower and subtab_lower in _SUBTAB_TO_MARKET:
            market_type = _SUBTAB_TO_MARKET[subtab_lower]
        elif tab_lower == "winner":
            market_type = "win"
        else:
            market_type = "win"  # safest default

        for row in raw_outrights:
            player = (row.get("player_name") or "").strip()
            if not player:
                continue
            outright_lines.append(NovigOutrightLine(
                market_type=market_type,
                player_name=player,
                yes_odds_american=_clean_odds(row.get("yes_odds_american")),
                no_odds_american=_clean_odds(row.get("no_odds_american")),
            ))

    if raw_matchups:
        # Tournament-long vs round matchup: NoVig shows a round header
        # ("4th Round Matchups") for per-round boards and no header at
        # all for tournament-long boards. Round_number distinguishes.
        matchup_market_type = (
            "round_matchup" if round_number else "tournament_matchup"
        )
        for row in raw_matchups:
            p1 = (row.get("player1_name") or "").strip()
            p2 = (row.get("player2_name") or "").strip()
            p1_odds = _clean_odds(row.get("player1_odds_american"))
            p2_odds = _clean_odds(row.get("player2_odds_american"))
            if not (p1 and p2 and p1_odds and p2_odds):
                continue
            matchup_lines.append(NovigMatchupLine(
                market_type=matchup_market_type,
                player1_name=p1,
                player1_odds_american=p1_odds,
                player2_name=p2,
                player2_odds_american=p2_odds,
                round_number=round_number,
            ))

    return NovigExtraction(
        tournament_name=tournament_name,
        market_tab=market_tab,
        subtab=subtab,
        round_number=round_number,
        outrights=outright_lines,
        matchups=matchup_lines,
        raw_json=data,
    )


def _clean_odds(raw: object) -> str | None:
    """Normalize an odds field into a canonical American-odds string or None.

    Accepts int, str, or None. Rejects placeholder dots and empty strings
    the model might emit for unavailable cells.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = int(raw)
        return f"{value:+d}"
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped or stripped in {"·", "•", "-", "null"}:
            return None
        # Ensure a sign prefix
        if stripped[0] not in "+-":
            try:
                value = int(stripped)
                return f"{value:+d}"
            except ValueError:
                return None
        return stripped
    return None


def merge_extractions(
    extractions: list[NovigExtraction],
) -> tuple[list[NovigOutrightLine], list[NovigMatchupLine], str | None]:
    """Flatten a batch of extractions into unified line lists.

    Used by /novig when the user drops N screenshots in one command.
    Tournament name returned is the most common non-empty one across
    the batch (or None if all are empty) so the command can run a
    single tournament match rather than N of them.
    """
    all_outrights: list[NovigOutrightLine] = []
    all_matchups: list[NovigMatchupLine] = []
    name_counts: dict[str, int] = {}

    for ext in extractions:
        all_outrights.extend(ext.outrights)
        all_matchups.extend(ext.matchups)
        if ext.tournament_name:
            name_counts[ext.tournament_name] = (
                name_counts.get(ext.tournament_name, 0) + 1
            )

    tournament_name = None
    if name_counts:
        tournament_name = max(name_counts.items(), key=lambda x: x[1])[0]

    return all_outrights, all_matchups, tournament_name
