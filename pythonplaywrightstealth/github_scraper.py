#!/usr/bin/env python3
"""
github_scraper.py – Resumable MDX content extraction and translation pipeline.

Downloads MDX source files from cloudflare/cloudflare-docs, extracts
translatable text, and produces i18n JSON files.

Features:
  - Disk-cached MDX downloads (cache/mdx/) with resume support
  - Incremental extraction with entries checkpoint (cache/entries_cache.json)
  - Rich content extraction: frontmatter, headings, paragraphs, list items,
    tables, admonitions (:::note/warning/caution/tip), details/summary blocks
  - Coverage reporting (cache/coverage_report.json)

Usage:
    python github_scraper.py                          # Full pipeline
    python github_scraper.py --max-pages 50           # Limit pages
    python github_scraper.py --sections workers r2    # Specific sections
    python github_scraper.py --skip-translate         # Extract only
    python github_scraper.py --fresh                  # Ignore cache
    python github_scraper.py --concurrency 16         # Faster downloads
"""

import argparse
import asyncio
import hashlib
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


# ── Caching helpers ─────────────────────────────────────────────────────────


def _safe_filename(file_path: str) -> str:
    """Convert an MDX repo path to a flat, filesystem-safe cache filename."""
    return hashlib.sha256(file_path.encode()).hexdigest() + ".mdx"


def _mdx_cache_path(cache_dir: str, file_path: str) -> str:
    return os.path.join(cache_dir, "mdx", _safe_filename(file_path))


def _read_cached_mdx(cache_dir: str, file_path: str) -> Optional[str]:
    p = _mdx_cache_path(cache_dir, file_path)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _write_cached_mdx(cache_dir: str, file_path: str, content: str) -> None:
    p = _mdx_cache_path(cache_dir, file_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def _load_entries_cache(cache_dir: str) -> Dict[str, Dict[str, Any]]:
    p = os.path.join(cache_dir, "entries_cache.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_entries_cache(
    cache_dir: str, entries: Dict[str, Dict[str, Any]]
) -> None:
    p = os.path.join(cache_dir, "entries_cache.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


# ── Path conversion ─────────────────────────────────────────────────────────


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
    cache_dir: str,
    fresh: bool,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Download a single MDX file.  Returns (file_path, content_or_None, error_or_None).
    Uses disk cache unless *fresh* is True.
    """
    if not fresh:
        cached = _read_cached_mdx(cache_dir, file_path)
        if cached is not None:
            return file_path, cached, None

    raw_url = f"{RAW_BASE}/{quote(file_path, safe='/')}"
    last_err: Optional[str] = None
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(
                    raw_url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        _write_cached_mdx(cache_dir, file_path, text)
                        return file_path, text, None
                    last_err = f"HTTP {resp.status}"
            except Exception as exc:
                last_err = str(exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    return file_path, None, last_err


# ── Main pipeline ───────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> None:
    cache_dir: str = args.cache_dir
    os.makedirs(os.path.join(cache_dir, "mdx"), exist_ok=True)

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
        "Will process %d files (%d in file_list.json, %d sections)",
        len(all_paths),
        total_in_file_list,
        len(file_list),
    )

    # ── Resume: load cached entries ─────────────────────────────────────
    if args.fresh:
        all_entries: Dict[str, Dict[str, Any]] = {}
    else:
        all_entries = _load_entries_cache(cache_dir)
        if all_entries:
            logger.info("Resumed %d entries from entries cache", len(all_entries))

    # Build set of paths already processed (present in entries cache)
    already_done: Set[str] = set()
    if not args.fresh:
        for p in all_paths:
            url_path = mdx_path_to_url_path(p)
            if url_path in all_entries:
                already_done.add(p)

    paths_to_process = [p for p in all_paths if p not in already_done]
    logger.info(
        "Skipping %d cached, downloading/extracting %d",
        len(already_done),
        len(paths_to_process),
    )

    # ── Download & extract ──────────────────────────────────────────────
    sem = asyncio.Semaphore(args.concurrency)
    stats = {
        "downloaded_ok": len(already_done),
        "download_errors": 0,
        "extract_empty": 0,
        "errors_detail": [],
    }

    processed_since_checkpoint = 0
    connector = aiohttp.TCPConnector(limit=args.concurrency * 2)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _download_one(session, sem, fp, cache_dir, args.fresh)
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

            processed_since_checkpoint += 1

            if i % PROGRESS_LOG_INTERVAL == 0:
                logger.info(
                    "Progress: %d/%d downloaded (%d entries so far)",
                    i,
                    len(paths_to_process),
                    len(all_entries),
                )

            if processed_since_checkpoint >= CHECKPOINT_INTERVAL:
                _save_entries_cache(cache_dir, all_entries)
                processed_since_checkpoint = 0
                logger.info("Checkpoint saved (%d entries)", len(all_entries))

    # Final checkpoint
    _save_entries_cache(cache_dir, all_entries)

    # ── Save en.json ────────────────────────────────────────────────────
    os.makedirs(config.I18N_DIR, exist_ok=True)
    with open(config.EN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d pages to %s", len(all_entries), config.EN_JSON_PATH)

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
    report_path = os.path.join(cache_dir, "coverage_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(coverage, f, indent=2, ensure_ascii=False)

    logger.info("═══ Coverage Report ═══")
    logger.info("  Total files in file_list.json : %d", coverage["total_files_in_file_list"])
    logger.info("  Files downloaded successfully  : %d", coverage["files_downloaded_ok"])
    logger.info("  Files with extraction errors   : %d", coverage["files_with_errors"])
    logger.info("  Files with no extractable text : %d", coverage["files_with_no_content"])
    logger.info("  Total unique URL paths output  : %d", coverage["total_url_paths_in_output"])
    logger.info("  Report saved to %s", report_path)

    # ── Translation ─────────────────────────────────────────────────────
    if not args.skip_translate:
        logger.info("═══ Starting Translation ═══")
        from translator import translate_entries

        zh_entries = translate_entries(
            all_entries, use_online=getattr(args, "online", False)
        )
        with open(config.ZH_CN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(zh_entries, f, indent=2, ensure_ascii=False)
        logger.info(
            "Saved %d pages to %s", len(zh_entries), config.ZH_CN_JSON_PATH
        )

    logger.info("═══ Done ═══")


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CFDC – Resumable MDX extraction & translation pipeline"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Max total pages to process (0 = unlimited)",
    )
    parser.add_argument(
        "--sections",
        nargs="+",
        help="Only process these sections",
    )
    parser.add_argument(
        "--skip-translate",
        action="store_true",
        help="Skip the translation step",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Use online translation (Google Translate)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore cache and re-download everything",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.path.join(SCRIPT_DIR, "cache"),
        help="Cache directory (default: cache/ in script dir)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Download concurrency (default: 8)",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
