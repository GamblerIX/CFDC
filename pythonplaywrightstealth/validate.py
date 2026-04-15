#!/usr/bin/env python3
"""
validate.py – Comprehensive validation of CFDC i18n output.

Checks key alignment, empty values, coverage against file_list.json,
translation quality, and generates statistics.  Prints a human-readable
report to stdout and writes a detailed JSON report file.

Usage:
    python validate.py
    python validate.py --verbose
    python validate.py --en-path ../i18n/en.json --zh-path ../i18n/zh-cn.json
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Helpers ─────────────────────────────────────────────────────────────────


def load_json(path: str) -> dict:
    """Read a JSON file and return its contents."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    """Write dict to a JSON file, creating parent directories if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _count_text_entries(page: dict) -> int:
    """Count the number of text entries (strings + list items) in a page."""
    count = 0
    for value in page.values():
        if isinstance(value, str):
            count += 1
        elif isinstance(value, list):
            count += len(value)
    return count


def _iter_text_entries(page: dict) -> List[Tuple[str, str]]:
    """Yield (sub_key, text) pairs for every text entry in a page."""
    entries: List[Tuple[str, str]] = []
    for key, value in page.items():
        if isinstance(value, str):
            entries.append((key, value))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    entries.append((f"{key}[{i}]", item))
    return entries


def _ascii_ratio(text: str) -> float:
    """Return the fraction of characters that are ASCII letters."""
    if not text:
        return 0.0
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    total_alpha = sum(1 for c in text if c.isalpha())
    return ascii_chars / total_alpha if total_alpha > 0 else 0.0


def _strip_protected_terms(text: str, terms: Set[str]) -> str:
    """Remove protected terms from text before measuring ASCII ratio."""
    result = text
    for term in sorted(terms, key=len, reverse=True):
        result = result.replace(term, "")
    return result


# ── Check 1: Key Alignment ─────────────────────────────────────────────────


def check_key_alignment(
    en: dict, zh: dict
) -> Dict[str, Any]:
    """Verify all top-level and sub-keys match between en and zh."""
    en_keys = set(en.keys())
    zh_keys = set(zh.keys())

    only_en = sorted(en_keys - zh_keys)
    only_zh = sorted(zh_keys - en_keys)

    sub_mismatches: List[Dict[str, Any]] = []
    for page_key in sorted(en_keys & zh_keys):
        en_sub = set(en[page_key].keys()) if isinstance(en[page_key], dict) else set()
        zh_sub = set(zh[page_key].keys()) if isinstance(zh[page_key], dict) else set()
        if en_sub != zh_sub:
            sub_mismatches.append({
                "page": page_key,
                "only_in_en": sorted(en_sub - zh_sub),
                "only_in_zh": sorted(zh_sub - en_sub),
            })

    passed = len(only_en) == 0 and len(only_zh) == 0 and len(sub_mismatches) == 0
    return {
        "passed": passed,
        "only_in_en": only_en,
        "only_in_zh": only_zh,
        "sub_key_mismatches": sub_mismatches,
    }


# ── Check 2: Empty Value Detection ─────────────────────────────────────────


def check_empty_values(
    en: dict, zh: dict
) -> Dict[str, Any]:
    """Find keys with empty/null Chinese values or [EN] prefixed values."""
    empty_paths: List[str] = []
    en_prefix_paths: List[str] = []

    common_keys = set(en.keys()) & set(zh.keys())
    for page_key in sorted(common_keys):
        en_page = en[page_key]
        zh_page = zh[page_key]
        if not isinstance(en_page, dict) or not isinstance(zh_page, dict):
            continue

        en_entries = _iter_text_entries(en_page)
        zh_entries = dict(_iter_text_entries(zh_page))

        for sub_key, en_val in en_entries:
            zh_val = zh_entries.get(sub_key, "")
            full_path = f"{page_key} → {sub_key}"

            if en_val and en_val.strip():
                if not zh_val or not zh_val.strip():
                    empty_paths.append(full_path)
                elif zh_val.startswith("[EN] "):
                    en_prefix_paths.append(full_path)

    return {
        "empty_count": len(empty_paths),
        "en_prefix_count": len(en_prefix_paths),
        "empty_samples": empty_paths[:20],
        "en_prefix_samples": en_prefix_paths[:20],
    }


