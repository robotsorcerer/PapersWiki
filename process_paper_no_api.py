#!/usr/bin/env python3
"""
process_paper_no_api.py — Paper pipeline with abstract-only fallback

When Anthropic API is unavailable or out of credits, this variant:
  1. Fetches metadata from arXiv
  2. Uses the abstract as the primary source for audio narration
  3. Generates audio directly from abstract + metadata

Generates markdown and audio files even without Claude summarization.

Usage:
    python process_paper_no_api.py --url https://arxiv.org/pdf/2605.17232
    python process_paper_no_api.py --arxiv-id 2605.17232
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

log = logging.getLogger("process_paper_no_api")


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
    if re.match(r'^\d{4}\.\d{4,5}(?:v\d+)?$', url_or_id.strip()):
        return url_or_id.strip()

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


def _create_fallback_summary(paper: dict) -> dict:
    """
    Create a summary dict using just the abstract and metadata.
    This is a lightweight alternative when Claude API is unavailable.
    """
    abstract = paper.get("abstract", "")
    title = paper.get("title", "Unknown")

    # Infer category from title and abstract
    text = (title + " " + abstract).lower()
    if any(w in text for w in (
        "barrier function", "reachability", "lyapunov", "lqr", "mpc",
        "nash equilibrium", "optimal control", "cbf", "hamilton-jacobi",
    )):
        category = "control"
    elif any(w in text for w in (
        "robot", "manipulation", "locomotion", "grasping", "navigation",
        "exoskeleton", "teleoperation",
    )):
        category = "robotics"
    elif any(w in text for w in (
        "diffusion", "transformer", "neural", "language model", "llm",
        "reinforcement learning", "imitation", "score", "gpt", "vla",
    )):
        category = "ml"
    else:
        category = "other"

    # Extract first few sentences from abstract as the problem statement
    sentences = [s.strip() for s in abstract.split('.') if s.strip()]
    problem_stmt = sentences[0] if sentences else abstract[:200]
    if not problem_stmt.endswith('.'):
        problem_stmt += '.'

    return {
        "problem_statement": problem_stmt,
        "methodology": "See abstract below for full details.",
        "results": abstract,  # Use full abstract as results
        "strengths": "- The paper addresses an important research question.",
        "weaknesses": "- This summary was generated from abstract only (API unavailable).",
        "related_work": "Refer to the paper for literature context.",
        "connections_to_infdiff": "Not determined (summarization unavailable).",
        "connections_to_hj_safety": "Not determined (summarization unavailable).",
        "category": category,
        "raw_markdown": "",
    }


def process(arxiv_id: str, skip_audio: bool = False) -> dict:
    """
    Process a single paper through the pipeline.
    Uses abstract-only fallback if Anthropic API is unavailable.
    """
    sys.path.insert(0, str(WIKI_DIR / "src"))
    import fetch as _fetch
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

    # Stage 3: Create fallback summary (abstract-based)
    log.info("Stage 3: Creating fallback summary from abstract...")
    summary_dict = _create_fallback_summary(enriched)
    summarized = dict(enriched)
    summarized["summary"] = summary_dict

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
        description="Process a single paper (abstract-only fallback mode)"
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
                print()
                print("📻 You can now listen to the paper summary!")
            print("=" * 60)

    except Exception as e:
        log.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
