#!/bin/bash
# audio-paper.sh — Quick audio generation for arXiv papers
#
# Usage:
#   ./audio-paper.sh 2605.17232
#   ./audio-paper.sh https://arxiv.org/pdf/2605.17232
#   ./audio-paper.sh --help

set -e

PYTHON_BIN="/home/lex/miniconda3/envs/311/bin/python"
WIKI_DIR="$(cd "$(dirname "$0")" && pwd)"

show_help() {
    cat << EOF
audio-paper — Generate MP3 audio summary from arXiv paper

USAGE:
    audio-paper.sh [OPTIONS] <arxiv-id-or-url>

EXAMPLES:
    audio-paper.sh 2605.17232
    audio-paper.sh https://arxiv.org/pdf/2605.17232
    audio-paper.sh --no-api 2605.17232    (use abstract-only mode)

OPTIONS:
    --no-api        Use abstract-only mode (no Anthropic API needed)
    --skip-audio    Generate markdown but skip MP3 (faster)
    --help          Show this message

OUTPUT:
    - Markdown file in: summaries/<category>/
    - Audio MP3 in:     audio/<category>/

EOF
    exit 0
}

# Parse arguments
no_api=0
skip_audio=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help)
            show_help
            ;;
        --no-api)
            no_api=1
            shift
            ;;
        --skip-audio)
            skip_audio=1
            shift
            ;;
        *)
            arxiv_input="$1"
            shift
            ;;
    esac
done

if [[ -z "$arxiv_input" ]]; then
    echo "Error: arXiv ID or URL required"
    show_help
fi

# Build command
cmd="$PYTHON_BIN"

if [[ $no_api -eq 1 ]]; then
    script="process_paper_no_api.py"
else
    script="process_paper.py"
fi

cmd="$cmd $WIKI_DIR/$script"

# Detect if input is URL or ID
if [[ "$arxiv_input" =~ ^https?:// ]]; then
    cmd="$cmd --url '$arxiv_input'"
else
    cmd="$cmd --arxiv-id '$arxiv_input'"
fi

# Add optional flags
if [[ $skip_audio -eq 1 ]]; then
    cmd="$cmd --skip-audio"
fi

# Execute
cd "$WIKI_DIR"
eval "$cmd"
