"""Question generation, scoring and round state.

Everything here is pure: functions take and return plain dicts, and time is
passed in explicitly, so the whole quiz can be unit-tested without Streamlit.

A question looks like:
    {"id", "country_id", "kind", "family", "facts", "answer", "choices",
     "prompt": [(template, fields), ...], "explanation": [(template, fields), ...],
     "source", "extra_source", "flag"}
Prompts are stored as templates so they can be shown in any interface language.

Rules that keep every question defensible:
  * exactly one choice is correct; choices are distinct;
  * only UN member and observer states are ever the answer to "which country…?";
  * `facts` names the underlying facts semantically (e.g. "capital:FRA"), so a
    reworded or reversed question about the same fact cannot appear twice in a round;
  * distractors that could arguably also be correct are excluded (shared capitals,
    widely circulating currencies, languages from the same continent, adjacent
    subregions, look-alike flags, shared calling codes and domains).
"""
from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, defaultdict

from .data import (AREAS, COLLECTIONS, CONTINENTS, COUNTRIES, DATA_DIR, DEFAULT_COLLECTION, STATES,
                   get_countries, get_country, is_state, load_political_records, neighbours)

CATEGORIES = ("Mixed", "Capitals", "Flags", "Heads of State", "Currency", "Languages", "Country Identification",
              "Geography / General Facts", "Continents", "True or False", "Landmarks")
DIFFICULTIES = ("Easy", "Medium", "Difficult", "Expert")
QUESTION_COUNTS = (5, 10, 15, 20, 25, 50)
DIFFICULTY_MULTIPLIERS = {"Easy": 1.0, "Medium": 1.25, "Difficult": 1.5, "Expert": 2.0}
HINTS_PER_ROUND = 3
HINT_PENALTY = 25
SPEED_BONUS = 25
PERFECT_ROUND_BONUS = 250
UNGEGN_AFG = "https://ungegn.un.org/dashboard/countries/details?id=4"
FLAG_SOURCE = "https://github.com/mledoze/countries/tree/master/data"
FULL_SCAN_LIMIT = 40  # pools up to this size are scanned completely so round capacity is exact

_CURATION = json.loads((DATA_DIR / "reference" / "curation.json").read_text(encoding="utf-8"))
NEVER_DISTRACTOR_CURRENCIES = frozenset(_CURATION["never_distractor_currencies"])
GLOBAL_LANGUAGES = frozenset(_CURATION["global_languages"])
FLAG_LOOKALIKES: dict[str, set[str]] = defaultdict(set)
for _a, _b in _CURATION["flag_lookalikes"]:
    FLAG_LOOKALIKES[_a].add(_b)
    FLAG_LOOKALIKES[_b].add(_a)

_ASCII_DOMAIN = re.compile(r"^\.[a-z]{2}$")
_NAME_STOPWORDS = frozenset({"and", "the", "of", "republic", "democratic", "islands", "island", "saint", "united",
                             "kingdom", "states", "new", "south", "north", "east", "west", "central", "federated",
                             "people's", "city", "da", "de", "la", "and"})


def reveals(text: str, name: str) -> bool:
    """True if `text` contains a recognisable stem of `name` (e.g. "Japanese yen" reveals "Japan").

    Used to drop clues and questions that would give the answer away."""
    words = re.findall(r"[^\W\d_]+", text.casefold())
    for token in re.findall(r"[^\W\d_]+(?:'s)?", name.casefold()):
        if token in _NAME_STOPWORDS or len(token) < 4:
            continue
        stem = token[:max(4, len(token) - 2)]
        if any(w.startswith(stem) for w in words):
            return True
    return False


def _owners(values_of) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for c in COUNTRIES:
        for v in values_of(c):
            owners[v].add(c["id"])
    return owners


CAPITAL_OWNERS = _owners(lambda c: [x["name"] for x in c["capitals"]])
DOMAIN_OWNERS = _owners(lambda c: c["domains"])
CODE_OWNERS = _owners(lambda c: c["calling_codes"])


def unique_domains(country) -> list[str]:
    return [d for d in country["domains"] if _ASCII_DOMAIN.match(d) and DOMAIN_OWNERS[d] == {country["id"]}]


def unique_calling_codes(country) -> list[str]:
    """Codes used by this place alone, and not a prefix or extension of another place's code."""
    return [code for code in country["calling_codes"]
            if CODE_OWNERS[code] == {country["id"]}
            and not any(o != code and (o.startswith(code) or code.startswith(o)) for o in CODE_OWNERS)]


