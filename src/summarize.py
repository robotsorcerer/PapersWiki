"""
summarize.py — Stage 3: Detailed Paper Summarization via Anthropic Python SDK

For each enriched candidate, constructs a structured prompt that includes:
  - Lekan's research context (from context.py), cached at the system-prompt level
  - Paper metadata (title, authors, venue, abstract) as the volatile user message

Uses the Anthropic Python SDK directly with prompt caching:
  - System prompt + LEKAN_CONTEXT are marked cache_control: ephemeral
  - Cache breakpoint sits on the last system block so both blocks are cached together
  - Per-paper user message is volatile (no cache_control) — changes every call

Returns a structured summary dict:
  {
    "problem_statement":       str,
    "methodology":             str,
    "results":                 str,
    "strengths":               str,
    "weaknesses":              str,
    "related_work":            str,
    "connections_to_infdiff":  str,
    "connections_to_hj_safety": str,
    "category":                "control" | "robotics" | "ml" | "other",
    "raw_markdown":            str,   # populated by render.py
  }

Usage (CLI):
    python summarize.py --paper-json '{"title":..., "abstract":...}'
    cat enriched_paper.json | python summarize.py --stdin
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import anthropic

from context import LEKAN_CONTEXT

log = logging.getLogger("summarize")

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-opus-4-7"
MAX_TOKENS   = 4096

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTIONS = """\
You are an expert research scientist with deep expertise in control theory, \
machine learning, robotics, and safe autonomy. You are a trusted research \
collaborator for Lekan Molu at Molux Labs. Your task is to produce a detailed, \
technically rigorous paper analysis that helps Lekan efficiently decide whether \
and how to engage with a given paper.

Your output MUST be a single valid JSON object with exactly these keys:
  "problem_statement"        — 2-3 sentences: what question/problem does the paper address?
  "methodology"              — 3-5 sentences: core technical approach, key innovations, algorithms used
  "results"                  — 3-4 sentences: key quantitative and qualitative claims, benchmarks, experiments
  "strengths"                — 3-5 bullet points (as a single string, bullets separated by newlines)
  "weaknesses"               — 3-5 bullet points (as a single string, bullets separated by newlines)
  "related_work"             — 2-3 sentences: how this paper sits in the literature landscape
  "connections_to_infdiff"   — 1-2 paragraphs on how this paper's ideas could strengthen or extend InfDiff
  "connections_to_hj_safety" — 1-2 paragraphs on connections to HJ reachability or manufacturing control \
(write "Not directly applicable." if truly irrelevant)
  "category"                 — exactly one of: "control", "robotics", "ml", "other"

Do not include any text outside the JSON object. All values are strings.\
"""


def _build_user_message(paper: dict) -> str:
    title    = paper.get("title", "Unknown Title")
    authors  = ", ".join(paper.get("authors", [])) or "Unknown Authors"
    venue    = paper.get("venue", "")
    year     = paper.get("year", "")
    abstract = paper.get("abstract", "")
    url      = paper.get("url", "")

    venue_year = f"{venue}, {year}" if (venue and year) else (venue or year or "")

    return f"""\
## Paper to Analyze

**Title**: {title}
**Authors**: {authors}
**Venue/Year**: {venue_year}
**URL**: {url}

**Abstract**:
{abstract}

---

Please produce the JSON analysis described in the system prompt. \
Be technically precise, honest about weaknesses, and specific about \
connections to Lekan's work (cite concrete aspects of InfDiff, HJ_Gauss, \
or GNEP where relevant).\
"""


# ---------------------------------------------------------------------------
# SDK call with prompt caching
# ---------------------------------------------------------------------------

