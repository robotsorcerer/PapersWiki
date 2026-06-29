# PapersWiki — Automated Paper Processing & Digestion

A fully automated pipeline that processes research papers from multiple sources, generates detailed 1-2 page summaries with strength/weakness analysis, synthesizes audio narration, and delivers daily digests via email. Built for researchers who need to stay current with rapidly-evolving literature.

**Timezone:** All timestamps are in EDT (Eastern Daylight Time, UTC-4).

## What It Does

**Input Sources:**
- Google Scholar Alert emails (`.eml` files in `email_src/`)
- Manual paper links (`papers_to_read.md`)

**Processing Pipeline (5 Stages):**

1. **Ingest** — Scan for new papers, deduplicate against `state/processed.json`
2. **Fetch** — Retrieve metadata via arXiv API or HTML scraping
3. **Summarize** — Generate detailed analysis using Claude API with prompt caching
4. **Render** — Output rich Markdown summaries to `summaries/<category>/`
5. **Audio** — Synthesize 3-5 minute MP3 narration via gTTS

**Daily Delivery:**
- Morning email digest (configurable time)
- MP3 attachments of new paper summaries
- Connections to your research highlighted

## Output: Detailed Summaries

Each paper generates a markdown file with:
- **Problem Statement** — What research question does this paper address?
- **Methodology** — How do they solve it? Key technical contributions.
- **Results & Claims** — Experiments, benchmarks, evidence.
- **Strengths** — What's novel or solid about this work?
- **Weaknesses** — Limitations, gaps, experimental design flaws.
- **Related Work Placement** — Where does this fit in the literature?
- **Connections to Your Research** — How could ideas from this paper improve your work? (InfDiff, HJ safety, manufacturing control, etc.)

Example output path: `summaries/control/2603.24566_integral_cbf_input_delay.md`

## Directory Structure

```
.
├── README.md                   # This file
├── SKILLS.md                   # Original task specification
├── pipeline.py                 # Main orchestrator
├── scripts/
│   └── run_pipeline.sh        # Cron entry point
├── src/
│   ├── ingest.py              # Stage 1: paper discovery
│   ├── fetch.py               # Stage 2: metadata retrieval
│   ├── summarize.py           # Stage 3: Claude summarization
│   ├── render.py              # Stage 4: markdown rendering
│   ├── audio.py               # Stage 5: TTS synthesis
│   ├── digest.py              # Morning email sender
│   └── context.py             # Research context for Claude
├── state/
│   └── processed.json         # Deduplication ledger
├── summaries/                 # Output markdown files
│   ├── control/
│   ├── robotics/
│   └── ml/
├── audio/                     # Persisted MP3 files
│   ├── control/
│   ├── robotics/
│   └── ml/
├── logs/                      # Pipeline execution logs
├── papers_to_read.md          # Manual paper intake
└── email_src/
    └── *.eml                  # Google Scholar alert emails
```

## Quick Start

### Prerequisites

- Python 3.11+ (conda env `311`)
- Anthropic API key with credits
- Gmail account with App Password
- Cron daemon

### Installation

1. **Set environment variables** in `~/.bashrc`:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export SMTP_PASS="xxxx xxxx xxxx xxxx"  # Gmail App Password
   ```

2. **Verify dependencies**:
   ```bash
   source /home/lex/miniconda3/etc/profile.d/conda.sh
   conda activate 311
   python -c "import anthropic, gtts, bs4; print('✓ Ready')"
   ```

3. **Test with one paper**:
   ```bash
   cd ~/Documents/Papers/PapersWiki
   python pipeline.py --limit 1 --dry-run
   ```
   Check `logs/pipeline_*.log` for details. All timestamps are in EDT.

### Schedule with Cron

Edit `crontab -e` and add (all times in EDT):

```bash
# Process new papers at midnight EDT daily
0 0 * * * /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh

