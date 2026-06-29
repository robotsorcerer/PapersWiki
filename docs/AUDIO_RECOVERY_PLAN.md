# Audio Recovery & Future Setup Plan

## Current Situation

**Summary Files:** 76 (all have failed summaries - API credits exhausted)
**Audio Files:** 33 (valid, generated before API failure)
**Missing Audio:** 43 files (from failed summaries)

### Failed Summary Indicators
All 76 summaries contain one of:
- `[Summarization failed: Anthropic API error 400`
- `[Not provided — see abstract:`

## Recovery Options

### Option A: Quick Fix (Requires Anthropic API Credits)
1. Set valid `ANTHROPIC_API_KEY` in environment
2. Re-run `summarize.py` on all papers
3. Re-run `render.py` to update summaries
4. Run `regenerate_audio.sh` to generate all audio

```bash
export ANTHROPIC_API_KEY="sk-..."
cd ~/Documents/Papers/PapersWiki
python src/summarize.py --stdin < state/enriched_papers.json
python src/render.py --stdin < state/summarized_papers.json
./scripts/regenerate_audio.sh
```

### Option B: Gradual Fix (Lower Cost)
Process papers in batches with prompt caching:

```bash
# Process 10 papers at a time with caching
python src/summarize.py --stdin < batch1.json  # Cache hit on system prompt
python src/summarize.py --stdin < batch2.json  # Reuses cache (~90% savings)
```

### Option C: Maintain Current State
Keep the 33 valid audio files as-is. Generate new summaries going forward:

```bash
# For NEW papers, the full pipeline works:
python src/fetch.py ...          # Get papers
python src/summarize.py --stdin  # Generate summaries (with API credits)
python src/render.py --stdin     # Render markdown
./scripts/regenerate_audio.sh    # Generate audio
```

## Future Prevention

### 1. Monitor API Credits
Before batch processing:
```bash
echo $ANTHROPIC_API_KEY | wc -c  # Should be ~100+ chars
```

### 2. Use Prompt Caching
Already implemented in `summarize.py`:
- System prompt + context cached (ephemeral)
- Reduces input token cost by ~90% on stable prefix
- Saves API budget significantly

### 3. Incremental Processing
Process papers in small batches instead of all at once:
```bash
# Process 5-10 papers per run
find papers.json -type f | head -5 | xargs -I {} python src/summarize.py --paper-json '{}'
```

### 4. Error Handling
Current setup logs failures to stderr. Capture them:
```bash
python src/summarize.py --stdin < papers.json 2> logs/summarize_errors.log
```

## Audio Generation System (Ready to Use)

### Updated Components
- ✅ `src/render.py` - Uses title-based slugs (not URLs)
- ✅ `src/audio.py` - Uses same naming convention as render.py
- ✅ `scripts/regenerate_audio.sh` - Batch regeneration script
- ✅ `AUDIO_GENERATION.md` - Complete audio guide

### Current Audio Files (Valid)
33 non-empty MP3 files in:
- `audio/control/` - 15 files
- `audio/other/` - 18 files
- `audio/robotics/` - 0 files
- `audio/ml/` - 0 files

### To Regenerate All Audio
Once summaries are fixed, run:
```bash
./scripts/regenerate_audio.sh
```

This will:
1. Read all `.md` summaries
2. Skip papers with `[Summarization failed` or `[Not provided`
3. Generate MP3 for valid summaries
4. Match filenames with summary files
5. Track progress in `state/audio_generation.json`

## Testing

### Test Audio File
```bash
xdg-open audio/other/guessing_games_nagel_1995.mp3
vlc audio/other/guessing_games_nagel_1995.mp3
```

### Verify Audio Quality
```bash
file audio/other/guessing_games_nagel_1995.mp3
du -h audio/other/guessing_games_nagel_1995.mp3
ffprobe audio/other/guessing_games_nagel_1995.mp3
```

## Next Steps

1. **Immediate:** System is ready for future use with proper API credentials
2. **Short-term:** Re-summarize papers with API credits (if available)
3. **Long-term:** Batch process new papers incrementally

---

**Status:** ✅ Audio pipeline ready | ⏳ Awaiting valid summaries
