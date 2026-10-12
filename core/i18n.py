"""Interface translations.

Strings are keyed by their English text. Templates are translated first and
then filled, so values (country names, capitals…) are never parsed back out
of rendered sentences. Answers are stored in canonical English; only their
display is localised.

Country names come from the country dataset's own translations (German,
Spanish, Chinese and Russian). Capitals, currencies and languages keep the
dataset's English spelling.

A missing or empty translation falls back to the English text. Russian
templates choose plural forms with a format spec, e.g.
"{n} {n:plural:вопрос|вопроса|вопросов}" (one | few | many).
"""
from __future__ import annotations

import json
import string
from pathlib import Path

from .data import COUNTRIES

_DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "translations.json").read_text(encoding="utf-8"))
LANGUAGES: tuple[str, ...] = tuple(_DATA["languages"])
DEFAULT_LANGUAGE = LANGUAGES[0]
STRINGS: dict[str, list[str]] = _DATA["strings"]

# Template fields whose *values* are themselves UI vocabulary (e.g. "capital", "Europe").
TRANSLATED_FIELDS = frozenset({"role", "continent", "title", "kind", "difficulty", "category", "area", "hint",
                               "region", "status"})
# Template fields that hold country names.
NAME_FIELDS = frozenset({"name", "other", "first", "second", "third", "country"})
PLACE_NAMES: dict[str, dict[str, str]] = {
    lang: {c["name"]: c["names"].get(lang, c["name"]) for c in COUNTRIES} for lang in LANGUAGES[1:]}



def plural_form(value, forms: list[str]) -> str:
    """Russian-style plural choice (one | few | many); with two forms, English-style (one | other)."""
    try:
        n = abs(int(str(value).replace(",", "").replace("\u00a0", "").replace(" ", "").split(".")[0]))
    except ValueError:
        return forms[-1]
    if len(forms) == 2:
        return forms[0] if n == 1 else forms[1]
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


class _Formatter(string.Formatter):
    def format_field(self, value, format_spec):
        if format_spec.startswith("plural:"):
            return plural_form(value, format_spec[len("plural:"):].split("|"))
        return super().format_field(value, format_spec)


_formatter = _Formatter()


def place_name(name, language: str = DEFAULT_LANGUAGE):
    return PLACE_NAMES.get(language, {}).get(name, name) if isinstance(name, str) else name


def translate(text, language: str = DEFAULT_LANGUAGE, /, **fields):
    """Translate `text` (and any vocabulary or name fields), then fill in `fields`.

    Text that is not interface vocabulary but is a country name is shown in the
    dataset's localised spelling; anything else is returned unchanged.
    """
    if not isinstance(text, str):
        return text
    idx = LANGUAGES.index(language) - 1 if language in LANGUAGES else -1
    if idx >= 0:
        if text in STRINGS:
            entries = STRINGS[text]
            text = entries[idx] if idx < len(entries) and entries[idx] else text  # English fallback
        elif not fields:
            return place_name(text, language)
        fields = {k: translate(v, language) if k in TRANSLATED_FIELDS
                  else place_name(v, language) if k in NAME_FIELDS else v
                  for k, v in fields.items()}
    return _formatter.vformat(text, (), fields) if fields else text


def render_parts(parts, language: str = DEFAULT_LANGUAGE) -> str:
    """Render a sequence of (template, fields) pairs produced by the quiz engine."""
    joiner = "" if language.startswith("中文") else " "
    return joiner.join(translate(tpl, language, **params) for tpl, params in parts)


def missing_translations() -> list[str]:
    """Keys with a missing or empty entry for any language (used by tests)."""
    expected = len(LANGUAGES) - 1
    return [k for k, v in STRINGS.items() if len(v) != expected or not all(v)]
