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

from core import accounts, analytics, cookies, legal, pilot_rewards, rewards
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


PUBLIC_TTL = 30   # seconds a server keeps the owner switch before reading it again


def deployment_enabled() -> bool:
    """The deployment-level safety switch [rewards] enabled in Streamlit secrets. Default off. While it is off, the
    public programme stays closed whatever the Owner dashboard switch says."""
    return bool(config().get("enabled"))


def owner_switch(refresh: bool = False) -> dict:
    """The Owner dashboard switch stored in Supabase (reward_program_settings.public_enabled), cached briefly.
    {'installed': False} until supabase/public_programme_migration.sql has run; it then counts as OFF."""
    cache = _health_cache()
    hit = cache.get("public_switch")
    if hit and not refresh and time.time() - hit[1] < PUBLIC_TTL:
        return hit[0]
    try:
        s = _supabase() if store_health() == "ok" else _memory_store()
        status = s.public_status()
    except Exception:
        status = {"installed": False, "enabled": False, "error": True}
    cache["public_switch"] = (status, time.time())
    return status


def legal_live() -> bool:
    """The reviewed legal documents and the operator identification are published ([legal] published and
    operator_verified, both default off; see core/legal.py). Nothing public or payable opens before that."""
    return legal.live()


def enabled() -> bool:
    """Public participation is open: the deployment safety switch AND the owner's dashboard switch are on, AND the
    reviewed legal documents participants agree to are published (core/legal.py).
    (The separate pause setting is shown on top of this; it stops new rewards and enrolments but keeps the page.)"""
    return deployment_enabled() and bool(owner_switch().get("enabled")) and legal_live()


def public_state() -> dict:
    """What the Owner dashboard shows: 'enabled', 'paused' or 'disabled', with every switch and the reason."""
    deployment = deployment_enabled()
    switch = owner_switch()
    paused = False
    try:
        s = store(for_tester=True)
        paused = bool(s.settings().paused) if s else False
    except Exception:
        pass
    owner = bool(switch.get("enabled"))
    if not switch.get("installed"):
        state, reason = "disabled", "The owner switch is not installed yet (run supabase/public_programme_migration.sql)."
    elif not deployment:
        state, reason = "disabled", ("Blocked by the deployment safety switch [rewards] enabled = false in Streamlit "
                                     "secrets" + (" — the owner switch is ON but has no effect" if owner else "") + ".")
    elif not owner:
        state, reason = "disabled", "The owner switch is OFF."
    elif not legal_live():
        state, reason = "disabled", ("Blocked until the legal documents are published: set [legal] operator_verified and "
                                     "[legal] published in Streamlit secrets after legal review (legal/OPERATOR_VERIFICATION.md).")
    elif paused:
        state, reason = "paused", "Both switches are ON, but the programme is paused (no new rewards or enrolments)."
    else:
        state, reason = "enabled", "Both switches are ON and the programme is not paused."
    return {"state": state, "reason": reason, "deployment": deployment, "owner": owner, "paused": paused, "legal": legal_live(),
            "installed": bool(switch.get("installed")), "changed_at": switch.get("changed_at"),
            "changed_by": switch.get("changed_by")}


def payouts_active() -> bool:
    """Real money can be approved and paid (owner switch, after legal review). Default off. Also needs the legal
    documents to be published (core/legal.py)."""
    return bool(config().get("payouts_active")) and legal_live()


def withdrawals_active() -> bool:
    """Real withdrawal requests may be submitted (owner switch, after legal review). Default off. The database has its
    own switch as well (reward_cashout_settings.live_requests): real requests need both. Test accounts can always
    simulate the process; their records are test records and are never payable. Also needs the legal documents to
    be published (core/legal.py)."""
    return bool(config().get("withdrawals_active")) and legal_live()


def fingerprint_key() -> str:
    """Server secret for keyed bank-account fingerprints ([rewards] bank_fingerprint_key, 32+ characters)."""
    return str(config().get("bank_fingerprint_key") or "")


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