# ── Check 3: Coverage Report ───────────────────────────────────────────────


def _file_path_to_url(file_path: str) -> str:
    """Convert a file_list.json path to an en.json key.

    ``src/content/docs/1.1.1.1/encryption/index.mdx`` → ``/1.1.1.1/encryption/``
    ``src/content/docs/agents/api-reference/agents-api.mdx`` →
        ``/agents/api-reference/agents-api/``
    """
    # Strip leading prefix
    path = file_path
    prefix = "src/content/docs/"
    if path.startswith(prefix):
        path = path[len(prefix):]

    # Remove .mdx extension
    if path.endswith(".mdx"):
        path = path[:-4]
    elif path.endswith(".md"):
        path = path[:-3]

    # Remove trailing /index
    if path.endswith("/index"):
        path = path[: -len("/index")]

    return f"/{path}/"


def check_coverage(
    en: dict, file_list_path: str
) -> Optional[Dict[str, Any]]:
    """Compare expected pages from file_list.json vs actual pages in en.json."""
    if not os.path.exists(file_list_path):
        return None

    file_list = load_json(file_list_path)
    expected_urls: Set[str] = set()
    for paths in file_list.values():
        for fp in paths:
            expected_urls.add(_file_path_to_url(fp))

    actual_urls = set(en.keys())
    missing = sorted(expected_urls - actual_urls)
    extra = sorted(actual_urls - expected_urls)
    found = len(expected_urls & actual_urls)
    total_expected = len(expected_urls)
    coverage_pct = (found / total_expected * 100) if total_expected > 0 else 0.0

    return {
        "total_expected": total_expected,
        "total_found": found,
        "missing_count": len(missing),
        "extra_count": len(extra),
        "coverage_pct": round(coverage_pct, 2),
        "missing_paths": missing[:30],
        "extra_paths": extra[:30],
    }


# ── Check 4: Translation Quality ───────────────────────────────────────────


def check_translation_quality(
    en: dict, zh: dict, protected_terms: Set[str]
) -> Dict[str, Any]:
    """Run translation quality checks on Chinese output."""
    english_residual: List[Dict[str, Any]] = []
    bad_translations: List[Dict[str, str]] = []
    long_untranslated: List[Dict[str, str]] = []
    zh_value_counter: Counter = Counter()

    # Known bad translations for protected terms
    bad_translation_map = {
        "Workers": "工人",
        "Pages": "页面",
        "Stream": "溪流",
        "Access": "使用权",
        "Gateway": "网关",
        "Cache": "缓存",
        "Tunnel": "隧道",
        "Images": "图片",
        "Queues": "队列",
    }

    common_keys = set(en.keys()) & set(zh.keys())
    for page_key in sorted(common_keys):
        en_page = en[page_key]
        zh_page = zh[page_key]
        if not isinstance(en_page, dict) or not isinstance(zh_page, dict):
            continue

        en_entries = _iter_text_entries(en_page)
        zh_entries = dict(_iter_text_entries(zh_page))

        for sub_key, en_val in en_entries:
            zh_val = zh_entries.get(sub_key, "")
            if not zh_val:
                continue

            full_path = f"{page_key} → {sub_key}"

            # Track values for duplicate detection
            if zh_val.strip():
                zh_value_counter[zh_val] += 1

            # English residual check
            stripped = _strip_protected_terms(zh_val, protected_terms)
            ratio = _ascii_ratio(stripped)
            if ratio > 0.5 and len(stripped.strip()) > 10:
                english_residual.append({
                    "path": full_path,
                    "ascii_ratio": round(ratio, 2),
                    "sample": zh_val[:120],
                })

            # Long untranslated text (>100 chars, still mostly English)
            if len(en_val) > 100 and en_val == zh_val:
                long_untranslated.append({
                    "path": full_path,
                    "length": len(en_val),
                    "sample": en_val[:120],
                })

        # Protected term verification (sample check on title)
        en_title = en_page.get("title", "")
        zh_title = zh_page.get("title", "")
        if en_title and zh_title:
            for term, bad in bad_translation_map.items():
                if term in en_title and bad in zh_title:
                    bad_translations.append({
                        "page": page_key,
                        "term": term,
                        "bad_translation": bad,
                        "zh_title": zh_title,
                    })

    # Duplicate values (appearing 3+ times across different keys)
    duplicates = [
        {"value": val[:100], "count": cnt}
        for val, cnt in zh_value_counter.most_common(20)
        if cnt >= 3 and len(val.strip()) > 5
    ]

    return {
        "english_residual_count": len(english_residual),
        "english_residual_samples": english_residual[:20],
        "bad_protected_terms": bad_translations,
        "duplicate_values": duplicates[:15],
        "long_untranslated_count": len(long_untranslated),
        "long_untranslated_samples": long_untranslated[:20],
    }