DOMAIN_POOL = {c["id"]: unique_domains(c) for c in COUNTRIES}
CODE_POOL = {c["id"]: unique_calling_codes(c) for c in COUNTRIES}


def currency_label(currency: dict) -> str:
    return f"{currency['name']} ({currency['code']})"




# --------------------------------------------------------------------------- choices

def _rank(country, other) -> int:
    """0 = neighbour, 1 = same subregion, 2 = same continent, 3 = elsewhere."""
    if other["id"] in country["borders"]:
        return 0
    if other["region"] and other["region"] == country["region"]:
        return 1
    return 2 if set(other["continents"]) & set(country["continents"]) else 3


def _pick(buckets, rng, size, difficulty, exclude=(), clash=None):
    """Choose `size` distinct values, nearest bucket first. `clash(a, b)` vetoes pairs."""
    if difficulty == "Easy":
        buckets = [[v for b in buckets for v in b]]
    chosen: list[str] = []
    for bucket in buckets:
        unique = [v for v in dict.fromkeys(bucket) if v not in chosen and v not in exclude]
        rng.shuffle(unique)
        for v in unique:
            if len(chosen) >= size:
                break
            if clash is None or not any(clash(v, other) for other in chosen):
                chosen.append(v)
        if len(chosen) >= size:
            break
    return chosen if len(chosen) >= size else None


def _options(correct, distractors, rng):
    if distractors is None:
        return None
    options = list(distractors) + [correct]
    rng.shuffle(options)
    return options


def country_choices(country, correct_name, difficulty, rng, size=4, exclude_ids=(), flags=False):
    """Distractor country names: states only, nearer countries at harder levels.

    With `flags`, no two choices may be look-alike flags (e.g. Chad and Romania)."""
    answer_id = next((c["id"] for c in STATES if c["name"] == correct_name), country["id"])
    banned = set(exclude_ids) | {country["id"], answer_id} | FLAG_LOOKALIKES.get(answer_id, set())
    buckets: list[list[str]] = [[], [], [], []]
    for other in STATES:
        if other["id"] not in banned:
            buckets[_rank(country, other)].append(other["id"])
    clash = (lambda a, b: b in FLAG_LOOKALIKES.get(a, ())) if flags else None
    ids = _pick(buckets, rng, size - 1, difficulty, clash=clash)
    by_id = {c["id"]: c["name"] for c in STATES}
    return _options(correct_name, [by_id[i] for i in ids] if ids else None, rng)


def value_choices(country, values_of, correct, valid, difficulty, rng, size=4, pool=COUNTRIES, allowed=None):
    """Distractors from other places' values, excluding anything valid for `country`."""
    valid = set(valid) | {correct}
    buckets: list[list[str]] = [[], [], [], []]
    for other in pool:
        if other["id"] == country["id"] or (allowed and not allowed(other)):
            continue
        buckets[_rank(country, other)].extend(v for v in values_of(other) if v and v not in valid)
    return _options(correct, _pick(buckets, rng, size - 1, difficulty), rng)


# --------------------------------------------------------------------------- generation

class _Builder:
    """Collects valid questions for one country."""

    def __init__(self, country):
        self.country = country
        self.items: list[dict] = []

    def add(self, suffix, kind, prompt, answer, options, explanation, *,
            facts, source=None, family=None, extra_source=None, flag=None):
        if (not options or len(options) not in (2, 4) or len(set(options)) != len(options)
                or options.count(answer) != 1):
            return
        c = self.country
        self.items.append({
            "id": f"{c['id']}:{suffix}", "country_id": c["id"], "kind": kind, "family": family or kind,
            "facts": list(facts), "prompt": list(prompt), "answer": answer, "choices": options,
            "explanation": list(explanation), "source": source or c["source"],
            "extra_source": extra_source, "flag": flag,
        })