def pilot_switch(refresh: bool = False) -> dict:
    """The owner's Friends & Family 10 switches in Supabase (reward_program_settings.pilot_enabled and
    invitation_only), cached briefly. Not installed (supabase/pilot_invitations_migration.sql not run): pilot OFF."""
    cache = _health_cache()
    hit = cache.get("pilot_switch")
    if hit and not refresh and time.time() - hit[1] < PUBLIC_TTL:
        return hit[0]
    try:
        s = _supabase() if store_health() == "ok" else _memory_store()
        status = s.pilot_status()
    except Exception:
        status = {"installed": False, "enabled": False, "invitation_only": True, "error": True}
    cache["pilot_switch"] = (status, time.time())
    return status


def pilot_open() -> bool:
    """The Friends & Family 10 accepts invited people: the owner's pilot switch is ON and the documents they agree
    to (Privacy Policy, Terms of Use, pilot terms) are published (core/legal.py). Independent of the public switch."""
    return bool(pilot_switch().get("enabled")) and legal.pilot_ready()


def invited(refresh: bool = False) -> bool:
    """Is the signed-in person's Google-verified email on the owner's invitation list (not revoked)? Cached for a
    minute per session. No verified email: not invited."""
    email = _verified_email()
    if not email:
        return False
    hit = st.session_state.get("rw_invited")
    if hit and not refresh and hit[0] == email and time.time() - hit[2] < 60:
        return hit[1]
    try:
        s = store(for_tester=False) or (_memory_store() if tester() else None)
        value = bool(s and s.pilot_invited(email))
    except Exception:
        value = False
    st.session_state.rw_invited = (email, value, time.time())
    return value


def pilot_terms_current() -> bool:
    """The participation terms recorded in the database are exactly the published pilot terms (same version label and
    content checksum). After any edit to the pilot terms, applications pause until the owner records the new
    approved version; the database refuses mismatches as well ('terms_outdated')."""
    return pilot_switch().get("terms_version") == legal.pilot_terms_id()


def entry_label(menu: bool = False) -> str:
    """The label of the participant page in menus: the Friends & Family 10 while public rewards are not ON."""
    if not enabled():
        return "🤝 " + t_label("Friends & Family 10")
    return "💰 " + t_label("My Rewards" if menu else "Rewards")


def t_label(text: str) -> str:
    from .state import t   # local import: state imports this module indirectly
    return t(text)


def may_apply() -> bool:
    """May this (real, non-test) person apply now? Mirrors the database rule: the pilot or the public programme is
    open, and an invitation is held — always for the pilot, and for the public programme unless the owner has
    separately switched invitation-only off. The database checks it again."""
    public, pilot = enabled(), pilot_open()
    if not (public or pilot):
        return False
    return invited() or (public and pilot_switch().get("invitation_only") is False)


def visible() -> bool:
    """Show the 💰 Rewards entry points (top bar and Settings): the public programme, owners/testers, or an invited
    person while the Friends & Family 10 is open. An ordinary visitor sees nothing while only the pilot is open."""
    return enabled() or tester() or (pilot_open() and invited())


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


def cashout_store(for_tester: bool | None = None) -> RewardsStore | None:
    """The rewards store when the withdrawals migration is installed (None otherwise). In the in-memory preview the
    owners listed in [analytics] owner_emails may decide, mirroring reward_cashout_settings.owner_emails."""
    s = store(for_tester)
    if s is None:
        return None
    if isinstance(s, MemoryStore):
        owners = analytics.config().get("owner_emails", [])
        s.tables["reward_cashout_settings"][0]["owner_emails"] = [owners] if isinstance(owners, str) else list(owners)
        return s
    cache = _health_cache()
    key = getattr(s, "url", "store") + "#cashout"
    hit = cache.get(key)
    if not hit or time.time() - hit[1] >= HEALTH_TTL:
        hit = cache[key] = (s.cashout_health(), time.time())
    return s if hit[0] == "ok" else None


def cashout_health() -> str:
    """'ok', 'missing_tables' (run supabase/withdrawals_migration.sql), 'error' or 'no_storage'."""
    s = store(for_tester=True)
    if s is None:
        return "no_storage"
    return "ok" if cashout_store(for_tester=True) else s.cashout_health()


