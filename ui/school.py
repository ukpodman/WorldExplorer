"""School Learning (Learn → 📚 School Learning): Nigerian SSS study notes, reading progress and topic practice.

Reusable for any subject in data/school/subjects.json: the screens below only read the subject, curriculum and lesson
files through core/school.py, so Nigerian History or Citizenship and Heritage Studies are added as data.

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

from core import accounts, school, school_store
from core.data import PHOTOS

from .components import html

SS = st.session_state
REVIEW_LABEL = "Educational review pending"
REVIEW_NOTE = ("These notes were written and fact-checked by the World Explorer team against published sources. "
               "They have not yet been reviewed by a qualified teacher. Always follow your teacher and your school's scheme of work.")
NOT_REWARDS = ("School Learning is for study only. It does not earn points, badges, rewards or money, and it is separate from the "
               "World Geography Quiz.")
RETRY_SECONDS = 30.0
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


def _who() -> dict | None:
    return accounts.identity()


def storage_mode() -> str:
    """'guest' (not signed in), 'session' (signed in, saving switched off), 'saved' or 'error'."""
    who = _who()
    if not who:
        return "guest"
    if not school_store.enabled():
        return "session"
    return "error" if SS.get("school_store_error") or SS.get("school_loaded") != who["profile_id"] else "saved"


def _restore(subject_id: str) -> None:
    """Load the signed-in student's saved progress once per session (retrying after a failure)."""
    who = _who()
    if not who or not school_store.enabled():
        return
    marker = who["profile_id"]
    if SS.get("school_loaded") == marker or time.time() < SS.get("school_retry_at", 0.0):
        return
    try:
        saved = school_store.load(marker, subject_id)
    except Exception:  # network or storage problem: keep the session progress, try again later
        SS.school_store_error = True
        SS.school_retry_at = time.time() + RETRY_SECONDS
        return
    mine = SS.school_progress.setdefault(subject_id, {})
    for lesson_id, rec in saved.items():
        if lesson_id not in school.lesson_ids(subject_id):
            continue
        total = len(school.pages(school.lesson(subject_id, lesson_id)))
        clean = school.clean_record(rec, total)
        here = mine.get(lesson_id)
        if not here or str(clean.get("updated_at", "")) >= str(here.get("updated_at", "")):
            mine[lesson_id] = clean
    SS.school_loaded = marker
    SS.school_store_error = False


def progress(subject_id: str) -> dict:
    _defaults()
    return SS.school_progress.setdefault(subject_id, {})


def _put(subject_id: str, lesson_id: str, rec: dict) -> None:
    """Keep the new record in the session and, for a signed-in student with saving on, save that one lesson."""
    before = progress(subject_id).get(lesson_id)
    progress(subject_id)[lesson_id] = rec
    if before == rec:
        return
    who = _who()
    if who and school_store.enabled() and SS.get("school_loaded") == who["profile_id"]:
        try:
            school_store.save(who["profile_id"], subject_id, lesson_id, rec)
            SS.school_store_error = False
        except Exception:
            SS.school_store_error = True


# --------------------------------------------------------------------------- navigation (button callbacks)

def go(view: str, lesson_id: str | None = None, page: int | None = None) -> None:
    _defaults()
    subject_id = SS.school_subject
    if lesson_id:
        SS.school_lesson = lesson_id
    if view == "lesson" and SS.school_lesson:
        d = school.lesson(subject_id, SS.school_lesson)
        total = len(school.pages(d))
        rec = progress(subject_id).get(SS.school_lesson)
        target = (rec or {}).get("page", 0) if page is None else page
        _put(subject_id, SS.school_lesson, school.move_to(rec, target, total))
        SS.school_scroll = True
    if view == "practice" and SS.school_lesson:
        d = school.lesson(subject_id, SS.school_lesson)
        session = school.new_practice(d)
        session["token"] = random.randrange(10**6)
        SS.school_practice = session
        SS.school_scroll = True
    SS.school_view = view


def open_subject(subject_id: str) -> None:
    SS.school_subject = subject_id
    SS.school_view = "topics"


def _turn(delta: int) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    total = len(school.pages(school.lesson(subject_id, lesson_id)))
    rec = progress(subject_id).get(lesson_id)
    _put(subject_id, lesson_id, school.move_to(rec, (rec or {}).get("page", 0) + delta, total))
    SS.school_scroll = True


