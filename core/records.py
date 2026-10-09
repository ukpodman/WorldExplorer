"""Personal records and medals (pure Python, no Streamlit).

* Medals depend on accuracy only, never on points or streak multipliers:
  gold >= 90 %, silver >= 70 %, bronze >= 50 %, no medal below 50 %.
* Score records are kept per exact round settings (area, places, category, difficulty,
  question count, timer and flag-question choice), so a score is only ever compared with
  rounds that were played under the same rules.
* The best answer streak is a single record across all rounds (a streak counts answers,
  so it does not depend on difficulty or points).
* ``update`` is called once per finished round; the quiz is marked so a second call
  (double click, rerun) changes nothing.
"""
from __future__ import annotations

MEDALS = ((90, "gold"), (70, "silver"), (50, "bronze"))
MAX_SCORE_RECORDS = 60  # keeps saved profiles small; the oldest settings are dropped first
SETTING_FIELDS = ("collection", "continent", "country_id", "category", "difficulty", "count", "timer", "flags")


def medal(accuracy: float) -> str | None:
    """'gold', 'silver', 'bronze' or None for an accuracy percentage (0-100)."""
    return next((name for threshold, name in MEDALS if accuracy >= threshold), None)


def empty_records() -> dict:
    return {"best_streak": 0, "scores": {}}


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def sanitize_records(value) -> dict | None:
    """Validated copy of stored records, or None if unusable. Missing fields get defaults."""
    if not isinstance(value, dict):
        return None
    out = empty_records()
    if _count(value.get("best_streak")):
        out["best_streak"] = value["best_streak"]
    scores = value.get("scores", {})
    if isinstance(scores, dict):
        valid = [(k, v) for k, v in scores.items() if isinstance(k, str) and len(k) <= 200 and _count(v)]
        out["scores"] = dict(valid[-MAX_SCORE_RECORDS:])
    return out


def settings_key(settings: dict) -> str:
    """Identifies equivalent rounds. Flag questions only matter for the Mixed category."""
    s = dict(settings)
    if s.get("category") != "Mixed":
        s["flags"] = None
    return "|".join(str(s.get(f)) for f in SETTING_FIELDS)


def update(records: dict, quiz: dict) -> dict:
    """Apply a finished round to `records` once; returns (and stores on the quiz) the outcome
    shown on the results screen. Later calls return the stored outcome unchanged."""
    if quiz.get("records_outcome") is not None:
        return quiz["records_outcome"]
    key = settings_key(quiz["settings"])
    previous_score = records["scores"].get(key)
    previous_streak = records["best_streak"]
    score, streak = quiz["score"], quiz["best_streak"]
    new_score = previous_score is None or score > previous_score
    if new_score:
        records["scores"].pop(key, None)  # re-insert so recently played settings are kept longest
        records["scores"][key] = score
        while len(records["scores"]) > MAX_SCORE_RECORDS:
            records["scores"].pop(next(iter(records["scores"])))
    new_streak = streak > previous_streak
    if new_streak:
        records["best_streak"] = streak
    quiz["records_outcome"] = {"key": key, "previous_score": previous_score, "best_score": max(score, previous_score or 0),
                               "new_score": new_score and previous_score is not None, "first_score": previous_score is None,
                               "previous_streak": previous_streak, "best_streak": records["best_streak"],
                               "new_streak": new_streak and streak > 0}
    return quiz["records_outcome"]