def _capitals(b, c, difficulty, rng):
    if not c["capital_question"] or c["capitals"][0]["name"] == c["name"]:
        return  # disputed/unsettled capitals, and city-states whose capital shares their name
    name, capitals = c["name"], [x["name"] for x in c["capitals"]]
    capital_of = lambda o: [x["name"] for x in o["capitals"]] if o["capital_question"] else []  # noqa: E731
    for cap in c["capitals"]:
        place, role = cap["name"], cap["role"]
        fact = [f"capital:{c['id']}:{place}"]
        expl = [("{place} is the {role} of {name}.", dict(place=place, role=role, name=name))]
        b.add(f"capital:{place}", "Capitals", [("Which place serves as the {role} of {name}?", dict(role=role, name=name))],
              place, value_choices(c, capital_of, place, capitals, difficulty, rng), expl,
              facts=fact, source=c.get("capital_source"))
        if (difficulty in ("Difficult", "Expert") and is_state(c) and CAPITAL_OWNERS[place] == {c["id"]}
                and not reveals(place, name)):
            b.add(f"reverse:{place}", "Capitals", [("{place} is the {role} of which country?", dict(place=place, role=role))],
                  name, country_choices(c, name, difficulty, rng), expl, facts=fact, source=c.get("capital_source"))


def _flag(b, c, difficulty, rng):
    if not c["flag"] or not is_state(c):
        return
    b.add("flag", "Flags", [("Which country does this flag belong to?", {})], c["name"],
          country_choices(c, c["name"], difficulty, rng, flags=True),
          [("This is the flag of {name}.", dict(name=c["name"]))],
          facts=[f"flag:{c['id']}"], source=FLAG_SOURCE, flag=c["id"])


def _currencies(b, c, difficulty, rng):
    if not c["currency_question"]:
        return
    labels = [currency_label(x) for x in c["currencies"]]
    codes = {x["code"] for x in c["currencies"]}
    allowed_of = lambda o: [currency_label(x) for x in o["currencies"]  # noqa: E731
                            if x["code"] not in NEVER_DISTRACTOR_CURRENCIES and x["code"] not in codes]
    for cur in c["currencies"]:
        label = currency_label(cur)
        b.add(f"currency:{cur['code']}", "Currency", [("Which of these currencies is used in {name}?", dict(name=c["name"]))],
              label, value_choices(c, allowed_of, label, labels, difficulty, rng),
              [("{name} uses {currencies}.", dict(name=c["name"], currencies=", ".join(labels)))],
              facts=[f"currency:{c['id']}:{cur['code']}"])


def _languages(b, c, difficulty, rng):
    """Languages with official status or wide use. Distractors are national languages of states on
    other continents, never a globally spoken language, so none can plausibly be correct."""
    langs = c["languages"]
    if not langs:
        return
    far = lambda o: not set(o["continents"]) & set(c["continents"])  # noqa: E731
    values_of = lambda o: [v for v in o["languages"] if v not in GLOBAL_LANGUAGES and v not in langs]  # noqa: E731
    for lang in langs:
        b.add(f"language:{lang}", "Languages",
              [("Which of these languages has official status or wide use in {name}?", dict(name=c["name"]))], lang,
              value_choices(c, values_of, lang, langs, "Easy", rng, pool=STATES, allowed=far),
              [("{language} has official status or wide use in {name}.", dict(language=lang, name=c["name"]))],
              facts=[f"language:{c['id']}:{lang}"], source=UNGEGN_AFG if c["id"] == "AFG" else None)


def _identification(b, c, difficulty, rng):
    if not is_state(c):
        return
    name = c["name"]
    if c["capital_question"] and c["capitals"] and not reveals(c["capitals"][0]["name"], name):
        cap = c["capitals"][0]
        prompt = [("Identify the country: its {role} is {capital}.", dict(role=cap["role"], capital=cap["name"]))]
        facts = [f"capital:{c['id']}:{cap['name']}"]
        hidden = [x for x in c["currencies"] if not reveals(x["name"], name)]
        if difficulty in ("Difficult", "Expert") and c["currency_question"] and hidden:
            cur = rng.choice(hidden)
            prompt.append(("It uses {currency}.", dict(currency=currency_label(cur))))
            facts.append(f"currency:{c['id']}:{cur['code']}")
        quiet = [x for x in c["languages"] if not reveals(x, name)]
        if difficulty == "Expert" and quiet:
            lang = rng.choice(quiet)
            prompt.append(("{language} has official status or wide use there.", dict(language=lang)))
            facts.append(f"language:{c['id']}:{lang}")
        b.add("identify", "Country Identification", prompt, name, country_choices(c, name, difficulty, rng),
              [("These clues describe {name}.", dict(name=name))], facts=facts, extra_source=c.get("capital_source"))
    # A pair of neighbours that only this country borders uniquely identifies it.
    near = [n for n in neighbours(c) if is_state(n)]
    pairs = [(x, y) for i, x in enumerate(near) for y in near[i + 1:]
             if [o["id"] for o in COUNTRIES if {x["id"], y["id"]} <= set(o["borders"])] == [c["id"]]]
    if pairs:
        x, y = rng.choice(pairs)
        b.add("identify-borders", "Country Identification",
              [("Which country shares land borders with both {first} and {second}?", dict(first=x["name"], second=y["name"]))],
              name, country_choices(c, name, difficulty, rng, exclude_ids=(x["id"], y["id"])),
              [("{name} shares land borders with {first} and {second}.", dict(name=name, first=x["name"], second=y["name"]))],
              facts=["border:" + ":".join(sorted([c["id"], n["id"]])) for n in (x, y)], family="Neighbour clues")


