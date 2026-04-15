#!/usr/bin/env python3
"""main.py：CFDC 抓取翻译总入口。"""

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("已写入 %s（%d 个顶层键）", path, len(data))


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run(args: argparse.Namespace) -> None:
    if args.max_pages:
        config.MAX_PAGES = args.max_pages

    if not args.translate_only and not args.extract_only:
        logger.info("═══ 阶段 1：发现 URL ═══")
        urls = await discover_urls(use_bfs=args.bfs, save_to_file=True)
        logger.info("URL 总数：%d", len(urls))
        if args.urls_only:
            return
    elif args.extract_only:
        if not os.path.exists(config.URLS_JSON_PATH):
            logger.error("未找到 urls.json，请先执行 URL 发现阶段")
            sys.exit(1)
        urls = load_json(config.URLS_JSON_PATH)

    if not args.translate_only:
        logger.info("═══ 阶段 2：提取文本 ═══")
        en_entries = await extract_all(urls)
        save_json(en_entries, config.EN_JSON_PATH)
    else:
        if not os.path.exists(config.EN_JSON_PATH):
            logger.error("未找到 en.json，请先执行提取阶段")
            sys.exit(1)
        en_entries = load_json(config.EN_JSON_PATH)

    logger.info("═══ 阶段 3：执行翻译 ═══")
    zh_entries = translate_entries(en_entries)
    save_json(zh_entries, config.ZH_CN_JSON_PATH)

    logger.info("═══ 全流程完成 ═══")
    logger.info("英文词条：%s", config.EN_JSON_PATH)
    logger.info("中文词条：%s", config.ZH_CN_JSON_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="CFDC 抓取与翻译工具")
    parser.add_argument("--urls-only", action="store_true", help="仅发现 URL")
    parser.add_argument("--extract-only", action="store_true", help="仅提取内容")
    parser.add_argument("--translate-only", action="store_true", help="仅翻译")
    parser.add_argument("--bfs", action="store_true", help="在 sitemap 之外启用 BFS")
    parser.add_argument("--max-pages", type=int, default=0, help="处理页面上限（0 为不限制）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
