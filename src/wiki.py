"""
wiki.py — Knowledge-Base Compiler (Karpathy-style "LLM Wiki" / second brain)

This module realises the Karpathy "second brain" contract on top of PapersWiki:

    raw  belongs to YOU and is never edited     ->  email_src/*.eml
    wiki belongs to the MODEL (generated/linked) ->  wiki/

It is NOT RAG. The raw Google Scholar alert emails are *compiled once* into a
linked Obsidian-style knowledge base that compounds over time. Every run is a
deterministic reconciliation: the wiki is rebuilt from the raw source of truth,
so the graph never rots and stays consistent.

The compiler is intentionally dependency-free (standard library only) so it can
run from cron with no API key, no network and no BeautifulSoup:

    python src/wiki.py                # build wiki/ from email_src/
    python src/wiki.py --email-src P  # custom raw dir
    python src/wiki.py --wiki-dir   P # custom output dir

Generated layout (the vault root is wiki/):

    wiki/
      index.md             # Home / Map-of-Content (counts + entry points)
      researchers/<slug>.md# one per followed scholar (+ matched co-authors)
      papers/<slug>.md     # one per unique paper, fully cross-linked
      topics/<slug>.md     # concept clusters (CBFs, diffusion, RL, ...)
      sources/<slug>.md     # one per raw .eml — provenance back to the truth

All inter-page references use Obsidian wikilinks ``[[path|Alias]]`` and every
entity carries backlinks, so the result is a navigable graph.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Reuse the raw-email parser (stdlib-only path) from the ingest stage.
sys.path.insert(0, str(Path(__file__).parent))
import ingest as _ingest  # noqa: E402

EDT = ZoneInfo("America/New_York")

WIKI_ROOT = Path(__file__).parent.parent
EMAIL_SRC = WIKI_ROOT / "email_src"
WIKI_DIR = WIKI_ROOT / "wiki"

log = logging.getLogger("wiki")


# ---------------------------------------------------------------------------
# Topic taxonomy — aligned with Lekan's research themes (see src/context.py).
# Each topic maps to a list of lowercase substrings searched in title+snippet.
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "control-barrier-functions": ["barrier function", "cbf", " clf", "control barrier", "safety filter"],
    "hamilton-jacobi-reachability": ["hamilton-jacobi", "hamilton jacobi", "reachability", "reachable set", "backward reachable"],
    "safe-control": ["safety", "safe control", "safe reinforcement", "robust control", "input-to-state"],
    "diffusion-models": ["diffusion polic", "diffusion model", "score-based", "score matching", "denoising", "flow matching", "rectified flow"],
    "imitation-learning": ["imitation", "behavior cloning", "behavioural cloning", "behavioral cloning", "learning from demonstration"],
    "reinforcement-learning": ["reinforcement learning", "policy gradient", "actor-critic", "actor critic", "q-learning", "q learning", "reward"],
    "model-predictive-control": ["model predictive", "mpc", "receding horizon", "optimal control"],
    "manipulation": ["manipulation", "grasp", "dexterous", "pusht", "manipulator", "in-hand"],
    "locomotion": ["locomotion", "legged", "quadruped", "bipedal", "humanoid", "walking", "gait"],
    "navigation-and-planning": ["navigation", "motion planning", "path planning", "route planning", "trajectory optimization", "trajectory generation"],
    "perception-and-slam": ["slam", "perception", "event camera", "visual", "mapping", "localization", "localisation", "scene", "3d reconstruction", "depth"],
    "optimization": ["optimization", "optimisation", "convex", "semidefinite", "variational inequality", "quadratic program", "nonconvex"],
    "multi-agent-and-games": ["game", "nash", "stackelberg", "equilibrium", "multi-agent", "multi agent", "flocking", "swarm", "cooperative"],
    "language-and-foundation-models": ["language model", " llm", "transformer", "foundation model", "vision-language", "vision language", "vlm", "vla"],
    "world-models": ["world model", "world-action", "predictive model"],
    "uncertainty-and-bayesian": ["uncertainty", "bayesian", "gaussian process", "stochastic", "probabilistic"],
}

# Coarse category buckets (mirrors summaries/ layout).
CATEGORY_TOPICS: dict[str, set[str]] = {
    "control": {"control-barrier-functions", "hamilton-jacobi-reachability", "safe-control",
                "model-predictive-control", "optimization"},
    "robotics": {"manipulation", "locomotion", "navigation-and-planning", "perception-and-slam"},
    "ml": {"diffusion-models", "imitation-learning", "reinforcement-learning",
           "language-and-foundation-models", "world-models", "uncertainty-and-bayesian"},
}


# ---------------------------------------------------------------------------
# Slug / link helpers
# ---------------------------------------------------------------------------

def _slug(text: str, maxlen: int = 60) -> str:
    """Filesystem- and Obsidian-friendly slug using hyphens."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:maxlen].strip("-") or "untitled"


