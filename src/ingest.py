"""
ingest.py — Stage 1: Paper Ingestion

Scans two input sources and emits a deduplicated list of candidate papers
to process:
  1. All *.eml files in email_src/ (Google Scholar alert emails).
  2. papers_to_read.md in WIKI_DIR.

Each candidate is recorded as a dict:
  {
    "id":      "arxiv:<id>"  | "url:<url>",
    "url":     canonical URL (arxiv abs preferred),
    "title":   str | "",   # extracted from email HTML when available
    "source":  str,        # filename that introduced it
    "added":   ISO-8601 timestamp (EDT)
  }

Processed IDs are persisted in state/processed.json so repeat runs only
yield genuinely new entries.

Usage (CLI):
    python ingest.py [--wiki-dir PATH] [--force-rescan]

    --force-rescan   ignore processed.json and re-emit everything (for debugging)
"""

from __future__ import annotations

import argparse
import email
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

EDT = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WIKI_DIR = Path(__file__).parent.parent
STATE_PATH = WIKI_DIR / "state" / "processed.json"
PAPERS_MD = WIKI_DIR / "papers_to_read.md"
EMAIL_SRC = WIKI_DIR / "email_src"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
# Matches arxiv IDs embedded in URLs (abs or pdf form)
_ARXIV_URL_RE = re.compile(
    r'https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)'
)
# Matches scholar redirect URLs that wrap an arxiv link
_SCHOLAR_URL_RE = re.compile(
    r'https?://scholar\.google\.com/scholar_url\?url=([^&\s>]+)'
)
# Matches bare arxiv IDs in markdown link targets  [Title](https://arxiv.org/...)
_MD_LINK_RE = re.compile(r'\(([^)]+)\)')
# Generic URL fallback (non-arxiv)
_GENERIC_URL_RE = re.compile(r'https?://[^\s<>"\']+')

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_PATH.exists():
        with STATE_PATH.open() as f:
            return json.load(f)
    return {"processed_ids": [], "candidates": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# ArXiv URL canonicalisation
# ---------------------------------------------------------------------------

def _arxiv_abs_url(arxiv_id: str) -> str:
    """Return the canonical abs URL for an arxiv ID."""
    return f"https://arxiv.org/abs/{arxiv_id}"


def _decode_scholar_redirect(url: str) -> str:
    """Unwrap a scholar_url redirect to get the actual target URL."""
    from urllib.parse import unquote
    m = _SCHOLAR_URL_RE.match(url)
    if m:
        return unquote(m.group(1))
    return url


# ---------------------------------------------------------------------------
# EML parsing
# ---------------------------------------------------------------------------

def _parse_eml(path: Path) -> list[tuple[str, str]]:
    """
    Parse a Google Scholar Alert email (.eml file).
    Returns a list of (title, url) tuples extracted from the message.
    """
    if not _HAS_BS4:
        logging.warning("BeautifulSoup not installed; skipping %s", path)
        return []

    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f)

    # Extract HTML body
    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                html = payload.decode("utf-8", errors="replace")
            else:
                html = payload
            break

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Scholar alerts use <a> tags with href to arxiv or other venues
    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = a.get_text(strip=True)

        if not href:
            continue

        # Unwrap Google Scholar redirects
        if "scholar.google.com/scholar_url" in href:
            href = _decode_scholar_redirect(href)

        # Keep non-empty URLs
        if href.startswith("http"):
            items.append((title, href))

    return items


# ---------------------------------------------------------------------------
# Rich record parsing (for the knowledge-base / wiki compiler)
# ---------------------------------------------------------------------------
# Unlike _parse_eml (which only yields (title, url) pairs for the paper
# pipeline), parse_eml_records() extracts a structured record per paper:
# title, url, authors, venue, year, snippet and the *followed researcher*
# that surfaced the alert. It is implemented with the standard library only
# (no BeautifulSoup) so the wiki compiler runs in any environment.

import html as _html_mod

