"""
digest.py — Morning Digest Email

Sends a daily 6 AM EDT summary email to $GMAIL_USER/$SMTP_USER listing the papers
processed in the past 24 hours. For each paper includes:
  - Title, venue, category
  - 2-sentence lead (problem statement)
  - Key connection to Lekan's work (InfDiff or HJ)
  - Link to the full markdown summary
  - Link to the audio MP3

Transport: Gmail SMTP via App Password stored in environment variable.

Required environment variables:
    SMTP_PASS        — Gmail App Password (not the account password)
                       Generate at: myaccount.google.com/apppasswords
    GMAIL_USER       — (optional) sender address, default $SMTP_USER

All times are in EDT (Eastern Daylight Time, UTC-4).

Usage (CLI):
    python digest.py --papers-json '[{...}, ...]'
    cat processed_today.json | python digest.py --stdin
    python digest.py --dry-run --stdin   # print email without sending
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("digest")

GMAIL_USER_DEFAULT = os.getenv("SMTP_USER", "")
SMTP_HOST          = "smtp.gmail.com"
SMTP_PORT          = 465   # SSL
WIKI_DIR           = Path(__file__).parent.parent
EDT                = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Email body construction
# ---------------------------------------------------------------------------

def _paper_block(paper: dict, index: int) -> str:
    """Render a single paper entry for the email body."""
    summary  = paper.get("summary", {})
    title    = paper.get("title", "Untitled")
    venue    = paper.get("venue", "")
    year     = paper.get("year", "")
    category = summary.get("category", "other").upper()
    url      = paper.get("url", "")
    venue_year = f"{venue}, {year}" if (venue and year) else (venue or year or "arXiv")

    prob     = summary.get("problem_statement", "")
    # Truncate to first 2 sentences
    prob_short = ". ".join(prob.split(". ")[:2]).strip()
    if prob_short and not prob_short.endswith("."):
        prob_short += "."

    # Connection hook — prefer InfDiff; fall back to HJ
    conn = summary.get("connections_to_infdiff", "")
    conn_label = "InfDiff connection"
    if not conn or "not directly applicable" in conn.lower():
        conn = summary.get("connections_to_hj_safety", "")
        conn_label = "HJ/Manufacturing connection"
    # Take first sentence only
    conn_short = conn.split(". ")[0].strip() if conn else ""
    if conn_short and not conn_short.endswith("."):
        conn_short += "."

    # Audio file path
    audio_paths = list(WIKI_DIR.glob(f"audio/**/*{paper.get('arxiv_id', '')}*.mp3"))
    audio_link  = str(audio_paths[0]) if audio_paths else "(audio not generated)"

    lines = [
        f"[{index}] {title}",
        f"    Venue: {venue_year}  |  Category: {category}",
        f"    URL:   {url}",
        "",
        f"    Problem: {prob_short}",
        f"    {conn_label}: {conn_short}",
        "",
        f"    Summary: summaries/{summary.get('category', 'other')}/{paper.get('id', '?').split(':')[-1]}.md",
        f"    Audio:   {audio_link}",
        "",
        "    " + "-" * 70,
    ]
    return "\n".join(lines)


def send_digest(papers: list[dict], dry_run: bool = False) -> None:
    """
    Compile and send the morning digest email.
    Groups papers by category and includes connection hooks.
    """
    date_str = datetime.now(EDT).strftime("%Y-%m-%d")

    # Group by category
    by_category = {}
    for p in papers:
        cat = p.get("summary", {}).get("category", "other")
        by_category.setdefault(cat, []).append(p)

    # Build email body
    lines = [
        f"PapersWiki Daily Digest — {date_str} (EDT)",
        f"{len(papers)} new paper(s) processed.",
        "=" * 78,
        "",
    ]

    for category in ["control", "robotics", "ml", "other"]:
        if category not in by_category:
            continue
        cat_papers = by_category[category]
        lines.append("")
        lines.append("=" * 30 + f"  {category.upper()}  " + "=" * 30)
        lines.append("")

        for i, paper in enumerate(cat_papers, 1):
            lines.append(_paper_block(paper, i))
            lines.append("")

    lines.extend([
        "=" * 78,
        "Sent by PapersWiki (Molux Labs).",
    ])

    body = "\n".join(lines)

    if dry_run:
        log.info("[DRY RUN] Email not sent. Body:\n%s", body)
        return

    # Send via Gmail
    user = os.getenv("GMAIL_USER", GMAIL_USER_DEFAULT)
    password = os.getenv("SMTP_PASS")

    if not password:
        raise RuntimeError("SMTP_PASS environment variable not set")

    msg = EmailMessage()
    msg["Subject"] = f"PapersWiki Daily Digest — {date_str} (EDT)"
    msg["From"] = user
    msg["To"] = user
    msg.set_content(body)

    # Attach MP3s for each paper
    for paper in papers:
        arxiv_id = paper.get("arxiv_id", "")
        if arxiv_id:
            audio_paths = list(WIKI_DIR.glob(f"audio/**/*{arxiv_id}*.mp3"))
            for audio_path in audio_paths:
                try:
                    with open(audio_path, "rb") as f:
                        msg.add_attachment(f.read(), maintype="audio", subtype="mpeg",
                                         filename=audio_path.name)
                except Exception as e:
                    log.warning("Failed to attach audio %s: %s", audio_path, e)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(user, password)
        server.send_message(msg)

    log.info("Email sent to %s", user)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Send PapersWiki digest email")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--papers-json", help="JSON string of papers list")
    grp.add_argument("--stdin", action="store_true", help="Read JSON list from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Print email without sending")
    args = parser.parse_args()

    if args.stdin:
        papers = json.load(sys.stdin)
        if isinstance(papers, dict):
            papers = [papers]
    else:
        papers = json.loads(args.papers_json)

    send_digest(papers, dry_run=args.dry_run)
