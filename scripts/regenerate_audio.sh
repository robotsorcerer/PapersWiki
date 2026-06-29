#!/bin/bash
# regenerate_audio.sh — Batch regenerate audio from summaries

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTHON_ENV="/home/lex/miniconda3/envs/311/bin/python"

echo "========================================================================"
echo "                    AUDIO REGENERATION SCRIPT"
echo "========================================================================"
echo ""

# Ensure gtts is installed
$PYTHON_ENV -m pip install gtts -q 2>/dev/null || true

# Run audio generation
$PYTHON_ENV << 'PYTHON_EOF'
import sys
import json
import re
from pathlib import Path

sys.path.insert(0, 'src')
from audio import synthesize

# Load state file (if exists) to track progress
state_file = Path("state/audio_generation.json")
state = {}
if state_file.exists():
    try:
        state = json.load(state_file.open())
    except:
        state = {}

# Find all summary files that should have audio
summaries_dir = Path("summaries")
summary_files = sorted(summaries_dir.rglob("*.md"))

print(f"Found {len(summary_files)} summary files")
print()

generated = 0
skipped = 0
failed = 0

for i, md_file in enumerate(summary_files, 1):
    try:
        content = md_file.read_text(encoding='utf-8')
        
        # Skip failed summaries
        if "[Summarization failed" in content or "[Not provided" in content:
            skipped += 1
            continue
        
        # Extract metadata from markdown
        lines = content.split('\n')
        title = lines[0].strip('# ').strip() if lines[0].startswith('#') else "Unknown"
        
        # Extract arxiv_id from filename
        match = re.search(r'(\d{4}\.\d{5})', md_file.name)
        arxiv_id = match.group(1) if match else ""
        
        # Get category from file path
        category = md_file.parent.name
        
        # Parse metadata
        authors = []
        venue = ""
        year = ""
        url = ""
        
        for line in lines[1:15]:
            if '**Authors**:' in line:
                m = re.search(r'\*\*Authors\*\*:\s*([^|]+)', line)
                if m:
                    authors = [a.strip() for a in m.group(1).split(',')[:1]]
            if '**Venue**:' in line:
                m = re.search(r'\*\*Venue\*\*:\s*([^|]+)', line)
                if m:
                    parts = m.group(1).strip().rsplit(', ', 1)
                    venue = parts[0]
                    year = parts[1] if len(parts) > 1 else ""
            if '**URL**:' in line:
                m = re.search(r'<([^>]+)>', line)
                if m:
                    url = m.group(1)
        
        # Construct paper dict
        paper = {
            "title": title,
            "authors": authors,
            "venue": venue,
            "year": year,
            "url": url,
            "arxiv_id": arxiv_id,
            "summary": {
                "category": category,
                "raw_markdown": content,
            }
        }
        
        # Generate audio
        try:
            audio_path = synthesize(paper)
            size_kb = audio_path.stat().st_size / 1024 if audio_path.exists() else 0
            print(f"[{i:3d}] ✓ {title[:45]:45s} {size_kb:6.1f} KB")
            generated += 1
        except Exception as e:
            print(f"[{i:3d}] ✗ {title[:45]:45s} - {str(e)[:30]}")
            failed += 1
    
    except Exception as e:
        print(f"Error: {e}")
        failed += 1

print()
print("=" * 80)
print(f"Results: {generated} generated, {skipped} skipped, {failed} failed")
print("=" * 80)

# Save state
state["last_run"] = str(Path("state/audio_generation.json").stat().st_mtime if Path("state/audio_generation.json").exists() else 0)
state["generated"] = generated
state["skipped"] = skipped  
state["failed"] = failed

Path("state").mkdir(exist_ok=True)
json.dump(state, state_file.open('w'))

sys.exit(0 if failed == 0 else 1)
PYTHON_EOF