def _jump(key: str) -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    total = len(school.pages(school.lesson(subject_id, lesson_id)))
    target = SS.get(key)
    if isinstance(target, int):
        _put(subject_id, lesson_id, school.move_to(progress(subject_id).get(lesson_id), target, total))
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
            _put(subject_id, lesson_id, school.record_practice(progress(subject_id).get(lesson_id), mark))
            who = _who()
            if who and school_store.enabled() and SS.get("school_loaded") == who["profile_id"]:
                try:
                    school_store.record_attempt(who["profile_id"], subject_id, lesson_id, mark, len(session["items"]), session["answers"])
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


def _storage_note() -> None:
    mode = storage_mode()
    text = {
        "guest": "You are learning as a guest: your reading progress and practice scores are kept only while this browser tab is open. "
                 "Sign in to keep them once saving is switched on.",
        "session": "Your School Learning progress is kept for this visit only. Saving School Learning progress to your account "
                   "is not switched on yet.",
        "saved": "Your School Learning progress is saved to your account (separately from quiz points and rewards).",
        "error": "We could not reach your saved School Learning progress just now. Your progress in this visit is kept and we will try again.",
    }[mode]
    html(f'<p class="sl-store sl-store-{mode}">{escape(text)}</p>')


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
        out += _chip("↻ Revise", "warn")
    return out


# --------------------------------------------------------------------------- home

def _home() -> None:
    subject_id = SS.school_subject
    prog = progress(subject_id)
    html('<div class="sl-intro"><h2>School Learning</h2>'
         '<p>Study notes, diagrams and practice for Nigerian senior secondary school (SSS) students, organised by the WAEC '
         f'Geography syllabus.</p><div class="sl-intro-meta">{_review_badge()}{_chip("English")}{_chip("No account needed to read")}</div></div>')
    if prog:
        target = school.continue_target(subject_id, prog)
        d = school.lesson(subject_id, target)
        rec = prog.get(target) or {}
        total = len(school.pages(d))
        with st.container(key="sl_continue"):
            html(f'<div class="sl-continue"><div class="sl-kicker">Continue learning</div>'
                 f'<div class="sl-continue-title">Lesson {d["number"]}: {escape(d["title"])}</div>'
                 f'<div class="sl-muted">Page {rec.get("page", 0) + 1} of {total} · {school.reading_percent(rec, total)}% read</div>'
                 f'{_bar(school.reading_percent(rec, total), "Reading progress")}</div>')
            st.button("Continue reading", key="sl_continue_btn", type="primary", icon=":material/menu_book:",
                      on_click=go, args=("lesson", target))
    html('<h3 class="sl-h">Subjects</h3>')
    with st.container(key="sl_subjects", horizontal=True):
        for s in school.subjects():
            with st.container(key=f"sl_subject_{s['id']}"):
                if s.get("status") == "available":
                    count = len(school.lesson_ids(s["id"]))
                    meta = f'{count} full lessons · {school.topic_count(s["id"])} syllabus topics mapped'
                    html(f'<div class="sl-subject" style="--subject:{escape(s.get("colour", "#1F5F7A"))}">'
                         f'<div class="sl-subject-icon" aria-hidden="true">{ICONS.get(s.get("icon"), "📘")}</div>'
                         f'<div class="sl-subject-name">{escape(s["title"])}</div><div class="sl-muted">{escape(s.get("level", ""))}</div>'
                         f'<p>{escape(s.get("summary", ""))}</p><div class="sl-muted">{escape(meta)}</div></div>')
                    st.button(f"Open {s['title']}", key=f"sl_open_{s['id']}", type="primary", width="stretch",
                              on_click=open_subject, args=(s["id"],))
                else:
                    html(f'<div class="sl-subject sl-subject-soon"><div class="sl-subject-icon" aria-hidden="true">{ICONS.get(s.get("icon"), "📘")}</div>'
                         f'<div class="sl-subject-name">{escape(s["title"])}</div><div class="sl-muted">{escape(s.get("level", ""))}</div>'
                         f'<p>{escape(s.get("summary", ""))}</p>{_chip("Coming later")}</div>')
    o = school.overview(subject_id, prog)
    with st.container(key="sl_home_progress"):
        _overview_tiles(o)
        st.button("View my progress", key="sl_home_progress_btn", icon=":material/insights:", on_click=go, args=("progress",))
    html(f'<p class="sl-disclaimer">🎓 {escape(NOT_REWARDS)}</p>')


