"""Question generation, scoring and round state.

Everything here is pure: functions take and return plain dicts, and time is
passed in explicitly, so the whole quiz can be unit-tested without Streamlit.

A question looks like:
    {"id", "country_id", "kind", "family", "facts", "answer", "choices",
     "prompt": [(template, fields), ...], "explanation": [(template, fields), ...],
     "source", "extra_source"}
Prompts are stored as templates so they can be shown in any interface language.
"""
from __future__ import annotations

import random
import time
from collections import Counter

from .data import AREAS, CONTINENTS, COUNTRIES, get_countries, get_country, load_political_records, neighbours

CATEGORIES = ("Mixed", "Capitals", "Heads of State", "Currency", "Languages", "Country Identification",
              "Geography / General Facts", "Continents", "True or False", "Landmarks")
DIFFICULTIES = ("Easy", "Medium", "Difficult", "Expert")
QUESTION_COUNTS = (5, 10, 15, 20, 25, 50)
DIFFICULTY_MULTIPLIERS = {"Easy": 1.0, "Medium": 1.25, "Difficult": 1.5, "Expert": 2.0}
HINTS_PER_ROUND = 3
HINT_PENALTY = 25
SPEED_BONUS = 25
PERFECT_ROUND_BONUS = 250
UNGEGN_AFG = "https://ungegn.un.org/dashboard/countries/details?id=4"


# --------------------------------------------------------------------------- choices

def _field_values(country: dict, field: str) -> list[str]:
    if field == "capital":
        return [x["name"] for x in country["capitals"]]
    if field == "currency":
        return [currency_label(x) for x in country["currencies"]]
    if field == "language":
        return country["official_languages"]
    if field == "country":
        return [country["name"]]
    if field == "region":
        return [country["region"]]
    return []


def currency_label(currency: dict) -> str:
    return f"{currency['name']} ({currency['code']})"


def plausible_choices(country, field, correct, valid_answers, difficulty, rng, size=4):
    """Return `size` shuffled options containing `correct` once and no other valid answer.

    Harder levels draw distractors from neighbours, then the same region, then the
    same continent; Easy draws from anywhere.
    """
    valid = set(valid_answers) | {correct}
    buckets: list[list[str]] = [[], [], [], []]
    for other in COUNTRIES:
        rank = (0 if other["id"] in country["borders"] else
                1 if other["region"] and other["region"] == country["region"] else
                2 if other["continent"] == country["continent"] else 3)
        buckets[rank].extend(v for v in _field_values(other, field) if v and v not in valid)
    if difficulty == "Easy":
        buckets = [[v for b in buckets for v in b]]
    distractors: list[str] = []
    for bucket in buckets:
        unique = [v for v in dict.fromkeys(bucket) if v not in distractors]
        rng.shuffle(unique)
        distractors.extend(unique)
        if len(distractors) >= size - 1:
            break
    if len(distractors) < size - 1:
        return None
    options = distractors[:size - 1] + [correct]
    rng.shuffle(options)
    return options


def _sample_options(answer, pool, rng, size=4):
    pool = [v for v in dict.fromkeys(pool) if v != answer]
    if len(pool) < size - 1:
        return None
    options = rng.sample(pool, size - 1) + [answer]
    rng.shuffle(options)
    return options


# --------------------------------------------------------------------------- generation

class _Builder:
    """Collects valid questions for one country."""

    def __init__(self, country):
        self.country = country
        self.items: list[dict] = []

    def add(self, suffix, kind, prompt, answer, options, explanation, *,
            source=None, facts=None, family=None, extra_source=None):
        if (not options or len(options) not in (2, 4) or len(set(options)) != len(options)
                or options.count(answer) != 1):
            return
        c = self.country
        self.items.append({
            "id": f"{c['id']}:{suffix}", "country_id": c["id"], "kind": kind, "family": family or kind,
            "facts": facts or [f"{c['id']}:{suffix.split(':')[0]}"],
            "prompt": list(prompt), "answer": answer, "choices": options,
            "explanation": list(explanation), "source": source or c["source"], "extra_source": extra_source,
        })


def _capitals(b, c, difficulty, rng):
    name, capitals = c["name"], [x["name"] for x in c["capitals"]]
    source = c.get("capital_source")
    for cap in c["capitals"]:
        place, role = cap["name"], cap["role"]
        fact, expl = [f"{c['id']}:capital"], [("{place} is the {role} of {name}.", dict(place=place, role=role, name=name))]
        b.add(f"capital:{place}", "Capitals", [("Which place serves as the {role} of {name}?", dict(role=role, name=name))],
              place, plausible_choices(c, "capital", place, capitals, difficulty, rng), expl, source=source, facts=fact)
        if difficulty in ("Difficult", "Expert"):
            b.add(f"reverse:{place}", "Capitals", [("{place} is the {role} of which country?", dict(place=place, role=role))],
                  name, plausible_choices(c, "country", name, [name], difficulty, rng), expl, source=source, facts=fact)


