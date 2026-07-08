# PapersWiki — A Karpathy-style LLM Wiki that talks

PapersWiki turns the firehose of Google Scholar alert emails into a
**self-maintaining, linked knowledge graph** — and then *narrates it to you*.

Every weekday morning it emails a small batch of **audio distillations**: single
MP3s that don't read papers one-by-one, but take you on a spoken *tour of the
connections* — how the papers that are new since your last digest thread into
the topics, researchers, and prior work you already follow. It is modeled
directly on Andrej Karpathy's
[LLM Wiki / second brain](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
the `wiki/` vault is the compiled, interlinked artifact; the distillation
narrates its *shape*.

**Timezone:** all timestamps are EDT (America/New_York).

---

## The idea in one picture

```
  email_src/*.eml           src/wiki.py            wiki/  (Obsidian vault)
  ─────────────────   ───────────────────────►   ────────────────────────
  RAW, immutable       compile deterministically   papers/ researchers/
  Scholar alerts       (stdlib-only, offline)      topics/ sources/ index.md
  (source of truth)                                        │
                                                           │  src/distill.py
                                                           ▼  (graph → narration)
                                            audio/digests/distill_<date>_b<n>.mp3
                                                           │  src/wiki_digest.py
                                                           ▼  (Gmail SMTP)
                                                    📧 $SMTP_USER
```

Two layers, cleanly separated (Karpathy's contract):

- **`email_src/` is the raw source of truth** — your `.eml` alerts. *Never edited.*
- **`wiki/` belongs to the compiler** — regenerated deterministically on every
  run, so the graph never goes stale.

This is **not RAG**. The alerts *compile once* into linked pages that compound
over time, rather than being re-retrieved and re-summarized on every query.

---

## What lands in your inbox

Monday–Friday at **5:00 AM ET**, a launchd agent runs the pipeline and sends
**3 distillation emails per session** (configurable), draining your alert
backlog in digestible tranches. Each email is self-contained:

- **One MP3** — a ~1,100-word spoken briefing (~8–10 min) that:
  - opens with the state of the graph (papers, topics, researchers),
  - tours the new papers **grouped by topic cluster**, and for each narrates
    *who wrote it, what it is in one line, and which existing papers it links
    into* (shared researcher first, then shared topic),
  - names the **most active researchers** in the batch,
  - closes on the graph's **densest hubs**.
- **Concise "show notes"** — a text table-of-contents of what the audio covers
  (featured papers + URLs, topic clusters touched, active researchers, hubs),
  plus a **backlog counter** so you can watch the queue drain.

When the backlog is empty, the session simply sends nothing (no spurious
"recap" emails).

---

## Backlog draining (why 3 emails/session)

The alert backlog can be large, so PapersWiki serves it in bites instead of one
overwhelming stream:

- Each session sends `BATCH_COUNT` emails (default **3**), each featuring
  `TRANCHE_SIZE` papers (default **12**).
- A per-paper **seen-ledger** (`state/digest_seen.json`) records exactly which
  papers have been narrated. Each tranche marks **only its own papers** seen, so
  the next email/session picks up precisely where the last left off — **no
  repeats, no gaps**.
- At ~36 papers/session the backlog empties in roughly a work-week, after which
  each morning's session only covers whatever genuinely new alerts arrived.

Tune per run via environment variables:

```bash
BATCH_COUNT=4 TRANCHE_SIZE=10 BATCH_PAUSE=60 scripts/mwf_digest.sh
```

---

## Text-to-speech & rate limits (important)

Audio is synthesized with **gTTS (Google Text-to-Speech)**, which is limited to
roughly **100 requests per hour per IP**. The architecture is designed around
this:

- **One distillation = exactly one gTTS request.** A whole session of 3–4 emails
  is 3–4 requests — orders of magnitude under the ceiling.
- **Never bulk-synthesize per-paper.** The legacy `scripts/generate_wiki_audio.py`
  makes *one request per paper*; running it fresh over a large corpus **will**
  trip the 100/hour wall and earn a multi-hour IP block. It is no longer part of
  the delivery flow. If you must run it, use its built-in throttles
  (`--sleep`, `--retry-429-sleep`).
- **Backoff + offline fallback.** `synthesize()` retries gTTS 429s with
  exponential backoff, then falls back to macOS's offline `/usr/bin/say`
  (transcoded to MP3 via `ffmpeg` if present, otherwise `.aiff`) — so a
  scheduled run **always produces audio** even if Google is throttling.

> If you have been sending more than ~100 gTTS requests per hour, carefully
> batch your requests so you don't get rate-limited. PapersWiki's one-request-
> per-distillation design keeps you comfortably under that ceiling; the
> per-paper generator is the only thing that can blow past it.

---

## Directory structure

```
.
├── README.md                    # This file
├── pipeline.py                  # Legacy orchestrator (wiki + Claude paper stages)
├── scripts/
│   ├── mwf_digest.sh            # launchd entry point: weekday backlog-drain sender
│   ├── generate_wiki_audio.py   # Per-paper MP3s (NOT in delivery flow; rate-limit risk)
│   └── regenerate_audio.sh      # Batch regen from summaries/ (legacy)
├── src/
│   ├── wiki.py                  # Compiles email_src/ → wiki/  (stdlib-only, offline)
│   ├── distill.py               # Graph → single spoken distillation MP3  ★ core
│   ├── wiki_digest.py           # Builds show-notes + emails the MP3 via Gmail SMTP
│   ├── ingest.py                # Raw .eml parser + paper discovery
│   ├── fetch.py summarize.py render.py audio.py digest.py context.py
│   └── input_handler.py
├── state/
│   ├── digest_seen.json         # Seen-ledger — defines what counts as "new"
│   └── processed.json           # Legacy dedup ledger (paper pipeline)
├── wiki/                        # COMPILED knowledge base (open as an Obsidian vault)
│   ├── index.md  papers/  researchers/  topics/  sources/
├── audio/
│   └── digests/                 # distill_<date>_b<n>.mp3 — the emailed distillations
├── docs/
│   ├── AUDIO_GUIDE.md           # Guide for audio generation
│   ├── SKILLS.md                # Skills documentation
│   └── UNIVERSAL_INPUT_GUIDE.md # Universal input handling guide
├── logs/                        # Pipeline + session logs
└── email_src/*.eml              # RAW source of truth — never edited
```

---

## How the knowledge base is compiled (`src/wiki.py`)

Fully offline, stdlib-only (no API key, no network, no BeautifulSoup) so it
always runs. It:

1. Parses every `.eml` in `email_src/` into structured records (title, URL,
   authors, venue, year, snippet, followed researcher).
2. Reconciles duplicate alerts into **unique papers**.
3. Classifies each paper into **topic clusters** (CBFs, Hamilton-Jacobi
   reachability, diffusion, RL, manipulation, locomotion, …) via the keyword
   taxonomy in `src/wiki.py` (`TOPIC_KEYWORDS`) and coarse categories
   (control / robotics / ml / other).
4. Canonicalizes abbreviated author names (`D Rus` → `Daniela Rus`) to link
   co-authored papers to the researchers you follow.
5. Emits the linked vault — `papers/`, `researchers/`, `topics/`, `sources/`,
   and an `index.md` Map-of-Content — using Obsidian wikilinks with backlinks.

```bash
python src/wiki.py            # rebuild wiki/ from email_src/
```

Retune the taxonomy by editing `TOPIC_KEYWORDS` in `src/wiki.py` (and research
themes in `src/context.py`), then rebuild.

---

## How the distillation is composed (`src/distill.py`)

1. `wiki.build_corpus()` → the in-memory linked graph.
2. Diff against `state/digest_seen.json` → the **unseen** papers, ordered
   deterministically (year desc, then title).
3. Carve out this run's **tranche** (`--limit N`).
4. Compose a flowing, connection-oriented narration (grouped by topic; each
   paper narrated with its graph neighbours).
5. Synthesize **one MP3** to `audio/digests/`, with gTTS-429 backoff and the
   offline `say` fallback.
6. Mark **only the tranche** seen (unless `--peek`).

```bash
# Preview the narration text without synthesizing or touching the ledger:
python src/distill.py --script-only --limit 12

# Build one tranche MP3 for real (advances the ledger):
python src/distill.py --limit 12

# Full-graph tour (everything at once):
python src/distill.py --force-all
```

Key flags: `--limit N` (tranche size), `--peek` (don't advance ledger),
`--skip-if-empty` (exit quietly when backlog is dry), `--force-all`,
`--max-featured N`, `--tag SUFFIX`.

---

## Emailing (`src/wiki_digest.py`)

Builds the show-notes body, attaches the single distilled MP3, and sends via
**Gmail SMTP over SSL**. Credentials come from the environment
(`SMTP_USER`, `SMTP_PASS`, `SMTP_HOST`, `SMTP_PORT`); the launchd wrapper loads
them from `~/.zsh_aliases` (grepping only the four `SMTP_*` export lines so it
never triggers interactive-zsh side effects). `SMTP_PASS` is a Gmail **App
Password**, not the account password.

```bash
# Dry run — build MP3 + print the email body, send nothing, don't advance ledger:
python src/wiki_digest.py --dry-run --limit 12

# Send one tranche now:
python src/wiki_digest.py --limit 12 --to you@example.com
```

---

## Scheduling (macOS launchd)

Delivery is driven by a LaunchAgent, **not** cron (more reliable on macOS across
sleep/wake):

- **Plist:** `~/Library/LaunchAgents/com.moluxlabs.paperswiki.mwf.plist`
- **Schedule:** weekdays (Mon–Fri), **05:00** local, via `StartCalendarInterval`.
- **Runs:** `scripts/mwf_digest.sh` → rebuild wiki → send up to `BATCH_COUNT`
  tranche emails → stop when backlog empty.
- **Logs:** `logs/mwf_digest_<timestamp>.log`, plus
  `logs/launchd_mwf.{out,err}.log`.

```bash
# Install / reload:
launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/com.moluxlabs.paperswiki.mwf.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.moluxlabs.paperswiki.mwf.plist

# Inspect:
launchctl print gui/$(id -u)/com.moluxlabs.paperswiki.mwf

# Fire once now (out of schedule):
launchctl kickstart -k gui/$(id -u)/com.moluxlabs.paperswiki.mwf
```

---

## Prerequisites

- **Python 3.11+** with `gtts` (the compiler & distiller are otherwise
  stdlib-only). Verify: `python -c "import gtts; print(gtts.__version__)"`.
- **Gmail App Password** exported as `SMTP_PASS` in `~/.zsh_aliases`:
  ```bash
  export SMTP_USER="you@example.com"
  export SMTP_PASS="xxxxxxxxxxxxxxxx"   # Gmail App Password (no spaces)
  export SMTP_HOST="smtp.gmail.com"
  export SMTP_PORT="465"
  ```
- **macOS** for launchd scheduling and the offline `say` TTS fallback.
- *(Optional)* `ffmpeg` so the `say` fallback yields `.mp3` instead of `.aiff`:
  `brew install ffmpeg`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `gTTSError: 429 (Too Many Requests)` | gTTS 100 req/hr IP limit — usually from running the per-paper generator. Wait for the quota to reset; the distiller's `say` fallback covers scheduled runs. |
| Empty / duplicate emails | Inspect `state/digest_seen.json`. Delete it to re-drain the whole backlog from scratch; it advances one tranche per email. |
| No email sent | `SMTP_PASS` unset — ensure `~/.zsh_aliases` exports it and 2FA + App Password are configured on the Gmail account. |
| Job never fires | `launchctl print gui/$(id -u)/com.moluxlabs.paperswiki.mwf`; check `logs/launchd_mwf.err.log`. |
| Wiki looks stale | Rebuild: `python src/wiki.py`. It's deterministic and safe to run anytime. |

---

## Legacy: the Claude paper pipeline

Before the distillation model, `pipeline.py` fetched each paper, summarized it
with the Claude API (`src/summarize.py`), rendered per-paper Markdown to
`summaries/`, and synthesized per-paper MP3s. Those modules remain for reference
and one-off use, but the **default delivery is now the offline, API-key-free
knowledge-graph distillation** described above. (The Claude path also requires
`ANTHROPIC_API_KEY` and is subject to its own credit limits.)

---

**Maintainer:** Lekan Molu · **License:** internal use by
Molux Labs · **Timezone:** EDT (UTC-4).
```
