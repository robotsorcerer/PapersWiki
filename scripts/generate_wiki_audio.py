"""
generate_wiki_audio.py — Produce MP3 narrations for every paper in wiki/papers/.

Strategy (hybrid: wiki metadata + summaries):
  1. For each wiki/papers/*.md page, extract arxiv_id / title / authors /
     category / snippet / related links.
  2. If a rich summaries/<cat>/<...>.md exists and is NOT "[Summarization
     failed" / "[Not provided", use that as the narration body (5-10 min).
  3. Otherwise, synthesize a shorter narration from the wiki page itself
     (title + authors + snippet + related-paper list).
  4. Write MP3 to audio/<category>/<slug>.mp3. Skip files that already exist
     (unless --force).

CLI:
    python scripts/generate_wiki_audio.py            # generate all missing
    python scripts/generate_wiki_audio.py --force    # regenerate everything
    python scripts/generate_wiki_audio.py --limit 5  # first 5 pages only
    python scripts/generate_wiki_audio.py --dry-run  # print, don't synthesize
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from audio import synthesize, _build_script, _strip_markdown, _bullets_to_sentences  # noqa: E402

WIKI_DIR      = ROOT / "wiki" / "papers"
SUMMARIES_DIR = ROOT / "summaries"
AUDIO_DIR     = ROOT / "audio"
STATE_FILE    = ROOT / "state" / "audio_generation.json"

CATEGORIES = {"control", "robotics", "ml", "other"}

FAILED_MARKERS = ("[Summarization failed", "[Not provided", "Not provided —")


# --------------------------------------------------------------------------
# Wiki page parsing
# --------------------------------------------------------------------------

def parse_wiki_page(md_path: Path) -> dict:
    """Extract structured fields from a wiki/papers/*.md file."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Metadata line: **Venue**: ... | **Category**: [[topics/...|Cat]] | **Link**: <url>
    venue = ""
    year = ""
    category = "other"
    url = ""
    m = re.search(r"\*\*Venue\*\*:\s*(.+?)\s*\|", text)
    if m:
        v = m.group(1).strip()
        ym = re.search(r"(\d{4})\s*$", v)
        if ym:
            year = ym.group(1)
            venue = v[:ym.start()].rstrip(", ").strip()
        else:
            venue = v
    m = re.search(r"\*\*Category\*\*:\s*(?:\[\[topics/[^|]*\|)?([A-Za-z ]+)", text)
    if m:
        cat = m.group(1).strip().lower().rstrip("]")
        if cat in CATEGORIES:
            category = cat
    m = re.search(r"\*\*Link\*\*:\s*<([^>]+)>", text)
    if m:
        url = m.group(1).strip()

    # Authors
    authors: list[str] = []
    m = re.search(r"\*\*Authors\*\*:\s*(.+)", text)
    if m:
        raw = m.group(1)
        # Strip wikilinks: [[researchers/foo|Foo Bar]] -> Foo Bar
        raw = re.sub(r"\[\[researchers/[^|]+\|([^\]]+)\]\]", r"\1", raw)
        raw = re.sub(r"\[\[[^\]]+\]\]", "", raw)
        for a in raw.split(","):
            a = a.strip().rstrip("…").rstrip(",").strip()
            if a and a not in ("…", "..."):
                authors.append(a)

    # arxiv_id: from URL or filename
    arxiv_id = ""
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", url)
    if m:
        arxiv_id = m.group(1)
    else:
        m = re.match(r"(\d{4}\.\d{4,5})", md_path.stem)
        if m:
            arxiv_id = m.group(1)

    # Snippet (## Summary body)
    snippet = ""
    sm = re.search(r"^##\s+Summary\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if sm:
        raw = sm.group(1).strip()
        if not raw.startswith("_No snippet available"):
            snippet = raw

    # Related papers (bulleted list under ## Related)
    related_titles: list[str] = []
    rm = re.search(r"^##\s+Related\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if rm:
        for line in rm.group(1).splitlines():
            m = re.match(r"^-\s+\[\[papers/[^|]+\|([^\]]+)\]\]", line.strip())
            if m:
                related_titles.append(m.group(1).strip())

    return {
        "path": md_path,
        "title": title or md_path.stem,
        "authors": authors,
        "venue": venue,
        "year": year,
        "category": category,
        "url": url,
        "arxiv_id": arxiv_id,
        "snippet": snippet,
        "related": related_titles,
    }


# --------------------------------------------------------------------------
# Summary lookup
# --------------------------------------------------------------------------

def find_rich_summary(wiki: dict) -> Path | None:
    """Return a matching summaries/<cat>/<...>.md if it exists and is rich."""
    arxiv_id = wiki["arxiv_id"]
    if not arxiv_id:
        return None
    candidates: list[Path] = []
    for cat_dir in SUMMARIES_DIR.iterdir():
        if not cat_dir.is_dir():
            continue
        for p in cat_dir.glob(f"{arxiv_id}*"):
            candidates.append(p)
    for p in candidates:
        content = p.read_text(encoding="utf-8", errors="replace")
        if any(marker in content for marker in FAILED_MARKERS):
            continue
        return p
    return None


# --------------------------------------------------------------------------
# Paper-dict builder consumed by audio.synthesize()
# --------------------------------------------------------------------------

def build_paper_dict(wiki: dict) -> dict:
    """Merge wiki metadata with the richest available content source."""
    rich_md = find_rich_summary(wiki)
    if rich_md is not None:
        # audio.synthesize() will run _sections_from_markdown fallback path
        summary = {
            "category": wiki["category"],
            "raw_markdown": rich_md.read_text(encoding="utf-8"),
        }
    else:
        # Fall back to wiki metadata: build a minimal structured summary
        problem = wiki["snippet"] or (
            f"This alert-surfaced paper appears in the {wiki['category']} track "
            "of the compiled wiki. No abstract snippet was available in the raw "
            "Google Scholar alert, so this narration covers only the metadata."
        )
        related = wiki["related"]
        related_text = ""
        if related:
            top = related[:6]
            related_text = "This paper is grouped in the knowledge base with " + ", ".join(top) + "."
        summary = {
            "category": wiki["category"],
            "problem_statement": problem,
            "methodology": "",
            "results": "",
            "strengths": "",
            "weaknesses": "",
            "related_work": related_text,
            "connections_to_infdiff": "",
            "connections_to_hj_safety": "",
        }

    return {
        "title": wiki["title"],
        "authors": wiki["authors"],
        "venue": wiki["venue"],
        "year": wiki["year"],
        "url": wiki["url"],
        "arxiv_id": wiki["arxiv_id"],
        "id": wiki["arxiv_id"] or wiki["path"].stem,
        "summary": summary,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="Regenerate even if MP3 exists")
    ap.add_argument("--limit", type=int, default=None, help="Only process first N pages")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, don't synthesize")
    ap.add_argument("--sleep", type=float, default=0.4,
                    help="Seconds to sleep between gTTS calls (rate-limit safety)")
    ap.add_argument("--retry-429-sleep", type=float, default=20.0,
                    help="Seconds to back off after a gTTS 429 response")
    args = ap.parse_args()

    pages = sorted(WIKI_DIR.glob("*.md"))
    if args.limit is not None:
        pages = pages[: args.limit]

    print(f"Found {len(pages)} wiki papers under {WIKI_DIR}")

    generated = skipped = failed = reused = 0
    for i, page in enumerate(pages, 1):
        try:
            wiki = parse_wiki_page(page)
        except Exception as e:
            print(f"[{i:3d}] PARSE-FAIL {page.name}: {e}")
            failed += 1
            continue

        paper = build_paper_dict(wiki)

        # Path preview
        from audio import _audio_path
        out = _audio_path(paper)
        if out.exists() and not args.force:
            reused += 1
            print(f"[{i:3d}] SKIP (exists) {paper['title'][:50]:50s} -> {out.name}")
            continue

        if args.dry_run:
            script = _build_script(paper)
            print(f"[{i:3d}] DRY {paper['title'][:50]:50s} words={len(script.split())} -> {out.name}")
            continue

        # Retry once on 429 with a longer back-off
        attempt = 0
        while True:
            attempt += 1
            try:
                path = synthesize(paper)
                size_kb = path.stat().st_size / 1024 if path.exists() else 0
                generated += 1
                print(f"[{i:3d}] OK   {paper['title'][:50]:50s} {size_kb:7.1f} KB -> {path.name}")
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg and attempt == 1:
                    print(f"[{i:3d}] 429  backing off {args.retry_429_sleep:.0f}s and retrying")
                    time.sleep(args.retry_429_sleep)
                    continue
                failed += 1
                print(f"[{i:3d}] FAIL {paper['title'][:50]:50s}  {msg[:60]}")
                break

        # Gentle per-request pacing to keep gTTS happy
        if args.sleep > 0:
            time.sleep(args.sleep)

    print()
    print("=" * 72)
    print(f"generated={generated}  reused={reused}  skipped={skipped}  failed={failed}")
    print("=" * 72)

    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "generated": generated, "reused": reused,
        "skipped": skipped, "failed": failed,
    }))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
