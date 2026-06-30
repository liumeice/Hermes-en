#!/usr/bin/env python3
"""
Step 3: Merge all individual PDFs into one final PDF with full bookmark structure.

Reads sidebar.json for the bookmark hierarchy and temp/pdfs/ directory for page PDFs.
Outputs: Output/HermesAgent-docs.pdf

Usage:
  source venv/Scripts/activate
  python step3_merge_pdfs.py
"""

import json
import os
import sys
import io
from pathlib import Path
import fitz  # PyMuPDF

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

OUTPUT_FILENAME = "Output/HermesAgent-docs.pdf"
PDFS_DIR = "temp/pdfs"
COVER_DIR = "Output/temp"
BASE_URL = "https://hermes-agent.nousresearch.com"


def flatten_pages_with_level(tree, pages=None):
    """Flatten the sidebar tree into a list of page dicts."""
    if pages is None:
        pages = []
    for node in tree:
        if "children" not in node or not node["children"]:
            pages.append(node)
        else:
            flatten_pages_with_level(node["children"], pages)
    return pages


def url_to_filename(url):
    """Convert a URL to a safe filename (same as step2)."""
    path = url.replace(BASE_URL, '').replace('https://', '').replace('http://', '')
    return path.replace('/', '_').replace('?', '_').replace('#', '_').replace(' ', '_')[:80]


def build_precise_toc(tree, page_start_map):
    """
    Build TOC where each bookmark points to the starting page of that webpage.

    page_start_map: {href -> actual PDF page number}

    Returns list of [level, title, page_number].
    For categories with children, the bookmark points to the first child's page.
    """
    raw_toc = []

    def process_nodes(nodes):
        for node in nodes:
            has_children = "children" in node and node["children"]
            href = node.get("href", "")
            level = node.get("level", 1)

            if has_children:
                # Pre-order: add category bookmark FIRST, then process children
                first_child_page = get_first_child_start_page(node["children"], page_start_map)
                if first_child_page:
                    raw_toc.append([level, node["title"], first_child_page])
                # Then process children
                process_nodes(node["children"])
            else:
                # Leaf page: point to its starting page
                if href in page_start_map:
                    raw_toc.append([level, node["title"], page_start_map[href]])

    process_nodes(tree)

    # Normalize levels: ensure no jumps > 1 (PyMuPDF requirement)
    toc = []
    prev_level = 1
    for level, title, page in raw_toc:
        if level > prev_level + 1:
            level = prev_level + 1
        elif level < 1:
            level = 1
        toc.append([level, title, page])
        prev_level = level

    return toc


def get_first_child_start_page(children, page_start_map):
    """Get the starting page number of the first leaf child."""
    for child in children:
        if "children" not in child or not child["children"]:
            href = child.get("href", "")
            if href in page_start_map:
                return page_start_map[href]
        else:
            result = get_first_child_start_page(child["children"], page_start_map)
            if result:
                return result
    return None


def main():
    print("Step 3: Merging PDFs with bookmark structure")
    print()

    # Load sidebar
    with open("sidebar.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    tree = data["children"]

    pdfs_dir = Path(PDFS_DIR)
    if not pdfs_dir.exists():
        print(f"  Error: {PDFS_DIR}/ directory not found. Run step2_generate_pdfs.py first.")
        sys.exit(1)

    # Build page map: href -> starting page number in merged PDF (1-indexed, 1 = cover)
    pages = flatten_pages_with_level(tree)
    page_start_map = {}

    # Count pages for each individual PDF to know the offset
    pdf_page_counts = {}
    for page_data in pages:
        href = page_data["href"]
        filename = url_to_filename(BASE_URL + href) + ".pdf"
        pdf_path = pdfs_dir / filename
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            try:
                doc = fitz.open(str(pdf_path))
                pdf_page_counts[href] = doc.page_count
                doc.close()
            except Exception:
                pdf_page_counts[href] = 1
        else:
            pdf_page_counts[href] = 1

    # Calculate starting page for each webpage
    current_page = 2  # Page 1 is the cover
    for page_data in pages:
        href = page_data["href"]
        page_start_map[href] = current_page
        current_page += pdf_page_counts.get(href, 1)

    total_pdf_pages = current_page - 1
    print(f"  Total content pages: {len(pages)}")
    print(f"  Total PDF pages (estimated): {total_pdf_pages}")

    # Collect all PDFs to merge (cover + pages)
    pdf_files = []

    # Cover
    cover_pdf = Path(COVER_DIR) / "Cover_Hermes_Agent.pdf"
    if cover_pdf.exists():
        pdf_files.append(str(cover_pdf))
    else:
        print(f"  Warning: cover.pdf not found, skipping")

    # Page PDFs in order
    for page_data in pages:
        href = page_data["href"]
        filename = url_to_filename(BASE_URL + href) + ".pdf"
        pdf_path = pdfs_dir / filename
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            pdf_files.append(str(pdf_path))
        else:
            print(f"  Warning: {filename} not found or empty, skipping")

    print(f"  PDFs to merge: {len(pdf_files)}")
    print()

    # Merge PDFs
    print("  Merging...")
    output_pdf = fitz.open()

    for i, pdf_path in enumerate(pdf_files):
        doc = fitz.open(pdf_path)
        output_pdf.insert_pdf(doc)
        doc.close()
        if (i + 1) % 50 == 0:
            print(f"    Merged {i + 1}/{len(pdf_files)} PDFs...")

    print(f"    Merged {len(pdf_files)} PDFs total")

    # Build and set TOC
    print("  Building bookmark structure...")
    toc = build_precise_toc(tree, page_start_map)
    print(f"  Bookmarks: {len(toc)} entries")

    # Apply TOC
    output_pdf.set_toc(toc)

    # Save
    output_path = Path(OUTPUT_FILENAME)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Saving to {output_path}...")
    output_pdf.save(str(output_path), garbage=4, deflate=True)
    output_pdf.close()

    # Final stats
    final_size = output_path.stat().st_size / (1024 * 1024)
    final_doc = fitz.open(str(output_path))
    final_pages = final_doc.page_count
    final_doc.close()

    print()
    print(f"  Done! Output: {output_path}")
    print(f"  Size: {final_size:.1f} MB")
    print(f"  Pages: {final_pages}")
    print(f"  Bookmarks: {len(toc)}")


if __name__ == "__main__":
    main()
