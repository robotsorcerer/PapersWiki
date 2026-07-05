# Universal Paper-to-Audio Guide

## Overview

The system now supports **any** paper source:

| Input Type | Example | Best For |
|-----------|---------|----------|
| **arXiv ID** | `2605.17232` | Quick lookup |
| **arXiv URL** | `https://arxiv.org/pdf/2605.17232` | Sharing links |
| **PDF URL** | `https://example.com/paper.pdf` | Proceedings, preprints |
| **PDF File** | `/path/to/paper.pdf` | Local papers |
| **Website** | `https://example.com/research` | Blog posts, papers pages |
| **Email** | `/path/to/paper.eml` | Extracted from emails |
| **Plain Text** | `"Title:...\nAuthors:...\nAbstract:..."` | Manual entry |

All sources go through the same pipeline and produce audio + markdown.

---

## Quick Start — Different Input Types

### 1️⃣ arXiv ID (Fastest)
```bash
paper-to-audio.sh 2605.17232
```
Output:
- Knowledge graph entry: `wiki/papers/2605.17232.md`
- Audio: `audio/ml/dimension_free_convergence_of_discrete_diffusion_m.mp3`

### 2️⃣ arXiv URL
```bash
paper-to-audio.sh https://arxiv.org/pdf/2605.17232
paper-to-audio.sh https://arxiv.org/abs/2605.17232
```

### 3️⃣ PDF from URL
```bash
paper-to-audio.sh https://openreview.net/pdf?id=abc123
paper-to-audio.sh https://proceedings.mlr.press/v139/paper.pdf
```

### 4️⃣ Local PDF File
```bash
paper-to-audio.sh /home/lex/Downloads/paper.pdf
paper-to-audio.sh ~/Papers/my-research.pdf
```

The system extracts title, abstract from PDF metadata and content.

### 5️⃣ Website/HTML Page
```bash
paper-to-audio.sh https://distill.pub/2020/neural-network-art/
paper-to-audio.sh https://paperswithcode.com/paper/...
paper-to-audio.sh https://blog.openai.com/...
```

Extracts title from Open Graph tags, HTML metadata, or page content.

### 6️⃣ Email File (.eml)
```bash
paper-to-audio.sh /path/to/email.eml
```

The system scans the email for:
- arXiv links → processes as arXiv paper
- PDF attachments → extracts from PDF
- PDF links in body → downloads and processes
- Email subject → uses as title

### 7️⃣ Plain Text
```bash
paper-to-audio.sh "Title: My Paper
Authors: John Doe, Jane Smith
Abstract: This paper investigates..."

# Or with multiline:
paper-to-audio.sh $'Title: My Paper\nAuthors: John Doe\nAbstract: ...'
```

Supports formats:
- `Title: ... Authors: ... Abstract: ...`
- `"Title" by Author(s), Year`
- Simple text (first line = title, rest = content)

---

## Batch Processing — Multiple Papers

### From Text File
```bash
cat > papers.txt << EOF
2605.17232
2604.21100
https://arxiv.org/pdf/2603.24566
/path/to/paper.pdf
https://example.com/research
EOF

paper-to-audio.sh --stdin < papers.txt
```

### From Command Loop
```bash
for id in 2605.17232 2604.21100 2603.24566; do
  paper-to-audio.sh $id
done
```

### From Mixed Sources
```bash
echo -e "2605.17232\nhttps://example.com/paper.pdf\n/local/paper.pdf" | \
  paper-to-audio.sh --stdin
```

---

## Advanced Usage

### Test without Generating Audio
```bash
paper-to-audio.sh --skip-audio 2605.17232
# Generates markdown only, much faster (~1-2 seconds)
```

### Get JSON Output (Programmatic)
```bash
paper-to-audio.sh --json 2605.17232 | jq '.title'
# Returns full metadata as JSON
```

### Pipe to Processing
```bash
# Extract JSON and save metadata
paper-to-audio.sh --json /path/to/paper.pdf > paper_metadata.json

# Process and extract only audio path
paper-to-audio.sh 2605.17232 2>&1 | grep "Audio:"
```

### Direct Python (for scripting)
```python
import sys
sys.path.insert(0, 'src')
from input_handler import detect_and_process

# Detect and process any input
candidate = detect_and_process("https://example.com/paper.pdf")
print(candidate)
# Output: {'id': '...', 'url': '...', 'title': '...', ...}
```

---

## Input Type Detection Logic

The system automatically detects input type:

```
Input: ?
  ↓
Is it a file path?
  → .eml? → Process email
  → .pdf? → Extract from PDF
  ↓
Is it a URL?
  → arxiv.org? → Query arXiv API
  → .pdf? → Download and extract
  → else → Scrape website
  ↓
Is it an arXiv ID (YYMM.NNNNN)?
  → Query arXiv API
  ↓
Otherwise:
  → Treat as plain text
  → Parse for Title/Authors/Abstract
```

