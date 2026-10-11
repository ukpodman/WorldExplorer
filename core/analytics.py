"""Pilot measurement: a few pseudonymous usage events, only with the visitor's permission.

What is recorded (table world_explorer_events, see SETUP_ANALYTICS.md):
  visit           once per browser session
  round_start     a quiz round begins       (mode: regular / daily / daily_replay / practice)
  round_complete  a quiz round is finished  (same modes; "daily" = the first counted attempt of that day)
  link            a guest id and a signed-in id belong to the same person (after "Save progress with Google")
  consent_declined  an anonymous count of "No thanks" answers (no identifier at all)
Each row also has: UTC time, a pseudonymous id, signed-in yes/no, device category (phone/tablet/desktop, from the
browser's user-agent string — the string itself is not stored), app language, the daily challenge date, and a
test flag. Never recorded: names, email addresses, IP addresses, precise location, photos, answers or answer text.

Identifiers: guests get a random id stored in the first-party cookie we_aid, written only after they allow usage
statistics. Signed-in players are identified by a one-way hash of their (already hashed) profile id with the
owner's salt, so the same person counts once across devices. No fingerprinting.

Safety rules:
  * nothing is recorded without consent ("granted"), and nothing at all unless the owner switched analytics on
    in secrets ([analytics] enabled = true) and storage is configured;
  * "No thanks" in one tab reaches the other open tabs of the browser (and the account's other sessions) on their
    next run, and every queued event is checked again just before it is sent, so nothing goes out after it;
  * Global Privacy Control (Sec-GPC: 1) always means no measurement, even after an earlier "Allow";
  * every event has a deterministic key (person + round/session), and the database ignores repeated keys, so
    reruns, double clicks and reconnects cannot inflate counts;
  * events are sent from a background thread with a short timeout; any failure is dropped silently and can
    never block play or touch player progress (which lives in a different table);
  * the server key never reaches the browser.
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import secrets as _secrets
import threading
import time
import urllib.request
from datetime import datetime, timezone

import streamlit as st

from . import accounts, cookies

EVENTS_TABLE = "world_explorer_events"
FEEDBACK_TABLE = "world_explorer_feedback"
EVENTS = ("visit", "round_start", "round_complete", "link", "consent_declined")
MODES = ("regular", "daily", "daily_replay", "practice")
APP_VERSION = "2026.10-pilot"
CONSENT_DAYS, ID_DAYS = 365, 400
SYNC = False            # tests set True to send immediately in the calling thread
TIMEOUT = 4
SEND_DELAY = 3.0        # seconds an event waits before it is sent (see _run_worker)
MAX_QUEUE = 500
PAGE = 1000             # Supabase returns at most 1000 rows per request by default
MAX_ROWS = 200_000


# --------------------------------------------------------------------------- configuration

def config() -> dict:
    try:
        return dict(st.secrets.get("analytics", {}))
    except Exception:
        return {}


def enabled() -> bool:
    """Switched on by the owner in secrets and backed by configured storage."""
    return bool(config().get("enabled")) and accounts.storage_ready()


def is_owner() -> bool:
    """Server-side owner check: a signed-in Google account whose verified email is listed in secrets."""
    who = accounts.identity()
    if not who:
        return False
    owners = config().get("owner_emails", [])
    if isinstance(owners, str):
        owners = [owners]
    allowed = {str(x).strip().lower() for x in owners if str(x).strip()}
    email = str(who.get("email") or "").strip().lower()
    google = str(who.get("iss") or "").rstrip("/") in ("https://accounts.google.com", "accounts.google.com")
    return bool(email) and google and email in allowed and who.get("email_verified") in (True, "true", "True")


def device_category(user_agent: str | None) -> str:
    ua = user_agent or ""
    if re.search(r"iPad|Tablet|PlayBook|Silk|Android(?!.*Mobile)", ua):
        return "tablet"
    if re.search(r"Mobi|iPhone|iPod|Android", ua):
        return "phone"
    return "desktop"


def _header(name: str) -> str:
    try:
        return st.context.headers.get(name) or ""
    except Exception:
        return ""


# --------------------------------------------------------------------------- session and consent

# The latest choice per browser id / signed-in id, shared by every session on this server, so a choice made in
# one tab reaches the other open tabs (and events still waiting to be sent) without a reload.
_CHOICES: dict = {}
_CHOICES_LOCK = threading.Lock()
CHOICE_TTL = 7 * 86400


def _session_ids() -> set:
    ss = st.session_state
    ids = {"g:" + ss["an_known_guest"]} if ss.get("an_known_guest") else set()
    who = accounts.identity()
    if who:
        ids.add("u:" + hashlib.sha256(f"{_salt()}\0{who['profile_id']}".encode()).hexdigest()[:32])
    return ids


def _record_choice(state: str) -> None:
    now = time.time()
    with _CHOICES_LOCK:
        for old in [k for k, (_, t) in _CHOICES.items() if now - t > CHOICE_TTL]:
            _CHOICES.pop(old, None)
        for pid in _session_ids():
            _CHOICES[pid] = (state, now)
    st.session_state.an_choice_at = now


def withdrawn(*pids) -> bool:
    """True if the latest choice recorded for any of these ids is "denied" (checked again just before sending)."""
    with _CHOICES_LOCK:
        return any(_CHOICES.get(pid, ("", 0))[0] == "denied" for pid in pids if pid)


def sync_choice() -> None:
    """Adopt a newer choice made in another tab of this browser (or another session of the same account)."""
    ss = st.session_state
    with _CHOICES_LOCK:
        # "No thanks" reaches every session of the browser and of the signed-in account; "Allow" only reaches tabs of
        # the same browser (its guest id), so allowing on one device never switches statistics on for another.
        choices = [_CHOICES[pid] for pid in _session_ids() if pid in _CHOICES
                   and (pid.startswith("g:") or _CHOICES[pid][0] == "denied")]
        latest = max(choices, key=lambda c: c[1], default=None)
    if not latest or latest[1] <= ss.get("an_choice_at", 0.0):
        return
    state, at = latest
    ss.an_choice_at = at
    if state == "denied" or ss.get("an_gpc"):
        ss.an_consent, ss.an_guest_id = "denied", None
    elif ss.get("an_known_guest"):
        ss.an_consent, ss.an_guest_id = "granted", ss.an_known_guest


def init_session() -> None:
    """Read the visitor's choice and ids once per browser session; on later runs, pick up choices from other tabs."""
    ss = st.session_state
    if "an_session" in ss:
        sync_choice()
        return
    ss.an_session = _secrets.token_hex(8)
    ss.an_sent = set()
    ss.an_choice_at = 0.0  # any choice recorded on the server since this tab opened is newer than its cookies
    # Global Privacy Control: the Sec-GPC request header, or navigator.globalPrivacyControl reported by the page
    # (some browser extensions only set the latter).
    ss.an_gpc = _header("Sec-GPC") == "1" or cookies.read("we_gpc") == "1"
    consent = cookies.read("we_consent")
    ss.an_known_guest = cookies.read("we_aid")
    ss.an_test = cookies.read("we_test") == "1"
    ss.an_device = device_category(_header("User-Agent"))
    if ss.an_gpc:
        # Global Privacy Control wins over any earlier "Allow": nothing is recorded and the id is removed.
        consent = "denied"
        if ss.an_known_guest:
            _record_choice("denied")
            cookies.write("we_aid", "", 0)
    elif consent == "granted":
        ss.an_known_guest = ss.an_known_guest or _secrets.token_hex(16)
        cookies.write("we_aid", ss.an_known_guest, ID_DAYS * 86400)    # refresh: Safari keeps it 7 days per visit
        cookies.write("we_consent", "granted", CONSENT_DAYS * 86400)
    ss.an_consent = consent
    ss.an_guest_id = ss.an_known_guest if consent == "granted" else None
    sync_choice()


