#!/usr/bin/env python3
"""
Step 2 (Async multi-page): Generate individual PDFs for each documentation page + a cover PDF.

Reads sidebar.json, visits each page with Playwright, applies DOM manipulation
(from the Node.js page-processor.js), and exports to PDF.

Uses Playwright's async API with asyncio.Semaphore to process pages concurrently.

Default concurrency = CPU thread count. Override with --workers N.

Usage:
  source venv/Scripts/activate
  python step2_generate_pdfs_mt.py              # uses all CPU threads
  python step2_generate_pdfs_mt.py --workers 4  # limit to 4
"""

import json
import os
import sys
import io
import time
import asyncio
import argparse
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = 'https://hermes-agent.nousresearch.com'
ORIGIN = 'https://hermes-agent.nousresearch.com'

# ============================================================
# DOM manipulation script (identical to step2_generate_pdfs.py)
# ============================================================
DOM_MANIPULATE_JS = r"""
() => {
  // 1. Navbar: hide completely
  document.querySelectorAll(
    'nav.navbar--fixed-top, nav.navbar--sticky' +
    ', .theme-layout-navbar.navbar--fixed-top' +
    ', .theme-layout-navbar' +
    ', nav.navbar'
  ).forEach(function(el) {
    el.style.setProperty('display', 'none', 'important');
  });
  document.querySelectorAll('.skipToContent_fXgn, [class*="skipToContent"]').forEach(function(el) {
    el.style.setProperty('display', 'none', 'important');
  });
  document.querySelectorAll('img').forEach(function(el) {
    var src = el.getAttribute('src') || '';
    if (src.indexOf('logo') >= 0 || src.indexOf('Logo') >= 0) {
      el.style.setProperty('display', 'none', 'important');
    }
  });

  // 2. Hide sidebar + TOC
  var sidebarSelectors = [
    'aside.theme-doc-sidebar-container',
    'aside[class*="docSidebarContainer"]',
    'aside[role="navigation"]',
    '#navbar-sidebar__backdrop',
    '.sidebarViewport_aRGl',
    '.docSidebarContainer_YfHR',
    'nav#menu.thin-scrollbar',
    'UL.theme-doc-sidebar-menu',
    'UL.menu__list',
    'LI.menu__list-item',
    'A.menu__link',
    '.navbar-sidebar',
    '.navbar-sidebar__backdrop',
    '.navbar-sidebar__brand',
    '.navbar-sidebar__panel',
    '.tableOfContents_bqdL',
    '[class*="tableOfContents"]',
    '.theme-doc-toc-desktop',
    '.theme-doc-toc-mobile',
    '.tocCollapsible',
    '.tocMobile',
    '.tocContainer',
    'div.col--3',
    '[aria-label="On this page"]',
    '[aria-label="Table of Contents"]',
    'aside[aria-label="On this page"]',
    '.theme-doc-sidebar-item-category',
    '.theme-doc-sidebar-item-link',
    '.navbarSearchContainer',
    '.searchBarContainer',
    '.navbar__search'
  ].join(', ');
  document.querySelectorAll(sidebarSelectors).forEach(function(el) {
    el.style.setProperty('display', 'none', 'important');
    el.style.setProperty('visibility', 'hidden', 'important');
    el.style.setProperty('height', '0', 'important');
    el.style.setProperty('width', '0', 'important');
    el.style.setProperty('overflow', 'hidden', 'important');
  });

  // 3. Hide "Copy page" button
  document.querySelectorAll('*').forEach(function(el) {
    var text = el.textContent || '';
    if ((text === 'Copy page' || text === 'Copy' || text === 'Copy Page')
        && el.offsetHeight > 0 && el.offsetHeight < 40) {
      el.style.setProperty('display', 'none', 'important');
    }
  });

  // 4. Hide footer / feedback
  document.querySelectorAll(
    'footer.theme-doc-footer, footer.theme-layout-footer, ' +
    'footer[class*="edit-meta-row"]'
  ).forEach(function(el) {
    el.style.setProperty('display', 'none', 'important');
  });
  document.querySelectorAll('*').forEach(function(el) {
    var text = el.textContent || '';
    if (text.includes('Was this page helpful')
        && el.offsetHeight < 200 && el.offsetWidth > 200) {
      el.style.setProperty('display', 'none', 'important');
    }
  });

  // 5. Adjust content spacing
  var main = document.querySelector('main') || document.querySelector('[role="main"]');
  if (main) {
    main.style.setProperty('padding-top', '0', 'important');
    main.style.setProperty('margin-top', '0', 'important');
  }
  document.querySelectorAll('.breadcrumbs, .theme-doc-breadcrumbs, nav[aria-label="Breadcrumbs"]').forEach(function(el) {
    el.style.setProperty('margin', '0 0 10mm 0', 'important');
    el.style.setProperty('padding', '0', 'important');
  });
  document.querySelectorAll('*').forEach(function(el) {
    var text = el.textContent || '';
    if ((text.trim() === 'On this page' || text.trim() === 'Table of contents' || text.trim() === 'Contents')
        && el.offsetHeight > 0 && el.offsetHeight < 80) {
      el.style.setProperty('display', 'none', 'important');
    }
  });

  // H1 spacing
  document.querySelectorAll('h1').forEach(function(el) {
    el.style.setProperty('margin-bottom', '3mm', 'important');
    el.style.setProperty('margin-top', '0', 'important');
    el.style.setProperty('padding-top', '0', 'important');
  });

  // Frontmatter cleanup — fix MDX frontmatter rendered as visible content
  (function() {
    var mdDiv = document.querySelector('.theme-doc-markdown');
    if (!mdDiv) return;
    var slug = (location.pathname.replace(/\/\/+$/, '').split('/').pop() || '').toLowerCase();
    function isFrontmatter(t) {
      if (!t) return false;
      return t.indexOf('sidebar_label') >= 0 ||
             t.indexOf('sidebar_position') >= 0 ||
             t.indexOf('description:') >= 0 ||
             /^P?---/.test(t) ||
             (t.indexOf('---') >= 0 && t.indexOf('title:') >= 0);
    }
    function hideTocEntry(id) {
      if (!id) return;
      document.querySelectorAll('a[href*="' + id + '"]').forEach(function(tocLink) {
        tocLink.style.setProperty('display', 'none', 'important');
        var tocLi = tocLink.closest('li');
        if (tocLi) tocLi.style.setProperty('display', 'none', 'important');
      });
    }
    var hasFrontmatterBug = false;
    var slugH1Candidates = [];
    var node = mdDiv.firstChild;
    while (node) {
      var nextSibling = node.nextSibling;
      if (node.nodeType === 3) {
        var t = node.textContent || '';
        if (t.trim().length > 0 && isFrontmatter(t)) {
          hasFrontmatterBug = true;
          var span = document.createElement('span');
          span.style.setProperty('display', 'none', 'important');
          span.textContent = t;
          if (node.parentNode) node.parentNode.replaceChild(span, node);
        }
      } else if (node.nodeType === 1) {
        var tag = node.tagName;
        if (tag === 'H1' || tag === 'HEADER') {
          var h1InNode = tag === 'H1' ? node : node.querySelector('h1');
          if (h1InNode) {
            var hText = (h1InNode.textContent || '').trim().toLowerCase();
            if (slug && hText === slug && /^[a-z0-9][a-z0-9-]*$/.test(hText)) {
              slugH1Candidates.push(tag === 'HEADER' ? node : h1InNode);
            }
          }
        } else if (tag === 'H2' || tag === 'H3' || tag === 'H4') {
          var headingText = (node.textContent || '').trim();
          if (isFrontmatter(headingText)) {
            hasFrontmatterBug = true;
            node.style.setProperty('display', 'none', 'important');
            node.style.setProperty('height', '0', 'important');
            hideTocEntry(node.id);
          }
        }
      }
      node = nextSibling;
    }
    if (hasFrontmatterBug) {
      slugH1Candidates.forEach(function(target) {
        target.style.setProperty('display', 'none', 'important');
        target.style.setProperty('height', '0', 'important');
      });
    }
  })();

  // 6. Expand tabs
  var tabLists = document.querySelectorAll(
    '[role="tablist"], .tabs, [class*="tabs__"], [data-component-part="tabs-list"]'
  );
  for (var t = 0; t < tabLists.length; t++) {
    var tabList = tabLists[t];
    var container = tabList.closest('.tabs-container')
      || tabList.closest('[class*="tabContainer"]')
      || tabList.closest('.margin-vert--md')
      || tabList.parentElement;
    var tabPanels = container
      ? container.querySelectorAll('[role="tabpanel"], [class*="tabitem"], .margin-top--md')
      : document.querySelectorAll('[role="tabpanel"], [class*="tabitem"]');
    var tabs = tabList.querySelectorAll('[role="tab"], .tabs__item, [class*="tabs__"]');
    var tabNames = [];
    for (var ti = 0; ti < tabs.length; ti++) tabNames.push(tabs[ti].textContent.trim());
    var tabHtmls = [];
    for (var pi = 0; pi < tabPanels.length; pi++) tabHtmls.push(tabPanels[pi].innerHTML);
    tabList.style.setProperty('display', 'none', 'important');
    for (var pi = 0; pi < tabPanels.length; pi++) tabPanels[pi].style.setProperty('display', 'none', 'important');
    for (var ti = 0; ti < tabHtmls.length; ti++) {
      var section = document.createElement('div');
      section.setAttribute('data-tab-expanded', tabNames[ti]);
      section.style.cssText = 'margin-top: 20px; margin-bottom: 25px; padding: 15px 0; display: block !important;';
      var heading = document.createElement('div');
      heading.style.cssText = 'font-size: 14px; font-weight: 600; color: #333; margin-bottom: 12px; padding: 6px 0 8px 0; border-bottom: 2px solid #e5e7eb;';
      heading.textContent = tabNames[ti];
      section.appendChild(heading);
      var cc = document.createElement('div');
      cc.style.cssText = 'display: block !important; opacity: 1 !important;';
      cc.innerHTML = tabHtmls[ti];
      var allEls = cc.querySelectorAll('*');
      for (var ci = 0; ci < allEls.length; ci++) {
        if (allEls[ci].classList) {
          allEls[ci].classList.remove('hidden');
          allEls[ci].classList.remove('sr-only');
          allEls[ci].classList.remove('opacity-0');
        }
      }
      section.appendChild(cc);
      tabList.parentNode.insertBefore(section, tabList);
    }
  }

  // 7. Large SVGs / small icons
  document.querySelectorAll('svg').forEach(function(svg) {
    var w = parseInt(svg.getAttribute('width')) || 0;
    var h = parseInt(svg.getAttribute('height')) || 0;
    var vb = svg.viewBox && svg.viewBox.baseVal;
    var vbw = vb ? vb.width : 0;
    if ((w > 100 || h > 100 || vbw > 200) && !(w <= 80 && h <= 80)) {
      svg.removeAttribute('width');
      svg.removeAttribute('height');
      svg.style.setProperty('width', '100%', 'important');
      svg.style.setProperty('height', 'auto', 'important');
      svg.style.setProperty('display', 'block', 'important');
    }
  });
  document.querySelectorAll('svg').forEach(function(el) {
    var w = parseInt(el.getAttribute('width')) || 0;
    var h = parseInt(el.getAttribute('height')) || 0;
    if (w > 0 && w <= 80 && h <= 80) {
      el.style.setProperty('max-width', '48px', 'important');
    }
  });

  // 8. Fix image paths (fallback to CDN for missing images)
  function fixImagePath(src) {
    if (!src) return null;
    if (src.indexOf('/zh-Hans/docs/img/') >= 0) return src.replace('/zh-Hans/docs/img/', '/docs/img/');
    if (src.indexOf('/zh-Hans/docs/') >= 0) return src.replace('/zh-Hans/docs/', '/docs/');
    if (src.indexOf('/zh-Hans/') >= 0) return src.replace('/zh-Hans/', '/');
    if (src.indexOf('/img/') === 0) return '/docs' + src;
    return null;
  }

  document.querySelectorAll('img').forEach(function(el) {
    var src = el.getAttribute('src') || '';
    var fixed = fixImagePath(src);
    if (fixed) el.setAttribute('src', fixed);
    el.style.setProperty('max-width', '100%', 'important');
    el.style.setProperty('height', 'auto', 'important');
    if (el.src) {
      el.onerror = function() {
        if (el._retried) return;
        el._retried = true;
        var en = fixImagePath(el.getAttribute('src'));
        if (en) el.src = en;
      };
    }
  });

  // 9. Code blocks
  document.querySelectorAll('pre, code[class*="language-"]').forEach(function(pre) {
    pre.style.setProperty('overflow', 'visible', 'important');
    pre.style.setProperty('width', '100%', 'important');
    pre.style.setProperty('max-width', '100%', 'important');
  });
  document.querySelectorAll('pre code').forEach(function(code) {
    code.style.setProperty('width', '100%', 'important');
    code.style.setProperty('max-width', '100%', 'important');
  });

  // 10. Global CSS
  var bgStyle = document.createElement('style');
  bgStyle.textContent = [
    'html, body { background-color: #FFFFFF !important; }',
    'h1, h2, h3, h4, h5, h6 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important; }',
    '@page { margin: 5mm 0 5mm 0; background-color: #FFFFFF; }',
    'pre, code { white-space: pre-wrap !important; word-break: break-all !important; overflow-wrap: anywhere !important; max-width: 100% !important; }',
    'pre { overflow: visible !important; width: 100% !important; max-width: 100% !important; }',
    'pre code, pre code span, pre .token-line, pre .token-line span { max-width: 100% !important; }',
    'table { display: table !important; width: 100% !important; table-layout: auto !important; }',
    'thead { display: table-header-group !important; }',
    'tbody { display: table-row-group !important; }',
    'tfoot { display: table-footer-group !important; }',
    'tr { display: table-row !important; }',
    'th, td { display: table-cell !important; }',
    '* { orphans: 1 !important; widows: 1 !important; }',
    'h1,h2,h3,h4,h5,h6 { break-after: avoid !important; page-break-after: avoid !important; }',
  ].join('');
  document.head.appendChild(bgStyle);

  // 11. Eliminate blank pages
  document.body.style.setProperty('height', 'auto', 'important');
  document.body.style.setProperty('min-height', 'auto', 'important');
  document.documentElement.style.setProperty('height', 'auto', 'important');
  document.documentElement.style.setProperty('min-height', 'auto', 'important');

  // 11b. Reset Docusaurus wrapper min-height
  document.querySelectorAll(
    '.main-wrapper, [class*="mainWrapper"], ' +
    '[class*="docMainContainer"], [class*="docMainWrapper"], ' +
    '.container, [class*="container"], ' +
    '[class*="layoutWrapper"], [class*="layout--writer"]'
  ).forEach(function(el) {
    el.style.setProperty('min-height', 'auto', 'important');
    el.style.setProperty('height', 'auto', 'important');
  });

  // 12. Pagination nav
  document.querySelectorAll('.pagination-nav, [class*="paginationNav"], [class*="spacer"], [class*="bottom-cta"]').forEach(function(el) {
    el.style.setProperty('display', 'none', 'important');
    el.style.setProperty('height', '0', 'important');
    el.style.setProperty('min-height', '0', 'important');
    el.style.setProperty('margin', '0', 'important');
    el.style.setProperty('padding', '0', 'important');
  });

  // 13. "Edit this page"
  document.querySelectorAll('*').forEach(function(el) {
    var text = el.textContent || '';
    if ((text.trim() === 'Edit this page' || text.trim() === 'Edit')
        && el.offsetHeight > 0 && el.offsetHeight < 50) {
      el.style.setProperty('display', 'none', 'important');
    }
  });
}
"""


