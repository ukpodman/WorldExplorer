"""Country data, lookups and political-record validation.

Pure Python (no Streamlit) so it can be tested and reused.
Country data adapted from mledoze/countries (ODbL 1.0); landmarks from the
UNESCO World Heritage List. See README.md for sources and licences.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_SOURCE = "https://github.com/mledoze/countries"

CONTINENTS = ("Africa", "Asia", "Europe", "North America", "South America", "Oceania")
WORLD = "World"
AREAS = (WORLD,) + CONTINENTS
POLITICAL_MAX_AGE_DAYS = 30


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _clean_strings(values) -> list[str]:
    return list(dict.fromkeys(v for v in (values or []) if isinstance(v, str) and v.strip()))


def normalize_country(record) -> dict | None:
    """Return a cleaned copy of a country record, or None if it is unusable."""
    if not isinstance(record, dict) or not all(record.get(k) for k in ("id", "name", "continent")):
        return None
    if record["continent"] not in CONTINENTS:
        return None
    c = dict(record)
    c["capitals"] = [{"name": x["name"], "role": x.get("role") or "capital"}
                     for x in c.get("capitals") or [] if isinstance(x, dict) and x.get("name")]
    c["currencies"] = [{"code": x["code"], "name": x["name"]}
                       for x in c.get("currencies") or [] if isinstance(x, dict) and x.get("name") and x.get("code")]
    for field in ("languages", "official_languages", "borders", "domains", "calling_codes"):
        c[field] = _clean_strings(c.get(field))
    c["landmarks"] = [x for x in c.get("landmarks") or [] if isinstance(x, dict) and x.get("name") and x.get("source")]
    c["region"] = c.get("region") or ""
    c["source"] = c.get("source") or DEFAULT_SOURCE
    c["landlocked"] = bool(c.get("landlocked"))
    c["tier"] = c.get("tier") if c.get("tier") in (1, 2, 3) else 3
    area = c.get("area_km2")
    c["area_km2"] = area if isinstance(area, (int, float)) and area > 0 else None
    return c


COUNTRIES: tuple[dict, ...] = tuple(sorted(
    (c for c in map(normalize_country, _load("countries.json")) if c), key=lambda c: c["name"]))
COUNTRY_BY_ID: dict[str, dict] = {c["id"]: c for c in COUNTRIES}
PHOTOS: dict[str, dict] = {k: v for k, v in _load("photos.json").items() if k in COUNTRY_BY_ID}


def get_country(country_id: str | None) -> dict | None:
    return COUNTRY_BY_ID.get(country_id)


def get_countries(continent: str = WORLD, country_id: str = "all") -> list[dict]:
    return [c for c in COUNTRIES
            if continent in (WORLD, c["continent"]) and country_id in ("all", c["id"])]


def neighbours(country: dict) -> list[dict]:
    """Bordering countries that exist in this collection."""
    return [n for n in map(get_country, country["borders"]) if n]


def valid_political_record(record, today: date | None = None) -> bool:
    try:
        age = ((today or date.today()) - date.fromisoformat(record["verified_on"])).days
        names = record["names"]
        return (isinstance(names, list) and bool(names)
                and all(isinstance(n, str) and n.strip() for n in names)
                and bool(record.get("title"))
                and str(record.get("source", "")).startswith("https://")
                and 0 <= age <= POLITICAL_MAX_AGE_DAYS)
    except (KeyError, TypeError, ValueError):
        return False


def load_political_records(today: date | None = None, override: Path | None = None) -> dict[str, dict]:
    """Bundled records plus an optional data/heads_of_state.local.json override.

    Records older than POLITICAL_MAX_AGE_DAYS are dropped so stale leaders are never quizzed.
    """
    records = dict(_load("heads_of_state.json"))
    override = override or DATA_DIR / "heads_of_state.local.json"
    if override.exists():
        try:
            extra = json.loads(override.read_text(encoding="utf-8"))
            if isinstance(extra, dict):
                records.update({k: v for k, v in extra.items() if k in COUNTRY_BY_ID and isinstance(v, dict)})
        except (OSError, ValueError):
            pass
    return {k: v for k, v in records.items() if valid_political_record(v, today)}
