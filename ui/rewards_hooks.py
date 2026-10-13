"""The rewards programme inside the running app: switches, storage choice, referral capture and the small hooks that
record validated activity (finished quizzes and genuine country exploration).

Nothing here runs for ordinary visitors while the programme is switched off ([rewards] enabled = false, the
default): every hook returns at once. Owners and testers listed in secrets can try the programme meanwhile; their
records are marked as test records and are never payable.

All amounts are decided by the database (core/rewards_store.py, supabase/rewards_schema.sql). A failure here never
interrupts play: hooks swallow errors and simply record nothing.
"""
from __future__ import annotations

import hashlib
import secrets as _secrets
import time

import streamlit as st

from core import accounts, analytics, cookies, rewards
from core.rewards_store import MemoryStore, RewardsStore, StoreError, SupabaseStore

REF_COOKIE = "we_ref"
REF_COOKIE_AGE = 30 * 24 * 3600          # an invitation link is remembered for 30 days in that browser
HEALTH_TTL = 60
APP_URL = "https://world-explorer-ukpodman.streamlit.app/"


# --------------------------------------------------------------------------- switches (server-side secrets)

def config() -> dict:
    try:
        return dict(st.secrets.get("rewards", {}))
    except Exception:
        return {}


def enabled() -> bool:
    """The public programme is on (owner switch). Default off."""
    return bool(config().get("enabled"))


def payouts_active() -> bool:
    """Real money can be approved and paid (owner switch, after legal review). Default off."""
    return bool(config().get("payouts_active"))


def _verified_email() -> str:
    who = accounts.identity()
    if not who or who.get("email_verified") not in (True, "true", "True"):
        return ""
    return str(who.get("email") or "").strip().lower()


def tester() -> bool:
    """Owner or a listed tester: may use the programme while it is off; all their records are test records."""
    if analytics.is_owner():
        return True
    listed = config().get("tester_emails", [])
    if isinstance(listed, str):
        listed = [listed]
    email = _verified_email()
    return bool(email) and email in {str(x).strip().lower() for x in listed if str(x).strip()}


def visible() -> bool:
    """Show the 💰 Rewards entry points (top bar and Settings)."""
    return enabled() or tester()


def app_url() -> str:
    return str(config().get("app_url") or APP_URL).rstrip("/") + "/"


# --------------------------------------------------------------------------- storage

@st.cache_resource(show_spinner=False)
def _memory_store() -> MemoryStore:
    """Process-wide preview store, used only by owners/testers when the rewards tables are not set up yet."""
    return MemoryStore()


@st.cache_resource(show_spinner=False)
def _health_cache() -> dict:
    return {}


def _supabase() -> SupabaseStore | None:
    storage = accounts._storage()
    return SupabaseStore(*storage) if storage else None


def store_health() -> str:
    """'ok', 'missing_tables', 'error' or 'no_storage' (cached for a minute per server)."""
    real = _supabase()
    if not real:
        return "no_storage"
    cache = _health_cache()
    hit = cache.get(real.url)
    if hit and time.time() - hit[1] < HEALTH_TTL:
        return hit[0]
    result = real.health()
    cache[real.url] = (result, time.time())
    return result


def store(for_tester: bool | None = None) -> RewardsStore | None:
    """The real tables when they are set up; otherwise an in-memory preview for owners/testers only."""
    if store_health() == "ok":
        return _supabase()
    if for_tester if for_tester is not None else tester():
        return _memory_store()
    return None


def preview_store() -> bool:
    return isinstance(store(), MemoryStore)


# --------------------------------------------------------------------------- referral links

def referral_link(code: str) -> str:
    return f"{app_url()}?ref={code}"


def whatsapp_link(code: str, message: str) -> str:
    import urllib.parse
    return "https://wa.me/?text=" + urllib.parse.quote(f"{message} {referral_link(code)}")


def _visit_token() -> str:
    token = st.session_state.get("rw_visit_token")
    if not token:
        token = st.session_state.rw_visit_token = _secrets.token_hex(8)
    return token