def preview_store() -> bool:
    return isinstance(store(), MemoryStore)


# --------------------------------------------------------------------------- Founding 50 (approval by the Owner)

def founding_store(for_tester: bool | None = None) -> RewardsStore | None:
    """The rewards store when supabase/founding50_migration.sql is installed (the in-memory preview always has it);
    None otherwise. Without it real players cannot apply or join (fail safe); owners see what to run."""
    s = store(for_tester)
    if s is None or isinstance(s, MemoryStore):
        return s
    cache = _health_cache()
    key = getattr(s, "url", "store") + "#founding"
    hit = cache.get(key)
    if not hit or time.time() - hit[1] >= HEALTH_TTL:
        hit = cache[key] = (s.founding_health(), time.time())
    return s if hit[0] == "ok" else None


def founding_health() -> str:
    """'ok', 'missing_tables' (run supabase/founding50_migration.sql), 'error' or 'no_storage'."""
    s = store(for_tester=True)
    if s is None:
        return "no_storage"
    return "ok" if founding_store(for_tester=True) else s.founding_health()


def founding_application(profile_id: str) -> dict | None:
    s = founding_store()
    return s.founding_application(profile_id) if s else None


def founding_unseen() -> int:
    """New Founding 50 applications the Owner has not opened yet (the in-app notification)."""
    try:
        s = founding_store(for_tester=True)
        return sum(1 for a in s.founding_applications() if not a.get("seen_at")) if s else 0
    except Exception:
        return 0


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
        if not rewards.qualifying_quiz(quiz):
            return
        times = [float(h.get("elapsed") or 0) for h in quiz.get("history", [])]
        detail = {"questions": len(quiz.get("questions", [])), "mode": quiz.get("mode"),
                  "avg_seconds": round(sum(times) / len(times), 2) if times else None}
        uid = str(quiz.get("uid") or hashlib.sha256(repr(quiz.get("questions")).encode()).hexdigest()[:16])
        # Friends & Family 10: the first completed Daily Challenge of a day is its own milestone
        if quiz.get("mode") == "daily":
            ping("challenge", f"daily:{quiz.get('day') or uid}", detail)
        else:
            ping("quiz", uid, detail)
        if tracking():
            _record("quiz", uid, detail)
    except Exception:
        pass


def note_answer(quiz: dict, index: int) -> None:
    """A quiz question was answered (Friends & Family 10 learning time only)."""
    if quiz and quiz.get("mode") != "daily_replay":
        ping("answer", f"{quiz.get('uid') or quiz.get('serial')}:{index}")


def note_view(country_id) -> None:
    """A country was opened in Learn or Explore (Friends & Family 10 learning time only)."""
    ping("view", country_id)


def note_country(country_id: str) -> None:
    """A meaningful interaction with a country page (opening its neighbours, landmarks, size comparison or details,
    or starting its quiz). Simply viewing a country, or time spent, never counts."""
    try:
        if country_id:
            ping("country", str(country_id))
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
    if not tracking() and not ff10_member():
        return {}
    return {"on_change": expander_changed, "args": (key, country_id)}


# --------------------------------------------------------------------------- Friends & Family 10 (provisional rewards)

FF10_TTL = 300
_FF10_POOL = None


def ff10_store(for_tester: bool | None = None) -> RewardsStore | None:
    """The rewards store when supabase/friends_family10_migration.sql is installed (the in-memory preview always has
    it); None otherwise, and then nothing is recorded and no progress is shown."""
    s = store(for_tester)
    if s is None or isinstance(s, MemoryStore):
        return s
    cache = _health_cache()
    key = getattr(s, "url", "store") + "#ff10"
    hit = cache.get(key)
    if not hit or time.time() - hit[1] >= HEALTH_TTL:
        hit = cache[key] = (s.ff10_health(), time.time())
    return s if hit[0] == "ok" else None


def ff10_health() -> str:
    s = store(for_tester=True)
    if s is None:
        return "no_storage"
    return "ok" if ff10_store(for_tester=True) else s.ff10_health()


