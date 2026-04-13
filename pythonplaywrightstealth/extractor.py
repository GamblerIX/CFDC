"""
extractor.py – Extract translatable text entries from rendered pages.

Uses Playwright-stealth to load each page and pull out structured text.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth  # type: ignore[import-untyped]

import config

stealth = Stealth()

logger = logging.getLogger(__name__)

# CSS selectors and their logical names
# (selector, key_prefix, extract_mode)
#   extract_mode: "text" = innerText, "list" = list of innerText from children
SELECTORS: list[tuple[str, str, str]] = [
    ("article h1", "h1", "text"),
    ("article h2", "h2", "text_list"),
    ("article h3", "h3", "text_list"),
    ("article h4", "h4", "text_list"),
    ("article p", "p", "text_list"),
    ("article li", "li", "text_list"),
    ("article td", "td", "text_list"),
    ("article th", "th", "text_list"),
    ("article blockquote", "blockquote", "text_list"),
    ("article a", "link", "text_list"),
    # Sidebar / navigation
    ("nav a", "nav", "text_list"),
]


async def extract_page_entries(page: Page, url: str) -> Dict[str, Any]:
    """
    Navigate to *url* and extract translatable text entries.
    Returns a dict keyed by selector-based identifiers.
    """
    path = urlparse(url).path
    entries: Dict[str, Any] = {}

    try:
        await page.goto(url, wait_until="networkidle", timeout=config.PAGE_TIMEOUT_MS)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", url, exc)
        return entries

    for selector, key_prefix, mode in SELECTORS:
        try:
            if mode == "text":
                el = await page.query_selector(selector)
                if el:
                    txt = (await el.inner_text()).strip()
                    if txt:
                        entries[key_prefix] = txt
            elif mode == "text_list":
                elements = await page.query_selector_all(selector)
                texts = []
                for el in elements:
                    txt = (await el.inner_text()).strip()
                    if txt and txt not in texts:  # deduplicate
                        texts.append(txt)
                if texts:
                    entries[key_prefix] = texts
        except Exception as exc:
            logger.debug("Selector %s failed on %s: %s", selector, url, exc)

    return entries


async def extract_all(urls: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Extract text entries from all URLs.
    Returns {path: {key: value, ...}, ...}.
    Supports resuming from cache.
    """
    all_entries: Dict[str, Dict[str, Any]] = {}

    # Load partial cache if exists
    if os.path.exists(config.ENTRIES_CACHE_PATH):
        with open(config.ENTRIES_CACHE_PATH, "r", encoding="utf-8") as f:
            all_entries = json.load(f)
        logger.info("Loaded %d cached page entries", len(all_entries))

    # Filter already-done URLs
    remaining = [u for u in urls if urlparse(u).path not in all_entries]
    if not remaining:
        logger.info("All pages already extracted.")
        return all_entries

    logger.info("Extracting entries from %d pages (%d already cached)", len(remaining), len(all_entries))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        await stealth.apply_stealth_async(context)

        # Process in batches with concurrency
        sem = asyncio.Semaphore(config.CONCURRENCY)

        async def _process(url: str) -> None:
            async with sem:
                p = await context.new_page()
                try:
                    entries = await extract_page_entries(p, url)
                    path = urlparse(url).path
                    if entries:
                        all_entries[path] = entries
                        logger.info("  ✓ %s (%d keys)", path, len(entries))
                    else:
                        logger.info("  ✗ %s (no entries)", path)
                except Exception as exc:
                    logger.warning("  ✗ %s error: %s", url, exc)
                finally:
                    await p.close()
                await asyncio.sleep(config.CRAWL_DELAY)

        # Process all remaining, save periodically
        batch_size = 50
        for i in range(0, len(remaining), batch_size):
            batch = remaining[i : i + batch_size]
            await asyncio.gather(*[_process(u) for u in batch])

            # Save checkpoint
            with open(config.ENTRIES_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(all_entries, f, indent=2, ensure_ascii=False)
            logger.info("Checkpoint: %d total pages extracted", len(all_entries))

        await browser.close()

    return all_entries