def _currencies(b, c, difficulty, rng):
    labels = [currency_label(x) for x in c["currencies"]]
    for label in labels:
        b.add(f"currency:{label}", "Currency", [("Which of these currencies is used in {name}?", dict(name=c["name"]))],
              label, plausible_choices(c, "currency", label, labels, difficulty, rng),
              [("{name} uses {currencies}.", dict(name=c["name"], currencies=", ".join(labels)))])


def _languages(b, c, difficulty, rng):
    langs = c["official_languages"]
    for lang in langs:
        b.add(f"language:{lang}", "Languages", [("Which of these is an official language of {name}?", dict(name=c["name"]))],
              lang, plausible_choices(c, "language", lang, langs, difficulty, rng),
              [("{language} is an official language of {name}.", dict(language=lang, name=c["name"]))],
              source=UNGEGN_AFG if c["id"] == "AFG" else None)


def _identification(b, c, difficulty, rng, category):
    name = c["name"]
    if c["capitals"]:
        cap = c["capitals"][0]
        prompt = [("Identify the country: its {role} is {capital}.", dict(role=cap["role"], capital=cap["name"]))]
        facts = [f"{c['id']}:capital"]
        if difficulty in ("Difficult", "Expert") and c["currencies"]:
            prompt.append(("It uses {currency}.", dict(currency=currency_label(rng.choice(c["currencies"])))))
            facts.append(f"{c['id']}:currency")
        if difficulty == "Expert" and c["official_languages"]:
            prompt.append(("{language} is one of its official languages.", dict(language=rng.choice(c["official_languages"]))))
            facts.append(f"{c['id']}:language")
        b.add("identify", "Country Identification", prompt, name,
              plausible_choices(c, "country", name, [name], difficulty, rng),
              [("These clues describe {name}.", dict(name=name))],
              facts=facts, extra_source=c.get("capital_source"))
    # A pair of neighbours that only this country borders uniquely identifies it.
    near = neighbours(c)
    pairs = [(x, y) for i, x in enumerate(near) for y in near[i + 1:]
             if [o["id"] for o in COUNTRIES if {x["id"], y["id"]} <= set(o["borders"])] == [c["id"]]]
    if pairs:
        x, y = rng.choice(pairs)
        b.add("identify-borders", "Country Identification",
              [("Which country shares land borders with both {first} and {second}?", dict(first=x["name"], second=y["name"]))],
              name, plausible_choices(c, "country", name, [name], difficulty, rng),
              [("{name} shares land borders with {first} and {second}.", dict(name=name, first=x["name"], second=y["name"]))],
              facts=["border:" + ":".join(sorted([c["id"], n["id"]])) for n in (x, y)], family="Neighbour clues")


def _landmarks(b, c, difficulty, rng, category):
    name = c["name"]
    others = [s["name"] for o in COUNTRIES if o["id"] != c["id"] for s in o["landmarks"]]
    for site in c["landmarks"]:
        expl, facts = [("{site} is in {name}.", dict(site=site["name"], name=name))], [f"landmark:{site['name']}"]
        b.add("landmark-reverse:" + site["name"], "Country Identification" if category == "Country Identification" else "Landmarks",
              [("In which country is the UNESCO World Heritage site {site}?", dict(site=site["name"]))], name,
              plausible_choices(c, "country", name, [name], difficulty, rng), expl,
              source=site["source"], facts=facts, family="Landmarks")
        if category != "Country Identification":
            b.add("landmark:" + site["name"], "Landmarks",
                  [("Which of these UNESCO World Heritage sites is in {name}?", dict(name=name))], site["name"],
                  _sample_options(site["name"], others, rng), expl, source=site["source"], facts=facts, family="Landmarks")