def ff10_member(refresh: bool = False) -> dict | None:
    """{'profile_id', 'test'} when the signed-in person's learning is recorded for Friends & Family 10: an approved
    participant while the pilot switch is ON (real records), or an owner/tester account (test records, never
    settled). Cached for a few minutes; the database checks the same rules on every record."""
    who = accounts.identity()
    if not who:
        return None
    cached = st.session_state.get("ff10_member")
    if (not refresh and cached and cached["profile_id"] == who["profile_id"]
            and time.time() - cached["at"] < FF10_TTL):
        return cached["value"]
    value = None
    try:
        s = ff10_store()
        account = s.account(who["profile_id"]) if s else None
        if account and account.get("test"):
            value = {"profile_id": who["profile_id"], "test": True} if tester() else None
        elif account and pilot_switch().get("enabled") and s.pilot_invited(account.get("email")):
            app = s.founding_application(who["profile_id"])   # approved AND invited (the database checks both)
            if app and app.get("status") == "approved" and not app.get("test"):
                # cash rewards need the CURRENT approved private terms accepted (the database checks it too)
                value = {"profile_id": who["profile_id"], "test": False,
                         "needs_acceptance": not s.ff10_terms_accepted(who["profile_id"])}
    except Exception:
        value = None
    st.session_state.ff10_member = {"profile_id": who["profile_id"], "at": time.time(), "value": value}
    return value


def _ff10_send(s: RewardsStore, profile_id: str, kind: str, subject: str, detail: dict | None) -> None:
    try:
        s.ff10_record(profile_id, kind, subject, detail)
    except Exception:
        pass                       # refused (e.g. pilot switched off) or unreachable: learning is never interrupted


def ping(kind: str, subject, detail: dict | None = None) -> None:
    """One meaningful learning interaction for Friends & Family 10 (does nothing for everybody else). The database
    time-stamps it and ignores repeats; Supabase calls run in the background so play never waits for them."""
    global _FF10_POOL
    try:
        member = ff10_member()
        if not member or member.get("needs_acceptance") or not str(subject or "").strip():
            return
        s = ff10_store()
        if s is None:
            return
        st.session_state.pop("ff10_progress", None)
        if isinstance(s, MemoryStore):
            _ff10_send(s, member["profile_id"], kind, str(subject), detail)
            return
        if _FF10_POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            _FF10_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ff10")
        _FF10_POOL.submit(_ff10_send, s, member["profile_id"], kind, str(subject), detail)
    except Exception:
        pass


def ff10_checks_on(s: RewardsStore | None = None) -> bool:
    """True when activity checks can be recorded (supabase/friends_family10_active_time_migration.sql installed; the
    in-memory preview always has it). Until then nothing is sent and every day is calculated exactly as before."""
    s = s or ff10_store()
    if s is None:
        return False
    if isinstance(s, MemoryStore):
        return True
    cache = _health_cache()
    key = getattr(s, "url", "store") + "#ff10hb"
    hit = cache.get(key)
    if not hit or time.time() - hit[1] >= HEALTH_TTL:
        hit = cache[key] = (s.ff10_heartbeat_health(), time.time())
    return hit[0] == "ok"


def _ff10_beat_send(s: RewardsStore, profile_id: str, area: str) -> None:
    try:
        s.ff10_heartbeat(profile_id, area)
    except Exception:
        pass                       # refused or unreachable: a lost check is simply not counted (never replayed later)


def beat(area: str | None) -> None:
    """One activity check from an engaged page (ui/ff10_heartbeat.py). The database time-stamps and validates it;
    does nothing for anybody who is not a Friends & Family 10 participant (or owner/tester) and never for School
    Learning."""
    global _FF10_POOL
    try:
        if area not in pilot_rewards.AREAS:
            return
        member = ff10_member()
        if not member or member.get("needs_acceptance"):
            return
        s = ff10_store()
        if s is None or not ff10_checks_on(s):
            return
        if isinstance(s, MemoryStore):
            _ff10_beat_send(s, member["profile_id"], area)
            return
        if _FF10_POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            _FF10_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ff10")
        _FF10_POOL.submit(_ff10_beat_send, s, member["profile_id"], area)
    except Exception:
        pass


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