def capture_referral() -> None:
    """Called on every run before the page: keep a ?ref=CODE through Google sign-in (session + a 30-day cookie),
    count one visit per browser session, and tidy the address bar."""
    try:
        raw = st.query_params.get("ref")
    except Exception:
        raw = None
    if raw is not None:
        code = str(raw).strip().upper()[:12]
        try:
            del st.query_params["ref"]
        except Exception:
            pass
        if rewards.valid_code(code) and st.session_state.get("rw_ref") != code:
            token = _visit_token()
            st.session_state.rw_ref = code
            st.session_state.rw_ref_visit = f"{token}:{code}"
            cookies.write(REF_COOKIE, f"{code}.{token}", REF_COOKIE_AGE)
            _record_visit(code, st.session_state.rw_ref_visit)
    elif "rw_ref" not in st.session_state:
        saved = cookies.read(REF_COOKIE)
        if saved:
            code, _, token = saved.partition(".")
            st.session_state.rw_ref = code
            st.session_state.rw_ref_visit = f"{token}:{code}" if token else None
        else:
            st.session_state.rw_ref = None


def _record_visit(code: str, visit_key: str) -> None:
    try:
        s = store(for_tester=False)
        if not s:
            return
        owner = s.account_by_code(code)
        if not enabled() and not (owner and owner.get("test")):
            return  # programme off: only invitations from test accounts are counted (owner testing)
        s.record_visit(visit_key, code)
    except Exception:
        pass


def after_sign_in() -> None:
    """Once per session, after the saved profile was read: a brand-new account may be credited to the friend whose
    link brought it here, and new registrations are counted for the owner. Existing accounts are never referrals."""
    who = accounts.identity()
    if not who or st.session_state.get("account_loaded") != who["profile_id"]:
        return
    if st.session_state.get("rw_after_sign_in") == who["profile_id"]:
        return
    st.session_state.rw_after_sign_in = who["profile_id"]
    is_new = bool(st.session_state.get("profile_was_new"))
    code = st.session_state.get("rw_ref")
    if not is_new and not code:
        return
    try:
        s = store()
        if not s:
            return
        referrer = s.account_by_code(code) if code else None
        test = tester()
        programme = enabled() or (test and (referrer is None or referrer.get("test")))
        if not programme:
            return
        if is_new or referrer:
            account = s.ensure_account(who["profile_id"], _verified_email() or None, who.get("name"), is_new, test)
            if code and account:
                s.attribute(who["profile_id"], code, st.session_state.get("rw_ref_visit"))
        st.session_state.pop("rw_ctx", None)
    except Exception:
        pass
    finally:
        if code:  # tried once: the invitation is used up in this browser either way
            st.session_state.rw_ref = None
            cookies.write(REF_COOKIE, "", 0)


# --------------------------------------------------------------------------- per-session context

def context(refresh: bool = False) -> dict | None:
    """Cached rewards state of the signed-in person (None when the programme does not apply)."""
    who = accounts.identity()
    if not who or not visible():
        return None
    now = rewards.lagos_now()
    today, month = rewards.day_key(now), rewards.month_key(now)
    ctx = st.session_state.get("rw_ctx")
    if (not refresh and ctx and ctx["profile_id"] == who["profile_id"] and ctx["day"] == today
            and time.time() - ctx["at"] < 600):
        return ctx
    s = store()
    if not s:
        return None
    try:
        account = s.account(who["profile_id"])
        ctx = {"profile_id": who["profile_id"], "day": today, "month": month, "at": time.time(), "account": account,
               "enrolment": None, "referral": None, "today": [], "history": None, "totals": None, "settings": s.settings()}
        if account:
            ctx["enrolment"] = s.enrolment(who["profile_id"], month)
            ctx["referral"] = s.referral_of(who["profile_id"])
            if account.get("membership") == "member" or (ctx["referral"] or {}).get("status") == "pending":
                events = s.events(who["profile_id"])
                ctx["today"] = [e for e in events if str(e.get("day"))[:10] == today]
                ctx["history"] = events
                ctx["totals"] = rewards.activity_totals(events)
    except Exception:
        return None
    st.session_state.rw_ctx = ctx
    return ctx


def _tracking(ctx: dict | None) -> bool:
    if not ctx or not ctx.get("account"):
        return False
    account = ctx["account"]
    if account.get("test") is False and not enabled():
        return False
    member = account.get("membership") == "member"
    pending = (ctx.get("referral") or {}).get("status") == "pending"
    return member or pending


def tracking() -> bool:
    """True when this person's activity is recorded (cheap: uses the cached context)."""
    try:
        return _tracking(context())
    except Exception:
        return False


