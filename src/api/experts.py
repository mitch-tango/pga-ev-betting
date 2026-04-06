"""Expert content fetching — YouTube transcripts and article scraping.

Fetches golf betting content from curated expert sources, primarily
YouTube transcripts (auto-generated, no API key needed) and Betsperts
articles (client-rendered, requires browser or cached text).

YouTube channels are searched for recent tournament-related videos,
and transcripts are fetched via youtube-transcript-api.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import requests
from youtube_transcript_api import YouTubeTranscriptApi

import config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class ExpertContent:
    """A piece of expert content (article or transcript) ready for extraction."""
    source: str
    author: str
    title: str
    url: str
    text: str
    published_date: str
    content_type: str  # "youtube_transcript", "article"


# ── YouTube ───────────────────────────────────────────────────────

def _search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube and extract video metadata from results page.

    Returns list of {video_id, title} dicts.
    """
    search_url = "https://www.youtube.com/results"
    resp = requests.get(
        search_url,
        params={"search_query": query},
        headers={"User-Agent": _USER_AGENT},
        timeout=15,
    )
    if resp.status_code != 200:
        logger.warning("YouTube search failed: HTTP %d", resp.status_code)
        return []

    # Extract video IDs and titles from the page
    video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
    titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}', resp.text)

    # Deduplicate while preserving order
    seen = set()
    results = []
    for vid, title in zip(video_ids, titles):
        if vid not in seen:
            seen.add(vid)
            results.append({"video_id": vid, "title": title})
        if len(results) >= max_results:
            break

    # If we have IDs but no titles, return IDs only
    if not results and video_ids:
        unique_ids = list(dict.fromkeys(video_ids))[:max_results]
        results = [{"video_id": vid, "title": ""} for vid in unique_ids]

    return results


def _fetch_transcript(video_id: str) -> str | None:
    """Fetch YouTube auto-generated transcript for a video."""
    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id)
        text = " ".join(snippet.text for snippet in transcript)
        return text
    except Exception as e:
        logger.warning("Transcript unavailable for %s: %s", video_id, e)
        return None


def fetch_youtube_content(
    tournament_name: str,
    channels: dict | None = None,
) -> list[ExpertContent]:
    """Fetch YouTube transcripts for tournament-related videos.

    Searches each configured channel for recent videos matching
    the tournament name, then fetches transcripts.
    """
    channels = channels or getattr(config, "EXPERT_YOUTUBE_CHANNELS", {})
    results = []

    for source_key, channel_config in channels.items():
        channel_query = channel_config.get("channel_query", source_key)
        search_terms = channel_config.get("search_terms", ["picks"])

        # Build search query: "Rick Gehman golf masters 2026 picks"
        year = datetime.now().year
        query = f"{channel_query} {tournament_name} {year} {search_terms[0]}"

        logger.info("Searching YouTube: %s", query)
        videos = _search_youtube(query, max_results=3)

        if not videos:
            logger.info("No videos found for %s", source_key)
            continue

        for video in videos:
            vid = video["video_id"]
            title = video["title"]

            # Skip if title doesn't seem related to golf/tournament
            title_lower = title.lower()
            tournament_words = tournament_name.lower().split()
            if not any(w in title_lower for w in tournament_words[:2]):
                continue

            transcript = _fetch_transcript(vid)
            if not transcript:
                continue

            # Skip very short transcripts (probably not a real preview)
            if len(transcript) < 1000:
                continue

            results.append(ExpertContent(
                source=source_key,
                author=channel_query,
                title=title,
                url=f"https://www.youtube.com/watch?v={vid}",
                text=transcript,
                published_date=datetime.now().strftime("%Y-%m-%d"),
                content_type="youtube_transcript",
            ))

            # Rate limit between transcript fetches
            time.sleep(1)

        logger.info("  %s: %d transcripts fetched", source_key, len(results))

    return results


# ── Betsperts Articles (manual/cached) ────────────────────────────