---

## Handling Different Paper Sources

### 📚 Conference Proceedings
```bash
# OpenReview papers
paper-to-audio.sh https://openreview.net/pdf?id=your_paper_id

# ICML/NeurIPS/ICLR
paper-to-audio.sh https://proceedings.mlr.press/v139/your_paper.pdf

# ACM/IEEE (if publicly accessible)
paper-to-audio.sh https://dl.acm.org/doi/pdf/...
```

### 📄 Preprints
```bash
# OSF Preprints
paper-to-audio.sh https://osf.io/preprints/psyarxiv/abc123/

# bioRxiv/medRxiv
paper-to-audio.sh https://www.biorxiv.org/content/10.1101/2021.01.01.425076v1.full.pdf
```

### 🔗 Author Websites
```bash
# Personal website
paper-to-audio.sh https://example.com/publications/my-paper

# Research lab
paper-to-audio.sh https://lab.mit.edu/papers/2024-neural-networks
```

### 📧 From Email
Your advisor sends: "Check out this paper on diffusion models: [arXiv link]"

```bash
# Save the email as .eml
paper-to-audio.sh ~/Downloads/advisor_email.eml
# System extracts arXiv link and processes automatically
```

### 💾 Downloaded Papers
```bash
# PDFs already on your computer
paper-to-audio.sh ~/Downloads/interesting_paper.pdf

# Batch process a folder
for pdf in ~/Papers/*.pdf; do
  paper-to-audio.sh "$pdf"
done
```

---

## Output Organization

Papers are automatically categorized:

```
audio/
├── control/          ← Barrier functions, optimal control, LQR, CBF
├── robotics/         ← Manipulation, navigation, grasping
├── ml/               ← Deep learning, diffusion, LLMs, transformers
└── other/            ← Miscellaneous

wiki/papers/          ← Knowledge graph entries (authoritative source)
```

**Note**: Per-paper summaries are no longer generated. The knowledge graph in `wiki/papers/` serves as the authoritative source.

---

## Limitations & Workarounds

### ❌ Paywalled Papers
- **Problem**: Can't download papers behind paywalls
- **Workaround**: Download PDF manually, then `paper-to-audio.sh /path/to/paper.pdf`

### ❌ JavaScript-Heavy Websites
- **Problem**: Website scraper can't access dynamically loaded content
- **Workaround**: Save page as HTML, extract title/abstract manually, use text mode

### ❌ Non-English Papers
- **Problem**: Text-to-speech is English-optimized
- **Workaround**: Use `--skip-audio` to generate markdown, translate to English first

### ❌ Papers Without Abstracts
- **Problem**: PDF extraction finds no abstract
- **Workaround**: Provide as text: `paper-to-audio.sh "Title: ...\nAbstract: First few paragraphs..."`

---

## Metadata Extraction Details

### From arXiv
- **Source**: arXiv API
- **Extracts**: Title, authors, abstract, year, category, PDF URL
- **Speed**: ~1-2 seconds
- **Quality**: Excellent (structured data)

### From PDF
- **Source**: PDF metadata + text extraction
- **Extracts**: Title (from metadata or first page), abstract (from first few pages), authors (from header)
- **Speed**: ~5-10 seconds (depends on file size)
- **Quality**: Good (metadata often reliable; text extraction varies)
- **Requires**: `pdfplumber` library

### From Website
- **Source**: Open Graph tags, HTML metadata, page content
- **Extracts**: Title, description/abstract, author tags (if available)
- **Speed**: ~1-2 seconds
- **Quality**: Variable (depends on website structure)

### From Email
- **Source**: Email headers, body, attachments
- **Extracts**: Subject (title), body (abstract), attached PDFs
- **Speed**: Instant
- **Quality**: Good (manual email content)

### From Text
- **Source**: Plain text (user provides)
- **Extracts**: Parsed from key-value format
- **Speed**: Instant
- **Quality**: Perfect (user-provided)

---

## Troubleshooting

### "Module not found: pdfplumber"
PDF extraction is optional. Install if you'll process PDFs frequently:
```bash
/home/lex/miniconda3/envs/311/bin/pip install pdfplumber
```

### "HTTP 429: Too many requests"
You're hitting arXiv/website rate limits. Wait a few minutes before retrying.

### "BeautifulSoup not installed"
Website scraping will use basic regex fallback (lower quality). Install for better results:
```bash
/home/lex/miniconda3/envs/311/bin/pip install beautifulsoup4
```

### "PDF title/abstract not extracted"
Some PDFs have poor metadata. Try:
1. Rename the file: `paper-to-audio.sh renamed_paper.pdf`
2. Use text mode: `paper-to-audio.sh "Title: Your Title\nAbstract: ..."`
3. Check the generated markdown and edit manually

