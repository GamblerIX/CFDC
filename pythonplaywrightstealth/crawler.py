"""
crawler.py – URL discovery & page fetching using Playwright-stealth.

Two-phase URL discovery:
  1. Parse sitemap.xml (fast, no browser needed).
  2. Optionally BFS-crawl with Playwright for URLs missing from the sitemap.
"""

import asyncio
import json
import logging
import os
import re
from typing import List, Set
from urllib.parse import urljoin, urlparse

import aiohttp
from lxml import etree
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async  # type: ignore[import-untyped]

import config

logger = logging.getLogger(__name__)

# ─── Sitemap parsing ────────────────────────────────────────────────────────

async def fetch_sitemap_urls() -> List[str]:
    """Download and parse sitemap.xml (including nested sitemaps) to get all URLs."""
    urls: Set[str] = set()
    to_fetch = [config.SITEMAP_URL]

    async with aiohttp.ClientSession() as session:
        while to_fetch:
            sitemap_url = to_fetch.pop()
            logger.info("Fetching sitemap: %s", sitemap_url)
            try:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("Sitemap %s returned status %d", sitemap_url, resp.status)
                        continue
                    xml_bytes = await resp.read()
            except Exception as exc:
                logger.warning("Failed to fetch sitemap %s: %s", sitemap_url, exc)
                continue

            try:
                root = etree.fromstring(xml_bytes)
            except etree.XMLSyntaxError as exc:
                logger.warning("Failed to parse sitemap %s: %s", sitemap_url, exc)
                continue

            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # Nested sitemaps
            for loc in root.findall(".//sm:sitemap/sm:loc", ns):
                if loc.text:
                    to_fetch.append(loc.text.strip())

            # Actual page URLs
            for loc in root.findall(".//sm:url/sm:loc", ns):
                if loc.text:
                    url = loc.text.strip()
                    if _is_valid_doc_url(url):
                        urls.add(_normalise_url(url))

    result = sorted(urls)
    logger.info("Sitemap discovery found %d URLs", len(result))
    return result


# ─── BFS browser crawling (supplement) ──────────────────────────────────────

async def bfs_crawl_urls(
    seed_urls: List[str] | None = None,
    known_urls: Set[str] | None = None,
    max_pages: int = 0,
) -> List[str]:
    """
    BFS-crawl using Playwright-stealth, starting from *seed_urls*.
    Returns newly discovered URLs not in *known_urls*.
    """
    visited: Set[str] = set(known_urls or set())
    queue: list[str] = list(seed_urls or [config.BASE_URL + "/"])
    discovered: Set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await stealth_async(page)

        while queue:
            if 0 < max_pages <= len(visited):
                break
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            logger.info("BFS visiting: %s", url)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
                await page.wait_for_timeout(1000)  # let JS render

                hrefs = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.href)",
                )
                for href in hrefs:
                    norm = _normalise_url(href)
                    if norm and _is_valid_doc_url(norm) and norm not in visited:
                        queue.append(norm)
                        discovered.add(norm)
            except Exception as exc:
                logger.warning("BFS error on %s: %s", url, exc)

            await asyncio.sleep(config.CRAWL_DELAY)

        await browser.close()

    new_urls = sorted(discovered - (known_urls or set()))
    logger.info("BFS crawl discovered %d new URLs", len(new_urls))
    return new_urls


# ─── Combined URL discovery ─────────────────────────────────────────────────

async def discover_urls(use_bfs: bool = False) -> List[str]:
    """
    Full URL discovery pipeline.
    1. Try sitemap.
    2. Optionally supplement with BFS.
    3. Cache to urls.json.
    """
    # Check cache
    if os.path.exists(config.URLS_CACHE_PATH):
        logger.info("Loading cached URLs from %s", config.URLS_CACHE_PATH)
        with open(config.URLS_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    urls = await fetch_sitemap_urls()

    if use_bfs:
        extra = await bfs_crawl_urls(known_urls=set(urls))
        urls = sorted(set(urls) | set(extra))

    if config.MAX_PAGES > 0:
        urls = urls[: config.MAX_PAGES]

    # Cache
    with open(config.URLS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d URLs to %s", len(urls), config.URLS_CACHE_PATH)

    return urls


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _normalise_url(url: str) -> str:
    """Strip fragment and query, ensure trailing slash for directories."""
    parsed = urlparse(url)
    # Only keep same-origin
    if parsed.netloc and parsed.netloc != urlparse(config.BASE_URL).netloc:
        return ""
    path = parsed.path.rstrip("/") + "/"
    return f"{config.BASE_URL}{path}"


def _is_valid_doc_url(url: str) -> bool:
    """Return True if the URL looks like a documentation page."""
    if not url.startswith(config.BASE_URL):
        return False
    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in config.SKIP_EXTENSIONS:
        return False
    return True