def _geography(b, c, difficulty, rng):
    name = c["name"]
    if c["region"]:
        b.add("region", "Geography / General Facts", [("In which geographic subregion is {name}?", dict(name=name))],
              c["region"], plausible_choices(c, "region", c["region"], [c["region"]], difficulty, rng),
              [("{name} is in {region}, within {continent}.", dict(name=name, region=c["region"], continent=c["continent"]))])
    near = neighbours(c)
    if near:
        other = rng.choice(near)
        b.add("border", "Geography / General Facts",
              [("Which of these countries shares a land border with {name}?", dict(name=name))], other["name"],
              plausible_choices(c, "country", other["name"], [n["name"] for n in near] + [name], difficulty, rng),
              [("{other} and {name} share a land border.", dict(other=other["name"], name=name))],
              facts=["border:" + ":".join(sorted([c["id"], other["id"]]))], family="Neighbours")
    if c["area_km2"]:
        # Require a >20% size gap so source rounding can never flip the answer.
        rivals = [o for o in COUNTRIES if o["id"] != c["id"] and o["area_km2"]
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
                  source="https://github.com/mledoze/countries",
                  facts=[f"{c['id']}:area", f"{other['id']}:area"], family="Size comparisons")
    for field, family, prompt in (
            ("domains", "Internet domains", "Which country-code internet domain belongs to {name}?"),
            ("calling_codes", "Calling codes", "Which international telephone calling code belongs to {name}?")):
        values = c[field]
        if values:
            answer = rng.choice(values)
            pool = [v for o in COUNTRIES for v in o[field] if v not in values]
            b.add(field, "Geography / General Facts", [(prompt, dict(name=name))], answer,
                  _sample_options(answer, pool, rng),
                  [("{name}: {values}.", dict(name=name, values=", ".join(values)))], family=family)


def _continents(b, c, difficulty, rng):
    options = rng.sample([x for x in CONTINENTS if x != c["continent"]], 3) + [c["continent"]]
    rng.shuffle(options)
    b.add("continent", "Continents", [("On which continent is {name}?", dict(name=c["name"]))], c["continent"],
          options, [("{name} is in {continent}.", dict(name=c["name"], continent=c["continent"]))])


def _true_false(b, c, difficulty, rng):
    name = c["name"]
    statements = [(
        ("{name} is landlocked.", dict(name=name)), c["landlocked"],
        ("{name} is landlocked." if c["landlocked"] else "{name} has a coastline.", dict(name=name)), "coast",
        "https://github.com/mledoze/countries")]

    def false_value(field, values):
        options = plausible_choices(c, field, values[0], values, difficulty, rng)
        return rng.choice([v for v in options if v not in values]) if options else None

    if c["capitals"]:
        cap = c["capitals"][0]
        truthful = rng.random() < 0.5
        stated = cap["name"] if truthful else false_value("capital", [x["name"] for x in c["capitals"]])
        if stated:
            statements.append((("{place} is the {role} of {name}.", dict(place=stated, role=cap["role"], name=name)), truthful,
                               ("{place} is the {role} of {name}.", dict(place=cap["name"], role=cap["role"], name=name)),
                               "capital", c.get("capital_source")))
    truthful = rng.random() < 0.5
    stated = c["continent"] if truthful else rng.choice([x for x in CONTINENTS if x != c["continent"]])
    statements.append((("{name} is in {continent}.", dict(name=name, continent=stated)), truthful,
                       ("{name} is in {continent}.", dict(name=name, continent=c["continent"])), "continent", None))
    currencies = [currency_label(x) for x in c["currencies"]]
    if currencies:
        truthful = rng.random() < 0.5
        stated = currencies[0] if truthful else false_value("currency", currencies)
        if stated:
            statements.append((("{name} uses {currencies}.", dict(name=name, currencies=stated)), truthful,
                               ("{name} uses {currencies}.", dict(name=name, currencies=", ".join(currencies))),
                               "currency", None))
    langs = c["official_languages"]
    if langs:
        truthful = rng.random() < 0.5
        stated = langs[0] if truthful else false_value("language", langs)
        if stated:
            statements.append((("{language} is an official language of {name}.", dict(language=stated, name=name)), truthful,
                               ("{name}: {values}.", dict(name=name, values=", ".join(langs))),
                               "language", UNGEGN_AFG if c["id"] == "AFG" else None))
    for prompt, truthful, explanation, topic, source in statements:
        b.add("truefalse:" + topic, "True or False", [prompt], "True" if truthful else "False", ["True", "False"],
              [explanation], source=source, facts=[f"{c['id']}:{topic}"])


def _leader(b, c, difficulty, rng, leaders):
    record = leaders.get(c["id"])
    if not record:
        return
    answer = " / ".join(record["names"])
    # Exclude any record sharing a person (e.g. Charles III for Canada and New Zealand).
    pool = [" / ".join(r["names"]) for r in leaders.values() if not set(r["names"]) & set(record["names"])]
    b.add("leader", "Heads of State",
          [("Who is the {title} and head of state of {name}? (Record verified {verified})",
            dict(title=record["title"], name=c["name"], verified=record["verified_on"]))],
          answer, _sample_options(answer, pool, rng),
          [("{answer} is recorded as {title} of {name}, verified {date}. Head of state and head of government can be different offices.",
            dict(answer=answer, title=record["title"], name=c["name"], date=record["verified_on"]))],
          source=record["source"])


