#!/usr/bin/env python3
"""
github_scraper.py – Extract translatable text from cloudflare-docs GitHub repo.

Since developers.cloudflare.com may not be directly accessible, this script
fetches the documentation source files (MDX) from the cloudflare/cloudflare-docs
GitHub repository and extracts translatable text entries.

Strategy:
  1. Load a pre-built file list (file_list.json) of all .mdx paths, or
     discover them from the repo tree via the GitHub MCP tool.
  2. Download raw MDX content from raw.githubusercontent.com (no auth needed).
  3. Extract translatable text entries.
  4. Translate to Chinese using deep-translator.

Usage:
    python github_scraper.py                    # Full pipeline
    python github_scraper.py --max-pages 20     # Limit pages for testing
    python github_scraper.py --sections workers pages r2  # Specific sections only
    python github_scraper.py --skip-translate   # Extract only, no translation
    python github_scraper.py --build-file-list  # Discover MDX files via tree crawl
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Set
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

# Concurrency for raw content downloads
DOWNLOAD_CONCURRENCY = 8


async def build_file_list_from_tree(session: aiohttp.ClientSession) -> List[str]:
    """
    Crawl the repo tree page-by-page via raw.githubusercontent.com to discover .mdx files.
    Falls back to a known section list and discovers files within each.
    """
    # Known top-level sections (from repo exploration)
    known_sections = [
        "1.1.1.1", "agents", "ai-crawl-control", "ai-gateway", "ai-search",
        "analytics", "api-shield", "argo-smart-routing", "automatic-platform-optimization",
        "billing", "bots", "browser-rendering", "byoip", "cache", "china-network",
        "client-ip-geolocation", "client-side-security", "cloudflare-agent",
        "cloudflare-challenges", "cloudflare-for-platforms", "cloudflare-one",
        "cloudflare-wan", "constellation", "containers", "d1", "data-localization",
        "ddos-protection", "dmarc-management", "dns", "durable-objects",
        "dynamic-workers", "email-routing", "email-security", "firewall",
        "fundamentals", "google-tag-gateway", "health-checks", "hyperdrive",
        "images", "key-transparency", "kv", "learning-paths", "load-balancing",
        "log-explorer", "logs", "magic-transit", "migration-guides", "moq",
        "multi-cloud-networking", "network-error-logging", "network-flow",
        "network-interconnect", "network", "notifications", "pages", "pipelines",
        "privacy-gateway", "privacy-proxy", "pulumi", "queues", "r2-sql", "r2",
        "radar", "randomness-beacon", "realtime", "reference-architecture",
        "registrar", "rules", "ruleset-engine", "sandbox", "secrets-store",
        "security-center", "security", "smart-shield", "spectrum", "speed", "ssl",
        "stream", "style-guide", "support", "tenant", "terraform", "time-services",
        "tunnel", "turnstile", "use-cases", "vectorize", "version-management",
        "waf", "waiting-room", "warp-client", "web-analytics", "web3",
        "workers-ai", "workers-vpc", "workers", "workflows", "zaraz",
    ]
    logger.info("Will scan %d known sections for MDX files", len(known_sections))
    return known_sections


async def discover_mdx_files_in_section(
    session: aiohttp.ClientSession, section: str
) -> List[str]:
    """
    Discover .mdx files in a section by fetching the GitHub tree API for each dir.
    Uses raw.githubusercontent.com tree discovery.
    Returns list of file paths relative to repo root.
    """
    # Use a simple recursive approach via raw github content
    # We'll try to fetch the directory listing via the GitHub API
    # Since direct API might not work, we'll construct paths from known patterns
    files: List[str] = []
    base = f"{DOCS_BASE_PATH}/{section}"

    # Try to get the index file first
    index_url = f"{RAW_BASE}/{base}/index.mdx"
    try:
        async with session.head(index_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                files.append(f"{base}/index.mdx")
    except Exception:
        pass

    return files


def extract_text_from_mdx(content: str, file_path: str) -> Dict[str, Any]:
    """
    Extract translatable text entries from MDX content.
    Returns a dict with structured text entries.
    """
    entries: Dict[str, Any] = {}

    # Extract frontmatter title and description
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        title_match = re.search(r"^title:\s*(.+)$", fm, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip().strip('"').strip("'")
            if title:
                entries["title"] = title

        desc_match = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
        if desc_match:
            desc = desc_match.group(1).strip().strip('"').strip("'")
            if desc:
                entries["description"] = desc

        sidebar_match = re.search(r"^sidebar:\s*\n\s*label:\s*(.+)$", fm, re.MULTILINE)
        if sidebar_match:
            label = sidebar_match.group(1).strip().strip('"').strip("'")
            if label:
                entries["sidebar_label"] = label

    # Remove frontmatter for body parsing
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)

    # Remove import statements
    body = re.sub(r"^import\s+.*$", "", body, flags=re.MULTILINE)

    # Remove code blocks (we don't translate code)
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`]+`", "", body)

    # Remove HTML/JSX tags but keep their text content
    body = re.sub(r"<[^>]+>", " ", body)

    # Extract headings
    headings = []
    for m in re.finditer(r"^#{1,6}\s+(.+)$", body, re.MULTILINE):
        h = m.group(1).strip()
        # Remove markdown links from headings
        h = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", h)
        h = h.strip()
        if h and len(h) > 1:
            headings.append(h)
    if headings:
        entries["headings"] = headings

    # Extract paragraphs (lines of text that are not headings, lists, etc.)
    paragraphs = []
    for line in body.split("\n"):
        line = line.strip()
        # Skip empty, headings, list items, table rows, images, links-only lines
        if not line or line.startswith("#") or line.startswith("|") or line.startswith("!"):
            continue
        if line.startswith("- ") or line.startswith("* ") or re.match(r"^\d+\.\s", line):
            # List item - extract content
            item = re.sub(r"^[-*]\s+|^\d+\.\s+", "", line).strip()
            item = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", item)  # remove links
            if item and len(item) > 2:
                paragraphs.append(item)
            continue
        # Regular paragraph line
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)  # remove links
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)  # remove bold
        line = re.sub(r"\*([^*]+)\*", r"\1", line)  # remove italic
        line = line.strip()
        if line and len(line) > 2:
            paragraphs.append(line)

    if paragraphs:
        # Deduplicate while preserving order
        seen: Set[str] = set()
        unique_p = []
        for p in paragraphs:
            if p not in seen:
                seen.add(p)
                unique_p.append(p)
        entries["paragraphs"] = unique_p

    return entries


def mdx_path_to_url_path(mdx_path: str) -> str:
    """Convert a file path like 'src/content/docs/workers/index.mdx' to '/workers/'."""
    # Remove base path
    rel = mdx_path.replace(DOCS_BASE_PATH + "/", "")
    # Remove .mdx extension
    rel = rel.rsplit(".mdx", 1)[0]
    # Remove trailing 'index'
    if rel.endswith("/index") or rel == "index":
        rel = rel.rsplit("index", 1)[0]
    # Ensure leading and trailing slashes
    path = "/" + rel.strip("/")
    if not path.endswith("/"):
        path += "/"
    return path


async def scrape_section(
    session: aiohttp.ClientSession, section: str, file_paths: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Download and extract text from a list of MDX file paths."""
    entries: Dict[str, Dict[str, Any]] = {}
    sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    async def _process_file(fpath: str) -> None:
        async with sem:
            raw_url = f"{RAW_BASE}/{quote(fpath, safe='/')}"
            try:
                async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return
                    content = await resp.text()
            except Exception as exc:
                logger.debug("  Error downloading %s: %s", fpath, exc)
                return

            url_path = mdx_path_to_url_path(fpath)
            page_entries = extract_text_from_mdx(content, fpath)

            if page_entries:
                entries[url_path] = page_entries

    tasks = [_process_file(fp) for fp in file_paths]
    await asyncio.gather(*tasks)

    logger.info("  Section %s: %d/%d pages extracted", section, len(entries), len(file_paths))
    return entries


