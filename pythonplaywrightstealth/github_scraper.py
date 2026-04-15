#!/usr/bin/env python3
"""
github_scraper.py：MDX 内容提取与翻译流水线。

Downloads MDX source files from cloudflare/cloudflare-docs, extracts
translatable text, and produces i18n JSON files.

Features:
  - Rich content extraction: frontmatter, headings, paragraphs, list items,
    tables, admonitions (:::note/warning/caution/tip), details/summary blocks
  - 生成覆盖率报告（coverage_report.json）

Usage:
    python github_scraper.py                          # Full pipeline
    python github_scraper.py --max-pages 50           # Limit pages
    python github_scraper.py --sections workers r2    # Specific sections
    python github_scraper.py --skip-translate         # Extract only
    python github_scraper.py --concurrency 16         # Faster downloads
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import aiohttp

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("github_scraper")

REPO_OWNER = "cloudflare"
REPO_NAME = "cloudflare-docs"
BRANCH = "production"
DOCS_BASE_PATH = "src/content/docs"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_LIST_PATH = os.path.join(SCRIPT_DIR, "file_list.json")

MAX_RETRIES = 3
CHECKPOINT_INTERVAL = 500
PROGRESS_LOG_INTERVAL = 100


# ── 路径转换 ─────────────────────────────────────────────────────────


def mdx_path_to_url_path(mdx_path: str) -> str:
    """Convert e.g. 'src/content/docs/workers/index.mdx' → '/workers/'."""
    rel = mdx_path.replace(DOCS_BASE_PATH + "/", "")
    rel = rel.rsplit(".mdx", 1)[0]
    if rel.endswith("/index") or rel == "index":
        rel = rel.rsplit("index", 1)[0]
    path = "/" + rel.strip("/")
    if not path.endswith("/"):
        path += "/"
    return path


# ── Content extraction ──────────────────────────────────────────────────────


def _strip_md_formatting(text: str) -> str:
    """Remove markdown inline formatting but keep text content."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)   # links
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)        # images
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)            # bold
    text = re.sub(r"__(.+?)__", r"\1", text)                 # bold alt
    text = re.sub(r"\*(.+?)\*", r"\1", text)                 # italic
    text = re.sub(r"_(.+?)_", r"\1", text)                   # italic alt
    text = re.sub(r"~~(.+?)~~", r"\1", text)                 # strikethrough
    return text.strip()


def _is_translatable(text: str) -> bool:
    """Return True if text is worth translating (>2 chars, not pure punctuation)."""
    if len(text) <= 2:
        return False
    if re.fullmatch(r"[\s\-_=|/\\:;.,!?#*`~<>{}()\[\]\"']+", text):
        return False
    return True


def _clean_line(line: str) -> str:
    """Strip inline code, JSX/HTML tags, and markdown formatting from a line."""
    line = re.sub(r"`[^`]*`", "", line)           # inline code
    line = re.sub(r"<[^>]+>", " ", line)           # HTML/JSX tags
    line = _strip_md_formatting(line)
    return re.sub(r"\s+", " ", line).strip()


