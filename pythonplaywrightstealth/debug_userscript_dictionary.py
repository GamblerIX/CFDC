#!/usr/bin/env python3
"""诊断并重建 userscript 词典。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = REPO_ROOT / "i18n"
EN_PATH = I18N_DIR / "en.json"
ZH_PATH = I18N_DIR / "zh-cn.json"
USER_EN_PATH = I18N_DIR / "userscript-en.json"
USER_ZH_PATH = I18N_DIR / "userscript-zh-cn.json"


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


def should_keep(source: str, translated: str, min_len: int, max_len: int) -> Tuple[bool, str]:
    if not source or not translated:
        return False, "empty"
    if translated.startswith("[EN]"):
        return False, "untranslated"
    if source == translated:
        return False, "same_text"
    if len(source) < min_len:
        return False, "too_short"
    if len(source) > max_len:
        return False, "too_long"
    if "\n" in source or "\n" in translated:
        return False, "multiline"
    if "http://" in source or "https://" in source:
        return False, "url"
    if re.search(r"[`{}<>]|\$\{|\}\)|\[\[|\]\]|::", source):
        return False, "code_like"
    if re.search(r"^\W+$", source):
        return False, "symbols_only"
    if re.search(r"^[0-9 .:/_\-]+$", source):
        return False, "number_like"
    return True, "kept"


def build_userscript_dict(min_len: int, max_len: int) -> Tuple[Dict[str, str], Counter[str], int]:
    en_data = load_json(EN_PATH)
    zh_data = load_json(ZH_PATH)

    excluded = Counter()
    collected: Dict[str, str] = {}
    total_pairs = 0

    for source, translated in iter_pairs(en_data, zh_data):
        total_pairs += 1
        keep, reason = should_keep(source, translated, min_len=min_len, max_len=max_len)
        if not keep:
            excluded[reason] += 1
            continue
        collected.setdefault(source, translated)

    return collected, excluded, total_pairs


def write_userscript_files(mapping: Dict[str, str]) -> None:
    payload_en = {"common": {k: k for k in mapping.keys()}}
    payload_zh = {"common": mapping}

    USER_EN_PATH.write_text(json.dumps(payload_en, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    USER_ZH_PATH.write_text(json.dumps(payload_zh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断并重建 userscript 词典")
    parser.add_argument("--write", action="store_true", help="将诊断结果写回 i18n/userscript-*.json")
    parser.add_argument("--min-len", type=int, default=2, help="最短词条长度")
    parser.add_argument("--max-len", type=int, default=120, help="最长词条长度")
    parser.add_argument("--top", type=int, default=10, help="输出排除原因前 N 项")
    args = parser.parse_args()

    current_en = load_json(USER_EN_PATH)
    current_entries = len(current_en.get("common", {})) if isinstance(current_en, dict) else 0

    mapping, excluded, total_pairs = build_userscript_dict(min_len=args.min_len, max_len=args.max_len)

    print(f"[debug] 当前 userscript-en.json 词条数: {current_entries}")
    print(f"[debug] en/zh 总 pair 数: {total_pairs}")
    print(f"[debug] 建议 userscript 词条数: {len(mapping)}")
    print("[debug] 被过滤原因（Top）:")
    for reason, count in excluded.most_common(args.top):
        print(f"  - {reason}: {count}")

    if args.write:
        write_userscript_files(mapping)
        print(f"[write] 已写入: {USER_EN_PATH}")
        print(f"[write] 已写入: {USER_ZH_PATH}")


if __name__ == "__main__":
    main()
