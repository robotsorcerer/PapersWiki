#!/usr/bin/env bash
# run_pipeline.sh — Cron entry point for PapersWiki
#
# All times are in EDT (Eastern Daylight Time, UTC-4)
#
# Cron setup (run `crontab -e` and add):
#   0 0 * * * /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh
#
# For 6 AM EDT digest (pipeline runs at midnight EDT, digest at 6 AM EDT):
#   0  0 * * *  /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh
#   0  6 * * *  /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh --digest-only
#
# Alternatively, run everything at 5:50 AM EDT so digest arrives at 6 AM EDT:
#   50 5 * * *  /home/lex/Documents/Papers/PapersWiki/scripts/run_pipeline.sh
#
# Required env var (add to ~/.bashrc or set in crontab):
#   export SMTP_PASS='xxxx xxxx xxxx xxxx'

set -euo pipefail

WIKI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/lex/miniconda3/envs/311/bin/python"
LOG_DIR="$WIKI_DIR/logs"
DATE="$(date '+%B %d, %Y %H:%M %Z')"
LOG_FILE="$LOG_DIR/pipeline_${DATE}.log"

mkdir -p "$LOG_DIR"

# Activate conda env so gTTS, bs4, anthropic etc. are on PATH
source /home/lex/miniconda3/etc/profile.d/conda.sh
conda activate 311

# ANTHROPIC_API_KEY must be in the environment (or ~/.bashrc / crontab).
# The Anthropic Python SDK reads it automatically — no Claude CLI needed.
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "$(date -Iseconds) [ERROR] ANTHROPIC_API_KEY is not set. Aborting." >> "$LOG_FILE"
    exit 1
fi

echo "$(date -Iseconds) [INFO] PapersWiki pipeline starting (EDT)" >> "$LOG_FILE"

cd "$WIKI_DIR"

if [[ "${1:-}" == "--digest-only" ]]; then
    # Re-send digest from last run's processed papers (useful if you split cron jobs)
    echo "$(date -Iseconds) [INFO] Digest-only mode" >> "$LOG_FILE"
    "$PYTHON" pipeline.py --limit 0 2>> "$LOG_FILE"
else
    "$PYTHON" pipeline.py "$@" 2>> "$LOG_FILE"
fi

echo "$(date -Iseconds) [INFO] Pipeline done" >> "$LOG_FILE"
