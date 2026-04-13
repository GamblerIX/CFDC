#!/usr/bin/env python3
"""
translate_remaining.py – Translate all [EN]-prefixed entries using Google Translate.

Uses concurrent workers for maximum throughput while respecting rate limits.

Usage:
    python translate_remaining.py                   # Translate all [EN] entries
    python translate_remaining.py --workers 10      # Custom concurrency
    python translate_remaining.py --dry-run          # Count without translating
"""

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("translate_remaining")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
CACHE_PATH = os.path.join(CACHE_DIR, "translation_cache.json")

# ── Term protection ────────────────────────────────────────────────────────

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


# ── Translation cache (thread-safe) ──────────────────────────────────────

_cache_lock = threading.Lock()
_cache: Dict[str, str] = {}


def load_cache() -> None:
    global _cache
    if os.path.isfile(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)


def save_cache() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with _cache_lock:
        snapshot = dict(_cache)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)


# ── Per-thread GoogleTranslator instances ────────────────────────────────

_tl = threading.local()


def _get_translator():
    if not hasattr(_tl, "translator"):
        from deep_translator import GoogleTranslator
        _tl.translator = GoogleTranslator(source="en", target="zh-CN")
    return _tl.translator


def _translate_one_raw(text: str) -> Optional[str]:
    """Translate a single string without protection. Returns None on failure."""
    for attempt in range(5):
        try:
            result = _get_translator().translate(text)
            if result and isinstance(result, str) and result.strip():
                return result
        except Exception:
            wait = 2.0 * (attempt + 1)
            if attempt < 4:
                time.sleep(wait)
    return None


def translate_protected(text: str) -> Optional[str]:
    """Translate with term protection. Returns None on failure."""
    protected_text, protected = _protect(text)
    translated = _translate_one_raw(protected_text)
    if translated is None:
        return None
    restored = _restore(translated, protected)
    if _has_artifacts(restored):
        # Retry without protection
        plain = _translate_one_raw(text)
        if plain and not _has_artifacts(plain):
            return plain
        return None
    return restored


# ── Worker function ──────────────────────────────────────────────────────

def _worker(text: str) -> Tuple[str, Optional[str]]:
    """Thread worker: translates one text, returns (original, translation)."""
    # Check cache first
    with _cache_lock:
        if text in _cache:
            return text, _cache[text]

    result = translate_protected(text)
    if result is not None:
        with _cache_lock:
            _cache[text] = result
    return text, result


# ── Collect entries ──────────────────────────────────────────────────────

def collect_en_entries(
    zh: Dict[str, Dict[str, Any]]
) -> List[Tuple[str, str, int, str]]:
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


def apply_translation(
    zh: Dict[str, Dict[str, Any]],
    page_key: str, sub_key: str, list_idx: int, translated: str,
) -> None:
    if list_idx == -1:
        zh[page_key][sub_key] = translated
    else:
        zh[page_key][sub_key][list_idx] = translated


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate remaining [EN]-prefixed entries via Google Translate"
    )
    parser.add_argument("--workers", type=int, default=8, help="Concurrent workers")
    parser.add_argument("--dry-run", action="store_true", help="Count entries without translating")
    parser.add_argument("--save-interval", type=int, default=500, help="Save cache every N items")
    args = parser.parse_args()

    logger.info("Loading zh-cn.json …")
    with open(config.ZH_CN_JSON_PATH, "r", encoding="utf-8") as f:
        zh = json.load(f)

    entries = collect_en_entries(zh)
    logger.info("Found %d [EN]-prefixed entries", len(entries))

    unique_texts = list(set(e[3] for e in entries))
    logger.info("Unique texts: %d", len(unique_texts))

    if args.dry_run:
        return

    if not unique_texts:
        logger.info("Nothing to translate!")
        return

    load_cache()
    uncached = [t for t in unique_texts if t not in _cache]
    logger.info("Cached: %d, need translation: %d", len(unique_texts) - len(uncached), len(uncached))

    if not uncached:
        logger.info("All texts already cached — applying…")
    else:
        logger.info("Translating %d texts with %d workers …", len(uncached), args.workers)
        done = 0
        failed = 0
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_worker, t): t for t in uncached}
            for future in as_completed(futures):
                text, result = future.result()
                done += 1
                if result is None:
                    failed += 1

                if done % 200 == 0 or done == len(uncached):
                    elapsed = time.time() - start_time
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (len(uncached) - done) / rate if rate > 0 else 0
                    logger.info(
                        "Progress: %d/%d (%.1f/s, failed: %d, ETA: %.0fm)",
                        done, len(uncached), rate, failed, eta / 60,
                    )

                if done % args.save_interval == 0:
                    save_cache()

        save_cache()
        elapsed = time.time() - start_time
        logger.info(
            "Done: %d translated, %d failed in %.1fs (%.1f/s)",
            done - failed, failed, elapsed, done / elapsed if elapsed > 0 else 0,
        )

    # Apply translations
    applied = 0
    still_en = 0
    for page_key, sub_key, list_idx, eng in entries:
        with _cache_lock:
            translation = _cache.get(eng)
        if translation is not None:
            apply_translation(zh, page_key, sub_key, list_idx, translation)
            applied += 1
        else:
            still_en += 1

    logger.info("Applied %d, still untranslated: %d", applied, still_en)

    with open(config.ZH_CN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(zh, f, indent=2, ensure_ascii=False)
    logger.info("Saved zh-cn.json (%d pages)", len(zh))


if __name__ == "__main__":
    main()