def _overview_tiles(o: dict) -> None:
    avg = f'{o["average"]}%' if o["average"] is not None else "—"
    tiles = [("Lessons completed", f'{o["completed"]} / {o["lessons"]}'), ("In progress", str(o["in_progress"])),
             ("To revise", str(o["revise"])), ("Average best practice score", avg)]
    html('<div class="sl-tiles">' + "".join(f'<div class="sl-tile"><div class="sl-tile-v">{escape(v)}</div>'
                                            f'<div class="sl-tile-l">{escape(k)}</div></div>' for k, v in tiles) + "</div>")


# --------------------------------------------------------------------------- topics (one subject)

def _topics() -> None:
    subject_id = SS.school_subject
    s, cur, prog = school.subject(subject_id), school.curriculum(subject_id), progress(subject_id)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_back_home", icon=":material/arrow_back:", on_click=go, args=("home",))
        st.button("My progress", key="sl_topics_progress", icon=":material/insights:", on_click=go, args=("progress",))
    html(f'<div class="sl-intro"><div class="sl-kicker">{escape(s.get("level", ""))}</div><h2>{escape(s["title"])}: Regional Geography of Nigeria</h2>'
         f'<p>Seven full lessons cover the WAEC regional geography of Nigeria. Each has notes, diagrams, key definitions, worked examples, '
         f'exam tips, quick checks, a summary, exam-style questions and 10 practice questions.</p>'
         f'<div class="sl-intro-meta">{_review_badge()}</div></div>')
    for lesson_id in school.lesson_ids(subject_id):
        d = school.lesson(subject_id, lesson_id)
        rec = prog.get(lesson_id)
        total = len(school.pages(d))
        pct = school.reading_percent(rec, total)
        best = f'Best practice score {rec["best"]}/{school.PRACTICE_SIZE}' if rec and rec.get("attempts") else "Not practised yet"
        reasons = school.revision_reasons(rec)
        with st.container(key=f"sl_lesson_card_{lesson_id}"):
            html(f'<div class="sl-card-head"><span class="sl-num">{d["number"]}</span><div><div class="sl-card-title">{escape(d["title"])}</div>'
                 f'<div class="sl-muted">{escape(d.get("short", ""))}</div></div></div>'
                 f'<div class="sl-card-meta">{_status_chips(rec)}<span class="sl-muted">About {d.get("minutes", 30)} min · {total} pages</span></div>'
                 f'{_bar(pct, "Reading progress")}<div class="sl-card-foot"><span>{pct}% read</span><span>{escape(best)}</span></div>'
                 + (f'<div class="sl-why">↻ {escape("; ".join(reasons))}</div>' if reasons else ""))
            with st.container(key=f"sl_card_actions_{lesson_id}", horizontal=True):
                label = "Start lesson" if not rec else ("Read again" if rec.get("completed") else "Continue")
                st.button(label, key=f"sl_read_{lesson_id}", type="primary", icon=":material/menu_book:",
                          on_click=go, args=("lesson", lesson_id, 0 if rec and rec.get("completed") else None))
                st.button("Practise 10 questions", key=f"sl_practise_{lesson_id}", icon=":material/edit_note:",
                          on_click=go, args=("practice", lesson_id))
    html('<h3 class="sl-h">The full syllabus</h3>')
    st.caption(cur["status_note"])
    for sec in cur["sections"]:
        done = sum(1 for tpc in sec["topics"] if tpc.get("lesson"))
        with st.expander(f'{sec["title"]} · {done} of {len(sec["topics"])} topics with lessons', key=f"sl_syllabus_{sec['id']}"):
            html(f'<p class="sl-muted">{escape(sec.get("waec", ""))}</p><ul class="sl-syllabus">' + "".join(
                f'<li>{escape(tpc["title"])} {_chip("Lesson available", "ok") if tpc.get("lesson") else _chip("Coming later")}</li>'
                for tpc in sec["topics"]) + "</ul>")
    with st.expander("Topics not examined for Nigerian candidates", key="sl_not_nigeria"):
        html('<ul class="sl-syllabus">' + "".join(f"<li>{escape(n)}</li>" for n in cur.get("not_for_nigeria", [])) + "</ul>")


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
        if photo:   # the app's licensed photo (author and licence shown); collapses to the caption if it cannot load
            credit = (f'Photo: {escape(photo["author"])} · <a href="{escape(photo["license_url"], quote=True)}" target="_blank" '
                      f'rel="noopener">{escape(photo["license"])}</a>')
            html(f'<figure class="sl-photo"><img src="{escape(photo["url"], quote=True)}" alt="" '
                 f'loading="lazy" decoding="async"><figcaption><b>{escape(b.get("caption") or photo["caption"])}</b>'
                 f'<span class="sl-credit">{credit}</span></figcaption></figure>')
    elif kind == "note":
        html(f'<div class="sl-note">💡 {_rich(b["text"])}</div>')