# ── Check 5: Statistics Summary ────────────────────────────────────────────


def compute_statistics(
    en: dict, zh: dict
) -> Dict[str, Any]:
    """Compute overall statistics about the translation output."""
    total_pages = len(en)
    total_entries = 0
    translated = 0
    untranslated = 0
    empty = 0

    common_keys = set(en.keys()) & set(zh.keys())
    for page_key in common_keys:
        en_page = en[page_key]
        zh_page = zh[page_key]
        if not isinstance(en_page, dict) or not isinstance(zh_page, dict):
            continue

        en_entries = _iter_text_entries(en_page)
        zh_entries = dict(_iter_text_entries(zh_page))

        for sub_key, en_val in en_entries:
            total_entries += 1
            zh_val = zh_entries.get(sub_key, "")

            if not zh_val or not zh_val.strip():
                empty += 1
            elif zh_val == en_val:
                untranslated += 1
            else:
                translated += 1

    avg_per_page = round(total_entries / total_pages, 1) if total_pages > 0 else 0

    return {
        "total_pages": total_pages,
        "total_entries": total_entries,
        "translated": translated,
        "untranslated": untranslated,
        "empty": empty,
        "avg_entries_per_page": avg_per_page,
    }


# ── Report Printer ──────────────────────────────────────────────────────────


