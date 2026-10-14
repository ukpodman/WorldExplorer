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

from core import rewards, withdrawals
from core.rewards import Settings

TABLES = ("reward_program_settings", "reward_accounts", "reward_enrolments", "reward_activity_events",
          "user_referrals", "reward_referral_visits", "reward_payments", "reward_audit_log")
CASHOUT_TABLES = ("reward_cashout_settings", "reward_cashout_requests", "reward_cashout_months",
                  "reward_cashout_payments", "reward_owner_notifications")   # supabase/withdrawals_migration.sql
PAGE = 1000


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
        if self.cashout_health() == "ok":   # withdrawal test records first (they refer to accounts)
            for table in ("reward_owner_notifications", "reward_cashout_payments", "reward_cashout_months",
                          "reward_cashout_requests"):
                self.delete(table, {"test": True})
        for table in ("reward_payments", "reward_activity_events", "user_referrals", "reward_referral_visits",
                      "reward_enrolments"):
            self.delete(table, {"test": True})
        self.log(actor, "test_data_cleared")

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
            "reward_owner_notifications": ("id",)}

    def __init__(self, settings: Settings | None = None, owner_emails: list[str] | None = None):
        self.lock = threading.RLock()
        self.tables: dict[str, list[dict]] = {t: [] for t in TABLES + CASHOUT_TABLES}
        row = (settings or Settings()).as_row()
        row.update(id=1, updated_at=_now(), updated_by=None)
        self.tables["reward_program_settings"].append(row)
        self.tables["reward_cashout_settings"].append({"id": 1, "live_requests": False, "real_payouts": False,
                                                       "min_days": withdrawals.MIN_DAYS,
                                                       "owner_emails": list(owner_emails or []),
                                                       "updated_at": _now(), "updated_by": None})
        self._audit_id = 0
        self._ids: dict[str, int] = {}
        self._cashout_fn = False   # like the database's we.cashout flag: set only inside the withdrawal functions

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
            if any(self._key(table, r) == self._key(table, row) for r in self.tables[table]):
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
                if table in ("reward_activity_events", "reward_audit_log", "reward_cashout_payments"):
                    raise StoreError("records cannot be changed")
                if table in ("reward_cashout_requests", "reward_cashout_months") and not self._cashout_fn:
                    raise StoreError("withdrawal records change only through the withdrawal functions")
                if table == "reward_owner_notifications" and set(changes) - {"read_at", "read_by", "email_status"}:
                    raise StoreError("only the read and email status of a notification can change")
                new = dict(old, **changes)
                if table == "reward_payments":
                    self._guard_payment(old, new)
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
        if new["status"] in ("approved", "paid") and not self._cashout_fn and any(
                m["profile_id"] == new["profile_id"] and m["month"] == new["month"] and m["status"] != "released"
                for m in self.tables["reward_cashout_months"]):
            raise StoreError(f"month {new['month']} of this participant is covered by a withdrawal request; manage it "
                             "under Withdrawals")
        if new["approved_amount"] > earned:
            raise StoreError(f"approved amount ({new['approved_amount']}) is more than was earned ({earned})")
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
        row = {"profile_id": p_profile, "month": p_month, "reserved_amount": 0, "waitlist_position": None,
               "test": bool(account.get("test")), "created_at": _now(), "updated_at": _now()}
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
        self.tables["reward_enrolments"].append(row)
        return dict(row)

    def _rpc_reward_promote_waitlist(self, p_month, p_actor=None):
        s = self.settings()
        if s.paused:
            return 0
        members = {a["profile_id"] for a in self.tables["reward_accounts"] if a.get("membership") == "member"}
        waiting = sorted((e for e in self.tables["reward_enrolments"]
                          if e["month"] == p_month and not e.get("test") and e["status"] == "waitlist"
                          and e["profile_id"] in members),
                         key=lambda e: (e.get("waitlist_position") or 0, e["created_at"]))
        moved = 0
        for e in waiting:
            _, places, used = self._usage(p_month)
            if places >= s.max_places or used + s.monthly_cap > s.monthly_budget:
                break
            e.update(status="enrolled", reserved_amount=s.monthly_cap, waitlist_position=None, updated_at=_now())
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
                                      as_of=p_as_of)
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
        old, now, note = dict(req), _now(), (p_note or "").strip() or None
        req.update(status=new, decision_note=note or req.get("decision_note"), decided_by=p_actor, decided_at=now,
                   updated_by=p_actor, updated_at=now)
        if new == "approved":
            req.update(beneficiary_verified=True, eligibility_confirmed=True, approved_by=p_actor, approved_at=now)
            if not req["test"]:   # the owner confirmed eligibility: the account counts as verified
                for a in self.tables["reward_accounts"]:
                    if a["profile_id"] == req["profile_id"] and a.get("verification") != "verified":
                        old_account = dict(a)
                        a.update(verification="verified", verification_note=a.get("verification_note")
                                 or f"Verified by the owner for withdrawal {req['reference']}")
                        self._audit("reward_accounts", "update", old_account, a)
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


def payable_rows(rows: list[dict]) -> list[dict]:
    """Real records only (test records are never payable and never counted in real figures)."""
    return [r for r in rows if not r.get("test")]
