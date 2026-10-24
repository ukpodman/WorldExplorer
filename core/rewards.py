"""Rewards programme rules (pure Python, no Streamlit): amounts, caps, Lagos-time days and months, referral
qualification, budget figures and fraud signals.

The same caps are enforced a second time inside the database (supabase/rewards_schema.sql, trigger
reward_events_cap): the app asks for an amount, the database stores at most what the rules allow. Every reward
event has a deterministic key, so refreshing a page or repeating an action can never pay twice.

Money is handled in whole naira (integers). Nothing here decides whether money is payable: until the owner switches
on payouts (secrets [rewards] payouts_active), amounts are shown as previews only.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta, timezone
from .legal import PILOT_MAX_PLACES

LAGOS = timezone(timedelta(hours=1), "Africa/Lagos")  # West Africa Time, UTC+1 all year (no daylight saving)
KINDS = ("active_day", "quiz", "country", "referral")
KIND_LABELS = {"active_day": "Active days", "quiz": "Quizzes", "country": "Countries explored", "referral": "Referrals"}
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O or 1/I/L
CODE_RE = re.compile(r"^WE[2-9A-HJ-NP-Z]{4}$")
MIN_QUIZ_QUESTIONS = 5
COUNTRIES_FOR_ACTIVE_DAY = 2
REFERRAL_NEEDS = {"active_days": 3, "quizzes": 5, "countries": 10}
TERMS_VERSION = "2026-10-founding50-1"
PAYMENT_STATUSES = ("pending_review", "approved", "paid", "on_hold", "rejected")
PAYMENT_LABELS = {"pending_review": "Pending Review", "approved": "Approved", "paid": "Paid", "on_hold": "On Hold",
                  "rejected": "Rejected"}


@dataclass
class Settings:
    """Programme settings (one row in reward_program_settings). Category maximums are amount × count."""
    monthly_cap: int = 1000
    active_day_amount: int = 25
    active_day_max: int = 20          # rewarded active days per month (₦500)
    quiz_amount: int = 10
    quiz_max_month: int = 30          # ₦300
    quiz_max_day: int = 3
    country_amount: int = 5
    country_max_month: int = 40       # ₦200
    country_max_day: int = 5
    referral_amount: int = 50
    referral_max_month: int = 4       # ₦200
    monthly_budget: int = 50000
    max_places: int = 50
    start_date: str = "2026-10-01"
    paused: bool = False

    @classmethod
    def from_row(cls, row: dict | None) -> "Settings":
        if not row:
            return cls()
        known = {f.name: f.type for f in fields(cls)}
        values = {}
        for k, v in row.items():
            if k in known and v is not None:
                values[k] = str(v)[:10] if k == "start_date" else (bool(v) if k == "paused" else int(v))
        return cls(**values)

    def as_row(self) -> dict:
        return asdict(self)

    def amount(self, kind: str) -> int:
        return {"active_day": self.active_day_amount, "quiz": self.quiz_amount, "country": self.country_amount,
                "referral": self.referral_amount}[kind]

    def month_limit(self, kind: str) -> int:
        return {"active_day": self.active_day_max, "quiz": self.quiz_max_month, "country": self.country_max_month,
                "referral": self.referral_max_month}[kind]

    def day_limit(self, kind: str) -> int | None:
        return {"quiz": self.quiz_max_day, "country": self.country_max_day, "active_day": 1}.get(kind)

    def category_cap(self, kind: str) -> int:
        return self.amount(kind) * self.month_limit(kind)

    def validate(self) -> list[str]:
        """Problems that would make the settings unsafe (shown to the owner before saving)."""
        problems = []
        if any(getattr(self, f.name) < 0 for f in fields(self) if f.name not in ("start_date", "paused")):
            problems.append("Amounts and limits cannot be negative.")
        if self.monthly_cap <= 0:
            problems.append("The monthly maximum per person must be above zero.")
        without_referrals = sum(self.category_cap(k) for k in ("active_day", "quiz", "country"))
        if without_referrals < self.monthly_cap:
            problems.append(f"People could not reach the monthly maximum without referrals "
                            f"(₦{without_referrals:,} from activities < ₦{self.monthly_cap:,}).")
        if self.max_places > PILOT_MAX_PLACES:
            problems.append(f"The Friends & Family Pilot is limited to {PILOT_MAX_PLACES} approved participants.")
        try:
            date.fromisoformat(self.start_date)
        except ValueError:
            problems.append("The programme start date must be a date (YYYY-MM-DD).")
        return problems

    def places_by_budget(self) -> int:
        """How many people the budget can fully fund (each reserves the monthly maximum)."""
        return self.monthly_budget // self.monthly_cap if self.monthly_cap else 0


# --------------------------------------------------------------------------- time (Nigeria)

def lagos_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(LAGOS)


def day_key(now: datetime | None = None) -> str:
    return lagos_now(now).date().isoformat()


def month_key(now: datetime | None = None) -> str:
    return lagos_now(now).strftime("%Y-%m")


def previous_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def programme_started(settings: Settings, now: datetime | None = None) -> bool:
    try:
        return lagos_now(now).date() >= date.fromisoformat(settings.start_date)
    except ValueError:
        return False


# --------------------------------------------------------------------------- codes and keys

def new_referral_code(rng=None) -> str:
    choice = (rng or secrets.SystemRandom()).choice
    return "WE" + "".join(choice(CODE_ALPHABET) for _ in range(4))


def valid_code(code) -> bool:
    return isinstance(code, str) and bool(CODE_RE.match(code))


def event_key(profile_id: str, kind: str, subject: str, month: str) -> str:
    """Deterministic: the same activity always maps to the same key (the database ignores repeats).
    Quizzes are keyed by their round id, countries once per month, active days once per day, referrals once."""
    if kind == "quiz":
        return f"quiz:{profile_id}:{subject}"
    if kind == "country":
        return f"country:{profile_id}:{month}:{subject}"
    if kind == "active_day":
        return f"active:{profile_id}:{subject}"
    if kind == "referral":
        return f"referral:{subject}"
    raise ValueError(kind)


# --------------------------------------------------------------------------- amounts

def award(kind: str, month_events: list[dict], day: str, settings: Settings, eligible: bool) -> tuple[int, str]:
    """The amount a new event may earn, given the person's other events this month (same test flag).
    Returns (amount, reason); reason explains a zero ("not_enrolled", "day_limit", "month_limit", "monthly_cap"…)."""
    if not eligible:
        return 0, "not_enrolled"
    if settings.paused:
        return 0, "paused"
    paid = [e for e in month_events if int(e.get("amount") or 0) > 0]
    same = [e for e in paid if e.get("kind") == kind]
    limit_day = settings.day_limit(kind)
    if limit_day is not None and sum(1 for e in same if e.get("day") == day) >= limit_day:
        return 0, "day_limit"
    if len(same) >= settings.month_limit(kind):
        return 0, "month_limit"
    amount = settings.amount(kind)
    room_category = settings.category_cap(kind) - sum(int(e["amount"]) for e in same)
    room_total = settings.monthly_cap - sum(int(e["amount"]) for e in paid)
    amount = min(amount, room_category, room_total)
    if amount <= 0:
        return 0, "monthly_cap"
    return amount, "awarded" if amount == settings.amount(kind) else "partial_cap"


def qualifying_quiz(quiz: dict) -> bool:
    """A finished, genuine round of at least five questions (practice replays of the Daily Challenge do not count;
    the score never matters)."""
    return bool(quiz and quiz.get("finished") and quiz.get("mode") != "daily_replay"
                and len(quiz.get("questions", [])) >= MIN_QUIZ_QUESTIONS
                and len(quiz.get("history", [])) >= len(quiz.get("questions", [])))


def active_day_due(day_events: list[dict]) -> bool:
    """A day counts once the person finished a qualifying quiz or explored two different countries that day
    (opening the app or signing in alone never counts)."""
    quizzes = sum(1 for e in day_events if e.get("kind") == "quiz")
    countries = {e.get("subject") for e in day_events if e.get("kind") == "country"}
    return quizzes >= 1 or len(countries) >= COUNTRIES_FOR_ACTIVE_DAY


def summarize(month_events: list[dict]) -> dict:
    """Per-category counts (rewarded events) and amounts for one person and month."""
    out = {k: {"count": 0, "amount": 0} for k in KINDS}
    for e in month_events:
        amount = int(e.get("amount") or 0)
        if amount > 0 and e.get("kind") in out:
            out[e["kind"]]["count"] += 1
            out[e["kind"]]["amount"] += amount
    out["total"] = sum(out[k]["amount"] for k in KINDS)
    return out


def activity_totals(events: list[dict]) -> dict:
    """Genuine activity regardless of rewards (used for referral qualification and analytics)."""
    return {"active_days": len({e.get("subject") for e in events if e.get("kind") == "active_day"}),
            "quizzes": sum(1 for e in events if e.get("kind") == "quiz"),
            "countries": len({e.get("subject") for e in events if e.get("kind") == "country"})}


def referral_qualifies(totals: dict) -> bool:
    return all(totals.get(k, 0) >= v for k, v in REFERRAL_NEEDS.items())


def referral_progress(totals: dict) -> dict:
    return {k: (min(totals.get(k, 0), v), v) for k, v in REFERRAL_NEEDS.items()}


# --------------------------------------------------------------------------- budget

def budget_figures(settings: Settings, enrolments: list[dict], events: list[dict], payments: list[dict]) -> dict:
    """Owner figures for one month (real records only: callers pass test=False rows)."""
    enrolled = [e for e in enrolments if e.get("status") == "enrolled"]
    reserved = sum(int(e.get("reserved_amount") or 0) for e in enrolments if e.get("status") in ("enrolled", "withdrawn"))
    earned = sum(int(e.get("amount") or 0) for e in events)
    approved = sum(int(p.get("approved_amount") or 0) for p in payments if p.get("status") in ("approved", "paid"))
    paid = sum(int(p.get("paid_amount") or 0) for p in payments if p.get("status") == "paid")
    pending = sum(int(p.get("earned") or 0) for p in payments if p.get("status") == "pending_review")
    return {"allocated": settings.monthly_budget, "reserved": reserved, "earned": earned,
            "pending": pending, "approved": approved, "paid": paid,
            "unreserved": max(settings.monthly_budget - reserved, 0), "participants": len(enrolled),
            "waitlist": sum(1 for e in enrolments if e.get("status") == "waitlist"),
            "places": settings.max_places, "average": round(earned / len(enrolled)) if enrolled else 0}


# --------------------------------------------------------------------------- fraud signals (proportionate)

def fraud_signals(account: dict, events: list[dict], referrals_made: list[dict], visits: list[dict]) -> list[str]:
    """Patterns worth a manual look. They never block anyone automatically; two people sharing a household or a
    device are not treated as fraud."""
    flags = []
    quizzes = [e for e in events if e.get("kind") == "quiz"]
    fast = [e for e in quizzes if (e.get("detail") or {}).get("avg_seconds", 99) < 1.5]
    if len(fast) >= 3:
        flags.append(f"Unusual quiz activity: {len(fast)} rounds answered in under 1.5 s per question")
    by_day: dict = {}
    for e in quizzes:
        by_day[e.get("day")] = by_day.get(e.get("day"), 0) + 1
    busy = [d for d, n in by_day.items() if n >= 15]
    if busy:
        flags.append(f"Unusual quiz activity: 15+ rounds on {len(busy)} day(s)")
    stamps = sorted(_dt(r.get("created_at")) for r in referrals_made if r.get("created_at"))
    for i in range(len(stamps)):
        burst = [s for s in stamps[i:] if s - stamps[i] <= timedelta(hours=24)]
        if len(burst) >= 5:
            flags.append(f"Suspicious registrations: {len(burst)} referred sign-ups within 24 hours")
            break
    attempts = [v for v in visits if v.get("outcome") in ("existing_account", "self", "already_referred")]
    if len(attempts) >= 3:
        flags.append(f"Duplicate referral attempts: {len(attempts)} with this person's link")
    quick = [r for r in referrals_made if r.get("status") == "qualified" and r.get("qualified_at") and r.get("created_at")
             and _dt(r["qualified_at"]) - _dt(r["created_at"]) < timedelta(days=3)]
    if len(quick) >= 2:
        flags.append(f"Suspicious earning pattern: {len(quick)} referrals qualified in under 3 days")
    if account.get("review") in ("review", "hold"):
        flags.append("Marked for manual review by the owner")
    return flags


def _dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- payments

def payment_transition(current: dict, status: str, amount: int | None, earned: int) -> tuple[dict, str | None]:
    """Validate an owner's payment update. Returns (changes, error). Paid always needs an explicit owner action and an
    approved amount; the approved amount can never exceed what was earned, and the paid amount never exceeds it."""
    if status not in PAYMENT_STATUSES:
        return {}, "Unknown status."
    approved = int(current.get("approved_amount") or 0)
    changes: dict = {"status": status}
    if status == "approved":
        value = earned if amount is None else int(amount)
        if value <= 0 or value > earned:
            return {}, f"The approved amount must be between ₦1 and the earned ₦{earned:,}."
        changes["approved_amount"] = value
    elif status == "paid":
        if current.get("status") != "approved" or approved <= 0:
            return {}, "Only an approved payment can be marked as paid."
        value = approved if amount is None else int(amount)
        if value <= 0 or value > approved:
            return {}, f"The paid amount must be between ₦1 and the approved ₦{approved:,}."
        changes["paid_amount"] = value
    elif status in ("rejected", "on_hold", "pending_review"):
        if current.get("status") == "paid":
            return {}, "A completed payment cannot be changed. Record a correction in the remarks instead."
        if status == "rejected":
            changes["approved_amount"] = 0
    return changes, None


# --------------------------------------------------------------------------- owner analytics

ANALYTICS_DEFINITIONS = {
    "registered": "Total registered users: saved player profiles (signed-in accounts) in world_explorer_profiles.",
    "new": "New registrations: reward accounts created for a brand-new profile in the period (counted while the "
           "programme is visible to that person).",
    "active": "Daily / weekly / monthly active users: distinct people with any measured event on the current Nigeria "
              "day, the last 7 days and the last 30 days (only visitors who allowed usage statistics).",
    "retention": "N-day retention: people active again on a day at least N days after their first measured day ÷ "
                 "people first seen at least N days ago.",
    "participants": "Participants: real (not test) enrolments with status 'enrolled' for the month; waiting list "
                    "counted separately.",
    "conversion": "Referral conversion: new accounts attributed to a link ÷ link visits; success rate: completed or "
                  "approved referrals ÷ attributed accounts.",
    "cost": "Cost per retained active user: rewards earned this month ÷ participants with at least 3 active days "
            "this month.",
}


def _lagos_day(value) -> str:
    return _dt(value).astimezone(LAGOS).date().isoformat()


def activity_overview(events: list[dict], now: datetime | None = None) -> dict:
    """DAU/WAU/MAU and 7/30-day retention from prepared analytics events (core.metrics.prepare: each event has a
    person id in "_p" and a timestamp in "_t")."""
    today = lagos_now(now).date()
    days_by_person: dict = {}
    for ev in events:
        person = ev.get("_p")
        if not person:
            continue
        days_by_person.setdefault(person, set()).add(_lagos_day(ev["_t"]))

    def active_within(n: int) -> int:
        start = (today - timedelta(days=n - 1)).isoformat()
        return sum(1 for days in days_by_person.values() if any(d >= start for d in days))

    def retention(n: int) -> dict:
        eligible = retained = 0
        for days in days_by_person.values():
            first = date.fromisoformat(min(days))
            if (today - first).days < n:
                continue
            eligible += 1
            if any((date.fromisoformat(d) - first).days >= n for d in days):
                retained += 1
        return {"n": retained, "d": eligible, "pct": round(100 * retained / eligible, 1) if eligible else None}

    return {"people": len(days_by_person), "dau": active_within(1), "wau": active_within(7), "mau": active_within(30),
            "retention7": retention(7), "retention30": retention(30)}


def referral_overview(accounts: list[dict], visits: list[dict], referrals: list[dict], events: list[dict]) -> dict:
    """Programme-wide referral figures (callers pass real records only)."""
    attributed = len(referrals)
    success = sum(1 for r in referrals if r.get("status") in ("qualified", "approved"))
    return {"links": len(accounts), "visits": len(visits), "registrations": attributed,
            "approved": sum(1 for r in referrals if r.get("status") == "approved"),
            "qualified": sum(1 for r in referrals if r.get("status") == "qualified"),
            "pending": sum(1 for r in referrals if r.get("status") == "pending"),
            "rejected": sum(1 for r in referrals if r.get("status") == "rejected"),
            "conversion": round(100 * attributed / len(visits), 1) if visits else None,
            "success_rate": round(100 * success / attributed, 1) if attributed else None,
            "earnings": sum(int(e.get("amount") or 0) for e in events if e.get("kind") == "referral")}


def cost_per_retained(month_events: list[dict], participants: list[str]) -> dict:
    """Rewards earned this month ÷ participants with at least 3 active days this month."""
    earned = sum(int(e.get("amount") or 0) for e in month_events)
    active = {}
    for e in month_events:
        if e.get("kind") == "active_day":
            active.setdefault(e.get("profile_id"), set()).add(e.get("subject"))
    retained = sum(1 for p in participants if len(active.get(p, ())) >= 3)
    return {"earned": earned, "retained": retained, "cost": round(earned / retained) if retained else None}


def fraud_overview(flags_by_profile: dict[str, list[str]]) -> dict:
    """Counts of accounts per fraud category (from fraud_signals)."""
    def count(prefix: str) -> int:
        return sum(1 for flags in flags_by_profile.values() if any(f.startswith(prefix) for f in flags))
    return {"registrations": count("Suspicious registrations"), "duplicates": count("Duplicate referral"),
            "quiz": count("Unusual quiz"), "earning": count("Suspicious earning"),
            "review": count("Marked for manual review"),
            "flagged": sum(1 for flags in flags_by_profile.values() if flags)}