### "Website title is wrong"
Website scraping extracts from Open Graph/HTML metadata. If it fails:
1. Check generated markdown
2. Edit markdown file manually
3. No need to re-process

### "Email processing doesn't find the paper"
The system looks for arXiv links or PDF attachments. If neither exist:
1. Extract the email content manually
2. Use text mode: `paper-to-audio.sh "Title: ...\nAbstract: ..."`

---

## Performance

| Input Type | Metadata Time | Audio Time | Total |
|-----------|---------------|-----------|-------|
| arXiv ID | 1-2s | 15-20s | ~20-25s |
| PDF URL | 3-5s | 15-20s | ~20-25s |
| PDF File | 5-10s | 15-20s | ~25-30s |
| Website | 1-2s | 15-20s | ~20-25s |
| Email | <1s | 15-20s | ~15-20s |
| Text | <1s | 15-20s | ~15-20s |

**Fast mode** (markdown only, no audio):
```bash
paper-to-audio.sh --skip-audio <input>  # ~1-2 seconds
```

---

## Integration With Your Workflow

### Add to your shell rc (.bashrc / .zshrc)
```bash
# Quick function for papers
alias audio-paper='cd ~/Documents/Papers/PapersWiki && ./paper-to-audio.sh'

# Usage:
audio-paper 2605.17232
audio-paper /path/to/paper.pdf
```

### Create a paper download hook
```bash
#!/bin/bash
# Save as ~/bin/auto-audio-paper.sh

# When you download a PDF, automatically generate audio
if [[ $1 == *.pdf ]]; then
  ~/Documents/Papers/PapersWiki/paper-to-audio.sh "$1" &
fi
```

### Schedule batch processing
```bash
# Run every morning at 9 AM
0 9 * * * cd ~/Documents/Papers/PapersWiki && paper-to-audio.sh --stdin < ~/inbox.txt
```

---

## Examples — Different Scenarios

### Scenario 1: Found an arXiv paper
```bash
# Copy arXiv ID from URL bar
paper-to-audio.sh 2605.17232

# Get audio for your commute
# Listen to: audio/ml/dimension_free_convergence_of_discrete_diffusion_m.mp3
```

### Scenario 2: Advisor sends a paper via email
```bash
# Email is in Downloads
paper-to-audio.sh ~/Downloads/advisor-email.eml

# System extracts paper link and generates audio automatically
```

### Scenario 3: Downloaded a conference paper
```bash
# ICLR paper as PDF
paper-to-audio.sh ~/Downloads/iclr2024_paper.pdf

# Get audio with extracted title/authors
```

### Scenario 4: Want to remember a blog post
```bash
# Save blog post about research
paper-to-audio.sh https://distill.pub/2021/deep-learning-trends/

# Turn it into audio format for later listening
```

### Scenario 5: Have a list of papers to process
```bash
# Create list of your reading queue
cat > reading_queue.txt << EOF
https://arxiv.org/pdf/2605.17232
https://arxiv.org/pdf/2604.21100
/path/to/downloaded_paper.pdf
https://example.com/research-blog
EOF

# Process all in background
paper-to-audio.sh --stdin < reading_queue.txt &
```

---

## What's Different from Before

**Before**: Only arXiv papers via URL/ID
**Now**: arXiv + PDFs + Websites + Emails + Text

**Before**: Single script for one input type
**Now**: Universal script handles all types automatically

**Before**: Manual metadata entry for non-arXiv
**Now**: Automatic extraction from any source

**Before**: Per-paper summaries in `summaries/` folder (now removed)
**Now**: Knowledge graph in `wiki/papers/` compiled from email alerts

---

## Future Enhancements

Possible additions (not yet implemented):

1. **GitHub URLs**: Extract README, research notes, code papers
2. **DOI links**: Resolve and fetch using Unpaywall
3. **Semantic Scholar**: Query and fetch papers by keyword
4. **Google Scholar**: Search and process papers
5. **YouTube**: Transcribe video lectures to audio + text
6. **Twitter threads**: Convert research threads to papers
7. **Slack messages**: Extract paper links from conversations
8. **Database support**: Track processed papers, avoid duplicates

---

## Getting Help

### Debug mode
```bash
# See detailed logs
LOGLEVEL=DEBUG paper-to-audio.sh 2605.17232
```

### Check what was detected
```bash
# Get JSON of extracted metadata
paper-to-audio.sh --json 2605.17232 | python -m json.tool
```

### Manual processing
```python
import sys
sys.path.insert(0, 'src')
from input_handler import detect_and_process

result = detect_and_process("https://example.com/paper.pdf")
print(f"Title: {result['title']}")
print(f"Abstract: {result['abstract'][:200]}")
```

Happy converting! 🎧📖