def _landmarks(b, c, difficulty, rng, category):
    name = c["name"]
    others = [s["name"] for o in COUNTRIES if o["id"] != c["id"] for s in o["landmarks"]]
    for site in c["landmarks"]:
        expl, facts = [("{site} is in {name}.", dict(site=site["name"], name=name))], [f"landmark:{site['name']}"]
        if is_state(c) and not reveals(site["name"], name):
            b.add("landmark-reverse:" + site["name"], "Country Identification" if category == "Country Identification" else "Landmarks",
                  [("In which country is the UNESCO World Heritage site {site}?", dict(site=site["name"]))], name,
                  country_choices(c, name, difficulty, rng), expl, source=site["source"], facts=facts, family="Landmarks")
        if category != "Country Identification":
            pool = [s for s in dict.fromkeys(others)]
            rng.shuffle(pool)
            b.add("landmark:" + site["name"], "Landmarks",
                  [("Which of these UNESCO World Heritage sites is in {name}?", dict(name=name))], site["name"],
                  _options(site["name"], pool[:3] if len(pool) >= 3 else None, rng), expl,
                  source=site["source"], facts=facts, family="Landmarks")


def _adjacent_regions(c) -> set[str]:
    """Subregions that touch this country's subregion — too close to be clear-cut distractors."""
    members = [o for o in COUNTRIES if o["region"] == c["region"]]
    return {get_country(b)["region"] for o in members for b in o["borders"] if get_country(b)} | {c["region"]}


def _geography(b, c, difficulty, rng):
    name = c["name"]
    if c["region"] and len(c["continents"]) == 1 and not reveals(c["region"], name):
        blocked = _adjacent_regions(c)
        b.add("region", "Geography / General Facts", [("In which geographic subregion is {name}?", dict(name=name))],
              c["region"], value_choices(c, lambda o: [o["region"]] if o["region"] not in blocked else [],
                                         c["region"], [c["region"]], difficulty, rng),
              [("{name} is in {region}, within {continent}.", dict(name=name, region=c["region"], continent=c["continent"]))],
              facts=[f"region:{c['id']}"])
    near = [n for n in neighbours(c) if is_state(n)]
    if near:
        other = rng.choice(near)
        b.add("border", "Geography / General Facts",
              [("Which of these countries shares a land border with {name}?", dict(name=name))], other["name"],
              country_choices(c, other["name"], difficulty, rng, exclude_ids=c["borders"]),
              [("{other} and {name} share a land border.", dict(other=other["name"], name=name))],
              facts=["border:" + ":".join(sorted([c["id"], other["id"]]))], family="Neighbours")
    if c["landlocked"] and is_state(c):
        coastal = [o["name"] for o in STATES if not o["landlocked"] and set(o["continents"]) & set(c["continents"])]
        rng.shuffle(coastal)
        b.add("landlocked", "Geography / General Facts", [("Which of these countries is landlocked?", {})], name,
              _options(name, coastal[:3] if len(coastal) >= 3 else None, rng),
              [("{name} is landlocked.", dict(name=name))], facts=[f"coast:{c['id']}"], family="Landlocked")
    if c["area_km2"] and is_state(c):
        # Require a >20% size gap so source rounding can never flip the answer.
        rivals = [o for o in STATES if o["id"] != c["id"] and o["area_km2"]
                  and max(o["area_km2"], c["area_km2"]) / min(o["area_km2"], c["area_km2"]) > 1.2]
        if rivals:
            other = rng.choice(rivals)
            options = [name, other["name"]]
            rng.shuffle(options)
            b.add("area:" + other["id"], "Geography / General Facts",
                  [("Which country has the larger total area: {name} or {other}?", dict(name=name, other=other["name"]))],
                  max(c, other, key=lambda x: x["area_km2"])["name"], options,
                  [("{name}: {a} km²; {other}: {b} km².",
                    dict(name=name, a=f"{c['area_km2']:,.0f}", other=other["name"], b=f"{other['area_km2']:,.0f}"))],
                  facts=[f"area:{c['id']}", f"area:{other['id']}"], family="Size comparisons")
    for values, field, family, prompt in (
            (DOMAIN_POOL.get(c["id"], []), "domain", "Internet domains", "Which country-code internet domain belongs to {name}?"),
            (CODE_POOL.get(c["id"], []), "code", "Calling codes", "Which international telephone calling code belongs to {name}?")):
        if values:
            answer = rng.choice(values)
            pool = [v for o in COUNTRIES if o["id"] != c["id"]
                    for v in (DOMAIN_POOL if field == "domain" else CODE_POOL)[o["id"]]]
            pool = list(dict.fromkeys(pool))
            rng.shuffle(pool)
            b.add(field, "Geography / General Facts", [(prompt, dict(name=name))], answer,
                  _options(answer, pool[:3] if len(pool) >= 3 else None, rng),
                  [("{name}: {values}.", dict(name=name, values=", ".join(values)))],
                  facts=[f"{field}:{c['id']}"], family=family)