def _ensure_enrolment(s: RewardsStore, ctx: dict) -> None:
    """Members are enrolled for each new month on their first activity (or join the waiting list)."""
    account = ctx["account"]
    if account.get("membership") != "member" or ctx.get("enrolment"):
        return
    try:
        ctx["enrolment"] = s.enrol(account["profile_id"], ctx["month"])
    except StoreError:
        ctx["enrolment"] = None   # paused or not possible: activity is still recorded without a reward


def _record(kind: str, subject: str, detail: dict | None = None) -> dict | None:
    ctx = context()
    if not _tracking(ctx):
        return None
    s = store()
    if not s:
        return None
    _ensure_enrolment(s, ctx)
    enrolled = (ctx.get("enrolment") or {}).get("status") == "enrolled"
    row = s.add_event(ctx["profile_id"], kind, subject, ctx["day"], reward=enrolled,
                      test=bool(ctx["account"].get("test")), detail=detail)
    if row:
        ctx["today"].append(row)
        if ctx.get("history") is not None:
            ctx["history"].append(row)
            ctx["totals"] = rewards.activity_totals(ctx["history"])
        if kind != "active_day" and not any(e.get("kind") == "active_day" for e in ctx["today"]) \
                and rewards.active_day_due(ctx["today"]):
            _record("active_day", ctx["day"])
        _check_referral(s, ctx)
        st.session_state.rw_last_award = row
    return row


def _check_referral(s: RewardsStore, ctx: dict) -> None:
    referral = ctx.get("referral")
    if not referral or referral.get("status") != "pending" or not ctx.get("totals"):
        return
    if not rewards.referral_qualifies(ctx["totals"]):
        return
    from datetime import datetime, timezone
    updated = s.update_referral(ctx["profile_id"], {"status": "qualified",
                                                     "qualified_at": datetime.now(timezone.utc).isoformat()})
    ctx["referral"] = updated or dict(referral, status="qualified")
    referrer = s.account(referral["referrer_id"])
    if not referrer:
        return
    if referrer.get("membership") == "member" and not s.enrolment(referrer["profile_id"], ctx["month"]):
        try:
            s.enrol(referrer["profile_id"], ctx["month"])
        except StoreError:
            pass
    s.add_event(referrer["profile_id"], "referral", ctx["profile_id"], ctx["day"], reward=True,
                test=bool(referrer.get("test")), detail={"referred": ctx["profile_id"][:12]})


# --------------------------------------------------------------------------- hooks called by the app

def note_quiz(quiz: dict) -> None:
    """A round just finished (called once per round). Only genuine rounds of five or more questions count."""
    try:
        if not rewards.qualifying_quiz(quiz) or not tracking():
            return
        times = [float(h.get("elapsed") or 0) for h in quiz.get("history", [])]
        detail = {"questions": len(quiz.get("questions", [])), "mode": quiz.get("mode"),
                  "avg_seconds": round(sum(times) / len(times), 2) if times else None}
        uid = str(quiz.get("uid") or hashlib.sha256(repr(quiz.get("questions")).encode()).hexdigest()[:16])
        _record("quiz", uid, detail)
    except Exception:
        pass


def note_country(country_id: str) -> None:
    """A meaningful interaction with a country page (opening its neighbours, landmarks, size comparison or details,
    or starting its quiz). Simply viewing a country, or time spent, never counts."""
    try:
        if country_id and tracking():
            _record("country", str(country_id))
    except Exception:
        pass


def explored(country_id: str, action=None, *args) -> None:
    """Button callback wrapper: note the interaction, then run the button's usual action unchanged."""
    note_country(country_id)
    if action:
        action(*args)


def expander_changed(key: str, country_id: str) -> None:
    if st.session_state.get(key):
        note_country(country_id)


def expander_hook(key: str, country_id: str) -> dict:
    """Keyword arguments for st.expander: a change callback only while this person's activity is recorded, so the
    expander behaves exactly as before for everybody else."""
    if not tracking():
        return {}
    return {"on_change": expander_changed, "args": (key, country_id)}


# --------------------------------------------------------------------------- owner helpers

def registered_users() -> int | None:
    """Number of saved player profiles (owner dashboard only; one small count request)."""
    import urllib.request
    storage = accounts._storage()
    if not storage:
        return None
    url, key = storage
    headers = {"apikey": key, "Prefer": "count=exact", "Range": "0-0"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    try:
        request = urllib.request.Request(f"{url}/rest/v1/{accounts.TABLE}?select=user_id", headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            total = (response.headers.get("Content-Range") or "").rpartition("/")[2]
        return int(total) if total.isdigit() else None
    except Exception:
        return None
