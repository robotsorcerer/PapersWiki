"""
pipeline.py — Main Orchestrator

Runs all five stages end-to-end for every unprocessed paper:

  Stage 1 (ingest)    — scan .eml files + papers_to_read.md → candidate list
  Stage 2 (fetch)     — arXiv API + scrape fallback → enriched metadata
  Stage 3 (summarize) — Claude CLI → structured 1-2 page analysis JSON
  Stage 4 (render)    — Markdown files in summaries/<category>/
  Stage 5 (audio)     — MP3 files in audio/<category>/
  Digest              — morning email to you@example.com

Designed to run unattended from cron (EDT):
    0 0 * * * /home/lex/miniconda3/envs/311/bin/python \
        /home/lex/Documents/Papers/PapersWiki/pipeline.py >> \
        /home/lex/Documents/Papers/PapersWiki/logs/pipeline.log 2>&1

Usage (interactive):
    python pipeline.py               # process all pending papers
    python pipeline.py --dry-run     # skip email send
    python pipeline.py --ingest-only # only run stage 1 and print candidates
    python pipeline.py --limit N     # process at most N papers per run
    python pipeline.py --force-rescan # reprocess all known papers
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EDT = ZoneInfo("America/New_York")

WIKI_DIR = Path(__file__).parent

log = logging.getLogger("pipeline")


def _setup_logging() -> None:
    log_dir = WIKI_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    date_str = datetime.now(EDT).strftime("%Y%m%d")
    log_file = log_dir / f"pipeline_{date_str}.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def run(
    dry_run: bool = False,
    ingest_only: bool = False,
    limit: int | None = None,
    force_rescan: bool = False,
    wiki_only: bool = False,
    build_wiki: bool = True,
) -> None:
    # Late imports so stages can be used standalone
    sys.path.insert(0, str(WIKI_DIR / "src"))
    import ingest as _ingest
    import wiki as _wiki

    log.info("=" * 60)
    log.info("PapersWiki pipeline starting — %s", datetime.now(EDT).isoformat())

    # -------------------------------------------------------------------
    # Stage 0: Knowledge base (Karpathy-style LLM Wiki)
    # Compile the raw email_src/ source of truth into a linked wiki/.
    # Deterministic + offline: no API key required. Runs first so the
    # knowledge base always reflects the latest raw alerts.
    # -------------------------------------------------------------------
    if build_wiki or wiki_only:
        log.info("Stage 0: Compile knowledge base (email_src/ -> wiki/)")
        try:
            stats = _wiki.build()
            log.info("Knowledge base: %s", stats)
        except Exception as e:
            log.error("Knowledge base build failed (non-fatal): %s", e, exc_info=True)
        if wiki_only:
            log.info("--wiki-only: skipping paper summarization stages.")
            return

    # Heavy stage imports deferred until we know we need them (so --wiki-only
    # works offline without anthropic/gtts installed).
    import fetch as _fetch
    import summarize as _summarize
    import render as _render
    import audio as _audio
    import digest as _digest

    # -------------------------------------------------------------------
    # Stage 1: Ingest
    # -------------------------------------------------------------------
    log.info("Stage 1: Ingest")
    new_candidates = _ingest.run(wiki_dir=WIKI_DIR, force_rescan=force_rescan)
    # Also include any previously ingested but not-yet-processed candidates
    pending = _ingest.get_pending()
    # Merge: put new ones first, then older pending ones not already in list
    new_ids = {c["id"] for c in new_candidates}
    all_to_process = new_candidates + [p for p in pending if p["id"] not in new_ids]

    log.info("Candidates to process: %d", len(all_to_process))

    if ingest_only:
        print(json.dumps(all_to_process, indent=2))
        return

    if limit is not None:
        all_to_process = all_to_process[:limit]
        log.info("Limiting to %d papers this run", limit)

    if not all_to_process:
        log.info("No new papers. Sending digest with 0 papers.")
        _digest.send_digest([], dry_run=dry_run)
        return

    processed_papers: list[dict] = []

    for i, candidate in enumerate(all_to_process):
        paper_id = candidate["id"]
        log.info("--- [%d/%d] %s ---", i + 1, len(all_to_process), paper_id)

        try:
            # ---------------------------------------------------------------
            # Stage 2: Fetch
            # ---------------------------------------------------------------
            log.info("  Stage 2: Fetch")
            enriched = _fetch.fetch(candidate)

            # ---------------------------------------------------------------
            # Stage 3: Summarize
            # ---------------------------------------------------------------
            log.info("  Stage 3: Summarize")
            summarized = _summarize.summarize(enriched)

            # ---------------------------------------------------------------
            # Stage 4: Render
            # ---------------------------------------------------------------
            log.info("  Stage 4: Render")
            md_path = _render.render(summarized)
            log.info("  Markdown: %s", md_path)

            # ---------------------------------------------------------------
            # Stage 5: Audio
            # ---------------------------------------------------------------
            log.info("  Stage 5: Audio")
            try:
                mp3_path = _audio.synthesize(summarized)
                log.info("  Audio: %s", mp3_path)
            except Exception as e:
                log.warning("  Audio synthesis failed (non-fatal): %s", e)

            # Mark as processed only after all stages succeed
            _ingest.mark_processed(paper_id)
            processed_papers.append(summarized)
            log.info("  Done: %s", paper_id)

        except Exception as e:
            log.error("  FAILED [%s]: %s", paper_id, e, exc_info=True)
            # Do NOT mark as processed — will retry next run

    log.info("Processed %d paper(s) successfully.", len(processed_papers))

    # -------------------------------------------------------------------
    # Digest email
    # -------------------------------------------------------------------
    log.info("Sending digest...")
    try:
        _digest.send_digest(processed_papers, dry_run=dry_run)
    except Exception as e:
        log.error("Digest failed: %s", e)

    log.info("Pipeline complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _setup_logging()
    parser = argparse.ArgumentParser(description="PapersWiki paper processing pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip sending email digest")
    parser.add_argument("--ingest-only", action="store_true",
                        help="Only run ingestion and print candidates")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N papers per run")
    parser.add_argument("--force-rescan", action="store_true",
                        help="Reprocess all known papers (clears processed state)")
    parser.add_argument("--wiki-only", action="store_true",
                        help="Only compile the knowledge base (email_src/ -> wiki/) and exit")
    parser.add_argument("--no-wiki", action="store_true",
                        help="Skip the knowledge-base compile step")
    args = parser.parse_args()

    run(
        dry_run=args.dry_run,
        ingest_only=args.ingest_only,
        limit=args.limit,
        force_rescan=args.force_rescan,
        wiki_only=args.wiki_only,
        build_wiki=not args.no_wiki,
    )
