# Audio Generation Guide

## Overview
The PapersWiki system generates audio summaries for papers using Google Text-to-Speech (gTTS).

## Audio File Naming
Audio files follow the same naming convention as summaries:
- ArXiv papers: `YYMM.XXXXX_title_slug.mp3`
- Other papers: `title_slug.mp3`

Example:
- Summary: `summaries/ml/2602.08813_robust_policy_optimization.md`
- Audio: `audio/ml/2602.08813_robust_policy_optimization.mp3`

## Generation Pipeline

### Manual Regeneration
To regenerate all audio files from summaries:

```bash
./scripts/regenerate_audio.sh
```

This script:
1. Reads all `.md` files from `summaries/`
2. Skips papers with failed summaries (`[Summarization failed` or `[Not provided`)
3. Generates audio using gTTS
4. Saves to `audio/<category>/`
5. Tracks progress in `state/audio_generation.json`

### Automatic Pipeline
The complete pipeline: fetch → summarize → render → audio

```bash
python src/summarize.py --stdin < papers.json
python src/render.py --stdin < summaries.json
./scripts/regenerate_audio.sh
```

## Requirements

- `gtts` Python package (auto-installed)
- Internet connection (for gTTS API)
- No API keys required

## Troubleshooting

**Audio generation is slow:**
- gTTS queues requests to avoid rate limiting
- Each paper ~3-5 minutes of audio = ~10-20 seconds generation

**gTTS fails with "403 Forbidden":**
- Google may be blocking requests temporarily
- Try: change `tld="com"` to `tld="co.uk"` in `src/audio.py` line 215

**Some papers don't generate audio:**
- Check if summary contains `[Summarization failed` or `[Not provided`
- Re-run summarization for those papers

## File Structure

```
audio/
├── control/        (26 files)
├── ml/            (9 files)
├── other/         (29 files)
└── robotics/      (12 files)
```

Total: 76 audio files for 76 summaries

## Audio Playback

Play any audio file with:
```bash
xdg-open audio/robotics/2601.22356_summary.mp3
```

Or with a specific player:
```bash
mpv audio/robotics/2601.22356_summary.mp3
vlc audio/robotics/2601.22356_summary.mp3
```

## Script Length & Duration

Each summary is 400-800 words, producing 3-5 minutes of audio.

- Title + authors + venue: ~30 seconds
- Problem statement: ~30 seconds
- Methodology: ~45 seconds
- Results: ~45 seconds
- Strengths + Weaknesses: ~60 seconds
- Connections to research: ~60 seconds

Total: ~4 minutes average
