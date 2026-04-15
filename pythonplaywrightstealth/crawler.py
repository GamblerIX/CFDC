"""crawler.py：文档 URL 发现模块（站点地图 + 可选 BFS 补充）。"""

import asyncio
import json
import logging
import os
from typing import List, Set
from urllib.parse import urlparse

import aiohttp
from lxml import etree
from playwright.async_api import async_playwright
from playwright_stealth import Stealth  # type: ignore[import-untyped]

import config

stealth = Stealth()
logger = logging.getLogger(__name__)


async def fetch_sitemap_urls() -> List[str]:
    """下载并解析 sitemap（含嵌套 sitemap），返回文档 URL 列表。"""
    urls: Set[str] = set()
    to_fetch = [config.SITEMAP_URL]

    async with aiohttp.ClientSession() as session:
        while to_fetch:
            sitemap_url = to_fetch.pop()
            logger.info("正在抓取站点地图：%s", sitemap_url)
            try:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("站点地图 %s 返回状态码 %d", sitemap_url, resp.status)
                        continue
                    xml_bytes = await resp.read()
            except Exception as exc:
                logger.warning("抓取站点地图失败 %s：%s", sitemap_url, exc)
                continue

            try:
                root = etree.fromstring(xml_bytes)
            except etree.XMLSyntaxError as exc:
                logger.warning("解析站点地图失败 %s：%s", sitemap_url, exc)
                continue

            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//sm:sitemap/sm:loc", ns):
                if loc.text:
                    to_fetch.append(loc.text.strip())

            for loc in root.findall(".//sm:url/sm:loc", ns):
                if loc.text:
                    url = _normalise_url(loc.text.strip())
                    if url and _is_valid_doc_url(url):
                        urls.add(url)

    result = sorted(urls)
    logger.info("站点地图发现 URL 数量：%d", len(result))
    return result


async def bfs_crawl_urls(
    seed_urls: List[str] | None = None,
    known_urls: Set[str] | None = None,
    max_pages: int = 0,
) -> List[str]:
    """使用浏览器 BFS 补充发现 URL。"""
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
        await stealth.apply_stealth_async(context)
        page = await context.new_page()

        while queue:
            if 0 < max_pages <= len(visited):
                break

            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            logger.info("BFS 访问：%s", url)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
                await page.wait_for_timeout(1000)
                hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                for href in hrefs:
                    norm = _normalise_url(href)
                    if norm and _is_valid_doc_url(norm) and norm not in visited:
                        queue.append(norm)
                        discovered.add(norm)
            except Exception as exc:
                logger.warning("BFS 抓取失败 %s：%s", url, exc)

            await asyncio.sleep(config.CRAWL_DELAY)

        await browser.close()

    new_urls = sorted(discovered - (known_urls or set()))
    logger.info("BFS 新发现 URL 数量：%d", len(new_urls))
    return new_urls


async def discover_urls(use_bfs: bool = False, save_to_file: bool = True) -> List[str]:
    """完整 URL 发现流程，不使用缓存。"""
    urls = await fetch_sitemap_urls()

    if use_bfs:
        extra = await bfs_crawl_urls(known_urls=set(urls), max_pages=config.MAX_PAGES)
        urls = sorted(set(urls) | set(extra))

    if config.MAX_PAGES > 0:
        urls = urls[: config.MAX_PAGES]

    if save_to_file:
        with open(config.URLS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(urls, f, indent=2, ensure_ascii=False)
        logger.info("已输出 URL 列表：%s（%d 条）", config.URLS_JSON_PATH, len(urls))

    return urls


def _normalise_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != urlparse(config.BASE_URL).netloc:
        return ""
    path = parsed.path.rstrip("/") + "/"
    return f"{config.BASE_URL}{path}"


def _is_valid_doc_url(url: str) -> bool:
    if not url.startswith(config.BASE_URL):
        return False
    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower()
    return ext not in config.SKIP_EXTENSIONS
