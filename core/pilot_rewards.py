"""WORLD EXPLORER — FRIENDS & FAMILY 10: provisional rewards for the private pilot (pure Python, no Streamlit).

The same rules run in three places: here (the app's display and the in-memory store), and in the database
(supabase/friends_family10_migration.sql), which is the authority. Tests run the scenarios against both.

Verified active learning time
* Time comes only from meaningful learning interactions the app records on the server, with the database's own clock
  (answering a quiz question, finishing a quiz or the Daily Challenge, opening a country's details, moving between
  countries in Learn or Explore). Opening the app, refreshing, or leaving a page open records nothing.
* An interaction is ignored when the same interaction (same kind and subject) was already recorded in the last
  REPEAT_SECONDS: repeating one action does not add time.
* All interactions of one day form one timeline, whatever the number of tabs or devices: the time between two
  consecutive interactions counts up to INACTIVITY_SECONDS. Overlapping sessions can never count twice, and the total
  can never exceed real time.

Daily tiers (cumulative totals for the day, not added together; each tier needs the milestones of the tiers below)
    15 min + 1 qualifying quiz                                  ₦100
    30 min + 2 qualifying quizzes                               ₦250
    45 min + the above + 1 country explored for the first time  ₦350
    60 min + the above + the Daily Challenge completed          ₦500
* A qualifying quiz is a finished round of at least five questions (core.rewards.qualifying_quiz). The Daily Challenge
  is its own milestone and is not counted as one of the two quizzes.
* Each day's amount is limited so that the month never exceeds MONTHLY_MAX per participant.

Monthly settlement (shared budget)
* Provisional amounts are never payable. After the month ends the Owner finalises a settlement: if the total of all
  participants' provisional amounts is within the budget, everybody's final allocation equals their provisional
  amount and the rest of the budget stays unspent; otherwise the budget is shared in proportion (largest-remainder
  method in whole naira, ties broken by profile id, so the result is deterministic, sums to exactly the budget and no
  one receives more than their provisional amount).
* Final allocations still need the Owner's approval per participant, and actual payment stays disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.rewards import _dt, lagos_now

PROGRAMME = "Friends & Family 10"
TITLE = "World Explorer — Friends & Family 10"
MAX_PARTICIPANTS = 10
MONTHLY_BUDGET = 50_000
DAILY_MAX = 500
MONTHLY_MAX = 7_000
MIN_MINUTES = 15
MAX_MINUTES = 60
INACTIVITY_SECONDS = 180      # the longest pause between two interactions that still counts as learning time
REPEAT_SECONDS = 600          # the same interaction again within 10 minutes is ignored
SUBJECT_MAX = 120
KINDS = ("answer", "quiz", "challenge", "country", "view")
KIND_LABELS = {"answer": "Quiz answers", "quiz": "Qualifying quizzes", "challenge": "Daily Challenge",
               "country": "Country details explored", "view": "Countries opened"}
TIERS = (   # (amount, minutes, quizzes, new countries, daily challenge)
    (100, 15, 1, 0, False),
    (250, 30, 2, 0, False),
    (350, 45, 2, 1, False),
    (500, 60, 2, 1, True),
)
LINE_STATUSES = ("pending_review", "approved", "withheld", "paid")
LINE_LABELS = {"pending_review": "Pending review", "approved": "Approved — payment pending", "withheld": "Withheld",
               "paid": "Paid by bank transfer"}
FAST_ANSWER_SECONDS = 2.0
TABLES = ("pilot_reward_settings", "pilot_activity", "pilot_day_reviews", "pilot_settlements",
          "pilot_settlement_lines")
PAYMENT_TABLES = ("pilot_beneficiaries", "pilot_payments")          # supabase/friends_family10_payments_migration.sql
ACCEPTANCE_TABLES = ("pilot_terms_acceptances",)                     # supabase/friends_family10_acceptance_migration.sql
REFERENCE_MIN = 4


@dataclass(frozen=True)
class DaySummary:
    day: str
    seconds: int
    minutes: int
    quizzes: int
    challenge: bool
    new_countries: int
    interactions: int
    subjects: int
    tier: int              # 0 = no tier reached
    tier_amount: int       # before the monthly maximum
    amount: int = 0        # after the monthly maximum (filled in by month_ledger)
    excluded: bool = False
    flags: tuple = ()


def lagos_day(value) -> str:
    return lagos_now(_dt(value)).date().isoformat()


def month_of(day: str) -> str:
    return str(day)[:7]


def clean_subject(subject) -> str:
    return str(subject or "").strip()[:SUBJECT_MAX]


def accept(history: list[dict], kind: str, subject: str, at) -> bool:
    """Would a new interaction be recorded? (kind known, subject given, not a repeat within REPEAT_SECONDS)."""
    if kind not in KINDS or not clean_subject(subject):
        return False
    when = _dt(at)
    for row in history:
        if row["kind"] == kind and row["subject"] == clean_subject(subject):
            gap = (when - _dt(row["at"])).total_seconds()
            if 0 <= gap < REPEAT_SECONDS:
                return False
    return True


def active_seconds(day_rows: list[dict]) -> int:
    """One timeline per day: the gap between consecutive interactions counts up to INACTIVITY_SECONDS."""
    times = sorted(_dt(r["at"]) for r in day_rows)
    return int(sum(min((b - a).total_seconds(), INACTIVITY_SECONDS) for a, b in zip(times, times[1:])))


def tier_for(minutes: int, quizzes: int, new_countries: int, challenge: bool) -> int:
    reached = 0
    for i, (_, need_min, need_quiz, need_new, need_challenge) in enumerate(TIERS, start=1):
        if minutes >= need_min and quizzes >= need_quiz and new_countries >= need_new and (challenge or not need_challenge):
            reached = i
        else:
            break                       # a higher tier needs every milestone below it
    return reached


def tier_amount(tier: int) -> int:
    return TIERS[tier - 1][0] if tier else 0


def flags_for(day_rows: list[dict], minutes: int) -> tuple:
    """Signals for the Owner's review (never applied automatically)."""
    out = []
    subjects = {(r["kind"], r["subject"]) for r in day_rows}
    if minutes >= 30 and len(subjects) < minutes / 3:
        out.append("Low variety: few different activities for the time recorded")
    speeds = [float((r.get("detail") or {}).get("avg_seconds") or 0) for r in day_rows if r["kind"] in ("quiz", "challenge")]
    if any(0 < s < FAST_ANSWER_SECONDS for s in speeds):
        out.append(f"Very fast quiz answers (under {FAST_ANSWER_SECONDS:g} s on average)")
    return tuple(out)


