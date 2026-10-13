"""Small first-party cookies, read on the server and written by a tiny script in the page.

Streamlit can read the cookies a browser sent when the page connected (st.context.cookies) but cannot set
cookies from Python. Writes are therefore queued here and rendered as one short script on the next run
(ui/components.inject_styles). Values are validated on read, and only these names are ever written:

  we_consent  "granted" / "denied"  — the visitor's usage-statistics choice (remembering a choice is necessary)
  we_aid      random 32-hex id       — written ONLY after the visitor allows usage statistics
  we_test     "1"                    — the owner marks a browser as test traffic (excluded from pilot metrics)
  we_gpc      "1"                    — the browser reports Global Privacy Control (navigator.globalPrivacyControl),
                                       written by GPC_SYNC in ui/components.py so the server can honour it too
  we_ref      "WE7X92.<16 hex>"      — a friend's invitation code from a ?ref= link (rewards programme), kept 30 days so
                                       it survives Google's sign-in page; removed once it has been used
  we_handoff  random token           — set when a guest asks to save progress with Google, so the progress can
                                       be found again after Google's sign-in page; kept (30 minutes from the last
                                       attempt) until the account save that includes it succeeds

Limits (explained to the owner in README.md): cookies are per browser and per device; they are gone after
clearing site data, in private windows when the window closes, and Safari keeps script-written cookies for at
most 7 days after the last visit.
"""
from __future__ import annotations

import json
import re

import streamlit as st

NAMES = {"we_consent": re.compile(r"^(granted|denied)$"), "we_aid": re.compile(r"^[0-9a-f]{32}$"),
         "we_test": re.compile(r"^1$"), "we_handoff": re.compile(r"^[A-Za-z0-9_-]{20,64}$"),
         "we_gpc": re.compile(r"^1$"), "we_ref": re.compile(r"^WE[2-9A-HJ-NP-Z]{4}(\.[0-9a-f]{16})?$")}


def read(name: str) -> str | None:
    """A validated cookie value sent with this session's connection, or None."""
    try:
        value = st.context.cookies.get(name)
    except Exception:  # no browser context (tests, scripts)
        return None
    return value if isinstance(value, str) and NAMES[name].match(value) else None


def write(name: str, value: str, max_age: int) -> None:
    """Queue a cookie write (max_age 0 deletes it). Rendered by script() on the next page update."""
    if name not in NAMES or (max_age and not NAMES[name].match(value)):
        return
    pending = st.session_state.setdefault("cookie_writes", {})
    pending[name] = (value if max_age else "", int(max_age))


def script() -> str:
    """One <script> that applies the queued writes (idempotent; empty when nothing is queued)."""
    pending = st.session_state.pop("cookie_writes", None) or {}  # rendered once, so an old tab never re-asserts it
    if not pending:
        return ""
    items = json.dumps([[k, v, a] for k, (v, a) in sorted(pending.items())])
    return ("<script data-we-cookies=\"1\">(function(){var s=location.protocol==='https:'?';Secure':'';"
            f"{items}.forEach(function(c){{document.cookie=c[0]+'='+encodeURIComponent(c[1])+"
            "';Path=/;Max-Age='+c[2]+';SameSite=Lax'+s;});})();</script>")
