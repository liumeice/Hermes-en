# Hermes-en

Scrape the [Hermes Agent English documentation](https://hermes-agent.nousresearch.com/docs/) and produce a single merged PDF (`Output/HermesAgent-docs.pdf`) with full bookmark/TOC structure.

## Pipeline

Three sequential steps, orchestrated by `run.bat`:

| Step | Script | Description |
|------|--------|-------------|
| 1 | `step1_scrape_sidebar.py` | Uses Playwright to expand the Docusaurus sidebar, extracts the full navigation tree → `sidebar.json` + `sidebar.md` |
| 2 | `step2_generate_pdfs.py` | Visits each doc page, applies DOM manipulation (hide nav/sidebar/footer, expand tabs, fix images), exports each page as individual PDF → `temp/pdfs/*.pdf` + cover PDF |
| 3 | `step3_merge_pdfs.py` | Merges all individual PDFs with PyMuPDF, builds hierarchical TOC bookmarks from `sidebar.json` → `Output/HermesAgent-docs.pdf` |

## Usage

```bash
# Run all steps
run.bat

# Run individual steps
run.bat step1
run.bat step2
run.bat step3
```

Step 2 skips already-generated PDFs (checks file existence + non-zero size), so re-running resumes from where it left off.

## Setup

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate.bat      # Windows CMD
# or
source .venv/Scripts/activate   # Git Bash / POSIX

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
python -m playwright install chromium
```

## Dependencies

- **Python 3.12+**
- **playwright** — headless Chromium for scraping and PDF export
- **PyMuPDF** (fitz) — PDF merging and bookmark generation
- **reportlab** — cover page PDF generation

## Output

| File | Description |
|------|-------------|
| `sidebar.json` | Full navigation tree — drives steps 2 and 3 |
| `sidebar.md` | Human-readable Markdown TOC |
| `temp/pdfs/*.pdf` | Individual page PDFs (intermediate) |
| `Output/temp/Cover_Hermes_Agent.pdf` | Cover page PDF (intermediate) |
| `Output/HermesAgent-docs.pdf` | **Final merged PDF** with hierarchical bookmarks |
