#!/usr/bin/env python3
"""
process_paper.py — Single-paper pipeline orchestrator

Processes a single paper (by arXiv URL or ID) through the full pipeline:
  1. Fetch metadata from arXiv
  2. Summarize via Claude
  3. Render to Markdown
  4. Generate audio MP3

Usage:
    python process_paper.py --url https://arxiv.org/pdf/2605.17232
    python process_paper.py --arxiv-id 2605.17232
    python process_paper.py --id 2605.17232
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import re
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EDT = ZoneInfo("America/New_York")
WIKI_DIR = Path(__file__).parent

log = logging.getLogger("process_paper")


def _setup_logging() -> None:
    """Setup logging to both stderr and a log file."""
    log_dir = WIKI_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    date_str = datetime.now(EDT).strftime("%Y%m%d")
    log_file = log_dir / f"process_paper_{date_str}.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def _extract_arxiv_id(url_or_id: str) -> str:
    """Extract arXiv ID from URL or ID string."""
    # If it looks like an ID already (YYMM.NNNNN), return it
    if re.match(r'^\d{4}\.\d{4,5}(?:v\d+)?$', url_or_id.strip()):
        return url_or_id.strip()

    # Otherwise try to extract from URL
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url_or_id)
    if m:
        return m.group(1)

    raise ValueError(f"Could not parse arXiv ID from: {url_or_id}")


def _build_candidate(arxiv_id: str) -> dict:
    """Create a minimal candidate dict for processing."""
    return {
        "id": f"arxiv:{arxiv_id}",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "title": "",
        "source": "cli",
        "added": datetime.now(EDT).isoformat(),
    }


def process(arxiv_id: str, skip_audio: bool = False) -> dict:
    """
    Process a single paper through the pipeline.

    Args:
        arxiv_id: arXiv ID (e.g., "2605.17232")
        skip_audio: if True, skip audio generation (faster for testing)

    Returns:
        The fully processed paper dict with summary, markdown path, and audio path.
    """
    # Late imports so modules can be used standalone
    sys.path.insert(0, str(WIKI_DIR / "src"))
    import fetch as _fetch
    import summarize as _summarize
    import render as _render
    import audio as _audio

    log.info("=" * 60)
    log.info("Processing paper: arxiv:%s", arxiv_id)

    # Stage 1: Create candidate
    candidate = _build_candidate(arxiv_id)
    log.info("Candidate: %s", candidate["id"])

    # Stage 2: Fetch metadata
    log.info("Stage 2: Fetching metadata...")
    try:
        enriched = _fetch.fetch(candidate)
        log.info("  Title: %s", enriched.get("title", "?")[:80])
        log.info("  Authors: %s", ", ".join(enriched.get("authors", [])[:3]))
    except Exception as e:
        log.error("Fetch failed: %s", e)
        raise

    # Stage 3: Summarize
    log.info("Stage 3: Summarizing with Claude...")
    try:
        summarized = _summarize.summarize(enriched)
        log.info("  Category: %s", summarized.get("summary", {}).get("category", "?"))
    except Exception as e:
        log.error("Summarization failed: %s", e)
        raise

    # Stage 4: Render to Markdown
    log.info("Stage 4: Rendering to Markdown...")
    try:
        md_path = _render.render(summarized)
        log.info("  Markdown: %s", md_path)
        summarized["markdown_path"] = str(md_path)
    except Exception as e:
        log.error("Rendering failed: %s", e)
        raise

    # Stage 5: Generate audio
    if not skip_audio:
        log.info("Stage 5: Generating audio...")
        try:
            mp3_path = _audio.synthesize(summarized)
            log.info("  Audio: %s", mp3_path)
            summarized["audio_path"] = str(mp3_path)
        except Exception as e:
            log.error("Audio synthesis failed (non-fatal): %s", e)
            summarized["audio_path"] = None
    else:
        summarized["audio_path"] = None

    log.info("Complete: arxiv:%s", arxiv_id)
    return summarized


def main() -> None:
    """Main entry point."""
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Process a single paper through the PapersWiki pipeline"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--url", help="arXiv PDF or abstract URL")
    grp.add_argument("--arxiv-id", help="arXiv ID (e.g., 2605.17232)")
    grp.add_argument("--id", dest="arxiv_id_alt", help="Alias for --arxiv-id")

    parser.add_argument(
        "--skip-audio", action="store_true",
        help="Skip audio generation (faster, for testing)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full paper dict as JSON"
    )

    args = parser.parse_args()

    # Extract arXiv ID
    url_or_id = args.url or args.arxiv_id or args.arxiv_id_alt
    try:
        arxiv_id = _extract_arxiv_id(url_or_id)
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    # Process the paper
    try:
        result = process(arxiv_id, skip_audio=args.skip_audio)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            # Human-friendly output
            title = result.get("title", "?")
            authors = ", ".join(result.get("authors", [])[:3])
            md_path = result.get("markdown_path")
            audio_path = result.get("audio_path")

            print()
            print("✓ Paper Processed Successfully")
            print("=" * 60)
            print(f"Title:      {title}")
            print(f"Authors:    {authors}")
            if md_path:
                print(f"Markdown:   {md_path}")
            if audio_path:
                print(f"Audio:      {audio_path}")
            print("=" * 60)

    except Exception as e:
        log.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
