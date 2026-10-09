"""One short "Did you know?" fact shown after an answer.

Facts come only from the bundled, sourced dataset (country records and UNESCO site links);
nothing is invented and no superlatives are claimed. Each fact carries the same semantic keys
the quiz engine uses (e.g. ``capital:FRA:Paris``), so a fact is never chosen if it repeats the
fact just tested or matches a fact tested by a later question in the round, which would give
that answer away.

Pure Python (no Streamlit). Facts are rendered with ``i18n.render_parts`` like questions.
"""
from __future__ import annotations

import hashlib

from .data import get_country
from .quiz import currency_label


def _neighbour_fact(c):
    near = [n for n in (get_country(b) for b in c["borders"]) if n]
    if not near:
        if c["landlocked"]:
            return None
        return ("borders", [("{name} has no land borders with other places in this dataset.", dict(name=c["name"]))],
                [f"borders:{c['id']}"])
    keys = ["border:" + ":".join(sorted([c["id"], n["id"]])) for n in near]
    names = [n["name"] for n in near]
    if len(near) == 1:
        parts = [("{name} shares a land border with one place: {first}.", dict(name=c["name"], first=names[0]))]
    elif len(near) == 2:
        parts = [("{name} shares land borders with {first} and {second}.", dict(name=c["name"], first=names[0], second=names[1]))]
    else:
        parts = [("{name} has {n} land neighbours, including {first}, {second} and {third}.",
                  dict(name=c["name"], n=len(near), first=names[0], second=names[1], third=names[2]))]
    return ("borders", parts, keys)


def candidates(country: dict) -> list[tuple[str, list, list, str | None]]:
    """(kind, parts, keys, source) for every fact the dataset supports about `country`."""
    c, out = country, []
    source = c["source"]
    for site in c["landmarks"][:3]:
        out.append(("landmark", [("{site} in {name} is on the UNESCO World Heritage List.", dict(site=site["name"], name=c["name"]))],
                    [f"landmark:{site['name']}"], site["source"]))
    near = _neighbour_fact(c)
    if near:
        out.append((*near, source))
    if c["area_km2"]:
        out.append(("area", [("{name} has a total area of about {size} km².", dict(name=c["name"], size=f"{c['area_km2']:,.0f}"))],
                    [f"area:{c['id']}"], source))
    if c["landlocked"]:
        out.append(("coast", [("{name} is landlocked.", dict(name=c["name"]))], [f"coast:{c['id']}"], source))
    if c["languages"]:
        out.append(("language", [("Languages with official status or wide use in {name}: {languages}.",
                                  dict(name=c["name"], languages=", ".join(c["languages"])))],
                    [f"language:{c['id']}:{x}" for x in c["languages"]], source))
    if c["currency_question"] and c["currencies"]:
        out.append(("currency", [("{name} uses {currencies}.", dict(name=c["name"], currencies=", ".join(currency_label(x) for x in c["currencies"])))],
                    [f"currency:{c['id']}:{x['code']}" for x in c["currencies"]], source))
    if c["capital_question"] and c["capitals"]:
        cap = c["capitals"][0]
        out.append(("capital", [("{place} is the {role} of {name}.", dict(place=cap["name"], role=cap["role"], name=c["name"]))],
                    [f"capital:{c['id']}:{cap['name']}"], c.get("capital_source") or source))
    if c["region"] and len(c["continents"]) == 1:
        out.append(("region", [("{name} is in {region}, within {continent}.", dict(name=c["name"], region=c["region"], continent=c["continent"]))],
                    [f"region:{c['id']}", f"continent:{c['id']}"], source))
    return out


def pick(questions: list[dict], index: int) -> dict | None:
    """The fact to show after question `index`, or None (the explanation then stands alone).

    Skips facts that repeat what was just tested or that any later question in the round tests.
    The choice is deterministic for a given question, so reruns show the same fact.
    """
    q = questions[index]
    country = get_country(q["country_id"])
    if not country:
        return None
    blocked = set(q["facts"]).union(*(set(later["facts"]) for later in questions[index + 1:]))
    options = [f for f in candidates(country) if not blocked.intersection(f[2])]
    if not options:
        return None
    start = int(hashlib.sha1(q["id"].encode("utf-8")).hexdigest(), 16) % len(options)
    kind, parts, keys, source = options[start]
    return {"kind": kind, "parts": parts, "keys": keys, "source": source}
