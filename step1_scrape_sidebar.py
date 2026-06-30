#!/usr/bin/env python3
"""
Step 1: Scrape the Hermes Agent documentation sidebar structure.

Uses click-to-expand on all .menu__link--sublist-caret elements with aria-expanded="false",
then force-shows all ul.menu__list elements to discover the full tree.

Outputs:
  - sidebar.json: Full tree structure with {title, href, level, children}
  - sidebar.md:   Human-readable Markdown table of contents

Usage:
  source venv/Scripts/activate
  python step1_scrape_sidebar.py
"""

import json
import sys
import io
from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = 'https://hermes-agent.nousresearch.com/docs/'


def expand_sidebar_all(page):
    """Expand ALL sidebar sections using the two-phase approach from the Node.js scripts."""

    # Phase 1: Click ALL collapsed headers repeatedly
    print('    Phase 1: Clicking all collapsed headers...')
    for p in range(6):
        result = page.evaluate('''() => {
            let clicks = 0;
            document.querySelectorAll('a[aria-expanded="false"].menu__link--sublist, a[aria-expanded="false"].menu__link--sublist-caret')
                .forEach(l => { l.click(); clicks++; });
            return { clicks, total: document.querySelectorAll('.menu__list-item').length };
        }''')
        print(f'    Pass {p+1}: clicked={result["clicks"]} totalItems={result["total"]}')
        if result['clicks'] == 0:
            break
        page.wait_for_timeout(1500)

    # Phase 2: Force-show ALL ul.menu__list + remove collapsed class
    print('    Phase 2: Force-showing all nested lists...')
    for p in range(4):
        result = page.evaluate('''() => {
            let forceShown = 0;
            // Force-show ALL ul.menu__list
            document.querySelectorAll('ul.menu__list').forEach(function(ul) {
                var c = window.getComputedStyle(ul);
                if (c.display === 'none' || c.maxHeight === '0px' || c.height === '0px') {
                    ul.style.setProperty('display', 'block', 'important');
                    ul.style.setProperty('max-height', 'none', 'important');
                    ul.style.setProperty('height', 'auto', 'important');
                    ul.style.setProperty('visibility', 'visible', 'important');
                    ul.style.setProperty('overflow', 'visible', 'important');
                    forceShown++;
                }
            });
            // Remove collapsed class from ALL li.menu__list-item
            document.querySelectorAll('li.menu__list-item--collapsed').forEach(function(li) {
                li.classList.remove('menu__list-item--collapsed');
            });
            // Force-show ALL li.menu__list-item with 0 height
            document.querySelectorAll('.menu__list-item').forEach(function(li) {
                var c = window.getComputedStyle(li);
                if (c.height === '0px') {
                    li.style.setProperty('display', 'list-item', 'important');
                    li.style.setProperty('height', 'auto', 'important');
                    li.style.setProperty('min-height', '32px', 'important');
                }
            });
            return { forceShown, total: document.querySelectorAll('.menu__list-item').length };
        }''')
        print(f'    Pass {p+1}: forceShown={result["forceShown"]} totalItems={result["total"]}')
        if result['forceShown'] == 0:
            break
        page.wait_for_timeout(500)

    # Final count
    final = page.evaluate('''() => ({
        total: document.querySelectorAll('.menu__list-item').length,
        lists: document.querySelectorAll('ul.menu__list').length
    })''')
    print(f'    Final: items={final["total"]} lists={final["lists"]}')