def question_candidates(country, category, difficulty, rng, leaders) -> list[dict]:
    b = _Builder(country)
    wants = lambda *cats: category == "Mixed" or category in cats  # noqa: E731
    if wants("Capitals"):
        _capitals(b, country, difficulty, rng)
    if wants("Currency"):
        _currencies(b, country, difficulty, rng)
    if wants("Languages"):
        _languages(b, country, difficulty, rng)
    if wants("Country Identification"):
        _identification(b, country, difficulty, rng, category)
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


def valid_settings(settings) -> bool:
    required = {"continent", "country_id", "category", "difficulty", "count", "timer"}
    return (isinstance(settings, dict) and required <= settings.keys()
            and settings["continent"] in AREAS and settings["category"] in CATEGORIES
            and settings["difficulty"] in DIFFICULTIES and settings["count"] in QUESTION_COUNTS
            and (settings["country_id"] == "all" or get_country(settings["country_id"]) is not None))


def generate_quiz(settings, recent=(), recent_facts=(), seed=None, leaders=None):
    """Return (questions, capacity).

    No fact is tested twice in a round; capacity is the number of distinct facts
    available for these filters, so small pools produce honest, shorter rounds.
    """
    if not valid_settings(settings):
        return [], 0
    rng = random.Random(seed)
    leaders = load_political_records() if leaders is None else leaders
    pool = get_countries(settings["continent"], settings["country_id"])
    candidates = [q for c in pool for q in question_candidates(c, settings["category"], settings["difficulty"], rng, leaders)]
    if settings["country_id"] != "all" and settings["category"] != "Country Identification":
        # With one chosen country, "which country…?" questions answer themselves.
        chosen = pool[0]["name"]
        candidates = [q for q in candidates if q["answer"] != chosen or q["family"] == "Size comparisons"]
    candidates = list({q["id"]: q for q in candidates}.values())
    rng.shuffle(candidates)
    recent, recent_facts = set(recent), set(recent_facts)
    selected, per_country, per_family, used = [], Counter(), Counter(), set()
    while candidates:
        last_family = selected[-1]["family"] if selected else None
        best = min(candidates, key=lambda q: (bool(recent_facts.intersection(q["facts"])), per_country[q["country_id"]],
                                              per_family[q["family"]], q["country_id"] in recent,
                                              q["family"] == last_family))
        selected.append(best)
        per_country[best["country_id"]] += 1
        per_family[best["family"]] += 1
        used.update(best["facts"])
        candidates = [q for q in candidates if q is not best and not used.intersection(q["facts"])]
    return selected[:settings["count"]], len(selected)


# --------------------------------------------------------------------------- scoring & round state

def score_answer(correct, difficulty, elapsed, streak, used_hint=False, time_limit=None) -> dict:
    if not correct:
        return {"base": 0, "speed": 0, "streak": 0, "hint": 0, "total": 0}
    base = round(100 * DIFFICULTY_MULTIPLIERS[difficulty])
    speed = SPEED_BONUS if elapsed <= (time_limit / 3 if time_limit else 7) else 0
    bonus = (50 if streak % 3 == 0 else 0) + (100 if streak % 5 == 0 else 0)
    hint = HINT_PENALTY if used_hint else 0
    return {"base": base, "speed": speed, "streak": bonus, "hint": hint, "total": max(0, base + speed + bonus - hint)}


def new_round(settings, questions, available, serial) -> dict:
    return {"settings": dict(settings), "questions": questions, "available": available, "serial": serial,
            "index": 0, "selected": None, "resolved": False, "finished": False,
            "score": 0, "correct": 0, "streak": 0, "best_streak": 0,
            "hints_remaining": HINTS_PER_ROUND, "hint_used": False, "hidden_options": [],
            "history": [], "started_at": None, "perfect_bonus": 0, "last_points": None}


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
    quiz["history"].append({"question": q, "answer": choice, "correct": correct, "elapsed": taken,
                            "hint": quiz["hint_used"], "timed_out": timed_out, "points": points})
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
    return quiz["perfect_bonus"]


def statistics(quiz) -> dict:
    history, total = quiz["history"], len(quiz["questions"])
    return {"total": total, "correct": quiz["correct"],
            "incorrect": sum(not h["correct"] and not h["timed_out"] for h in history),
            "timed_out": sum(h["timed_out"] for h in history),
            "accuracy": 100 * quiz["correct"] / total if total else 0,
            "average_time": sum(h["elapsed"] for h in history) / len(history) if history else 0,
            "best_streak": quiz["best_streak"], "score": quiz["score"]}