def gpc_active() -> bool:
    return bool(st.session_state.get("an_gpc"))


def needs_choice() -> bool:
    return enabled() and st.session_state.get("an_consent") is None and not gpc_active()


def grant() -> None:
    ss = st.session_state
    if gpc_active():
        return  # the browser asks sites not to track; an "Allow" cannot override it
    ss.an_consent = "granted"
    ss.an_known_guest = ss.get("an_known_guest") or _secrets.token_hex(16)
    ss.an_guest_id = ss.an_known_guest
    cookies.write("we_consent", "granted", CONSENT_DAYS * 86400)
    cookies.write("we_aid", ss.an_guest_id, ID_DAYS * 86400)
    _record_choice("granted")
    log_visit()


def deny() -> None:
    ss = st.session_state
    first_answer = ss.get("an_consent") is None
    _record_choice("denied")   # other open tabs and queued events stop at once
    ss.an_consent = "denied"
    ss.an_guest_id = None
    cookies.write("we_consent", "denied", CONSENT_DAYS * 86400)
    cookies.write("we_aid", "", 0)  # remove the id from this browser
    if first_answer and enabled():
        # An anonymous tally of "No thanks" answers: no id, no cookie, used only to show measurement coverage.
        _send(EVENTS_TABLE, {"event_key": "declined:" + ss.get("an_session", _secrets.token_hex(8)),
                             "event": "consent_declined", "anon_id": None, "signed_in": False,
                             "device": ss.get("an_device"), "lang": _lang(), "test": bool(ss.get("an_test")),
                             "app_version": APP_VERSION})


