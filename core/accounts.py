"""Optional sign-in (Streamlit OIDC via st.login) and server-side profile storage (Supabase REST).

Credentials live only in Streamlit secrets — see .streamlit/secrets.toml.example and LOGIN_SETUP.md.
The browser never talks to Supabase: the server derives the row id from the verified
OIDC issuer + subject, so users cannot read or write each other's rows.

Safety rules:
  * guests can always play; sign-in problems never block the app;
  * nothing is written until the saved profile has been read successfully, so a
    connection failure can never overwrite saved progress with an empty profile;
  * failed reads are retried with a delay rather than on every click.
"""
from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import threading
import time
from datetime import date, timedelta
import urllib.parse
import urllib.request

import streamlit as st

from . import cookies
from .badges import STAT_COUNTERS, sanitize_stats
from .records import MAX_SCORE_RECORDS, sanitize_records
from .daily import MAX_DAILY_HISTORY, MAX_MISTAKES, sanitize_daily, sanitize_mistakes
from .data import AREAS, COLLECTIONS, get_country
from .i18n import LANGUAGES

PROFILE_KEYS = ("profile_name", "profile_photo", "app_language", "scope_mode", "scope_continent",
                "scope_country", "scope_collection", "points", "rounds_finished", "recent", "recent_facts",
                "sound_enabled", "sound_volume", "stats", "records", "size_reference", "daily", "mistakes",
                "transfers")
SCOPE_MODES = ("All countries", "One continent", "One country")
PHOTO_PREFIX = "data:image/jpeg;base64,"
MAX_PHOTO_CHARS = 500_000
TABLE = "world_explorer_profiles"
RETRY_SECONDS = 60
MAX_TRANSFERS = 20
CALLBACK_PATH = "/oauth2callback"


def sanitize_profile(values) -> dict:
    """Keep only well-formed profile fields. Unknown keys are ignored and missing keys keep
    their defaults, so profiles saved by older versions load unchanged."""
    if not isinstance(values, dict):
        return {}
    out = {}
    for key in PROFILE_KEYS:
        if key not in values:
            continue
        v = values[key]
        if key in ("points", "rounds_finished"):
            ok = isinstance(v, int) and not isinstance(v, bool) and v >= 0
        elif key in ("recent", "recent_facts"):
            ok = isinstance(v, list)
            v = [x for x in v if isinstance(x, str)][-500:] if ok else v
        elif key == "profile_name":
            ok = isinstance(v, str)
            v = v[:40] if ok else v
        elif key == "profile_photo":
            ok = isinstance(v, str) and (v == "" or (v.startswith(PHOTO_PREFIX) and len(v) < MAX_PHOTO_CHARS))
        elif key == "app_language":
            ok = v in LANGUAGES
        elif key == "scope_mode":
            ok = v in SCOPE_MODES
        elif key == "scope_continent":
            ok = v in AREAS
        elif key == "scope_collection":
            ok = v in COLLECTIONS
        elif key == "sound_enabled":
            ok = isinstance(v, bool)
        elif key == "sound_volume":
            ok = isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100
        elif key == "stats":
            v = sanitize_stats(v)
            ok = v is not None
        elif key == "daily":
            v = sanitize_daily(v)
            ok = v is not None
        elif key == "mistakes":
            v = sanitize_mistakes(v)
            ok = v is not None
        elif key == "transfers":  # ids of guest-progress transfers already added (never the token itself)
            ok = isinstance(v, list)
            v = [x for x in v if isinstance(x, str) and len(x) == 16 and all(c in "0123456789abcdef" for c in x)][-MAX_TRANSFERS:] if ok else v
        elif key == "size_reference":
            ok = isinstance(v, str) and (v == "" or get_country(v) is not None)
        elif key == "records":
            v = sanitize_records(v)
            ok = v is not None
        else:  # scope_country
            ok = v == "all" or get_country(v) is not None
        if ok:
            out[key] = v
    return out