# Send digest at 6 AM EDT daily (optional: if you want to separate processing from email)
0 6 * * * /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh --digest-only
```

## Usage

### Full pipeline (all stages):
```bash
python pipeline.py
```

### Dry run (skip email):
```bash
python pipeline.py --dry-run
```

### Process only N papers:
```bash
python pipeline.py --limit 5
```

### Only ingest (debug paper detection):
```bash
python pipeline.py --ingest-only
```

### Reprocess all papers (clear state):
```bash
python pipeline.py --force-rescan
```

## How It Works

### Stage 1: Ingest

Scans two input sources:
1. `.eml` files in `email_src/` directory (Google Scholar Alert emails)
   - Parses HTML from quoted-printable encoded email bodies
   - Extracts arxiv/doi links and paper titles
2. `papers_to_read.md` — Markdown links in format `[Title](URL)`

Deduplicates against `state/processed.json`. Each candidate gets a stable `id` (either `arxiv:<id>` or `url:<hash>`). Timestamps are in EDT.

### Stage 2: Fetch

For each candidate URL:
- **arXiv URLs**: Query the arXiv API for title, authors, abstract, category, year
- **Other URLs**: Scrape `<meta name="description">` and `<title>` tags as fallback

Returns enriched metadata dict.

### Stage 3: Summarize

Calls Claude Sonnet via Anthropic SDK with:
- **System prompt** (cached): Categorization rules, research context (InfDiff, HJ safety, manufacturing)
- **User message**: Paper abstract + title, request for detailed analysis

Returns JSON output with sections:
```json
{
  "category": "control" | "robotics" | "ml",
  "problem_statement": "...",
  "methodology": "...",
  "results": "...",
  "strengths": "...",
  "weaknesses": "...",
  "related_work": "...",
  "connections_to_infdiff": "...",
  "connections_to_hj_safety": "..."
}
```

**Prompt Caching:** System prompt cached with `cache_control: {"type": "ephemeral"}` — first call writes cache (~1.25× cost), subsequent calls read at ~0.1× cost. ~90% savings on stable prefix.

### Stage 4: Render

Converts summarized JSON to rich Markdown with fixed template:
- Header (title, authors, venue, category)
- All 7 sections from summary
- Audio file path
- Generation timestamp

Output: `summaries/<category>/<arxiv_id>_<slug>.md`

### Stage 5: Audio

Extracts narrative text from markdown, strips formatting, synthesizes MP3 via gTTS:
```python
from gtts import gTTS
gTTS(summary_text, lang="en", tld="com").save(mp3_path)
```

Typical 800-word summary → ~3-5 minutes of audio.

Output: `audio/<category>/<arxiv_id>_<slug>.mp3`

### Digest Email

Morning job that reads `audio/` directory, attaches new MP3s, and sends to `you@example.com` with:
- List of papers processed (count by category)
- Brief snippet of each paper's problem statement
- Link to full markdown summary
- Audio MP3 attachment

## Architecture Decisions

### Why 5 stages?
- **Separation of concerns**: each stage can be tested/debugged independently
- **Resilience**: if stage N fails, stages 1–(N-1) succeed and retry next run
- **Extensibility**: easy to insert new sources (RSS, arXiv feeds) or outputs (web UI, Slack)

### Why prompt caching?
- Saves ~90% on repeated system prompts (categorization rules, research context)
- First run ~1.25× cost, subsequent runs ~0.1× cost
- With 5-10 papers/day, ~3 cache hits per run = ~50% overall savings

### Why two cron jobs?
- Decouple processing (midnight) from delivery (6 AM)
- If network outage kills midnight processing, 6 AM still sends whatever was successful
- Allows manual dry-run processing without triggering email

### Why gTTS instead of other TTS?
- Free (after initial API quota)
- No model/voice licensing complexity
- Consistent quality for academic content
- Direct MP3 output, no transcoding needed

## Costs & Performance

**API Costs:**
- ~$0.01/day at Sonnet pricing (5-10 papers with prompt caching)
- Varies: complex abstracts → higher token count

**Storage:**
- ~500 KB per summary markdown
- ~1-3 MB per 3-5 minute MP3
- 10 papers/day = ~5 MB storage/day

**Compute:**
- Ingest: <1s
- Fetch: ~5s (network-bound, one URL per second)
- Summarize: ~10s per paper (Claude API RTT)
- Render: <1s
- Audio: ~5s per paper (gTTS synthesis)
- **Total: ~2-3 min for 10 papers**

## Customization

### Change email recipient:
Edit `src/digest.py` line 40:
```python
GMAIL_USER_DEFAULT = "your-email@example.com"
```

### Change cron time:
Edit `crontab -e`:
```bash
# 5:50 AM instead of midnight (sends digest by 6 AM)
50 5 * * * /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh
```

### Add research context:
Edit `src/context.py` to include your papers/results, then update the system prompt in `src/summarize.py`.

### Filter by category:
In `src/pipeline.py`, add post-processing to skip categories:
```python
if category not in ("control", "robotics"):
    continue  # skip ML papers
```

## Troubleshooting

**Pipeline fails with "ANTHROPIC_API_KEY is not set":**
- Ensure `ANTHROPIC_API_KEY` is in `~/.bashrc` or crontab
- Test: `echo $ANTHROPIC_API_KEY` in your shell

**arXiv API returns empty results:**
- Check if arxiv_id is valid (format: `YYMM.NNNNN`)
- Network timeout: retry next run (automatic)

**Email not sending:**
- Verify `SMTP_PASS` is set to Gmail App Password (not account password)
- Ensure 2FA is enabled on Gmail account
- Check `logs/digest_*.log`

**Audio synthesis fails:**
- Verify gTTS is installed: `pip list | grep gtts`
- Check internet connectivity (gTTS requires network)
- Confirm `ffmpeg` is available: `which ffmpeg`

**Papers not being detected:**
- Run `python pipeline.py --ingest-only` to see candidates
- Check `.eml` file encoding (should be UTF-8)
- Verify `papers_to_read.md` uses markdown link syntax: `[Title](URL)`

## Contributing

To extend the pipeline:

1. **Add new input source**: Modify `src/ingest.py` with new parser
2. **Change summarization logic**: Edit system prompt in `src/summarize.py`
3. **Add output format**: Create new `render_*` function in `src/render.py`

All stages are independent Python modules — feel free to refactor or parallelize.

## License

Internal use by Molux Labs.

---

**Last updated:** 2026-05-02 (EDT)  
**Maintainer:** Lekan Molu (you@example.com)  
**Timezone:** EDT (Eastern Daylight Time, UTC-4)
