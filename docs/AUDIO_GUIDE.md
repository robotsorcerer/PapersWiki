# PapersWiki Audio Generation Guide

## Overview

You now have a complete, generalizable system to convert academic papers into audio summaries using Google Text-to-Speech (gTTS). The system works in two modes:

### Mode 1: Full Intelligence (Claude API) — Best Quality
When the Anthropic API is available and has credits, the system:
1. Fetches paper metadata from arXiv
2. Uses Claude to produce a detailed technical summary
3. Renders to Markdown with structured sections
4. Generates audio with rich context

### Mode 2: Abstract-Only Fallback — Offline/Budget-Friendly
When the API is unavailable or out of credits:
1. Fetches paper metadata from arXiv
2. Uses the paper abstract as the primary content source
3. Renders to Markdown with the full abstract
4. Generates audio directly from abstract + metadata

Both modes produce **MP3 audio files** (~20-25 minutes) suitable for leisure listening.

---

## Quick Start

### Process a Single Paper

**Using the full Claude pipeline:**
```bash
cd /home/lex/Documents/Papers/PapersWiki
/home/lex/miniconda3/envs/311/bin/python process_paper.py --arxiv-id 2605.17232
```

**Using abstract-only (no API needed):**
```bash
/home/lex/miniconda3/envs/311/bin/python process_paper_no_api.py --arxiv-id 2605.17232
```

**With a full arXiv URL:**
```bash
python process_paper.py --url https://arxiv.org/pdf/2605.17232
python process_paper.py --url https://arxiv.org/abs/2605.17232
```

---

## Output Files

Audio files are saved in:
```
audio/<category>/<arxiv_id>_<title_slug>.mp3
```

Categories: `control`, `robotics`, `ml`, `other`

Markdown summaries are saved in:
```
summaries/<category>/<arxiv_id>_<title_slug>.md
```

### Example Output for Your Paper

- **Audio**: `audio/ml/dimension_free_convergence_of_discrete_diffusion_m.mp3` (1.5 MB, ~18 min)
- **Markdown**: `summaries/ml/dimension_free_convergence_of_discrete_diffusion_m.md`

---

## Audio Content Structure

The MP3 audio follows this narration script (automatically generated from the summary):

1. **Title + Authors + Venue/Year** — Paper identification
2. **Problem Statement** — The research question
3. **Methodology** — Core technical approach
4. **Results** — Key findings and claims
5. **Strengths** — Paper's advantages
6. **Limitations** — Weaknesses/gaps
7. **Related Work** — Position in literature
8. **Connections** — Tie-in to Lekan's research (when Claude API available)

**Duration**: 15-25 minutes at natural speech speed (150 WPM)

---

## System Architecture

### Pipeline Stages

```
Stage 1: Fetch (src/fetch.py)
  ↓ Fetches title, authors, abstract from arXiv API
  ↓
Stage 2: Summarize (src/summarize.py) — OPTIONAL, requires Claude API
  ↓ Produces structured JSON with problem/methodology/results/etc.
  ↓
Stage 3: Render (src/render.py)
  ↓ Converts summary to Markdown file
  ↓
Stage 4: Audio (src/audio.py)
  ↓ Converts Markdown to MP3 via gTTS
  ↓
Output: .md + .mp3 files
```

### Orchestrators

| Script | Mode | API Required? | Use Case |
|--------|------|---------------|----------|
| `process_paper.py` | Full intelligence | Yes (Claude) | Best quality, with detailed analysis |
| `process_paper_no_api.py` | Abstract-only | No | Offline, budget-friendly, fallback |
| `pipeline.py` | Batch processing | Yes (Claude) | Process multiple papers at once |

---

## Customization

### Change Audio Language

Edit `src/audio.py`, line ~223:
```python
tts = gTTS(text=script, lang="en", tld="com", slow=False)  # Change lang="en" to another code
```

Supported languages: `en`, `es`, `fr`, `de`, `it`, `pt`, `ja`, `zh`, etc.

### Adjust Speech Rate

Same location, set `slow=True` for slower (1.5× slower) narration.

### Customize Narration Script

The `_build_script()` function in `src/audio.py` (line ~88) controls what gets read. Modify section order or add/remove fields:

```python
parts.append(f"Problem. {prob}")  # These are the parts that become audio
parts.append(f"Approach. {meth}")
```

### Change Output Category

The system auto-categorizes papers. To override for a specific paper:
1. Edit the markdown file and change the category in the frontmatter
2. Move the audio file to the correct `audio/<category>/` folder

---

## Batch Processing

To process multiple papers from a list of arXiv IDs:

```bash
cat > /tmp/papers.txt << EOF
2605.17232
2604.21100
2603.24566
EOF

while read id; do
  /home/lex/miniconda3/envs/311/bin/python process_paper_no_api.py --arxiv-id "$id"
done < /tmp/papers.txt
```

Or modify `pipeline.py` to read from your email or paper list and process all pending papers.

---

## Environment & Dependencies

**Python Environment**: `/home/lex/miniconda3/envs/311/`

**Required Packages**:
- `anthropic` — Claude API (for full mode)
- `gtts` — Google Text-to-Speech
- `beautifulsoup4` — HTML parsing fallback

**API Keys Required**:
- `ANTHROPIC_API_KEY` (for `process_paper.py` only, not needed for `process_paper_no_api.py`)

---

## Troubleshooting

### "Module not found: anthropic"
You're using the wrong Python. Always use:
```bash
/home/lex/miniconda3/envs/311/bin/python process_paper.py ...
```

### "Credit balance too low"
Your Anthropic API account ran out of credits. Use `process_paper_no_api.py` instead, or:
1. Go to https://console.anthropic.com/account/billing/overview
2. Add credits
3. Then switch back to `process_paper.py` for better summaries

### "HTTP 429: Too many requests"
You're hitting arXiv API rate limits. Wait a few minutes and try again, or the system will automatically fall back to HTML scraping.

### Audio quality is poor
This is normal for gTTS (free service). For better quality, consider paid TTS options:
- Google Cloud Text-to-Speech (better quality, paid)
- Amazon Polly
- Azure Text-to-Speech

To integrate a different TTS provider, modify `src/audio.py` in the `synthesize()` function.

---

## For Future Papers

To process any new paper from arXiv:

1. **Copy the arXiv URL or ID** from the paper's arXiv page
2. **Run the one-liner**:
   ```bash
   /home/lex/miniconda3/envs/311/bin/python \
     /home/lex/Documents/Papers/PapersWiki/process_paper_no_api.py \
     --url https://arxiv.org/pdf/<arxiv_id>
   ```
3. **Find your audio file** in the output (printed at the end)
4. **Listen during leisure time** 🎧

The system is fully generalizable — no paper-specific configuration needed.

---

## Current Paper: Dimension-Free Convergence of Discrete Diffusion Models

**arXiv ID**: 2605.17232  
**Title**: Dimension-Free Convergence of Discrete Diffusion Models: Adjoint Equations Induce the Right Space  
**Authors**: Kelvin Kan, Xingjian Li, Benjamin J. Zhang (+ 3 more)  
**Category**: Machine Learning  
**Published**: May 2026  

**Audio File**: `audio/ml/dimension_free_convergence_of_discrete_diffusion_m.mp3` (1.5 MB, ~18 min)  
**Markdown**: `summaries/ml/dimension_free_convergence_of_discrete_diffusion_m.md`

The paper develops a unified adjoint-equation-based framework for establishing dimension-free convergence guarantees in discrete diffusion models. It addresses fundamental limitations in existing KL-based and TV-based convergence analyses.