# --------------------------------------------------------------------------- configuration

def _secret_section(name) -> dict:
    try:
        return dict(st.secrets.get(name, {}))
    except Exception:  # no secrets file, or Streamlit raises its own not-found error
        return {}


def _authlib_ready() -> bool:
    try:
        import authlib  # noqa: F401  (installed by streamlit[auth])
        return True
    except ImportError:
        return False


def _current_origin() -> str | None:
    try:
        url = st.context.url
    except Exception:
        return None
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None


def auth_diagnosis(provider: str | None = None) -> dict:
    """Explain whether sign-in can work, without revealing any secret.

    Returns {"ok": bool, "problem": code or None, "expected": callback for this address,
    "configured": configured callback}. The callback URL is not a secret: it is the app's
    own address and is shown to the owner so it can be registered with Google.
    """
    auth = _secret_section("auth")
    origin = _current_origin()
    expected = origin + CALLBACK_PATH if origin else None
    configured = str(auth.get("redirect_uri", "") or "")
    result = {"ok": False, "problem": None, "expected": expected, "configured": configured or None}
    providers = [provider] if provider else ["google", "account"]
    ready_providers = [p for p in providers if all((auth.get(p) or {}).get(k)
                                                   for k in ("client_id", "client_secret", "server_metadata_url"))]
    if not auth or not configured or not auth.get("cookie_secret") or not ready_providers:
        result["problem"] = "not_configured"
    elif not _authlib_ready():
        result["problem"] = "authlib_missing"
    elif not configured.endswith(CALLBACK_PATH):
        result["problem"] = "callback_path"
    else:
        parsed = urllib.parse.urlparse(configured)
        local = parsed.hostname in ("localhost", "127.0.0.1")
        configured_origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme != "https" and not local:
            result["problem"] = "not_https"
        else:
            result["ok"] = True
            if origin and configured_origin != origin and "{port}" not in configured:
                # Not blocking (the reported address could differ behind a proxy), but almost
                # always the cause of Google's "redirect_uri_mismatch" or a failed callback.
                result["problem"] = "origin_mismatch"
    return result


def provider_ready(name) -> bool:
    return auth_diagnosis(name)["ok"]


def _storage():
    config = _secret_section("profiles")
    url, key = str(config.get("url", "")), str(config.get("server_key", ""))
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not host.endswith(".supabase.co") or not key:
        return None
    return url.rstrip("/"), key


def storage_ready() -> bool:
    return _storage() is not None


# --------------------------------------------------------------------------- identity

def identity() -> dict | None:
    try:
        if not st.user.is_logged_in:
            return None
        claims = dict(st.user)
    except Exception:  # auth not configured, or an older Streamlit without st.user
        return None
    issuer, subject = claims.get("iss"), claims.get("sub")
    if not issuer or not subject:
        return None
    claims["profile_id"] = hashlib.sha256(f"{issuer}\0{subject}".encode()).hexdigest()
    return claims


