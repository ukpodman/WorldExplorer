"""Pure helpers for the Learn page: country stepping, neighbours by collection and size comparison. No Streamlit here, so every rule is unit-tested directly."""
from __future__ import annotations

import random

from .data import get_country

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