def _dedupe(items: List[str]) -> List[str]:
    """Deduplicate while preserving order."""
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_text_from_mdx(content: str, file_path: str) -> Dict[str, Any]:
    """
    Extract translatable text entries from MDX content.

    Returns a dict with keys: title, description, sidebar_label,
    headings, paragraphs, list_items, table_cells, admonitions.
    Only present when non-empty.
    """
    entries: Dict[str, Any] = {}

    # ── Frontmatter ─────────────────────────────────────────────────────
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        title_m = re.search(r"^title:\s*(.+)$", fm, re.MULTILINE)
        if title_m:
            t = title_m.group(1).strip().strip("\"'")
            if t:
                entries["title"] = t

        desc_m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
        if desc_m:
            d = desc_m.group(1).strip().strip("\"'")
            if d:
                entries["description"] = d

        sidebar_m = re.search(
            r"^sidebar:\s*\n\s*label:\s*(.+)$", fm, re.MULTILINE
        )
        if sidebar_m:
            lbl = sidebar_m.group(1).strip().strip("\"'")
            if lbl:
                entries["sidebar_label"] = lbl

    # ── Prepare body ────────────────────────────────────────────────────
    body = re.sub(
        r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL
    )
    # Remove import statements
    body = re.sub(r"^import\s+.*$", "", body, flags=re.MULTILINE)

    # ── Extract admonitions BEFORE stripping code blocks ────────────────
    admonitions: List[str] = []
    for m in re.finditer(
        r"^:::(note|warning|caution|tip|danger|important)\s*(?:\[.*?\])?\s*\n"
        r"(.*?)\n^:::\s*$",
        body,
        re.MULTILINE | re.DOTALL,
    ):
        block = m.group(2).strip()
        for line in block.split("\n"):
            cleaned = _clean_line(line)
            if _is_translatable(cleaned):
                admonitions.append(cleaned)

    # ── Extract table cells BEFORE removing table rows ──────────────────
    table_cells: List[str] = []
    for m in re.finditer(r"^\|(.+)\|$", body, re.MULTILINE):
        row = m.group(1)
        # Skip separator rows (---|---)
        if re.fullmatch(r"[\s|:\-]+", row):
            continue
        for cell in row.split("|"):
            cleaned = _clean_line(cell)
            if _is_translatable(cleaned):
                table_cells.append(cleaned)

    # ── Remove code blocks ──────────────────────────────────────────────
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`]*`", "", body)

    # ── Remove admonition fences (content already extracted) ────────────
    body = re.sub(
        r"^:::(note|warning|caution|tip|danger|important)\s*(?:\[.*?\])?\s*\n"
        r".*?\n^:::\s*$",
        "",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )

    # ── Remove table rows (content already extracted) ───────────────────
    body = re.sub(r"^\|.*\|$", "", body, flags=re.MULTILINE)

    # ── Remove HTML/JSX tags but keep text ──────────────────────────────
    body = re.sub(r"<[^>]+>", " ", body)

    # ── Extract headings ────────────────────────────────────────────────
    headings: List[str] = []
    for m in re.finditer(r"^#{1,6}\s+(.+)$", body, re.MULTILINE):
        h = _strip_md_formatting(m.group(1).strip())
        if _is_translatable(h):
            headings.append(h)

    # ── Extract list items and paragraphs ───────────────────────────────
    list_items: List[str] = []
    paragraphs: List[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip headings (already extracted), images, horizontal rules
        if (
            stripped.startswith("#")
            or stripped.startswith("![")
            or re.fullmatch(r"[-*_]{3,}", stripped)
            or re.fullmatch(r"---+", stripped)
        ):
            continue

        # List items (unordered: - or *, ordered: 1.)
        list_match = re.match(r"^(?:[-*+]|\d+\.)\s+(.*)", stripped)
        if list_match:
            item = _clean_line(list_match.group(1))
            if _is_translatable(item):
                list_items.append(item)
            continue

        # Regular paragraph line
        cleaned = _clean_line(stripped)
        if _is_translatable(cleaned):
            paragraphs.append(cleaned)

    # ── Assemble entries ────────────────────────────────────────────────
    if headings:
        entries["headings"] = _dedupe(headings)
    if paragraphs:
        entries["paragraphs"] = _dedupe(paragraphs)
    if list_items:
        entries["list_items"] = _dedupe(list_items)
    if table_cells:
        entries["table_cells"] = _dedupe(table_cells)
    if admonitions:
        entries["admonitions"] = _dedupe(admonitions)

    return entries


# ── Downloading ─────────────────────────────────────────────────────────────


async def _download_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    file_path: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """下载单个 MDX 文件，返回 (file_path, content, error)。"""
    raw_url = f"{RAW_BASE}/{quote(file_path, safe='/')}"
    last_err: Optional[str] = None
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        return file_path, await resp.text(), None
                    last_err = f"HTTP {resp.status}"
            except Exception as exc:
                last_err = str(exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    return file_path, None, last_err


# ── Main pipeline ───────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> None:
    # ── Load file list ──────────────────────────────────────────────────
    if not os.path.exists(FILE_LIST_PATH):
        logger.error(
            "file_list.json not found. Run:\n  python build_file_list.py"
        )
        sys.exit(1)

    with open(FILE_LIST_PATH, "r", encoding="utf-8") as f:
        file_list: Dict[str, List[str]] = json.load(f)

    if args.sections:
        file_list = {
            s: p for s, p in file_list.items() if s in args.sections
        }

    # Flatten to a single ordered list
    all_paths: List[str] = []
    for paths in file_list.values():
        all_paths.extend(paths)

    total_in_file_list = len(all_paths)

    if args.max_pages > 0:
        all_paths = all_paths[: args.max_pages]

    logger.info(
        "计划处理 %d 个文件（file_list.json 共 %d 个，涉及 %d 个分区）",
        len(all_paths),
        total_in_file_list,
        len(file_list),
    )

    all_entries: Dict[str, Dict[str, Any]] = {}
    paths_to_process = list(all_paths)
    logger.info("开始下载与提取，共 %d 个文件", len(paths_to_process))

    # ── 下载与提取 ───────────────────────────────────────────────────
    sem = asyncio.Semaphore(args.concurrency)
    stats = {
        "downloaded_ok": 0,
        "download_errors": 0,
        "extract_empty": 0,
        "errors_detail": [],
    }

    connector = aiohttp.TCPConnector(limit=args.concurrency * 2)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _download_one(session, sem, fp)
            for fp in paths_to_process
        ]

        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            file_path, content, err = await coro

            if err is not None:
                stats["download_errors"] += 1
                stats["errors_detail"].append(
                    {"file": file_path, "error": err}
                )
                continue

            stats["downloaded_ok"] += 1

            url_path = mdx_path_to_url_path(file_path)
            page_entries = extract_text_from_mdx(content, file_path)

            if page_entries:
                all_entries[url_path] = page_entries
            else:
                stats["extract_empty"] += 1


    # ── Save en.json ────────────────────────────────────────────────────
    os.makedirs(config.I18N_DIR, exist_ok=True)
    with open(config.EN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)
    logger.info("已写入 %d 个页面到 %s", len(all_entries), config.EN_JSON_PATH)

    # ── Coverage report ─────────────────────────────────────────────────
    coverage = {
        "total_files_in_file_list": total_in_file_list,
        "files_attempted": len(all_paths),
        "files_downloaded_ok": stats["downloaded_ok"],
        "files_with_errors": stats["download_errors"],
        "files_with_no_content": stats["extract_empty"],
        "total_url_paths_in_output": len(all_entries),
        "errors": stats["errors_detail"][:50],
    }
    report_path = os.path.join(SCRIPT_DIR, "coverage_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(coverage, f, indent=2, ensure_ascii=False)

    logger.info("═══ 覆盖率报告 ═══")
    logger.info("  file_list.json 文件总数      ：%d", coverage["total_files_in_file_list"])
    logger.info("  下载成功文件数               ：%d", coverage["files_downloaded_ok"])
    logger.info("  下载/提取失败文件数          ：%d", coverage["files_with_errors"])
    logger.info("  无可提取文本文件数           ：%d", coverage["files_with_no_content"])
    logger.info("  输出 URL 路径总数            ：%d", coverage["total_url_paths_in_output"])
    logger.info("  报告已写入 %s", report_path)

    # ── Translation ─────────────────────────────────────────────────────
    if not args.skip_translate:
        logger.info("═══ 开始翻译 ═══")
        from translator import translate_entries

        zh_entries = translate_entries(
            all_entries, use_online=getattr(args, "online", False)
        )
        with open(config.ZH_CN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(zh_entries, f, indent=2, ensure_ascii=False)
        logger.info(
            "已写入 %d 个页面到 %s", len(zh_entries), config.ZH_CN_JSON_PATH
        )

    logger.info("═══ 完成 ═══")


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CFDC：MDX 提取与翻译流水线"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="最多处理页面数（0 为不限制）",
    )
    parser.add_argument(
        "--sections",
        nargs="+",
        help="仅处理指定分区",
    )
    parser.add_argument(
        "--skip-translate",
        action="store_true",
        help="跳过翻译阶段",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="使用在线翻译（Google Translate）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="下载并发数（默认 8）",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
