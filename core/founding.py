"""WORLD EXPLORER FOUNDING 50 — pure rules shared by the app, the in-memory store and the tests.

Option B: anyone can use World Explorer for free and anyone signed in can apply; only the Owner approves. Only
approved participants can earn money. The database (supabase/founding50_migration.sql) is the authority and enforces
the same rules again: one application per person, owner-only decisions, at most `max_places` (50) approved
participants, no enrolment or earning without approval, and the 30-day withdrawal wait counted from the first
official enrolment after the first approval.
"""
from __future__ import annotations

from core.rewards import _dt

STATUSES = ("pending", "approved", "waitlist", "rejected")
STATUS_LABELS = {"pending": "Pending", "approved": "Approved", "waitlist": "Waiting List", "rejected": "Rejected"}
ACTIONS = {"approve": "approved", "reject": "rejected", "waitlist": "waitlist"}
STATES = ("Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
          "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT Abuja", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
          "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers",
          "Sokoto", "Taraba", "Yobe", "Zamfara")
NOTE_MAX = 300
DECISION_NOTE_MAX = 500
TABLE = "reward_founding_applications"


def approved(application: dict | None, account: dict | None) -> bool:
    """May this account take part and earn? Test accounts always may (owner testing); real accounts need an
    APPROVED application (= reward_founding_approved)."""
    if account and account.get("test"):
        return True
    return bool(application and application.get("status") == "approved" and not application.get("test"))


def blocks_payment(application: dict | None, account: dict | None) -> bool:
    """A real account that was never approved, or that the Owner rejected after approval, cannot request, be approved
    for or be paid a withdrawal or monthly payment (= reward_founding_blocks). Moved back to the waiting list:
    earnings already earned stay payable."""
    if account and account.get("test"):
        return False
    return not (application and application.get("first_approved_at") and application.get("status") != "rejected"
                and not application.get("test"))


def clock_start(application: dict | None, account: dict | None):
    """The earliest moment an enrolment may count for the 30-day withdrawal wait (None = no limit, test accounts)."""
    if account and account.get("test"):
        return None
    if not application or not application.get("first_approved_at"):
        return False   # never approved: no enrolment counts
    return _dt(application["first_approved_at"])


def apply_error(account: dict | None, existing: dict | None, state: str | None, note: str | None, adult: bool,
                resident: bool, terms: bool, public_on: bool) -> str | None:
    """Why an application is refused (the database checks the same), or None."""
    if not account:
        return "no_account"
    if existing:
        return "already_applied"
    if not (adult and resident and terms):
        return "declarations_required"
    if not state or str(state).strip() not in STATES:
        return "state_required"
    if len(note or "") > NOTE_MAX:
        return "note_too_long"
    if not account.get("test") and account.get("membership") == "suspended":
        return "suspended"
    if not account.get("test") and not public_on:
        return "programme_off"
    return None


def decide_error(application: dict | None, action: str, note: str | None, approved_count: int,
                 max_places: int) -> str | None:
    if application is None:
        return "unknown_application"
    new = ACTIONS.get(action)
    if new is None:
        return "invalid_action"
    if application["status"] == new:
        return "no_change"
    clean = (note or "").strip()
    if len(clean) > DECISION_NOTE_MAX:
        return "note_too_long"
    if (new == "rejected" or application["status"] == "approved") and not clean:
        return "reason_required"
    if new == "approved" and not application.get("test") and approved_count >= max_places:
        return "places_full"
    return None


def counts(applications: list[dict]) -> dict:
    out = {s: 0 for s in STATUSES}
    for a in applications:
        out[a["status"]] = out.get(a["status"], 0) + 1
    out["total"] = len(applications)
    return out


def dashboard(applications: list[dict], enrolments: list[dict], events: list[dict], max_places: int, month: str,
              net_earnings: dict[str, int] | None = None) -> dict:
    """The Founding 50 dashboard figures (pass real rows only for real figures).
    net_earnings: profile_id → net verified earnings from completed months (withdrawals.month_earnings)."""
    c = counts(applications)
    approved_ids = {a["profile_id"] for a in applications if a["status"] == "approved"}
    enrolled = {e["profile_id"] for e in enrolments if e["month"] == month and e["status"] == "enrolled"
                and e["profile_id"] in approved_ids}
    active = {e["profile_id"] for e in events if e["month"] == month and e["profile_id"] in approved_ids}
    earned_month = sum(int(e.get("amount") or 0) for e in events if e["month"] == month
                       and e["profile_id"] in approved_ids)
    ever = {a["profile_id"] for a in applications if a.get("first_approved_at")}
    verified = sum(v for pid, v in (net_earnings or {}).items() if pid in ever)
    return {**c, "places": max_places, "available": max(max_places - c["approved"], 0), "enrolled": len(enrolled),
            "active": len(active), "earned_month": earned_month, "verified": verified,
            "unseen": sum(1 for a in applications if not a.get("seen_at"))}


def waitlist_order(applications: list[dict]) -> list[dict]:
    """Waiting-list applications in the order they were placed there (then by application date)."""
    rows = [a for a in applications if a["status"] == "waitlist"]
    return sorted(rows, key=lambda a: (str(a.get("decided_at") or ""), str(a.get("applied_at") or "")))
