"""Optional sign-in (Streamlit OIDC) and server-side profile storage (Supabase REST).

Credentials live only in .streamlit/secrets.toml — see secrets.toml.example.
The browser never talks to Supabase: the server derives the row id from the
verified OIDC issuer + subject, so users cannot read or write each other's rows.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request

import streamlit as st

from .data import AREAS, get_country
from .i18n import LANGUAGES

PROFILE_KEYS = ("profile_name", "profile_photo", "app_language", "scope_mode", "scope_continent",
                "scope_country", "points", "rounds_finished", "recent", "recent_facts")
SCOPE_MODES = ("All countries", "One continent", "One country")
PHOTO_PREFIX = "data:image/jpeg;base64,"
MAX_PHOTO_CHARS = 500_000
TABLE = "world_explorer_profiles"


def sanitize_profile(values) -> dict:
    """Keep only well-formed profile fields. Never trust stored data blindly."""
    if not isinstance(values, dict):
        return {}
    out = {}
    for key in PROFILE_KEYS:
        v = values.get(key)
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


def provider_ready(name) -> bool:
    auth = _secret_section("auth")
    provider = auth.get(name) or {}
    return bool(auth.get("redirect_uri") and auth.get("cookie_secret")
                and all(provider.get(k) for k in ("client_id", "client_secret", "server_metadata_url")))


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
    except (AttributeError, KeyError):  # older Streamlit without st.user / auth not configured
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


def restore_profile() -> None:
    """Load the signed-in user's saved profile once per session."""
    who = identity()
    if not who or st.session_state.get("account_loaded") == who["profile_id"]:
        return
    if not st.session_state.get("profile_name"):
        st.session_state.profile_name = str(who.get("name", ""))[:40]
    if not storage_ready():
        return
    try:
        rows = _request(who["profile_id"])
    except Exception:
        # Never write until a read has succeeded: an outage must not overwrite saved progress.
        st.session_state.profile_save_error = True
        return
    st.session_state.update(sanitize_profile(rows[0]["profile"] if rows else {}))
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
    who = identity()
    return bool(who and st.session_state.get("account_loaded") == who["profile_id"]
                and storage_ready() and not st.session_state.get("profile_save_error"))


def login(provider: str) -> bool:
    save_profile()
    try:
        st.login(provider)
        return True
    except Exception:
        return False


def logout() -> None:
    save_profile()
    st.logout()