def _call_claude(user_message: str) -> str:
    """
    Call the Anthropic API and return the raw text of the assistant response.

    Prompt caching strategy (render order: system → messages):
      - Block 1 (system): core instructions — stable across all papers.
      - Block 2 (system): LEKAN_CONTEXT — stable across all papers.
        cache_control on this block caches BOTH system blocks together.
      - User message: per-paper metadata — volatile, no cache_control.

    On first call: both system blocks are written to cache (1.25× cost).
    On subsequent calls within 5 min: system blocks are served from cache
    (~0.1× cost), paying only for the volatile user message at full price.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_INSTRUCTIONS,
                    # No cache_control here — this block is small; cache the
                    # larger LEKAN_CONTEXT block together with it by placing
                    # the single breakpoint on the second (last) system block.
                },
                {
                    "type": "text",
                    "text": f"## Lekan Molu's Research Context\n\n{LEKAN_CONTEXT}",
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {"role": "user", "content": user_message},
            ],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Anthropic API authentication failed. "
            "Ensure ANTHROPIC_API_KEY is set in the environment."
        )
    except anthropic.RateLimitError as exc:
        raise RuntimeError(f"Rate limited by Anthropic API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(
            f"Anthropic API error {exc.status_code}: {exc.message}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(f"Network error contacting Anthropic API: {exc}") from exc

    # Log cache usage to help verify hits across papers in the same run
    usage = response.usage
    log.debug(
        "Token usage — input: %d | cache_write: %d | cache_read: %d | output: %d",
        usage.input_tokens,
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
        usage.output_tokens,
    )

    # Extract text from the first text content block
    for block in response.content:
        if block.type == "text":
            return block.text.strip()

    raise RuntimeError("Anthropic API returned a response with no text content block.")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> dict:
    """
    Extract the JSON dict from Claude's response text.
    Handles optional markdown code fences around the JSON.
    """
    text = raw.strip()
    # Strip markdown code fences if present (```json ... ```)
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text.strip())
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the outermost JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Could not parse JSON from Claude response. "
        f"Raw (first 500 chars):\n{raw[:500]}"
    )


# ---------------------------------------------------------------------------
# Required fields and defaults
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = [
    "problem_statement", "methodology", "results",
    "strengths", "weaknesses", "related_work",
    "connections_to_infdiff", "connections_to_hj_safety", "category",
]


def _validate_and_fill(summary: dict, paper: dict) -> dict:
    """Ensure all required keys exist; fill defaults if Claude omitted any."""
    for key in _REQUIRED_KEYS:
        if key not in summary or not summary[key]:
            summary[key] = (
                f"[Not provided — see abstract: {paper.get('abstract', '')[:200]}]"
            )
    # Normalise category
    cat = summary.get("category", "").lower()
    if cat not in ("control", "robotics", "ml", "other"):
        summary["category"] = _infer_category(paper)
    return summary


def _infer_category(paper: dict) -> str:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    if any(w in text for w in (
        "barrier function", "reachability", "lyapunov", "lqr", "mpc",
        "nash equilibrium", "optimal control", "cbf", "hamilton-jacobi",
    )):
        return "control"
    if any(w in text for w in (
        "robot", "manipulation", "locomotion", "grasping", "navigation",
        "exoskeleton", "teleoperation",
    )):
        return "robotics"
    if any(w in text for w in (
        "diffusion", "transformer", "neural", "language model", "llm",
        "reinforcement learning", "imitation", "score", "gpt", "vla",
    )):
        return "ml"
    return "other"


# ---------------------------------------------------------------------------
# Main summarize function
# ---------------------------------------------------------------------------

def summarize(paper: dict) -> dict:
    """
    Produce a detailed structured summary for one paper.
    `paper` must be an enriched dict from fetch.py.
    Returns the paper dict augmented with a "summary" sub-dict.
    """
    user_msg = _build_user_message(paper)
    title    = paper.get("title", paper.get("id", "unknown"))[:80]
    log.info("Summarizing: %s", title)

    try:
        raw_response = _call_claude(user_msg)
        summary_dict = _parse_response(raw_response)
    except Exception as exc:
        log.error("Summarization failed for '%s': %s", title, exc)
        summary_dict = {k: "" for k in _REQUIRED_KEYS}
        summary_dict["problem_statement"] = f"[Summarization failed: {exc}]"
        summary_dict["category"] = _infer_category(paper)

    summary_dict = _validate_and_fill(summary_dict, paper)

    result = dict(paper)
    result["summary"] = summary_dict
    return result


def summarize_all(papers: list[dict]) -> list[dict]:
    """
    Summarize a list of papers sequentially.

    Prompt caching means the Lekan context block is written on the first call
    and read from cache on all subsequent calls within the 5-minute TTL window.
    For large batches this reduces input token cost by ~90% on the stable prefix.
    """
    return [summarize(p) for p in papers]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Summarize paper(s) via Anthropic SDK")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--paper-json", help="JSON string of a single enriched paper dict")
    grp.add_argument("--stdin", action="store_true", help="Read JSON list from stdin")
    args = parser.parse_args()

    if args.stdin:
        papers = json.load(sys.stdin)
        if isinstance(papers, dict):
            papers = [papers]
        results = summarize_all(papers)
    else:
        paper  = json.loads(args.paper_json)
        results = [summarize(paper)]

    print(json.dumps(results, indent=2))