async def run(args: argparse.Namespace) -> None:
    """Main pipeline."""
    all_entries: Dict[str, Dict[str, Any]] = {}

    # Load or build the file list
    if os.path.exists(FILE_LIST_PATH):
        logger.info("Loading file list from %s", FILE_LIST_PATH)
        with open(FILE_LIST_PATH, "r", encoding="utf-8") as f:
            file_list = json.load(f)  # {section: [file_paths]}
    else:
        logger.error(
            "file_list.json not found. Run the file list builder first:\n"
            "  python build_file_list.py\n"
            "Or provide it manually."
        )
        sys.exit(1)

    # Filter sections if requested
    if args.sections:
        file_list = {s: paths for s, paths in file_list.items() if s in args.sections}

    total_files = sum(len(paths) for paths in file_list.values())
    logger.info("Will process %d files across %d sections", total_files, len(file_list))

    if args.max_pages > 0:
        # Limit total files
        limited: Dict[str, List[str]] = {}
        count = 0
        for section, paths in file_list.items():
            remaining = args.max_pages - count
            if remaining <= 0:
                break
            limited[section] = paths[:remaining]
            count += len(limited[section])
        file_list = limited
        total_files = sum(len(paths) for paths in file_list.values())
        logger.info("Limited to %d files", total_files)

    async with aiohttp.ClientSession() as session:
        for section, paths in file_list.items():
            section_entries = await scrape_section(session, section, paths)
            all_entries.update(section_entries)
            logger.info("Progress: %d total pages extracted", len(all_entries))

    # Save en.json
    os.makedirs(config.I18N_DIR, exist_ok=True)
    with open(config.EN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d pages to %s", len(all_entries), config.EN_JSON_PATH)

    # Translate
    if not args.skip_translate:
        logger.info("═══ Starting Translation ═══")
        from translator import translate_entries
        zh_entries = translate_entries(all_entries)
        with open(config.ZH_CN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(zh_entries, f, indent=2, ensure_ascii=False)
        logger.info("Saved %d pages to %s", len(zh_entries), config.ZH_CN_JSON_PATH)

    logger.info("═══ Done ═══")


def main() -> None:
    parser = argparse.ArgumentParser(description="CFDC GitHub Scraper")
    parser.add_argument("--sections", nargs="+", help="Specific sections to scrape")
    parser.add_argument("--max-pages", type=int, default=0, help="Max total pages (0=unlimited)")
    parser.add_argument("--skip-translate", action="store_true", help="Skip translation step")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