def print_report(report: dict, verbose: bool = False) -> None:
    """Print a human-readable validation report."""
    print()
    print("=" * 70)
    print("  CFDC Validation Report")
    print("=" * 70)

    # ── Key Alignment ───────────────────────────────────────────────────
    alignment = report["key_alignment"]
    status = "✅ PASS" if alignment["passed"] else "❌ FAIL"
    print(f"\n{'─' * 70}")
    print(f"  1. Key Alignment: {status}")
    print(f"{'─' * 70}")
    print(f"  Pages only in en.json:   {len(alignment['only_in_en'])}")
    print(f"  Pages only in zh-cn.json: {len(alignment['only_in_zh'])}")
    print(f"  Sub-key mismatches:       {len(alignment['sub_key_mismatches'])}")
    if verbose:
        for p in alignment["only_in_en"][:10]:
            print(f"    [en only] {p}")
        for p in alignment["only_in_zh"][:10]:
            print(f"    [zh only] {p}")
        for m in alignment["sub_key_mismatches"][:10]:
            print(f"    [sub-key] {m['page']}: en={m['only_in_en']} zh={m['only_in_zh']}")

    # ── Empty Values ────────────────────────────────────────────────────
    empties = report["empty_values"]
    print(f"\n{'─' * 70}")
    print("  2. Empty Value Detection")
    print(f"{'─' * 70}")
    print(f"  Empty Chinese values:     {empties['empty_count']}")
    print(f"  [EN] prefixed values:     {empties['en_prefix_count']}")
    if verbose:
        for p in empties["empty_samples"][:10]:
            print(f"    [empty] {p}")
        for p in empties["en_prefix_samples"][:10]:
            print(f"    [EN]    {p}")

    # ── Coverage ────────────────────────────────────────────────────────
    coverage = report.get("coverage")
    print(f"\n{'─' * 70}")
    print("  3. Coverage Report")
    print(f"{'─' * 70}")
    if coverage is None:
        print("  ⚠️  file_list.json not found – skipped")
    else:
        print(f"  Expected pages:  {coverage['total_expected']}")
        print(f"  Found pages:     {coverage['total_found']}")
        print(f"  Missing pages:   {coverage['missing_count']}")
        print(f"  Extra pages:     {coverage['extra_count']}")
        print(f"  Coverage:        {coverage['coverage_pct']}%")
        if verbose and coverage["missing_paths"]:
            print("  Missing:")
            for p in coverage["missing_paths"][:15]:
                print(f"    - {p}")
        if verbose and coverage["extra_paths"]:
            print("  Extra:")
            for p in coverage["extra_paths"][:15]:
                print(f"    + {p}")

    # ── Translation Quality ─────────────────────────────────────────────
    quality = report["translation_quality"]
    print(f"\n{'─' * 70}")
    print("  4. Translation Quality")
    print(f"{'─' * 70}")
    print(f"  English residual (>50% ASCII): {quality['english_residual_count']}")
    print(f"  Bad protected-term translations: {len(quality['bad_protected_terms'])}")
    print(f"  Duplicate values (3+ occurrences): {len(quality['duplicate_values'])}")
    print(f"  Long untranslated (>100 chars):  {quality['long_untranslated_count']}")
    if verbose:
        if quality["english_residual_samples"]:
            print("  English residual samples:")
            for e in quality["english_residual_samples"][:10]:
                print(f"    [{e['ascii_ratio']}] {e['path']}")
                print(f"           {e['sample']}")
        if quality["bad_protected_terms"]:
            print("  Bad protected-term translations:")
            for b in quality["bad_protected_terms"]:
                print(f"    {b['page']}: '{b['term']}' → '{b['bad_translation']}' in \"{b['zh_title']}\"")
        if quality["duplicate_values"]:
            print("  Top duplicate values:")
            for d in quality["duplicate_values"][:10]:
                print(f"    [{d['count']}x] {d['value']}")
        if quality["long_untranslated_samples"]:
            print("  Long untranslated samples:")
            for u in quality["long_untranslated_samples"][:10]:
                print(f"    [{u['length']} chars] {u['path']}")

    # ── Statistics ──────────────────────────────────────────────────────
    stats = report["statistics"]
    print(f"\n{'─' * 70}")
    print("  5. Statistics Summary")
    print(f"{'─' * 70}")
    print(f"  Total pages:          {stats['total_pages']}")
    print(f"  Total text entries:   {stats['total_entries']}")
    print(f"  Translated:           {stats['translated']}")
    print(f"  Untranslated:         {stats['untranslated']}")
    print(f"  Empty:                {stats['empty']}")
    print(f"  Avg entries/page:     {stats['avg_entries_per_page']}")

    # ── Final Result ────────────────────────────────────────────────────
    critical_pass = alignment["passed"]
    print(f"\n{'=' * 70}")
    if critical_pass:
        print("  Result: ✅ ALL CRITICAL CHECKS PASSED")
    else:
        print("  Result: ❌ CRITICAL CHECKS FAILED (key alignment issues)")
    print(f"{'=' * 70}")
    print()


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate CFDC i18n output files and generate quality reports."
    )
    parser.add_argument(
        "--en-path", default=config.EN_JSON_PATH,
        help="Path to English JSON (default: from config)",
    )
    parser.add_argument(
        "--zh-path", default=config.ZH_CN_JSON_PATH,
        help="Path to Chinese JSON (default: from config)",
    )
    parser.add_argument(
        "--file-list", default=os.path.join(SCRIPT_DIR, "file_list.json"),
        help="Path to file_list.json (default: script dir)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show detailed lists of issues",
    )
    args = parser.parse_args()

    # ── Load data ───────────────────────────────────────────────────────
    logger.info("加载英文 JSON：%s", args.en_path)
    en = load_json(args.en_path)
    logger.info("加载中文 JSON：%s", args.zh_path)
    zh = load_json(args.zh_path)

    # ── Run checks ──────────────────────────────────────────────────────
    logger.info("正在执行校验 …")

    report: Dict[str, Any] = {
        "key_alignment": check_key_alignment(en, zh),
        "empty_values": check_empty_values(en, zh),
        "coverage": check_coverage(en, args.file_list),
        "translation_quality": check_translation_quality(
            en, zh, config.NO_TRANSLATE_TERMS
        ),
        "statistics": compute_statistics(en, zh),
    }

    # ── Output ──────────────────────────────────────────────────────────
    print_report(report, verbose=args.verbose)

    report_path = config.VALIDATION_REPORT_PATH
    save_json(report, report_path)
    logger.info("详细 JSON 报告已写入 %s", report_path)

    # ── Exit code ───────────────────────────────────────────────────────
    if not report["key_alignment"]["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
