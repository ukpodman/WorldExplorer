"""Interface translations.

Strings are keyed by their English text. Templates are translated first and
then filled, so values (country names, capitals…) are never parsed back out
of rendered sentences. Canonical quiz data and answers stay in English.
"""
from __future__ import annotations

import json
import string
from pathlib import Path

_DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "translations.json").read_text(encoding="utf-8"))
LANGUAGES: tuple[str, ...] = tuple(_DATA["languages"])
DEFAULT_LANGUAGE = LANGUAGES[0]
STRINGS: dict[str, list[str]] = _DATA["strings"]

# Template fields whose *values* are themselves UI vocabulary (e.g. "capital", "Europe").
TRANSLATED_FIELDS = frozenset({"role", "continent", "title", "kind", "difficulty", "category", "area", "hint"})

_formatter = string.Formatter()


def translate(text, language: str = DEFAULT_LANGUAGE, /, **fields):
    """Translate `text` (and any vocabulary fields), then fill in `fields`."""
    if not isinstance(text, str):
        return text
    idx = LANGUAGES.index(language) - 1 if language in LANGUAGES else -1
    if idx >= 0:
        text = STRINGS.get(text, [text] * len(LANGUAGES))[idx]
        fields = {k: translate(v, language) if k in TRANSLATED_FIELDS else v for k, v in fields.items()}
    return _formatter.vformat(text, (), fields) if fields else text


def render_parts(parts, language: str = DEFAULT_LANGUAGE) -> str:
    """Render a sequence of (template, fields) pairs produced by the quiz engine."""
    joiner = "" if language.startswith("中文") else " "
    return joiner.join(translate(tpl, language, **params) for tpl, params in parts)


def missing_translations() -> list[str]:
    """Keys with a missing or empty entry for any language (used by tests)."""
    expected = len(LANGUAGES) - 1
    return [k for k, v in STRINGS.items() if len(v) != expected or not all(v)]