def _request(profile_id: str, payload: dict | None = None):
    url, key = _storage()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_secret_"):  # legacy JWT service keys also need Authorization
        headers["Authorization"] = "Bearer " + key
    if payload is None:
        route, data, method = f"/rest/v1/{TABLE}?user_id=eq.{profile_id}&select=profile", None, "GET"
    else:
        route, method = f"/rest/v1/{TABLE}?on_conflict=user_id", "POST"
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        data = json.dumps({"user_id": profile_id, "profile": payload}).encode()
    request = urllib.request.Request(url + route, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(2_000_000)
    return json.loads(raw) if raw else None


def _payload(ss=None) -> dict:
    """What is saved: the profile fields plus any unfinished quiz round (core/active_round.py), in one JSON value."""
    from . import active_round
    ss = st.session_state if ss is None else ss
    data = {k: ss.get(k) for k in PROFILE_KEYS}
    data["active_round"] = active_round.pack(ss)
    return data


def _fingerprint() -> str:
    return json.dumps(_payload(), sort_keys=True, default=str)


def connection_state() -> str:
    """'guest', 'no_storage', 'loading_failed', 'saved' or 'save_failed'."""
    who = identity()
    if not who:
        return "guest"
    if not storage_ready():
        return "no_storage"
    if st.session_state.get("account_loaded") != who["profile_id"]:
        return "loading_failed"
    return "save_failed" if st.session_state.get("profile_save_error") else "saved"


def retry_now() -> None:
    st.session_state.profile_retry_at = 0.0


def restore_profile(now: float | None = None) -> None:
    """Load the signed-in user's saved profile once per session (retrying after failures)."""
    who = identity()
    if not who or st.session_state.get("account_loaded") == who["profile_id"]:
        return
    if not st.session_state.get("profile_name"):
        st.session_state.profile_name = str(who.get("name", ""))[:40]
    if not storage_ready():
        return
    now = time.time() if now is None else now
    if now < st.session_state.get("profile_retry_at", 0.0):
        return
    try:
        rows = _request(who["profile_id"])
        if rows is not None and not isinstance(rows, list):
            raise ValueError("unexpected response")
    except Exception:
        # Never write until a read has succeeded: an outage must not overwrite saved progress.
        st.session_state.profile_save_error = True
        st.session_state.profile_retry_at = now + RETRY_SECONDS
        return
    stored = rows[0].get("profile") if rows and isinstance(rows[0], dict) else {}
    saved = sanitize_profile(stored)
    # an unfinished round saved earlier; ui/state.restore_active_round() checks it and offers to continue it
    st.session_state.saved_active_round = stored.get("active_round") if isinstance(stored, dict) else None
    claim = _find_handoff()
    pending = None
    if claim:
        tid, guest = claim
        if tid in saved.get("transfers", []):
            _finish_handoff(tid)  # already added by an earlier or concurrent session: never add it twice
        else:
            # Guest progress from before Google's sign-in page: added to the saved profile, never replacing it.
            # It stays recoverable on the server until a save containing it succeeds (see save_profile).
            base = _progress_of(saved, defaults=st.session_state)
            merged = merge_progress(base, guest)
            saved.update(merged)
            saved["transfers"] = (saved.get("transfers", []) + [tid])[-MAX_TRANSFERS:]
            pending = {"id": tid, "guest": guest, "base": base, "merged": _progress_of(merged, defaults=base),
                       "existing": bool(rows),
                       "points": merged["points"] - base["points"], "rounds": merged["rounds_finished"] - base["rounds_finished"]}
    st.session_state.update(saved)
    st.session_state.profile_was_new = not rows  # no saved profile yet: a new registration (rewards referrals)
    st.session_state.account_loaded = who["profile_id"]
    st.session_state.profile_save_error = False
    st.session_state.profile_saved_fingerprint = _fingerprint() if rows else ""
    if pending:
        st.session_state.pending_transfer = pending
        st.session_state.profile_saved_fingerprint = ""
        save_profile()  # write at once, so the confirmation is only shown once the transfer is really saved


def save_profile() -> None:
    who = identity()
    if not who or not storage_ready() or st.session_state.get("account_loaded") != who["profile_id"]:
        return
    pending = st.session_state.get("pending_transfer")
    fingerprint = _fingerprint()
    if not pending and fingerprint == st.session_state.get("profile_saved_fingerprint"):
        return
    try:
        if pending:
            with _handoffs()["lock"]:  # one transfer save at a time on this server (concurrent tabs)
                _save_transfer(who["profile_id"], pending)
            fingerprint = _fingerprint()
        else:
            _request(who["profile_id"], _payload())
        st.session_state.profile_saved_fingerprint = fingerprint
        st.session_state.profile_save_error = False
    except Exception:
        st.session_state.profile_save_error = True


def _save_transfer(profile_id: str, pending: dict) -> None:
    """Save a session that added guest progress, idempotently. The saved profile is read again first:
    * the transfer is already in it (another tab or an earlier attempt saved it) → take the saved progress,
      which contains the guest progress exactly once, plus what this session earned since its merge;
    * the saved progress changed since this session loaded it → add the guest progress to the fresh copy, plus
      what this session earned since its merge;
    * otherwise write this session's progress (saved base + guest progress + anything played since).
    Only after the write succeeds is the server copy of the guest progress dropped."""
    rows = _request(profile_id)
    if rows is not None and not isinstance(rows, list):
        raise ValueError("unexpected response")
    fresh = sanitize_profile(rows[0].get("profile") if rows and isinstance(rows[0], dict) else {})
    ss = st.session_state
    fresh_progress = _progress_of(fresh, defaults=pending["base"])
    if pending["id"] in fresh.get("transfers", []):
        earned = _earned_since(pending["merged"])
        ss.update(merge_progress(fresh_progress, earned))
        ss.transfers = fresh.get("transfers", [])
        _rebase(pending, fresh_progress, fresh_progress)
    elif _canonical(fresh_progress) != _canonical(pending["base"]):
        earned = _earned_since(pending["merged"])
        rebuilt = merge_progress(fresh_progress, pending["guest"])
        ss.update(merge_progress(rebuilt, earned))
        ss.transfers = (fresh.get("transfers", []) + [pending["id"]])[-MAX_TRANSFERS:]
        _rebase(pending, fresh_progress, rebuilt)
    _request(profile_id, _payload(ss))
    ss.pop("pending_transfer", None)
    _finish_handoff(pending["id"])
    ss.handoff_notice = {"points": pending["points"], "rounds": pending["rounds"], "existing": pending["existing"]}


def _rebase(pending: dict, fresh_progress: dict, merged: dict) -> None:
    """After rebuilding on a fresh saved copy: the next attempt compares with that copy, and this session's own
    play keeps being measured from `merged` (the fresh copy with the guest progress, without the session's play,
    which is not saved yet). A failed write followed by a retry therefore neither loses nor repeats anything."""
    pending["base"] = fresh_progress
    pending["merged"] = _progress_of(merged, defaults=fresh_progress)


def _earned_since(merged: dict) -> dict:
    """Progress this session earned after its guest transfer was merged (answers, rounds, daily days, records),
    in the shape merge_progress adds: counters as differences, the rest as sets to combine."""
    now = _progress_of(st.session_state, defaults=merged)
    m_stats = sanitize_stats(merged.get("stats") or {})
    n_stats = sanitize_stats(now.get("stats") or {})
    stats = {k: max(0, n_stats[k] - m_stats[k]) for k in STAT_COUNTERS}
    stats["correct_by_continent"] = {c: max(0, v - m_stats["correct_by_continent"].get(c, 0))
                                     for c, v in n_stats["correct_by_continent"].items()}
    m_daily = sanitize_daily(merged.get("daily") or {})
    n_daily = sanitize_daily(now.get("daily") or {})
    new_days = {d: r for d, r in n_daily["results"].items() if d not in m_daily["results"]}
    return {"points": max(0, (now.get("points") or 0) - (merged.get("points") or 0)),
            "rounds_finished": max(0, (now.get("rounds_finished") or 0) - (merged.get("rounds_finished") or 0)),
            "stats": stats, "records": now.get("records") or {},
            "daily": {"results": new_days, "streak": 0, "best": n_daily["best"], "last": ""},
            "mistakes": now.get("mistakes") or [],
            "recent": now.get("recent") or [], "recent_facts": now.get("recent_facts") or []}


# --------------------------------------------------------------------------- guest progress → account

# Progress a guest can carry into an account. Preferences (language, area, sound, name, photo) are not carried:
# an existing saved profile keeps its own.
PROGRESS_KEYS = ("points", "rounds_finished", "stats", "records", "daily", "mistakes", "recent", "recent_facts")
HANDOFF_SECONDS = 30 * 60
MAX_HANDOFFS = 2000


@st.cache_resource(show_spinner=False)
def _handoffs() -> dict:
    """Server memory shared by sessions: token -> {"expires", "progress", "claimed"}. Short-lived, never persisted."""
    return {"lock": threading.RLock(), "items": {}}


def guest_has_progress() -> bool:
    return identity() is None and (st.session_state.get("rounds_finished", 0) > 0 or st.session_state.get("points", 0) > 0)


def _snapshot() -> dict:
    return json.loads(json.dumps({k: st.session_state.get(k) for k in PROGRESS_KEYS}, default=list))


def _transfer_id(token: str) -> str:
    """Stored in the profile to make retries idempotent. A one-way digest: the token itself is never saved."""
    return hashlib.sha256(("transfer\0" + token).encode()).hexdigest()[:16]


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=list)


