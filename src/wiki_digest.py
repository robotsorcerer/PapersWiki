"""
wiki_digest.py — Email the Karpathy-style audio distillation of the graph.

The Mon/Wed/Fri 5:00 AM email is NOT a wall of raw summaries. It carries ONE
distilled MP3 (built by src/distill.py) that narrates how the papers that are
new since the last digest thread into the existing knowledge graph, plus a
concise text "show notes" table-of-contents of what the audio covers.

Transport: Gmail SMTP over SSL. Credentials come from the environment
(SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT) — the launchd wrapper loads them
from ~/.zsh_aliases.

Recipient: you@example.com

Usage:
    python src/wiki_digest.py                 # distill new papers + email MP3
    python src/wiki_digest.py --dry-run       # build MP3 + print body, no send
    python src/wiki_digest.py --force-all     # distill the whole graph
    python src/wiki_digest.py --peek          # don't advance the seen-ledger
    python src/wiki_digest.py --max-featured 12
"""
from __future__ import annotations

import argparse
import logging
import mimetypes
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import distill as _distill  # noqa: E402

log = logging.getLogger("wiki_digest")

EDT = ZoneInfo("America/New_York")

DEFAULT_RECIPIENT = "you@example.com"
SMTP_HOST_DEFAULT = "smtp.gmail.com"
SMTP_PORT_DEFAULT = 465


# ---------------------------------------------------------------------------
# Show-notes body (a TOC for the audio, not the raw summaries)
# ---------------------------------------------------------------------------

def build_body(result: dict) -> str:
    notes = result["notes"]
    n_new = notes.get("new_count", 0)
    total = result.get("total_papers", 0)
    now = datetime.now(EDT).strftime("%A, %Y-%m-%d")

    L: list[str] = []
    L.append(f"PapersWiki — Knowledge-Graph Audio Distillation")
    L.append(now)
    L.append("=" * 72)
    L.append("")
    L.append("Attached is a single MP3: a spoken tour of your research second brain,")
    L.append("in the style of Karpathy's LLM Wiki. It narrates how new papers connect")
    L.append("to the existing graph — not a reading of individual abstracts.")
    L.append("")
    L.append(f"Graph size: {total} papers.")
    if n_new == 0:
        L.append("New since last digest: none — the audio revisits the graph's shape.")
    else:
        L.append(f"In this tranche: {n_new} paper(s).")
    remaining = notes.get("remaining_backlog")
    if remaining is not None:
        if remaining > 0:
            L.append(f"Backlog remaining after this email: {remaining} paper(s).")
        else:
            L.append("Backlog remaining: 0 — this tranche empties the queue. 🎉")
    L.append("")

    featured = notes.get("featured", [])
    if featured:
        L.append("-" * 72)
        L.append("IN THIS DISTILLATION (featured new papers):")
        L.append("")
        for i, f in enumerate(featured, 1):
            L.append(f"  [{i}] {f['title']}")
            meta = f"      topic: {f.get('topic', '')}"
            if f.get("researchers"):
                meta += "  |  via: " + ", ".join(f["researchers"])
            L.append(meta)
            if f.get("url"):
                L.append(f"      {f['url']}")
            L.append("")

    topics = notes.get("topics", [])
    if topics:
        L.append("-" * 72)
        L.append("TOPIC CLUSTERS TOUCHED:")
        for t in topics:
            L.append(f"  - {t['topic']}: {t['count']} new")
        L.append("")

    active = notes.get("active_researchers", [])
    if active:
        L.append("-" * 72)
        L.append("MOST ACTIVE RESEARCHERS THIS BATCH:")
        for r in active:
            L.append(f"  - {r['name']}: {r['count']} new paper(s)")
        L.append("")

    hub = notes.get("hub_topics", [])
    if hub:
        L.append("-" * 72)
        L.append("DENSEST HUBS OF THE GRAPH:")
        for disp, cnt in hub:
            L.append(f"  - {disp}: {cnt} papers")
        L.append("")

    L.append("=" * 72)
    L.append("Open wiki/index.md (Obsidian vault) to explore the full graph.")
    L.append("Sent by PapersWiki (Molux Labs).")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send(result: dict, dry_run: bool, recipient: str) -> None:
    body = build_body(result)
    mp3: Path | None = result.get("mp3")

    if dry_run:
        print(body)
        print()
        print(f"[DRY RUN] MP3: {mp3}  ->  would send to {recipient}")
        return

    user = os.getenv("SMTP_USER") or recipient
    password = os.getenv("SMTP_PASS")
    if not password:
        raise RuntimeError("SMTP_PASS not set (source ~/.zsh_aliases before running)")
    host = os.getenv("SMTP_HOST", SMTP_HOST_DEFAULT)
    port = int((os.getenv("SMTP_PORT") or SMTP_PORT_DEFAULT))

    n_new = result["notes"].get("new_count", 0)
    remaining = result["notes"].get("remaining_backlog")
    date_str = datetime.now(EDT).strftime("%Y-%m-%d %a")

    msg = EmailMessage()
    if n_new and remaining is not None and remaining > 0:
        msg["Subject"] = (f"PapersWiki Distillation — {date_str} "
                          f"({n_new} papers, {remaining} in backlog)")
    elif n_new:
        msg["Subject"] = f"PapersWiki Distillation — {date_str} ({n_new} papers)"
    else:
        msg["Subject"] = f"PapersWiki Distillation — {date_str} (graph recap)"
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(body)

    if mp3 and mp3.exists():
        ctype, _ = mimetypes.guess_type(str(mp3))
        maintype, subtype = (ctype or "audio/mpeg").split("/", 1)
        with open(mp3, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=mp3.name)
    else:
        log.warning("No MP3 to attach (mp3=%s)", mp3)

    with smtplib.SMTP_SSL(host, port) as srv:
        srv.login(user, password)
        srv.send_message(msg)
    log.info("distillation emailed to %s (mp3=%s, new=%d)",
             recipient, mp3.name if mp3 else None, n_new)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description="Email the knowledge-graph audio distillation")
    ap.add_argument("--dry-run", action="store_true", help="Build MP3 + print body, do not send")
    ap.add_argument("--force-all", action="store_true", help="Distill the entire graph")
    ap.add_argument("--peek", action="store_true", help="Do not advance the seen-ledger")
    ap.add_argument("--max-featured", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None,
                    help="Distill only the next N unseen papers (one tranche)")
    ap.add_argument("--skip-if-empty", action="store_true",
                    help="If nothing is unseen, exit 0 without sending")
    ap.add_argument("--tag", default=None, help="Filename suffix for the MP3")
    ap.add_argument("--to", default=DEFAULT_RECIPIENT)
    args = ap.parse_args()

    # In --dry-run we still don't want to advance the ledger, so peek there.
    peek = args.peek or args.dry_run
    result = _distill.run(
        script_only=False,
        peek=peek,
        force_all=args.force_all,
        max_featured=args.max_featured,
        limit=args.limit,
        skip_if_empty=args.skip_if_empty,
        tag=args.tag,
    )
    if result.get("skipped"):
        log.info("Backlog empty — no email sent.")
        print("SKIPPED_EMPTY")
        return 0
    send(result, dry_run=args.dry_run, recipient=args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
