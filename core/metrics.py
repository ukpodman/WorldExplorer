"""Pilot metrics from the analytics events (pure Python; used by the owner dashboard and the tests).

All days are UTC calendar days, the same day boundary as the Daily Challenge. A "person" is one pseudonymous id;
a guest id that later signed in ("link" event) is merged into that signed-in person. Only visitors who allowed
usage statistics are measured. Each metric below states its numerator and denominator in DEFINITIONS.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

PENDING_ROUND = timedelta(hours=1)   # a first round started within the last hour may still be finished
RETURN_WINDOW = timedelta(days=7)

DEFINITIONS = {
    "people": "Measured people: distinct pseudonymous ids with at least one event (guest ids merged into the "
              "signed-in person after “Save progress with Google”). Only visitors who allowed usage statistics.",
    "new": "New visitors: people whose first-ever event falls inside the selected period.",
    "returning": "Returning visitors: people active in the selected period on a UTC day after the day they were "
                 "first seen.",
    "rounds": "Quiz starts / completions: round_start and round_complete events in the period, by mode. A daily "
              "“first counted completion” is a completed round of mode daily (only the first attempt of a day "
              "can have that mode); replays and mistake practice are counted separately. “Daily person-days” counts "
              "each person once per Daily Challenge day.",
    "first_round": "First-round completion rate = people whose first started round (any mode except replay) was "
                   "completed ÷ people who started a first round. First rounds started in the last hour are "
                   "pending and left out. Uses all data, not just the period.",
    "return7": "Return within 7 days = people with any event on a later UTC day within 7×24 h after their first "
               "completed round ÷ people whose first completed round was at least 7×24 h ago (their full window has "
               "elapsed). People still inside their window are listed as pending. Uses all data.",
    "active3": "Active on 3+ days = people with events on at least three distinct UTC days ÷ all measured people. "
               "Uses all data.",
    "signed_in": "Guest vs signed-in: a person counts as signed-in if any of their events was signed in.",
    "declined": "“No thanks” answers: anonymous count of visitors who declined usage statistics (no id, so they "
                "cannot be counted as people). Shows how much traffic is not measured.",
}


def _ts(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    stamp = datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _canonical(events: list[dict]) -> dict:
    """guest id -> signed-in id, from link events (a guest linked to two accounts keeps the first)."""
    alias = {}
    for ev in sorted(events, key=lambda e: e["_t"]):
        if ev.get("event") == "link" and ev.get("linked_id") and ev.get("anon_id"):
            alias.setdefault(ev["linked_id"], ev["anon_id"])
    return alias


def prepare(rows: list[dict], include_test: bool = False) -> tuple[list[dict], int]:
    """Parsed, merged events (oldest first) and the number of excluded test/owner events.

    Excluded unless include_test: every event of any person who has at least one test-flagged event
    (owner accounts, browsers marked as test traffic)."""
    events = []
    for row in rows:
        try:
            ev = dict(row, _t=_ts(row["occurred_at"]))
        except Exception:
            continue
        events.append(ev)
    alias = _canonical(events)
    for ev in events:
        ev["_p"] = alias.get(ev.get("anon_id"), ev.get("anon_id"))
    excluded = 0
    if not include_test:
        flagged = {ev["_p"] for ev in events if ev.get("test") and ev["_p"]}
        kept = [ev for ev in events if not ev.get("test") and ev["_p"] not in flagged]
        excluded = len(events) - len(kept)
        events = kept
    events.sort(key=lambda e: e["_t"])
    return events, excluded


def _rate(n: int, d: int) -> dict:
    return {"n": n, "d": d, "pct": (100 * n / d) if d else None}


def compute(rows: list[dict], now: datetime, period_days: int | None = None, include_test: bool = False) -> dict:
    events, excluded = prepare(rows, include_test)
    start = (now - timedelta(days=period_days)) if period_days else None
    in_period = (lambda t: t >= start and t <= now) if start else (lambda t: t <= now)
    declined = sum(1 for ev in events if ev.get("event") == "consent_declined" and in_period(ev["_t"]))
    events = [ev for ev in events if ev["_p"] and ev.get("event") != "consent_declined" and ev["_t"] <= now]

    first_seen, days, signed, device = {}, defaultdict(set), defaultdict(bool), {}
    for ev in events:
        p = ev["_p"]
        first_seen.setdefault(p, ev["_t"])
        days[p].add(ev["_t"].date())
        signed[p] |= bool(ev.get("signed_in"))
        if ev.get("device"):
            device[p] = ev["device"]
    people = list(first_seen)

    by_person = defaultdict(list)
    for ev in events:
        by_person[ev["_p"]].append(ev)
    active_in_period = {ev["_p"] for ev in events if in_period(ev["_t"])}
    new = [p for p in people if in_period(first_seen[p])]
    returning = [p for p in active_in_period
                 if any(in_period(ev["_t"]) and ev["_t"].date() > first_seen[p].date() for ev in by_person[p])]

    # rounds by mode inside the period
    rounds = {m: {"starts": 0, "completions": 0, "people_started": set(), "people_completed": set()}
              for m in ("regular", "daily", "daily_replay", "practice")}
    for ev in events:
        if ev.get("event") in ("round_start", "round_complete") and in_period(ev["_t"]) and ev.get("mode") in rounds:
            r = rounds[ev["mode"]]
            if ev["event"] == "round_start":
                r["starts"] += 1
                r["people_started"].add(ev["_p"])
            else:
                r["completions"] += 1
                r["people_completed"].add(ev["_p"])
    rounds = {m: {"starts": r["starts"], "completions": r["completions"], "people_started": len(r["people_started"]),
                  "people_completed": len(r["people_completed"])} for m, r in rounds.items()}
    # A person can have two "first" daily completions on one day if they played as a guest in two browsers before
    # signing in; distinct person-days count each person once per Daily Challenge day.
    daily_person_days = len({(ev["_p"], ev.get("day") or ev["_t"].date().isoformat()) for ev in events
                             if ev.get("event") == "round_complete" and ev.get("mode") == "daily" and in_period(ev["_t"])})

    # first-round completion (all data)
    completed_keys = {(ev["_p"], ev.get("round_id")) for ev in events if ev.get("event") == "round_complete"}
    first_start = {}
    for ev in events:
        if ev.get("event") == "round_start" and ev.get("mode") != "daily_replay":
            first_start.setdefault(ev["_p"], ev)
    eligible = [p for p, ev in first_start.items() if now - ev["_t"] >= PENDING_ROUND or (p, ev.get("round_id")) in completed_keys]
    done_first = [p for p in eligible if (p, first_start[p].get("round_id")) in completed_keys]

    # return within 7 days of the first completed (non-replay) round (all data)
    first_complete = {}
    for ev in events:
        if ev.get("event") == "round_complete" and ev.get("mode") != "daily_replay":
            first_complete.setdefault(ev["_p"], ev["_t"])
    cohort = [p for p, t in first_complete.items() if now - t >= RETURN_WINDOW]
    pending = len(first_complete) - len(cohort)
    returned = [p for p in cohort
                if any(first_complete[p] < ev["_t"] <= first_complete[p] + RETURN_WINDOW
                       and ev["_t"].date() > first_complete[p].date() for ev in by_person[p])]

    active3 = [p for p in people if len(days[p]) >= 3]
    signed_people = [p for p in people if signed[p]]

    # daily participation per UTC day (last 14 days with data)
    per_day = defaultdict(lambda: {"active": set(), "daily_first": set(), "rounds_completed": 0})
    for ev in events:
        d = per_day[ev["_t"].date()]
        d["active"].add(ev["_p"])
        if ev.get("event") == "round_complete":
            d["rounds_completed"] += 1
            if ev.get("mode") == "daily":
                d["daily_first"].add(ev["_p"])   # people, so a person counts once per day
    daily_table = [{"day": day.isoformat(), "active": len(v["active"]), "daily_first": len(v["daily_first"]),
                    "rounds_completed": v["rounds_completed"]} for day, v in sorted(per_day.items())][-14:]

    devices = defaultdict(int)
    for p in people:
        devices[device.get(p, "unknown")] += 1

    return {"people": len(people), "new": len(new), "returning": len(returning), "active_in_period": len(active_in_period),
            "rounds": rounds, "daily_person_days": daily_person_days, "first_round": _rate(len(done_first), len(eligible)),
            "return7": dict(_rate(len(returned), len(cohort)), pending=pending),
            "active3": _rate(len(active3), len(people)),
            "signed_in": {"signed_in": len(signed_people), "guest": len(people) - len(signed_people),
                          "linked": len({ev["linked_id"] for ev in events if ev.get("event") == "link"})},
            "devices": dict(devices), "declined": declined, "excluded_events": excluded, "daily_table": daily_table,
            "period_days": period_days, "now": now.isoformat(timespec="minutes")}