def set_test_browser(on: bool) -> None:
    st.session_state.an_test = bool(on)
    cookies.write("we_test", "1", 3650 * 86400) if on else cookies.write("we_test", "", 0)


# --------------------------------------------------------------------------- identity

def _salt() -> str:
    return str(config().get("salt") or "world-explorer-pilot")


def person_id() -> tuple[str | None, bool]:
    """(pseudonymous id, signed in?) — None when this visitor is not measured."""
    ss = st.session_state
    if ss.get("an_consent") != "granted":
        return None, False
    who = accounts.identity()
    if who:
        digest = hashlib.sha256(f"{_salt()}\0{who['profile_id']}".encode()).hexdigest()[:32]
        return "u:" + digest, True
    guest = ss.get("an_guest_id")
    return ("g:" + guest, False) if guest else (None, False)


def _lang() -> str:
    return str(st.session_state.get("app_language", ""))[:20]


# --------------------------------------------------------------------------- events

def track(event: str, key: str, *, mode: str | None = None, day: str | None = None, linked: str | None = None,
          round_id: str | None = None) -> bool:
    """Record one event at most once per person and key. Never raises."""
    try:
        if event not in EVENTS or not enabled():
            return False
        sync_choice()
        pid, signed_in = person_id()
        if not pid:
            return False
        ss = st.session_state
        event_key = hashlib.sha256(f"{pid}|{event}|{key}".encode()).hexdigest()[:40]
        sent = ss.setdefault("an_sent", set())
        if event_key in sent:
            return False
        sent.add(event_key)
        row = {"event_key": event_key, "event": event, "anon_id": pid, "signed_in": signed_in,
               "mode": mode if mode in MODES else None, "day": day, "linked_id": linked, "round_id": round_id,
               "device": ss.get("an_device"), "lang": _lang(),
               "test": bool(ss.get("an_test")) or is_owner(), "app_version": APP_VERSION}
        _send(EVENTS_TABLE, row)
        return True
    except Exception:
        return False


def log_visit() -> None:
    """Once per browser session; also links a guest id to the signed-in person after sign-in."""
    ss = st.session_state
    track("visit", "visit:" + str(ss.get("an_session")))
    pid, signed_in = person_id()
    guest = ss.get("an_guest_id")
    if signed_in and guest:
        track("link", "link:" + guest, linked="g:" + guest)


