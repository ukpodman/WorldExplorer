"""School Learning (Learn → 📚 School Learning): Nigerian SSS study notes, reading progress and topic practice.

Reusable for any subject in data/school/subjects.json: the screens below only read the subject, curriculum and lesson
files through core/school.py. Geography uses the screens in this module; subjects with "engine": "interactive"
(Nigerian History; Citizenship and Heritage Studies) use the class → term → topic screens and interactive lessons in
ui/school_interactive.py, with the same progress records, account saving and device cookie.

Screens (st.session_state.school_view): "home" → "topics" (one subject) → "lesson" (one page at a time) → "practice";
"progress" is the student's dashboard. English only (School Learning is written for Nigerian SSS English-medium
classes); the rest of World Explorer keeps its five languages.

School Learning is study only: nothing here calls the rewards hooks, the quiz engine, points, badges, daily
challenge, quiz statistics, referrals or withdrawals. Practice is its own small engine (core.school) and only reuses
the look of the World Geography Quiz answer cards.
"""
from __future__ import annotations

import random
import re
import time
from html import escape

import streamlit as st

from core import accounts, cookies, school, school_store
from core.data import PHOTOS

from .components import cookie_script, html

SS = st.session_state
REVIEW_LABEL = "Educational review pending"
REVIEW_NOTE = ("These notes were written and fact-checked by the World Explorer team against published sources. "
               "They have not yet been reviewed by a qualified teacher. Always follow your teacher and your school's scheme of work.")
NOT_REWARDS = ("School Learning is for study only. It does not earn points, badges, rewards or money, and it is separate from the "
               "World Geography Quiz.")
RETRY_SECONDS = 30.0
DEVICE_COOKIE = "we_school"
DEVICE_DAYS = 180
ICONS = {"globe": "🌍", "book": "📜", "shield": "🏛️"}


# --------------------------------------------------------------------------- text helpers

def _rich(text: str) -> str:
    """Escape, then turn the lesson files' **bold** markup into <b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(str(text)))


def _plain(text: str) -> str:
    return str(text).replace("**", "")


def _chip(text: str, tone: str = "") -> str:
    return f'<span class="sl-chip{" sl-chip-" + tone if tone else ""}">{escape(text)}</span>'


# --------------------------------------------------------------------------- state and saving

def _defaults() -> None:
    SS.setdefault("school_view", "home")
    SS.setdefault("school_subject", "geography")
    SS.setdefault("school_lesson", None)
    SS.setdefault("school_progress", {})
    SS.setdefault("school_practice", None)
    SS.setdefault("school_device_on", False)


def _keep(key: str) -> None:
    """Copy a filter widget's value to a plain key, so the choice survives leaving the screen or the Learn page."""
    SS[key + "_saved"] = SS.get(key)


def _restore_widget(key: str, default, allowed=None) -> None:
    if key not in SS:
        value = SS.get(key + "_saved", default)
        SS[key] = value if allowed is None or value in allowed else default


def _who() -> dict | None:
    return accounts.identity()


def _owner() -> str:
    """Whose progress the session holds: the signed-in account's one-way id, or "guest"."""
    who = _who()
    return who["profile_id"] if who else "guest"


def _loaded(subject_id: str) -> bool:
    """The signed-in student's saved progress for this subject has been loaded (tracked per account AND subject)."""
    who = _who()
    return bool(who) and f'{who["profile_id"]}:{subject_id}' in SS.get("school_loaded_keys", set())


def _ensure_owner() -> None:
    """Progress belongs to one identity. When the identity changes in this browser session (sign-in, sign-out or a
    different account), nothing studied under the previous identity is carried over: an account's progress stays in
    that account, and a guest's progress is only *offered* for import (see _guest_offer_box), never added silently."""
    owner = _owner()
    previous = SS.get("school_owner")
    if previous == owner:
        return
    if previous is not None:
        # An offer belongs only to the guest → account step that created it. Any other identity change (account →
        # guest, account → another account, or a later guest → account step) drops it, so a declined or postponed
        # offer can never be shown to, or imported into, a different account. A device copy is re-read for the new
        # identity by _device_restore and is offered with its "someone else may have used this device" warning.
        SS.pop("school_guest_offer", None)
        SS.pop("school_offer_on_device", None)
        if previous == "guest" and any(SS.get("school_progress", {}).values()):
            SS.school_guest_offer = SS.school_progress
        SS.school_progress = {}
        SS.school_practice = None
        SS.school_view = "home"
        SS.school_device_on = False
        for key in ("school_loaded_keys", "school_store_error", "school_retry_at", "school_device_checked",
                    "school_offer_hidden", "school_import_result", "sl_device"):
            SS.pop(key, None)
    SS.school_owner = owner


def storage_mode() -> str:
    """'guest' (not signed in), 'session' (signed in, saving switched off), 'saved' or 'error'."""
    who = _who()
    if not who:
        return "guest"
    if not school_store.enabled():
        return "session"
    return "error" if SS.get("school_store_error") or not _loaded(SS.get("school_subject", "geography")) else "saved"


# ---- progress kept on this device (opt-in, guests only)
# A small first-party cookie with lesson positions and scores only (no name, e-mail or account id). A guest switches it
# on; switching it off deletes the cookie. It is per browser and per device, and browsers may clear it. It is never
# merged into an account automatically: a signed-in student is asked whether to add it (or to discard it).
DEVICE_FIELDS = ("page", "furthest", "completed", "revision", "best", "last", "attempts", "answered", "correct", "version")


def device_pack(prog: dict) -> str:
    """Encode a subject's progress for the cookie (compact JSON, base64url)."""
    import base64
    import json
    data = {}
    for lesson_id, rec in prog.items():
        if lesson_id in school.lesson_ids(SS.get("school_subject", "geography")) and isinstance(rec, dict):
            row = [int(rec.get(k, 0)) if not isinstance(rec.get(k), bool) else int(rec[k]) for k in DEVICE_FIELDS]
            row.append(rec.get("page_id", ""))
            row.append(rec.get("updated_at", ""))
            data[lesson_id] = row
    raw = json.dumps({"v": 1, "s": SS.get("school_subject", "geography"), "p": data}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def device_unpack(value: str | None) -> tuple[str, dict]:
    """(subject, {lesson_id: record}) from a cookie value; anything malformed is ignored."""
    import base64
    import json
    if not value:
        return "", {}
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode())
        subject_id = str(data.get("s", ""))
        out = {}
        for lesson_id, row in dict(data.get("p", {})).items():
            if lesson_id not in school.lesson_ids(subject_id) or not isinstance(row, list) or len(row) < len(DEVICE_FIELDS):
                continue
            rec = {k: (bool(v) if k in ("completed", "revision") else v) for k, v in zip(DEVICE_FIELDS, row)}
            if rec.get("attempts") == 0:
                rec.pop("best", None), rec.pop("last", None)
            if not rec.get("version"):
                rec.pop("version", None)
            if len(row) > len(DEVICE_FIELDS):
                rec["page_id"] = row[len(DEVICE_FIELDS)]
            if len(row) > len(DEVICE_FIELDS) + 1:
                rec["updated_at"] = row[len(DEVICE_FIELDS) + 1]
            d = school.lesson(subject_id, lesson_id)
            pages_ = school.pages(d)
            clean = school.clean_record({k: v for k, v in rec.items() if v not in ("", None)}, len(pages_), [p["id"] for p in pages_])
            if clean:
                out[lesson_id] = clean
        return subject_id, out
    except Exception:
        return "", {}


