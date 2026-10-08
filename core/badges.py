"""Badges and the activity statistics they are earned from.

Pure Python (no Streamlit). Statistics change only when a quiz answer or a finished
round is recorded, never when a page is opened, so reruns cannot award anything twice.
Badges are derived from the statistics (plus the existing points and rounds totals),
which keeps them consistent with saved profiles from earlier versions.
"""
from __future__ import annotations

from .data import CONTINENTS, get_country

STAT_COUNTERS = ("answered", "correct", "perfect_rounds", "flags_correct")


def empty_stats() -> dict:
    return {**{k: 0 for k in STAT_COUNTERS}, "correct_by_continent": {c: 0 for c in CONTINENTS}}


def sanitize_stats(value) -> dict | None:
    """Validated copy of stored statistics, or None if the value is unusable. Missing fields default to 0."""
    if not isinstance(value, dict):
        return None
    out = empty_stats()
    for key in STAT_COUNTERS:
        v = value.get(key, 0)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[key] = v
    by = value.get("correct_by_continent", {})
    if isinstance(by, dict):
        for c in CONTINENTS:
            v = by.get(c, 0)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out["correct_by_continent"][c] = v
    return out


def record_answer(stats: dict, question: dict, correct: bool) -> None:
    """Call once per recorded answer (timeouts count as answered, not correct)."""
    stats["answered"] += 1
    if not correct:
        return
    stats["correct"] += 1
    if question.get("family") == "Flags":
        stats["flags_correct"] += 1
    country = get_country(question.get("country_id"))
    if country:
        stats["correct_by_continent"][country["continent"]] += 1


def record_round(stats: dict, quiz: dict) -> None:
    """Call once when a round finishes."""
    if quiz.get("perfect_bonus"):
        stats["perfect_rounds"] += 1


def _continent_badge(continent: str) -> dict:
    return {"id": "continent_" + continent.lower().replace(" ", "_"), "name": "{continent} Explorer",
            "fields": {"continent": continent}, "symbol": "◎",
            "description": "Answer 5 questions about {continent} correctly.",
            "progress": lambda s, points, rounds, c=continent: (s["correct_by_continent"][c], 5)}


BADGES = [
    {"id": "first_steps", "name": "First Steps", "symbol": "✦", "description": "Answer your first question correctly.",
     "progress": lambda s, points, rounds: (1 if points > 0 or s["correct"] > 0 else 0, 1)},
    {"id": "century", "name": "Century", "symbol": "★", "description": "Earn 100 points.",
     "progress": lambda s, points, rounds: (min(points, 100), 100)},
    {"id": "round_finisher", "name": "Round Finisher", "symbol": "✓", "description": "Complete your first quiz round.",
     "progress": lambda s, points, rounds: (min(rounds, 1), 1)},
    {"id": "five_rounds", "name": "Seasoned Explorer", "symbol": "⚑", "description": "Complete 5 quiz rounds.",
     "progress": lambda s, points, rounds: (min(rounds, 5), 5)},
    {"id": "perfect_round", "name": "Flawless", "symbol": "◆", "description": "Finish a round with every answer correct and no hints.",
     "progress": lambda s, points, rounds: (min(s["perfect_rounds"], 1), 1)},
    {"id": "flag_spotter", "name": "Flag Spotter", "symbol": "⚐", "description": "Identify 10 flags correctly.",
     "progress": lambda s, points, rounds: (min(s["flags_correct"], 10), 10)},
    {"id": "fifty_correct", "name": "Sharp Mind", "symbol": "✺", "description": "Give 50 correct answers.",
     "progress": lambda s, points, rounds: (min(s["correct"], 50), 50)},
    *[_continent_badge(c) for c in CONTINENTS],
    {"id": "globetrotter", "name": "Globetrotter", "symbol": "✈", "description": "Answer at least one question correctly about every continent.",
     "progress": lambda s, points, rounds: (sum(1 for c in CONTINENTS if s["correct_by_continent"][c] > 0), len(CONTINENTS))},
]


def evaluate(stats: dict, points: int, rounds: int) -> list[dict]:
    """Every badge with its progress: {id, name, fields, symbol, description, value, target, earned}."""
    out = []
    for badge in BADGES:
        value, target = badge["progress"](stats, points, rounds)
        value = min(value, target)
        out.append({"id": badge["id"], "name": badge["name"], "fields": badge.get("fields", {}), "symbol": badge["symbol"],
                    "description": badge["description"], "value": value, "target": target, "earned": value >= target})
    return out


def earned_ids(stats: dict, points: int, rounds: int) -> set[str]:
    return {b["id"] for b in evaluate(stats, points, rounds) if b["earned"]}
