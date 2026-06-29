"""
render.py — Stage 4: Markdown Rendering

Converts a summarized paper dict (output of summarize.py) into a rich
Markdown file stored in summaries/<category>/<arxiv_id_or_slug>.md

File naming:
  summaries/control/2603.24566_integral_cbf_input_delay.md
  summaries/ml/2604.21100_preconditioned_deltanet.md
  summaries/robotics/2603.23995_mirror_retargeting.md

Each file follows a fixed template:

  # <Title>
  **Authors**: ...  | **Venue**: ... | **Year**: ... | **Source**: ...
  **URL**: ...

  ## Problem Statement
  ## Methodology
  ## Results & Claims
  ## Strengths
  ## Weaknesses
  ## Related Work Placement
  ## How This Connects to Lekan's Research
  ### Potential Improvements to InfDiff
  ### Potential Improvements to HJ Reachability / Manufacturing Control

The `raw_markdown` field of the summary dict is set to this rendered string.

Usage (CLI):
    cat summarized_paper.json | python render.py --stdin
    python render.py --paper-json '{...}'
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("render")

WIKI_DIR      = Path(__file__).parent.parent
SUMMARIES_DIR = WIKI_DIR / "summaries"

CATEGORIES = ("control", "robotics", "ml", "other")


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _slug(text: str, maxlen: int = 50) -> str:
    """Convert a title or ID to a filesystem-safe slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:maxlen]


def _output_path(paper: dict) -> Path:
    """Compute the output .md file path for a paper."""
    summary  = paper.get("summary", {})
    category = summary.get("category", "other")
    if category not in CATEGORIES:
        category = "other"

    arxiv_id = paper.get("arxiv_id", "")
    title    = paper.get("title", paper.get("id", "unknown"))
    if arxiv_id:
        fname = f"{arxiv_id}_{_slug(title)}.md"
    else:
        # Use title as the slug instead of URL for cleaner filenames
        title_slug = _slug(title)
        fname = f"{title_slug}.md"

    return SUMMARIES_DIR / category / fname


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------

def _authors_str(paper: dict) -> str:
    authors = paper.get("authors", [])
    if not authors:
        return "Unknown Authors"
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + f", et al. ({len(authors)} authors)"


def render(paper: dict) -> Path:
    """
    Render a summarized paper to a Markdown file.
    Returns the path to the written file.
    """
    summary  = paper.get("summary", {})
    out_path = _output_path(paper)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    title    = paper.get("title", "Untitled")
    authors  = _authors_str(paper)
    venue    = paper.get("venue", "")
    year     = paper.get("year", "")
    source   = paper.get("source", "")
    url      = paper.get("url", "")
    category = summary.get("category", "other")

    venue_year = f"{venue}, {year}" if (venue and year) else (venue or year or "N/A")

    lines: list[str] = []

    # Header
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        f"**Authors**: {authors}  |  **Venue**: {venue_year}  |  "
        f"**Category**: {category.upper()}  |  **Source**: {source}"
    )
    lines.append(f"**URL**: <{url}>")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Problem Statement
    lines.append("## Problem Statement")
    lines.append("")
    lines.append(summary.get("problem_statement", "_Not available._"))
    lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append(summary.get("methodology", "_Not available._"))
    lines.append("")

    # Results
    lines.append("## Results & Claims")
    lines.append("")
    lines.append(summary.get("results", "_Not available._"))
    lines.append("")

    # Strengths
    lines.append("## Strengths")
    lines.append("")
    strengths = summary.get("strengths", "_Not available._")
    # Ensure bullet formatting
    if strengths and not strengths.startswith("- ") and "\n" not in strengths:
        strengths = "- " + strengths
    lines.append(strengths)
    lines.append("")

    # Weaknesses
    lines.append("## Weaknesses")
    lines.append("")
    weaknesses = summary.get("weaknesses", "_Not available._")
    if weaknesses and not weaknesses.startswith("- ") and "\n" not in weaknesses:
        weaknesses = "- " + weaknesses
    lines.append(weaknesses)
    lines.append("")

    # Related Work
    lines.append("## Related Work Placement")
    lines.append("")
    lines.append(summary.get("related_work", "_Not available._"))
    lines.append("")

    # Connections to Lekan's Research
    lines.append("## How This Connects to Lekan's Research")
    lines.append("")

    lines.append("### Potential Improvements to InfDiff")
    lines.append("")
    lines.append(summary.get("connections_to_infdiff", "_Not analyzed._"))
    lines.append("")

    lines.append("### Potential Improvements to HJ Reachability / Manufacturing Control")
    lines.append("")
    lines.append(summary.get("connections_to_hj_safety", "_Not analyzed._"))
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated by PapersWiki — {paper.get('added', '')} (EDT)*")

    md_text = "\n".join(lines)

    # Stash raw markdown back into the paper dict for audio stage
    paper.setdefault("summary", {})["raw_markdown"] = md_text

    out_path.write_text(md_text, encoding="utf-8")
    log.info("Rendered: %s", out_path)
    return out_path


def render_all(papers: list[dict]) -> list[Path]:
    paths = []
    for p in papers:
        try:
            paths.append(render(p))
        except Exception as e:
            log.error("Render failed for %s: %s", p.get("id", "?"), e)
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Render summarized papers to Markdown")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--paper-json", help="JSON string of a single summarized paper dict")
    grp.add_argument("--stdin", action="store_true", help="Read JSON list from stdin")
    args = parser.parse_args()

    if args.stdin:
        papers = json.load(sys.stdin)
        if isinstance(papers, dict):
            papers = [papers]
        paths = render_all(papers)
    else:
        paper = json.loads(args.paper_json)
        paths = [render(paper)]

    for p in paths:
        print(str(p))