DEVICE_MAX = 3500          # the cookie's size limit (core/cookies.py checks the same pattern)


def _row(rec: dict) -> list:
    row = [int(rec.get(k, 0)) if not isinstance(rec.get(k), bool) else int(rec[k]) for k in DEVICE_FIELDS]
    return row + [rec.get("page_id", ""), rec.get("updated_at", "")]


def device_pack_all(all_progress: dict) -> str:
    """Version 2 of the cookie: every available subject's progress, {"v": 2, "p": {subject: {lesson: row}}}. If it would
    be too large, the least recently updated lessons are left out (the newest progress is always kept)."""
    import base64
    import json
    rows = []
    for subject_id, prog in (all_progress or {}).items():
        if not (school.subject(subject_id) or {}).get("status") == "available":
            continue
        ids = set(school.lesson_ids(subject_id))
        rows += [(str(rec.get("updated_at", "")), subject_id, lesson_id, _row(rec))
                 for lesson_id, rec in (prog or {}).items() if lesson_id in ids and isinstance(rec, dict)]
    rows.sort(reverse=True)
    while True:
        data: dict = {}
        for _, subject_id, lesson_id, row in rows:
            data.setdefault(subject_id, {})[lesson_id] = row
        raw = json.dumps({"v": 2, "p": data}, separators=(",", ":"))
        value = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        if len(value) <= DEVICE_MAX or not rows:
            return value
        rows.pop()


def device_unpack_all(value: str | None) -> dict:
    """{subject: {lesson_id: record}} from a version 2 cookie, or from a version 1 cookie (one subject)."""
    import base64
    import json
    if not value:
        return {}
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("v") != 2:
        subject_id, saved = device_unpack(value)
        return {subject_id: saved} if saved else {}
    out = {}
    for subject_id, rows in dict(data.get("p") or {}).items():
        if not isinstance(rows, dict) or (school.subject(str(subject_id)) or {}).get("status") != "available":
            continue
        one = base64.urlsafe_b64encode(json.dumps({"v": 1, "s": subject_id, "p": rows}).encode()).decode().rstrip("=")
        _, saved = device_unpack(one)
        if saved:
            out[subject_id] = saved
    return out


def _device_restore() -> None:
    """Once per session: a guest gets back the progress kept on this device; a signed-in student is only offered it."""
    if SS.get("school_device_checked"):
        return
    SS.school_device_checked = True
    found = device_unpack_all(cookies.read(DEVICE_COOKIE))
    if not found:
        return
    if _owner() != "guest":
        offer = SS.setdefault("school_guest_offer", {})
        for subject_id, saved in found.items():
            mine = offer.setdefault(subject_id, {})
            for lesson_id, rec in saved.items():
                if lesson_id not in mine or str(rec.get("updated_at", "")) >= str(mine[lesson_id].get("updated_at", "")):
                    mine[lesson_id] = rec
        SS.school_offer_on_device = True
        return
    SS.school_device_on = True
    for subject_id, saved in found.items():
        mine = SS.school_progress.setdefault(subject_id, {})
        for lesson_id, rec in saved.items():
            here = mine.get(lesson_id)
            if not here or str(rec.get("updated_at", "")) >= str(here.get("updated_at", "")):
                mine[lesson_id] = rec


def _device_write() -> None:
    if SS.get("school_device_on") and _owner() == "guest":
        cookies.write(DEVICE_COOKIE, device_pack_all(SS.get("school_progress", {})), DEVICE_DAYS * 86400)


def _offer() -> dict:
    """Guest progress (from this session before signing in, or from this device) waiting for the student's decision."""
    if _owner() == "guest" or SS.get("school_offer_hidden"):
        return {}
    return {k: v for k, v in (SS.get("school_guest_offer") or {}).get(SS.get("school_subject", "geography"), {}).items()
            if k in school.lesson_ids(SS.get("school_subject", "geography"))}


def _import_guest() -> None:
    """The student chose to add their guest progress. Newer (or equal, i.e. a retry) records are added to this visit's
    progress and saved to the account. The guest offer and the device backup are removed ONLY after every save to the
    account has succeeded; otherwise both are kept and the student is told exactly where the progress now is."""
    subject_id = SS.school_subject
    offer = _offer()
    if not offer:
        return
    chosen = {}
    for lesson_id, rec in offer.items():
        here = progress(subject_id).get(lesson_id)
        if not here or str(rec.get("updated_at", "")) >= str(here.get("updated_at", "")):
            chosen[lesson_id] = dict(rec)
            progress(subject_id)[lesson_id] = dict(rec)
    who = _who()
    if not who or not school_store.enabled():
        status = "session"                     # account saving is switched off: usable for this visit only
    elif not _loaded(subject_id):
        status = "error"                       # the account could not be loaded, so nothing can be saved yet
    else:
        saved = [_save_to_account(subject_id, lesson_id, rec) for lesson_id, rec in chosen.items()]
        status = "saved" if all(saved) else "error"
    SS.school_import_result = {"status": status, "count": len(offer), "added": len(chosen),
                               "device": bool(SS.get("school_offer_on_device"))}
    if status == "saved":
        _forget_guest()
    elif status == "session":
        _hide_offer()                          # added for this visit; the device backup (if any) is kept
    # "error": the offer stays visible so "Add to my progress" can be tried again; the device backup is kept


def _import_notice() -> None:
    """One-time, accurate feedback after "Add to my progress"."""
    res = SS.pop("school_import_result", None)
    if not res:
        return
    def lessons(k: int) -> str:
        return f'{k} lesson{"s" if k != 1 else ""}'
    n, added = res["count"], res.get("added", res["count"])
    skipped = n - added
    newer = "your account" if res["status"] == "saved" else "your progress"
    skip_note = (f" {lessons(skipped)} {'was' if skipped == 1 else 'were'} skipped because {newer} already has newer progress."
                 if skipped and added else "")
    if res["status"] in ("saved", "session") and not added:
        st.info(f"Nothing was added: {newer} already has newer progress for {'this lesson' if n == 1 else f'all {n} lessons'}."
                + (" The outdated guest copy on this device has been removed." if res["status"] == "saved" and res["device"]
                   else " The guest copy is still kept on this device." if res["device"] else ""))
    elif res["status"] == "saved":
        st.success(f"Guest progress added to your account ({lessons(added)})." + skip_note
                   + (" The guest copy on this device has been removed." if res["device"] else ""))
    elif res["status"] == "session":
        st.info(f"Guest progress ({lessons(added)}) added for this visit only. Saving to accounts is switched off, "
                "so it is not stored in your account." + skip_note
                + (" The guest copy is still kept on this device." if res["device"] else ""))
    else:
        st.warning(f"Your guest progress ({lessons(n)}) could not be saved to your account right now. It is in your progress "
                   "for this visit" + (", and the guest copy is still kept on this device" if res["device"] else "")
                   + ". Choose “Add to my progress” again to retry.")


def _forget_guest() -> None:
    SS.pop("school_guest_offer", None)
    if SS.pop("school_offer_on_device", False):
        cookies.write(DEVICE_COOKIE, "", 0)


def _hide_offer() -> None:
    SS.school_offer_hidden = True


def _device_toggle() -> None:
    SS.school_device_on = bool(SS.get("sl_device"))
    if SS.school_device_on:
        _device_write()
    else:
        cookies.write(DEVICE_COOKIE, "", 0)


