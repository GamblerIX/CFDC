#!/usr/bin/env python3
"""诊断页面词条覆盖率：验证页面英文文本有多少能被 userscript 词典翻译。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = REPO_ROOT / "i18n"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_pairs(en_node: Any, zh_node: Any) -> Iterable[Tuple[str, str]]:
    if isinstance(en_node, str) and isinstance(zh_node, str):
        yield en_node.strip(), zh_node.strip()
        return
    if isinstance(en_node, list) and isinstance(zh_node, list):
        for e, z in zip(en_node, zh_node):
            yield from iter_pairs(e, z)
        return
    if isinstance(en_node, dict) and isinstance(zh_node, dict):
        for key, value in en_node.items():
            if key in zh_node:
                yield from iter_pairs(value, zh_node[key])


def build_map(en_path: Path, zh_path: Path) -> Dict[str, str]:
    en = load_json(en_path)
    zh = load_json(zh_path)
    mapping: Dict[str, str] = {}
    for source, translated in iter_pairs(en, zh):
        if source and translated and not translated.startswith("[EN]"):
            mapping.setdefault(source, translated)
    return mapping


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_page_texts(url: str) -> Set[str]:
    headers = {"User-Agent": "Mozilla/5.0 (CFDC coverage checker)"}
    html = requests.get(url, headers=headers, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    main = soup.select_one("main[data-pagefind-body]") or soup.select_one("main") or soup
    texts: Set[str] = set()
    for node in main.find_all(string=True):
        parent = node.parent
        if parent and parent.name in {"script", "style", "noscript", "code", "pre", "textarea"}:
            continue
        normalized = normalize_text(str(node))
        if not normalized:
            continue
        texts.add(normalized)
    return texts


def run_check(urls: List[str], sample_untranslated: int) -> None:
    userscript_map = build_map(I18N_DIR / "userscript-en.json", I18N_DIR / "userscript-zh-cn.json")
    full_map = build_map(I18N_DIR / "en.json", I18N_DIR / "zh-cn.json")

    print(f"[dict] userscript_map: {len(userscript_map)}")
    print(f"[dict] full_map: {len(full_map)}")

    grand_total = 0
    grand_userscript_hits = 0
    grand_full_hits = 0

    for url in urls:
        texts = extract_page_texts(url)
        userscript_hits = [t for t in texts if t in userscript_map]
        full_hits = [t for t in texts if t in full_map]
        untranslated = [t for t in sorted(texts) if t not in userscript_map]

        grand_total += len(texts)
        grand_userscript_hits += len(userscript_hits)
        grand_full_hits += len(full_hits)

        userscript_ratio = (len(userscript_hits) / len(texts) * 100) if texts else 0
        full_ratio = (len(full_hits) / len(texts) * 100) if texts else 0

        print(f"\n[url] {url}")
        print(f"[page] text_nodes(unique): {len(texts)}")
        print(f"[page] userscript_hits: {len(userscript_hits)} ({userscript_ratio:.2f}%)")
        print(f"[page] full_hits: {len(full_hits)} ({full_ratio:.2f}%)")

        if sample_untranslated > 0:
            print(f"[page] userscript_untranslated(sample {sample_untranslated}):")
            for text in untranslated[:sample_untranslated]:
                print(f"  - {text[:200]}")

    if grand_total:
        print("\n[summary]")
        print(f"total_unique_text_nodes: {grand_total}")
        print(
            f"userscript_total_hits: {grand_userscript_hits} "
            f"({grand_userscript_hits / grand_total * 100:.2f}%)"
        )
        print(f"full_total_hits: {grand_full_hits} ({grand_full_hits / grand_total * 100:.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="检查页面文本是否被 userscript/full 词典覆盖")
    parser.add_argument(
        "urls",
        nargs="*",
        default=[
            "https://developers.cloudflare.com/",
            "https://developers.cloudflare.com/1.1.1.1/",
            "https://developers.cloudflare.com/workers/",
        ],
        help="待检查 URL 列表",
    )
    parser.add_argument("--sample-untranslated", type=int, default=8, help="每页输出未覆盖样本数量")
    args = parser.parse_args()

    run_check(args.urls, sample_untranslated=args.sample_untranslated)


if __name__ == "__main__":
    main()
