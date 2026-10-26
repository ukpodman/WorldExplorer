"""Where the rewards programme keeps its records.

RewardsStore holds every operation the app needs (accounts, enrolment, activity events, referrals, payments,
settings, audit) on top of six small primitives: select, insert, update, delete, rpc and count. Two classes provide
them:

* SupabaseStore — the real tables (supabase/rewards_schema.sql) over Supabase REST, called only from the server with
  the server key the app already uses for player progress. The browser never talks to these tables.
* MemoryStore — the same rules in Python, kept in memory. Used by the tests and for owner testing on a copy of the
  app that has no Supabase storage configured. Nothing in it is ever payable.

The database is the authority on amounts: an event is stored with the amount the database allows, and the store
returns the stored row so the app always shows what was really recorded.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from core import founding, pilot_rewards, rewards, withdrawals
from core.rewards import Settings

TABLES = ("reward_program_settings", "reward_accounts", "reward_enrolments", "reward_activity_events",
          "user_referrals", "reward_referral_visits", "reward_payments", "reward_audit_log")
CASHOUT_TABLES = ("reward_cashout_settings", "reward_cashout_requests", "reward_cashout_months",
                  "reward_cashout_payments", "reward_owner_notifications")   # supabase/withdrawals_migration.sql
FOUNDING_TABLES = (founding.TABLE,)                                            # supabase/founding50_migration.sql
PILOT_TABLES = (founding.INVITES,)                                             # supabase/pilot_invitations_migration.sql
FF10_TABLES = pilot_rewards.TABLES + pilot_rewards.PAYMENT_TABLES + pilot_rewards.ACCEPTANCE_TABLES
PAGE = 1000
PILOT_COLUMNS = ("pilot_enabled", "pilot_changed_at", "pilot_changed_by", "invitation_only", "invitation_changed_at",
                 "invitation_changed_by", "pilot_terms_version", "public_terms_version", "terms_changed_at",
                 "terms_changed_by")


class StoreError(Exception):
    """A refused operation; str(error) is the database's short reason (e.g. 'paused', 'not_member')."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _match(row: dict, where: dict | None) -> bool:
    for col, cond in (where or {}).items():
        value = row.get(col)
        if isinstance(cond, tuple):
            op, arg = cond
            if op == "in" and value not in arg:
                return False
            if op == "gte" and not (value is not None and str(value) >= str(arg)):
                return False
            if op == "lte" and not (value is not None and str(value) <= str(arg)):
                return False
            if op == "neq" and value == arg:
                return False
        elif value != cond:
            return False
    return True


