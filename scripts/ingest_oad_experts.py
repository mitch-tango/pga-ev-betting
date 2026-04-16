#!/usr/bin/env python3
"""Ingest a PGA OAD tournament folder into the expert-picks pipeline.

One-shot workflow: scan the OAD folder for `.docx` picks docs and
`.md` podcast transcripts, stage them as text files in
`data/raw/expert_articles/` with the tournament slug prefix, run the
LLM extraction pipeline, and write the resulting consensus signals
to `data/raw/{slug}/expert_signals.json` where the scan paths pick
them up automatically.

Usage:
    python scripts/ingest_oad_experts.py "<oad_folder>" <slug> [<tournament_name>]

Example:
    python scripts/ingest_oad_experts.py \\
        "/path/to/PGA OAD/RBC Heritage" \\
        rbc-heritage \\
        "RBC Heritage"

The <tournament_name> is optional and defaults to the slug titlecased.
It's only used for logging.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.experts import fetch_betsperts_articles
from src.core.expert_picks import (
    extract_all_picks, compute_expert_signals, format_expert_summary,
)
from src.pipeline.pull_outrights import pull_all_outrights

logging.basicConfig(level=logging.WARNING)


def _stage_files(oad_folder: Path, slug: str) -> int:
    """Copy .md transcripts and convert .docx pick docs into expert_articles/.

    Files are prefixed with `{slug}-` so fetch_betsperts_articles() picks
    them up via its tournament-word filename match.
    """
    dst = Path("data/raw/expert_articles")
    dst.mkdir(parents=True, exist_ok=True)
    staged = 0

    # Podcast transcripts (markdown)
    tx_dir = oad_folder / "podcast_transcripts"
    if tx_dir.exists():
        for md in tx_dir.glob("*.md"):
            out = dst / f"{slug}-{md.stem.lower().replace('_','-')}.txt"
            shutil.copy(md, out)
            staged += 1

    # Pick docs (docx)
    try:
        from docx import Document
    except ImportError:
        print("WARN: python-docx not installed — skipping .docx files "
              "(pip install python-docx to enable)")
        return staged

    for docx_path in oad_folder.glob("*.docx"):
        if docx_path.name.startswith("~$"):
            continue
        try:
            doc = Document(docx_path)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            print(f"  skip {docx_path.name}: {e}")
            continue
        if not text.strip() or len(text) < 200:
            continue
        author = docx_path.stem.split()[0].title()
        doc_slug = docx_path.stem.lower().replace(" ", "-")
        out = dst / f"{slug}-{doc_slug}.txt"
        out.write_text(f"By {author}\n\n{text}", encoding="utf-8")
        staged += 1

    return staged


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    oad_folder = Path(sys.argv[1])
    slug = sys.argv[2]
    tournament_name = sys.argv[3] if len(sys.argv) > 3 else slug.replace("-", " ").title()

    if not oad_folder.is_dir():
        print(f"ERROR: {oad_folder} is not a directory")
        sys.exit(1)

    print(f"=== Ingest OAD experts → {slug} ===")
    print(f"Source: {oad_folder}")
    print(f"Tournament: {tournament_name}\n")

    staged = _stage_files(oad_folder, slug)
    print(f"Staged {staged} files into data/raw/expert_articles/\n")

    if not staged:
        print("Nothing to extract. Exiting.")
        sys.exit(0)

    # fetch_betsperts_articles walks data/raw/expert_articles/ and matches
    # files whose stem contains any word from the tournament name.
    content = fetch_betsperts_articles(tournament_name)
    print(f"Loaded {len(content)} content items for extraction")

    if not content:
        print("No content matched — check slug/tournament name alignment.")
        sys.exit(1)

    print("Extracting picks via Claude Haiku (this may take 1–2 min)...")
    picks = extract_all_picks(content)
    print(f"Extracted {len(picks)} picks\n")

    # Build field list from current DG outrights so name matching works
    od = pull_all_outrights(tour="pga")
    field_names = sorted({
        p["player_name"]
        for mkt in ("win", "top_10", "top_20", "make_cut")
        for p in od.get(mkt, [])
    })
    print(f"Field: {len(field_names)} players")

    signals = compute_expert_signals(picks, field_names)
    print(f"Players with signals: {len(signals)}\n")
    print(format_expert_summary(signals))

    out_path = Path("data/raw") / slug / "expert_signals.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(signals, indent=2))
    print(f"\nSaved → {out_path}")
    print(f"\nNext scan will automatically pick up these signals.")


if __name__ == "__main__":
    main()
