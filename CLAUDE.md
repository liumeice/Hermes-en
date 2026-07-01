# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project Overview

**Hermes-en** — A pipeline that scrapes the [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs/) and produces a single merged PDF (`Output/HermesAgent-docs.pdf`) with full bookmark/TOC structure.

## Pipeline

Three sequential steps, orchestrated by `run.bat`:

| Step | Script | What it does |
|------|--------|-------------|
| 1 | `step1_scrape_sidebar.py` | Uses Playwright to expand the Docusaurus sidebar, extracts the full navigation tree → `sidebar.json` + `sidebar.md` |
| 2 | `step2_generate_pdfs.py` | Visits each doc page, applies DOM manipulation (hide nav/sidebar/footer, expand tabs, fix images), exports each page as individual PDF → `temp/pdfs/*.pdf` + cover PDF → `Output/temp/Cover_Hermes_Agent.pdf` |
| 2 (mt) | `step2_generate_pdfs_mt.py` | **Multi-threaded** version — Playwright async API + `asyncio.Semaphore` for concurrent page processing. Default workers = CPU count; override with `--workers N` or `run.bat step2-mt N` |
| 3 | `step3_merge_pdfs.py` | Merges all individual PDFs with PyMuPDF, builds hierarchical TOC bookmarks from `sidebar.json` → `Output/HermesAgent-docs.pdf` |

### Running the pipeline

```bash
# Run all steps
run.bat

# Run individual steps
run.bat step1
run.bat step2              # single-threaded
run.bat step2-mt           # multi-threaded (CPU threads)
run.bat step2-mt 4         # multi-threaded with 4 workers
run.bat step3
```

Step 2 (both versions) skips already-generated PDFs (checks file existence + non-zero size), so re-running resumes from where it left off.

## Dependencies

- **Python 3** in a virtual environment (`venv/`)
- **playwright** 1.60.0 — headless Chromium for scraping and PDF export
- **PyMuPDF** (fitz) 1.27.2.3 — PDF merging and bookmark generation

Activate the venv before running scripts directly:
```bash
# Windows CMD
call venv\Scripts\activate.bat

# Git Bash / POSIX
source venv/Scripts/activate
```

Install playwright browsers if not already done:
```bash
python -m playwright install chromium
```

## Key Files

| File | Purpose |
|------|---------|
| `sidebar.json` | Full navigation tree with `{title, href, level, children}` — drives steps 2 and 3 |
| `sidebar.md` | Human-readable Markdown TOC |
| `step2_generate_pdfs.py` | Step 2: single-threaded PDF generator (sync Playwright API) |
| `step2_generate_pdfs_mt.py` | Step 2: multi-threaded PDF generator (async Playwright API + semaphore) |
| `_test_js.js` | Standalone DOM manipulation script (large) — source of truth for the JS embedded in step2 |
| `_test_js_unix.js` | Unix-line-ending copy of the JS for bracket validation |
| `_check_brackets.py` | Validates bracket/paren balance in `_test_js_unix.js` |
| `_eval_test.js` | Quick eval test to check for JS syntax errors |

## Architecture Notes

- **DOM manipulation** is a large JavaScript function (`DOM_MANIPULATE_JS` in step2) that handles: hiding nav/sidebar/footer/TOC, expanding collapsed tab panels, fixing broken image paths (zh-Hans → en redirects), adjusting code block layout, setting print CSS, and eliminating blank pages. This was ported from an original `page-processor.js`. Both `step2_generate_pdfs.py` and `step2_generate_pdfs_mt.py` share identical DOM manipulation logic.
- **Single-threaded step 2** (`step2_generate_pdfs.py`) uses Playwright's sync API, processing pages one at a time.
- **Multi-threaded step 2** (`step2_generate_pdfs_mt.py`) uses Playwright's async API with `asyncio.Semaphore` for concurrency control. A single shared browser instance spawns independent context+page pairs per document, bounded by the worker count (defaults to CPU thread count).
- **Sidebar expansion** (step1) uses a two-phase approach: click-to-expand collapsed headers, then force-show all `ul.menu__list` elements via CSS overrides.
- **Cover page** is generated from inline HTML with A4-styled CSS, producing `Cover_Hermes_Agent.pdf`.
- **PDF merging** (step3) tracks page offsets per document to build accurate starting-page bookmarks. Categories point to their first child's starting page.

## Utility Scripts

- `_check_brackets.py` — checks bracket/parenthesis balance in the JS file (useful when editing the embedded DOM script)
- `_eval_test.js` — Node.js script that evals `_test_js.js` and reports the first line with a syntax error
