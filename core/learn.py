"""Pure helpers for the Learn page: country stepping, neighbours by collection, recall cards and
size comparison. No Streamlit here, so every rule is unit-tested directly."""
from __future__ import annotations

import random

from .data import get_country
from .quiz import currency_label

# --------------------------------------------------------------------------- navigation


def step(ids: list[str], current: str, delta: int) -> str | None:
    """The country `delta` places after `current` in `ids`, wrapping round at either end.

    A country outside `ids` (opened from a link or a quiz review) steps to the first (Next) or
    last (Previous) country of the list. None when there is nowhere else to go.
    """
    if not ids:
        return None
    if current not in ids:
        return ids[0] if delta > 0 else ids[-1]
    if len(ids) == 1:
        return None
    return ids[(ids.index(current) + delta) % len(ids)]


def surprise(ids: list[str], current: str, rng: random.Random | None = None) -> str | None:
    """A random country from `ids` other than `current`; None if there is no other choice."""
    others = [i for i in ids if i != current]
    return (rng or random).choice(others) if others else None


def split_neighbours(country: dict, allowed_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """(neighbours in the selected places collection, neighbours left out by that selection)."""
    near = [n for n in map(get_country, country["borders"]) if n]
    return [n for n in near if n["id"] in allowed_ids], [n for n in near if n["id"] not in allowed_ids]


# --------------------------------------------------------------------------- recall cards

def recall_items(country: dict) -> list[dict]:
    """Capital, currency and languages cards, built from the same curated fields the quiz uses.

    Each item: {kind, title, question (parts), answer (str) or None, note (str) when omitted}.
    Unsettled capitals and unreliable currency lists (curation flags) are omitted, not guessed.
    """
    name = country["name"]
    items = []
    caps = country["capitals"]
    if country["capital_question"] and caps:
        multiple = len(caps) > 1
        items.append({"kind": "capital", "title": "Capital",
                      "question": [("Which places serve as the capitals of {name}?" if multiple else
                                    "What is the capital of {name}?", dict(name=name))],
                      "answer": [(x["name"], x["role"]) for x in caps], "note": None})
    else:
        items.append({"kind": "capital", "title": "Capital", "question": None, "answer": None,
                      "note": country.get("capital_note") or "No settled capital is recorded for this place, so it is not tested here."})
    curs = country["currencies"]
    if country["currency_question"] and curs:
        multiple = len(curs) > 1
        items.append({"kind": "currency", "title": "Currency",
                      "question": [("Which currencies are used in {name}?" if multiple else
                                    "Which currency is used in {name}?", dict(name=name))],
                      "answer": [(currency_label(x), None) for x in curs], "note": None})
    else:
        items.append({"kind": "currency", "title": "Currency", "question": None, "answer": None,
                      "note": country.get("currency_note") or "The currency record for this place is not reliable enough to test here."})
    langs = country["languages"]
    if langs:
        items.append({"kind": "languages", "title": "Languages",
                      "question": [("Which languages have official status or wide use in {name}?", dict(name=name))],
                      "answer": [(x, None) for x in langs], "note": None})
    else:
        items.append({"kind": "languages", "title": "Languages", "question": None, "answer": None,
                      "note": "No languages are recorded for this place."})
    return items


# --------------------------------------------------------------------------- size comparison

MIN_VISIBLE = 1.0  # percent: smaller bars are drawn as a thin marker and labelled "too small to show"


def compare_areas(first: dict, second: dict) -> dict:
    """Compare total areas (km², the dataset's single area field for both countries).

    Returns {"kind": "same" | "missing" | "ratio", ...}. For "ratio": larger/smaller country dicts,
    ratio (>= 1), share (smaller as % of larger) and bar widths in percent (larger = 100).
    """
    if first["id"] == second["id"]:
        return {"kind": "same"}
    missing = [c for c in (first, second) if not c.get("area_km2")]
    if missing:
        return {"kind": "missing", "missing": missing}
    larger, smaller = (first, second) if first["area_km2"] >= second["area_km2"] else (second, first)
    ratio = larger["area_km2"] / smaller["area_km2"]
    share = 100 * smaller["area_km2"] / larger["area_km2"]
    return {"kind": "ratio", "larger": larger, "smaller": smaller, "ratio": ratio, "share": share,
            "bars": {larger["id"]: 100.0, smaller["id"]: share}, "tiny": share < MIN_VISIBLE,
            "similar": ratio < 1.05}


def ratio_text(ratio: float) -> str:
    """Readable multiplier: 1.4, 12, 1,250 — never false precision."""
    if ratio < 10:
        return f"{ratio:.1f}"
    return f"{round(ratio):,}"
