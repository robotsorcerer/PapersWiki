#!/usr/bin/env python3
"""
process_paper_universal.py — Process papers from ANY source

Handles multiple input types:
  - arXiv URLs/IDs:           https://arxiv.org/pdf/2605.17232 or 2605.17232
  - PDF URLs:                 https://example.com/paper.pdf
  - Websites:                 https://example.com/paper-page
  - PDF files:                /path/to/paper.pdf
  - Email files:              /path/to/paper.eml (extracts arXiv links or PDFs)
  - Plain text:               "Title: ... Authors: ... Abstract: ..."

All inputs are converted to a standard candidate dict and processed through:
  1. Fetch metadata (from arXiv API, website scrape, or PDF extraction)
  2. Render to Markdown
  3. Generate audio MP3

Usage:
    # arXiv
    python process_paper_universal.py 2605.17232
    python process_paper_universal.py https://arxiv.org/pdf/2605.17232

    # PDF
    python process_paper_universal.py https://example.com/paper.pdf
    python process_paper_universal.py /local/path/to/paper.pdf

    # Website
    python process_paper_universal.py https://example.com/research/paper

    # Email
    python process_paper_universal.py /path/to/email.eml

    # Text with metadata
    python process_paper_universal.py "Title: My Paper\\nAuthors: John Doe\\nAbstract: ..."

    # Batch mode
    python process_paper_universal.py --stdin < papers.txt
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

log = logging.getLogger("process_paper_universal")


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


def process(input_str: str, skip_audio: bool = False, no_api: bool = True) -> dict:
    """
    Process paper from any source.

    Args:
        input_str: Paper source (arXiv, URL, file, text, etc.)
        skip_audio: Skip MP3 generation if True
        no_api: Use abstract-only mode if True (recommended)

    Returns:
        Processed paper dict with markdown_path and audio_path
    """
    sys.path.insert(0, str(WIKI_DIR / "src"))
    from input_handler import detect_and_process
    import fetch as _fetch
    import render as _render
    import audio as _audio

    log.info("=" * 60)
    log.info("Processing: %s", input_str[:80])

    # Stage 1: Detect and process input
    log.info("Stage 1: Detecting input type and extracting metadata...")
    try:
        candidate = detect_and_process(input_str)
        log.info("  Input type: %s", candidate.get("source", "unknown"))
        log.info("  Title: %s", candidate.get("title", "?")[:80])
    except Exception as e:
        log.error("Input processing failed: %s", e)
        raise

    # Stage 2: Enrich metadata (only if we don't already have what we need)
    log.info("Stage 2: Enriching metadata...")
    try:
        # If source is arXiv or website, fetch additional metadata
        if candidate.get("source") in ("arxiv", "website"):
            enriched = _fetch.fetch(candidate)
            log.info("  Title: %s", enriched.get("title", "?")[:80])
            log.info("  Authors: %s", ", ".join(enriched.get("authors", [])[:3]))
        else:
            enriched = candidate

    except Exception as e:
        log.error("Fetch enrichment failed (continuing with candidate): %s", e)
        enriched = candidate

    # Stage 3: Create summary (abstract-only fallback)
    log.info("Stage 3: Creating summary...")
    if no_api:
        # Abstract-only mode
        summary_dict = _create_fallback_summary(enriched)
    else:
        # Would use Claude here, but for now just fallback
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

    log.info("Complete: %s", input_str[:80])
    return summarized


def _create_fallback_summary(paper: dict) -> dict:
    """Create summary from abstract and metadata."""
    abstract = paper.get("abstract", "")
    title = paper.get("title", "Unknown")

    # Infer category
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

    # Extract problem statement from abstract
    sentences = [s.strip() for s in abstract.split('.') if s.strip()]
    problem_stmt = sentences[0] if sentences else abstract[:200]
    if not problem_stmt.endswith('.'):
        problem_stmt += '.'

    return {
        "problem_statement": problem_stmt,
        "methodology": "See abstract below for full details.",
        "results": abstract,
        "strengths": "- The paper addresses a research question.",
        "weaknesses": "- This summary was generated from available metadata.",
        "related_work": "Refer to the paper for literature context.",
        "connections_to_infdiff": "Not determined.",
        "connections_to_hj_safety": "Not determined.",
        "category": category,
        "raw_markdown": "",
    }


def main() -> None:
    """Main entry point."""
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Process papers from ANY source (arXiv, PDF, website, email, text)",
        epilog="""
Examples:
  %(prog)s 2605.17232
  %(prog)s https://arxiv.org/pdf/2605.17232
  %(prog)s https://example.com/paper.pdf
  %(prog)s /path/to/paper.pdf
  %(prog)s https://example.com/research
  %(prog)s /path/to/paper.eml
  %(prog)s "Title: My Paper\\nAuthors: John Doe\\nAbstract: ..."
  cat papers.txt | %(prog)s --stdin
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("input", nargs='?', help="Paper source (URL, file, ID, or text)")
    grp.add_argument("--stdin", action="store_true",
                     help="Process multiple inputs from stdin (one per line)")

    parser.add_argument("--skip-audio", action="store_true",
                        help="Skip audio generation (faster, markdown only)")
    parser.add_argument("--json", action="store_true",
                        help="Output full paper dict as JSON")
    parser.add_argument("--no-api", action="store_true", default=True,
                        help="Use abstract-only mode (recommended, no API needed)")

    args = parser.parse_args()

    if args.stdin:
        # Batch mode
        inputs = [line.strip() for line in sys.stdin if line.strip()]
        results = []
        for inp in inputs:
            try:
                result = process(inp, skip_audio=args.skip_audio, no_api=args.no_api)
                results.append(result)
            except Exception as e:
                log.error("Failed: %s — %s", inp[:80], e)

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                _print_result(r)

    else:
        # Single input
        try:
            result = process(args.input, skip_audio=args.skip_audio, no_api=args.no_api)

            if args.json:
                print(json.dumps(result, indent=2))
            else:
                _print_result(result)

        except Exception as e:
            log.error("Pipeline failed: %s", e, exc_info=True)
            sys.exit(1)


def _print_result(result: dict) -> None:
    """Print human-friendly result."""
    title = result.get("title", "?")
    authors = ", ".join(result.get("authors", [])[:3])
    md_path = result.get("markdown_path")
    audio_path = result.get("audio_path")
    source = result.get("source", "?")

    print()
    print("✓ Paper Processed Successfully")
    print("=" * 60)
    print(f"Source:     {source}")
    print(f"Title:      {title}")
    if authors:
        print(f"Authors:    {authors}")
    if md_path:
        print(f"Markdown:   {md_path}")
    if audio_path:
        print(f"Audio:      {audio_path}")
        print()
        print("📻 Ready to listen!")
    print("=" * 60)


if __name__ == "__main__":
    main()
