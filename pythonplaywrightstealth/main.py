#!/usr/bin/env python3
"""
main.py – Orchestrator for the CFDC crawler & translator pipeline.

Usage:
    python main.py                  # Full pipeline
    python main.py --urls-only      # Only discover URLs
    python main.py --extract-only   # Only extract (requires urls.json)
    python main.py --translate-only  # Only translate (requires en.json)
    python main.py --max-pages N    # Limit to N pages (for testing)

Outputs:
    ../i18n/en.json      – English text entries
    ../i18n/zh-cn.json   – Chinese translations
"""

import argparse
import asyncio
import json
import logging
import os
import sys

import config
from crawler import discover_urls
from extractor import extract_all
from translator import translate_entries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def save_json(data: dict, path: str) -> None:
    """Write dict to a JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved %s (%d top-level keys)", path, len(data))


def load_json(path: str) -> dict:
    """Read a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run(args: argparse.Namespace) -> None:
    """Main async pipeline."""

    if args.max_pages:
        config.MAX_PAGES = args.max_pages

    # ── Phase 1: URL discovery ──────────────────────────────────────────
    if not args.translate_only and not args.extract_only:
        logger.info("═══ Phase 1: URL Discovery ═══")
        urls = await discover_urls(use_bfs=args.bfs)
        logger.info("Total URLs: %d", len(urls))
        if args.urls_only:
            return

    # ── Phase 2: Content extraction ─────────────────────────────────────
    if not args.translate_only:
        if args.extract_only:
            if not os.path.exists(config.URLS_CACHE_PATH):
                logger.error("urls.json not found. Run without --extract-only first.")
                sys.exit(1)
            urls = load_json(config.URLS_CACHE_PATH)

        logger.info("═══ Phase 2: Content Extraction ═══")
        en_entries = await extract_all(urls)
        save_json(en_entries, config.EN_JSON_PATH)
    else:
        if not os.path.exists(config.EN_JSON_PATH):
            logger.error("en.json not found. Run extraction first.")
            sys.exit(1)
        en_entries = load_json(config.EN_JSON_PATH)

    # ── Phase 3: Translation ────────────────────────────────────────────
    logger.info("═══ Phase 3: Translation ═══")
    zh_entries = translate_entries(en_entries)
    save_json(zh_entries, config.ZH_CN_JSON_PATH)

    # ── Done ────────────────────────────────────────────────────────────
    logger.info("═══ Pipeline Complete ═══")
    logger.info("  English entries: %s", config.EN_JSON_PATH)
    logger.info("  Chinese entries: %s", config.ZH_CN_JSON_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="CFDC Crawler & Translator")
    parser.add_argument("--urls-only", action="store_true", help="Only discover URLs")
    parser.add_argument("--extract-only", action="store_true", help="Only extract content")
    parser.add_argument("--translate-only", action="store_true", help="Only translate")
    parser.add_argument("--bfs", action="store_true", help="Use BFS crawling in addition to sitemap")
    parser.add_argument("--max-pages", type=int, default=0, help="Max pages to process (0 = unlimited)")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
