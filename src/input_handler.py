"""
input_handler.py — Multi-source input detection and processing

Detects and handles various input types:
  - arXiv URLs/IDs
  - Direct PDF links
  - Generic website URLs
  - Email (.eml) files
  - Plain text with paper metadata

Returns a standardized candidate dict that feeds into fetch.py.

Usage:
    from input_handler import detect_and_process

    candidate = detect_and_process("https://example.com/paper.pdf")
    candidate = detect_and_process("/path/to/email.eml")
    candidate = detect_and_process("https://arxiv.org/abs/2605.17232")
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EDT = ZoneInfo("America/New_York")

log = logging.getLogger("input_handler")

# ---------------------------------------------------------------------------
# Input type detection
# ---------------------------------------------------------------------------

def _detect_input_type(input_str: str) -> str:
    """
    Detect the type of input:
    - 'arxiv_id': arXiv identifier (YYMM.NNNNN)
    - 'arxiv_url': arXiv URL
    - 'pdf_url': Direct PDF link
    - 'website_url': Generic website URL
    - 'eml_file': Email file path
    - 'pdf_file': Local PDF file
    - 'text': Plain text (potentially with metadata)
    """
    input_str = input_str.strip()

    # Check if it's a file path
    if input_str.startswith('/') or input_str.startswith('./'):
        p = Path(input_str)
        if p.exists():
            if input_str.endswith('.eml'):
                return 'eml_file'
            elif input_str.endswith('.pdf'):
                return 'pdf_file'

    # Check if it's a URL
    if input_str.startswith('http://') or input_str.startswith('https://'):
        # arXiv URLs
        if 'arxiv.org' in input_str:
            return 'arxiv_url'
        # Direct PDF links
        if input_str.endswith('.pdf') or '/pdf/' in input_str.lower():
            return 'pdf_url'
        # Generic website
        return 'website_url'

    # Check if it's an arXiv ID (format: YYMM.NNNNN[vN])
    if re.match(r'^\d{4}\.\d{4,5}(?:v\d+)?$', input_str):
        return 'arxiv_id'

    # Otherwise treat as text
    return 'text'


# ---------------------------------------------------------------------------
# arXiv handling
# ---------------------------------------------------------------------------

def _extract_arxiv_id(url_or_id: str) -> str:
    """Extract arXiv ID from URL or ID string."""
    if re.match(r'^\d{4}\.\d{4,5}(?:v\d+)?$', url_or_id.strip()):
        return url_or_id.strip()

    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url_or_id)
    if m:
        return m.group(1)

    raise ValueError(f"Could not parse arXiv ID from: {url_or_id}")


def _process_arxiv(input_str: str) -> dict:
    """Process arXiv URL or ID."""
    arxiv_id = _extract_arxiv_id(input_str)
    return {
        "id": f"arxiv:{arxiv_id}",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "title": "",
        "source": "arxiv",
        "added": datetime.now(EDT).isoformat(),
    }


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def _extract_pdf_metadata(pdf_path: str) -> dict:
    """Extract metadata from a PDF file."""
    try:
        import pdfplumber
    except ImportError:
        log.warning("pdfplumber not installed. Install with: pip install pdfplumber")
        return {"title": "", "abstract": "", "text": ""}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Get title from first page or metadata
            metadata = pdf.metadata
            title = metadata.get('Title', '') if metadata else ""

            # Extract text from first few pages for abstract
            text = ""
            for page in pdf.pages[:3]:
                text += page.extract_text() or ""

            # Try to extract abstract from text
            abstract_match = re.search(
                r'(?:ABSTRACT|Abstract)(.*?)(?:INTRODUCTION|Introduction|1\.|Keywords)',
                text,
                re.IGNORECASE | re.DOTALL
            )
            abstract = abstract_match.group(1).strip() if abstract_match else text[:500]

            return {
                "title": title or Path(pdf_path).stem,
                "abstract": abstract,
                "text": text[:2000],  # First 2000 chars
            }
    except Exception as e:
        log.error("Failed to extract PDF metadata: %s", e)
        return {"title": Path(pdf_path).stem, "abstract": "", "text": ""}


def _process_pdf_file(pdf_path: str) -> dict:
    """Process a local PDF file."""
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    metadata = _extract_pdf_metadata(pdf_path)

    return {
        "id": f"pdf:{p.stem}",
        "url": f"file://{p.absolute()}",
        "title": metadata.get("title", p.stem),
        "abstract": metadata.get("abstract", ""),
        "source": "pdf_file",
        "added": datetime.now(EDT).isoformat(),
    }


def _process_pdf_url(pdf_url: str) -> dict:
    """Process a PDF from a direct URL."""
    # Download and extract metadata
    try:
        req = Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            pdf_data = resp.read()

        # Save to temp file for processing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_data)
            tmp_path = tmp.name

        metadata = _extract_pdf_metadata(tmp_path)
        Path(tmp_path).unlink()  # Clean up temp file

        return {
            "id": f"pdf:{urlparse(pdf_url).path.split('/')[-1]}",
            "url": pdf_url,
            "title": metadata.get("title", "Paper from PDF"),
            "abstract": metadata.get("abstract", ""),
            "source": "pdf_url",
            "added": datetime.now(EDT).isoformat(),
        }
    except Exception as e:
        log.error("Failed to fetch PDF from URL: %s", e)
        # Return minimal candidate with just the URL
        return {
            "id": f"pdf:{urlparse(pdf_url).path.split('/')[-1]}",
            "url": pdf_url,
            "title": "",
            "source": "pdf_url",
            "added": datetime.now(EDT).isoformat(),
        }


# ---------------------------------------------------------------------------
# Website handling
# ---------------------------------------------------------------------------

def _extract_website_metadata(url: str) -> dict:
    """Scrape paper metadata from a website."""
    try:
        from bs4 import BeautifulSoup
        has_bs4 = True
    except ImportError:
        has_bs4 = False
        log.warning("BeautifulSoup not installed. HTML parsing will be basic.")

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.error("Failed to fetch website: %s", e)
        return {"title": "", "abstract": "", "authors": []}

    title = ""
    abstract = ""
    authors = []

    if has_bs4:
        soup = BeautifulSoup(html, 'html.parser')

        # Try Open Graph tags first
        og_title = soup.find('meta', {'property': 'og:title'})
        if og_title:
            title = og_title.get('content', '')

        og_desc = soup.find('meta', {'property': 'og:description'})
        if og_desc:
            abstract = og_desc.get('content', '')

        # Try citation metadata (for academic papers)
        for meta in soup.find_all('meta', {'name': re.compile(r'citation_author', re.I)}):
            author = meta.get('content', '').strip()
            if author:
                authors.append(author)

        # Fallback to title tag
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        # Try to find abstract in common locations
        if not abstract:
            abstract_elem = soup.find(['div', 'section'], {'class': re.compile(r'abstract', re.I)})
            if abstract_elem:
                abstract = abstract_elem.get_text(strip=True)[:500]
    else:
        # Basic regex fallback
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()

        desc_match = re.search(
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
            html,
            re.IGNORECASE
        )
        if desc_match:
            abstract = desc_match.group(1)

    return {
        "title": title,
        "abstract": abstract,
        "authors": authors,
    }


def _process_website(url: str) -> dict:
    """Process a generic website URL."""
    metadata = _extract_website_metadata(url)

    # Generate ID from URL
    parsed = urlparse(url)
    url_slug = re.sub(r'[^a-z0-9]+', '_', parsed.path.lower())[:30].strip('_')

    return {
        "id": f"web:{url_slug}",
        "url": url,
        "title": metadata.get("title", "Paper from Website"),
        "abstract": metadata.get("abstract", ""),
        "authors": metadata.get("authors", []),
        "source": "website",
        "added": datetime.now(EDT).isoformat(),
    }


# ---------------------------------------------------------------------------
# Email handling
# ---------------------------------------------------------------------------

def _process_eml_file(eml_path: str) -> dict:
    """
    Extract paper information from an email (.eml) file.

    Looks for:
    - arXiv links in the email body
    - Attached PDFs
    - Paper metadata in headers/body
    """
    import email
    from email.policy import default

    p = Path(eml_path)
    if not p.exists():
        raise FileNotFoundError(f"Email file not found: {eml_path}")

    try:
        with open(eml_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=default)

        subject = msg.get('Subject', '').strip()

        # Extract text from email
        text = ""
        attachments = []

        for part in msg.iter_parts():
            if part.get_content_type() == 'text/plain':
                text += part.get_payload(decode=True).decode('utf-8', errors='replace')
            elif part.get_content_type() == 'text/html':
                text += part.get_payload(decode=True).decode('utf-8', errors='replace')
            elif part.get_content_type() == 'application/pdf':
                filename = part.get_filename()
                if filename:
                    attachments.append(filename)

        # Look for arXiv links
        arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', text)
        if arxiv_match:
            log.info("Found arXiv link in email: %s", arxiv_match.group(1))
            return _process_arxiv(arxiv_match.group(1))

        # Look for other paper links
        url_match = re.search(r'https?://[^\s<>"\)]+\.pdf', text)
        if url_match:
            log.info("Found PDF link in email: %s", url_match.group(0))
            return _process_pdf_url(url_match.group(0))

        # If there's a PDF attachment, try to process it
        if attachments:
            log.info("Found PDF attachment(s): %s", ', '.join(attachments))
            # Return basic candidate with attachment info
            return {
                "id": f"email:{p.stem}",
                "url": f"file://{p.absolute()}",
                "title": subject or "Paper from Email",
                "abstract": text[:500],
                "attachments": attachments,
                "source": "eml_file",
                "added": datetime.now(EDT).isoformat(),
            }

        # Fallback: treat email subject/content as paper info
        return {
            "id": f"email:{p.stem}",
            "url": f"file://{p.absolute()}",
            "title": subject or "Paper from Email",
            "abstract": text[:500],
            "source": "eml_file",
            "added": datetime.now(EDT).isoformat(),
        }

    except Exception as e:
        log.error("Failed to parse email file: %s", e)
        raise


# ---------------------------------------------------------------------------
# Text/metadata handling
# ---------------------------------------------------------------------------

def _process_text(text: str) -> dict:
    """
    Parse plain text that may contain paper metadata.

    Supports formats like:
    - Title: ... Authors: ... Year: ...
    - "Title" by Author(s)
    - Simple title + abstract
    """
    lines = text.strip().split('\n')

    title = ""
    abstract = ""
    authors = []

    # Try to extract key-value pairs
    for line in lines:
        if line.startswith('Title:'):
            title = line.replace('Title:', '').strip()
        elif line.startswith('Authors:'):
            authors_str = line.replace('Authors:', '').strip()
            authors = [a.strip() for a in authors_str.split(',')]
        elif line.startswith('Abstract:'):
            abstract = line.replace('Abstract:', '').strip()

    # If no structured data, use first line as title and rest as abstract
    if not title:
        title = lines[0] if lines else "Paper"
        abstract = '\n'.join(lines[1:]) if len(lines) > 1 else ""

    # Generate slug ID
    title_slug = re.sub(r'[^a-z0-9]+', '_', title.lower())[:30].strip('_')

    return {
        "id": f"text:{title_slug}",
        "url": "",
        "title": title,
        "abstract": abstract[:500],
        "authors": authors,
        "source": "text",
        "added": datetime.now(EDT).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main detection and processing
# ---------------------------------------------------------------------------

def detect_and_process(input_str: str) -> dict:
    """
    Detect input type and process accordingly.

    Returns a standardized candidate dict ready for fetch.py.

    Args:
        input_str: Can be arXiv ID/URL, PDF link/path, website URL, email file, or text

    Returns:
        Candidate dict with keys: id, url, title, abstract, source, added
    """
    input_type = _detect_input_type(input_str)

    log.info("Detected input type: %s", input_type)

    handlers = {
        'arxiv_id': lambda s: _process_arxiv(s),
        'arxiv_url': lambda s: _process_arxiv(s),
        'pdf_url': lambda s: _process_pdf_url(s),
        'pdf_file': lambda s: _process_pdf_file(s),
        'website_url': lambda s: _process_website(s),
        'eml_file': lambda s: _process_eml_file(s),
        'text': lambda s: _process_text(s),
    }

    handler = handlers.get(input_type)
    if not handler:
        raise ValueError(f"Unknown input type: {input_type}")

    return handler(input_str)


def process_multiple(inputs: list[str]) -> list[dict]:
    """Process multiple inputs and return list of candidates."""
    candidates = []
    for inp in inputs:
        try:
            candidate = detect_and_process(inp)
            candidates.append(candidate)
        except Exception as e:
            log.error("Failed to process input '%s': %s", inp[:80], e)
    return candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Detect and process various input types")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("input", nargs='?', help="Input: arXiv ID/URL, PDF link/path, website URL, email file, or text")
    grp.add_argument("--stdin", action="store_true", help="Read inputs from stdin (one per line)")

    args = parser.parse_args()

    if args.stdin:
        inputs = [line.strip() for line in sys.stdin if line.strip()]
        candidates = process_multiple(inputs)
    else:
        candidates = [detect_and_process(args.input)]

    print(json.dumps(candidates, indent=2))