def _continents(b, c, difficulty, rng):
    if len(c["continents"]) > 1 or reveals(c["continent"], c["name"]):
        return  # transcontinental/ambiguous, or the name gives it away ("South Africa")
    options = rng.sample([x for x in CONTINENTS if x != c["continent"]], 3) + [c["continent"]]
    rng.shuffle(options)
    b.add("continent", "Continents", [("On which continent is {name}?", dict(name=c["name"]))], c["continent"],
          options, [("{name} is in {continent}.", dict(name=c["name"], continent=c["continent"]))],
          facts=[f"continent:{c['id']}"])


def _true_false(b, c, difficulty, rng):
    name = c["name"]
    statements = [(("{name} is landlocked.", dict(name=name)), c["landlocked"],
                   ("{name} is landlocked." if c["landlocked"] else "{name} has a coastline.", dict(name=name)),
                   "coast", None)]
    if c["capital_question"] and c["capitals"][0]["name"] != name:
        cap = c["capitals"][0]
        truthful = rng.random() < 0.5
        stated = cap["name"]
        if not truthful:
            options = value_choices(c, lambda o: [x["name"] for x in o["capitals"]] if o["capital_question"] else [],
                                    cap["name"], [x["name"] for x in c["capitals"]], difficulty, rng)
            stated = next((v for v in options or [] if v != cap["name"]), None)
        if stated:
            statements.append((("{place} is the {role} of {name}.", dict(place=stated, role=cap["role"], name=name)), truthful,
                               ("{place} is the {role} of {name}.", dict(place=cap["name"], role=cap["role"], name=name)),
                               f"capital:{c['id']}:{cap['name']}", c.get("capital_source")))
    if len(c["continents"]) == 1:
        truthful = rng.random() < 0.5
        stated = c["continent"] if truthful else rng.choice([x for x in CONTINENTS if x != c["continent"]])
        statements.append((("{name} is in {continent}.", dict(name=name, continent=stated)), truthful,
                           ("{name} is in {continent}.", dict(name=name, continent=c["continent"])),
                           f"continent:{c['id']}", None))
    if c["currency_question"]:
        labels = [currency_label(x) for x in c["currencies"]]
        truthful = rng.random() < 0.5
        cur = c["currencies"][0]
        stated = labels[0]
        if not truthful:
            codes = {x["code"] for x in c["currencies"]}
            pool = [currency_label(x) for o in STATES for x in o["currencies"]
                    if x["code"] not in codes and x["code"] not in NEVER_DISTRACTOR_CURRENCIES and set(o["continents"]) & set(c["continents"])]
            stated = rng.choice(pool) if pool else None
        if stated:
            statements.append((("{name} uses {currencies}.", dict(name=name, currencies=stated)), truthful,
                               ("{name} uses {currencies}.", dict(name=name, currencies=", ".join(labels))),
                               f"currency:{c['id']}:{cur['code']}", None))
    for (prompt, truthful, explanation, fact, source) in statements:
        topic = fact.split(":")[0]
        b.add("truefalse:" + topic, "True or False", [prompt], "True" if truthful else "False", ["True", "False"],
              [explanation], source=source, facts=[fact if ":" in fact else f"{fact}:{c['id']}"])