def day_summaries(rows: list[dict], excluded_days: set[str] | None = None) -> list[DaySummary]:
    """Every day with activity for ONE participant (rows of any months; the order of rows does not matter).
    The monthly maximum is not applied here (see month_ledger)."""
    rows = sorted(rows, key=lambda r: _dt(r["at"]))
    first_country: dict[str, str] = {}
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        day = str(r.get("day") or lagos_day(r["at"]))[:10]
        by_day.setdefault(day, []).append(r)
        if r["kind"] == "country":
            first_country.setdefault(r["subject"], day)
    out = []
    for day in sorted(by_day):
        day_rows = by_day[day]
        seconds = active_seconds(day_rows)
        minutes = seconds // 60
        quizzes = len({r["subject"] for r in day_rows if r["kind"] == "quiz"})
        challenge = any(r["kind"] == "challenge" for r in day_rows)
        new = sum(1 for d in first_country.values() if d == day)
        tier = tier_for(minutes, quizzes, new, challenge)
        out.append(DaySummary(day=day, seconds=seconds, minutes=minutes, quizzes=quizzes, challenge=challenge,
                              new_countries=new, interactions=len(day_rows),
                              subjects=len({(r["kind"], r["subject"]) for r in day_rows}), tier=tier,
                              tier_amount=tier_amount(tier), excluded=day in (excluded_days or set()),
                              flags=flags_for(day_rows, minutes)))
    return out


