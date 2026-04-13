#!/usr/bin/env python3
"""
build_file_list.py – Discover all .mdx files in cloudflare-docs repo.

Uses raw.githubusercontent.com to fetch the git tree and find all MDX files
under src/content/docs/. Outputs file_list.json.

This script can also accept a pre-built tree (from GitHub MCP tools or API).
"""

import asyncio
import json
import logging
import os
import re
import sys
from typing import Dict, List
from urllib.parse import quote

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_file_list")

REPO_OWNER = "cloudflare"
REPO_NAME = "cloudflare-docs"
BRANCH = "production"
DOCS_BASE = "src/content/docs"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "file_list.json")

# All known top-level sections
KNOWN_SECTIONS = [
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


async def probe_common_files(
    session: aiohttp.ClientSession, section: str
) -> List[str]:
    """
    Probe common file patterns to discover MDX files in a section.
    Returns list of paths that exist.
    """
    base = f"{DOCS_BASE}/{section}"
    found: List[str] = []

    # Common file patterns in Cloudflare docs
    candidates = [
        f"{base}/index.mdx",
        f"{base}/get-started.mdx",
        f"{base}/get-started/index.mdx",
        f"{base}/configuration.mdx",
        f"{base}/configuration/index.mdx",
        f"{base}/platform/index.mdx",
        f"{base}/platform/pricing.mdx",
        f"{base}/reference/index.mdx",
        f"{base}/examples/index.mdx",
        f"{base}/tutorials/index.mdx",
    ]

    sem = asyncio.Semaphore(10)

    async def _check(path: str) -> None:
        async with sem:
            url = f"{RAW_BASE}/{quote(path, safe='/')}"
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        found.append(path)
            except Exception:
                pass

    await asyncio.gather(*[_check(c) for c in candidates])
    return found


async def discover_via_html_tree(
    session: aiohttp.ClientSession, section: str
) -> List[str]:
    """
    Discover MDX files by fetching the GitHub tree page for the section.
    Uses the GitHub HTML tree view which lists all files.
    """
    found: List[str] = []

    # Fetch the GitHub file tree page (HTML)
    tree_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/file-list/{BRANCH}/{DOCS_BASE}/{section}"
    try:
        async with session.get(tree_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                return found
            html = await resp.text()
    except Exception:
        return found

    # Extract file paths from the HTML
    # GitHub file-list page contains file paths in various formats
    pattern = rf'{DOCS_BASE}/{re.escape(section)}/[^"<>\s]+\.mdx'
    for m in re.finditer(pattern, html):
        path = m.group(0)
        if path not in found:
            found.append(path)

    return found


async def discover_section_files_via_page(
    session: aiohttp.ClientSession, section: str
) -> List[str]:
    """
    Discover files by parsing the main GitHub tree page for the section.
    """
    found: List[str] = []
    base_path = f"{DOCS_BASE}/{section}"

    # Fetch the tree page
    url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/tree/{BRANCH}/{base_path}"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"Accept": "application/json"},
        ) as resp:
            if resp.status != 200:
                logger.debug("Tree page %s returned %d", url, resp.status)
                return found
            data = await resp.json()
    except Exception as exc:
        logger.debug("Tree page error %s: %s", url, exc)
        return found

    # Parse JSON payload
    items = data.get("payload", {}).get("tree", {}).get("items", [])
    for item in items:
        path = item.get("path", "")
        if path.endswith(".mdx"):
            found.append(f"{base_path}/{path}" if not path.startswith(base_path) else path)

    return found


async def discover_via_index_crawl(
    session: aiohttp.ClientSession, section: str
) -> List[str]:
    """
    Discover files by reading the index.mdx and following internal links.
    Then probe discovered paths for more MDX files.
    """
    found: List[str] = []
    base = f"{DOCS_BASE}/{section}"

    # First get the index
    index_url = f"{RAW_BASE}/{base}/index.mdx"
    try:
        async with session.get(index_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                found.append(f"{base}/index.mdx")
                content = await resp.text()
            else:
                return found
    except Exception:
        return found

    # Extract internal links from the MDX content
    # Look for links like [text](/section/path/) or href="/section/path/"
    link_pattern = rf'(?:href="|]\()/{re.escape(section)}/([^")\s#]+)'
    linked_paths = set()
    for m in re.finditer(link_pattern, content):
        sub_path = m.group(1).strip("/")
        if sub_path:
            linked_paths.add(sub_path)

    # Also look for sidebar config patterns
    # sidebar entries often reference sub-pages
    sidebar_pattern = r'(?:slug|link|href):\s*["\']?/?(?:' + re.escape(section) + r')/([^"\')\s#]+)'
    for m in re.finditer(sidebar_pattern, content):
        sub_path = m.group(1).strip("/")
        if sub_path:
            linked_paths.add(sub_path)

    # Probe each discovered path
    sem = asyncio.Semaphore(10)

    async def _probe(sub_path: str) -> None:
        candidates = [
            f"{base}/{sub_path}/index.mdx",
            f"{base}/{sub_path}.mdx",
        ]
        for candidate in candidates:
            url = f"{RAW_BASE}/{quote(candidate, safe='/')}"
            async with sem:
                try:
                    async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200 and candidate not in found:
                            found.append(candidate)
                            return
                except Exception:
                    pass

    await asyncio.gather(*[_probe(sp) for sp in linked_paths])
    return found


async def build_file_list() -> Dict[str, List[str]]:
    """Build the complete file list for all sections."""
    result: Dict[str, List[str]] = {}

    async with aiohttp.ClientSession() as session:
        for i, section in enumerate(KNOWN_SECTIONS):
            logger.info("[%d/%d] Discovering files in %s...", i + 1, len(KNOWN_SECTIONS), section)

            # Try multiple discovery methods
            files = await discover_via_index_crawl(session, section)
            common = await probe_common_files(session, section)

            # Merge
            all_files = list(set(files + common))
            all_files.sort()

            if all_files:
                result[section] = all_files
                logger.info("  Found %d files in %s", len(all_files), section)
            else:
                logger.warning("  No files found in %s", section)

    return result


async def main() -> None:
    logger.info("Building file list for cloudflare-docs...")
    file_list = await build_file_list()

    total = sum(len(v) for v in file_list.values())
    logger.info("Total: %d files across %d sections", total, len(file_list))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(file_list, f, indent=2, ensure_ascii=False)
    logger.info("Saved to %s", OUTPUT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
