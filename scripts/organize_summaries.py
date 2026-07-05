#!/usr/bin/env python3
"""
Organize and clean up legacy summaries from the summaries/ folder.

This script:
1. Moves all markdown files from summaries/ subfolders to docs/summaries/ (flat structure)
2. Cleans up the markdown format to be consistent
3. Preserves metadata (title, authors, URL, venue, category, source)
4. Removes the failed API error messages and template boilerplate
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime

SUMMARIES_DIR = Path("summaries")
DEST_DIR = Path("docs/summaries")


def extract_metadata(content: str) -> dict:
    """Extract metadata from the summary file."""
    metadata = {
        "title": "",
        "authors": "",
        "venue": "",
        "category": "",
        "source": "",
        "url": "",
        "abstract": "",
    }
    
    # Extract title (first line after #)
    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if title_match:
        metadata["title"] = title_match.group(1).strip()
    
    # Extract authors line
    authors_match = re.search(r'\*\*Authors\*\*:\s*(.+?)\s*\|', content)
    if authors_match:
        metadata["authors"] = authors_match.group(1).strip()
    
    # Extract venue
    venue_match = re.search(r'\*\*Venue\*\*:\s*(.+?)\s*\|', content)
    if venue_match:
        metadata["venue"] = venue_match.group(1).strip()
    
    # Extract category
    cat_match = re.search(r'\*\*Category\*\*:\s*(.+?)\s*\|', content)
    if cat_match:
        metadata["category"] = cat_match.group(1).strip()
    
    # Extract source
    source_match = re.search(r'\*\*Source\*\*:\s*(.+?)$', content, re.MULTILINE)
    if source_match:
        metadata["source"] = source_match.group(1).strip()
    
    # Extract URL
    url_match = re.search(r'\*\*URL\*\*:\s*<(.+?)>', content)
    if url_match:
        metadata["url"] = url_match.group(1).strip()
    
    # Extract abstract from [Not provided — see abstract: ...]
    abstract_match = re.search(r'\[Not provided — see abstract: (.+?)\]', content, re.DOTALL)
    if abstract_match:
        abstract = abstract_match.group(1).strip()
        # Clean up truncated abstracts
        if abstract.endswith('...') or abstract.endswith('…'):
            abstract = abstract.rstrip('.…') + '...'
        metadata["abstract"] = abstract
    
    return metadata


def clean_summary(content: str) -> str:
    """Clean and reformat a summary file."""
    metadata = extract_metadata(content)
    
    # Build clean summary
    lines = []
    
    # Title
    if metadata["title"]:
        lines.append(f"# {metadata['title']}")
    else:
        lines.append("# Untitled Summary")
    
    lines.append("")
    
    # Metadata block
    meta_parts = []
    if metadata["authors"]:
        meta_parts.append(f"**Authors**: {metadata['authors']}")
    if metadata["venue"]:
        meta_parts.append(f"**Venue**: {metadata['venue']}")
    if metadata["category"]:
        meta_parts.append(f"**Category**: {metadata['category']}")
    if metadata["source"]:
        meta_parts.append(f"**Source**: {metadata['source']}")
    
    if meta_parts:
        lines.append(" | ".join(meta_parts))
        lines.append("")
    
    if metadata["url"]:
        lines.append(f"**URL**: <{metadata['url']}>")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Abstract section
    if metadata["abstract"]:
        lines.append("## Abstract")
        lines.append("")
        lines.append(metadata["abstract"])
        lines.append("")
    
    # Note about API failure
    if "Summarization failed" in content:
        lines.append("## Note")
        lines.append("")
        lines.append("> This summary was generated in abstract-only mode due to API credit limitations. For a full knowledge-graph entry, see the corresponding page in `wiki/papers/`.")
        lines.append("")
    
    lines.append("---")
    lines.append(f"*Legacy summary — moved from summaries/ on {datetime.now().strftime('%Y-%m-%d')}*")
    
    return "\n".join(lines)


def sanitize_filename(name: str) -> str:
    """Create a safe filename from the original."""
    # Remove problematic characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Limit length
    if len(name) > 200:
        name = name[:200]
    return name


def main():
    """Main entry point."""
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    
    moved_count = 0
    error_count = 0
    
    # Find all markdown files in summaries/
    for md_file in SUMMARIES_DIR.rglob("*.md"):
        try:
            # Read content
            content = md_file.read_text(encoding="utf-8")
            
            # Clean the content
            cleaned = clean_summary(content)
            
            # Determine new filename (flatten structure)
            new_name = sanitize_filename(md_file.stem) + ".md"
            dest_path = DEST_DIR / new_name
            
            # Handle duplicates
            counter = 1
            while dest_path.exists():
                new_name = sanitize_filename(f"{md_file.stem}_{counter}") + ".md"
                dest_path = DEST_DIR / new_name
                counter += 1
            
            # Write cleaned content
            dest_path.write_text(cleaned, encoding="utf-8")
            
            # Remove original
            md_file.unlink()
            
            moved_count += 1
            print(f"✓ Moved: {md_file.relative_to('.')} -> {dest_path.relative_to('.')}")
            
        except Exception as e:
            error_count += 1
            print(f"✗ Error processing {md_file}: {e}")
    
    # Remove empty subdirectories
    for subdir in SUMMARIES_DIR.iterdir():
        if subdir.is_dir():
            try:
                subdir.rmdir()
                print(f"✓ Removed empty directory: {subdir}")
            except OSError:
                # Directory not empty
                pass
    
    print(f"\n--- Summary ---")
    print(f"Moved: {moved_count} files")
    print(f"Errors: {error_count} files")
    print(f"Destination: {DEST_DIR.absolute()}")


if __name__ == "__main__":
    main()