def _alias(text: str) -> str:
    """Sanitise a display alias so it cannot break a [[link|alias]]."""
    return re.sub(r"\s+", " ", (text or "").replace("|", "/").replace("[", "(").replace("]", ")")).strip()


def _link(path: str, alias: str) -> str:
    """Build an Obsidian wikilink ``[[path|alias]]`` (vault root = wiki/)."""
    return f"[[{path}|{_alias(alias)}]]"


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


# ---------------------------------------------------------------------------
# Researcher-name canonicalisation
# ---------------------------------------------------------------------------

def _name_key(name: str) -> tuple[str, str] | None:
    """
    Reduce a name to (surname, first-initial) for matching abbreviated Scholar
    author strings (``D Rus``) against followed full names (``Daniela Rus``).
    """
    tokens = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    tokens = [t for t in tokens if t.lower() not in {"jr", "jr.", "ii", "iii"}]
    if len(tokens) < 2:
        return None
    surname = re.sub(r"[^a-z]", "", tokens[-1].lower())
    first_initial = re.sub(r"[^a-z]", "", tokens[0].lower())[:1]
    if not surname or not first_initial:
        return None
    return (surname, first_initial)


# ---------------------------------------------------------------------------
# Topic / category classification
# ---------------------------------------------------------------------------

def _classify_topics(text: str) -> list[str]:
    text = f" {(text or '').lower()} "
    found = [topic for topic, kws in TOPIC_KEYWORDS.items()
             if any(kw in text for kw in kws)]
    return found