def extract_sidebar_tree(page):
    """Extract the full sidebar tree after expansion, using depth-first DOM walk."""
    return page.evaluate('''() => {
        const sidebar = document.querySelector('aside.theme-doc-sidebar-container')
            || document.querySelector('[class*="docSidebarContainer"]')
            || document.querySelector('aside');
        if (!sidebar) return [];

        const result = [];
        const seen = new Set();

        function walk(li, parentGroup) {
            // Check if this li has a collapsible header + nested list
            const collapsible = li.querySelector(':scope > div.menu__list-item-collapsible');
            const subLink = collapsible ? collapsible.querySelector('a.menu__link--sublist') : null;
            const nested = li.querySelector(':scope > ul.menu__list');

            if (nested && subLink) {
                // This is a category with children
                const span = subLink.querySelector('span[title]');
                const name = span ? span.getAttribute('title') : subLink.textContent.trim();
                const groupName = (name && name.length >= 2) ? name : parentGroup;

                const href = subLink.getAttribute('href') || '';
                const levelMatch = li.className.match(/level-(\d)/);
                const level = levelMatch ? parseInt(levelMatch[1]) : 1;

                const item = {
                    title: name,
                    href: href || '',
                    level: level,
                    type: 'category',
                    children: [],
                };

                nested.querySelectorAll(':scope > li').forEach(function(c) {
                    const child = walk(c, groupName);
                    if (child) item.children.push(child);
                });

                // If no href, use first child's href
                if (!item.href && item.children.length > 0) {
                    item.href = item.children[0].href || '';
                }

                return item;
            }

            // This is a leaf link
            const linkEl = li.querySelector(':scope > a.menu__link:not(.menu__link--sublist)')
                || li.querySelector(':scope > a[href]:not([href="#"])');
            if (linkEl) {
                const text = linkEl.textContent.trim();
                const href = linkEl.getAttribute('href');
                if (text && text.length >= 2 && href && href.indexOf('/docs/') >= 0 && !seen.has(href)) {
                    seen.add(href);
                    const levelMatch = li.className.match(/level-(\d)/);
                    return {
                        title: text,
                        href: href,
                        level: levelMatch ? parseInt(levelMatch[1]) : 1,
                        type: 'link',
                        children: [],
                    };
                }
            }
            return null;
        }

        const menuList = sidebar.querySelector('ul.theme-doc-sidebar-menu') || sidebar.querySelector('ul.menu__list');
        if (menuList) {
            menuList.querySelectorAll(':scope > li').forEach(function(li) {
                const item = walk(li, null);
                if (item) result.push(item);
            });
        }
        return result;
    }''')


def count_leaves(tree):
    """Count leaf pages in the tree."""
    count = 0
    for node in tree:
        if not node.get('children'):
            count += 1
        else:
            count += count_leaves(node['children'])
    return count


def clean_tree(nodes):
    """Remove 'type' field from tree for final output."""
    result = []
    for n in nodes:
        cleaned = {
            'title': n['title'],
            'href': n['href'],
            'level': n['level'],
        }
        if n.get('children'):
            cleaned['children'] = clean_tree(n['children'])
        result.append(cleaned)
    return result


def tree_to_markdown(tree, indent=0):
    """Convert the tree to a Markdown table of contents."""
    lines = []
    for node in tree:
        prefix = '  ' * indent
        if node['children']:
            lines.append(f'{prefix}- **{node["title"]}**')
            lines.extend(tree_to_markdown(node['children'], indent + 1))
        else:
            lines.append(f'{prefix}- [{node["title"]}](https://hermes-agent.nousresearch.com{node["href"]})')
    return lines


def main():
    print('Step 1: Scraping sidebar structure from', BASE_URL)
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1600, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        )
        page = context.new_page()

        print('  Navigating to', BASE_URL)
        page.goto(BASE_URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(3000)

        print('  Expanding all sidebar sections...')
        expand_sidebar_all(page)
        page.wait_for_timeout(2000)

        print('  Extracting sidebar tree...')
        tree = extract_sidebar_tree(page)

        browser.close()

    total = count_leaves(tree)
    print(f'  Total pages: {total}')
    print(f'  Top-level categories: {len(tree)}')

    # Show structure summary
    for node in tree:
        has = bool(node.get('children'))
        leaf_count = count_leaves(node['children']) if has else 1
        print(f'    [{node["level"]}] {"+" if has else "-"} {node["title"]} ({leaf_count} pages)')

    clean_sidebar = clean_tree(tree)

    # Prepend homepage as first entry
    home_node = {
        'title': 'Hermes Agent Documentation',
        'href': '/docs/',
        'level': 1,
    }
    clean_sidebar.insert(0, home_node)
    total += 1  # count the homepage

    # Output sidebar.json
    output_json = {
        'source': BASE_URL,
        'root': 'Hermes Agent Documentation',
        'total_pages': total,
        'children': clean_sidebar,
    }

    with open('sidebar.json', 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    print('  Written: sidebar.json')

    # Output sidebar.md
    md_lines = [
        '# Hermes Agent Documentation - Table of Contents',
        '',
        f'Source: {BASE_URL}',
        f'Total pages: {total}',
        '',
        f'- [Hermes Agent Documentation]({BASE_URL})',
        '',
    ]
    md_lines.extend(tree_to_markdown(tree))

    with open('sidebar.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines) + '\n')
    print('  Written: sidebar.md')

    print()
    print('Done!')


if __name__ == '__main__':
    main()