def track_round(event: str, quiz: dict) -> None:
    if quiz and quiz.get("uid"):
        key = f"{event}:{quiz['uid']}"
        if event == "round_complete" and quiz.get("mode") == "daily" and quiz.get("day"):
            # At most one first counted completion per person and Daily Challenge day, even if a guest reloads
            # (fresh session progress) or a player uses two devices: the database ignores the repeat.
            key = f"daily_complete:{quiz['day']}"
        track(event, key, mode=quiz.get("mode", "regular"), day=quiz.get("day"), round_id=quiz["uid"])


# --------------------------------------------------------------------------- transport

_queue: queue.Queue = queue.Queue(MAX_QUEUE)
_worker_lock = threading.Lock()
_worker: threading.Thread | None = None


def _headers_for(key: str) -> dict:
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    return headers


def _post(url: str, key: str, table: str, row: dict) -> None:
    """Insert one row; a repeated event_key is ignored by the database (no error, no duplicate)."""
    route = f"/rest/v1/{table}" + ("?on_conflict=event_key" if table == EVENTS_TABLE else "")
    headers = _headers_for(key)
    headers["Prefer"] = ("resolution=ignore-duplicates," if table == EVENTS_TABLE else "") + "return=minimal"
    request = urllib.request.Request(url + route, data=json.dumps(row).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        response.read(1000)


def _deliver(url: str, key: str, table: str, row: dict, attempts: int = 2) -> bool:
    """Send one row unless its person has withdrawn in the meantime (checked before every attempt)."""
    for attempt in range(attempts):
        if table == EVENTS_TABLE and withdrawn(row.get("anon_id"), row.get("linked_id")):
            return False
        try:
            _post(url, key, table, row)
            return True
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(2)
    return False


def _run_worker() -> None:
    while True:
        queued_at, item = _queue.get()
        try:
            # A short hold before sending: a "No thanks" or a Global Privacy Control signal arriving from another
            # tab, or from the reload that follows a GPC signal, still stops this event.
            time.sleep(max(0.0, queued_at + SEND_DELAY - time.monotonic()))
            _deliver(*item)
        finally:
            _queue.task_done()


def _send(table: str, row: dict) -> None:
    storage = accounts._storage()
    if not storage:
        return
    url, key = storage
    if SYNC:
        _deliver(url, key, table, row, attempts=1)
        return
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="we-analytics", daemon=True)
            _worker.start()
    try:
        _queue.put_nowait((time.monotonic(), (url, key, table, row)))
    except queue.Full:
        pass  # measurement is best effort; play is never slowed down


def send_feedback(page: str, device: str, description: str, contact: str = "") -> bool:
    """Store one feedback message. Returns False (and stores nothing) if storage is unavailable."""
    storage = accounts._storage()
    text = (description or "").strip()
    if not storage or not text or not config().get("enabled"):
        return False
    row = {"page": str(page)[:30], "device": str(device)[:20], "description": text[:2000],
           "contact": (contact or "").strip()[:120] or None, "lang": _lang(), "app_version": APP_VERSION}
    try:
        _post(storage[0], storage[1], FEEDBACK_TABLE, row)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- owner dashboard data

def _get(url: str, key: str, route: str) -> list:
    request = urllib.request.Request(url + route, headers=_headers_for(key), method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read(50_000_000) or b"[]")
    if not isinstance(data, list):
        raise ValueError("unexpected response")
    return data


def fetch(table: str, columns: str, order: str) -> list[dict]:
    """All rows of an analytics table, page by page. Owner dashboard only (callers check is_owner())."""
    storage = accounts._storage()
    if not storage:
        raise RuntimeError("storage not configured")
    rows: list[dict] = []
    while len(rows) < MAX_ROWS:
        page = _get(storage[0], storage[1], f"/rest/v1/{table}?select={columns}&order={order}&limit={PAGE}&offset={len(rows)}")
        rows.extend(page)
        if len(page) < PAGE:
            break
    return rows


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