def _progress_of(profile: dict, defaults) -> dict:
    """The progress part of a sanitized profile, with missing keys taken from `defaults`."""
    out = {}
    for k in PROGRESS_KEYS:
        v = profile.get(k, defaults.get(k) if hasattr(defaults, "get") else None)
        out[k] = json.loads(json.dumps(v, default=list)) if v is not None else v
    return out


def prepare_handoff() -> str:
    """Keep this guest's progress on the server for 30 minutes and remember the token in a cookie, so it can be
    added to the account after Google's sign-in page (which starts a new browser session)."""
    store = _handoffs()
    token = st.session_state.get("handoff_token") or _secrets.token_urlsafe(24)
    now = time.time()
    with store["lock"]:
        items = store["items"]
        for old in [k for k, e in items.items() if e["expires"] < now]:
            items.pop(old, None)
        while len(items) >= MAX_HANDOFFS:
            items.pop(next(iter(items)))
        entry = items.get(token)
        if entry and entry["claimed"]:
            return token  # already being added to an account: the guest tab no longer changes it
        items[token] = {"expires": now + HANDOFF_SECONDS, "progress": _snapshot(), "claimed": False}
    st.session_state.handoff_token = token
    cookies.write("we_handoff", token, HANDOFF_SECONDS)
    return token