def month_ledger(summaries: list[DaySummary], month: str) -> list[DaySummary]:
    """The month's days with their provisional amounts: each day's tier amount, limited so that the running total
    never exceeds MONTHLY_MAX. Days the Owner excluded earn ₦0 and do not use up the maximum."""
    total, out = 0, []
    for s in sorted((s for s in summaries if month_of(s.day) == month), key=lambda s: s.day):
        amount = 0 if s.excluded else max(0, min(s.tier_amount, DAILY_MAX, MONTHLY_MAX - total))
        total += amount
        out.append(DaySummary(**{**s.__dict__, "amount": amount}))
    return out


def provisional(rows: list[dict], month: str, excluded_days: set[str] | None = None) -> int:
    return sum(d.amount for d in month_ledger(day_summaries(rows, excluded_days), month))


def allocate(provisional_by_id: dict[str, int], budget: int = MONTHLY_BUDGET) -> dict[str, int]:
    """Final allocations in whole naira. Within budget: unchanged. Over budget: proportional shares by the
    largest-remainder method (floor of each exact share, then one naira each to the largest remainders, ties by
    profile id). Never above a person's provisional amount, and the total never exceeds the budget."""
    clean = {pid: max(0, min(int(v), MONTHLY_MAX)) for pid, v in provisional_by_id.items()}
    total = sum(clean.values())
    if total <= budget:
        return dict(clean)
    base = {pid: v * budget // total for pid, v in clean.items()}
    remainders = sorted(clean, key=lambda pid: (-(clean[pid] * budget % total), pid))
    for pid in remainders[:budget - sum(base.values())]:
        base[pid] += 1
    return base


def scaled(provisional_by_id: dict[str, int], budget: int = MONTHLY_BUDGET) -> bool:
    return sum(max(0, min(int(v), MONTHLY_MAX)) for v in provisional_by_id.values()) > budget


def next_milestones(day: DaySummary | None) -> list[str]:
    """What is still needed today for the next tier (empty once the top tier is reached)."""
    minutes = day.minutes if day else 0
    quizzes = day.quizzes if day else 0
    new = day.new_countries if day else 0
    challenge = day.challenge if day else False
    tier = day.tier if day else 0
    if tier >= len(TIERS):
        return []
    amount, need_min, need_quiz, need_new, need_challenge = TIERS[tier]
    out = []
    if minutes < need_min:
        out.append(f"{need_min - minutes} more minutes of active learning")
    if quizzes < need_quiz:
        out.append(f"{need_quiz - quizzes} more qualifying quiz" + ("zes" if need_quiz - quizzes != 1 else ""))
    if new < need_new:
        out.append("explore a country you have not explored before")
    if need_challenge and not challenge:
        out.append("complete today's Daily Challenge")
    return out


def fingerprint(month: str, budget: int, total_provisional: int, total_final: int, lines: list[dict]) -> str:
    """SHA-256 of the complete allocation: month, budget, totals and every participant's provisional and final amount,
    in profile-id order. The database computes exactly the same text (pilot_settlement_preview); finalising refuses
    any settlement whose recomputed fingerprint differs from the one the owner previewed."""
    import hashlib
    body = ";".join(f"{x['profile_id']}:{int(x['provisional'])}:{int(x['final'])}"
                    for x in sorted(lines, key=lambda x: x["profile_id"]))
    text = f"ff10-settlement-v1|{month}|{int(budget)}|{int(total_provisional)}|{int(total_final)}|{body}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def settlement_preview(rows_by_id: dict[str, list[dict]], month: str, excluded: dict[str, set[str]] | None = None,
                       budget: int = MONTHLY_BUDGET) -> dict:
    """The exact settlement the Owner would finalise for a month (real participants only)."""
    prov = {pid: provisional(rows, month, (excluded or {}).get(pid)) for pid, rows in rows_by_id.items()}
    final = allocate(prov, budget)
    total_p, total_f = sum(prov.values()), sum(final.values())
    lines = [{"profile_id": pid, "provisional": prov[pid], "final": final[pid]} for pid in sorted(prov)]
    return {"month": month, "budget": budget, "total_provisional": total_p, "total_final": total_f,
            "scaled": total_p > budget, "unspent": budget - total_f, "lines": lines,
            "fingerprint": fingerprint(month, budget, total_p, total_f, lines)}


def month_ended(month: str, now: datetime | None = None) -> bool:
    return month < lagos_now(now).strftime("%Y-%m")
