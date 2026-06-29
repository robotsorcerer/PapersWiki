#!/bin/bash
# paper-to-audio.sh — Convert papers from ANY source to audio
#
# Supports: arXiv URLs/IDs, PDFs, websites, emails, text
#
# Usage:
#   ./paper-to-audio.sh 2605.17232
#   ./paper-to-audio.sh https://arxiv.org/pdf/2605.17232
#   ./paper-to-audio.sh https://example.com/paper.pdf
#   ./paper-to-audio.sh /path/to/paper.pdf
#   ./paper-to-audio.sh /path/to/email.eml
#   ./paper-to-audio.sh https://example.com/research
#   ./paper-to-audio.sh --help

set -e

PYTHON_BIN="/home/lex/miniconda3/envs/311/bin/python"
WIKI_DIR="$(cd "$(dirname "$0")" && pwd)"

show_help() {
    cat << 'EOF'
paper-to-audio — Convert papers from ANY source to audio MP3

USAGE:
    paper-to-audio.sh [OPTIONS] <input>

INPUT TYPES SUPPORTED:
    arXiv ID:               2605.17232
    arXiv URL:              https://arxiv.org/pdf/2605.17232
    PDF URL:                https://example.com/paper.pdf
    PDF file:               /path/to/paper.pdf
    Website:                https://example.com/research/paper
    Email file:             /path/to/paper.eml
    Plain text:             "Title: ... Authors: ... Abstract: ..."

EXAMPLES:
    paper-to-audio.sh 2605.17232
    paper-to-audio.sh https://arxiv.org/pdf/2605.17232
    paper-to-audio.sh https://example.com/paper.pdf
    paper-to-audio.sh /path/to/paper.pdf
    paper-to-audio.sh /path/to/email.eml
    paper-to-audio.sh https://springer.com/article/...

OPTIONS:
    --skip-audio            Generate markdown but skip MP3 (faster)
    --json                  Output JSON instead of human format
    --help                  Show this message

OUTPUT:
    - Markdown file in: summaries/<category>/
    - Audio MP3 in:     audio/<category>/

EOF
    exit 0
}

# Parse arguments
skip_audio=0
json_output=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help)
            show_help
            ;;
        --skip-audio)
            skip_audio=1
            shift
            ;;
        --json)
            json_output=1
            shift
            ;;
        -*)
            echo "Error: Unknown option $1"
            show_help
            ;;
        *)
            input="$1"
            shift
            ;;
    esac
done

if [[ -z "$input" ]]; then
    echo "Error: input required"
    show_help
fi

# Build command
cmd="$PYTHON_BIN $WIKI_DIR/process_paper_universal.py"

# Quote input if it looks like text with spaces/special chars
if [[ "$input" =~ ^[a-zA-Z0-9./-]+$ ]]; then
    cmd="$cmd $input"
else
    cmd="$cmd '$input'"
fi

# Add optional flags
if [[ $skip_audio -eq 1 ]]; then
    cmd="$cmd --skip-audio"
fi

if [[ $json_output -eq 1 ]]; then
    cmd="$cmd --json"
fi

# Execute
cd "$WIKI_DIR"
eval "$cmd"