def _page_body(subject_id: str, d: dict, page: dict) -> None:
    kind = page["kind"]
    html(f'<h3 class="sl-page-title">{escape(page["title"])}</h3>')
    if kind == "intro":
        for p in d["intro"]:
            html(f'<p class="sl-p">{_rich(p)}</p>')
        html('<div class="sl-box"><div class="sl-box-t">By the end of this lesson you should be able to:</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(o)}</li>" for o in d["objectives"]) + "</ul></div>")
        html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">Where this fits in the syllabus</div><ul class="sl-list">'
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
        html('<div class="sl-box sl-box-gold"><div class="sl-box-t">Exam tips</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(x)}</li>" for x in d["exam_tips"]) + "</ul></div>")
    elif kind == "check":
        st.caption("Try to answer each question yourself first, then open it to check.")
        for i, c in enumerate(d["checks"], 1):
            with st.expander(f"{i}. {_plain(c['q'])}", key=f"sl_check_{d['id']}_{i}"):
                html(f'<p class="sl-p">{_rich(c["a"])}</p>')
    elif kind == "review":
        html('<div class="sl-box"><div class="sl-box-t">Summary</div><ul class="sl-list">'
             + "".join(f"<li>{_rich(x)}</li>" for x in d["summary"]) + "</ul></div>")
        html('<h4 class="sl-h4">Exam-style questions</h4>')
        for i, q in enumerate(d["structured"], 1):
            html(f'<div class="sl-structured"><p class="sl-p"><b>Question {i}</b> ({q["marks"]} marks). {_rich(q["q"])}</p></div>')
            with st.expander("Show a model answer and marking points", key=f"sl_model_{d['id']}_{i}"):
                html("".join(f'<p class="sl-p">{_rich(m)}</p>' for m in q["model"])
                     + '<div class="sl-box-t">Marking points</div><ul class="sl-list">'
                     + "".join(f"<li>{_rich(p)}</li>" for p in q["points"]) + "</ul>")
        html('<h4 class="sl-h4">References</h4><ul class="sl-refs">' + "".join(
            f'<li><a href="{escape(r["url"], quote=True)}" target="_blank" rel="noopener">{escape(r["title"])}</a></li>'
            for r in d["references"]) + "</ul>")


def _lesson() -> None:
    subject_id, lesson_id = SS.school_subject, SS.school_lesson
    if lesson_id not in school.lesson_ids(subject_id):
        SS.school_view = "topics"
        _topics()
        return
    d = school.lesson(subject_id, lesson_id)
    pages = school.pages(d)
    total = len(pages)
    rec = progress(subject_id).get(lesson_id) or school.move_to(None, 0, total)
    here = rec.get("page", 0)
    pct = school.reading_percent(rec, total)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("All topics", key="sl_back_topics", icon=":material/arrow_back:", on_click=go, args=("topics",))
        st.button("My progress", key="sl_lesson_progress", icon=":material/insights:", on_click=go, args=("progress",))
    with st.container(key="sl_reader_head"):
        html(f'<div class="sl-kicker">Lesson {d["number"]} of {len(school.lesson_ids(subject_id))} · SSS Geography</div>'
             f'<h2 class="sl-lesson-title">{escape(d["title"])}</h2>'
             f'<div class="sl-card-meta">{_status_chips(rec)}{_review_badge()}</div>'
             f'<div class="sl-readline"><span>Page {here + 1} of {total}</span><span>{pct}% read</span></div>{_bar(pct, "Reading progress")}')
    side, main = st.columns([1, 3], gap="medium")
    with side, st.container(key="sl_contents"):
        html('<div class="sl-box-t">Contents</div>')
        for i, p in enumerate(pages):
            seen = i <= rec.get("furthest", 0)
            st.button(("● " if i == here else ("✓ " if seen else "○ ")) + p["title"], key=f"sl_toc_{i}",
                      type="primary" if i == here else "secondary", width="stretch",
                      on_click=go, args=("lesson", None, i))
    with main, st.container(key="sl_reader"):
        jump_key = f"sl_jump_{lesson_id}"
        SS[jump_key] = here
        with st.container(key="sl_jump_box"):
            st.selectbox("Jump to part of the lesson", list(range(total)), key=jump_key,
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
                st.button("Practise 10 questions", key="sl_practise_end", type="primary", icon=":material/edit_note:",
                          on_click=go, args=("practice",))
        with st.container(key="sl_lesson_actions"):
            done = bool(rec.get("completed"))
            ready = school.can_complete(rec, total)
            with st.container(key="sl_status_row", horizontal=True, vertical_alignment="center"):
                if done:
                    st.button("Completed · mark as not complete", key="sl_uncomplete", icon=":material/check_circle:",
                              on_click=_complete, args=(False,))
                else:
                    st.button("Mark lesson complete", key="sl_complete", icon=":material/task_alt:", disabled=not ready,
                              type="primary" if ready else "secondary", on_click=_complete, args=(True,))
                on = bool(rec.get("revision"))
                st.button("Remove from revision list" if on else "Add to revision list", key="sl_revision",
                          icon=":material/bookmark_remove:" if on else ":material/bookmark_add:", on_click=_revision, args=(not on,))
            if not done and not ready:
                st.caption("Reach the last page to mark this lesson complete. Completion records that you have read it; "
                           "your revision list is separate.")
            reasons = school.revision_reasons(rec)
            if reasons:
                html(f'<div class="sl-why">↻ Revise: {escape("; ".join(reasons))}</div>')
        before, after = school.neighbours(subject_id, lesson_id)
        with st.container(key="sl_lesson_nav", horizontal=True):
            prev_title = f"Lesson {school.lesson(subject_id, before)['number']}" if before else "Previous lesson"
            next_title = f"Lesson {school.lesson(subject_id, after)['number']}" if after else "Next lesson"
            st.button(f"Previous lesson · {prev_title}" if before else "Previous lesson", key="sl_prev_lesson",
                      icon=":material/skip_previous:", disabled=not before, on_click=go, args=("lesson", before))
            st.button(f"Next lesson · {next_title}" if after else "Next lesson", key="sl_next_lesson",
                      icon=":material/skip_next:", icon_position="right", disabled=not after, on_click=go, args=("lesson", after))
    _scroll_to(".st-key-sl_reader_head")


# --------------------------------------------------------------------------- practice

def _practice() -> None:
    subject_id = SS.school_subject
    session = SS.get("school_practice")
    if not session or session["lesson"] not in school.lesson_ids(subject_id):
        SS.school_view = "topics"
        _topics()
        return
    d = school.lesson(subject_id, session["lesson"])
    token = session["token"]
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("Back to lesson", key="sl_practice_back", icon=":material/arrow_back:", on_click=go, args=("lesson", d["id"]))
        st.button("All topics", key="sl_practice_topics", icon=":material/list:", on_click=go, args=("topics",))
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
        html(f'<div class="sl-readline"><span>Question {index + 1} of {len(session["items"])}</span>'
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
                 f'<p class="feedback-explain">{_rich(q["explanation"])}</p></div>')
            with st.container(key="sl_feedback_actions", horizontal=True):
                last = index + 1 == len(session["items"])
                st.button("See my score" if last else "Next question", key=f"sl_next_{token}_{index}", type="primary",
                          icon=":material/arrow_forward:", icon_position="right", on_click=_next, args=(token, index))
                if section:
                    page = next(i for i, p in enumerate(school.pages(d)) if p["id"] == section["id"])
                    st.button(f"Revise: {section['title']}", key=f"sl_revise_{token}_{index}", icon=":material/menu_book:",
                              on_click=go, args=("lesson", d["id"], page))
    _scroll_to(".st-key-sl_question_card")


def _practice_result(subject_id: str, d: dict, session: dict) -> None:
    mark, total = school.score(session), len(session["items"])
    rec = progress(subject_id).get(d["id"]) or {}
    good = mark >= school.REVISE_BELOW * total
    with st.container(key="sl_result"):
        html(f'<div class="sl-result {"sl-result-good" if good else "sl-result-revise"}"><div class="sl-result-score">{mark}<small>/{total}</small></div>'
             f'<div><div class="sl-card-title">{"Well done!" if good else "Keep going: revise and try again."}</div>'
             f'<div class="sl-muted">Best score for this lesson: {rec.get("best", mark)}/{total} · practice sessions: {rec.get("attempts", 1)}</div>'
             + ("" if good else '<div class="sl-why">↻ This lesson has been suggested for revision (best score below 6/10).</div>')
             + "</div></div>")
        missed = []
        for a in session["answers"]:
            q = school.question(d, a["id"])
            missed.append(f'<li class="{"ok" if a["correct"] else "bad"}"><span aria-hidden="true">{"✓" if a["correct"] else "✕"}</span> '
                          f'{escape(q["q"])}<br><small>{"Correct" if a["correct"] else "Correct answer: " + escape(q["options"][q["answer"]])}</small></li>')
        html('<div class="sl-box-t">Your answers</div><ul class="sl-answers-review">' + "".join(missed) + "</ul>")
        with st.container(key="sl_result_actions", horizontal=True):
            st.button("Try 10 new questions", key="sl_again", type="primary", icon=":material/refresh:", on_click=go, args=("practice", d["id"]))
            st.button("Back to lesson", key="sl_result_lesson", icon=":material/menu_book:", on_click=go, args=("lesson", d["id"]))
            st.button("My progress", key="sl_result_progress", icon=":material/insights:", on_click=go, args=("progress",))
    _storage_note()


# --------------------------------------------------------------------------- progress dashboard

def _progress() -> None:
    subject_id = SS.school_subject
    prog = progress(subject_id)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_progress_home", icon=":material/arrow_back:", on_click=go, args=("home",))
        st.button("All topics", key="sl_progress_topics", icon=":material/list:", on_click=go, args=("topics",))
    html(f'<div class="sl-intro"><h2>My School Learning progress</h2><p>{escape(school.subject(subject_id)["title"])}. '
         'Reading status shows how far you have read; the revision list is separate, so a completed lesson can still be on it.</p></div>')
    _overview_tiles(school.overview(subject_id, prog))
    rows = []
    for lesson_id in school.lesson_ids(subject_id):
        d = school.lesson(subject_id, lesson_id)
        rec = prog.get(lesson_id)
        total = len(school.pages(d))
        best = f'{rec["best"]}/{school.PRACTICE_SIZE} ({rec["attempts"]}×)' if rec and rec.get("attempts") else "—"
        reasons = "; ".join(school.revision_reasons(rec)) or "—"
        rows.append(f'<tr><th scope="row">{d["number"]}. {escape(d["title"])}</th><td>{_status_chips(rec)}</td>'
                    f'<td>{school.reading_percent(rec, total)}%</td><td>{escape(best)}</td><td>{escape(reasons)}</td></tr>')
    html('<div class="sl-table-wrap" tabindex="0"><table class="sl-table sl-progress-table"><thead><tr><th scope="col">Lesson</th>'
         '<th scope="col">Status</th><th scope="col">Read</th><th scope="col">Best practice</th><th scope="col">Revision</th></tr></thead>'
         f'<tbody>{"".join(rows)}</tbody></table></div>')
    target = school.continue_target(subject_id, prog)
    st.button(f"Continue learning · Lesson {school.lesson(subject_id, target)['number']}", key="sl_progress_continue",
              type="primary", icon=":material/menu_book:", on_click=go, args=("lesson", target))
    _storage_note()
    html(f'<p class="sl-disclaimer">🎓 {escape(NOT_REWARDS)}</p>')


# --------------------------------------------------------------------------- entry point

VIEWS = {"home": _home, "topics": _topics, "lesson": _lesson, "practice": _practice, "progress": _progress}


def render() -> None:
    _defaults()
    if not school.subject(SS.school_subject) or school.subject(SS.school_subject).get("status") != "available":
        SS.school_subject = next(s["id"] for s in school.subjects() if s.get("status") == "available")
    _restore(SS.school_subject)
    with st.container(key=f"school_{SS.school_view if SS.school_view in VIEWS else 'home'}"):
        VIEWS.get(SS.school_view, _home)()
        if SS.school_view in ("home", "topics", "lesson"):
            _storage_note()