# A Google Scholar alert article block: an <h3> title (optionally a link),
# a green author/venue line (color:#006621) and a snippet div.
_H3_SPLIT_RE = re.compile(r'<h3\b', re.IGNORECASE)
_TITLE_LINK_RE = re.compile(
    r'<a\b[^>]*class="[^"]*gse_alrt_title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_ANY_LINK_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                                re.IGNORECASE | re.DOTALL)
_TITLE_TEXT_RE = re.compile(r'>(.*?)</h3>', re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(r'color:#006621[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)
_SNIPPET_RE = re.compile(
    r'<div\b[^>]*(?:class="[^"]*gse_alrt_sni[^"]*"|style="[^"]*)[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_FOLLOWING_ANCHOR_RE = re.compile(
    r'following new articles (?:written by|related to|in)\s*<a\b[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_FOLLOWING_PLAIN_RE = re.compile(
    r'following new articles (?:written by|related to|in)\s*([^<]+?)\s*\.?\s*</p>',
    re.IGNORECASE | re.DOTALL,
)
_YEAR_RE = re.compile(r'(19|20)\d{2}\b')
# adsabs / other wrappers that embed an arxiv id, e.g. 2026arXiv260520676N
_ARXIV_EMBED_RE = re.compile(r'arxiv[:/]?(\d{2})(\d{2})\.?(\d{4,5})', re.IGNORECASE)


def _strip_tags(fragment: str) -> str:
    """Remove HTML tags and unescape entities, collapsing whitespace."""
    text = re.sub(r'<[^>]+>', '', fragment or '')
    text = _html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def canonical_arxiv_id(url: str) -> str | None:
    """Return a YYMM.NNNNN arxiv id if one can be recovered from the URL."""
    m = _ARXIV_URL_RE.search(url)
    if m:
        return m.group(1)
    m = _ARXIV_EMBED_RE.search(url)
    if m:
        return f"{m.group(1)}{m.group(2)}.{m.group(3)}"
    return None


def _split_authors(authors_str: str) -> tuple[list[str], bool]:
    """Split a Scholar author line into a list; flag if it was truncated (…)."""
    truncated = "…" in authors_str or "..." in authors_str
    cleaned = authors_str.replace("…", "").replace("...", "").strip()
    authors = [a.strip() for a in cleaned.split(",") if a.strip()]
    return authors, truncated


def _followed_from_subject(subject: str) -> str:
    """'Daniela Rus - new articles' -> 'Daniela Rus'."""
    subj = (subject or "").strip()
    for sep in (" - new articles", " - new citations", " - new results"):
        if subj.endswith(sep):
            return subj[: -len(sep)].strip()
    # Fallback: drop a trailing ' - ...' clause
    if " - " in subj:
        return subj.rsplit(" - ", 1)[0].strip()
    return subj


def parse_eml_records(path: Path) -> list[dict]:
    """
    Parse a Google Scholar Alert email into structured per-paper records.

    Returns a list of dicts, one per article:
      {
        "title", "url", "arxiv_id", "authors" (list), "authors_truncated",
        "venue", "year", "snippet", "followed", "source", "date"
      }
    Implemented with the stdlib only (regex over the decoded HTML body).
    """
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f)

    subject = str(msg.get("Subject", "") or "")
    date_hdr = str(msg.get("Date", "") or "")
    followed = _followed_from_subject(subject)

    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
            break
    if not html:
        return []

    # Refine the followed researcher from the body footer when present.
    m = _FOLLOWING_ANCHOR_RE.search(html) or _FOLLOWING_PLAIN_RE.search(html)
    if m:
        body_followed = _strip_tags(m.group(1))
        if body_followed:
            followed = body_followed

    records: list[dict] = []
    # Each article begins at an <h3>. Split and process the trailing chunks.
    chunks = _H3_SPLIT_RE.split(html)
    for chunk in chunks[1:]:
        block = "<h3" + chunk

        # Title + URL
        url, title = "", ""
        lm = _TITLE_LINK_RE.search(block)
        if not lm:
            lm = _TITLE_ANY_LINK_RE.search(block)
        if lm:
            url = lm.group(1).strip()
            title = _strip_tags(lm.group(2))
        else:
            tm = _TITLE_TEXT_RE.search(block)
            if tm:
                title = _strip_tags(tm.group(1))

        if not title:
            continue

        if url and "scholar.google.com/scholar_url" in url:
            url = _decode_scholar_redirect(url)
        url = _html_mod.unescape(url)

        # Authors / venue / year
        authors, authors_truncated, venue, year = [], False, "", ""
        mm = _META_RE.search(block)
        if mm:
            meta = _strip_tags(mm.group(1))
            authors_part, venue_part = meta, ""
            if " - " in meta:
                authors_part, venue_part = meta.rsplit(" - ", 1)
            authors, authors_truncated = _split_authors(authors_part)
            ym = _YEAR_RE.search(venue_part)
            if ym:
                year = ym.group(0)
                venue = venue_part[: ym.start()].strip(" ,")
            else:
                venue = venue_part.strip(" ,")

        # Snippet: first content div that is not the author line.
        snippet = ""
        for sm in _SNIPPET_RE.finditer(block):
            cand = _strip_tags(sm.group(1))
            if cand and "color:#006621" not in sm.group(0) and cand != ", ".join(authors):
                # Skip the footer "This message was sent by Google Scholar…"
                if cand.lower().startswith("this message was sent"):
                    continue
                snippet = cand
                break

        records.append({
            "title": title,
            "url": url,
            "arxiv_id": canonical_arxiv_id(url) if url else None,
            "authors": authors,
            "authors_truncated": authors_truncated,
            "venue": venue,
            "year": year,
            "snippet": snippet,
            "followed": followed,
            "source": path.name,
            "date": date_hdr,
        })

    return records


def parse_all_records(email_src: Path = EMAIL_SRC) -> list[dict]:
    """Parse every *.eml file in email_src/ into a flat list of records."""
    all_records: list[dict] = []
    for eml_path in sorted(email_src.glob("*.eml")):
        try:
            all_records.extend(parse_eml_records(eml_path))
        except Exception as e:  # pragma: no cover - defensive
            logging.warning("Failed to parse records from %s: %s", eml_path.name, e)
    return all_records


# ---------------------------------------------------------------------------
# Paper URL fetching
# ---------------------------------------------------------------------------

def _fetch_paper_url(title: str, log: logging.Logger) -> str | None:
    """
    Attempt to fetch a paper URL from its title/citation.
    Tries arXiv API, then falls back to logging for manual intervention.
    """
    import urllib.request
    import urllib.parse

    # Try arXiv API search
    try:
        query = urllib.parse.quote(title)
        url = f"http://export.arxiv.org/api/query?search_query=all:{query}&max_results=1"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = response.read().decode("utf-8")
            # Simple XML parsing for arXiv ID
            import re as re_local
            m = re_local.search(r'arxiv.org/abs/(\d{4}\.\d{4,5})', data)
            if m:
                arxiv_id = m.group(1)
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                log.info("Found arXiv paper for '%s': %s", title[:50], arxiv_url)
                return arxiv_url
    except Exception as e:
        log.debug("arXiv search failed for '%s': %s", title[:50], e)

    # Log for manual lookup
    log.warning(
        "Could not auto-fetch URL for paper: %s\n"
        "  Please add a markdown link or manual URL to papers_to_read.md",
        title[:100]
    )
    return None


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _parse_papers_md(path: Path) -> list[tuple[str, str, bool]]:
    """
    Parse papers_to_read.md.
    Extracts markdown links [Title](URL) → (title, url, has_link).
    Also extracts plain text entries (papers without links) → (title, "", False).
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    items = []
    processed_lines = set()

    # First pass: extract markdown links [Title](URL)
    link_pattern = r'\[([^\]]*)\]\((https?://[^\)]+)\)'
    for m in re.finditer(link_pattern, text):
        title = m.group(1).strip()
        url = m.group(2).strip()
        if title and url:
            items.append((title, url, True))
            # Track which lines had links
            processed_lines.add(m.start())

    # Second pass: extract plain text entries (+ title) without links
    plain_pattern = r'^\s*\+\s+(.+?)$'
    for m in re.finditer(plain_pattern, text, re.MULTILINE):
        entry_text = m.group(1).strip()
        # Skip if this line contains a markdown link (already processed)
        if '[' in entry_text and ']' in entry_text and '(' in entry_text:
            continue
        # Skip if empty
        if entry_text:
            items.append((entry_text, "", False))

    return items


# ---------------------------------------------------------------------------
# Paper ID generation
# ---------------------------------------------------------------------------

def _make_id(url: str) -> str:
    """Generate a stable ID from a URL."""
    # If arxiv, extract the ID
    m = _ARXIV_URL_RE.search(url)
    if m:
        return f"arxiv:{m.group(1)}"

    # Otherwise, use URL hash
    import hashlib
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"url:{url_hash}"


# ---------------------------------------------------------------------------
# Main ingest logic
# ---------------------------------------------------------------------------

def run(wiki_dir: Path = WIKI_DIR, force_rescan: bool = False) -> list[dict]:
    """
    Scan input sources and emit deduplicated list of new candidates.
    Returns list of candidate dicts: {id, url, title, source, added}.
    """
    log = logging.getLogger("ingest")
    state = _load_state() if not force_rescan else {}

    processed_ids = set(state.get("processed_ids", []))
    log.info("Found %d .eml files", len(list(EMAIL_SRC.glob("*.eml"))))

    candidates_by_id = {}

    # Parse .eml files
    for eml_path in sorted(EMAIL_SRC.glob("*.eml")):
        try:
            items = _parse_eml(eml_path)
            for title, url in items:
                cand_id = _make_id(url)
                if cand_id not in processed_ids and cand_id not in candidates_by_id:
                    candidates_by_id[cand_id] = {
                        "id": cand_id,
                        "url": url,
                        "title": title,
                        "source": eml_path.name,
                        "added": datetime.now(EDT).isoformat(),
                    }
        except Exception as e:
            log.warning("Failed to parse %s: %s", eml_path.name, e)

    # Parse papers_to_read.md
    try:
        items = _parse_papers_md(PAPERS_MD)
        for title, url, has_link in items:
            # If no URL, attempt to fetch it online
            if not url and has_link is False:
                fetched_url = _fetch_paper_url(title, log)
                if fetched_url:
                    url = fetched_url

            if url:  # Only add if we have a URL
                cand_id = _make_id(url)
                if cand_id not in processed_ids and cand_id not in candidates_by_id:
                    candidates_by_id[cand_id] = {
                        "id": cand_id,
                        "url": url,
                        "title": title,
                        "source": "papers_to_read.md",
                        "added": datetime.now(EDT).isoformat(),
                    }
    except Exception as e:
        log.warning("Failed to parse papers_to_read.md: %s", e)

    log.info("papers_to_read.md -> %d candidates", len([c for c in candidates_by_id.values() if c["source"] == "papers_to_read.md"]))

    new_candidates = list(candidates_by_id.values())
    log.info(
        "Total unique candidates: %d | Already processed: %d | New: %d",
        len(candidates_by_id),
        len(processed_ids),
        len(new_candidates),
    )

    return new_candidates


def get_pending() -> list[dict]:
    """Return list of candidates that were ingested but not yet processed."""
    state = _load_state()
    return state.get("candidates", [])


def mark_processed(paper_id: str) -> None:
    """Mark a paper ID as processed."""
    state = _load_state()
    if paper_id not in state.get("processed_ids", []):
        state.setdefault("processed_ids", []).append(paper_id)
    _save_state(state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Ingest papers from .eml + markdown sources")
    parser.add_argument("--wiki-dir", type=Path, default=WIKI_DIR,
                        help="Path to PapersWiki root")
    parser.add_argument("--force-rescan", action="store_true",
                        help="Ignore processed.json and re-emit all")
    args = parser.parse_args()

    WIKI_DIR = args.wiki_dir
    candidates = run(wiki_dir=args.wiki_dir, force_rescan=args.force_rescan)
    print(json.dumps(candidates, indent=2))
