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
import time
import urllib.parse
import urllib.request

import streamlit as st

from .badges import sanitize_stats
from .records import sanitize_records
from .data import AREAS, COLLECTIONS, get_country
from .i18n import LANGUAGES

PROFILE_KEYS = ("profile_name", "profile_photo", "app_language", "scope_mode", "scope_continent",
                "scope_country", "scope_collection", "points", "rounds_finished", "recent", "recent_facts",
                "sound_enabled", "sound_volume", "stats", "records")
SCOPE_MODES = ("All countries", "One continent", "One country")
PHOTO_PREFIX = "data:image/jpeg;base64,"
MAX_PHOTO_CHARS = 500_000
TABLE = "world_explorer_profiles"
RETRY_SECONDS = 60
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


def _fingerprint() -> str:
    return json.dumps({k: st.session_state.get(k) for k in PROFILE_KEYS}, sort_keys=True)


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
    st.session_state.update(sanitize_profile(stored))
    st.session_state.account_loaded = who["profile_id"]
    st.session_state.profile_save_error = False
    st.session_state.profile_saved_fingerprint = _fingerprint() if rows else ""


def save_profile() -> None:
    who = identity()
    if not who or not storage_ready() or st.session_state.get("account_loaded") != who["profile_id"]:
        return
    fingerprint = _fingerprint()
    if fingerprint == st.session_state.get("profile_saved_fingerprint"):
        return
    try:
        _request(who["profile_id"], {k: st.session_state.get(k) for k in PROFILE_KEYS})
        st.session_state.profile_saved_fingerprint = fingerprint
        st.session_state.profile_save_error = False
    except Exception:
        st.session_state.profile_save_error = True


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