def _restore(subject_id: str) -> None:
    """Load the signed-in student's saved progress once per session (retrying after a failure)."""
    who = _who()
    if not who or not school_store.enabled():
        return
    marker = who["profile_id"]
    if _loaded(subject_id) or time.time() < SS.get("school_retry_at", 0.0):
        return
    try:
        saved = school_store.load(marker, subject_id)
    except Exception:  # network or storage problem: keep the session progress, try again later
        SS.school_store_error = True
        SS.school_retry_at = time.time() + RETRY_SECONDS
        return
    mine = SS.school_progress.setdefault(subject_id, {})
    newer_here = []
    for lesson_id, rec in saved.items():
        if lesson_id not in school.lesson_ids(subject_id):
            continue
        pages_ = school.pages(school.lesson(subject_id, lesson_id))
        clean = school.clean_record(rec, len(pages_), [p["id"] for p in pages_])
        here = mine.get(lesson_id)
        if not here or str(clean.get("updated_at", "")) >= str(here.get("updated_at", "")):
            mine[lesson_id] = clean
    for lesson_id, here in mine.items():   # this same account's changes made before the load succeeded, including guest
        if lesson_id not in saved or str(here.get("updated_at", "")) > str(saved[lesson_id].get("updated_at", "")):
            newer_here.append(lesson_id)   # lessons it explicitly chose to add (_ensure_owner empties the session on any
                                           # identity change, so nothing from another identity is ever here)
    SS.setdefault("school_loaded_keys", set()).add(f"{marker}:{subject_id}")
    SS.school_store_error = False
    for lesson_id in newer_here:
        try:
            school_store.save(marker, subject_id, lesson_id, mine[lesson_id])
        except Exception:
            SS.school_store_error = True


def progress(subject_id: str) -> dict:
    _defaults()
    return SS.school_progress.setdefault(subject_id, {})


def _put(subject_id: str, lesson_id: str, rec: dict) -> None:
    """Keep the new record in the session; save that one lesson to the account (saving on) or to this device (opted in)."""
    before = progress(subject_id).get(lesson_id)
    progress(subject_id)[lesson_id] = rec
    if before == rec:
        return
    _save_to_account(subject_id, lesson_id, rec)
    _device_write()


def _save_to_account(subject_id: str, lesson_id: str, rec: dict) -> bool | None:
    """Save one lesson to the signed-in student's account. None: account saving is not active (guest, switched off, or
    the account is not loaded yet); True: school_store.save() succeeded; False: it raised (school_store_error is set)."""
    who = _who()
    if not who or not school_store.enabled() or not _loaded(subject_id):
        return None
    try:
        school_store.save(who["profile_id"], subject_id, lesson_id, rec)
    except Exception:
        SS.school_store_error = True
        return False
    SS.school_store_error = False
    return True


# --------------------------------------------------------------------------- navigation (button callbacks)

def go(view: str, lesson_id: str | None = None, page: int | None = None) -> None:
    _defaults()
    subject_id = SS.school_subject
    if lesson_id:
        SS.school_lesson = lesson_id
    if view == "practice" and school.interactive(subject_id) and SS.school_lesson:
        pages_ = school.pages(school.lesson(subject_id, SS.school_lesson))   # interactive lessons: the knowledge check page
        view, page = "lesson", school.page_index(pages_, "knowledge-check", len(pages_) - 1)
    if view == "lesson" and SS.school_lesson:
        d = school.lesson(subject_id, SS.school_lesson)
        pages_ = school.pages(d)
        rec = progress(subject_id).get(SS.school_lesson)
        target = school.page_index(pages_, (rec or {}).get("page_id"), (rec or {}).get("page", 0)) if page is None else page
        _put(subject_id, SS.school_lesson, school.move_to(rec, target, len(pages_), pages_, d.get("version", 1)))
        SS.school_scroll = True
    if view == "practice" and SS.school_lesson:
        d = school.lesson(subject_id, SS.school_lesson)
        session = school.new_practice(d, recent=(progress(subject_id).get(SS.school_lesson) or {}).get("recent"))
        session["token"] = random.randrange(10**6)
        SS.school_practice = session
        SS.school_scroll = True
    SS.school_view = view


def open_subject(subject_id: str) -> None:
    SS.school_subject = subject_id
    SS.school_view = "topics"


def continue_subject(subject_id: str) -> None:
    """Continue Learning on a subject card: the lesson to continue (where the student stopped), or the first lesson."""
    SS.school_subject = subject_id
    ids = school.lesson_ids(subject_id)
    if not ids:
        open_subject(subject_id)
        return
    prog = progress(subject_id)
    go("lesson", school.continue_target(subject_id, prog) if prog else ids[0])


def _turn(delta: int) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    d = school.lesson(subject_id, lesson_id)
    pages_ = school.pages(d)
    rec = progress(subject_id).get(lesson_id)
    _put(subject_id, lesson_id, school.move_to(rec, (rec or {}).get("page", 0) + delta, len(pages_), pages_, d.get("version", 1)))
    SS.school_scroll = True


def _jump(key: str) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    d = school.lesson(subject_id, lesson_id)
    pages_ = school.pages(d)
    target = SS.get(key)
    if isinstance(target, int):
        _put(subject_id, lesson_id, school.move_to(progress(subject_id).get(lesson_id), target, len(pages_), pages_, d.get("version", 1)))
        SS.school_scroll = True


def _complete(done: bool) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    total = len(school.pages(school.lesson(subject_id, lesson_id)))
    _put(subject_id, lesson_id, school.set_completed(progress(subject_id).get(lesson_id), total, done))


def _revision(on: bool) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    _put(subject_id, lesson_id, school.set_revision(progress(subject_id).get(lesson_id), on))


def _answer(token: int, index: int, pos: int) -> None:
    session = SS.get("school_practice")
    if not session or session.get("token") != token:
        return
    d = school.lesson(SS.school_subject, session["lesson"])
    if school.answer(session, d, index, pos):
        SS.school_fresh = (token, index)


def _next(token: int, index: int) -> None:
    session = SS.get("school_practice")
    if not session or session.get("token") != token:
        return
    if school.advance(session, index):
        SS.school_scroll = True
        if session["finished"] and not session.get("recorded"):
            session["recorded"] = True
            subject_id, lesson_id = SS.school_subject, session["lesson"]
            mark = school.score(session)
            asked = [a["id"] for a in session["answers"]]
            _put(subject_id, lesson_id, school.record_practice(progress(subject_id).get(lesson_id), mark, asked, len(asked)))
            who = _who()
            if who and school_store.enabled() and _loaded(subject_id):
                try:
                    school_store.record_attempt(who["profile_id"], subject_id, lesson_id, mark, len(session["items"]), session["answers"],
                                                school.lesson(subject_id, lesson_id).get("version", 1))
                except Exception:
                    SS.school_store_error = True


# --------------------------------------------------------------------------- shared pieces

def _scroll_to(selector: str) -> None:
    """After a page turn: bring the reader's top into view (once). No '<' in the script (the HTML cleaner drops it)."""
    if not SS.pop("school_scroll", False):
        return
    sel = selector.replace("'", "")
    st.html("<script>/*" + str(time.time_ns()) + "*/(function(){let n=0;const go=()=>{const el=document.querySelector('" + sel + "');"
            "if(!el){if(40>n++)setTimeout(go,50);return;}const r=el.getBoundingClientRect();"
            "if(0>r.top||r.top>innerHeight*0.6){el.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}};"
            "setTimeout(go,60);})();</script>", unsafe_allow_javascript=True)