def refresh_handoff() -> None:
    """Keep a prepared hand-off up to date with the guest's latest progress (end of every run). A token that is
    gone, expired or already claimed by a signed-in session is never recreated or changed, so progress cannot be
    added twice."""
    token = st.session_state.get("handoff_token")
    if not token or identity() is not None:
        return
    store = _handoffs()
    with store["lock"]:
        entry = store["items"].get(token)
        if entry and not entry["claimed"] and entry["expires"] >= time.time():
            entry["progress"] = _snapshot()
            return
    st.session_state.pop("handoff_token", None)
    st.session_state.pop("signin_ready", None)


def _find_handoff() -> tuple[str, dict] | None:
    """(transfer id, guest progress) for this browser's hand-off token, if the server still has it. The entry is
    kept (marked as claimed and extended) until a save containing it succeeds, so a failed save, a refresh or a
    second tab can recover it; the transfer id in the saved profile prevents adding it twice."""
    token = cookies.read("we_handoff")
    if not token:
        return None
    store = _handoffs()
    now = time.time()
    with store["lock"]:
        entry = store["items"].get(token)
        if not entry or entry["expires"] < now:
            store["items"].pop(token, None)
            entry = None
        else:
            entry.update(claimed=True, expires=now + HANDOFF_SECONDS)
            progress = json.loads(json.dumps(entry["progress"]))
    if entry is None:
        cookies.write("we_handoff", "", 0)
        return None
    cookies.write("we_handoff", token, HANDOFF_SECONDS)  # keep it for recovery while the save is pending
    return _transfer_id(token), progress


