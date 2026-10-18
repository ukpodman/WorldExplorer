"""Unfinished quiz rounds saved with the signed-in player's profile, so a refresh, a closed browser or a lost
connection (a phone call, another app) does not end the round.

The round is stored inside the existing profile JSON (world_explorer_profiles.profile, key "active_round"): no new
table and no migration. It is written by the same server-side save as points and badges, in the same request, so
points and the round can never be saved apart.

What is kept: the exact questions in their order, the current question, every recorded answer with its points, score,
streak, hints, settings and mode (regular, daily, practice). Nothing is scored again on restore: answers already
recorded stay recorded, and an answered question cannot be answered twice.

Timed rounds: the moment the current question was first shown is kept as wall-clock time, so the time that passed
while the player was away still counts. Leaving cannot buy extra time; a question whose time ran out is recorded as
timed out, as before.
"""

from __future__ import annotations

import time

VERSION = 1
MAX_QUESTIONS = 60          # rounds are at most 50 questions; anything larger is not a real round
MODES = ("regular", "daily", "daily_replay", "practice")
_ROUND_KEYS = ("settings", "questions", "available", "serial", "index", "selected", "resolved", "finished", "score",
               "correct", "streak", "best_streak", "hints_remaining", "hint_used", "hidden_options", "history",
               "perfect_bonus", "last_points", "event", "mode", "day", "uid", "badges_before", "round_recorded",
               "records_outcome")


def _wall_presented(quiz: dict, now_mono: float, now_wall: float) -> float | None:
    """Wall-clock time the current question was first shown (kept on the round, so it is computed once)."""
    started = quiz.get("started_at")
    if started is None:
        return None
    if quiz.get("_wall_for") != started:
        quiz["_wall_for"] = started
        quiz["_wall_presented"] = round(now_wall - (now_mono - started), 3)
    return quiz["_wall_presented"]


def _pack_round(quiz: dict, now_mono: float, now_wall: float) -> dict | None:
    if not isinstance(quiz, dict) or quiz.get("finished") or not quiz.get("questions"):
        return None
    out = {k: quiz.get(k) for k in _ROUND_KEYS if k in quiz}
    questions = quiz["questions"]
    out["history"] = []
    for h in quiz.get("history", []):   # each answer refers to its question by position (no copy of the question)
        entry = {k: v for k, v in h.items() if k != "question"}
        try:
            entry["qi"] = questions.index(h["question"])
        except (ValueError, KeyError):
            return None
        out["history"].append(entry)
    out["presented_wall"] = _wall_presented(quiz, now_mono, now_wall)
    out["paused_elapsed"] = quiz.get("paused_elapsed")
    return out


def pack(ss, now_mono: float | None = None, now_wall: float | None = None) -> dict | None:
    """The unfinished rounds of this session as plain JSON data, or None when there is nothing to keep."""
    now_mono = time.monotonic() if now_mono is None else now_mono
    now_wall = time.time() if now_wall is None else now_wall
    current = _pack_round(ss.get("quiz"), now_mono, now_wall)
    parked = {}
    for group, q in (ss.get("parked_rounds") or {}).items():
        packed = _pack_round(q, now_mono, now_wall)
        if packed:
            parked[group] = packed
    if not current and not parked:
        return None
    return {"v": VERSION, "current": current, "parked": parked}


def _valid_question(q) -> bool:
    return (isinstance(q, dict) and isinstance(q.get("choices"), list) and len(q["choices"]) in (2, 4)
            and q.get("answer") in q["choices"] and isinstance(q.get("prompt"), (list, str)))


def _unpack_round(data, now_mono: float, now_wall: float) -> dict | None:
    """A saved round back in engine form, or None if anything is missing or inconsistent (never a broken round)."""
    try:
        if not isinstance(data, dict) or data.get("finished"):
            return None
        questions = data["questions"]
        if not isinstance(questions, list) or not 0 < len(questions) <= MAX_QUESTIONS or not all(map(_valid_question, questions)):
            return None
        index, history = data["index"], data["history"]
        if not (isinstance(index, int) and 0 <= index < len(questions) and isinstance(history, list)):
            return None
        resolved = bool(data["resolved"])
        if len(history) != index + (1 if resolved else 0):   # one recorded answer per question already passed
            return None
        if data.get("mode", "regular") not in MODES or not isinstance(data.get("settings"), dict):
            return None
        quiz = {k: data[k] for k in _ROUND_KEYS if k in data}
        quiz["history"] = []
        for h in history:
            qi = h.get("qi") if isinstance(h, dict) else None
            if not isinstance(qi, int) or not 0 <= qi < len(questions):
                return None
            entry = {k: v for k, v in h.items() if k != "qi"}
            entry["question"] = questions[qi]
            quiz["history"].append(entry)
        for key in ("score", "correct", "streak", "best_streak", "hints_remaining", "serial"):
            if not isinstance(quiz.get(key), int) or quiz[key] < 0:
                return None
        if quiz["correct"] > len(history) or not isinstance(quiz.get("hidden_options", []), list):
            return None
        if resolved and not isinstance(quiz.get("event"), dict):
            return None
        quiz.setdefault("hidden_options", [])
        quiz.setdefault("event", None)
        quiz["resolved"], quiz["finished"] = resolved, False
        quiz["created"] = -1e9            # never mistaken for a double click on Start
        quiz["started_at"] = None
        presented = data.get("presented_wall")
        timed = bool(quiz["settings"].get("timer"))
        if not resolved and timed and isinstance(presented, (int, float)):
            # the clock kept running while the player was away (a refresh, a closed browser)
            quiz["started_at"] = now_mono - max(0.0, now_wall - float(presented))
        elif not resolved and not timed:
            paused = data.get("paused_elapsed")
            quiz["paused_elapsed"] = float(paused) if isinstance(paused, (int, float)) and paused >= 0 else 0.0
        return quiz
    except (KeyError, TypeError, ValueError):
        return None


def unpack(data, now_mono: float | None = None, now_wall: float | None = None) -> tuple[dict | None, dict]:
    """(current round, parked rounds by group) from saved data; anything invalid is left out."""
    now_mono = time.monotonic() if now_mono is None else now_mono
    now_wall = time.time() if now_wall is None else now_wall
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return None, {}
    current = _unpack_round(data.get("current"), now_mono, now_wall)
    parked = {}
    for group, q in (data.get("parked") or {}).items() if isinstance(data.get("parked"), dict) else []:
        r = _unpack_round(q, now_mono, now_wall)
        if r and group in ("regular", "daily", "practice"):
            parked[group] = r
    return current, parked