def _leader(b, c, difficulty, rng, leaders):
    record = leaders.get(c["id"])
    if not record:
        return
    answer = " / ".join(record["names"])
    # Exclude any record sharing a person (e.g. Charles III for Canada and New Zealand).
    pool = list(dict.fromkeys(" / ".join(r["names"]) for r in leaders.values() if not set(r["names"]) & set(record["names"])))
    rng.shuffle(pool)
    b.add("leader", "Heads of State",
          [("Who is the {title} and head of state of {name}? (Record verified {verified})",
            dict(title=record["title"], name=c["name"], verified=record["verified_on"]))],
          answer, _options(answer, pool[:3] if len(pool) >= 3 else None, rng),
          [("{answer} is recorded as {title} of {name}, verified {date}. Head of state and head of government can be different offices.",
            dict(answer=answer, title=record["title"], name=c["name"], date=record["verified_on"]))],
          facts=[f"leader:{c['id']}"], source=record["source"])


def question_candidates(country, category, difficulty, rng, leaders, flags=True) -> list[dict]:
    b = _Builder(country)
    wants = lambda *cats: category == "Mixed" or category in cats  # noqa: E731
    if wants("Capitals"):
        _capitals(b, country, difficulty, rng)
    if category == "Flags" or (category == "Mixed" and flags):
        _flag(b, country, difficulty, rng)
    if wants("Currency"):
        _currencies(b, country, difficulty, rng)
    if wants("Languages"):
        _languages(b, country, difficulty, rng)
    if wants("Country Identification"):
        _identification(b, country, difficulty, rng)
    if wants("Geography / General Facts"):
        _geography(b, country, difficulty, rng)
    if wants("Continents"):
        _continents(b, country, difficulty, rng)
    if wants("True or False"):
        _true_false(b, country, difficulty, rng)
    if wants("Landmarks", "Country Identification"):
        _landmarks(b, country, difficulty, rng, category)
    if wants("Heads of State"):
        _leader(b, country, difficulty, rng, leaders)
    return b.items


# --------------------------------------------------------------------------- rounds

def normalize_settings(settings) -> dict | None:
    """Fill optional keys (older sessions lack them) and validate. None if invalid."""
    if not isinstance(settings, dict):
        return None
    s = {"collection": DEFAULT_COLLECTION, "flags": True, **settings}
    required = {"continent", "country_id", "category", "difficulty", "count", "timer"}
    if not (required <= s.keys() and s["continent"] in AREAS and s["category"] in CATEGORIES
            and s["difficulty"] in DIFFICULTIES and s["count"] in QUESTION_COUNTS and s["collection"] in COLLECTIONS
            and isinstance(s["timer"], bool) and isinstance(s["flags"], bool)):
        return None
    if s["country_id"] != "all" and not get_countries(s["continent"], s["country_id"], s["collection"]):
        return None
    return s


def valid_settings(settings) -> bool:
    return normalize_settings(settings) is not None


def _country_order(pool, recent, difficulty, rng):
    """Countries not asked recently first; within that, mix well-known and less-known places."""
    rng.shuffle(pool)
    tier_weight = {"Easy": {1: 0, 2: 1, 3: 2}, "Medium": {1: 0, 2: 0, 3: 1}}.get(difficulty, {1: 0, 2: 0, 3: 0})
    return sorted(pool, key=lambda c: (c["id"] in recent, tier_weight[c["tier"]] if rng.random() < 0.6 else 0))


