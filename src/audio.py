"""
audio.py — Stage 5: Text-to-Speech Synthesis

Converts the rendered markdown summary into spoken audio using gTTS
(Google Text-to-Speech), producing a per-paper MP3 in audio/<category>/.

Audio narration script:
  1. Title + authors + venue/year
  2. Problem statement
  3. Methodology
  4. Results
  5. Strengths (abbreviated)
  6. Weaknesses (abbreviated)
  7. Connections to Lekan's work (InfDiff + HJ)

At 150 WPM average, a 400-word script produces ~3 min of audio.
A full-detail 800-word script produces ~5 min.

We target 3-5 minutes: include all sections but keep bullet lists
to a single spoken sentence per bullet.

Usage (CLI):
    python audio.py --paper-json '{...}'
    cat summarized_paper.json | python audio.py --stdin
    python audio.py --md-file summaries/control/2603.24566_foo.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("audio")

WIKI_DIR   = Path(__file__).parent.parent
AUDIO_DIR  = WIKI_DIR / "audio"
PYTHON_311 = "/home/lex/miniconda3/envs/311/bin/python"

CATEGORIES = ("control", "robotics", "ml", "other")

# ---------------------------------------------------------------------------
# Markdown → spoken-word script
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove markdown syntax to produce clean spoken text."""
    # Remove links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove bold/italic markers
    text = re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', text)
    # Remove code fences
    text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]+`', '', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove URLs completely (don't speak them)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    # Remove horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    # Remove heading markers, keep text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Compress whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _bullets_to_sentences(text: str) -> str:
    """Convert bullet list items to natural spoken sentences."""
    lines = text.split('\n')
    spoken = []
    for line in lines:
        line = line.strip()
        if line.startswith('- ') or line.startswith('* '):
            line = line[2:].strip()
        if line:
            # Ensure sentence ends with period
            if not line.endswith(('.', '?', '!')):
                line += '.'
            spoken.append(line)
    return ' '.join(spoken)


def _build_script(paper: dict) -> str:
    """
    Build a 400-800 word spoken script from the paper summary.
    Designed for 3-5 minutes of gTTS audio.
    """
    summary = paper.get("summary", {})
    title   = paper.get("title", "Untitled Paper")

    # Skip URL titles (use generic fallback instead)
    if title.startswith("http"):
        title = "Academic Paper"

    authors = paper.get("authors", [])
    venue   = paper.get("venue", "")
    year    = paper.get("year", "")

    # Author attribution
    if not authors:
        author_str = "authors unknown"
    elif len(authors) == 1:
        author_str = authors[0]
    elif len(authors) <= 3:
        author_str = ", ".join(authors[:-1]) + " and " + authors[-1]
    else:
        author_str = authors[0] + " and collaborators"

    venue_year = f"{venue}, {year}." if (venue and year) else ((venue or year or "") + ".")

    parts: list[str] = []

    # --- Opening ---
    parts.append(
        f"Paper summary. Title: {title}. "
        f"By {author_str}. Published in {venue_year}"
    )

    # --- Problem ---
    prob = _strip_markdown(summary.get("problem_statement", ""))
    if prob:
        parts.append(f"Problem. {prob}")

    # --- Methodology ---
    meth = _strip_markdown(summary.get("methodology", ""))
    if meth:
        parts.append(f"Approach. {meth}")

    # --- Results ---
    res = _strip_markdown(summary.get("results", ""))
    if res:
        parts.append(f"Results. {res}")

    # --- Strengths (as sentences) ---
    str_raw = _strip_markdown(summary.get("strengths", ""))
    if str_raw:
        str_spoken = _bullets_to_sentences(str_raw)
        parts.append(f"Strengths. {str_spoken}")

    # --- Weaknesses ---
    weak_raw = _strip_markdown(summary.get("weaknesses", ""))
    if weak_raw:
        weak_spoken = _bullets_to_sentences(weak_raw)
        parts.append(f"Limitations. {weak_spoken}")

    # --- Related Work ---
    rw = _strip_markdown(summary.get("related_work", ""))
    if rw:
        parts.append(f"Context in the literature. {rw}")

    # --- InfDiff connections ---
    infdiff = _strip_markdown(summary.get("connections_to_infdiff", ""))
    if infdiff and "not directly applicable" not in infdiff.lower():
        parts.append(f"Connections to InfDiff. {infdiff}")

    # --- HJ connections ---
    hj = _strip_markdown(summary.get("connections_to_hj_safety", ""))
    if hj and "not directly applicable" not in hj.lower():
        parts.append(f"Connections to Hamilton-Jacobi reachability. {hj}")

    # --- Closing ---
    parts.append("End of summary.")

    script = "\n\n".join(parts)
    # Sanitise non-ASCII that trips up gTTS
    script = re.sub(r'[^\x00-\x7F]', ' ', script)
    return script


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _audio_path(paper: dict) -> Path:
    summary  = paper.get("summary", {})
    category = summary.get("category", "other")
    if category not in CATEGORIES:
        category = "other"

    arxiv_id = paper.get("arxiv_id", "")
    title    = paper.get("title", paper.get("id", "unknown"))
    slug     = re.sub(r'[^a-z0-9]+', '_', title.lower())[:50].strip('_')

    if arxiv_id:
        fname = f"{arxiv_id}_{slug}.mp3"
    else:
        # Use title slug instead of URL slug for cleaner filenames
        fname = f"{slug}.mp3"

    return AUDIO_DIR / category / fname


# ---------------------------------------------------------------------------
# gTTS synthesis
# ---------------------------------------------------------------------------

def synthesize(paper: dict) -> Path:
    """
    Produce an MP3 for one paper. Returns the path to the MP3 file.
    Raises RuntimeError on failure.
    """
    try:
        from gtts import gTTS
    except ImportError:
        raise RuntimeError(
            "gtts not installed. Run: "
            "/home/lex/miniconda3/envs/311/bin/pip install gtts"
        )

    script   = _build_script(paper)
    out_path = _audio_path(paper)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    title = paper.get("title", paper.get("id", "unknown"))[:60]
    log.info("Synthesizing audio: %s -> %s", title, out_path.name)
    log.debug("Script length: %d chars (~%d words)", len(script), len(script.split()))

    tts = gTTS(text=script, lang="en", tld="com", slow=False)
    tts.save(str(out_path))

    log.info("Audio saved: %s (%.1f KB)", out_path, out_path.stat().st_size / 1024)
    return out_path


def synthesize_all(papers: list[dict]) -> list[Path]:
    paths = []
    for i, p in enumerate(papers):
        log.info("[%d/%d] Audio: %s", i + 1, len(papers), p.get("title", "?")[:60])
        try:
            paths.append(synthesize(p))
        except Exception as e:
            log.error("Audio failed for %s: %s", p.get("id", "?"), e)
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
    parser = argparse.ArgumentParser(description="Synthesize audio summaries via gTTS")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--paper-json", help="JSON string of a single summarized paper dict")
    grp.add_argument("--stdin", action="store_true", help="Read JSON list from stdin")
    grp.add_argument("--md-file", type=Path,
                     help="Render a script from an existing markdown summary file (no audio synthesis, just print script)")
    args = parser.parse_args()

    if args.md_file:
        # Convenience: print the spoken script from a .md file
        md_text = args.md_file.read_text(encoding="utf-8")
        # Minimal stub paper dict for script building
        paper = {"summary": {"raw_markdown": md_text}, "title": args.md_file.stem}
        print(_build_script(paper))
        sys.exit(0)

    if args.stdin:
        papers = json.load(sys.stdin)
        if isinstance(papers, dict):
            papers = [papers]
        paths = synthesize_all(papers)
    else:
        paper = json.loads(args.paper_json)
        paths = [synthesize(paper)]

    for p in paths:
        print(str(p))
