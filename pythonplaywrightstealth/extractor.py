"""extractor.py：从渲染后的页面中提取可翻译文本。"""

import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth  # type: ignore[import-untyped]

import config

stealth = Stealth()
logger = logging.getLogger(__name__)

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
    ("nav a", "nav", "text_list"),
]


async def extract_page_entries(page: Page, url: str) -> Dict[str, Any]:
    """进入单页并提取文本条目。"""
    entries: Dict[str, Any] = {}
    try:
        await page.goto(url, wait_until="networkidle", timeout=config.PAGE_TIMEOUT_MS)
    except Exception as exc:
        logger.warning("页面加载失败 %s：%s", url, exc)
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
                    if txt and txt not in texts:
                        texts.append(txt)
                if texts:
                    entries[key_prefix] = texts
        except Exception as exc:
            logger.debug("选择器 %s 在 %s 提取失败：%s", selector, url, exc)

    return entries


async def extract_all(urls: List[str]) -> Dict[str, Dict[str, Any]]:
    """提取全部 URL，不做断点缓存。"""
    all_entries: Dict[str, Dict[str, Any]] = {}
    logger.info("开始提取页面：%d", len(urls))

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

        sem = asyncio.Semaphore(config.CONCURRENCY)

        async def _process(url: str) -> None:
            async with sem:
                p = await context.new_page()
                try:
                    entries = await extract_page_entries(p, url)
                    path = urlparse(url).path
                    if entries:
                        all_entries[path] = entries
                        logger.info("✓ %s（%d 个键）", path, len(entries))
                    else:
                        logger.info("✗ %s（无条目）", path)
                except Exception as exc:
                    logger.warning("✗ %s 提取异常：%s", url, exc)
                finally:
                    await p.close()
                await asyncio.sleep(config.CRAWL_DELAY)

        await asyncio.gather(*[_process(u) for u in urls])
        await browser.close()

    return all_entries