class RewardsStore:
    """High-level operations. Subclasses implement the primitives."""

    kind = "base"

    # ---- primitives (overridden)
    def select(self, table: str, where: dict | None = None, order: str | None = None,
               limit: int | None = None) -> list[dict]:
        raise NotImplementedError

    def insert(self, table: str, row: dict, ignore_duplicates: bool = False, conflict: str | None = None) -> list[dict]:
        raise NotImplementedError

    def update(self, table: str, where: dict, changes: dict) -> list[dict]:
        raise NotImplementedError

    def delete(self, table: str, where: dict) -> int:
        raise NotImplementedError

    def rpc(self, name: str, args: dict):
        raise NotImplementedError

    def health(self) -> str:
        """'ok', 'missing_tables' (the SQL setup has not been run) or 'error'."""
        try:
            self.select("reward_program_settings", {"id": 1}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) else "error"
        except Exception:
            return "error"

    # ---- settings
    def settings(self) -> Settings:
        rows = self.select("reward_program_settings", {"id": 1}, limit=1)
        return Settings.from_row(rows[0] if rows else None)

    def save_settings(self, settings: Settings, actor: str) -> list[str]:
        problems = settings.validate()
        if problems:
            return problems
        row = settings.as_row()
        row.update(updated_by=actor, updated_at=_now())
        self.update("reward_program_settings", {"id": 1}, row)
        return []

    # ---- public programme switch (supabase/public_programme_migration.sql)
    def public_status(self) -> dict:
        """The owner's public programme switch: {'installed', 'enabled', 'changed_at', 'changed_by'}. 'installed' is
        False until the migration has run (then the switch counts as OFF)."""
        rows = self.select("reward_program_settings", {"id": 1}, limit=1)
        row = rows[0] if rows else {}
        if "public_enabled" not in row:
            return {"installed": False, "enabled": False, "changed_at": None, "changed_by": None}
        return {"installed": True, "enabled": bool(row.get("public_enabled")), "changed_at": row.get("public_changed_at"),
                "changed_by": row.get("public_changed_by")}

    def set_public(self, enabled: bool, actor: str, confirmed: bool = False) -> dict:
        """Owner-only (checked by the database). Switching ON needs confirmed=True. Recorded in the audit log."""
        return self._one(self.rpc("reward_set_public_programme", {"p_enabled": bool(enabled), "p_actor": actor,
                                                                  "p_confirmed": bool(confirmed)}))

    # ---- accounts
    def account(self, profile_id: str) -> dict | None:
        rows = self.select("reward_accounts", {"profile_id": profile_id}, limit=1)
        return rows[0] if rows else None

    def account_by_code(self, code: str) -> dict | None:
        if not rewards.valid_code(code):
            return None
        rows = self.select("reward_accounts", {"referral_code": code}, limit=1)
        return rows[0] if rows else None

    def accounts(self) -> list[dict]:
        return self.select("reward_accounts", order="created_at")

    def ensure_account(self, profile_id: str, email: str | None, name: str | None, new_registration: bool,
                       test: bool = False) -> dict:
        result = self.rpc("reward_ensure_account", {"p_profile": profile_id, "p_email": email, "p_name": name,
                                                    "p_new": bool(new_registration), "p_test": bool(test)})
        return result[0] if isinstance(result, list) else result

    def update_account(self, profile_id: str, changes: dict) -> dict | None:
        rows = self.update("reward_accounts", {"profile_id": profile_id}, changes)
        return rows[0] if rows else None

    def join(self, profile_id: str, month: str) -> dict:
        """Record the self-declarations and enrol for the month (enrolled, or on the waiting list)."""
        self.update_account(profile_id, {"membership": "member", "age_confirmed": True, "residence_confirmed": True,
                                         "terms_version": rewards.TERMS_VERSION, "declared_at": _now()})
        return self.enrol(profile_id, month)

    def leave(self, profile_id: str, month: str) -> None:
        if self.enrolment(profile_id, month):
            self.withdraw(profile_id, month, profile_id)
        self.update_account(profile_id, {"membership": "withdrawn"})

    # ---- enrolment
    def enrol(self, profile_id: str, month: str) -> dict:
        result = self.rpc("reward_enrol", {"p_profile": profile_id, "p_month": month})
        return result[0] if isinstance(result, list) else result

    def withdraw(self, profile_id: str, month: str, actor: str | None = None) -> dict | None:
        result = self.rpc("reward_withdraw", {"p_profile": profile_id, "p_month": month, "p_actor": actor})
        return (result[0] if result else None) if isinstance(result, list) else result

    def promote(self, month: str, actor: str | None = None) -> int:
        return int(self.rpc("reward_promote_waitlist", {"p_month": month, "p_actor": actor}) or 0)

    def enrolment(self, profile_id: str, month: str) -> dict | None:
        rows = self.select("reward_enrolments", {"profile_id": profile_id, "month": month}, limit=1)
        return rows[0] if rows else None

    def enrolments(self, month: str | None = None, profile_id: str | None = None) -> list[dict]:
        where = {k: v for k, v in (("month", month), ("profile_id", profile_id)) if v}
        return self.select("reward_enrolments", where, order="created_at")

    # ---- activity
    def add_event(self, profile_id: str, kind: str, subject: str, day: str, *, reward: bool, test: bool,
                  detail: dict | None = None) -> dict | None:
        """Record one activity. reward=True asks the database to pay it (it decides how much). Returns the stored
        row, or None when this activity was already recorded (same key)."""
        month = day[:7]
        row = {"event_key": rewards.event_key(profile_id, kind, subject, month), "profile_id": profile_id,
               "kind": kind, "subject": str(subject)[:120], "month": month, "day": day,
               "amount": 1 if reward else 0, "test": bool(test), "detail": detail or {}}
        rows = self.insert("reward_activity_events", row, ignore_duplicates=True, conflict="event_key")
        return rows[0] if rows else None

    def events(self, profile_id: str | None = None, month: str | None = None, kind: str | None = None) -> list[dict]:
        where = {k: v for k, v in (("profile_id", profile_id), ("month", month), ("kind", kind)) if v}
        return self.select("reward_activity_events", where, order="created_at")

    # ---- referrals
    def record_visit(self, visit_key: str, code: str, test: bool = False) -> str:
        """Count one visit through a referral link (once per browser session). Returns the outcome so far."""
        owner = self.account_by_code(code)
        outcome = "visit" if owner else "unknown_code"
        self.insert("reward_referral_visits", {"visit_key": visit_key, "code": str(code)[:12],
                                               "referrer_id": owner["profile_id"] if owner else None,
                                               "outcome": outcome, "test": bool(owner and owner.get("test"))},
                    ignore_duplicates=True, conflict="visit_key")
        return outcome

    def attribute(self, referred_id: str, code: str, visit_key: str | None = None) -> str:
        return str(self.rpc("reward_attribute", {"p_referred": referred_id, "p_code": code, "p_visit": visit_key}))

    def referral_of(self, referred_id: str) -> dict | None:
        rows = self.select("user_referrals", {"referred_id": referred_id}, limit=1)
        return rows[0] if rows else None

    def referrals(self, referrer_id: str | None = None) -> list[dict]:
        return self.select("user_referrals", {"referrer_id": referrer_id} if referrer_id else None,
                           order="created_at")

    def update_referral(self, referred_id: str, changes: dict) -> dict | None:
        rows = self.update("user_referrals", {"referred_id": referred_id}, changes)
        return rows[0] if rows else None

    def visits(self, referrer_id: str | None = None) -> list[dict]:
        return self.select("reward_referral_visits", {"referrer_id": referrer_id} if referrer_id else None,
                           order="created_at")

    # ---- payments
    def payment(self, profile_id: str, month: str) -> dict | None:
        rows = self.select("reward_payments", {"profile_id": profile_id, "month": month}, limit=1)
        return rows[0] if rows else None

    def payments(self, month: str | None = None, profile_id: str | None = None) -> list[dict]:
        where = {k: v for k, v in (("month", month), ("profile_id", profile_id)) if v}
        return self.select("reward_payments", where, order="created_at")

    def open_payment(self, profile_id: str, month: str, test: bool, actor: str) -> dict:
        """Start the payment review for one person and month (the database records what was earned)."""
        self.insert("reward_payments", {"profile_id": profile_id, "month": month, "test": bool(test),
                                        "updated_by": actor}, ignore_duplicates=True, conflict="profile_id,month")
        return self.payment(profile_id, month)

    def update_payment(self, profile_id: str, month: str, changes: dict, actor: str) -> dict | None:
        allowed = {"status", "approved_amount", "paid_amount", "payment_date", "reference", "remarks", "reason"}
        clean = {k: v for k, v in changes.items() if k in allowed}
        clean["updated_by"] = actor
        rows = self.update("reward_payments", {"profile_id": profile_id, "month": month}, clean)
        return rows[0] if rows else None

    # ---- audit
    def log(self, actor: str | None, action: str, target: str | None = None, value: dict | None = None) -> None:
        self.insert("reward_audit_log", {"actor": actor, "action": action, "target": target, "new_value": value})

    def audit(self, limit: int = 500) -> list[dict]:
        return self.select("reward_audit_log", order="at.desc", limit=limit)

    def clear_test_data(self, actor: str) -> None:
        """Remove owner/tester preview records (never real ones; the database refuses those)."""
        if self.ff10_health() == "ok":
            self.delete("pilot_activity", {"test": True})
        if self.founding_health() == "ok":
            self.delete(founding.TABLE, {"test": True})
        if self.cashout_health() == "ok":   # withdrawal test records first (they refer to accounts)
            for table in ("reward_owner_notifications", "reward_cashout_payments", "reward_cashout_months",
                          "reward_cashout_requests"):
                self.delete(table, {"test": True})
        for table in ("reward_payments", "reward_activity_events", "user_referrals", "reward_referral_visits",
                      "reward_enrolments"):
            self.delete(table, {"test": True})
        self.log(actor, "test_data_cleared")

    # ---- Founding 50 (supabase/founding50_migration.sql; the database functions decide)
    def founding_health(self) -> str:
        """'ok', 'missing_tables' (the Founding 50 migration has not been run) or 'error'."""
        try:
            self.select(founding.TABLE, {"id": 0}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) or "does not exist" in str(error) else "error"
        except Exception:
            return "error"

    def founding_application(self, profile_id: str) -> dict | None:
        rows = self.select(founding.TABLE, {"profile_id": profile_id}, limit=1)
        return rows[0] if rows else None

    def founding_applications(self, status: str | None = None) -> list[dict]:
        return self.select(founding.TABLE, {"status": status} if status else None, order="applied_at")

    def apply_founding(self, profile_id: str, state: str, note: str | None, adult: bool, resident: bool,
                       terms: bool, terms_version: str | None = None) -> dict:
        """Submit a Funding 50 application (one per person; the database refuses duplicates). terms_version is the
        participation terms the applicant was shown and accepted; the database requires it to equal the owner's
        approved version (reward_program_settings.participation_terms_version) and keeps it with the application."""
        return self._one(self.rpc("reward_founding_apply", {
            "p_profile": profile_id, "p_state": state, "p_note": note, "p_adult": bool(adult),
            "p_resident": bool(resident), "p_terms": bool(terms),
            "p_terms_version": terms_version or rewards.TERMS_VERSION}))

    def decide_founding(self, application_id: int, action: str, actor: str, note: str | None = None) -> dict:
        """Owner only (checked by the database): approve, reject or waitlist."""
        return self._one(self.rpc("reward_founding_decide", {"p_id": int(application_id), "p_action": action,
                                                             "p_actor": actor, "p_note": note}))

    def mark_founding_seen(self, actor: str, application_id: int | None = None) -> int:
        return int(self._one(self.rpc("reward_founding_mark_seen", {
            "p_actor": actor, "p_id": int(application_id) if application_id is not None else None})) or 0)

    # ---- Friends & Family 10: invitation-only entry (supabase/pilot_invitations_migration.sql)
    def pilot_status(self) -> dict:
        """{'installed', 'enabled', 'invitation_only', ...}. Until the migration has run: not installed, pilot OFF and
        invitation-only (the safe reading: nobody can be let in by it)."""
        rows = self.select("reward_program_settings", {"id": 1}, limit=1)
        row = rows[0] if rows else {}
        if "pilot_enabled" not in row:
            return {"installed": False, "enabled": False, "invitation_only": True, "terms_version": None,
                    "public_terms_version": None, "changed_at": None, "changed_by": None}
        return {"installed": True, "enabled": bool(row.get("pilot_enabled")),
                "invitation_only": row.get("invitation_only") is not False,
                "terms_version": row.get("pilot_terms_version"),            # the pilot's approved terms
                "public_terms_version": row.get("public_terms_version"),
                "changed_at": row.get("pilot_changed_at"), "changed_by": row.get("pilot_changed_by")}

    def set_pilot(self, enabled: bool, actor: str, confirmed: bool = False) -> dict:
        """Owner-only (checked by the database). Switching ON needs confirmed=True. Audited."""
        return self._one(self.rpc("reward_set_pilot", {"p_enabled": bool(enabled), "p_actor": actor,
                                                       "p_confirmed": bool(confirmed)}))

    def set_invitation_only(self, value: bool, actor: str, confirmed: bool = False) -> dict:
        """Owner-only. Switching invitation-only OFF (public applications) needs confirmed=True. Audited."""
        return self._one(self.rpc("reward_set_invitation_only", {"p_value": bool(value), "p_actor": actor,
                                                                 "p_confirmed": bool(confirmed)}))

    def set_participation_terms(self, mode: str, version: str, actor: str) -> dict:
        """Owner-only: record the approved participation terms for one way in ('pilot' or 'public'), audited."""
        return self._one(self.rpc("reward_set_participation_terms", {"p_mode": mode, "p_version": version,
                                                                     "p_actor": actor}))

    def invite(self, email: str, actor: str, note: str | None = None) -> dict:
        return self._one(self.rpc("reward_pilot_invite", {"p_email": email, "p_actor": actor, "p_note": note}))

    def revoke_invitation(self, email: str, actor: str) -> dict:
        return self._one(self.rpc("reward_pilot_revoke", {"p_email": email, "p_actor": actor}))

    def invitations(self) -> list[dict]:
        try:
            return self.select(founding.INVITES, None, order="invited_at")
        except StoreError:
            return []           # not installed yet

    def pilot_invited(self, email: str | None) -> bool:
        e = founding.normalize_email(email)
        if not e:
            return False
        try:
            rows = self.select(founding.INVITES, {"email": e}, limit=1)
        except StoreError:
            return False
        return bool(rows) and not rows[0].get("revoked_at")

    # ---- Friends & Family 10: provisional rewards (supabase/friends_family10_migration.sql; the database decides)
    def ff10_health(self) -> str:
        """'ok', 'missing_tables' (the Friends & Family 10 migration has not been run) or 'error'."""
        try:
            self.select("pilot_reward_settings", {"id": 1}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) or "does not exist" in str(error) else "error"
        except Exception:
            return "error"

    def ff10_record(self, profile_id: str, kind: str, subject: str, detail: dict | None = None) -> dict | None:
        """One meaningful learning interaction, time-stamped by the database clock. None when it was a repeat (ignored).
        The database refuses people who are not approved participants (test accounts are recorded as test)."""
        row = self._one(self.rpc("pilot_record_activity", {"p_profile": profile_id, "p_kind": kind,
                                                           "p_subject": subject, "p_detail": detail}))
        return row if row and row.get("id") is not None else None

    def ff10_activity(self, profile_id: str | None = None, month: str | None = None) -> list[dict]:
        where = {"profile_id": profile_id} if profile_id else {}
        if month:
            where["day"] = ("gte", f"{month}-01")
        rows = self.select("pilot_activity", where or None, order="at,id")
        return [r for r in rows if not month or str(r["day"])[:7] == month]

    def ff10_ledger(self, profile_id: str, month: str) -> list[dict]:
        """The database's own day-by-day calculation for one participant (real records only)."""
        return list(self.rpc("pilot_month_days", {"p_profile": profile_id, "p_month": month}) or [])

    def ff10_reviews(self) -> list[dict]:
        return self.select("pilot_day_reviews", None, order="day")

    def ff10_review_day(self, profile_id: str, day: str, excluded: bool, actor: str, reason: str | None = None) -> dict:
        return self._one(self.rpc("pilot_review_day", {"p_profile": profile_id, "p_day": str(day)[:10],
                                                       "p_excluded": bool(excluded), "p_actor": actor,
                                                       "p_reason": reason}))

    def ff10_preview(self, month: str) -> dict:
        return self._one(self.rpc("pilot_settlement_preview", {"p_month": month}))

    def ff10_settle(self, month: str, actor: str, expected_fingerprint: str, confirmed: bool = False) -> dict:
        """Finalise a month exactly as previewed: expected_fingerprint is the preview's 'fingerprint' (the complete
        allocation); the database recomputes it under a month lock and refuses any difference ('preview_changed')."""
        return self._one(self.rpc("pilot_settle_month", {"p_month": month, "p_actor": actor,
                                                         "p_confirmed": bool(confirmed),
                                                         "p_expected_fingerprint": expected_fingerprint}))

    def ff10_settlements(self) -> list[dict]:
        return self.select("pilot_settlements", None, order="month")

    def ff10_lines(self, month: str | None = None, profile_id: str | None = None) -> list[dict]:
        where = {k: v for k, v in (("month", month), ("profile_id", profile_id)) if v}
        return self.select("pilot_settlement_lines", where or None, order="month")

    def ff10_decide(self, month: str, profile_id: str, action: str, actor: str, note: str | None = None) -> dict:
        return self._one(self.rpc("pilot_settlement_decide", {"p_month": month, "p_profile": profile_id,
                                                              "p_action": action, "p_actor": actor, "p_note": note}))

    # ---- Friends & Family 10 real cash payments (supabase/friends_family10_payments_migration.sql)
    def ff10_payments_health(self) -> str:
        """'ok', 'missing_tables' (the payments migration has not been run) or 'error'."""
        try:
            self.select("pilot_payments", {"id": 0}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) or "does not exist" in str(error) else "error"
        except Exception:
            return "error"

    def ff10_payments_enabled(self) -> bool:
        rows = self.select("pilot_reward_settings", {"id": 1}, limit=1)
        return bool(rows and rows[0].get("payments_enabled"))

    def ff10_set_payments(self, enabled: bool, actor: str, confirmed: bool = False) -> dict:
        """Owner only: authorise (or suspend) the private pilot's cash payments. Independent of public payouts."""
        return self._one(self.rpc("pilot_set_payments", {"p_enabled": bool(enabled), "p_actor": actor,
                                                         "p_confirmed": bool(confirmed)}))

    def ff10_beneficiaries(self) -> list[dict]:
        return self.select("pilot_beneficiaries", None, order="profile_id")

    def ff10_verify_beneficiary(self, profile_id: str, legal_name: str, bank_name: str, account_last4: str,
                                actor: str, confirmed: bool = False, note: str | None = None) -> dict:
        """Owner only: the participant's identity and bank account name were checked (only the last 4 digits kept)."""
        return self._one(self.rpc("pilot_verify_beneficiary", {
            "p_profile": profile_id, "p_legal_name": legal_name, "p_bank_name": bank_name,
            "p_account_last4": account_last4, "p_actor": actor, "p_confirmed": bool(confirmed), "p_note": note}))

    def ff10_record_payment(self, month: str, profile_id: str, amount: int, paid_on: str, reference: str, actor: str,
                            confirmed: bool = False) -> dict:
        """Owner only: record a manual bank transfer of an approved final allocation (the database checks every rule)."""
        return self._one(self.rpc("pilot_record_payment", {
            "p_month": month, "p_profile": profile_id, "p_amount": int(amount), "p_paid_on": str(paid_on)[:10],
            "p_reference": reference, "p_actor": actor, "p_confirmed": bool(confirmed)}))

    # ---- Friends & Family 10: acceptance of the current private terms (friends_family10_acceptance_migration.sql)
    def ff10_acceptance_health(self) -> str:
        try:
            self.select("pilot_terms_acceptances", {"profile_id": "-"}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) or "does not exist" in str(error) else "error"
        except Exception:
            return "error"

    def ff10_terms_accepted(self, profile_id: str) -> bool:
        """The participant applied with, or has since accepted, the currently recorded private terms."""
        current = str(self.pilot_status().get("terms_version") or "").strip()
        if not current:
            return False
        app = self.founding_application(profile_id)
        if app and app.get("terms_version") == current:
            return True
        try:
            return bool(self.select("pilot_terms_acceptances", {"profile_id": profile_id, "terms_version": current},
                                    limit=1))
        except StoreError:
            return False

    def ff10_accept_terms(self, profile_id: str, terms_version: str) -> dict:
        return self._one(self.rpc("pilot_accept_terms", {"p_profile": profile_id, "p_terms_version": terms_version}))

    def ff10_payments(self, month: str | None = None) -> list[dict]:
        return self.select("pilot_payments", {"month": month} if month else None, order="id")

    # ---- cash withdrawals (supabase/withdrawals_migration.sql; the database functions decide)
    @staticmethod
    def _one(result):
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def cashout_health(self) -> str:
        """'ok', 'missing_tables' (the withdrawals migration has not been run) or 'error'."""
        try:
            self.select("reward_cashout_settings", {"id": 1}, limit=1)
            return "ok"
        except StoreError as error:
            return "missing_tables" if "missing" in str(error) or "does not exist" in str(error) else "error"
        except Exception:
            return "error"

    def cashout_settings(self) -> dict:
        rows = self.select("reward_cashout_settings", {"id": 1}, limit=1)
        return rows[0] if rows else {"live_requests": False, "min_days": withdrawals.MIN_DAYS, "owner_emails": []}

    def cashout_status(self, profile_id: str, as_of: str | None = None) -> dict:
        """Eligibility, available balance and totals for one player (as_of: simulated date, test accounts only)."""
        return self._one(self.rpc("reward_cashout_status", {"p_profile": profile_id, "p_as_of": as_of})) or {}

    def request_cashout(self, profile_id: str, legal_name: str, declarations: dict, expected_amount: int,
                        as_of: str | None = None, flags: list | None = None) -> dict:
        return self._one(self.rpc("reward_cashout_request", {
            "p_profile": profile_id, "p_legal_name": legal_name, "p_declarations": declarations,
            "p_expected_amount": int(expected_amount), "p_as_of": as_of, "p_flags": flags or []}))

    def decide_cashout(self, request_id: int, action: str, actor: str, note: str | None = None,
                       beneficiary: bool = False, eligibility: bool = False, disqualify: bool = False) -> dict:
        return self._one(self.rpc("reward_cashout_decide", {
            "p_id": int(request_id), "p_action": action, "p_actor": actor, "p_note": note,
            "p_beneficiary_verified": bool(beneficiary), "p_eligibility_confirmed": bool(eligibility),
            "p_disqualify": bool(disqualify)}))

    def pay_cashout(self, request_id: int, amount: int, payment_date: str, reference: str | None, actor: str) -> dict:
        return self._one(self.rpc("reward_cashout_pay", {
            "p_id": int(request_id), "p_amount": int(amount), "p_payment_date": payment_date,
            "p_reference": reference, "p_actor": actor}))

    def fingerprint_cashout(self, request_id: int, fingerprint: str, actor: str) -> int:
        return int(self._one(self.rpc("reward_cashout_set_fingerprint", {
            "p_id": int(request_id), "p_fingerprint": fingerprint, "p_actor": actor})) or 0)

    def cashout_requests(self, profile_id: str | None = None) -> list[dict]:
        return self.select("reward_cashout_requests", {"profile_id": profile_id} if profile_id else None,
                           order="requested_at.desc")

    def cashout_request(self, request_id: int) -> dict | None:
        rows = self.select("reward_cashout_requests", {"id": int(request_id)}, limit=1)
        return rows[0] if rows else None

    def cashout_months(self, profile_id: str | None = None) -> list[dict]:
        return self.select("reward_cashout_months", {"profile_id": profile_id} if profile_id else None,
                           order="month")

    def cashout_payments(self, profile_id: str | None = None) -> list[dict]:
        return self.select("reward_cashout_payments", {"profile_id": profile_id} if profile_id else None,
                           order="recorded_at.desc")

    def notifications(self, unread: bool = False) -> list[dict]:
        return self.select("reward_owner_notifications", {"read_at": None} if unread else None,
                           order="created_at.desc", limit=200)

    def mark_notification_read(self, notification_id: int, actor: str) -> None:
        self.update("reward_owner_notifications", {"id": int(notification_id), "read_at": None},
                    {"read_at": _now(), "read_by": actor})

    def set_email_status(self, notification_id: int, status: str) -> None:
        self.update("reward_owner_notifications", {"id": int(notification_id)}, {"email_status": status})


