"""Manual cash withdrawals (V21): pure rules shared by the app, the in-memory store and the tests.

The database (supabase/withdrawals_migration.sql) is the authority and enforces the same rules again: eligibility,
the whole-balance amount, one open request per person, earning months that can be requested and paid only once,
owner-only decisions and a payment ledger that records exactly the approved amount.

Nothing here moves money. Approving a request only records the owner's decision; the owner transfers the money from
their own bank and then records it with "Mark as paid". Bank account numbers are never stored: the owner may record a
keyed fingerprint (HMAC-SHA256 with a server secret) to spot the same account on two different profiles.

Money is whole naira. Days and months follow Nigeria time (Africa/Lagos, UTC+1).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone

from core.rewards import LAGOS, _dt

STATUSES = ("pending_review", "under_review", "approved", "on_hold", "rejected", "paid")
OPEN = ("pending_review", "under_review", "approved", "on_hold")
STATUS_LABELS = {"pending_review": "Pending Review", "under_review": "Under Review",
                 "approved": "Approved — Awaiting Payment", "on_hold": "On Hold", "rejected": "Rejected",
                 "paid": "Paid"}
ACTIONS = {"review": "under_review", "approve": "approved", "hold": "on_hold", "reject": "rejected"}
DECLARATIONS = ("legal_name", "own_account", "name_match", "false_information")
REASONS = ("not_joined", "not_approved", "suspended", "declarations", "account_on_hold", "not_enrolled", "waiting_period",
           "no_earnings", "open_request", "not_live")
TEST_LABEL = "TEST RECORD — NOT PAYABLE"
MIN_DAYS = 30
REFERENCE_RE = re.compile(r"^WD-[0-9]{6}-[2-9A-HJ-NP-Z]{4}$")
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
NUBAN_RE = re.compile(r"^[0-9]{10}$")          # Nigerian bank account numbers have 10 digits
MIN_KEY_LENGTH = 32

MONTH_NAMES = {
    "English": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"],
    "Deutsch": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                "November", "Dezember"],
    "Español": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                "noviembre", "diciembre"],
    "Русский": ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
                "ноябрь", "декабрь"],
}


# --------------------------------------------------------------------------- dates (Nigeria)

def lagos_date(value) -> date:
    return _dt(value).astimezone(LAGOS).date()


def today(as_of: str | date | None = None, now: datetime | None = None) -> date:
    if as_of:
        return as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10])
    return (now or datetime.now(timezone.utc)).astimezone(LAGOS).date()


def month_of(day: date) -> str:
    return day.strftime("%Y-%m")


def month_name(month: str, language: str = "English") -> str:
    year, number = month.split("-")
    if language.startswith("中文"):
        return f"{year}年{int(number)}月"
    names = MONTH_NAMES.get(language, MONTH_NAMES["English"])
    return f"{names[int(number) - 1]} {year}"


def period_label(months: list[str], language: str = "English") -> str:
    """'October 2026' or 'September 2026 – October 2026'."""
    months = sorted(months)
    if not months:
        return ""
    if len(months) == 1:
        return month_name(months[0], language)
    return f"{month_name(months[0], language)} – {month_name(months[-1], language)}"


# --------------------------------------------------------------------------- eligibility and balance

def settled_by_withdrawal(review: dict, reservations: list[dict]) -> bool:
    """A reward_payments row for a month that a paid withdrawal settled. The money is already counted once in
    reward_cashout_payments, so such rows are never added a second time. Recognised by the withdrawal's paid
    reservation (exactly as reward_cashout_settled() in the database), never by the reference text, which the existing
    payment rules allow to be edited."""
    return any(r.get("profile_id") == review.get("profile_id") and r.get("month") == review.get("month")
               and r.get("status") == "paid" for r in reservations)


def first_enrolment(enrolments: list[dict], test: bool, since=None):
    """The original rewards enrolment: the first month this person actually took part in (a waiting-list place they
    left without taking part does not count), at the moment the place was taken (enrolled_at). Never the latest login.
    since: Founding 50 — only enrolments from that moment on count (the first approval); False = none counts."""
    if since is False:
        return None
    stamps = [_dt(e.get("enrolled_at") or e["created_at"]) for e in enrolments
              if bool(e.get("test")) == test and (e.get("status") == "enrolled"
                                                  or (e.get("status") == "withdrawn"
                                                      and int(e.get("reserved_amount") or 0) > 0))]
    if since is not None:
        stamps = [x for x in stamps if x >= since]
    return min(stamps) if stamps else None


def month_earnings(profile_id: str, test: bool, events: list[dict], referrals: list[dict]) -> dict[str, dict]:
    """Net verified earnings per month, exactly as reward_cashout_month_earnings() in the database.
    Earned rewards are never negative or edited; the existing reduction is a REJECTED referral, whose reward stays
    recorded but is not payable. gross = all rewards; refused = rewards of rejected referrals; net = gross − refused
    (never below zero); awaiting = referral rewards whose referral is not approved or rejected yet (such a month is
    not verified yet and waits for the owner's decision)."""
    referral_status = {r.get("referred_id"): r.get("status") for r in referrals}
    out: dict[str, dict] = {}
    for e in events:
        amount = int(e.get("amount") or 0)
        if e.get("profile_id") != profile_id or bool(e.get("test")) != test or amount <= 0:
            continue
        month = out.setdefault(e["month"], {"gross": 0, "refused": 0, "net": 0, "awaiting": 0})
        month["gross"] += amount
        if e.get("kind") == "referral":
            state = referral_status.get(e.get("subject"))
            if state == "rejected":
                month["refused"] += amount
            elif state in (None, "pending", "qualified"):
                month["awaiting"] += amount
    for month in out.values():
        month["net"] = max(month["gross"] - month["refused"], 0)
    return out


def _open_months(profile_id: str, current_month: str, earnings: dict, reservations: list[dict],
                 reviews: list[dict]) -> list[str]:
    held = {r["month"] for r in reservations if r.get("profile_id") == profile_id and r.get("status") != "released"}
    reviewed = {p["month"] for p in reviews if p.get("profile_id") == profile_id
                and p.get("status") in ("approved", "paid", "on_hold", "rejected")}
    return [m for m in sorted(earnings) if m < current_month and m not in held and m not in reviewed]


def available_months(profile_id: str, test: bool, current_month: str, events: list[dict], reservations: list[dict],
                     reviews: list[dict], referrals: list[dict] | None = None) -> list[dict]:
    """Net verified earnings from completed months that no withdrawal holds and no monthly payment review approved,
    paid, held or refused. The current (incomplete) month is never included; a month with a referral reward still
    awaiting review waits; a month is never negative."""
    earnings = month_earnings(profile_id, test, events, referrals or [])
    return [{"month": m, "amount": earnings[m]["net"]} for m in _open_months(profile_id, current_month, earnings,
                                                                              reservations, reviews)
            if earnings[m]["awaiting"] == 0 and earnings[m]["net"] > 0]


def month_refused(profile_id: str, month: str, earning: dict, reservations: list[dict], reviews: list[dict]) -> int:
    """One refused figure per person and month (never counted twice): a month refused in a monthly review or
    disqualified with a withdrawal counts in full; a month a monthly review settled for less than was earned counts
    the difference; otherwise the rewards of rejected referrals."""
    review = next((p for p in reviews if p.get("profile_id") == profile_id and p.get("month") == month), None)
    if review and not settled_by_withdrawal(review, reservations):
        if review.get("status") == "rejected":
            return earning["gross"]
        if review.get("status") in ("approved", "paid"):
            return max(earning["gross"] - int(review.get("approved_amount") or 0), 0)
    if any(r.get("profile_id") == profile_id and r.get("month") == month and r.get("status") == "disqualified"
           for r in reservations):
        return earning["gross"]
    return earning["refused"]


def earnings_changed(request: dict, reservations: list[dict], events: list[dict], referrals: list[dict]) -> bool:
    """True when a reserved month's net verified earnings no longer equal the reserved amount or a referral reward in
    it awaits review again (the request must then be rejected and requested again)."""
    earnings = month_earnings(request["profile_id"], bool(request.get("test")), events, referrals)
    for r in reservations:
        if r.get("request_id") == request["id"] and r.get("status") == "reserved":
            month = earnings.get(r["month"])
            if month is None or month["net"] != int(r["amount"]) or month["awaiting"] > 0:
                return True
    return False


def public_request(row: dict | None) -> dict | None:
    """A request as the player may see it (without the identity and verification details)."""
    if not row:
        return None
    return {k: v for k, v in row.items() if k not in ("legal_name", "declarations", "bank_fingerprint", "flags")}


def status(account: dict | None, settings: dict, enrolments: list[dict], events: list[dict], reservations: list[dict],
           reviews: list[dict], requests: list[dict], payments: list[dict], as_of=None,
           now: datetime | None = None, referrals: list[dict] | None = None, founding: bool = False,
           application: dict | None = None) -> dict:
    """The player's withdrawal card, exactly as reward_cashout_status() computes it in the database.
    founding=True (supabase/founding50_migration.sql installed): real accounts need a Founding 50 approval and the
    30-day wait counts from the first official enrolment after the first approval."""
    live, min_days = bool(settings.get("live_requests")), int(settings.get("min_days") or MIN_DAYS)
    if not account:
        return {"eligible": False, "reasons": ["not_joined"], "amount": 0, "months": [], "live": live, "test": False,
                "min_days": min_days}
    test, pid = bool(account.get("test")), account["profile_id"]
    if as_of and not test:
        raise ValueError("simulation_for_test_accounts_only")
    day = today(as_of, now)
    current = month_of(day)
    since = None
    if founding:
        from core import founding as _founding
        since = _founding.clock_start(application, account)
    joined = first_enrolment([e for e in enrolments if e.get("profile_id") == pid], test, since)
    joined_on = joined.astimezone(LAGOS).date() if joined else None
    eligible_on = joined_on + timedelta(days=min_days) if joined_on else None

    reasons = []
    if account.get("membership") == "none" or not account.get("terms_version"):
        reasons.append("not_joined")
    if founding and _founding.blocks_payment(application, account):
        reasons.append("not_approved")
    if account.get("membership") == "suspended":
        reasons.append("suspended")
    if not test and not (account.get("age_confirmed") and account.get("residence_confirmed")):
        reasons.append("declarations")
    if account.get("review") == "hold":
        reasons.append("account_on_hold")
    if joined is None:
        reasons.append("not_enrolled")
    elif day < eligible_on:
        reasons.append("waiting_period")
    earnings = month_earnings(pid, test, events, referrals or [])
    open_months = _open_months(pid, current, earnings, reservations, reviews)
    months = [{"month": m, "amount": earnings[m]["net"]} for m in open_months
              if earnings[m]["awaiting"] == 0 and earnings[m]["net"] > 0]
    waiting = [m for m in open_months if earnings[m]["awaiting"] > 0]
    amount = sum(m["amount"] for m in months)
    if amount <= 0:
        reasons.append("no_earnings")
    mine = [r for r in requests if r.get("profile_id") == pid]
    open_request = next((r for r in mine if r.get("status") in OPEN), None)
    if open_request:
        reasons.append("open_request")
    if not test and not live:
        reasons.append("not_live")

    own_events = [e for e in events if e.get("profile_id") == pid and bool(e.get("test")) == test
                  and int(e.get("amount") or 0) > 0]
    earned = sum(int(e["amount"]) for e in own_events)
    earned_now = sum(int(e["amount"]) for e in own_events if str(e["month"]) >= current)
    same = [r for r in mine if bool(r.get("test")) == test]
    pending = sum(int(r["amount"]) for r in same if r["status"] in ("pending_review", "under_review", "on_hold"))
    approved = sum(int(r["amount"]) for r in same if r["status"] == "approved")
    paid = sum(int(p["amount"]) for p in payments if p.get("profile_id") == pid and bool(p.get("test")) == test) \
        + sum(int(p.get("paid_amount") or 0) for p in reviews
              if p.get("profile_id") == pid and bool(p.get("test")) == test and p.get("status") == "paid"
              and not settled_by_withdrawal(p, reservations))
    refused = sum(month_refused(pid, m, earning, reservations, reviews) for m, earning in earnings.items())
    return {"eligible": not reasons, "reasons": reasons, "today": day.isoformat(), "month": current,
            "joined_on": joined_on.isoformat() if joined_on else None,
            "eligible_on": eligible_on.isoformat() if eligible_on else None,
            "days_left": max((eligible_on - day).days, 0) if eligible_on else None,
            "months": months, "amount": amount, "waiting_months": waiting,
            "open_request": public_request(open_request), "live": live,
            "test": test, "min_days": min_days,
            "totals": {"earned": earned, "current_month": earned_now, "available": amount, "pending": pending,
                       "approved": approved, "paid": paid, "refused": refused,
                       "unpaid": max(earned - paid - refused, 0)}}


# --------------------------------------------------------------------------- requests

def new_reference(day: date, rng=None) -> str:
    choice = (rng or secrets.SystemRandom()).choice
    return f"WD-{day.strftime('%Y%m')}-" + "".join(choice(ALPHABET) for _ in range(4))


def declarations_complete(declarations: dict) -> bool:
    return all(bool((declarations or {}).get(k)) for k in DECLARATIONS)


def legal_name_ok(name: str | None) -> bool:
    return 2 <= len((name or "").strip()) <= 120


def transition_error(current: str, action: str, note: str | None = None, beneficiary: bool = False,
                     eligibility: bool = False) -> str | None:
    """The owner's decision rules (the database checks them again). Returns the database's short reason or None."""
    new = ACTIONS.get(action)
    if new is None:
        return "unknown_action"
    if current in ("paid", "rejected"):
        return "request_closed"
    if new == current or (new == "under_review" and current not in ("pending_review", "on_hold")):
        return "invalid_transition"
    if new in ("on_hold", "rejected") and len((note or "").strip()) < 3:
        return "reason_required"
    if new == "approved" and not (beneficiary and eligibility):
        return "verification_required"
    return None


# --------------------------------------------------------------------------- identity and fraud prompts

def normalize_name(name: str | None) -> str:
    """For comparing names only: accents removed, case folded, words sorted ('Ádé  OKAFOR' == 'okafor ade')."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return " ".join(sorted(re.findall(r"[^\W_]+", text)))


def fingerprint(key: str, bank: str, account_number: str) -> str:
    """Keyed fingerprint of a bank account (HMAC-SHA256). The number itself is never stored or logged."""
    if not key or len(key) < MIN_KEY_LENGTH:
        raise ValueError("fingerprint_key_missing")
    digits = re.sub(r"\D", "", account_number or "")
    if not NUBAN_RE.match(digits):
        raise ValueError("account_number_invalid")
    bank_id = re.sub(r"[^0-9A-Z]", "", (bank or "").upper())
    if not bank_id:
        raise ValueError("bank_required")
    return hmac.new(key.encode(), f"{bank_id}:{digits}".encode(), hashlib.sha256).hexdigest()


def identity_flags(request: dict, requests: list[dict], accounts: list[dict]) -> list[str]:
    """Prompts for the owner's manual review. They never block a payment: different people can share a name."""
    flags = []
    pid, test = request.get("profile_id"), bool(request.get("test"))
    others = [r for r in requests if r.get("profile_id") != pid and bool(r.get("test")) == test]
    name = normalize_name(request.get("legal_name"))
    same_name = {r["profile_id"] for r in others if name and normalize_name(r.get("legal_name")) == name}
    if same_name:
        flags.append(f"Repeated identity: the same legal name is used on {len(same_name)} other account(s)")
    fp = request.get("bank_fingerprint")
    same_bank = {r["profile_id"] for r in others if fp and r.get("bank_fingerprint") == fp}
    if same_bank:
        flags.append(f"Duplicate bank account: the same account fingerprint appears on {len(same_bank)} other "
                     "account(s)")
    account = next((a for a in accounts if a.get("profile_id") == pid), {})
    google = normalize_name(account.get("display_name"))
    if google and name and not set(google.split()) & set(name.split()):
        flags.append("Legal name shares no word with the Google account name (check the beneficiary name)")
    return flags


# --------------------------------------------------------------------------- owner accounting

def programme_months(start: str, until: str) -> list[str]:
    """Calendar months from the programme start month up to and including `until` (YYYY-MM)."""
    y, m = map(int, start[:7].split("-"))
    out = []
    while f"{y}-{m:02d}" <= until and len(out) < 240:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _refused_by_person_month(events: list[dict], reservations: list[dict], reviews: list[dict],
                             referrals: list[dict]) -> dict[tuple, int]:
    out = {}
    for pid, test in {(e.get("profile_id"), bool(e.get("test"))) for e in events}:
        for month, earning in month_earnings(pid, test, events, referrals).items():
            out[(pid, month)] = month_refused(pid, month, earning, reservations, reviews)
    return out


def summary(requests: list[dict], payments: list[dict], events: list[dict], reservations: list[dict],
            reviews: list[dict], monthly_budget: int, start_date: str, current_month: str,
            referrals: list[dict] | None = None) -> dict:
    """Withdrawal dashboard figures. Callers pass real rows only (test rows are never real liabilities).

    Remaining budget = monthly budget × programme months so far − rewards earned (an earned reward is owed until it is
    paid or refused), plus refused amounts, which return to the budget."""
    count = {s: sum(1 for r in requests if r.get("status") == s) for s in STATUSES}
    awaiting = sum(int(r["amount"]) for r in requests if r.get("status") == "approved")
    cash_paid = sum(int(p["amount"]) for p in payments)
    review_paid = sum(int(p.get("paid_amount") or 0) for p in reviews
                      if p.get("status") == "paid" and not settled_by_withdrawal(p, reservations))
    earned = sum(int(e.get("amount") or 0) for e in events if int(e.get("amount") or 0) > 0)
    refused = sum(_refused_by_person_month(events, reservations, reviews, referrals or []).values())
    allocated = monthly_budget * len(programme_months(start_date, current_month))
    return {"total": len(requests), **count, "awaiting": awaiting, "paid_amount": cash_paid + review_paid,
            "paid_withdrawals": cash_paid, "paid_reviews": review_paid, "earned": earned, "refused": refused,
            "allocated": allocated, "remaining_budget": allocated - earned + refused,
            "pending_amount": sum(int(r["amount"]) for r in requests
                                  if r.get("status") in ("pending_review", "under_review", "on_hold"))}


def by_earning_month(events: list[dict], reservations: list[dict], requests: list[dict], reviews: list[dict],
                     referrals: list[dict] | None = None) -> list[dict]:
    """Liabilities by the month in which rewards were earned (never by the month they were paid)."""
    status_of = {r["id"]: r["status"] for r in requests}
    rows: dict[str, dict] = {}

    def row(month):
        return rows.setdefault(month, {"Earning month": month, "Earned (liability)": 0, "Requested": 0,
                                       "Approved, awaiting payment": 0, "Paid": 0, "Refused": 0,
                                       "Not yet requested": 0})
    for e in events:
        if int(e.get("amount") or 0) > 0:
            row(e["month"])["Earned (liability)"] += int(e["amount"])
    for r in reservations:
        target = row(r["month"])
        if r["status"] == "paid":
            target["Paid"] += int(r["amount"])
        elif r["status"] == "reserved":
            key = "Approved, awaiting payment" if status_of.get(r["request_id"]) == "approved" else "Requested"
            target[key] += int(r["amount"])
    for p in reviews:
        if p.get("status") == "paid" and not settled_by_withdrawal(p, reservations):
            row(p["month"])["Paid"] += int(p.get("paid_amount") or 0)
    for (pid, month), refused in _refused_by_person_month(events, reservations, reviews, referrals or []).items():
        row(month)["Refused"] += refused
    for target in rows.values():
        target["Not yet requested"] = max(target["Earned (liability)"] - target["Requested"]
                                          - target["Approved, awaiting payment"] - target["Paid"] - target["Refused"], 0)
    return [rows[m] for m in sorted(rows, reverse=True)]


def by_payment_month(payments: list[dict], reviews: list[dict], reservations: list[dict]) -> list[dict]:
    """Cash actually paid, by the month the owner transferred it."""
    rows: dict[str, dict] = {}
    for p in payments:
        target = rows.setdefault(p["payment_month"], {"Payment month": p["payment_month"], "Withdrawals paid": 0,
                                                      "Monthly reviews paid": 0, "Cash paid": 0, "Payments": 0})
        target["Withdrawals paid"] += int(p["amount"])
        target["Payments"] += 1
    for p in reviews:
        if p.get("status") == "paid" and p.get("payment_date") and not settled_by_withdrawal(p, reservations):
            month = str(p["payment_date"])[:7]
            target = rows.setdefault(month, {"Payment month": month, "Withdrawals paid": 0, "Monthly reviews paid": 0,
                                             "Cash paid": 0, "Payments": 0})
            target["Monthly reviews paid"] += int(p.get("paid_amount") or 0)
            target["Payments"] += 1
    for target in rows.values():
        target["Cash paid"] = target["Withdrawals paid"] + target["Monthly reviews paid"]
    return [rows[m] for m in sorted(rows, reverse=True)]
