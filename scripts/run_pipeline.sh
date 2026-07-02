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
LOG_DIR="$WIKI_DIR/logs"
DATE="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/pipeline_${DATE}.log"

mkdir -p "$LOG_DIR"

# --- Resolve a Python interpreter robustly -------------------------------
# Prefer an explicit $PYTHON, then the project conda env, then PATH.
# (The knowledge-base compiler is stdlib-only, so any Python 3.9+ works.)
if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x "/home/lex/miniconda3/envs/311/bin/python" ]]; then
        PYTHON="/home/lex/miniconda3/envs/311/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    else
        PYTHON="$(command -v python)"
    fi
fi

# Activate conda env if available (provides gTTS, bs4, anthropic for the
# paper pipeline). Non-fatal if conda is not present.
for _conda in "$HOME/miniconda3/etc/profile.d/conda.sh" \
              "/opt/miniconda3/etc/profile.d/conda.sh" \
              "/home/lex/miniconda3/etc/profile.d/conda.sh"; do
    if [[ -f "$_conda" ]]; then
        # shellcheck disable=SC1090
        source "$_conda"
        conda activate 311 2>/dev/null || true
        break
    fi
done

log() { echo "$(date -Iseconds) $*" | tee -a "$LOG_FILE"; }

cd "$WIKI_DIR"

# -------------------------------------------------------------------------
# Step 1: Compile the knowledge base (Karpathy-style LLM Wiki).
# email_src/ (raw, source of truth) -> wiki/ (compiled, linked).
# This is OFFLINE and needs no API key, so it always runs.
# -------------------------------------------------------------------------
log "[INFO] Compiling knowledge base (email_src/ -> wiki/)"
"$PYTHON" "$WIKI_DIR/src/wiki.py" >> "$LOG_FILE" 2>&1 \
    && log "[INFO] Knowledge base compiled -> wiki/" \
    || log "[ERROR] Knowledge base compile failed (see $LOG_FILE)"

# If the caller only wants the knowledge base, stop here.
if [[ "${1:-}" == "--wiki-only" ]]; then
    log "[INFO] --wiki-only: done."
    exit 0
fi

# -------------------------------------------------------------------------
# Step 2: Paper summarization pipeline (fetch + Claude summaries + audio +
# digest email). This DOES require ANTHROPIC_API_KEY; if it is absent we
# skip gracefully — the knowledge base above has already been built.
# -------------------------------------------------------------------------
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    log "[WARN] ANTHROPIC_API_KEY not set — skipping paper summarization."
    log "[INFO] Pipeline done (knowledge base only)."
    exit 0
fi

if [[ "${1:-}" == "--digest-only" ]]; then
    log "[INFO] Digest-only mode"
    "$PYTHON" pipeline.py --limit 0 --no-wiki >> "$LOG_FILE" 2>&1
else
    "$PYTHON" pipeline.py "$@" >> "$LOG_FILE" 2>&1
fi

log "[INFO] Pipeline done"
