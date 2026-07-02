"""
distill.py — Karpathy-style audio distillation of the knowledge graph.

This does NOT read papers one-by-one. Following Karpathy's "LLM Wiki / second
brain" idea (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
the wiki/ vault is the *compiled, interlinked artifact*. This module narrates
the SHAPE of that graph and, in particular, how the papers that are NEW since
the last digest thread into the existing web of topics, researchers, and prior
work. The output is a single spoken "briefing" MP3 — an associative tour of the
connections, not a recital of abstracts.

Pipeline role (Mon/Wed/Fri 5:00 AM):
    1. wiki.build_corpus()  -> the linked graph (offline, stdlib-only)
    2. diff against state/digest_seen.json -> which paper keys are NEW
    3. compose a connection-oriented narration script
    4. gTTS -> audio/digests/distill_<date>.mp3
    5. mark the new keys as seen (unless --peek)

Offline by design: no Anthropic API key needed (mirrors wiki.py), so it keeps
working even when API credits are exhausted.

CLI:
    python src/distill.py                 # build MP3 for new papers, mark seen
    python src/distill.py --script-only   # print the narration, synthesize nothing
    python src/distill.py --peek          # build MP3 but do NOT mark seen
    python src/distill.py --force-all     # treat every paper as new (full tour)
    python src/distill.py --max-featured 12
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import wiki as _wiki  # noqa: E402

log = logging.getLogger("distill")

EDT        = ZoneInfo("America/New_York")
STATE_DIR  = ROOT / "state"
SEEN_FILE  = STATE_DIR / "digest_seen.json"
AUDIO_DIR  = ROOT / "audio" / "digests"

CATEGORIES = ("control", "robotics", "ml", "other")


# ---------------------------------------------------------------------------
# Seen-state ledger (defines what counts as "new")
# ---------------------------------------------------------------------------

def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data.get("seen_keys", []))
        except Exception as e:
            log.warning("could not read %s: %s", SEEN_FILE, e)
    return set()


def save_seen(keys: set[str]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps({
        "seen_keys": sorted(keys),
        "updated": datetime.now(EDT).isoformat(),
    }, indent=0), encoding="utf-8")


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _related_keys(p: dict, corpus: dict, limit: int = 6) -> list[str]:
    """Papers linked to p by shared researcher (first) then shared topic."""
    researchers = corpus["researchers"]
    topics = corpus["topics"]
    related: list[str] = []
    seen = {p["key"]}
    for n in p.get("linked_researchers", []):
        for k in sorted(researchers.get(n, {}).get("papers", [])):
            if k not in seen:
                related.append(k)
                seen.add(k)
    for t in p.get("topics", []):
        for k in sorted(topics.get(t, [])):
            if k not in seen:
                related.append(k)
                seen.add(k)
    return related[:limit]


def _spoken_authors(p: dict) -> str:
    a = p.get("authors", [])
    if not a:
        return "authors not listed"
    if p.get("authors_truncated") or len(a) > 3:
        return f"{a[0]} and collaborators"
    if len(a) == 1:
        return a[0]
    return ", ".join(a[:-1]) + " and " + a[-1]


def _clean(text: str) -> str:
    """Collapse whitespace and drop wiki markup / non-ASCII for gTTS."""
    text = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", text or "")
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _snippet_lead(p: dict, sentences: int = 1) -> str:
    snip = _clean(p.get("snippet", ""))
    if not snip:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", snip)
    lead = " ".join(parts[:sentences]).strip()
    return lead


# ---------------------------------------------------------------------------
# Narration composition
# ---------------------------------------------------------------------------

def compose_script(corpus: dict, new_keys: list[str], max_featured: int) -> tuple[str, dict]:
    """
    Build the spoken distillation and a structured "show notes" dict
    (used by the email body / TOC).
    """
    papers = corpus["papers"]
    researchers = corpus["researchers"]
    topics = corpus["topics"]

    now = datetime.now(EDT)
    date_phrase = now.strftime("%A, %B %d, %Y")

    n_papers = len(papers)
    n_topics = len(topics)
    n_res = len(researchers)
    n_new = len(new_keys)

    parts: list[str] = []
    notes: dict = {"date": now.strftime("%Y-%m-%d"), "featured": [], "topics": [], "new_count": n_new}

    # --- Opening: state of the graph -------------------------------------
    parts.append(
        f"Knowledge graph distillation for {date_phrase}. "
        f"This is a tour of your research second brain, not a reading of individual papers. "
        f"The graph now holds {n_papers} papers, woven across {n_topics} topic clusters, "
        f"surfaced from {n_res} researchers you follow."
    )

    if n_new == 0:
        # Quiet period: narrate the shape of the existing graph instead.
        parts.append(
            "No new papers have entered the graph since the last distillation, "
            "so this briefing revisits the structure of what you already hold."
        )
        parts.extend(_narrate_graph_shape(corpus))
        parts.append("End of distillation.")
        script = _finalize(parts)
        notes["hub_topics"] = _hub_topics(corpus, top=5)
        return script, notes

    parts.append(
        f"Since the last distillation, {n_new} new "
        f"{'paper has' if n_new == 1 else 'papers have'} entered the graph. "
        "Here is how they connect to what you already know."
    )

    # --- Group new papers by topic cluster -------------------------------
    featured = new_keys[:max_featured]
    remaining = new_keys[max_featured:]

    by_topic: dict[str, list[str]] = {}
    uncategorized: list[str] = []
    for k in featured:
        p = papers[k]
        if p["topics"]:
            # File under its first (primary) topic for narration flow.
            by_topic.setdefault(p["topics"][0], []).append(k)
        else:
            uncategorized.append(k)

    # Order topics by how many new papers landed in them (busiest first).
    topic_order = sorted(by_topic, key=lambda t: (-len(by_topic[t]), t))

    for topic in topic_order:
        keys = by_topic[topic]
        disp = _wiki._topic_display(topic)
        total_in_topic = len(topics.get(topic, []))
        lead = (
            f"In the {disp} cluster, {len(keys)} new "
            f"{'paper' if len(keys) == 1 else 'papers'} "
            f"{'joins' if len(keys) == 1 else 'join'} an existing body of "
            f"{total_in_topic} in this area."
        )
        parts.append(lead)
        notes["topics"].append({"topic": disp, "count": len(keys)})

        for k in keys:
            p = papers[k]
            parts.append(_narrate_paper(p, corpus))
            notes["featured"].append({
                "title": _clean(p["title"]),
                "topic": disp,
                "url": p.get("url", ""),
                "researchers": p.get("linked_researchers", []),
            })

    # Uncategorized new papers (no topic keyword matched).
    if uncategorized:
        parts.append(
            f"{len(uncategorized)} new "
            f"{'paper' if len(uncategorized) == 1 else 'papers'} "
            "did not match an existing topic cluster, hinting at a possible new thread."
        )
        for k in uncategorized:
            p = papers[k]
            parts.append(_narrate_paper(p, corpus))
            notes["featured"].append({
                "title": _clean(p["title"]),
                "topic": "uncategorized",
                "url": p.get("url", ""),
                "researchers": p.get("linked_researchers", []),
            })

    # --- Who is driving the new work -------------------------------------
    res_counter: dict[str, int] = {}
    for k in new_keys:
        for n in papers[k].get("linked_researchers", []):
            res_counter[n] = res_counter.get(n, 0) + 1
    if res_counter:
        top = sorted(res_counter, key=lambda n: (-res_counter[n], n))[:3]
        phrases = [f"{n}, with {res_counter[n]} new "
                   f"{'paper' if res_counter[n] == 1 else 'papers'}" for n in top]
        lead_verb = "is" if len(top) == 1 else "are"
        parts.append(
            f"Among the researchers you follow, the most active in this batch {lead_verb} "
            + _oxford(phrases) + "."
        )
        notes["active_researchers"] = [{"name": n, "count": res_counter[n]} for n in top]

    # --- Overflow note ----------------------------------------------------
    if remaining:
        titles = [_clean(papers[k]["title"]) for k in remaining[:5]]
        parts.append(
            f"{len(remaining)} further new "
            f"{'paper' if len(remaining) == 1 else 'papers'} entered the graph, "
            f"including {_oxford(titles)}. They are filed in the wiki and available for a closer look."
        )

    # --- Closing: hub topics ---------------------------------------------
    hub = _hub_topics(corpus, top=3)
    if hub:
        hub_phrases = [f"{disp}, with {cnt} papers" for disp, cnt in hub]
        parts.append(
            "Zooming back out, the densest hubs of your graph remain "
            + _oxford(hub_phrases) + "."
        )
        notes["hub_topics"] = hub

    parts.append("End of distillation.")
    return _finalize(parts), notes


def _narrate_paper(p: dict, corpus: dict) -> str:
    """One flowing spoken passage: what it is + how it connects."""
    papers = corpus["papers"]
    title = _clean(p["title"])
    surfacer = p.get("linked_researchers", [])
    who = ""
    if surfacer:
        who = f", surfaced through {_oxford(surfacer)}"

    seg = f"{title}, by {_spoken_authors(p)}{who}."

    lead = _snippet_lead(p, sentences=1)
    if lead:
        seg += f" In brief: {lead}"
        if not seg.endswith((".", "!", "?")):
            seg += "."

    # The connective tissue — the point of the whole exercise.
    related = _related_keys(p, corpus, limit=6)
    if related:
        rel_titles = [_clean(papers[k]["title"]) for k in related[:2]]
        seg += (f" It links into your existing work on related lines, "
                f"neighbouring papers such as {_oxford(rel_titles)}.")
    else:
        seg += " It currently sits at the edge of the graph, with few neighbours."
    return seg


def _narrate_graph_shape(corpus: dict) -> list[str]:
    """Fallback narration when there are no new papers."""
    researchers = corpus["researchers"]
    out: list[str] = []
    hub = _hub_topics(corpus, top=5)
    if hub:
        phrases = [f"{disp}, with {cnt} papers" for disp, cnt in hub]
        out.append("The densest topic hubs are " + _oxford(phrases) + ".")
    # Most prolific followed researchers.
    ranked = sorted(researchers.values(), key=lambda r: (-len(r["papers"]), r["name"]))[:3]
    if ranked:
        phrases = [f"{r['name']}, appearing in {len(r['papers'])} papers" for r in ranked]
        out.append("The researchers with the widest footprint are " + _oxford(phrases) + ".")
    return out


def _hub_topics(corpus: dict, top: int = 3) -> list[tuple[str, int]]:
    topics = corpus["topics"]
    ranked = sorted(topics, key=lambda t: (-len(topics[t]), t))[:top]
    return [(_wiki._topic_display(t), len(topics[t])) for t in ranked]


def _oxford(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _finalize(parts: list[str]) -> str:
    script = "\n\n".join(parts)
    script = re.sub(r"[^\x00-\x7F]", " ", script)   # gTTS-safe ASCII
    script = re.sub(r"[ \t]+", " ", script)
    return script.strip()


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def _say_fallback(script: str, out_path: Path) -> Path | None:
    """
    Offline TTS via macOS `say` when gTTS is rate-limited. `say` cannot write
    mp3 directly, so we emit AIFF and transcode to mp3 with ffmpeg if present;
    otherwise we keep the .aiff and return that path. Returns None if `say` is
    unavailable (non-macOS).
    """
    import shutil
    import subprocess

    say = shutil.which("say")
    if not say:
        return None

    aiff = out_path.with_suffix(".aiff")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([say, "-o", str(aiff), script], check=True,
                       capture_output=True, timeout=600)
    except Exception as e:
        log.warning("`say` fallback failed: %s", e)
        return None

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        try:
            subprocess.run([ffmpeg, "-y", "-i", str(aiff),
                            "-codec:a", "libmp3lame", "-qscale:a", "4",
                            str(out_path)],
                           check=True, capture_output=True, timeout=600)
            aiff.unlink(missing_ok=True)
            log.info("Synthesized via offline `say` + ffmpeg fallback")
            return out_path
        except Exception as e:
            log.warning("ffmpeg transcode failed (keeping .aiff): %s", e)
    log.info("Synthesized via offline `say` fallback (AIFF, no ffmpeg)")
    return aiff


def synthesize(script: str, out_path: Path, retries: int = 4,
               backoff: float = 20.0) -> Path:
    """
    Synthesize the narration to MP3. Tries gTTS first (retrying on 429 rate
    limits), then falls back to offline macOS `say` so a scheduled run always
    produces audio even if Google is throttling.

    Note: gTTS is limited to ~100 requests/hour per IP. Because a distillation
    run makes exactly ONE request, the schedule (3×/week) never approaches that
    ceiling on its own — the fallback is purely defensive.
    """
    import time
    from gtts import gTTS
    from gtts.tts import gTTSError

    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            gTTS(text=script, lang="en", tld="com", slow=False).save(str(out_path))
            return out_path
        except gTTSError as e:
            last_err = e
            if "429" in str(e) and attempt < retries:
                wait = backoff * attempt
                log.warning("gTTS 429 (attempt %d/%d); backing off %.0fs",
                            attempt, retries, wait)
                time.sleep(wait)
                continue
            break  # non-429 error or out of retries -> try fallback

    log.warning("gTTS unavailable (%s); trying offline `say` fallback", last_err)
    fb = _say_fallback(script, out_path)
    if fb is not None:
        return fb
    raise last_err if last_err else RuntimeError("TTS failed with no error")


def run(script_only: bool, peek: bool, force_all: bool, max_featured: int,
        limit: int | None = None, skip_if_empty: bool = False,
        tag: str | None = None) -> dict:
    """
    Build one distillation. Returns a result dict:
        { "mp3": Path|None, "script": str, "notes": dict, "new_keys": [...],
          "total_papers": int, "remaining": int, "skipped": bool }

    Batch / backlog-drain semantics:
      - limit=None  : distill ALL unseen papers in one go (normal delta digest).
      - limit=N     : distill only the next N unseen papers (a "tranche") and
                      mark ONLY those as seen, so repeated calls drain the
                      backlog N papers at a time.
      - skip_if_empty: if there is nothing unseen to send, return early with
                      skipped=True (no synthesis, no email) instead of a recap.
    """
    corpus = _wiki.build_corpus()
    all_keys = set(corpus["papers"].keys())
    papers = corpus["papers"]

    if force_all:
        candidate_set = set(all_keys)
    else:
        seen = load_seen()
        candidate_set = all_keys - seen

    # Order newest-first-ish: by year desc then title, for deterministic tranches.
    candidates = sorted(
        candidate_set,
        key=lambda k: (papers[k].get("year") or "", papers[k]["title"]),
        reverse=True,
    )
    remaining_before = len(candidates)

    # Carve out this session's tranche.
    batch = candidates[:limit] if limit is not None else candidates
    remaining_after = remaining_before - len(batch)

    # Nothing to do — bow out quietly instead of emailing an empty recap.
    if skip_if_empty and not force_all and not batch:
        return {"mp3": None, "script": "", "notes": {"new_count": 0},
                "new_keys": [], "total_papers": len(all_keys),
                "remaining": 0, "skipped": True}

    script, notes = compose_script(corpus, batch, max_featured)
    notes["remaining_backlog"] = remaining_after

    result = {"mp3": None, "script": script, "notes": notes,
              "new_keys": batch, "total_papers": len(all_keys),
              "remaining": remaining_after, "skipped": False}

    if script_only:
        return result

    date_str = datetime.now(EDT).strftime("%Y%m%d")
    suffix = f"_{tag}" if tag else ""
    out_path = AUDIO_DIR / f"distill_{date_str}{suffix}.mp3"
    log.info("Synthesizing distillation (%d words, %d papers) -> %s",
             len(script.split()), len(batch), out_path)
    final_path = synthesize(script, out_path)   # may be .aiff if `say` fallback used
    result["mp3"] = final_path
    log.info("Distillation saved: %s (%.1f KB)",
             final_path, final_path.stat().st_size / 1024)

    # Advance the seen-ledger. In batch mode mark ONLY the tranche just sent,
    # so the next call picks up where this one left off.
    if not peek:
        if force_all:
            save_seen(all_keys)
            log.info("Marked %d papers as seen (force-all)", len(all_keys))
        else:
            seen = load_seen()
            seen.update(batch)
            save_seen(seen)
            log.info("Marked %d papers as seen (%d remain in backlog)",
                     len(batch), remaining_after)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    ap = argparse.ArgumentParser(description="Distill the knowledge graph into one MP3")
    ap.add_argument("--script-only", action="store_true",
                    help="Print narration script, synthesize nothing, don't mark seen")
    ap.add_argument("--peek", action="store_true",
                    help="Synthesize MP3 but do NOT mark papers as seen")
    ap.add_argument("--force-all", action="store_true",
                    help="Treat every paper as new (full-graph tour)")
    ap.add_argument("--max-featured", type=int, default=12,
                    help="Max new papers narrated in depth (rest summarized)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Distill only the next N unseen papers (a tranche); "
                         "mark only those seen so repeated calls drain the backlog")
    ap.add_argument("--skip-if-empty", action="store_true",
                    help="If nothing is unseen, exit without synthesizing")
    ap.add_argument("--tag", default=None,
                    help="Filename suffix to disambiguate multiple runs in one day")
    args = ap.parse_args()

    res = run(args.script_only, args.peek, args.force_all, args.max_featured,
              limit=args.limit, skip_if_empty=args.skip_if_empty, tag=args.tag)
    if args.script_only:
        print(res["script"])
    elif res.get("skipped"):
        print("(backlog empty — nothing to distill)")
    else:
        print(res["mp3"])