def _storage_note(with_device: bool = True) -> None:
    """Say plainly where progress is kept, and offer to keep it on this device when account saving is unavailable."""
    mode = storage_mode()
    device = bool(SS.get("school_device_on"))
    text = {
        "guest": ("You are learning as a guest. Your progress is kept on this device (switch below)." if device else
                  "You are learning as a guest. Your progress is kept only while this browser tab is open, unless you "
                  "switch on “Keep my progress on this device”."),
        "session": "Saving School Learning progress to accounts is not switched on yet, so your progress is kept for this "
                   "visit only.",
        "saved": "Your School Learning progress is saved to your account, separately from quiz points and rewards, so you can "
                 "continue on another device.",
        "error": "We could not reach your saved School Learning progress just now. Your progress in this visit is kept, and we will "
                 "try again shortly. Nothing is lost.",
    }[mode]
    with st.container(key="sl_store_box"):
        html(f'<p class="sl-store sl-store-{mode}">{escape(text)}</p>')
        if with_device and mode == "guest":
            SS.sl_device = device
            st.toggle("Keep my progress on this device", key="sl_device", on_change=_device_toggle,
                      help="Stores your lesson positions and practice scores in a small cookie in this browser: no name, e-mail or "
                           "account details. It stays for up to 180 days, but private windows, clearing site data or some "
                           "browsers (for example Safari after 7 days without a visit) can remove it. Switch off to delete it.")


def _review_badge() -> str:
    return f'<span class="sl-review" title="{escape(REVIEW_NOTE, quote=True)}">⚠ {escape(REVIEW_LABEL)}</span>'


def _bar(percent: int, label: str) -> str:
    percent = max(0, min(100, int(percent)))
    return (f'<div class="sl-bar" role="progressbar" aria-label="{escape(label, quote=True)}" aria-valuemin="0" aria-valuemax="100" '
            f'aria-valuenow="{percent}"><span style="width:{percent}%"></span></div>')


def _status_chips(rec: dict | None) -> str:
    state_ = school.status(rec)
    tone = {"Not started": "", "In progress": "teal", "Completed": "ok"}[state_]
    out = _chip(("✓ " if state_ == "Completed" else "") + state_, tone)
    if school.revision_reasons(rec):
        out += _chip("↻ Needs revision", "warn")
    return out


def _levels(levels: list[str]) -> str:
    return "".join(_chip(x, "level") for x in levels)


def _guest_offer_box() -> None:
    """Explicit, separate import of guest progress after signing in. Nothing is added unless the student chooses."""
    _import_notice()
    offer = _offer()
    if not offer:
        return
    names = ", ".join(f'{school.lesson(SS.school_subject, i)["number"]}. {school.lesson(SS.school_subject, i)["short"]}'
                      for i in sorted(offer, key=lambda i: school.lesson(SS.school_subject, i)["number"]))
    where = "your account" if storage_mode() in ("saved", "error") else "your progress for this visit"
    with st.container(key="sl_guest_offer"):
        html(f'<div class="sl-offer"><b>You studied {len(offer)} lesson{"s" if len(offer) != 1 else ""} as a guest on this device</b>'
             f'<span class="sl-muted"> ({escape(names)}).</span><p class="sl-muted">Add that progress to {escape(where)}? '
             'Nothing is added unless you choose. If someone else used this device as a guest, choose “Discard”.</p></div>')
        with st.container(key="sl_offer_actions", horizontal=True):
            st.button("Add to my progress", key="sl_import_guest", type="primary", icon=":material/download_done:", on_click=_import_guest)
            st.button("Discard guest progress", key="sl_discard_guest", icon=":material/delete:", on_click=_forget_guest)
            st.button("Not now", key="sl_offer_later", on_click=_hide_offer)


# --------------------------------------------------------------------------- home: school → subjects

def _home() -> None:
    subject_id = SS.school_subject
    prog = progress(subject_id)
    html('<div class="sl-intro"><h2>School Learning</h2>'
         '<p>Study notes, maps, interactive lessons and practice for Nigerian students. Geography (SSS 1–3) follows the WAEC syllabus; '
         'Nigerian History (Primary and JSS) and Citizenship and Heritage Studies (SSS) follow the subjects introduced from the '
         '2025/26 session, starting with a few lessons.</p>'
         f'<div class="sl-intro-meta">{_review_badge()}{_chip("English")}{_chip("No account needed")}</div></div>')
    _guest_offer_box()
    if prog and school.lesson_ids(subject_id):
        _continue_card(subject_id, prog, "sl_continue_btn")
    _restore_widget("sl_subject_search", "")
    with st.container(key="sl_subject_bar", horizontal=True, vertical_alignment="center"):
        html('<h3 class="sl-h">Subjects</h3>')
        query = st.text_input("Search subjects", key="sl_subject_search", label_visibility="collapsed", icon=":material/search:",
                              placeholder="Search subjects…", on_change=_keep, args=("sl_subject_search",))
    needle = query.strip().casefold()
    shown = [x for x in school.subjects() if not needle or needle in " ".join([x["title"], x.get("summary", ""), x.get("level", "")]
                                                                               + x.get("keywords", []) + x.get("levels", [])).casefold()]
    if not shown:
        st.caption("No subject matches your search.")
    with st.container(key="sl_subjects", horizontal=True):
        for s in shown:
            with st.container(key=f"sl_subject_{s['id']}"):
                icon = ICONS.get(s.get("icon"), "📘")
                if s.get("status") == "available" and school.interactive(s["id"]):
                    from . import school_interactive
                    school_interactive.subject_card(s, progress(s["id"]))
                    _card_buttons(s)
                elif s.get("status") == "available":
                    o = school.overview(s["id"], progress(s["id"]))
                    html(f'<div class="sl-subject" style="--subject:{escape(s.get("colour", "#1F5F7A"))}">'
                         f'<div class="sl-subject-top"><span class="sl-subject-icon" aria-hidden="true">{icon}</span>'
                         f'<div><div class="sl-subject-name">{escape(s["title"])}</div><div class="sl-muted">{escape(s.get("level", ""))}</div></div></div>'
                         f'<p>{escape(s.get("summary", ""))}</p>'
                         f'<div class="sx-card-facts"><div><b>{o["lessons"]} full lessons</b><span>educational review pending</span></div>'
                         f'<div><b>{school.topic_count(s["id"])} topics</b><span>syllabus topics mapped</span></div></div>'
                         f'<div class="sl-card-meta">{_levels(s.get("levels", []))}</div>'
                         f'{_bar(round(100 * o["completed"] / o["lessons"]) if o["lessons"] else 0, s["title"] + " progress")}'
                         f'<div class="sl-card-foot"><span>{o["completed"]} of {o["lessons"]} completed</span>'
                         f'<span>{o["completed"] + o["in_progress"]} started</span></div></div>')
                    _card_buttons(s)
                else:   # no button: nothing pretends to be ready
                    html(f'<div class="sl-subject sl-subject-soon"><div class="sl-subject-top"><span class="sl-subject-icon" aria-hidden="true">{icon}</span>'
                         f'<div><div class="sl-subject-name">{escape(s["title"])}</div><div class="sl-muted">{escape(s.get("level", ""))}</div></div></div>'
                         f'<p>{escape(s.get("summary", ""))}</p>{_chip("Coming soon")}</div>')
    with st.container(key="sl_home_progress"):
        _overview_tiles(school.overview(subject_id, prog), compact=True)
        st.button("View my progress", key="sl_home_progress_btn", icon=":material/insights:", on_click=go, args=("progress",))
    html(f'<p class="sl-disclaimer">🎓 {escape(NOT_REWARDS)}</p>')


