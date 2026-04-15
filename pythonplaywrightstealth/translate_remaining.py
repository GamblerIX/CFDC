#!/usr/bin/env python3
"""translate_remaining.py：并发翻译 zh-cn.json 中仍带 [EN] 前缀的条目。"""

import argparse
import json
import logging
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional, Tuple

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("translate_remaining")

_NO_TRANSLATE_SORTED = sorted(config.NO_TRANSLATE_TERMS, key=len, reverse=True)
_TERMS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _NO_TRANSLATE_SORTED) + r")\b",
    re.IGNORECASE,
)
_EXTRA_PROTECT = [
    re.compile(r"https?://\S+"),
    re.compile(r"(?<!\w)/[\w./_-]+"),
    re.compile(r"\b\w+\.\w+\.\w[\w.]*\b"),
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)(?:[-+]\S+)?\b"),
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),
    re.compile(r"`[^`]+`"),
    re.compile(r"\{[^}]+\}"),
    re.compile(r"--[\w-]+"),
]


def _protect(text: str) -> Tuple[str, List[str]]:
    protected: List[str] = []

    def _repl(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return f"\u27e6{idx}\u27e7"

    text = _TERMS_RE.sub(_repl, text)
    for pat in _EXTRA_PROTECT:
        text = pat.sub(_repl, text)
    return text, protected


def _restore(text: str, protected: List[str]) -> str:
    for idx, term in enumerate(protected):
        text = text.replace(f"\u27e6{idx}\u27e7", term)
    return text


def _has_artifacts(text: str) -> bool:
    return bool(re.search(r"\u27e6\d+\u27e7", text))


def _get_translator():
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source="en", target="zh-CN")


def _translate_one_raw(text: str) -> Optional[str]:
    translator = _get_translator()
    for attempt in range(5):
        try:
            result = translator.translate(text)
            if result and isinstance(result, str) and result.strip():
                return result
        except Exception:
            if attempt < 4:
                time.sleep(2.0 * (attempt + 1))
    return None


def translate_protected(text: str) -> Optional[str]:
    protected_text, protected = _protect(text)
    translated = _translate_one_raw(protected_text)
    if translated is None:
        return None
    restored = _restore(translated, protected)
    if _has_artifacts(restored):
        plain = _translate_one_raw(text)
        if plain and not _has_artifacts(plain):
            return plain
        return None
    return restored


def collect_en_entries(zh: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, int, str]]:
    entries = []
    for page_key, page in zh.items():
        for sub_key, val in page.items():
            if isinstance(val, str) and val.startswith("[EN] "):
                entries.append((page_key, sub_key, -1, val[5:]))
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    if isinstance(item, str) and item.startswith("[EN] "):
                        entries.append((page_key, sub_key, i, item[5:]))
    return entries


def apply_translation(zh: Dict[str, Dict[str, Any]], page_key: str, sub_key: str, list_idx: int, translated: str) -> None:
    if list_idx == -1:
        zh[page_key][sub_key] = translated
    else:
        zh[page_key][sub_key][list_idx] = translated


def _worker(text: str) -> Tuple[str, Optional[str]]:
    return text, translate_protected(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="翻译 zh-cn.json 中剩余的 [EN] 条目")
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不执行翻译")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=300,
        help="翻译阶段最长运行时间（分钟，0 为不限制）",
    )
    args = parser.parse_args()

    with open(config.ZH_CN_JSON_PATH, "r", encoding="utf-8") as f:
        zh = json.load(f)

    entries = collect_en_entries(zh)
    logger.info("检测到 [EN] 条目：%d", len(entries))
    unique_texts = list({e[3] for e in entries})
    logger.info("去重后待翻译文本：%d", len(unique_texts))

    if args.dry_run or not unique_texts:
        return

    results: Dict[str, str] = {}
    done = 0
    failed = 0
    start = time.time()
    deadline = None if args.max_runtime_minutes == 0 else start + args.max_runtime_minutes * 60

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(_worker, t): t for t in unique_texts}
        while pending:
            if deadline is not None and time.time() >= deadline:
                logger.warning("达到最长运行时长，提前结束翻译")
                for future in pending:
                    future.cancel()
                break

            completed, _ = wait(pending.keys(), timeout=1, return_when=FIRST_COMPLETED)
            if not completed:
                continue

            for future in completed:
                text = pending.pop(future)
                try:
                    _, translated = future.result()
                except Exception:
                    translated = None

                done += 1
                if translated is None:
                    failed += 1
                else:
                    results[text] = translated

                if done % 200 == 0 or done == len(unique_texts):
                    elapsed = max(1e-6, time.time() - start)
                    rate = done / elapsed
                    logger.info("进度：%d/%d，失败：%d，速度：%.2f 条/秒", done, len(unique_texts), failed, rate)

    applied = 0
    still_en = 0
    for page_key, sub_key, list_idx, eng in entries:
        translation = results.get(eng)
        if translation is None:
            still_en += 1
            continue
        apply_translation(zh, page_key, sub_key, list_idx, translation)
        applied += 1

    logger.info("已应用：%d，仍未翻译：%d", applied, still_en)
    with open(config.ZH_CN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(zh, f, indent=2, ensure_ascii=False)
    logger.info("已写回 zh-cn.json")


if __name__ == "__main__":
    main()
