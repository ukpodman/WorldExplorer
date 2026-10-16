"""Test fixtures for the Founding 50 approval rule (tests only).

Since supabase/founding50_migration.sql, real accounts can enrol and earn only with an APPROVED Founding 50
application. The older rewards and withdrawal scenarios test other rules, so their stores give every account they
create an approved application (auto_approve), exactly as if the Owner had approved it. The Founding 50 rules
themselves are tested in tests/test_founding50.py without these shortcuts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import founding


def _memory(store) -> bool:
    """The in-memory store (checked by its tables, not its class: the app reloads its modules on a fresh run)."""
    return hasattr(store, "tables") and not hasattr(store, "cluster")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approve(store, profile_id: str, at: str | None = None) -> None:
    """An approved application for this account (bypasses the owner function and the place limit — fixture only)."""
    if _memory(store):
        account = store.account(profile_id) or {}
        when = at or _now()
        row = store._founding_row(profile_id)
        if row:
            row.update(status="approved", approved_at=when, first_approved_at=row.get("first_approved_at") or when)
            return
        store._ids[founding.TABLE] = store._ids.get(founding.TABLE, 0) + 1
        store.tables[founding.TABLE].append({
            "id": store._ids[founding.TABLE], "profile_id": profile_id, "status": "approved", "state": "Lagos",
            "note": None, "age_confirmed": True, "residence_confirmed": True, "terms_version": "test",
            "applied_at": when, "first_approved_at": when, "approved_at": when, "decided_at": when,
            "decided_by": "fixture", "decision_note": None, "seen_at": when, "seen_by": "fixture",
            "test": bool(account.get("test")), "updated_at": when})
    else:
        store.cluster.approve(store.db, profile_id, at)


def auto_approve(store):
    """Every account this store creates gets an approved Founding 50 application."""
    original = store.ensure_account

    def ensure_account(profile_id, *args, **kwargs):
        account = original(profile_id, *args, **kwargs)
        approve(store, profile_id)
        return account

    store.ensure_account = ensure_account
    return store


def backdate(store, profile_id: str, days: int) -> None:
    """Move this person's enrolments (and, before them, their approval) `days` days into the past."""
    stamp = datetime.now(timezone.utc) - timedelta(days=days)
    approved_at = (stamp - timedelta(hours=1)).isoformat()
    if _memory(store):
        for e in store.tables["reward_enrolments"]:
            if e["profile_id"] == profile_id:
                e["created_at"] = stamp.isoformat()
                if e.get("enrolled_at"):
                    e["enrolled_at"] = stamp.isoformat()
        row = store._founding_row(profile_id)
        if row:
            row.update(first_approved_at=approved_at, approved_at=approved_at)
    else:
        store.cluster.psql(store.db, f"update public.reward_enrolments set created_at = now() - interval "
                                     f"'{int(days)} days', enrolled_at = case when enrolled_at is null then null else "
                                     f"now() - interval '{int(days)} days' end where profile_id = '{profile_id}'",
                           "service_role")
        store.cluster.psql(store.db, "select set_config('we.founding', 'on', false); update "
                                     "public.reward_founding_applications set first_approved_at = now() - interval "
                                     f"'{int(days)} days 1 hour', approved_at = now() - interval '{int(days)} days 1 hour' "
                                     f"where profile_id = '{profile_id}'")