def _card_buttons(s: dict) -> None:
    started = any(progress(s["id"]).get(i) for i in school.lesson_ids(s["id"]))
    with st.container(key=f"sl_card_btns_{s['id']}", horizontal=True):
        st.button("Continue learning" if started else "Start learning", key=f"sl_cont_{s['id']}", type="primary",
                  icon=":material/menu_book:", on_click=continue_subject, args=(s["id"],), disabled=not school.lesson_ids(s["id"]))
        st.button("Explore subject", key=f"sl_open_{s['id']}", icon=":material/explore:", on_click=open_subject, args=(s["id"],))


def _continue_card(subject_id: str, prog: dict, key: str) -> None:
    """Continue learning: the most recent unfinished lesson, at the page (section) where the student stopped."""
    target = school.continue_target(subject_id, prog)
    d = school.lesson(subject_id, target)
    rec = prog.get(target) or {}
    pages_ = school.pages(d)
    here = school.page_index(pages_, rec.get("page_id"), rec.get("page", 0))
    with st.container(key="sl_continue"):
        html(f'<div class="sl-continue"><div class="sl-kicker">Continue learning · {escape(school.subject(subject_id)["title"])}</div>'
             f'<div class="sl-continue-title">' + (escape(d["class"]) + " · " if d.get("class") else f'Lesson {d["number"]}: ')
             + f'{escape(d["title"])}</div>'
             f'<div class="sl-muted">{escape(pages_[here]["title"])} · page {here + 1} of {len(pages_)} · '
             f'{school.reading_percent(rec, len(pages_))}% read</div>{_bar(school.reading_percent(rec, len(pages_)), "Reading progress")}</div>')
        st.button("Continue learning", key=key, type="primary", icon=":material/menu_book:", on_click=go, args=("lesson", target))


def _overview_tiles(o: dict, compact: bool = False) -> None:
    avg = f'{o["average"]}%' if o["average"] is not None else "—"
    tiles = [("Lessons completed", f'{o["completed"]} / {o["lessons"]}'), ("In progress", str(o["in_progress"])),
             ("Need revision", str(o["revise"])), ("Average practice score", avg)]
    if not compact:
        tiles.insert(0, ("Lessons available", str(o["lessons"])))
        tiles.append((f'Questions attempted ({o["correct"]} correct)' if o["answered"] else "Questions attempted", str(o["answered"])))
    html(f'<div class="sl-tiles{" sl-tiles-6" if not compact else ""}">' + "".join(
        f'<div class="sl-tile"><div class="sl-tile-v">{escape(v)}</div><div class="sl-tile-l">{escape(k)}</div></div>' for k, v in tiles) + "</div>")


# --------------------------------------------------------------------------- topics: subject → level → topic → lesson

def _topics() -> None:
    if school.interactive(SS.school_subject):
        from . import school_interactive
        school_interactive.topics_view()
        return
    subject_id = SS.school_subject
    s, cur, prog = school.subject(subject_id), school.curriculum(subject_id), progress(subject_id)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_back_home", icon=":material/arrow_back:", on_click=go, args=("home",))
        st.button("My progress", key="sl_topics_progress", icon=":material/insights:", on_click=go, args=("progress",))
    _guest_offer_box()
    html(f'<div class="sl-intro"><div class="sl-kicker">{escape(s.get("level", ""))}</div><h2>{escape(s["title"])}</h2>'
         '<p>Seven full lessons on the regional geography of Nigeria, each with notes, maps, key terms, worked examples, exam guidance, '
         'quick checks, exam-style questions and a bank of 21 practice questions. The rest of the syllabus is listed below as coming soon.</p>'
         f'<div class="sl-intro-meta">{_review_badge()}</div></div>')
    sections = ["All"] + [sec["id"] for sec in cur["sections"]]
    titles = {"All": "All curriculum sections", **{sec["id"]: sec["title"] for sec in cur["sections"]}}
    levels = ["All"] + cur.get("levels", [])
    _restore_widget("sl_topic_search", "")
    _restore_widget("sl_section", "All", sections)
    _restore_widget("sl_level", "All", levels)
    _restore_widget("sl_state", "All", list(school.STATE_FILTERS))
    with st.container(key="sl_filters"):
        query = st.text_input("Search Geography topics", key="sl_topic_search", label_visibility="collapsed", icon=":material/search:",
                              placeholder="Search Geography topics, e.g. Harmattan, census, ports…", on_change=_keep, args=("sl_topic_search",))
        with st.container(key="sl_filter_row", horizontal=True):
            section = st.selectbox("Curriculum section", sections, key="sl_section", format_func=titles.get,
                                   on_change=_keep, args=("sl_section",))
            level = st.selectbox("Class", levels, key="sl_level", format_func=lambda x: "All classes" if x == "All" else x,
                                 on_change=_keep, args=("sl_level",))
        state_ = st.pills("Learning status", list(school.STATE_FILTERS), key="sl_state", required=True,
                          on_change=_keep, args=("sl_state",), label_visibility="collapsed")
    found = school.find_lessons(subject_id, prog, query, section, state_ or "All", level)
    if found:
        html(f'<div class="sl-count">{len(found)} of {len(school.lesson_ids(subject_id))} lessons</div>')
    else:
        html('<div class="sl-count">No lessons match these filters.</div>')
    with st.container(key="sl_lesson_grid", horizontal=True):   # two cards per row on wide screens, one on phones
        for lesson_id in found:
            _lesson_card(subject_id, lesson_id, prog.get(lesson_id))
    soon = school.find_topics(subject_id, query, section, level)
    if soon:
        with st.expander(f"Coming soon: {len(soon)} more syllabus topics", key="sl_soon"):
            st.caption(cur["status_note"])
            html('<ul class="sl-syllabus">' + "".join(
                f'<li><div class="sl-soon-t">{escape(t["title"])} {_levels(t.get("level", []))}</div>'
                f'<div class="sl-muted">{escape(sec["title"])} · {escape("; ".join(t.get("objectives", [])))}</div></li>'
                for sec, t in soon) + "</ul>")
    with st.expander("Topics not examined for Nigerian candidates", key="sl_not_nigeria"):
        html('<ul class="sl-syllabus">' + "".join(f"<li>{escape(n)}</li>" for n in cur.get("not_for_nigeria", [])) + "</ul>")


def _lesson_card(subject_id: str, lesson_id: str, rec: dict | None) -> None:
    d = school.lesson(subject_id, lesson_id)
    total = len(school.pages(d))
    pct = school.reading_percent(rec, total)
    best = f'Best practice score {rec["best"]}/{school.PRACTICE_SIZE}' if rec and rec.get("attempts") else "Not practised yet"
    reasons = school.revision_reasons(rec)
    with st.container(key=f"sl_lesson_card_{lesson_id}"):
        html(f'<div class="sl-card-head"><span class="sl-num">{d["number"]}</span><div><div class="sl-card-title">{escape(d["title"])}</div>'
             f'<div class="sl-card-meta">{_levels(d.get("level", []))}<span class="sl-muted">About {d.get("minutes", 30)} min · {total} pages · '
             f'{len(d["practice"])} questions</span></div></div></div>'
             f'<div class="sl-card-meta">{_status_chips(rec)}' + (_chip("Updated since you read it", "teal") if school.updated_since(rec, d) else "")
             + f'</div>{_bar(pct, "Reading progress")}<div class="sl-card-foot"><span>{pct}% read</span><span>{escape(best)}</span></div>'
             + (f'<div class="sl-why">↻ {escape("; ".join(reasons))}</div>' if reasons else ""))
        with st.container(key=f"sl_card_actions_{lesson_id}", horizontal=True):
            label = "Start lesson" if not rec else ("Read again" if rec.get("completed") else "Continue")
            st.button(label, key=f"sl_read_{lesson_id}", type="primary", icon=":material/menu_book:",
                      on_click=go, args=("lesson", lesson_id, 0 if rec and rec.get("completed") else None))
            st.button("Practise questions", key=f"sl_practise_{lesson_id}", icon=":material/edit_note:",
                      on_click=go, args=("practice", lesson_id))