def generate_quiz(settings, recent=(), recent_facts=(), seed=None, leaders=None):
    """Return (questions, capacity).

    No fact is tested twice in a round. `capacity` is the number of distinct-fact
    questions available for these filters: exact for small pools; for large pools it
    is at least the requested count. Rounds are never padded with repeated facts.
    """
    s = normalize_settings(settings)
    if s is None:
        return [], 0
    rng = random.Random(seed)
    leaders = load_political_records() if leaders is None else leaders
    recent, recent_facts = set(recent), set(recent_facts)
    pool = get_countries(s["continent"], s["country_id"], s["collection"])
    single = s["country_id"] != "all"
    full_scan = len(pool) <= FULL_SCAN_LIMIT or s["category"] == "Heads of State"
    order = _country_order(list(pool), recent, s["difficulty"], rng)
    if s["category"] == "Heads of State":
        order = [c for c in order if c["id"] in leaders]

    candidates: list[dict] = []
    target = s["count"] * 4
    for i, country in enumerate(order):
        candidates.extend(question_candidates(country, s["category"], s["difficulty"], rng, leaders, s["flags"]))
        enough_countries = i + 1 >= min(len(order), s["count"] * 2)
        if not full_scan and enough_countries and len(candidates) >= target:
            break
    if single and s["category"] != "Country Identification":
        # With one chosen country, questions answered by its own name teach nothing — keep at most one
        # (a size comparison, which is a genuine comparison).
        chosen = pool[0]["name"]
        named = [q for q in candidates if q["answer"] == chosen and q["family"] == "Size comparisons"][:1]
        candidates = [q for q in candidates if q["answer"] != chosen] + named
    candidates = list({q["id"]: q for q in candidates}.values())
    rng.shuffle(candidates)

    selected, per_country, per_family, used = [], Counter(), Counter(), set()
    limit = float("inf") if full_scan else s["count"]
    while candidates and len(selected) < limit:
        last_family = selected[-1]["family"] if selected else None
        best = min(candidates, key=lambda q: (bool(recent_facts.intersection(q["facts"])), per_country[q["country_id"]],
                                              per_family[q["family"]], q["country_id"] in recent,
                                              q["family"] == last_family))
        selected.append(best)
        per_country[best["country_id"]] += 1
        per_family[best["family"]] += 1
        used.update(best["facts"])
        candidates = [q for q in candidates if q is not best and not used.intersection(q["facts"])]
    capacity = len(selected) if full_scan else max(len(selected), s["count"])
    return selected[:s["count"]], capacity


# --------------------------------------------------------------------------- scoring & round state

# Streak multiplier: the n-th consecutive correct answer in a round multiplies the question's base points.
# (minimum streak, multiplier), checked from the top. A wrong answer or a timeout resets the streak to 0.
STREAK_MULTIPLIERS = ((5, 3), (3, 2), (1, 1))


def streak_multiplier(streak: int) -> int:
    """1 for the 1st-2nd correct answer in a row, 2 for the 3rd-4th, 3 from the 5th on."""
    return next((m for minimum, m in STREAK_MULTIPLIERS if streak >= minimum), 1)


def score_answer(correct, difficulty, elapsed, streak, used_hint=False, time_limit=None) -> dict:
    """Points for one answer. `streak` already includes this answer when it is correct.

    total = max(0, base x multiplier + speed bonus - hint penalty)
    Only the base is multiplied; the speed bonus and the hint penalty are flat, and the
    perfect-round bonus (added in advance()) is never multiplied.
    """
    if not correct:
        return {"base": 0, "multiplier": 1, "streak": 0, "speed": 0, "hint": 0, "total": 0}
    base = round(100 * DIFFICULTY_MULTIPLIERS[difficulty])
    multiplier = streak_multiplier(streak)
    speed = SPEED_BONUS if elapsed <= (time_limit / 3 if time_limit else 7) else 0
    hint = HINT_PENALTY if used_hint else 0
    boosted = base * multiplier
    return {"base": base, "multiplier": multiplier, "streak": boosted - base, "speed": speed, "hint": hint,
            "total": max(0, boosted + speed - hint)}


def new_round(settings, questions, available, serial) -> dict:
    return {"settings": normalize_settings(settings) or dict(settings), "questions": questions, "available": available,
            "serial": serial, "index": 0, "selected": None, "resolved": False, "finished": False,
            "score": 0, "correct": 0, "streak": 0, "best_streak": 0,
            "hints_remaining": HINTS_PER_ROUND, "hint_used": False, "hidden_options": [],
            "history": [], "started_at": None, "perfect_bonus": 0, "last_points": None, "event": None}


def current_question(quiz) -> dict:
    return quiz["questions"][quiz["index"]]


def time_limit(quiz) -> int | None:
    if not quiz["settings"]["timer"]:
        return None
    return 15 if quiz["settings"]["difficulty"] == "Expert" else 20


def elapsed(quiz, now=None) -> float:
    now = time.monotonic() if now is None else now
    if quiz["started_at"] is None and not quiz["resolved"] and not quiz["finished"]:
        quiz["started_at"] = now
    started = quiz["started_at"]
    return 0.0 if started is None else max(0.0, now - started)


