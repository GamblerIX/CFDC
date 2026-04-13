"""
translator.py – Translate extracted English entries to Chinese.

Uses deep-translator (Google Translate free tier).
Respects rate limits and preserves technical terms.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Union

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]

import config

logger = logging.getLogger(__name__)

# Compiled regex for protecting terms from translation
_PROTECT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(config.NO_TRANSLATE_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Placeholder template (unlikely to appear in real text)
_PH_TEMPLATE = "⟦{}⟧"


def _protect_terms(text: str) -> tuple[str, list[str]]:
    """Replace protected terms with numbered placeholders."""
    protected: list[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return _PH_TEMPLATE.format(idx)

    return _PROTECT_RE.sub(_replace, text), protected


def _restore_terms(text: str, protected: list[str]) -> str:
    """Restore protected terms from placeholders."""
    for idx, term in enumerate(protected):
        placeholder = _PH_TEMPLATE.format(idx)
        text = text.replace(placeholder, term)
    return text


def _translate_single(text: str) -> str:
    """Translate a single string, protecting technical terms."""
    if not text or not text.strip():
        return text

    # Skip very short or purely technical strings
    if len(text.strip()) <= 2:
        return text

    protected_text, protected_terms = _protect_terms(text)

    try:
        translated = GoogleTranslator(source="en", target="zh-CN").translate(protected_text)
        if translated is None:
            return text
        return _restore_terms(translated, protected_terms)
    except Exception as exc:
        logger.warning("Translation failed for '%s...': %s", text[:50], exc)
        return text


def translate_entries(en_entries: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Translate all extracted entries from English to Chinese.
    Returns a new dict with the same structure but translated values.
    """
    zh_entries: Dict[str, Dict[str, Any]] = {}
    total_pages = len(en_entries)

    for idx, (path, page_data) in enumerate(en_entries.items(), 1):
        logger.info("Translating page %d/%d: %s", idx, total_pages, path)
        zh_page: Dict[str, Any] = {}

        for key, value in page_data.items():
            if isinstance(value, str):
                zh_page[key] = _translate_single(value)
                time.sleep(config.TRANSLATE_DELAY)
            elif isinstance(value, list):
                translated_list = []
                for item in value:
                    if isinstance(item, str):
                        translated_list.append(_translate_single(item))
                        time.sleep(config.TRANSLATE_DELAY)
                    else:
                        translated_list.append(item)
                zh_page[key] = translated_list
            else:
                zh_page[key] = value

        zh_entries[path] = zh_page

    return zh_entries