# --------------------------------------------------------------------------- lesson reader

def _block(subject_id: str, b: dict) -> None:
    kind = b["type"]
    if kind == "p":
        html(f'<p class="sl-p">{_rich(b["text"])}</p>')
    elif kind == "h":
        html(f'<h4 class="sl-h4">{_rich(b["text"])}</h4>')
    elif kind == "list":
        html('<ul class="sl-list">' + "".join(f"<li>{_rich(i)}</li>" for i in b["items"]) + "</ul>")
    elif kind == "cards":
        html('<div class="sl-cards">' + "".join(
            f'<div class="sl-infocard sl-tone-{escape(i.get("tone") or "plain")}"><div class="sl-infocard-t">{_rich(i["title"])}</div>'
            f'<div>{_rich(i["text"])}</div></div>' for i in b["items"]) + "</div>")
    elif kind == "table":
        head = "".join(f'<th scope="col">{_rich(h)}</th>' for h in b["head"])
        rows = "".join("<tr>" + "".join(f"<td>{_rich(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
        html(f'<div class="sl-table-wrap" tabindex="0"><table class="sl-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
    elif kind == "figure":
        svg = " ".join(school.figure(subject_id, b["src"]).split())   # one line: markdown keeps inline SVG intact
        html(f'<figure class="sl-fig">{svg}<figcaption><b>{_rich(b["caption"])}</b>'
             f'<span class="sl-credit">{escape(b.get("credit", ""))}</span></figcaption></figure>')
    elif kind == "photo":
        photo = PHOTOS.get(str(b["src"]).removeprefix("country:"))
        if photo:   # the app's licensed photo; a broken image hides itself and only the caption and credit remain
            credit = (f'Photo: {escape(photo["author"])} · <a href="{escape(photo["license_url"], quote=True)}" target="_blank" '
                      f'rel="noopener">{escape(photo["license"])}</a>')
            html(f'<figure class="sl-photo"><img src="{escape(photo["url"], quote=True)}" alt="" loading="lazy" decoding="async" '
                 f'onerror="this.style.display=\'none\'"><figcaption><b>{escape(b.get("caption") or photo["caption"])}</b>'
                 f'<span class="sl-credit">{credit}</span></figcaption></figure>')
    elif kind == "note":
        html(f'<div class="sl-note">💡 {_rich(b["text"])}</div>')


def _exam_guidance(subject_id: str) -> None:
    g = school.curriculum(subject_id).get("exam_guidance")
    if not g:
        return
    html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">How to approach examination questions</div>'
         '<div class="sl-two"><div><b>Objective (multiple-choice) questions</b><ul class="sl-list">'
         + "".join(f"<li>{_rich(x)}</li>" for x in g["objective"]) + '</ul></div><div><b>Structured (written) questions</b><ul class="sl-list">'
         + "".join(f"<li>{_rich(x)}</li>" for x in g["structured"]) + f'</ul></div></div><p class="sl-muted">{escape(g.get("note", ""))}</p></div>')


def _page_body(subject_id: str, d: dict, page: dict) -> None:
    kind = page["kind"]
    html(f'<h3 class="sl-page-title">{escape(page["title"])}</h3>')
    if kind == "intro":
        for p in d["intro"]:
            html(f'<p class="sl-p">{_rich(p)}</p>')
        html('<div class="sl-box"><div class="sl-box-t">Learning objectives: by the end of this lesson you should be able to</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(o)}</li>" for o in d["objectives"]) + "</ul></div>")
        html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">Where this fits in the curriculum</div>'
             f'<p class="sl-p">{_levels(d.get("level", []))} {escape(d.get("level_note", ""))}</p><ul class="sl-list">'
             + "".join(f"<li>{_rich(x)}</li>" for x in d.get("syllabus", [])) + "</ul>"
             f'<p class="sl-muted">{escape(REVIEW_NOTE)}</p></div>')
    elif kind == "section":
        for b in page["section"]["blocks"]:
            _block(subject_id, b)
    elif kind == "definitions":
        html('<dl class="sl-defs">' + "".join(f"<div><dt>{_rich(term)}</dt><dd>{_rich(meaning)}</dd></div>"
                                              for term, meaning in d["definitions"]) + "</dl>")
    elif kind == "examples":
        for i, w in enumerate(d.get("worked", []), 1):
            html(f'<div class="sl-worked"><div class="sl-box-t">Worked example {i}: {_rich(w["title"])}</div>'
                 f'<p class="sl-p"><b>Question.</b> {_rich(w["problem"])}</p><ol class="sl-list">'
                 + "".join(f"<li>{_rich(s)}</li>" for s in w["steps"]) + "</ol>"
                 + (f'<p class="sl-muted">{_rich(w["note"])}</p>' if w.get("note") else "") + "</div>")
        html('<div class="sl-box sl-box-gold"><div class="sl-box-t">Exam tips for this topic</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(x)}</li>" for x in d["exam_tips"]) + "</ul></div>")
        _exam_guidance(subject_id)
    elif kind == "check":
        st.caption("Try to answer each question yourself first, then open it to check.")
        for i, c in enumerate(d["checks"], 1):
            with st.expander(f"{i}. {_plain(c['q'])}", key=f"sl_check_{d['id']}_{i}"):
                html(f'<p class="sl-p">{_rich(c["a"])}</p>')
    elif kind == "review":
        html('<div class="sl-box"><div class="sl-box-t">Revision summary</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(x)}</li>" for x in d["summary"]) + "</ul></div>")
        html('<h4 class="sl-h4">Structured (exam-style) questions</h4>')
        for i, q in enumerate(d["structured"], 1):
            html(f'<div class="sl-structured"><p class="sl-p"><b>Question {i}</b> ({q["marks"]} marks). {_rich(q["q"])}</p></div>')
            with st.expander("Show a model answer and marking guidance", key=f"sl_model_{d['id']}_{i}"):
                html("".join(f'<p class="sl-p">{_rich(m)}</p>' for m in q["model"])
                     + '<div class="sl-box-t">Marking guidance</div><ul class="sl-list">'
                     + "".join(f"<li>{_rich(p)}</li>" for p in q["points"]) + "</ul>")
        html('<h4 class="sl-h4">References</h4><ul class="sl-refs">' + "".join(
            f'<li><a href="{escape(r["url"], quote=True)}" target="_blank" rel="noopener">{escape(r["title"])}</a></li>'
            for r in d["references"]) + "</ul>")


def _lesson() -> None:
    if school.interactive(SS.school_subject):
        from . import school_interactive
        school_interactive.lesson_view()
        return
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    if lesson_id not in school.lesson_ids(subject_id):
        SS.school_view = "topics"
        _topics()
        return
    d = school.lesson(subject_id, lesson_id)
    pages = school.pages(d)
    total = len(pages)
    rec = progress(subject_id).get(lesson_id) or school.move_to(None, 0, total, pages)
    here = school.page_index(pages, rec.get("page_id"), rec.get("page", 0))
    pct = school.reading_percent(rec, total)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("Back to topics", key="sl_back_topics", icon=":material/arrow_back:", on_click=go, args=("topics",))
        st.button("My progress", key="sl_lesson_progress", icon=":material/insights:", on_click=go, args=("progress",))
    with st.container(key="sl_reader_head"):
        html(f'<div class="sl-kicker">Lesson {d["number"]} of {len(school.lesson_ids(subject_id))} · Geography · {escape(" / ".join(d.get("level", [])))}</div>'
             f'<h2 class="sl-lesson-title">{escape(d["title"])}</h2>'
             f'<div class="sl-card-meta">{_status_chips(rec)}{_review_badge()}</div>'
             f'<div class="sl-readline"><span>Page {here + 1} of {total}</span><span>{pct}% read</span></div>{_bar(pct, "Reading progress")}')
    side, main = st.columns([1, 3], gap="medium")
    with side, st.container(key="sl_contents"):
        html('<div class="sl-box-t">Contents</div>')
        for i, p in enumerate(pages):
            seen = i <= rec.get("furthest", 0)
            st.button(("● " if i == here else ("✓ " if seen else "◦ ")) + p["title"], key=f"sl_toc_{i}",
                      type="primary" if i == here else "secondary", width="stretch",
                      on_click=go, args=("lesson", None, i))
    with main, st.container(key="sl_reader"):
        jump_key = f"sl_jump_{lesson_id}"
        SS[jump_key] = here
        with st.container(key="sl_jump_box"):
            st.selectbox("Lesson contents", list(range(total)), key=jump_key,
                         format_func=lambda i: f"{i + 1}. {pages[i]['title']}", on_change=_jump, args=(jump_key,))
        with st.container(key=f"sl_page_{pages[here]['kind']}"):
            _page_body(subject_id, d, pages[here])
        with st.container(key="sl_pager", horizontal=True):
            st.button("Previous page", key="sl_prev_page", icon=":material/chevron_left:", disabled=here == 0,
                      on_click=_turn, args=(-1,))
            if here + 1 < total:
                st.button("Next page", key="sl_next_page", type="primary", icon=":material/chevron_right:", icon_position="right",
                          on_click=_turn, args=(1,))
            else:
                st.button("Practise questions", key="sl_practise_end", type="primary", icon=":material/edit_note:",
                          on_click=go, args=("practice",))
        with st.container(key="sl_lesson_actions"):
            done = bool(rec.get("completed"))
            ready = school.can_complete(rec, total)
            with st.container(key="sl_status_row", horizontal=True, vertical_alignment="center"):
                if done:
                    st.button("Completed · undo", key="sl_uncomplete", icon=":material/check_circle:",
                              on_click=_complete, args=(False,), help="Marks the lesson as not complete. Your scores are kept.")
                else:
                    st.button("Mark lesson complete", key="sl_complete", icon=":material/task_alt:", disabled=not ready,
                              type="primary" if ready else "secondary", on_click=_complete, args=(True,))
                on = bool(rec.get("revision"))
                st.button("Remove from revision" if on else "Add to revision", key="sl_revision",
                          icon=":material/bookmark_remove:" if on else ":material/bookmark_add:", on_click=_revision, args=(not on,))
                st.button("Practise questions", key="sl_practise_now", icon=":material/edit_note:", on_click=go, args=("practice",))
            if not done and not ready:
                st.caption("Reach the last page to mark this lesson complete. Completion records that you have read it; "
                           "your revision list is separate and a low practice score never removes completion.")
            reasons = school.revision_reasons(rec)
            if reasons:
                html(f'<div class="sl-why">↻ Needs revision: {escape("; ".join(reasons))}</div>')
        before, after = school.neighbours(subject_id, lesson_id)
        with st.container(key="sl_lesson_nav", horizontal=True):
            st.button(f"Previous lesson · {school.lesson(subject_id, before)['short']}" if before else "Previous lesson",
                      key="sl_prev_lesson", icon=":material/skip_previous:", disabled=not before, on_click=go, args=("lesson", before))
            st.button(f"Next lesson · {school.lesson(subject_id, after)['short']}" if after else "Next lesson",
                      key="sl_next_lesson", icon=":material/skip_next:", icon_position="right", disabled=not after,
                      on_click=go, args=("lesson", after))
    _scroll_to(".st-key-sl_reader_head")


# --------------------------------------------------------------------------- practice

def _practice() -> None:
    subject_id = SS.school_subject
    if school.interactive(subject_id):          # interactive lessons have their knowledge check inside the lesson
        SS.school_view = "lesson"
        _lesson()
        return
    session = SS.get("school_practice")
    if not session or session["lesson"] not in school.lesson_ids(subject_id):
        SS.school_view = "topics"
        _topics()
        return
    d = school.lesson(subject_id, session["lesson"])
    token = session["token"]
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("Back to lesson", key="sl_practice_back", icon=":material/arrow_back:", on_click=go, args=("lesson", d["id"]))
        st.button("Back to topics", key="sl_practice_topics", icon=":material/list:", on_click=go, args=("topics",))
    html(f'<div class="sl-practice-head"><div class="sl-kicker">School practice · Lesson {d["number"]}</div>'
         f'<h2 class="sl-lesson-title">{escape(d["title"])}</h2>'
         f'<p class="sl-muted">📚 School practice is separate from the 🌍 World Geography Quiz: no points, streaks, badges or rewards.</p></div>')
    if session["finished"]:
        _practice_result(subject_id, d, session)
        _scroll_to(".st-key-sl_result")
        return
    index = session["index"]
    item = session["items"][index]
    q = school.question(d, item["id"])
    answered = len(session["answers"]) > index
    rec = session["answers"][index] if answered else None
    fresh = answered and SS.get("school_fresh") == (token, index)
    with st.container(key="sl_question_card"):
        html(f'<div class="sl-readline"><span>Question {index + 1} of {len(session["items"])} · {escape(q["difficulty"].title())}</span>'
             f'<span>{school.score(session)} correct so far</span></div>{_bar(100 * (index + answered) // len(session["items"]), "Practice progress")}'
             f'<h3 class="sl-question">{escape(q["q"])}</h3>')
        with st.container(key="sl_answers"):
            for row in (0, 2):
                for column, pos in zip(st.columns(2), (row, row + 1)):
                    original = item["order"][pos]
                    text = q["options"][original]
                    style, label = "neutral_answer", text
                    if answered and original == q["answer"]:
                        style = "correct_answer"
                        label = f"{text} `✓ {'Your answer · Correct' if original == rec['chosen'] else 'Correct answer'}`"
                    elif answered and original == rec["chosen"]:
                        style, label = "wrong_answer", f"{text} `✕ Your answer · Wrong`"
                    if fresh and style != "neutral_answer":
                        style += "_fx"
                    with column, st.container(key=f"ans{pos}_{style}"):
                        st.button(label, key=f"sl_ans_{token}_{index}_{pos}", width="stretch", disabled=answered,
                                  on_click=_answer, args=(token, index, pos))
    if answered:
        tone = "correct" if rec["correct"] else "wrong"
        head = "✓ Correct!" if rec["correct"] else f'✕ Not quite. Correct answer: <b>{escape(q["options"][q["answer"]])}</b>'
        section = next((s for s in d["sections"] if s["id"] == q["section"]), None)
        with st.container(key=f"sl_feedback_{tone}"):
            html(f'<div class="feedback feedback-{tone}" role="status"><div class="feedback-head"><span>{head}</span></div>'
                 f'<p class="feedback-explain">{_rich(q["explanation"])}</p>'
                 + (f'<p class="feedback-note">From the lesson section: {escape(section["title"])}</p>' if section else "") + '</div>')
            with st.container(key="sl_feedback_actions", horizontal=True):
                last = index + 1 == len(session["items"])
                st.button("See my score" if last else "Next question", key=f"sl_next_{token}_{index}", type="primary",
                          icon=":material/arrow_forward:", icon_position="right", on_click=_next, args=(token, index))
    _scroll_to(".st-key-sl_question_card")


def _practice_result(subject_id: str, d: dict, session: dict) -> None:
    mark, total = school.score(session), len(session["items"])
    rec = progress(subject_id).get(d["id"]) or {}
    good = mark >= school.REVISE_BELOW * total
    areas = school.areas_to_revise(session, d)
    pages_ = school.pages(d)
    with st.container(key="sl_result"):
        html(f'<div class="sl-result {"sl-result-good" if good else "sl-result-revise"}"><div class="sl-result-score">{mark}<small>/{total}</small></div>'
             f'<div><div class="sl-card-title">{mark} of {total} correct. ' + ("Well done!" if good else "Keep going: revise and try again.") + '</div>'
             f'<div class="sl-muted">Best score for this lesson: {rec.get("best", mark)}/{total} · practice rounds: {rec.get("attempts", 1)}</div>'
             + ("" if good else '<div class="sl-why">↻ This lesson now shows “Needs revision” (best score below 6/10). Your completion is not affected.</div>')
             + "</div></div>")
        if areas:
            html('<div class="sl-box-t">Areas to revise</div>')
            with st.container(key="sl_areas", horizontal=True):
                for sec, n in areas:
                    page = school.page_index(pages_, sec["id"])
                    st.button(f"{sec['title']} · {n} missed", key=f"sl_area_{sec['id']}", icon=":material/menu_book:",
                              on_click=go, args=("lesson", d["id"], page))
        review = []
        for a in session["answers"]:
            q = school.question(d, a["id"])
            review.append(f'<li class="{"ok" if a["correct"] else "bad"}"><span aria-hidden="true">{"✓" if a["correct"] else "✕"}</span> '
                          f'{escape(q["q"])}<br><small>{"Correct" if a["correct"] else "Correct answer: " + escape(q["options"][q["answer"]])}'
                          f' · {escape(q["explanation"])}</small></li>')
        with st.expander("Your answers with explanations", key="sl_review_answers", expanded=not good):
            html('<ul class="sl-answers-review">' + "".join(review) + "</ul>")
        with st.container(key="sl_result_actions", horizontal=True):
            st.button("Try 10 more questions", key="sl_again", type="primary", icon=":material/refresh:", on_click=go, args=("practice", d["id"]),
                      help="New questions from this lesson's bank first; questions you have just seen come back only when the bank runs out.")
            st.button("Back to lesson", key="sl_result_lesson", icon=":material/menu_book:", on_click=go, args=("lesson", d["id"]))
            st.button("My progress", key="sl_result_progress", icon=":material/insights:", on_click=go, args=("progress",))
    _storage_note()


# --------------------------------------------------------------------------- progress dashboard

def _progress() -> None:
    if school.interactive(SS.school_subject):
        from . import school_interactive
        school_interactive.progress_view()
        return
    subject_id = SS.school_subject
    prog = progress(subject_id)
    o = school.overview(subject_id, prog)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_progress_home", icon=":material/arrow_back:", on_click=go, args=("home",))
        st.button("Back to topics", key="sl_progress_topics", icon=":material/list:", on_click=go, args=("topics",))
    _guest_offer_box()
    html(f'<div class="sl-intro"><h2>My School Learning progress</h2><p>{escape(school.subject(subject_id)["title"])} · '
         'academic progress only, kept separately from quiz points, badges and rewards.</p></div>')
    _overview_tiles(o)
    if prog:
        _continue_card(subject_id, prog, "sl_progress_continue")
    if o["recent"]:
        html('<div class="sl-box-t">Recently studied</div>')
        with st.container(key="sl_recent", horizontal=True):
            for lesson_id in o["recent"]:
                d = school.lesson(subject_id, lesson_id)
                st.button(f"{d['number']}. {d['title']}", key=f"sl_recent_{lesson_id}", icon=":material/history:",
                          on_click=go, args=("lesson", lesson_id))
    rows = []
    for lesson_id in school.lesson_ids(subject_id):
        d = school.lesson(subject_id, lesson_id)
        rec = prog.get(lesson_id)
        total = len(school.pages(d))
        best = f'{rec["best"]}/{school.PRACTICE_SIZE}' if rec and rec.get("attempts") else "—"
        tried = (f'{rec.get("answered", 0)} ({rec["attempts"]} round{"s" if rec["attempts"] != 1 else ""})'
                 if rec and rec.get("attempts") else "—")
        reasons = "; ".join(school.revision_reasons(rec)) or "—"
        rows.append(f'<tr><th scope="row">{d["number"]}. {escape(d["title"])}</th><td data-label="Status">{_status_chips(rec)}</td>'
                    f'<td data-label="Read">{school.reading_percent(rec, total)}%</td><td data-label="Best score">{escape(best)}</td>'
                    f'<td data-label="Questions attempted">{escape(tried)}</td><td data-label="Revision">{escape(reasons)}</td></tr>')
    html('<div class="sl-table-wrap" tabindex="0"><table class="sl-table sl-progress-table"><thead><tr><th scope="col">Lesson</th>'
         '<th scope="col">Status</th><th scope="col">Read</th><th scope="col">Best score</th><th scope="col">Questions attempted</th>'
         f'<th scope="col">Revision</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    with st.expander("How progress is calculated", key="sl_rules"):
        html('<ul class="sl-list">'
             '<li><b>Not started:</b> you have not opened the lesson. <b>In progress:</b> opened but not marked complete.</li>'
             '<li><b>Completed:</b> you pressed “Mark lesson complete” after reaching the last page. A practice score never removes it.</li>'
             '<li><b>Needs revision:</b> you added the lesson to your revision list, or your best practice score is below 6/10. '
             'It is shown alongside the reading status, so a completed lesson can still need revision.</li>'
             '<li><b>Read %:</b> the furthest page you have reached, out of the lesson’s pages.</li>'
             '<li><b>Average practice score:</b> the average of your best score in each lesson you have practised.</li>'
             '<li><b>Questions attempted:</b> every practice question you have answered in finished rounds.</li></ul>')
    _storage_note()
    html(f'<p class="sl-disclaimer">🎓 {escape(NOT_REWARDS)}</p>')


# --------------------------------------------------------------------------- entry point

VIEWS = {"home": _home, "topics": _topics, "lesson": _lesson, "practice": _practice, "progress": _progress}


@st.fragment
def _school() -> None:
    """School Learning reruns on its own (a page turn or an answer does not redraw the rest of World Explorer)."""
    _ensure_owner()
    _device_restore()
    _restore(SS.school_subject)
    if SS.school_view == "home":                # the home cards show every subject's progress
        for s in school.subjects():
            if s.get("status") == "available" and s["id"] != SS.school_subject:
                _restore(s["id"])
    with st.container(key=f"school_{SS.school_view if SS.school_view in VIEWS else 'home'}"):
        VIEWS.get(SS.school_view, _home)()
        if SS.school_view in ("home", "topics", "lesson"):
            _storage_note()
    cookie_script()   # apply a queued "keep on this device" write now (fragment reruns do not reach the page footer)


def render() -> None:
    _defaults()
    if not school.subject(SS.school_subject) or school.subject(SS.school_subject).get("status") != "available":
        SS.school_subject = next(s["id"] for s in school.subjects() if s.get("status") == "available")
    _school()
