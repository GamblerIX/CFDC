#!/usr/bin/env python3
"""
build_file_list.py – Discover all .mdx files in cloudflare-docs repo.

Uses the GitHub API recursive tree endpoint to fetch every file path in a
single request, then filters for .mdx files under src/content/docs/.
Outputs file_list.json grouped by top-level section.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

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

GITHUB_API = "https://api.github.com"
TREE_URL = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/git/trees"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "file_list.json")

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubled each retry


def _docs_prefix(section: str) -> str:
    return f"{DOCS_BASE}/{section}/"


def _section_from_path(path: str) -> Optional[str]:
    """Extract the top-level section name from a docs path."""
    if not path.startswith(DOCS_BASE + "/"):
        return None
    rest = path[len(DOCS_BASE) + 1:]
    section = rest.split("/", 1)[0]
    return section if section else None


async def _fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    params: Optional[dict] = None,
) -> dict:
    """Fetch JSON from *url* with retry logic and error handling."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 403:
                    # Rate-limited – honour Retry-After if present
                    retry_after = int(resp.headers.get("Retry-After", RETRY_BACKOFF * attempt))
                    logger.warning("触发限流（403），%d 秒后重试…", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF * attempt
            logger.warning("第 %d/%d 次尝试失败：%s，%d 秒后重试…", attempt, MAX_RETRIES, exc, wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"All {MAX_RETRIES} attempts failed for {url}") from last_exc


# ── Primary strategy: recursive tree ────────────────────────────────────

async def fetch_full_tree(session: aiohttp.ClientSession) -> dict:
    """Fetch the full recursive git tree for the branch."""
    url = f"{TREE_URL}/{BRANCH}"
    logger.info("正在获取递归树：%s …", url)
    return await _fetch_json(session, url, params={"recursive": "1"})


def extract_mdx_files(tree_nodes: list) -> List[str]:
    """Return sorted .mdx paths under DOCS_BASE from tree node list."""
    return sorted(
        node["path"]
        for node in tree_nodes
        if node.get("type") == "blob"
        and node["path"].startswith(DOCS_BASE + "/")
        and node["path"].endswith(".mdx")
    )


# ── Fallback strategy: per-section tree fetches ─────────────────────────

async def _resolve_tree_sha(session: aiohttp.ClientSession) -> str:
    """Resolve the commit SHA for BRANCH, then its root tree SHA."""
    ref_url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/git/ref/heads/{BRANCH}"
    ref_data = await _fetch_json(session, ref_url)
    commit_sha = ref_data["object"]["sha"]

    commit_url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/git/commits/{commit_sha}"
    commit_data = await _fetch_json(session, commit_url)
    return commit_data["tree"]["sha"]


async def _walk_to_subtree(
    session: aiohttp.ClientSession, root_sha: str, path_parts: List[str]
) -> str:
    """Walk from root tree SHA down the given path components, returning the
    SHA of the final subtree."""
    sha = root_sha
    for part in path_parts:
        data = await _fetch_json(session, f"{TREE_URL}/{sha}")
        entry = next((e for e in data["tree"] if e["path"] == part and e["type"] == "tree"), None)
        if entry is None:
            raise RuntimeError(f"子树 '{part}' 未找到于 {sha}")
        sha = entry["sha"]
    return sha


async def _fetch_section_tree(
    session: aiohttp.ClientSession, docs_sha: str, section: str
) -> List[str]:
    """Fetch recursive tree for a single section directory."""
    data = await _fetch_json(session, f"{TREE_URL}/{docs_sha}")
    entry = next((e for e in data["tree"] if e["path"] == section and e["type"] == "tree"), None)
    if entry is None:
        return []

    section_data = await _fetch_json(
        session, f"{TREE_URL}/{entry['sha']}", params={"recursive": "1"}
    )
    prefix = f"{DOCS_BASE}/{section}/"
    return sorted(
        f"{prefix}{node['path']}"
        for node in section_data.get("tree", [])
        if node.get("type") == "blob" and node["path"].endswith(".mdx")
    )


async def fetch_sections_individually(session: aiohttp.ClientSession) -> List[str]:
    """Fallback: discover sections, then fetch each section tree."""
    logger.info("递归树被截断，切换为按分区抓取 …")

    root_sha = await _resolve_tree_sha(session)
    docs_sha = await _walk_to_subtree(session, root_sha, DOCS_BASE.split("/"))

    # List sections (top-level dirs under DOCS_BASE)
    docs_tree = await _fetch_json(session, f"{TREE_URL}/{docs_sha}")
    sections = [
        e["path"] for e in docs_tree["tree"] if e["type"] == "tree"
    ]
    logger.info("待单独扫描分区数：%d", len(sections))

    all_files: List[str] = []
    for i, section in enumerate(sections, 1):
        logger.info("  [%d/%d] %s", i, len(sections), section)
        try:
            files = await _fetch_section_tree(session, docs_sha, section)
            all_files.extend(files)
        except Exception as exc:
            logger.warning("  跳过分区 %s: %s", section, exc)

    return sorted(all_files)


# ── Grouping ────────────────────────────────────────────────────────────

def group_by_section(paths: List[str]) -> Dict[str, List[str]]:
    """Group file paths by their top-level section directory."""
    groups: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        section = _section_from_path(path)
        if section:
            groups[section].append(path)
    # Sort keys and values
    return {k: sorted(v) for k, v in sorted(groups.items())}


# ── Main ────────────────────────────────────────────────────────────────

async def build_file_list() -> Dict[str, List[str]]:
    """Build the complete file list for all sections."""
    async with aiohttp.ClientSession() as session:
        tree_data = await fetch_full_tree(session)

        truncated = tree_data.get("truncated", False)
        tree_nodes = tree_data.get("tree", [])
        logger.info(
            "Tree response: %d nodes, truncated=%s", len(tree_nodes), truncated
        )

        if truncated:
            logger.warning("递归树结果被截断，使用按分区回退方案")
            mdx_files = await fetch_sections_individually(session)
        else:
            mdx_files = extract_mdx_files(tree_nodes)

    result = group_by_section(mdx_files)

    # Statistics
    total = sum(len(v) for v in result.values())
    logger.info("发现完成：共 %d 个 .mdx 文件，覆盖 %d 个分区", total, len(result))
    top5 = sorted(result.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
    for section, files in top5:
        logger.info("  %-30s %d files", section, len(files))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover all .mdx files in the cloudflare-docs repo via the GitHub API."
    )
    parser.add_argument(
        "--output", "-o",
        default=OUTPUT_PATH,
        help=f"Output JSON path (default: {OUTPUT_PATH})",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    logger.info("开始构建文件列表：%s/%s @ %s …", REPO_OWNER, REPO_NAME, BRANCH)

    file_list = await build_file_list()

    total = sum(len(v) for v in file_list.values())
    logger.info("总计：%d 个文件，%d 个分区", total, len(file_list))

    out = args.output
    out_dir = os.path.dirname(os.path.abspath(out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(file_list, f, indent=2, ensure_ascii=False)
    logger.info("已写入 %s", out)


if __name__ == "__main__":
    asyncio.run(main())