# ============================================================
# Cover page HTML
# ============================================================
def generate_cover_html(total_pages):
    now = datetime.now()
    edition = f'{now.year}·{now.month:02d}'
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: 210mm; height: 297mm; overflow: hidden; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #fff; }}
  .page {{ width: 210mm; height: 297mm; position: relative; overflow: hidden; background: linear-gradient(160deg, #1a1a2e 0%, #16213e 40%, #0f3460 100%); }}
  .geo-lines {{ position: absolute; inset: 0; opacity: 0.06; }}
  .geo-lines svg {{ width: 100%; height: 100%; }}
  .center-wrap {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
  .content {{ display: flex; flex-direction: column; align-items: center; text-align: center; }}
  .top-rule {{ width: 32px; height: 1px; background: rgba(255,255,255,0.35); margin-bottom: 40px; }}
  .brand-label {{ font-size: 11px; font-weight: 400; letter-spacing: 6px; text-transform: uppercase; color: rgba(255,255,255,0.5); margin-bottom: 36px; }}
  .title {{ font-size: 56px; font-weight: 300; line-height: 1.1; margin-bottom: 8px; letter-spacing: 2px; }}
  .title em {{ font-style: normal; font-weight: 700; }}
  .title-sub {{ font-size: 24px; font-weight: 300; color: rgba(255,255,255,0.8); margin-bottom: 44px; letter-spacing: 6px; }}
  .divider-wrap {{ display: flex; align-items: center; gap: 12px; margin-bottom: 44px; }}
  .divider-line {{ width: 28px; height: 0.5px; background: rgba(255,255,255,0.3); }}
  .divider-diamond {{ width: 5px; height: 5px; background: rgba(255,255,255,0.4); transform: rotate(45deg); }}
  .edition {{ display: flex; align-items: center; gap: 14px; margin-bottom: 52px; }}
  .edition-line {{ width: 24px; height: 0.5px; background: rgba(255,255,255,0.25); }}
  .edition-text {{ font-size: 15px; font-weight: 400; color: rgba(255,255,255,0.75); letter-spacing: 2px; }}
  .features {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 8px 18px; max-width: 460px; margin-bottom: 56px; }}
  .feature-tag {{ font-size: 11px; font-weight: 400; color: rgba(255,255,255,0.55); padding: 4px 12px; border: 0.5px solid rgba(255,255,255,0.2); letter-spacing: 0.5px; }}
  .bottom-rule {{ position: absolute; bottom: 60px; left: 0; right: 0; display: flex; justify-content: center; }}
  .bottom-rule-line {{ width: 32px; height: 1px; background: rgba(255,255,255,0.2); }}
  .bottom-info {{ position: absolute; bottom: 28px; left: 0; right: 0; text-align: center; }}
  .bottom-url {{ font-size: 11px; color: rgba(255,255,255,0.35); letter-spacing: 1.5px; margin-bottom: 5px; }}
  .bottom-copy {{ font-size: 9px; color: rgba(255,255,255,0.2); letter-spacing: 0.5px; }}
  .corner {{ position: absolute; width: 24px; height: 24px; opacity: 0.12; }}
  .corner svg {{ width: 100%; height: 100%; }}
  .corner-tl {{ top: 28px; left: 28px; }}
  .corner-tr {{ top: 28px; right: 28px; transform: scaleX(-1); }}
  .corner-bl {{ bottom: 28px; left: 28px; transform: scaleY(-1); }}
  .corner-br {{ bottom: 28px; right: 28px; transform: scale(-1,-1); }}
</style></head>
<body>
<div class="page">
  <div class="geo-lines"><svg viewBox="0 0 794 1123" fill="none"><line x1="0" y1="374" x2="794" y2="374" stroke="#fff" stroke-width="0.5"/><line x1="0" y1="748" x2="794" y2="748" stroke="#fff" stroke-width="0.5"/><line x1="264" y1="0" x2="264" y2="1123" stroke="#fff" stroke-width="0.5"/><line x1="530" y1="0" x2="530" y2="1123" stroke="#fff" stroke-width="0.5"/><circle cx="397" cy="561" r="180" stroke="#fff" stroke-width="0.5"/><circle cx="397" cy="561" r="280" stroke="#fff" stroke-width="0.3"/></svg></div>
  <div class="corner corner-tl"><svg viewBox="0 0 24 24"><path d="M0 24V0h24" stroke="#fff" stroke-width="1" fill="none"/></svg></div>
  <div class="corner corner-tr"><svg viewBox="0 0 24 24"><path d="M0 24V0h24" stroke="#fff" stroke-width="1" fill="none"/></svg></div>
  <div class="corner corner-bl"><svg viewBox="0 0 24 24"><path d="M0 24V0h24" stroke="#fff" stroke-width="1" fill="none"/></svg></div>
  <div class="corner corner-br"><svg viewBox="0 0 24 24"><path d="M0 24V0h24" stroke="#fff" stroke-width="1" fill="none"/></svg></div>
  <div class="center-wrap"><div class="content">
    <div class="top-rule"></div>
    <div class="brand-label">Nous Research</div>
    <div class="title"><em>Hermes</em> Agent</div>
    <div class="title-sub">Official Documentation</div>
    <div class="divider-wrap"><span class="divider-line"></span><span class="divider-diamond"></span><span class="divider-line"></span></div>
    <div class="edition"><span class="edition-line"></span><span class="edition-text">{edition}</span><span class="edition-line"></span></div>
    <div class="features"><span class="feature-tag">Quick Start</span><span class="feature-tag">Core Concepts</span><span class="feature-tag">Tool Use</span><span class="feature-tag">Multi-Step Reasoning</span><span class="feature-tag">MCP Protocol</span><span class="feature-tag">API Reference</span></div>
  </div></div>
  <div class="bottom-rule"><span class="bottom-rule-line"></span></div>
  <div class="bottom-info"><div class="bottom-url">hermes-agent.nousresearch.com</div><div class="bottom-copy">Generated by liumc</div></div>
</div>
</body></html>"""


def flatten_pages(tree, pages=None):
    """Flatten the sidebar tree into a list of leaf page dicts."""
    if pages is None:
        pages = []
    for node in tree:
        if 'children' not in node or not node['children']:
            pages.append(node)
        else:
            flatten_pages(node['children'], pages)
    return pages


def url_to_filename(url):
    """Convert a URL to a safe filename."""
    path = url.replace(ORIGIN, '').replace('https://', '').replace('http://', '')
    return path.replace('/', '_').replace('?', '_').replace('#', '_').replace(' ', '_')[:150]


# ============================================================
# Progress display (single-threaded asyncio, no lock needed)
# ============================================================
class ProgressDisplay:
    """Async-friendly progress tracker."""

    def __init__(self, total):
        self._done = 0
        self._total = total
        self._lock = asyncio.Lock()

    async def record_and_print(self, idx, title, status_icon, detail=''):
        async with self._lock:
            self._done += 1
            pct = self._done / self._total * 100
            bar_len = 30
            filled = int(bar_len * self._done / self._total)
            bar = '█' * filled + '░' * (bar_len - filled)
            title_short = title[:50]
            line = f'  [{bar}] {pct:5.1f}%  {self._done:3d}/{self._total} | {status_icon} {title_short:<50s} {detail}'
            print(line)
            return self._done

    def set_done(self, n):
        """Set initial done count (for pre-skipped pages)."""
        self._done = n


async def generate_cover_pdf_async(output_path, total_pages):
    """Generate cover page PDF using Playwright async API."""
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 794, 'height': 1123})
        page = await context.new_page()
        await page.set_content(generate_cover_html(total_pages), wait_until='domcontentloaded', timeout=10000)
        await page.wait_for_timeout(500)
        await page.pdf(
            path=output_path,
            format='A4',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
        )
        await browser.close()
        print(f'  Generated: {output_path}')
    finally:
        await pw.stop()


async def process_page_async(page_data, idx, total, pdfs_dir, progress, semaphore, browser):
    """
    Process a single page with concurrency control via semaphore.
    Uses the shared browser instance — creates a new context+page per document.
    Returns (status, title).
    """
    async with semaphore:
        title = page_data['title']
        href = page_data['href']
        url = f'{ORIGIN}{href}'
        filename = url_to_filename(url) + '.pdf'
        output_path = pdfs_dir / filename

        # Skip check
        if output_path.exists() and output_path.stat().st_size > 0:
            await progress.record_and_print(idx, title, '⏭', 'skipped')
            return 'skipped'

        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        )
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until='networkidle', timeout=60000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)

            # Check for 404
            is_404 = await page.evaluate('''() => {
                var h1 = document.querySelector('h1');
                return h1 && h1.textContent && (h1.textContent.includes('404') || h1.textContent.includes('Not Found'));
            }''')
            if is_404:
                await page.close()
                await context.close()
                await progress.record_and_print(idx, title, '❌', '404')
                return 'failed'

            # Apply DOM manipulation
            await page.evaluate(DOM_MANIPULATE_JS)

            # Wait for images - scroll to each image to trigger lazy-load
            img_positions = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('img')).map(img => ({
                    y: img.getBoundingClientRect().y,
                })).filter(img => img.y > 0);
            }''')
            img_positions.sort(key=lambda x: x['y'])

            for img in img_positions:
                y = img['y']
                await page.evaluate(f'() => window.scrollTo({{top: {y}, behavior: "auto"}})')
                await page.wait_for_timeout(500)

            await page.evaluate('() => window.scrollTo({top: 0, behavior: "auto"})')
            await page.wait_for_timeout(1000)

            # Wait until all images loaded (max 15s)
            for _ in range(30):
                all_loaded = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('img')).every(
                        img => img.complete && img.naturalWidth > 0
                    );
                }''')
                if all_loaded:
                    break
                await page.wait_for_timeout(500)

            # Generate PDF
            await page.pdf(
                path=str(output_path),
                format='A4',
                print_background=True,
                margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
            )

            size_kb = output_path.stat().st_size / 1024 if output_path.exists() else 0
            await page.close()
            await context.close()
            await progress.record_and_print(idx, title, '✓', f'{size_kb:>8.1f} KB')
            return 'success'

        except Exception as e:
            err_msg = str(e)[:60]
            await progress.record_and_print(idx, title, '✗', f'ERR: {err_msg}')
            try:
                await page.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            return 'failed'


async def main_async(num_workers):
    """Main async entry point."""
    print(f'Step 2 (async): Generating individual PDFs | {num_workers} workers (CPU: {os.cpu_count() or "?"})')
    print()

    # Load sidebar
    with open('sidebar.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    pages = flatten_pages(data['children'])
    total = len(pages)
    print(f'  Total pages to convert: {total}')

    # Create output directories
    pdfs_dir = Path('temp/pdfs')
    cover_dir = Path('Output/temp')
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    cover_dir.mkdir(parents=True, exist_ok=True)

    # Generate cover PDF
    cover_path = cover_dir / 'Cover_Hermes_Agent.pdf'
    if not cover_path.exists():
        print('  Generating cover page...')
        await generate_cover_pdf_async(str(cover_path), total)
    else:
        print('  Cover already exists, skipping.')
    print()

    # Separate pages into skip vs. need-processing
    pending = []
    already_skipped = 0
    for p in pages:
        fname = url_to_filename(f'{ORIGIN}{p["href"]}') + '.pdf'
        fpath = pdfs_dir / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            already_skipped += 1
        else:
            pending.append(p)

    print(f'  {already_skipped} pages already generated, {len(pending)} remaining')
    print()

    if not pending:
        print('  All pages already generated. Nothing to do.')
        return

    progress = ProgressDisplay(total)
    progress.set_done(already_skipped)

    # Launch one browser, process pages concurrently with semaphore
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(num_workers)

        tasks = []
        for i, page_data in enumerate(pending):
            orig_idx = pages.index(page_data) + 1
            tasks.append(process_page_async(page_data, orig_idx, total, pdfs_dir, progress, semaphore, browser))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        await browser.close()
    finally:
        await pw.stop()

    # Tally results
    success = already_skipped
    failed = 0
    for r in results:
        if isinstance(r, Exception):
            failed += 1
        elif r == 'success':
            success += 1
        else:
            failed += 1

    skipped = already_skipped
    print()
    print(f'  Summary: {success} generated (incl. skipped), {skipped} skipped, {failed} failed')
    print(f'  Output directory: {pdfs_dir}/')


def main():
    parser = argparse.ArgumentParser(description='Generate individual PDFs for each documentation page (async multi-page).')
    parser.add_argument('--workers', type=int, default=None,
                        help='Number of concurrent workers. Defaults to CPU count (%d on this machine).' % (os.cpu_count() or 4))
    args = parser.parse_args()

    num_workers = args.workers if args.workers else (os.cpu_count() or 4)
    asyncio.run(main_async(num_workers))


if __name__ == '__main__':
    main()