def _category_for(topics: list[str]) -> str:
    scores = {cat: len(set(topics) & cat_topics)
              for cat, cat_topics in CATEGORY_TOPICS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


# ---------------------------------------------------------------------------
# Corpus model
# ---------------------------------------------------------------------------

def _paper_key(rec: dict) -> str:
    if rec.get("arxiv_id"):
        return f"arxiv:{rec['arxiv_id']}"
    if rec.get("url"):
        return f"url:{rec['url']}"
    return f"title:{_norm_title(rec['title'])}"


def build_corpus(email_src: Path = EMAIL_SRC) -> dict:
    """
    Parse all raw emails and reconcile them into a linked corpus model:
        papers     : key -> merged paper dict (+ slug, topics, category, links)
        researchers: name -> {slug, papers:set(keys), followed:bool, topics:set}
        topics     : topic -> set(paper keys)
        sources    : filename -> {followed, date, subject, papers:set(keys)}
    """
    records = _ingest.parse_all_records(email_src)

    papers: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    followed_names: dict[tuple[str, str], str] = {}

    # First pass: register followed researchers so we can resolve abbreviations.
    for rec in records:
        followed = rec.get("followed", "").strip()
        if followed:
            k = _name_key(followed)
            if k:
                followed_names.setdefault(k, followed)

    # Second pass: build papers + sources.
    for rec in records:
        key = _paper_key(rec)
        src = rec["source"]
        followed = rec.get("followed", "").strip()

        sources.setdefault(src, {
            "followed": followed,
            "date": rec.get("date", ""),
            "papers": set(),
        })
        sources[src]["papers"].add(key)

        if key not in papers:
            topics = _classify_topics(f"{rec['title']} {rec.get('snippet','')}")
            papers[key] = {
                "key": key,
                "title": rec["title"],
                "url": rec.get("url", ""),
                "arxiv_id": rec.get("arxiv_id"),
                "authors": list(rec.get("authors", [])),
                "authors_truncated": rec.get("authors_truncated", False),
                "venue": rec.get("venue", ""),
                "year": rec.get("year", ""),
                "snippet": rec.get("snippet", ""),
                "topics": topics,
                "category": _category_for(topics),
                "followed": set(),
                "sources": set(),
                "slug": "",
            }
        p = papers[key]
        p["sources"].add(src)
        if followed:
            p["followed"].add(followed)
        # Prefer the richest metadata seen across duplicate alerts.
        if len(rec.get("authors", [])) > len(p["authors"]):
            p["authors"] = list(rec["authors"])
        if not p["snippet"] and rec.get("snippet"):
            p["snippet"] = rec["snippet"]
        if not p["venue"] and rec.get("venue"):
            p["venue"] = rec["venue"]
        if not p["year"] and rec.get("year"):
            p["year"] = rec["year"]

    # Assign unique slugs to papers.
    used: set[str] = set()
    for p in papers.values():
        base = p["arxiv_id"] or _slug(p["title"])
        slug = base
        i = 2
        while slug in used:
            slug = f"{base}-{i}"
            i += 1
        used.add(slug)
        p["slug"] = slug

    # Build researcher index (followed scholars + matched authors).
    researchers: dict[str, dict] = {}

    def _ensure_researcher(name: str, followed: bool) -> str:
        slug = _slug(name)
        r = researchers.get(name)
        if r is None:
            r = researchers[name] = {
                "name": name, "slug": slug,
                "papers": set(), "topics": set(), "followed": followed,
            }
        if followed:
            r["followed"] = True
        return name

    for p in papers.values():
        # The followed scholar(s) that surfaced the paper.
        for fname in p["followed"]:
            _ensure_researcher(fname, followed=True)
            researchers[fname]["papers"].add(p["key"])
            researchers[fname]["topics"].update(p["topics"])
        # Co-authors that match a followed researcher get linked too.
        for author in p["authors"]:
            ak = _name_key(author)
            if ak and ak in followed_names:
                canon = followed_names[ak]
                _ensure_researcher(canon, followed=True)
                researchers[canon]["papers"].add(p["key"])
                researchers[canon]["topics"].update(p["topics"])

    # Resolve which researcher links each paper should carry.
    for p in papers.values():
        linked = set(p["followed"])
        for author in p["authors"]:
            ak = _name_key(author)
            if ak and ak in followed_names:
                linked.add(followed_names[ak])
        p["linked_researchers"] = sorted(linked)

    topics: dict[str, set] = defaultdict(set)
    for p in papers.values():
        for t in p["topics"]:
            topics[t].add(p["key"])

    return {
        "papers": papers,
        "researchers": researchers,
        "topics": dict(topics),
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

def _paper_link(p: dict) -> str:
    return _link(f"papers/{p['slug']}", p["title"])


def _researcher_link(r: dict) -> str:
    return _link(f"researchers/{r['slug']}", r["name"])


def _topic_display(topic: str) -> str:
    return topic.replace("-", " ").title()


def _render_paper(p: dict, corpus: dict) -> str:
    researchers = corpus["researchers"]
    papers = corpus["papers"]
    L: list[str] = []
    L.append(f"# {p['title']}")
    L.append("")

    meta = []
    if p["venue"] or p["year"]:
        meta.append(f"**Venue**: {', '.join(x for x in [p['venue'], p['year']] if x)}")
    meta.append(f"**Category**: [[topics/{p['category']}|{_topic_display(p['category'])}]]"
                if p["category"] != "other" else "**Category**: Other")
    if p["url"]:
        meta.append(f"**Link**: <{p['url']}>")
    L.append("  |  ".join(meta))
    L.append("")

    # Authors
    if p["authors"]:
        rendered = []
        fkeys = {_name_key(n): n for n in p["linked_researchers"]}
        for a in p["authors"]:
            ak = _name_key(a)
            if ak in fkeys:
                rendered.append(_researcher_link(researchers[fkeys[ak]]))
            else:
                rendered.append(a)
        tail = ", …" if p["authors_truncated"] else ""
        L.append(f"**Authors**: {', '.join(rendered)}{tail}")
        L.append("")

    # Surfaced-by (the followed researcher alert that introduced the paper)
    if p["linked_researchers"]:
        links = ", ".join(_researcher_link(researchers[n]) for n in p["linked_researchers"])
        L.append(f"**Followed researchers**: {links}")
        L.append("")

    # Topics
    if p["topics"]:
        links = ", ".join(f"[[topics/{t}|{_topic_display(t)}]]" for t in p["topics"])
        L.append(f"**Topics**: {links}")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append(p["snippet"] or "_No snippet available in the source alert._")
    L.append("")

    # Related papers: shared researcher first, then shared topic.
    related: list[str] = []
    seen = {p["key"]}
    for n in p["linked_researchers"]:
        for k in sorted(researchers[n]["papers"]):
            if k not in seen and k in papers:
                related.append(_paper_link(papers[k]))
                seen.add(k)
    for t in p["topics"]:
        for k in sorted(corpus["topics"].get(t, [])):
            if k not in seen and k in papers:
                related.append(_paper_link(papers[k]))
                seen.add(k)
    if related:
        L.append("## Related")
        L.append("")
        for r in related[:8]:
            L.append(f"- {r}")
        L.append("")

    # Provenance back to the raw source of truth.
    L.append("## Source (raw)")
    L.append("")
    for src in sorted(p["sources"]):
        L.append(f"- {_link('sources/' + _slug(src), src)}")
    L.append("")
    L.append("> The raw alert email is the source of truth and is never edited. "
             "This page is compiled from it.")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _render_researcher(r: dict, corpus: dict) -> str:
    papers = corpus["papers"]
    L: list[str] = []
    L.append(f"# {r['name']}")
    L.append("")
    role = "Followed researcher" if r["followed"] else "Author"
    L.append(f"*{role}* — surfaced via Google Scholar alerts in `email_src/`.")
    L.append("")

    if r["topics"]:
        links = ", ".join(f"[[topics/{t}|{_topic_display(t)}]]"
                          for t in sorted(r["topics"]))
        L.append(f"**Active topics**: {links}")
        L.append("")

    paper_keys = sorted(r["papers"],
                        key=lambda k: (papers[k]["year"] or "", papers[k]["title"]),
                        reverse=True)
    L.append(f"## Papers ({len(paper_keys)})")
    L.append("")
    for k in paper_keys:
        p = papers[k]
        yr = f" ({p['year']})" if p["year"] else ""
        L.append(f"- {_paper_link(p)}{yr}")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _render_topic(topic: str, keys: set, corpus: dict) -> str:
    papers = corpus["papers"]
    researchers = corpus["researchers"]
    L: list[str] = []
    L.append(f"# {_topic_display(topic)}")
    L.append("")
    L.append(f"Concept cluster compiled from `email_src/`. {len(keys)} paper(s).")
    L.append("")

    # Researchers active in this topic.
    active = sorted({n for n, r in researchers.items()
                     if r["topics"] and topic in r["topics"]})
    if active:
        links = ", ".join(_researcher_link(researchers[n]) for n in active)
        L.append(f"**Researchers**: {links}")
        L.append("")

    L.append("## Papers")
    L.append("")
    for k in sorted(keys, key=lambda k: (papers[k]["year"] or "", papers[k]["title"]),
                    reverse=True):
        p = papers[k]
        yr = f" ({p['year']})" if p["year"] else ""
        L.append(f"- {_paper_link(p)}{yr}")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _render_category(cat: str, keys: set, corpus: dict) -> str:
    papers = corpus["papers"]
    L: list[str] = []
    L.append(f"# Category: {cat.upper()}")
    L.append("")
    L.append(f"Coarse category bucket (mirrors `summaries/{cat}/`). "
             f"{len(keys)} paper(s), classified from title + snippet keywords.")
    L.append("")
    L.append("## Papers")
    L.append("")
    for k in sorted(keys, key=lambda k: (papers[k]["year"] or "", papers[k]["title"]),
                    reverse=True):
        p = papers[k]
        yr = f" ({p['year']})" if p["year"] else ""
        topics = ", ".join(f"[[topics/{t}|{_topic_display(t)}]]" for t in p["topics"])
        suffix = f" — {topics}" if topics else ""
        L.append(f"- {_paper_link(p)}{yr}{suffix}")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _render_source(src: str, info: dict, corpus: dict) -> str:
    papers = corpus["papers"]
    L: list[str] = []
    L.append(f"# Source: {src}")
    L.append("")
    L.append(f"- **Followed researcher**: {info['followed'] or 'Unknown'}")
    if info.get("date"):
        L.append(f"- **Alert date**: {info['date']}")
    L.append(f"- **Raw file**: [`email_src/{src}`](../../email_src/{src})")
    L.append("")
    L.append("> Raw source of truth — never edited. The pages below are compiled from it.")
    L.append("")
    L.append(f"## Papers introduced ({len(info['papers'])})")
    L.append("")
    for k in sorted(info["papers"]):
        if k in papers:
            L.append(f"- {_paper_link(papers[k])}")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _render_index(corpus: dict) -> str:
    papers = corpus["papers"]
    researchers = corpus["researchers"]
    topics = corpus["topics"]
    sources = corpus["sources"]

    L: list[str] = []
    L.append("# 🧠 Research Knowledge Base")
    L.append("")
    L.append("A self-maintaining, linked knowledge base in the style of Karpathy's "
             "*LLM Wiki / second brain*.")
    L.append("")
    L.append("- **`email_src/`** — the **raw** source of truth (Google Scholar alerts). "
             "Never edited.")
    L.append("- **`wiki/`** — **compiled** by `src/wiki.py` into the linked pages below. "
             "Rebuilt deterministically on every run, so the graph never rots.")
    L.append("")
    L.append(f"_Last compiled: {datetime.now(EDT).strftime('%Y-%m-%d %H:%M %Z')}_")
    L.append("")
    L.append("## At a glance")
    L.append("")
    L.append(f"- **Papers**: {len(papers)}")
    L.append(f"- **Researchers followed**: {len(researchers)}")
    L.append(f"- **Topics**: {len(topics)}")
    L.append(f"- **Source emails**: {len(sources)}")
    L.append("")

    # Researchers by paper count.
    L.append("## Researchers")
    L.append("")
    for name in sorted(researchers,
                       key=lambda n: (-len(researchers[n]["papers"]), n)):
        r = researchers[name]
        L.append(f"- {_researcher_link(r)} — {len(r['papers'])} paper(s)")
    L.append("")

    # Topics by paper count.
    L.append("## Topics")
    L.append("")
    for t in sorted(topics, key=lambda t: (-len(topics[t]), t)):
        L.append(f"- [[topics/{t}|{_topic_display(t)}]] — {len(topics[t])} paper(s)")
    L.append("")

    # Categories
    L.append("## Categories")
    L.append("")
    cat_counts: dict[str, int] = defaultdict(int)
    for p in papers.values():
        cat_counts[p["category"]] += 1
    for cat in ("control", "robotics", "ml", "other"):
        if cat_counts.get(cat):
            if cat == "other":
                L.append(f"- **OTHER** — {cat_counts[cat]} paper(s)")
            else:
                L.append(f"- [[topics/{cat}|{cat.upper()}]] — {cat_counts[cat]} paper(s)")
    L.append("")

    L.append("## Sources")
    L.append("")
    for src in sorted(sources):
        L.append(f"- {_link('sources/' + _slug(src), src)} "
                 f"({len(sources[src]['papers'])} paper(s))")
    L.append("")
    L.append(_footer())
    return "\n".join(L)


def _footer() -> str:
    return ("---\n*Compiled by `src/wiki.py` from the raw `email_src/` alerts — "
            f"{datetime.now(EDT).strftime('%Y-%m-%d %H:%M %Z')}. Do not hand-edit; "
            "edit the raw emails instead.*")


# ---------------------------------------------------------------------------
# Build driver
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(email_src: Path = EMAIL_SRC, wiki_dir: Path = WIKI_DIR) -> dict:
    """Compile email_src/ into a linked wiki/ knowledge base. Returns stats."""
    log.info("Compiling knowledge base: %s -> %s", email_src, wiki_dir)
    corpus = build_corpus(email_src)

    papers = corpus["papers"]
    researchers = corpus["researchers"]
    topics = corpus["topics"]
    sources = corpus["sources"]

    _write(wiki_dir / "index.md", _render_index(corpus))
    for p in papers.values():
        _write(wiki_dir / "papers" / f"{p['slug']}.md", _render_paper(p, corpus))
    for r in researchers.values():
        _write(wiki_dir / "researchers" / f"{r['slug']}.md", _render_researcher(r, corpus))
    for t, keys in topics.items():
        _write(wiki_dir / "topics" / f"{t}.md", _render_topic(t, keys, corpus))
    # Coarse category MOC pages (control/robotics/ml) so category links resolve.
    cat_groups: dict[str, set] = defaultdict(set)
    for p in papers.values():
        cat_groups[p["category"]].add(p["key"])
    for cat, keys in cat_groups.items():
        if cat == "other":
            continue
        _write(wiki_dir / "topics" / f"{cat}.md", _render_category(cat, keys, corpus))
    for src, info in sources.items():
        _write(wiki_dir / "sources" / f"{_slug(src)}.md", _render_source(src, info, corpus))

    stats = {
        "papers": len(papers),
        "researchers": len(researchers),
        "topics": len(topics),
        "sources": len(sources),
    }
    log.info("Knowledge base compiled: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="Compile email_src/ (raw) into a linked wiki/ knowledge base")
    parser.add_argument("--email-src", type=Path, default=EMAIL_SRC,
                        help="Raw source-of-truth directory of .eml alerts")
    parser.add_argument("--wiki-dir", type=Path, default=WIKI_DIR,
                        help="Output directory for the compiled wiki")
    args = parser.parse_args()

    stats = build(email_src=args.email_src, wiki_dir=args.wiki_dir)
    print(f"Compiled knowledge base -> {args.wiki_dir}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