# ============================================================================ Supabase (REST, server only)

class SupabaseStore(RewardsStore):
    kind = "supabase"

    def __init__(self, url: str, key: str, timeout: float = 10):
        self.url, self.key, self.timeout = url.rstrip("/"), key, timeout

    def _headers(self, prefer: str | None = None) -> dict:
        headers = {"apikey": self.key, "Content-Type": "application/json", "Accept": "application/json"}
        if not self.key.startswith("sb_secret_"):  # legacy JWT service keys also need Authorization
            headers["Authorization"] = "Bearer " + self.key
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _call(self, method: str, route: str, body=None, prefer: str | None = None):
        data = json.dumps(body, default=str).encode() if body is not None else None
        request = urllib.request.Request(self.url + route, data=data, headers=self._headers(prefer), method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(50_000_000)
        except urllib.error.HTTPError as error:
            try:
                info = json.loads(error.read(20_000) or b"{}")
            except Exception:
                info = {}
            message = str(info.get("message") or error.reason or error.code)
            if error.code == 404 or info.get("code") in ("42P01", "PGRST202", "PGRST205"):
                raise StoreError("missing: " + message) from None
            raise StoreError(message) from None
        return json.loads(raw) if raw else None

    @staticmethod
    def _filters(where: dict | None) -> list[str]:
        parts = []
        for col, cond in (where or {}).items():
            if isinstance(cond, tuple):
                op, arg = cond
                value = "(" + ",".join(urllib.parse.quote(str(a), safe="") for a in arg) + ")" if op == "in" \
                    else urllib.parse.quote(str(arg), safe="")
                parts.append(f"{col}={op}.{value}")
            elif isinstance(cond, bool):
                parts.append(f"{col}=is.{str(cond).lower()}")
            elif cond is None:
                parts.append(f"{col}=is.null")
            else:
                parts.append(f"{col}=eq.{urllib.parse.quote(str(cond), safe='')}")
        return parts

    def select(self, table, where=None, order=None, limit=None):
        base = [f"select=*"] + self._filters(where) + ([f"order={order}"] if order else [])
        rows: list[dict] = []
        while True:
            take = PAGE if limit is None else min(PAGE, limit - len(rows))
            page = self._call("GET", f"/rest/v1/{table}?" + "&".join(base + [f"limit={take}", f"offset={len(rows)}"]))
            rows.extend(page or [])
            if not page or len(page) < take or (limit is not None and len(rows) >= limit):
                return rows

    def insert(self, table, row, ignore_duplicates=False, conflict=None):
        route = f"/rest/v1/{table}" + (f"?on_conflict={conflict}" if conflict else "")
        prefer = ("resolution=ignore-duplicates," if ignore_duplicates else "") + "return=representation"
        return self._call("POST", route, row, prefer) or []

    def update(self, table, where, changes):
        route = f"/rest/v1/{table}?" + "&".join(self._filters(where))
        return self._call("PATCH", route, changes, "return=representation") or []

    def delete(self, table, where):
        route = f"/rest/v1/{table}?" + "&".join(self._filters(where))
        return len(self._call("DELETE", route, None, "return=representation") or [])

    def rpc(self, name, args):
        return self._call("POST", f"/rest/v1/rpc/{name}", args)


# ============================================================================ in memory (tests, owner testing)

class MemoryStore(RewardsStore):
    """The database rules re-implemented in Python (same triggers and functions). Thread-safe."""

    kind = "memory"
    KEYS = {"reward_program_settings": ("id",), "reward_accounts": ("profile_id",),
            "reward_enrolments": ("profile_id", "month"), "reward_activity_events": ("event_key",),
            "user_referrals": ("referred_id",), "reward_referral_visits": ("visit_key",),
            "reward_payments": ("profile_id", "month"), "reward_audit_log": ("id",),
            "reward_cashout_settings": ("id",), "reward_cashout_requests": ("id",),
            "reward_cashout_months": ("request_id", "month"), "reward_cashout_payments": ("id",),
            "reward_owner_notifications": ("id",), founding.TABLE: ("id",), founding.INVITES: ("email",),
            "pilot_reward_settings": ("id",), "pilot_activity": ("id",), "pilot_day_reviews": ("profile_id", "day"),
            "pilot_settlements": ("month",), "pilot_settlement_lines": ("month", "profile_id"),
            "pilot_beneficiaries": ("profile_id",), "pilot_payments": ("id",),
            "pilot_terms_acceptances": ("profile_id", "terms_version")}

    def __init__(self, settings: Settings | None = None, owner_emails: list[str] | None = None,
                 public_enabled: bool = False):
        self.lock = threading.RLock()
        self.tables: dict[str, list[dict]] = {t: [] for t in TABLES + CASHOUT_TABLES + FOUNDING_TABLES + PILOT_TABLES
                                              + FF10_TABLES}
        self.tables["pilot_reward_settings"].append({
            "id": 1, "max_participants": pilot_rewards.MAX_PARTICIPANTS, "monthly_budget": pilot_rewards.MONTHLY_BUDGET,
            "daily_max": pilot_rewards.DAILY_MAX, "monthly_max": pilot_rewards.MONTHLY_MAX,
            "min_minutes": pilot_rewards.MIN_MINUTES, "max_minutes": pilot_rewards.MAX_MINUTES,
            "inactivity_seconds": pilot_rewards.INACTIVITY_SECONDS, "repeat_seconds": pilot_rewards.REPEAT_SECONDS,
            "payments_enabled": False, "payments_changed_at": None, "payments_changed_by": None, "created_at": _now()})
        self._ff10_fn = False      # like we.ff10: set only inside the settlement functions
        row = (settings or Settings()).as_row()
        row.update(id=1, updated_at=_now(), updated_by=None, public_enabled=bool(public_enabled),
                   public_changed_at=None, public_changed_by=None, pilot_enabled=False, pilot_changed_at=None,
                   pilot_changed_by=None, invitation_only=True, invitation_changed_at=None, invitation_changed_by=None,
                   pilot_terms_version=None, public_terms_version=None, terms_changed_at=None, terms_changed_by=None)
        self.tables["reward_program_settings"].append(row)
        self.tables["reward_cashout_settings"].append({"id": 1, "live_requests": False, "real_payouts": False,
                                                       "min_days": withdrawals.MIN_DAYS,
                                                       "owner_emails": list(owner_emails or []),
                                                       "updated_at": _now(), "updated_by": None})
        self._audit_id = 0
        self._ids: dict[str, int] = {}
        self._cashout_fn = False   # like the database's we.cashout flag: set only inside the withdrawal functions
        self._public_fn = False    # like we.public: set only inside reward_set_public_programme
        self._founding_fn = False  # like we.founding: set only inside the Founding 50 functions

    # ---- primitives
    def select(self, table, where=None, order=None, limit=None):
        with self.lock:
            rows = [dict(r) for r in self.tables[table] if _match(r, where)]
        if order:
            for part in reversed(order.split(",")):
                col, _, direction = part.partition(".")
                rows.sort(key=lambda r: (r.get(col) is None, str(r.get(col))), reverse=direction == "desc")
        return rows[:limit] if limit is not None else rows

    def _key(self, table, row):
        return tuple(row.get(k) for k in self.KEYS[table])

    def insert(self, table, row, ignore_duplicates=False, conflict=None):
        with self.lock:
            row = dict(row)
            if table == "reward_audit_log":
                self._audit_id += 1
                row.setdefault("id", self._audit_id)
                row.setdefault("at", _now())
            if table in CASHOUT_TABLES and table != "reward_cashout_settings":
                if not self._cashout_fn:
                    raise StoreError("withdrawal records change only through the withdrawal functions")
                if "id" in self.KEYS[table] and row.get("id") is None:
                    self._ids[table] = self._ids.get(table, 0) + 1
                    row["id"] = self._ids[table]
                if table == "reward_cashout_requests" and row.get("status", "pending_review") in withdrawals.OPEN and any(
                        r["profile_id"] == row["profile_id"] and r["status"] in withdrawals.OPEN
                        for r in self.tables[table]):
                    raise StoreError("duplicate key (one open request per person)")
                if table == "reward_cashout_months" and any(
                        r["profile_id"] == row["profile_id"] and r["month"] == row["month"]
                        and r["status"] != "released" for r in self.tables[table]):
                    raise StoreError("duplicate key (month already covered by a withdrawal request)")
            if table == founding.TABLE:
                if not self._founding_fn:
                    raise StoreError("Founding 50 applications change only through the Founding 50 functions")
                if any(r["profile_id"] == row["profile_id"] for r in self.tables[table]):
                    raise StoreError("duplicate key (one application per person)")
                if row.get("id") is None:
                    self._ids[table] = self._ids.get(table, 0) + 1
                    row["id"] = self._ids[table]
            if table in FF10_TABLES and not self._ff10_fn:
                raise StoreError("Friends & Family 10 records change only through the database functions")
            if table in ("pilot_activity", "pilot_payments") and row.get("id") is None:
                self._ids[table] = self._ids.get(table, 0) + 1
                row["id"] = self._ids[table]
            if table not in ("pilot_activity", "pilot_payments") and any(self._key(table, r) == self._key(table, row)
                                                 for r in self.tables[table]):
                if ignore_duplicates:
                    return []
                raise StoreError("duplicate key")
            row.setdefault("created_at", _now())
            if table == "reward_activity_events":
                self._cap_event(row)
            elif table == "reward_payments":
                self._guard_payment(None, row)
            elif table == "reward_referral_visits":
                row.setdefault("updated_at", row["created_at"])
            self.tables[table].append(row)
            if table == "reward_payments":
                self._audit(table, "insert", None, row)
            return [dict(row)]

    def update(self, table, where, changes):
        with self.lock:
            out = []
            for i, old in enumerate(self.tables[table]):
                if not _match(old, where):
                    continue
                if table in ("reward_activity_events", "reward_audit_log", "reward_cashout_payments",
                             "pilot_activity", "pilot_settlements", "pilot_reward_settings", "pilot_payments",
                             "pilot_terms_acceptances"):
                    raise StoreError("records cannot be changed")
                if table == "pilot_settlement_lines":
                    self._guard_line(old, dict(old, **changes))
                if table == "pilot_day_reviews" and not self._ff10_fn:
                    raise StoreError("Friends & Family 10 records change only through the database functions")
                if table in ("reward_cashout_requests", "reward_cashout_months") and not self._cashout_fn:
                    raise StoreError("withdrawal records change only through the withdrawal functions")
                if table == founding.TABLE and not self._founding_fn:
                    raise StoreError("Founding 50 applications change only through the Founding 50 functions")
                if table == "reward_owner_notifications" and set(changes) - {"read_at", "read_by", "email_status"}:
                    raise StoreError("only the read and email status of a notification can change")
                new = dict(old, **changes)
                if table == "reward_enrolments":
                    self._guard_enrolment(old, new)
                if table == "reward_payments":
                    self._guard_payment(old, new)
                if table == "reward_program_settings" and not self._public_fn and any(
                        new.get(k) != old.get(k) for k in ("public_enabled", "public_changed_at", "public_changed_by")):
                    raise StoreError("the public programme switch changes only through reward_set_public_programme")
                if table == "reward_program_settings" and not getattr(self, "_pilot_fn", False) and any(
                        new.get(k) != old.get(k) for k in PILOT_COLUMNS):
                    raise StoreError("the pilot switches change only through reward_set_pilot / reward_set_invitation_only")
                if table == "reward_program_settings":
                    problems = Settings.from_row(new).validate()
                    if problems:
                        raise StoreError(problems[0])
                self.tables[table][i] = new
                watched = {"reward_program_settings": None, "reward_payments": None,
                           "reward_accounts": ("membership", "verification", "review"), "user_referrals": ("status",)}
                if table in watched and (watched[table] is None or any(c in changes for c in watched[table])):
                    self._audit(table, "update", old, new)
                out.append(dict(new))
            return out

    def delete(self, table, where):
        with self.lock:
            doomed = [r for r in self.tables[table] if _match(r, where)]
            if table in ("reward_accounts", "reward_audit_log", "reward_program_settings",
                         "reward_cashout_settings") and doomed:
                raise StoreError("records cannot be deleted")
            if any(not r.get("test") for r in doomed):
                raise StoreError("real records are kept and cannot be deleted")
            self.tables[table] = [r for r in self.tables[table] if r not in doomed]
            return len(doomed)

    def rpc(self, name, args):
        with self.lock:
            return getattr(self, "_rpc_" + name)(**args)

    # ---- trigger equivalents
    def _audit(self, table, op, old, new):
        actor = new.get("updated_by") or new.get("decided_by")
        target = {"reward_program_settings": "settings",
                  "reward_payments": f"{new.get('profile_id')} {new.get('month')}",
                  "user_referrals": new.get("referred_id")}.get(table, new.get("profile_id"))
        self._audit_id += 1
        self.tables["reward_audit_log"].append({"id": self._audit_id, "at": _now(), "actor": actor,
                                                "action": f"{table}_{op}", "target": target,
                                                "old_value": old, "new_value": dict(new)})

    def _cap_event(self, row):
        row.setdefault("detail", {})
        owner = next((a for a in self.tables["reward_accounts"] if a["profile_id"] == row["profile_id"]), None)
        if owner is None:
            raise StoreError("unknown profile (foreign key)")
        row["test"] = bool(owner.get("test"))   # test records follow the account
        if int(row.get("amount") or 0) <= 0:
            row["amount"], row["reason"] = 0, row.get("reason") or "activity_only"
            return
        settings = self.settings()
        pid, month, test = row["profile_id"], row["month"], bool(row.get("test"))
        account = next((a for a in self.tables["reward_accounts"] if a["profile_id"] == pid), None)
        enrolled = any(e["profile_id"] == pid and e["month"] == month and e["status"] == "enrolled"
                       and bool(e.get("test")) == test for e in self.tables["reward_enrolments"])
        eligible = bool(account and account.get("membership") == "member" and bool(account.get("test")) == test
                        and enrolled)
        if eligible and not settings.paused and str(row["day"]) < settings.start_date:
            row["amount"], row["reason"] = 0, "not_started"
            return
        month_events = [e for e in self.tables["reward_activity_events"]
                        if e["profile_id"] == pid and e["month"] == month and bool(e.get("test")) == test]
        row["amount"], row["reason"] = rewards.award(row["kind"], month_events, str(row["day"]), settings, eligible)
        if not test and row["amount"] > 0 and not self._approved(pid):    # = trigger reward_events_founding
            row["amount"], row["reason"] = 0, "not_approved"
        if not test and row["amount"] > 0 and not self._public_on():      # = trigger reward_events_public
            row["amount"], row["reason"] = 0, "programme_off"

    def _guard_payment(self, old, new):
        new["updated_at"] = _now()
        earned = sum(int(e["amount"]) for e in self.tables["reward_activity_events"]
                     if e["profile_id"] == new["profile_id"] and e["month"] == new["month"]
                     and bool(e.get("test")) == bool(new.get("test")))
        for k in ("approved_amount", "paid_amount"):
            new[k] = int(new.get(k) or 0)
        new.setdefault("status", "pending_review")
        if old is None:
            new["earned"] = earned
        if old is not None and old["status"] == "paid":
            if (new["status"] != "paid" or new["paid_amount"] != old["paid_amount"]
                    or new["approved_amount"] != old["approved_amount"]
                    or new.get("payment_date") != old.get("payment_date")):
                raise StoreError("a completed payment cannot be changed; add a remark instead")
        if new["status"] in ("approved", "paid") and not self._cashout_fn \
                and (old is None or old["status"] not in ("approved", "paid")) and any(
                m["profile_id"] == new["profile_id"] and m["month"] == new["month"] and m["status"] != "released"
                for m in self.tables["reward_cashout_months"]):
            raise StoreError(f"month {new['month']} of this participant is covered by a withdrawal request; manage it "
                             "under Withdrawals")
        if not self._cashout_fn:   # = reward_payments_settlement_guard: the WD- link of a settled month is kept
            settled = withdrawals.settled_by_withdrawal(new, self.tables["reward_cashout_months"])
            changed = old is None or new.get("reference") != old.get("reference")
            if settled and old is not None and changed:
                raise StoreError(f"the reference of a payment settled by withdrawal request {old.get('reference')} "
                                 "cannot be changed; add a remark instead")
            if not settled and changed and withdrawals.REFERENCE_RE.match(str(new.get("reference") or "").upper()):
                raise StoreError("references in the form WD-YYYYMM-XXXX are reserved for payments settled by a "
                                 "withdrawal request")
        if new["approved_amount"] > earned:
            raise StoreError(f"approved amount ({new['approved_amount']}) is more than was earned ({earned})")
        if not new.get("test") and new["status"] in ("approved", "paid") \
                and (old is None or old["status"] != new["status"]) and self._founding_blocks(new["profile_id"]):
            raise StoreError("founding_not_approved")                    # = trigger reward_payments_founding
        if new["status"] in ("approved", "paid"):
            account = next((a for a in self.tables["reward_accounts"] if a["profile_id"] == new["profile_id"]), {})
            if account.get("test") or new.get("test"):
                raise StoreError("test records are never payable")
            if account.get("verification") != "verified":
                raise StoreError("verify the participant's eligibility before approving a payment")
            if new["approved_amount"] <= 0:
                raise StoreError("set the approved amount first")
        if new["status"] == "paid" and (old is None or old["status"] not in ("approved", "paid")):
            raise StoreError("only an approved payment can be marked as paid")
        if new["status"] == "rejected":
            new["approved_amount"] = new["paid_amount"] = 0
        if new["paid_amount"] > new["approved_amount"]:
            raise StoreError("the paid amount cannot be more than the approved amount")
        if new["status"] == "paid" and (not new.get("payment_date") or new["paid_amount"] <= 0):
            raise StoreError("a paid record needs a payment date and amount")

    # ---- function equivalents
    def _rpc_reward_ensure_account(self, p_profile, p_email, p_name, p_new, p_test=False):
        accounts = self.tables["reward_accounts"]
        for a in accounts:
            if a["profile_id"] == p_profile:
                if p_email is not None:
                    a["email"] = p_email
                return dict(a)
        taken = {a["referral_code"] for a in accounts}
        code = rewards.new_referral_code()
        while code in taken:
            code = rewards.new_referral_code()
        row = {"profile_id": p_profile, "referral_code": code, "email": p_email,
               "display_name": (p_name or "")[:80] or None, "created_at": _now(), "new_registration": bool(p_new),
               "membership": "none", "age_confirmed": False, "residence_confirmed": False, "terms_version": None,
               "declared_at": None, "verification": "provisional", "verification_note": None, "review": "ok",
               "review_note": None, "test": bool(p_test)}
        accounts.append(row)
        return dict(row)

    def _rpc_reward_attribute(self, p_referred, p_code, p_visit=None):
        owner = self.account_by_code(str(p_code or "").strip().upper())
        me = self.account(p_referred)
        referrals = self.tables["user_referrals"]
        if not me or not owner:
            outcome = "unknown_code"
        elif owner["profile_id"] == p_referred:
            outcome = "self"
        elif any(r["referred_id"] == p_referred for r in referrals):
            outcome = "already_referred"
        elif not me.get("new_registration"):
            outcome = "existing_account"
        elif any(r["referred_id"] == owner["profile_id"] and r["referrer_id"] == p_referred for r in referrals):
            outcome = "circular"
        elif bool(owner.get("test")) != bool(me.get("test")):
            outcome = "unknown_code"
        else:
            referrals.append({"referred_id": p_referred, "referrer_id": owner["profile_id"],
                              "code": owner["referral_code"], "status": "pending", "created_at": _now(),
                              "qualified_at": None, "decided_at": None, "decided_by": None, "note": None,
                              "test": bool(me.get("test"))})
            outcome = "attributed"
        if p_visit:
            for v in self.tables["reward_referral_visits"]:
                if v["visit_key"] == p_visit:
                    v.update(outcome=outcome, referred_id=p_referred, updated_at=_now(),
                             referrer_id=v.get("referrer_id") or (owner or {}).get("profile_id"))
        return outcome

    def _usage(self, month):
        rows = [e for e in self.tables["reward_enrolments"] if e["month"] == month and not e.get("test")]
        places = sum(1 for e in rows if e["status"] == "enrolled")
        used = sum(int(e["reserved_amount"]) for e in rows if e["status"] in ("enrolled", "withdrawn"))
        return rows, places, used

    def _rpc_reward_enrol(self, p_profile, p_month):
        existing = self.enrolment(p_profile, p_month)
        if existing:
            return existing
        account = self.account(p_profile)
        if not account or account.get("membership") != "member":
            raise StoreError("not_member")
        s = self.settings()
        if s.paused:
            raise StoreError("paused")
        if not account.get("test") and not self._approved(p_profile):   # = trigger reward_enrolments_founding
            raise StoreError("not_approved")
        if not account.get("test") and not self._public_on():           # = trigger reward_enrolments_public
            raise StoreError("programme_off")
        row = {"profile_id": p_profile, "month": p_month, "reserved_amount": 0, "waitlist_position": None,
               "test": bool(account.get("test")), "created_at": _now(), "updated_at": _now(), "enrolled_at": None}
        if account.get("test"):
            row.update(status="enrolled", reserved_amount=s.monthly_cap)
        else:
            rows, places, used = self._usage(p_month)
            waiting = any(e["status"] == "waitlist" for e in rows)
            if places < s.max_places and used + s.monthly_cap <= s.monthly_budget and not waiting:
                row.update(status="enrolled", reserved_amount=s.monthly_cap)
            else:
                row.update(status="waitlist",
                           waitlist_position=max([e.get("waitlist_position") or 0 for e in rows] + [0]) + 1)
        if row["status"] == "enrolled":
            row["enrolled_at"] = _now()
        self.tables["reward_enrolments"].append(row)
        return dict(row)

    def _rpc_reward_promote_waitlist(self, p_month, p_actor=None):
        s = self.settings()
        if s.paused:
            return 0
        members = {a["profile_id"] for a in self.tables["reward_accounts"] if a.get("membership") == "member"}
        waiting = sorted((e for e in self.tables["reward_enrolments"]
                          if e["month"] == p_month and not e.get("test") and e["status"] == "waitlist"
                          and e["profile_id"] in members and self._approved(e["profile_id"])),
                         key=lambda e: (e.get("waitlist_position") or 0, e["created_at"]))
        moved = 0
        for e in waiting:
            _, places, used = self._usage(p_month)
            if places >= s.max_places or used + s.monthly_cap > s.monthly_budget:
                break
            if not self._public_on():                                    # = trigger reward_enrolments_public
                raise StoreError("programme_off")
            e.update(status="enrolled", reserved_amount=s.monthly_cap, waitlist_position=None, updated_at=_now(),
                     enrolled_at=_now())
            moved += 1
        if moved:
            self.log(p_actor, "waitlist_promoted", p_month, {"moved": moved})
        return moved

    def _rpc_reward_withdraw(self, p_profile, p_month, p_actor=None):
        earned = sum(int(e["amount"]) for e in self.tables["reward_activity_events"]
                     if e["profile_id"] == p_profile and e["month"] == p_month)
        out = None
        for e in self.tables["reward_enrolments"]:
            if e["profile_id"] == p_profile and e["month"] == p_month and e["status"] != "withdrawn":
                e.update(status="withdrawn", reserved_amount=min(int(e["reserved_amount"]), earned),
                         waitlist_position=None, updated_at=_now())
                out = dict(e)
        self.log(p_actor or p_profile, "withdrawn", f"{p_profile} {p_month}", {"earned": earned})
        return out

    # ---- cash withdrawals (the same rules as supabase/withdrawals_migration.sql)
    def _cashout_audit(self, table, op, old, new):
        self._audit_id += 1
        self.tables["reward_audit_log"].append({
            "id": self._audit_id, "at": _now(), "actor": new.get("updated_by") or new.get("recorded_by"),
            "action": f"{table}_{op}",
            "target": new.get("reference") or (f"request {new['request_id']}" if new.get("request_id") else "settings"),
            "old_value": dict(old) if old else None, "new_value": dict(new)})

    def _payable_checks(self, req) -> None:
        """Withdrawal approval never changes the player's general verification; real requests need it already
        (the existing payment rules require it), and the reserved months must still be net verified earnings."""
        account = self.account(req["profile_id"]) or {}
        if not req["test"] and account.get("verification") != "verified":
            raise StoreError("account_not_verified")
        if withdrawals.earnings_changed(req, self.tables["reward_cashout_months"],
                                        self.tables["reward_activity_events"], self.tables["user_referrals"]):
            raise StoreError("earnings_changed")

    def _public_on(self) -> bool:
        return bool(self.tables["reward_program_settings"][0].get("public_enabled"))

    def _rpc_reward_set_public_programme(self, p_enabled, p_actor, p_confirmed=False):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_enabled is None:
            raise StoreError("invalid_value")
        if p_enabled and not p_confirmed:
            raise StoreError("confirmation_required")
        self._public_fn = True
        try:
            row = self.update("reward_program_settings", {"id": 1}, {
                "public_enabled": bool(p_enabled), "public_changed_at": _now(), "public_changed_by": p_actor,
                "updated_at": _now(), "updated_by": p_actor})[0]
        finally:
            self._public_fn = False
        self.log(p_actor, "public_programme_on" if p_enabled else "public_programme_off", "settings",
                 {"public_enabled": bool(p_enabled), "confirmed": bool(p_confirmed)})
        return row

    # ---- Friends & Family 10 (supabase/pilot_invitations_migration.sql)
    def _settings_row(self) -> dict:
        return self.tables["reward_program_settings"][0]

    def _pilot_on(self) -> bool:
        return bool(self._settings_row().get("pilot_enabled"))

    def _invitation_only(self) -> bool:
        return self._settings_row().get("invitation_only") is not False

    def _invited(self, email) -> bool:
        e = founding.normalize_email(email)
        return bool(e) and any(r["email"] == e and not r.get("revoked_at") for r in self.tables[founding.INVITES])

    def _set_pilot_columns(self, changes: dict, actor: str) -> dict:
        self._pilot_fn = True
        try:
            return self.update("reward_program_settings", {"id": 1}, {**changes, "updated_at": _now(), "updated_by": actor})[0]
        finally:
            self._pilot_fn = False

    def _rpc_reward_set_pilot(self, p_enabled, p_actor, p_confirmed=False):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_enabled is None:
            raise StoreError("invalid_value")
        if p_enabled and not p_confirmed:
            raise StoreError("confirmation_required")
        if p_enabled and not self._settings_row().get("pilot_terms_version"):
            raise StoreError("terms_required")
        row = self._set_pilot_columns({"pilot_enabled": bool(p_enabled), "pilot_changed_at": _now(),
                                       "pilot_changed_by": p_actor}, p_actor)
        self.log(p_actor, "pilot_on" if p_enabled else "pilot_off", "settings",
                 {"pilot_enabled": bool(p_enabled), "confirmed": bool(p_confirmed)})
        return row

    def _rpc_reward_set_invitation_only(self, p_value, p_actor, p_confirmed=False):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_value is None:
            raise StoreError("invalid_value")
        if not p_value and not p_confirmed:
            raise StoreError("confirmation_required")
        if not p_value and not self._settings_row().get("public_terms_version"):
            raise StoreError("terms_required")
        row = self._set_pilot_columns({"invitation_only": bool(p_value), "invitation_changed_at": _now(),
                                       "invitation_changed_by": p_actor}, p_actor)
        self.log(p_actor, "invitation_only_on" if p_value else "invitation_only_off", "settings",
                 {"invitation_only": bool(p_value), "confirmed": bool(p_confirmed)})
        return row

    def _rpc_reward_set_participation_terms(self, p_mode, p_version, p_actor):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_mode not in ("pilot", "public"):
            raise StoreError("invalid_mode")
        v = str(p_version or "").strip()
        if not v or len(v) > 120:
            raise StoreError("invalid_value")
        row = self._set_pilot_columns({f"{p_mode}_terms_version": v, "terms_changed_at": _now(),
                                       "terms_changed_by": p_actor}, p_actor)
        self.log(p_actor, f"{p_mode}_terms_set", "settings", {"mode": p_mode, "terms_version": v})
        return row

    def _rpc_reward_pilot_invite(self, p_email, p_actor, p_note=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        e = founding.normalize_email(p_email)
        if not founding.email_ok(e):
            raise StoreError("invalid_email")
        if len(p_note or "") > founding.INVITE_NOTE_MAX:
            raise StoreError("note_too_long")
        row = {"email": e, "note": (p_note or "").strip() or None, "invited_by": p_actor, "invited_at": _now(),
               "revoked_at": None, "revoked_by": None, "updated_at": _now()}
        rows = self.tables[founding.INVITES]
        for i, r in enumerate(rows):
            if r["email"] == e:
                rows[i] = row
                break
        else:
            rows.append(row)
        self.log(p_actor, "pilot_invited", e, dict(row))
        return dict(row)

    def _rpc_reward_pilot_revoke(self, p_email, p_actor):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        e = founding.normalize_email(p_email)
        for r in self.tables[founding.INVITES]:
            if r["email"] == e and not r.get("revoked_at"):
                r.update(revoked_at=_now(), revoked_by=p_actor, updated_at=_now())
                self.log(p_actor, "pilot_revoked", e, dict(r))
                return dict(r)
        raise StoreError("not_invited")

    def _real_payouts(self) -> bool:
        return bool(self.tables["reward_cashout_settings"][0].get("real_payouts"))

    def _owner(self, actor) -> bool:
        owners = {str(x).strip().lower() for x in self.tables["reward_cashout_settings"][0].get("owner_emails") or []}
        return bool(actor) and str(actor).strip().lower() in owners

    def _rpc_reward_cashout_status(self, p_profile, p_as_of=None):
        try:
            return withdrawals.status(self.account(p_profile), self.tables["reward_cashout_settings"][0],
                                      self.tables["reward_enrolments"], self.tables["reward_activity_events"],
                                      self.tables["reward_cashout_months"], self.tables["reward_payments"],
                                      self.tables["reward_cashout_requests"], self.tables["reward_cashout_payments"],
                                      as_of=p_as_of, referrals=self.tables["user_referrals"], founding=True,
                                      application=self.founding_application(p_profile))
        except ValueError as error:
            raise StoreError(str(error)) from None

    def _rpc_reward_cashout_request(self, p_profile, p_legal_name, p_declarations, p_expected_amount, p_as_of=None,
                                    p_flags=None):
        st = self._rpc_reward_cashout_status(p_profile, p_as_of)
        if not st.get("eligible"):
            raise StoreError("not_eligible: " + (st.get("reasons") or ["unknown"])[0])
        if p_expected_amount != st["amount"]:
            raise StoreError("amount_changed")
        if not withdrawals.legal_name_ok(p_legal_name):
            raise StoreError("legal_name_required")
        if not withdrawals.declarations_complete(p_declarations):
            raise StoreError("declarations_required")
        account = self.account(p_profile)
        day = withdrawals.today(p_as_of)
        taken = {r["reference"] for r in self.tables["reward_cashout_requests"]}
        ref = withdrawals.new_reference(day)
        while ref in taken:
            ref = withdrawals.new_reference(day)
        test = bool(account.get("test"))
        now = _now()
        row = {"reference": ref, "profile_id": p_profile, "amount": st["amount"],
               "months": sorted(m["month"] for m in st["months"]), "legal_name": p_legal_name.strip(),
               "declarations": dict(p_declarations, declared_at=now), "status": "pending_review",
               "request_month": withdrawals.month_of(day), "requested_at": now, "simulated_as_of": p_as_of,
               "flags": list(p_flags or []), "beneficiary_verified": False, "eligibility_confirmed": False,
               "bank_fingerprint": None, "decision_note": None, "approved_by": None, "approved_at": None,
               "decided_by": None, "decided_at": None, "paid_at": None, "test": test, "updated_at": now,
               "updated_by": p_profile}
        self._cashout_fn = True
        try:
            req = self.insert("reward_cashout_requests", row)[0]
            for m in st["months"]:
                self.insert("reward_cashout_months", {"request_id": req["id"], "profile_id": p_profile,
                                                      "month": m["month"], "amount": m["amount"],
                                                      "status": "reserved", "test": test, "updated_at": now})
            self.insert("reward_owner_notifications", {
                "kind": "cashout_request", "request_id": req["id"], "title": "New withdrawal request",
                "details": {"reference": ref, "player": account.get("display_name") or account.get("email")
                            or p_profile[:10], "amount": req["amount"], "requested_at": now,
                            "months": req["months"]},
                "read_at": None, "read_by": None, "email_status": "pending", "test": test})
            self._cashout_audit("reward_cashout_requests", "insert", None, req)
        finally:
            self._cashout_fn = False
        return dict(req)

    def _locked_request(self, p_id, p_actor):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        req = next((r for r in self.tables["reward_cashout_requests"] if r["id"] == int(p_id)), None)
        if req is None:
            raise StoreError("unknown_request")
        return req

    def _rpc_reward_cashout_decide(self, p_id, p_action, p_actor, p_note=None, p_beneficiary_verified=False,
                                   p_eligibility_confirmed=False, p_disqualify=False):
        req = self._locked_request(p_id, p_actor)
        error = withdrawals.transition_error(req["status"], p_action, p_note, p_beneficiary_verified,
                                             p_eligibility_confirmed)
        if error:
            raise StoreError(error)
        new = withdrawals.ACTIONS[p_action]
        reserved = sum(int(m["amount"]) for m in self.tables["reward_cashout_months"]
                       if m["request_id"] == req["id"] and m["status"] == "reserved")
        if new == "approved" and not req["test"] and not self._real_payouts():
            raise StoreError("payouts_disabled")
        if new == "approved" and reserved != req["amount"]:
            raise StoreError("reservation_mismatch")
        if new == "approved":
            self._payable_checks(req)
        if new == "approved" and not req["test"] and self._founding_blocks(req["profile_id"]):
            raise StoreError("founding_not_approved")                    # = trigger reward_cashout_founding
        old, now, note = dict(req), _now(), (p_note or "").strip() or None
        req.update(status=new, decision_note=note or req.get("decision_note"), decided_by=p_actor, decided_at=now,
                   updated_by=p_actor, updated_at=now)
        if new == "approved":
            req.update(beneficiary_verified=True, eligibility_confirmed=True, approved_by=p_actor, approved_at=now)

        if new == "rejected":
            for m in self.tables["reward_cashout_months"]:
                if m["request_id"] == req["id"] and m["status"] == "reserved":
                    m.update(status="disqualified" if p_disqualify else "released", updated_at=now)
        for n in self.tables["reward_owner_notifications"]:
            if n.get("request_id") == req["id"] and not n.get("read_at"):
                n.update(read_at=now, read_by=p_actor)
        self._cashout_audit("reward_cashout_requests", "update", old, req)
        return dict(req)

    def _rpc_reward_cashout_pay(self, p_id, p_amount, p_payment_date, p_reference, p_actor):
        req = self._locked_request(p_id, p_actor)
        if req["status"] == "paid" or any(p["request_id"] == req["id"] for p in self.tables["reward_cashout_payments"]):
            raise StoreError("already_paid")
        if req["status"] != "approved":
            raise StoreError("not_approved")
        if not req["test"] and not self._real_payouts():
            raise StoreError("payouts_disabled")
        if p_amount != req["amount"]:
            raise StoreError("amount_mismatch")
        self._payable_checks(req)
        if not req["test"] and self._founding_blocks(req["profile_id"]):
            raise StoreError("founding_not_approved")                    # = trigger reward_cashout_founding
        if not p_payment_date:
            raise StoreError("payment_date_required")
        pay_day = withdrawals.today(p_payment_date)
        if not req["test"] and pay_day > withdrawals.today():
            raise StoreError("payment_date_in_future")
        if not req["test"] and pay_day < withdrawals.lagos_date(req["approved_at"]):
            raise StoreError("payment_before_approval")
        reference = (p_reference or "").strip() or None
        if reference and not req["test"] and any(
                (p.get("bank_reference") or "").lower() == reference.lower() and not p.get("test")
                for p in self.tables["reward_cashout_payments"]):
            raise StoreError("duplicate_reference")
        now = _now()
        self._cashout_fn = True
        try:
            pay = self.insert("reward_cashout_payments", {
                "request_id": req["id"], "profile_id": req["profile_id"], "amount": req["amount"],
                "payment_date": pay_day.isoformat(), "payment_month": withdrawals.month_of(pay_day),
                "bank_reference": reference, "recorded_by": p_actor, "recorded_at": now, "test": req["test"]})[0]
        finally:
            self._cashout_fn = False
        old = dict(req)
        req.update(status="paid", paid_at=now, decided_by=p_actor, decided_at=now, updated_by=p_actor,
                   updated_at=now)
        for m in self.tables["reward_cashout_months"]:
            if m["request_id"] == req["id"] and m["status"] == "reserved":
                m.update(status="paid", updated_at=now)
        if not req["test"]:   # settle each month in the existing reward_payments table (its own rules apply)
            self._cashout_fn = True
            try:
                for m in sorted((m for m in self.tables["reward_cashout_months"] if m["request_id"] == req["id"]),
                                key=lambda m: m["month"]):
                    self.insert("reward_payments", {"profile_id": req["profile_id"], "month": m["month"],
                                                    "test": False, "updated_by": p_actor},
                                ignore_duplicates=True)
                    current = self.payment(req["profile_id"], m["month"])
                    remarks = ((current.get("remarks") + " · ") if current.get("remarks") else "") \
                        + f"Paid through withdrawal request {req['reference']}"
                    self.update("reward_payments", {"profile_id": req["profile_id"], "month": m["month"]},
                                {"status": "approved", "approved_amount": m["amount"], "remarks": remarks,
                                 "updated_by": p_actor})
                    self.update("reward_payments", {"profile_id": req["profile_id"], "month": m["month"]},
                                {"status": "paid", "paid_amount": m["amount"], "payment_date": pay_day.isoformat(),
                                 "reference": req["reference"], "updated_by": p_actor})
            finally:
                self._cashout_fn = False
        self._cashout_audit("reward_cashout_payments", "insert", None, pay)
        self._cashout_audit("reward_cashout_requests", "update", old, req)
        return dict(pay)

    def _rpc_reward_cashout_set_fingerprint(self, p_id, p_fingerprint, p_actor):
        req = self._locked_request(p_id, p_actor)
        if not p_fingerprint or not re.fullmatch(r"[0-9a-f]{64}", str(p_fingerprint)):
            raise StoreError("invalid_fingerprint")
        if req["status"] in ("paid", "rejected"):
            raise StoreError("request_closed")
        old = dict(req)
        req.update(bank_fingerprint=p_fingerprint, updated_by=p_actor, updated_at=_now())
        self._cashout_audit("reward_cashout_requests", "update", old, req)
        return len({r["profile_id"] for r in self.tables["reward_cashout_requests"]
                    if r.get("bank_fingerprint") == p_fingerprint and r["profile_id"] != req["profile_id"]
                    and bool(r.get("test")) == bool(req.get("test"))})

    # ---- Founding 50 (the same rules as supabase/founding50_migration.sql)
    def _founding_row(self, profile_id):
        return next((a for a in self.tables[founding.TABLE] if a["profile_id"] == profile_id), None)

    def _approved(self, profile_id) -> bool:
        return founding.approved(self._founding_row(profile_id), self.account(profile_id))

    def _founding_blocks(self, profile_id) -> bool:
        return founding.blocks_payment(self._founding_row(profile_id), self.account(profile_id))

    def _guard_enrolment(self, old, new):
        """= trigger reward_enrolments_founding on updates (waiting-list moves and the like)."""
        if new.get("status") == "enrolled" and old.get("status") != "enrolled":
            new["enrolled_at"] = _now()
        if not new.get("test") and new.get("status") in ("enrolled", "waitlist") \
                and new.get("status") != old.get("status") and not self._approved(new["profile_id"]):
            raise StoreError("not_approved")

    def _founding_update(self, app_id, changes):
        self._founding_fn = True
        try:
            return self.update(founding.TABLE, {"id": app_id}, changes)[0]
        finally:
            self._founding_fn = False

    def _rpc_reward_founding_apply(self, p_profile, p_state, p_note, p_adult, p_resident, p_terms,
                                   p_terms_version):
        account = self.account(p_profile)
        error = founding.apply_error(account, self._founding_row(p_profile), p_state, p_note, p_adult, p_resident,
                                     p_terms, self._public_on(), pilot_on=self._pilot_on(),
                                     invitation_only=self._invitation_only(),
                                     invited=self._invited((account or {}).get("email")),
                                     terms_version=p_terms_version,
                                     pilot_terms=self._settings_row().get("pilot_terms_version"),
                                     public_terms=self._settings_row().get("public_terms_version"))
        if error is None and not str(p_terms_version or "").strip():
            error = "declarations_required"
        if error:
            raise StoreError(error)
        now = _now()
        self._founding_fn = True
        try:
            app = self.insert(founding.TABLE, {
                "profile_id": p_profile, "status": "pending", "state": str(p_state).strip(),
                "note": (p_note or "").strip() or None, "age_confirmed": True, "residence_confirmed": True,
                "terms_version": str(p_terms_version).strip(), "applied_at": now, "first_approved_at": None,
                "approved_at": None, "decided_at": None, "decided_by": None, "decision_note": None, "seen_at": None,
                "seen_by": None, "test": bool(account.get("test")), "updated_at": now})[0]
        finally:
            self._founding_fn = False
        self.log(p_profile, "founding_applied", p_profile, dict(app))
        return app

    def _rpc_reward_founding_decide(self, p_id, p_action, p_actor, p_note=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_action not in founding.ACTIONS:
            raise StoreError("invalid_action")
        app = next((a for a in self.tables[founding.TABLE] if a["id"] == int(p_id)), None)
        taken = sum(1 for a in self.tables[founding.TABLE] if a["status"] == "approved" and not a.get("test"))
        error = founding.decide_error(app, p_action, p_note, taken, self.settings().max_places)
        if error:
            raise StoreError(error)
        if p_action == "approve" and not app.get("test") and app["status"] != "approved" \
                and self._ff10_places_full(app["profile_id"]):
            raise StoreError("places_full")
        new, note, now, before = founding.ACTIONS[p_action], (p_note or "").strip() or None, _now(), app["status"]
        changes = {"status": new, "decided_at": now, "decided_by": p_actor,
                   "decision_note": note or app.get("decision_note"), "seen_at": app.get("seen_at") or now,
                   "seen_by": app.get("seen_by") or p_actor, "updated_at": now}
        if new == "approved":
            changes.update(approved_at=now, first_approved_at=app.get("first_approved_at") or now)
        row = self._founding_update(app["id"], changes)
        if before == "approved":   # the place and budget are freed; what was earned is kept
            for e in sorted((e for e in self.tables["reward_enrolments"]
                             if e["profile_id"] == row["profile_id"] and e["status"] != "withdrawn"
                             and e["month"] >= rewards.month_key()),                 # past months untouched
                            key=lambda e: e["month"]):
                self._rpc_reward_withdraw(row["profile_id"], e["month"], p_actor)
        self.log(p_actor, "founding_" + new, row["profile_id"], {"status": new, "note": note, "test": row["test"]})
        self.tables["reward_audit_log"][-1]["old_value"] = {"status": before}
        return row

    def _rpc_reward_founding_mark_seen(self, p_actor, p_id=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        n = 0
        for a in list(self.tables[founding.TABLE]):
            if not a.get("seen_at") and (p_id is None or a["id"] == int(p_id)):
                self._founding_update(a["id"], {"seen_at": _now(), "seen_by": p_actor})
                n += 1
        return n

    # ---- Friends & Family 10 (= supabase/friends_family10_migration.sql)
    def _ff10_settings(self) -> dict:
        return self.tables["pilot_reward_settings"][0]

    def _ff10_settled(self, month: str) -> bool:
        return any(r["month"] == month for r in self.tables["pilot_settlements"])

    def _ff10_insert(self, table, row):
        self._ff10_fn = True
        try:
            return self.insert(table, row)[0]
        finally:
            self._ff10_fn = False

    def _guard_line(self, old, new):
        """= trigger pilot_settlement_lines_guard."""
        if any(new.get(k) != old.get(k) for k in ("month", "profile_id", "provisional", "final")):
            raise StoreError("settled amounts cannot be changed")
        if not self._ff10_fn:
            raise StoreError("settlement lines change only through the owner functions")
        if old["status"] == "paid":
            raise StoreError("already_paid")

    def _rpc_pilot_record_activity(self, p_profile, p_kind, p_subject, p_detail=None):
        return self._rpc_pilot_record_activity_at(p_profile, p_kind, p_subject, p_detail, _now())

    def _rpc_pilot_record_activity_at(self, p_profile, p_kind, p_subject, p_detail, p_at):
        subject = pilot_rewards.clean_subject(p_subject)
        if p_kind not in pilot_rewards.KINDS or not subject:
            raise StoreError("invalid_activity")
        account = self.account(p_profile)
        if account is None:
            raise StoreError("unknown_account")
        day = pilot_rewards.lagos_day(p_at)
        if not account.get("test"):
            if not self._pilot_on():
                raise StoreError("pilot_closed")
            if not self._ff10_participant(p_profile):
                raise StoreError("not_participant")
            if self._ff10_settled(day[:7]):
                raise StoreError("month_settled")
        history = [r for r in self.tables["pilot_activity"]
                   if r["profile_id"] == p_profile and r["kind"] == p_kind and r["subject"] == subject]
        if not pilot_rewards.accept(history, p_kind, subject, p_at):
            return None
        detail = None
        if p_kind in ("quiz", "challenge") and isinstance(p_detail, dict):
            detail = {k: p_detail[k] for k in ("questions", "avg_seconds")
                      if isinstance(p_detail.get(k), (int, float)) and not isinstance(p_detail.get(k), bool)} or None
        return self._ff10_insert("pilot_activity", {
            "profile_id": p_profile, "day": day, "kind": p_kind, "subject": subject, "detail": detail,
            "test": bool(account.get("test")), "at": p_at if isinstance(p_at, str) else p_at.isoformat()})

    def _ff10_excluded(self, profile_id) -> set[str]:
        return {str(r["day"])[:10] for r in self.tables["pilot_day_reviews"]
                if r["profile_id"] == profile_id and r["excluded"]}

    def _rpc_pilot_month_days(self, p_profile, p_month):
        rows = [r for r in self.tables["pilot_activity"] if r["profile_id"] == p_profile and not r.get("test")]
        days = pilot_rewards.month_ledger(pilot_rewards.day_summaries(rows, self._ff10_excluded(p_profile)), p_month)
        return [{"day": d.day, "seconds": d.seconds, "minutes": d.minutes, "quizzes": d.quizzes,
                 "challenge": d.challenge, "new_countries": d.new_countries, "interactions": d.interactions,
                 "tier": d.tier, "tier_amount": d.tier_amount, "excluded": d.excluded, "amount": d.amount}
                for d in days]

    def _rpc_pilot_settlement_preview(self, p_month):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(p_month or "")):
            raise StoreError("invalid_month")
        people = {r["profile_id"] for r in self.tables["pilot_activity"]
                  if not r.get("test") and str(r["day"])[:7] == p_month}
        rows = {pid: [r for r in self.tables["pilot_activity"] if r["profile_id"] == pid and not r.get("test")]
                for pid in people}
        return pilot_rewards.settlement_preview(rows, p_month, {pid: self._ff10_excluded(pid) for pid in people},
                                                self._ff10_settings()["monthly_budget"])

    def _rpc_pilot_review_day(self, p_profile, p_day, p_excluded, p_actor, p_reason=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        reason = (p_reason or "").strip() or None
        if p_excluded and not reason:
            raise StoreError("reason_required")
        if reason and len(reason) > 500:
            raise StoreError("note_too_long")
        if self._ff10_settled(str(p_day)[:7]):
            raise StoreError("month_settled")
        row = {"profile_id": p_profile, "day": str(p_day)[:10], "excluded": bool(p_excluded), "reason": reason,
               "reviewed_by": p_actor, "reviewed_at": _now()}
        self.tables["pilot_day_reviews"] = [r for r in self.tables["pilot_day_reviews"]
                                            if (r["profile_id"], r["day"]) != (row["profile_id"], row["day"])]
        self._ff10_insert("pilot_day_reviews", row)
        self.log(p_actor, "pilot_day_excluded" if p_excluded else "pilot_day_restored", f"{p_profile} {row['day']}", row)
        return row

    def _rpc_pilot_settle_month(self, p_month, p_actor, p_confirmed, p_expected_fingerprint):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if not p_confirmed:
            raise StoreError("confirmation_required")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(p_month or "")):
            raise StoreError("invalid_month")
        if not pilot_rewards.month_ended(p_month):
            raise StoreError("month_not_ended")
        if self._ff10_settled(p_month):
            raise StoreError("already_settled")
        preview = self._rpc_pilot_settlement_preview(p_month)
        if not p_expected_fingerprint or preview["fingerprint"] != p_expected_fingerprint:
            raise StoreError("preview_changed")
        row = self._ff10_insert("pilot_settlements", {
            "month": p_month, "budget": preview["budget"], "total_provisional": preview["total_provisional"],
            "total_final": preview["total_final"], "participants": len(preview["lines"]), "scaled": preview["scaled"],
            "fingerprint": preview["fingerprint"],
            "finalised_by": p_actor, "finalised_at": _now()})
        for line in preview["lines"]:
            self._ff10_insert("pilot_settlement_lines", {
                "month": p_month, "profile_id": line["profile_id"], "provisional": line["provisional"],
                "final": line["final"], "status": "pending_review", "decided_by": None, "decided_at": None,
                "note": None, "paid_at": None, "payment_reference": None})
        self.log(p_actor, "pilot_settled", p_month, preview)
        return row

    def _ff10_line(self, month, profile_id):
        return next((r for r in self.tables["pilot_settlement_lines"]
                     if r["month"] == month and r["profile_id"] == profile_id), None)

    def _ff10_update_line(self, month, profile_id, changes):
        self._ff10_fn = True
        try:
            return self.update("pilot_settlement_lines", {"month": month, "profile_id": profile_id}, changes)[0]
        finally:
            self._ff10_fn = False

    def _rpc_pilot_settlement_decide(self, p_month, p_profile, p_action, p_actor, p_note=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        new = {"approve": "approved", "withhold": "withheld"}.get(p_action)
        if not new:
            raise StoreError("invalid_action")
        line = self._ff10_line(p_month, p_profile)
        if line is None:
            raise StoreError("unknown_line")
        if line["status"] == "paid":
            raise StoreError("already_paid")
        if line["status"] == new:
            raise StoreError("no_change")
        note = (p_note or "").strip() or None
        if note and len(note) > 500:
            raise StoreError("note_too_long")
        if (new == "withheld" or line["status"] != "pending_review") and not note:
            raise StoreError("reason_required")
        before = dict(line)
        row = self._ff10_update_line(p_month, p_profile, {"status": new, "decided_by": p_actor,
                                                          "decided_at": _now(), "note": note or line.get("note")})
        self.log(p_actor, "pilot_line_" + new, f"{p_profile} {p_month}", row)
        self.tables["reward_audit_log"][-1]["old_value"] = before
        return row

    def _rpc_pilot_mark_paid(self, p_month, p_profile, p_actor, p_reference=None):
        raise StoreError("use_pilot_record_payment")

    # ---- real cash payments (= supabase/friends_family10_payments_migration.sql)
    def _rpc_pilot_set_payments(self, p_enabled, p_actor, p_confirmed=False):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if p_enabled and not p_confirmed:
            raise StoreError("confirmation_required")
        if p_enabled and not str(self._settings_row().get("pilot_terms_version") or "").strip():
            raise StoreError("terms_required")
        row = self._ff10_settings()
        row.update(payments_enabled=bool(p_enabled), payments_changed_at=_now(), payments_changed_by=p_actor)
        self.log(p_actor, "pilot_payments_on" if p_enabled else "pilot_payments_off", "pilot_payments",
                 {"payments_enabled": bool(p_enabled)})
        return dict(row)

    def _rpc_pilot_verify_beneficiary(self, p_profile, p_legal_name, p_bank_name, p_account_last4, p_actor,
                                      p_confirmed, p_note=None):
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if not p_confirmed:
            raise StoreError("confirmation_required")
        if not self._ff10_participant(p_profile):
            raise StoreError("not_participant")
        if not re.fullmatch(r"[0-9]{4}", str(p_account_last4 or "").strip()):
            raise StoreError("invalid_account_last4")
        name, bank = str(p_legal_name or "").strip(), str(p_bank_name or "").strip()
        if len(name) < 3 or len(bank) < 2:
            raise StoreError("details_required")
        row = {"profile_id": p_profile, "legal_name": name[:120], "bank_name": bank[:80],
               "account_last4": str(p_account_last4).strip(), "verified": True,
               "note": (p_note or "").strip()[:500] or None, "verified_by": p_actor, "verified_at": _now()}
        self.tables["pilot_beneficiaries"] = [r for r in self.tables["pilot_beneficiaries"] if r["profile_id"] != p_profile]
        self._ff10_insert("pilot_beneficiaries", row)
        self.log(p_actor, "pilot_beneficiary_verified", p_profile, row)
        return row

    def _rpc_pilot_record_payment(self, p_month, p_profile, p_amount, p_paid_on, p_reference, p_actor, p_confirmed):
        from datetime import date as _date
        if not self._owner(p_actor):
            raise StoreError("not_owner")
        if not p_confirmed:
            raise StoreError("confirmation_required")
        settings = self._ff10_settings()
        if not settings["payments_enabled"]:
            raise StoreError("payments_disabled")
        settlement = next((r for r in self.tables["pilot_settlements"] if r["month"] == p_month), None)
        if settlement is None:
            raise StoreError("not_settled")
        line = self._ff10_line(p_month, p_profile)
        if line is None:
            raise StoreError("unknown_line")
        payments = [r for r in self.tables["pilot_payments"] if r["month"] == p_month]
        if line["status"] == "paid" or any(r["profile_id"] == p_profile for r in payments):
            raise StoreError("already_paid")
        if line["status"] != "approved":
            raise StoreError("not_approved")
        ben = next((r for r in self.tables["pilot_beneficiaries"] if r["profile_id"] == p_profile and r["verified"]), None)
        if ben is None:
            raise StoreError("beneficiary_not_verified")
        if p_amount != line["final"] or line["final"] <= 0:
            raise StoreError("amount_mismatch")
        paid = sum(int(r["amount"]) for r in payments)
        if paid + p_amount > settlement["total_final"] or paid + p_amount > settings["monthly_budget"]:
            raise StoreError("budget_exceeded")
        ref = str(p_reference or "").strip()
        if len(ref) < pilot_rewards.REFERENCE_MIN:
            raise StoreError("reference_required")
        if any(r["bank_reference"] == ref for r in self.tables["pilot_payments"]):
            raise StoreError("duplicate_reference")
        try:
            paid_on = _date.fromisoformat(str(p_paid_on)[:10])
        except ValueError:
            raise StoreError("invalid_date")
        today = rewards.lagos_now().date()
        settled_on = rewards.lagos_now(rewards._dt(settlement["finalised_at"])).date()
        if paid_on > today or paid_on < settled_on:
            raise StoreError("invalid_date")
        row = self._ff10_insert("pilot_payments", {
            "month": p_month, "profile_id": p_profile, "amount": int(p_amount), "paid_on": paid_on.isoformat(),
            "bank_reference": ref, "beneficiary_name": ben["legal_name"], "bank_name": ben["bank_name"],
            "account_last4": ben["account_last4"], "status": "paid", "recorded_by": p_actor, "recorded_at": _now()})
        self._ff10_update_line(p_month, p_profile, {"status": "paid", "paid_at": _now(), "payment_reference": ref,
                                                    "decided_by": p_actor, "decided_at": _now()})
        self.log(p_actor, "pilot_payment_recorded", f"{p_profile} {p_month}", row)
        return row

    def _email(self, profile_id) -> str | None:
        return (self.account(profile_id) or {}).get("email")

    def _ff10_participant(self, profile_id) -> bool:
        """= pilot_is_participant: approved real application AND an active invitation (whatever Public Rewards says)
        AND the current private terms accepted."""
        return self._ff10_member(profile_id) and self._ff10_accepted(profile_id)

    def _ff10_member(self, profile_id) -> bool:
        """Approved real application AND an active invitation."""
        account = self.account(profile_id)
        return bool(account) and not account.get("test") \
            and founding.approved(self._founding_row(profile_id), account) and self._invited(account.get("email"))

    def _ff10_accepted(self, profile_id) -> bool:
        """= pilot_terms_accepted: applied with, or since accepted, the currently recorded pilot terms."""
        current = str(self._settings_row().get("pilot_terms_version") or "").strip()
        if not current:
            return False
        app = self._founding_row(profile_id)
        return bool(app and app.get("terms_version") == current) or any(
            r["profile_id"] == profile_id and r["terms_version"] == current
            for r in self.tables["pilot_terms_acceptances"])

    def _rpc_pilot_accept_terms(self, p_profile, p_terms_version):
        if not self._ff10_member(p_profile):
            raise StoreError("not_participant")
        current = str(self._settings_row().get("pilot_terms_version") or "").strip()
        if not current:
            raise StoreError("terms_required")
        if str(p_terms_version or "").strip() != current:
            raise StoreError("terms_outdated")
        row = next((r for r in self.tables["pilot_terms_acceptances"]
                    if r["profile_id"] == p_profile and r["terms_version"] == current), None)
        if row is None:
            row = self._ff10_insert("pilot_terms_acceptances", {"profile_id": p_profile, "terms_version": current,
                                                                "accepted_at": _now()})
        self.log(p_profile, "pilot_terms_accepted", p_profile, dict(row))
        return dict(row)

    def _ff10_places_full(self, profile_id) -> bool:
        """= trigger pilot_places_guard. Public Rewards OFF: at most 10 approved. Public Rewards ON: approving an
        invited person (a pilot member) needs one of the 10 pilot places; public applicants are not counted here."""
        public = self._public_on()
        if public and not self._invited(self._email(profile_id)):
            return False
        taken = sum(1 for a in self.tables[founding.TABLE] if a["status"] == "approved" and not a.get("test")
                    and a["profile_id"] != profile_id and (not public or self._invited(self._email(a["profile_id"]))))
        return taken >= self._ff10_settings()["max_participants"]


def payable_rows(rows: list[dict]) -> list[dict]:
    """Real records only (test records are never payable and never counted in real figures)."""
    return [r for r in rows if not r.get("test")]
