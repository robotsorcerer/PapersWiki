"""
fetch.py — Stage 2: Paper Metadata & Abstract Fetching

Given a candidate dict from ingest.py, fetches:
  - title (if not already known)
  - authors
  - venue / year
  - abstract

Primary: arXiv API (https://export.arxiv.org/api/query)
Fallback: direct HTTP scrape of the abs page for non-arxiv URLs

Returns an enriched candidate dict with keys:
  "title", "authors", "venue", "year", "abstract", "pdf_url"

Usage (CLI):
    python fetch.py --id arxiv:2603.24566
    python fetch.py --url https://arxiv.org/abs/2603.24566
    cat state/processed.json | python fetch.py --stdin  # reads candidates from stdin JSON
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

log = logging.getLogger("fetch")

ARXIV_API = "https://export.arxiv.org/api/query"
FETCH_DELAY = 1.0   # seconds between API calls — respect arXiv rate limits
TIMEOUT     = 20    # seconds per request

# ---------------------------------------------------------------------------
# ArXiv API helpers
# ---------------------------------------------------------------------------

def _arxiv_id_from_url(url: str) -> Optional[str]:
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    return m.group(1) if m else None


def _fetch_arxiv_api(arxiv_id: str) -> dict:
    """Call the arXiv Atom API and return a metadata dict."""
    params = urlencode({"id_list": arxiv_id, "max_results": "1"})
    url = f"{ARXIV_API}?{params}"
    log.debug("ArXiv API: %s", url)

    req = Request(url, headers={"User-Agent": "PapersWiki-fetcher/1.0 (you@example.com)"})
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise RuntimeError(f"arXiv API request failed: {e}") from e

    # Parse Atom XML
    # Extract the entry block (contains the actual paper metadata)
    # The feed-level <title> contains the query string, not the paper title
    entry_m = re.search(r'<entry>(.*?)</entry>', xml, re.DOTALL)
    if not entry_m:
        raise RuntimeError(f"No entry found in arXiv response for {arxiv_id}")

    entry = entry_m.group(1)

    # Use regex to avoid lxml dependency
    def _first(pattern: str, text: str | None = None, default: str = "") -> str:
        search_text = text if text is not None else entry
        m = re.search(pattern, search_text, re.DOTALL)
        return m.group(1).strip() if m else default

    def _all(pattern: str, text: str | None = None) -> list[str]:
        search_text = text if text is not None else entry
        return [m.strip() for m in re.findall(pattern, search_text, re.DOTALL)]

    title    = re.sub(r'\s+', ' ', _first(r'<title[^>]*>(.*?)</title>').replace("\n", " "))
    # Remove leading "v\d+" arXiv prefix that sometimes appears
    title    = re.sub(r'^\[\d{4}\.\d+\]\s*', '', title)
    abstract = re.sub(r'\s+', ' ', _first(r'<summary[^>]*>(.*?)</summary>'))
    authors  = _all(r'<author[^>]*>.*?<name>(.*?)</name>')
    # arXiv category often serves as a proxy for venue
    cats     = _all(r'<category\s+term="([^"]+)"')
    year_m   = re.search(r'<published>(\d{4})', entry)
    year     = year_m.group(1) if year_m else ""
    pdf_url  = f"https://arxiv.org/pdf/{arxiv_id}"

    venue = "arXiv"
    if cats:
        venue = f"arXiv [{', '.join(cats[:2])}]"

    return {
        "arxiv_id": arxiv_id,
        "title":    title or f"arXiv:{arxiv_id}",
        "authors":  authors,
        "venue":    venue,
        "year":     year,
        "abstract": abstract,
        "pdf_url":  pdf_url,
    }


# ---------------------------------------------------------------------------
# HTML scrape fallback for non-arXiv URLs
# ---------------------------------------------------------------------------

def _scrape_url(url: str) -> dict:
    """
    Best-effort HTML scrape of a paper abs/landing page.
    Returns whatever can be extracted; fields may be empty strings.
    """
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 PapersWiki-fetcher/1.0",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        log.warning("Scrape failed for %s: %s", url, e)
        return {"title": "", "authors": [], "venue": "", "year": "", "abstract": "", "pdf_url": url}

    title    = ""
    abstract = ""
    authors  = []

    if _HAS_BS4:
        soup = BeautifulSoup(raw, "html.parser")
        # Try OG tags first (most reliable across sites)
        og_title = soup.find("meta", {"property": "og:title"})
        og_desc  = soup.find("meta", {"property": "og:description"})
        title    = (og_title.get("content", "") if og_title else
                    soup.title.get_text(strip=True) if soup.title else "")
        abstract = og_desc.get("content", "") if og_desc else ""
        # ACM / Springer / IEEE author tags
        for meta in soup.find_all("meta", {"name": re.compile(r"citation_author", re.I)}):
            a = meta.get("content", "").strip()
            if a:
                authors.append(a)
        # arXiv abs page fallback (in case _ARXIV_ID check missed it)
        abs_div = soup.find("blockquote", class_="abstract")
        if abs_div:
            abstract = abs_div.get_text(strip=True).replace("Abstract:", "").strip()
    else:
        # Regex fallback
        m = re.search(r'<title[^>]*>(.*?)</title>', raw, re.DOTALL | re.I)
        title = m.group(1).strip() if m else ""
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', raw, re.I)
        abstract = m.group(1) if m else ""

    year_m = re.search(r'\b(20\d{2})\b', raw)
    year   = year_m.group(1) if year_m else ""

    return {
        "title":    title.strip(),
        "authors":  authors,
        "venue":    "",    # can't reliably extract venue from HTML
        "year":     year,
        "abstract": abstract.strip(),
        "pdf_url":  url,
    }


# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch(candidate: dict) -> dict:
    """
    Enrich a candidate dict with full metadata.
    candidate must have "id" and "url" keys.
    Returns the candidate dict augmented with metadata keys.
    """
    result = dict(candidate)
    url    = candidate.get("url", "")
    pid    = candidate.get("id", "")

    arxiv_id = None
    if pid.startswith("arxiv:"):
        arxiv_id = pid[len("arxiv:"):]
    else:
        arxiv_id = _arxiv_id_from_url(url)

    if arxiv_id:
        try:
            meta = _fetch_arxiv_api(arxiv_id)
            result.update(meta)
            log.info("Fetched (arXiv): %s — %s", arxiv_id, result.get("title", "")[:80])
        except Exception as e:
            log.warning("arXiv API failed for %s: %s — falling back to scrape", arxiv_id, e)
            meta = _scrape_url(url)
            result.update(meta)
    else:
        # Non-arXiv URL
        log.info("Fetching (scrape): %s", url)
        meta = _scrape_url(url)
        result.update(meta)

    # Ensure a fallback title
    if not result.get("title"):
        result["title"] = url

    time.sleep(FETCH_DELAY)
    return result


def fetch_all(candidates: list[dict]) -> list[dict]:
    """Fetch metadata for a list of candidates sequentially."""
    enriched = []
    for i, c in enumerate(candidates):
        log.info("[%d/%d] Fetching: %s", i + 1, len(candidates), c.get("id"))
        enriched.append(fetch(c))
    return enriched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Fetch paper metadata for candidates")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--id",  help='Paper ID e.g. "arxiv:2603.24566"')
    grp.add_argument("--url", help="Paper URL")
    grp.add_argument("--stdin", action="store_true",
                     help="Read JSON list of candidates from stdin")
    args = parser.parse_args()

    if args.stdin:
        candidates = json.load(sys.stdin)
        results = fetch_all(candidates)
    elif args.id:
        results = [fetch({"id": args.id, "url": "", "title": "", "source": "cli", "added": ""})]
    else:
        results = [fetch({"id": f"url:{args.url}", "url": args.url, "title": "",
                          "source": "cli", "added": ""})]

    print(json.dumps(results, indent=2))