def _finish_handoff(transfer_id: str) -> None:
    """The transfer is saved (or was already): drop the server copy and the cookie."""
    store = _handoffs()
    with store["lock"]:
        for token in [k for k in store["items"] if _transfer_id(k) == transfer_id]:
            store["items"].pop(token, None)
    cookies.write("we_handoff", "", 0)


def _streak_from(results: dict) -> tuple[int, int, str]:
    """(current run ending on the latest day, longest run, latest day) from completed daily results."""
    days = sorted(date.fromisoformat(d) for d in results)
    if not days:
        return 0, 0, ""
    longest = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if b - a == timedelta(days=1) else 1
        longest = max(longest, run)
    return run, longest, days[-1].isoformat()


def merge_progress(saved: dict, guest: dict) -> dict:
    """Saved progress plus guest progress. Nothing saved is lost or lowered:
    points, rounds and statistics add up (the guest play was separate); records keep the higher value;
    daily results are combined (a day already saved keeps its saved result) and the day streak is recomputed;
    mistakes and recently asked lists are combined without duplicates."""
    s = {k: saved.get(k) for k in PROGRESS_KEYS}
    g = sanitize_profile({k: guest.get(k) for k in PROGRESS_KEYS})
    out = {}
    out["points"] = (s["points"] or 0) + g.get("points", 0)
    out["rounds_finished"] = (s["rounds_finished"] or 0) + g.get("rounds_finished", 0)
    stats, extra = sanitize_stats(s["stats"] or {}), g.get("stats") or sanitize_stats({})
    for k in STAT_COUNTERS:
        stats[k] += extra[k]
    for c, v in extra["correct_by_continent"].items():
        stats["correct_by_continent"][c] += v
    out["stats"] = stats
    rec, grec = sanitize_records(s["records"] or {}), g.get("records") or sanitize_records({})
    scores = {k: v for k, v in grec["scores"].items() if k not in rec["scores"]}   # guest-only settings first,
    for key, score in rec["scores"].items():                                     # so the cap drops those before
        scores[key] = max(score, grec["scores"].get(key, 0))                    # any saved record
    out["records"] = {"best_streak": max(rec["best_streak"], grec["best_streak"]),
                      "scores": dict(list(scores.items())[-MAX_SCORE_RECORDS:])}
    sd, gd = sanitize_daily(s["daily"] or {}), g.get("daily") or sanitize_daily({})
    results = dict(sorted({**gd["results"], **sd["results"]}.items())[-MAX_DAILY_HISTORY:])
    streak, last = sd["streak"], sd["last"]
    for day in sorted(set(gd["results"]) - set(sd["results"])):   # continue the saved streak with guest-only days
        if last and day <= last:
            continue
        gap = (date.fromisoformat(day) - date.fromisoformat(last)).days if last else None
        streak, last = (streak + 1 if gap == 1 else 1), day
    longest = _streak_from(results)[1]
    out["daily"] = {"results": results, "streak": streak, "last": last,
                    "best": max(sd["best"], gd["best"], longest, streak)}
    mistakes = list(sanitize_mistakes(s["mistakes"] or []))
    for m in g.get("mistakes") or []:
        if all(set(m["facts"]) != set(x["facts"]) for x in mistakes):
            mistakes.append(m)
    out["mistakes"] = mistakes[-MAX_MISTAKES:]
    for k in ("recent", "recent_facts"):
        out[k] = ((s[k] or []) + [x for x in g.get(k, []) if x not in (s[k] or [])])[-500:]
    return out


def is_saved_online() -> bool:
    return connection_state() == "saved"


def login(provider: str) -> bool:
    if not provider_ready(provider):
        return False
    save_profile()
    try:
        st.login(provider)
        return True
    except Exception:
        return False


def logout() -> None:
    save_profile()
    try:
        st.logout()
    except Exception:
        pass