def is_current(quiz, serial, index) -> bool:
    return bool(quiz) and quiz["serial"] == serial and quiz["index"] == index and not quiz["finished"]


def _event(quiz, kind):
    """A one-off feedback event (used for sound). Its id never repeats within a session."""
    quiz["event"] = {"id": f"{quiz['serial']}:{quiz['index']}:{kind}", "kind": kind}


def resolve(quiz, choice, now=None) -> int:
    """Record an answer (None = timed out / skipped). Returns points awarded."""
    if not quiz or quiz["resolved"] or quiz["finished"]:
        return 0
    q = current_question(quiz)
    if choice is not None and (choice not in q["choices"] or choice in quiz["hidden_options"]):
        return 0
    taken, limit = elapsed(quiz, now), time_limit(quiz)
    timed_out = limit is not None and taken >= limit
    if timed_out:
        choice, taken = None, float(limit)
    correct = choice == q["answer"]
    quiz["streak"] = quiz["streak"] + 1 if correct else 0
    quiz["best_streak"] = max(quiz["best_streak"], quiz["streak"])
    quiz["correct"] += correct
    points = score_answer(correct, quiz["settings"]["difficulty"], taken, quiz["streak"], quiz["hint_used"], limit)
    quiz.update(selected=choice, resolved=True, last_points=points, score=quiz["score"] + points["total"])
    from .facts import pick  # local import: facts uses this module's helpers
    quiz["history"].append({"question": q, "answer": choice, "correct": correct, "elapsed": taken,
                            "hint": quiz["hint_used"], "timed_out": timed_out, "points": points,
                            "streak": quiz["streak"], "fact": pick(quiz["questions"], quiz["index"])})
    _event(quiz, "correct" if correct else "incorrect")
    return points["total"]


def expire_if_due(quiz, now=None) -> int:
    limit = time_limit(quiz)
    if quiz and not quiz["resolved"] and not quiz["finished"] and limit is not None and elapsed(quiz, now) >= limit:
        return resolve(quiz, None, now)
    return 0


def use_hint(quiz, rng=random, now=None) -> bool:
    """Hide one wrong option. Returns True if a hint was applied."""
    if (not quiz or quiz["finished"] or quiz["resolved"] or quiz["hint_used"] or quiz["hints_remaining"] <= 0
            or len(current_question(quiz)["choices"]) < 4):
        return False
    expire_if_due(quiz, now)  # a hint clicked after the clock ran out records the timeout instead
    if quiz["resolved"]:
        return False
    q = current_question(quiz)
    quiz["hidden_options"] = [rng.choice([c for c in q["choices"] if c != q["answer"]])]
    quiz["hint_used"] = True
    quiz["hints_remaining"] -= 1
    return True


def advance(quiz) -> int:
    """Move to the next question or finish. Returns any perfect-round bonus awarded."""
    if not quiz or not quiz["resolved"] or quiz["finished"]:
        return 0
    if quiz["index"] + 1 < len(quiz["questions"]):
        quiz.update(index=quiz["index"] + 1, selected=None, resolved=False, started_at=None,
                    hint_used=False, hidden_options=[], last_points=None)
        return 0
    quiz["finished"] = True
    if quiz["correct"] == len(quiz["questions"]) and not any(h["hint"] for h in quiz["history"]):
        quiz["perfect_bonus"] = round(PERFECT_ROUND_BONUS * DIFFICULTY_MULTIPLIERS[quiz["settings"]["difficulty"]])
        quiz["score"] += quiz["perfect_bonus"]
    _event(quiz, "perfect" if quiz["perfect_bonus"] else "complete")
    return quiz["perfect_bonus"]


def missed(quiz) -> list[dict]:
    """History entries answered wrongly or not at all — only available once a round is finished."""
    return [h for h in quiz["history"] if not h["correct"]] if quiz and quiz["finished"] else []


def statistics(quiz) -> dict:
    history, total = quiz["history"], len(quiz["questions"])
    return {"total": total, "correct": quiz["correct"],
            "incorrect": sum(not h["correct"] and not h["timed_out"] for h in history),
            "timed_out": sum(h["timed_out"] for h in history),
            "accuracy": 100 * quiz["correct"] / total if total else 0,
            "average_time": sum(h["elapsed"] for h in history) / len(history) if history else 0,
            "best_streak": quiz["best_streak"], "score": quiz["score"]}