def fetch_betsperts_articles(
    tournament_name: str,
) -> list[ExpertContent]:
    """Fetch Betsperts article content.

    Betsperts uses client-side rendering (Next.js), so we can't scrape
    articles directly via requests. This function:
    1. Checks for cached article text in data/raw/expert_articles/
    2. Returns cached content if available

    To populate the cache, use the browser extension or manually save
    article text to data/raw/expert_articles/{slug}.txt
    """
    cache_dir = Path("data/raw/expert_articles")
    results = []

    if not cache_dir.exists():
        return results

    # Look for cached articles matching tournament name
    tournament_slug = tournament_name.lower().replace(" ", "-").replace("'", "")
    for txt_file in cache_dir.glob("*.txt"):
        if any(word in txt_file.stem.lower()
               for word in tournament_slug.split("-")[:2]):
            text = txt_file.read_text(encoding="utf-8")
            if len(text) < 200:
                continue

            # Try to extract author from first line
            lines = text.strip().split("\n")
            author = "Betsperts"
            for line in lines[:5]:
                if line.strip().startswith("By ") or line.strip().startswith("by "):
                    author = line.strip()[3:].strip()
                    break

            results.append(ExpertContent(
                source="betsperts",
                author=author,
                title=txt_file.stem.replace("-", " ").title(),
                url=f"https://betspertsgolf.com/golf-betting/{txt_file.stem}",
                text=text,
                published_date=datetime.fromtimestamp(
                    txt_file.stat().st_mtime
                ).strftime("%Y-%m-%d"),
                content_type="article",
            ))

    return results


# ── Combined Fetch ────────────────────────────────────────────────

def _load_cached_content(tournament_slug: str) -> list[ExpertContent]:
    """Load previously cached expert content for a tournament."""
    cache_dir = Path("data/raw") / tournament_slug
    if not cache_dir.exists():
        return []

    # Find the most recent cache file
    cache_files = sorted(cache_dir.glob("*/expert_content.json"), reverse=True)
    if not cache_files:
        return []

    try:
        with open(cache_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        content = [ExpertContent(**item) for item in data]
        logger.info("Loaded %d cached items from %s", len(content), cache_files[0])
        return content
    except Exception as e:
        logger.warning("Failed to load cached content: %s", e)
        return []


def fetch_all_expert_content(
    tournament_name: str,
    tournament_slug: str | None = None,
) -> list[ExpertContent]:
    """Fetch expert content from all configured sources.

    Falls back to cached content if fresh YouTube fetches fail
    (e.g., IP rate limiting). Caches successful fetches for reuse.
    """
    all_content = []

    # YouTube transcripts (primary source)
    try:
        yt_content = fetch_youtube_content(tournament_name)
        all_content.extend(yt_content)
        logger.info("YouTube: %d transcripts fetched", len(yt_content))
    except Exception as e:
        logger.warning("YouTube fetch failed: %s", e)

    # If YouTube returned nothing, try cached content
    if not all_content and tournament_slug:
        cached = _load_cached_content(tournament_slug)
        yt_cached = [c for c in cached if c.content_type == "youtube_transcript"]
        if yt_cached:
            all_content.extend(yt_cached)
            logger.info("YouTube: using %d cached transcripts (fresh fetch failed)",
                        len(yt_cached))

    # Betsperts articles (cached/manual)
    try:
        bp_content = fetch_betsperts_articles(tournament_name)
        all_content.extend(bp_content)
        logger.info("Betsperts articles: %d loaded from cache", len(bp_content))
    except Exception as e:
        logger.warning("Betsperts article fetch failed: %s", e)

    # Cache if we got any content
    if all_content and tournament_slug:
        _cache_content(all_content, tournament_slug)

    return all_content


def _cache_content(
    content: list[ExpertContent],
    tournament_slug: str,
) -> None:
    """Cache fetched content to avoid re-fetching."""
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    cache_path = Path("data/raw") / tournament_slug / date_str
    cache_path.mkdir(parents=True, exist_ok=True)

    filepath = cache_path / "expert_content.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in content], f, indent=2, ensure_ascii=False)

    logger.info("Cached %d expert content items → %s", len(content), filepath)
