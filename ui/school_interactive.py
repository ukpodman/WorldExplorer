"""School Learning — interactive subjects (Nigerian History; Citizenship and Heritage Studies).

ui/school.py routes here when a subject's subjects.json entry has "engine": "interactive". Everything below is driven by
the curriculum and lesson files read through core/lessons.py and core/assess.py: class → term → topic → lesson, the
lesson's pages (parts A–K), its activities and its knowledge check. Adding a lesson needs no change here.

Progress uses the same per-lesson records, the same account table and the same device cookie as Geography (ui/school.py),
so no database change is needed. School Learning is study only: nothing here calls the rewards hooks, points, badges,
the quiz engine or Friends & Family 10 activity.

Accessibility: every interaction is a button, radio, select box or text field (no drag and drop: ordering uses
"Move up" / "Move down"); read-aloud uses the browser's own speech synthesis, starts only when the student presses
Listen, and can be paused, resumed, restarted and stopped from the keyboard.
"""
from __future__ import annotations

import json
import random
import time
from html import escape

import streamlit as st

from core import assess, lessons, school, school_store

from . import school as base
from .components import html

SS = st.session_state
TERM_TITLES = {"first": "First Term", "second": "Second Term", "third": "Third Term", "unassigned": "Term not confirmed"}
KIND_ICONS = {"person": "👤", "place": "📍", "event": "📅", "institution": "🏛️", "object": "🏺"}
EVIDENCE_ICONS = {"oral": "🗣️", "archaeological": "⛏️", "written": "📜", "art": "🎨", "interpretation": "📖"}
EVIDENCE_TITLES = {"oral": "Oral tradition", "archaeological": "Archaeology", "written": "Written source", "art": "Art and artefact",
                   "interpretation": "Later interpretation"}
VERDICT_TITLES = {"best": "Best response", "acceptable": "Acceptable, but not the best", "poor": "Poor response"}


# --------------------------------------------------------------------------- small helpers

def _subject() -> str:
    return SS.school_subject


def _d(lesson_id: str) -> dict:
    return school.lesson(_subject(), lesson_id)


def _basis_chip(item: dict) -> str:
    b = item.get("basis")
    if not b:
        return ""
    tone = {"fact": "ok", "tradition": "warn", "interpretation": "teal", "disputed": "warn", "approximate": "teal"}[b]
    return base._chip(lessons.BASIS[b], tone)


def _src_refs(d: dict, item: dict) -> str:
    """Numbered references to the lesson's source list (on the last page), e.g. [2][5]."""
    ids = [s["id"] for s in d["sources"]]
    refs = [(ids.index(s) + 1, d["sources"][ids.index(s)]["title"]) for s in item.get("src", []) if s in ids]
    if not refs:
        return ""
    return '<span class="sx-refs">Source ' + "".join(
        f'<abbr title="{escape(t, quote=True)}">[{n}]</abbr>' for n, t in refs) + "</span>"


def _meta(d: dict, item: dict) -> str:
    out = _basis_chip(item) + _src_refs(d, item)
    return f'<div class="sx-meta">{out}</div>' if out else ""


def _figure_svg(subject_id: str, name: str) -> str:
    return " ".join(lessons.figure(subject_id, name).split())


def _class_title(subject_id: str, class_id: str) -> str:
    c = lessons.class_(subject_id, class_id)
    return c["title"] if c else class_id


def _status_for(d: dict) -> str:
    if lessons.finished(d):
        return base._chip("✓ Reviewed", "ok")
    return base._review_badge() + base._chip("Draft", "warn")


# --------------------------------------------------------------------------- subject card (home)

def card_numbers(subject_id: str, prog: dict) -> dict:
    """What the home card shows: classes with lessons, lessons by review status, curriculum topics, progress."""
    c = lessons.counts(subject_id)
    p = lessons.progress_by(subject_id, prog)
    return {**c, **{"completed": p["completed"], "started": p["started"], "percent": p["percent"]}}


def subject_card(s: dict, prog: dict) -> None:
    n = card_numbers(s["id"], prog)
    icon = base.ICONS.get(s.get("icon"), "📘")
    lessons_txt = f'{n["lessons"]} lesson{"s" if n["lessons"] != 1 else ""}'
    status = (f'{n["reviewed"]} reviewed · {n["draft"]} draft (educational review pending)' if n["draft"]
              else f'{n["reviewed"]} reviewed')
    html(f'<div class="sl-subject" style="--subject:{escape(s.get("colour", "#1F5F7A"))}">'
         f'<div class="sl-subject-top"><span class="sl-subject-icon" aria-hidden="true">{icon}</span>'
         f'<div><div class="sl-subject-name">{escape(s["title"])}</div><div class="sl-muted">{escape(s.get("level", ""))}</div></div></div>'
         f'<p>{escape(s.get("summary", ""))}</p>'
         f'<div class="sx-card-facts"><div><b>{escape(lessons_txt)}</b><span>{escape(status)}</span></div>'
         f'<div><b>{n["topics"]} topics</b><span>listed from published schemes of work</span></div></div>'
         f'<div class="sl-card-meta">{"".join(base._chip(x, "level") for x in n["classes"]) or base._chip("No lessons yet")}</div>'
         f'{base._bar(n["percent"], s["title"] + " progress")}'
         f'<div class="sl-card-foot"><span>{n["completed"]} of {n["lessons"]} completed</span><span>{n["started"]} started</span></div></div>')


# --------------------------------------------------------------------------- subject page: class → term → topics

def _default_class(subject_id: str, prog: dict) -> str:
    nxt = lessons.suggested_next(subject_id, prog) if prog else None
    if nxt:
        return lessons.class_id_of(subject_id, _d(nxt)["class"]) or lessons.classes(subject_id)[0]["id"]
    with_lessons = lessons.classes_with_lessons(subject_id)
    return (with_lessons or lessons.classes(subject_id))[0]["id"]


def _pick_class(subject_id: str) -> None:
    SS[f"sx_class_{subject_id}_saved"] = SS.get(f"sx_class_{subject_id}")
    SS.pop(f"sx_term_{subject_id}", None)
    SS.pop(f"sx_term_{subject_id}_saved", None)


def _keep(key: str) -> None:
    SS[key + "_saved"] = SS.get(key)


def topics_view() -> None:
    subject_id = _subject()
    s, cur, prog = school.subject(subject_id), lessons.curriculum(subject_id), base.progress(subject_id)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_back_home", icon=":material/arrow_back:", on_click=base.go, args=("home",))
        st.button("My progress", key="sl_topics_progress", icon=":material/insights:", on_click=base.go, args=("progress",))
    base._guest_offer_box()
    n = lessons.counts(subject_id)
    html(f'<div class="sl-intro"><div class="sl-kicker">{escape(s.get("level", ""))}</div><h2>{escape(s["title"])}</h2>'
         f'<p>{escape(cur["note"])}</p>'
         f'<div class="sl-intro-meta">{base._review_badge()}{base._chip(str(n["lessons"]) + " lessons so far")}'
         f'{base._chip(str(n["topics"]) + " topics listed")}</div></div>')
    if prog and lessons.lesson_ids(subject_id):
        base._continue_card(subject_id, prog, "sl_continue_btn")
    classes = lessons.classes(subject_id)
    ids = [c["id"] for c in classes]
    with_lessons = {c["id"] for c in lessons.classes_with_lessons(subject_id)}
    ckey, tkey = f"sx_class_{subject_id}", f"sx_term_{subject_id}"
    base._restore_widget(ckey, _default_class(subject_id, prog), ids)
    with st.container(key="sx_class_box"):
        html('<h3 class="sl-h">1. Choose your class</h3>')
        class_id = st.pills("Class", ids, key=ckey, required=True, label_visibility="collapsed",
                            format_func=lambda i: _class_title(subject_id, i) + (" ●" if i in with_lessons else ""),
                            on_change=_pick_class, args=(subject_id,))
        st.caption("● = has lessons. Every class shows the topics listed so far, so you can see what is coming.")
    cl = lessons.class_(subject_id, class_id or ids[0])
    terms = [t["id"] for t in cl["terms"]]
    if not terms:
        html(f'<div class="sl-note">{escape(cl.get("note") or "Topics for this class have not been added yet.")}</div>')
        return
    first_with = next((t["id"] for t in cl["terms"] if any(tp.get("lessons") for tp in t["topics"])), terms[0])
    base._restore_widget(tkey, first_with, terms)
    with st.container(key="sx_term_box"):
        html('<h3 class="sl-h">2. Choose a term</h3>')
        term_id = st.segmented_control("Term", terms, key=tkey, required=True, label_visibility="collapsed",
                                       format_func=lambda t: TERM_TITLES.get(t, t), on_change=_keep, args=(tkey,))
    term = next(t for t in cl["terms"] if t["id"] == (term_id or terms[0]))
    p = lessons.progress_by(subject_id, prog, cl["id"], term["id"])
    html(f'<div class="sx-term-head"><h3 class="sl-h">3. Topics · {escape(cl["title"])}, {escape(TERM_TITLES.get(term["id"], ""))}</h3>'
         f'<div class="sl-muted">{len(term["topics"])} topics · {p["lessons"]} with lessons · {p["completed"]} completed</div>'
         f'{base._bar(p["percent"], "Term progress")}</div>')
    if term["id"] == "unassigned":
        st.caption("The published schemes we checked do not divide this class's topics into terms the same way, so the "
                   "term is not shown. Follow your school's scheme of work.")
    if not term["topics"]:
        html('<div class="sl-note">No topics have been listed for this term yet.</div>')
        return
    shown_lessons: set[str] = set()
    for i, tp in enumerate(term["topics"], 1):
        ready = [lid for lid in tp.get("lessons", []) if lid in lessons.lesson_ids(subject_id)]
        verified = lessons.VERIFICATION[tp["verification"]]
        with st.container(key=f"sx_topic_{tp['id']}"):
            html(f'<div class="sx-topic"><span class="sx-topic-n">{i}</span><div><div class="sl-card-title">{escape(tp["title"])}</div>'
                 f'<div class="sl-muted" title="{escape(verified, quote=True)}">{escape(verified)}</div></div></div>')
            if not ready:
                html('<div class="sx-soon">Lesson not written yet</div>')
            for lid in ready:
                if lid in shown_lessons:
                    html(f'<div class="sx-soon">Covered in the lesson “{escape(_d(lid)["title"])}” above</div>')
                    continue
                shown_lessons.add(lid)
                lesson_card(subject_id, lid, prog.get(lid))


def lesson_card(subject_id: str, lesson_id: str, rec: dict | None) -> None:
    d = _d(lesson_id)
    total = len(school.pages(d))
    pct = school.reading_percent(rec, total)
    best = f'Best knowledge-check score {rec["best"]}/10' if rec and rec.get("attempts") else "Knowledge check not taken yet"
    acts = ", ".join(sorted({a["type"] for a in d["activities"]}))
    with st.container(key=f"sl_lesson_card_{lesson_id}"):
        html(f'<div class="sl-card-head"><span class="sl-num">{escape(str(d.get("number", "•")))}</span><div>'
             f'<div class="sl-card-title">{escape(d["title"])}</div>'
             f'<div class="sl-card-meta">{base._chip(d["class"], "level")}<span class="sl-muted">About {d["minutes"]} min · {total} pages · '
             f'{len(d["activities"])} activities ({escape(acts)}) · {len(d["assessment"])} check questions</span></div></div></div>'
             f'<div class="sl-card-meta">{base._status_chips(rec)}{_status_for(d)}'
             + (base._chip("Updated since you read it", "teal") if school.updated_since(rec, d) else "")
             + f'</div>{base._bar(pct, "Reading progress")}<div class="sl-card-foot"><span>{pct}% read</span><span>{escape(best)}</span></div>')
        with st.container(key=f"sl_card_actions_{lesson_id}", horizontal=True):
            label = "Start lesson" if not rec else ("Read again" if rec.get("completed") else "Continue")
            st.button(label, key=f"sl_read_{lesson_id}", type="primary", icon=":material/menu_book:",
                      on_click=base.go, args=("lesson", lesson_id, 0 if rec and rec.get("completed") else None))
            st.button("Knowledge check", key=f"sl_practise_{lesson_id}", icon=":material/quiz:",
                      on_click=base.go, args=("practice", lesson_id))


# --------------------------------------------------------------------------- read-aloud

def read_aloud(page_id: str, text: str) -> None:
    """Listen / Pause / Resume / Restart / Stop with the browser's speech synthesis. Nothing plays until Listen is
    pressed; changing page stops speech that was started on another page. (No '<' in the script: the HTML cleaner
    drops it.)"""
    box = "sxra-" + "".join(ch for ch in page_id if ch.isalnum() or ch == "-")
    buttons = "".join(f'<button type="button" class="sx-ra-btn" data-a="{a}">{label}</button>'
                      for a, label in (("play", "▶ Listen"), ("pause", "⏸ Pause"), ("resume", "⏵ Resume"),
                                       ("restart", "↺ Restart"), ("stop", "■ Stop")))
    script = ("<script>/*" + str(time.time_ns()) + "*/(function(){const id='" + box + "';const go=function(){const b=document.getElementById(id);"
              "if(!b){return setTimeout(go,60);}if(b.dataset.ready){return;}b.dataset.ready='1';const out=b.querySelector('.sx-ra-state');"
              "const s=window.speechSynthesis;if(!s||!window.SpeechSynthesisUtterance){out.textContent='Read-aloud is not available in this browser.';"
              "b.querySelectorAll('button').forEach(function(x){x.disabled=true;});return;}"
              "if(window.__weReadAloud&&window.__weReadAloud!==id){s.cancel();}"
              "const text=JSON.parse(b.dataset.text);const say=function(){s.cancel();const u=new SpeechSynthesisUtterance(text);u.lang='en-GB';u.rate=0.95;"
              "u.onend=function(){out.textContent='Finished.';};window.__weReadAloud=id;s.speak(u);out.textContent='Reading…';};"
              "const act={play:say,restart:say,pause:function(){s.pause();out.textContent='Paused.';},"
              "resume:function(){s.resume();out.textContent='Reading…';},stop:function(){s.cancel();out.textContent='Stopped.';}};"
              "b.querySelectorAll('button').forEach(function(x){x.addEventListener('click',function(){act[x.dataset.a]();});});};go();})();</script>")
    st.html(f'<div class="sx-ra" id="{box}" data-text="{escape(json.dumps(text), quote=True)}" role="group" aria-label="Read this page aloud">'
            f'{buttons}<span class="sx-ra-state" aria-live="polite">Not playing.</span></div>' + script, unsafe_allow_javascript=True)


# --------------------------------------------------------------------------- content blocks

def block(subject_id: str, d: dict, b: dict) -> None:
    kind = b["type"]
    meta = _meta(d, b)
    if kind == "p":
        html(f'<p class="sl-p">{base._rich(b["text"])}</p>{meta}')
    elif kind == "h":
        html(f'<h4 class="sl-h4">{base._rich(b["text"])}</h4>')
    elif kind == "list":
        html('<ul class="sl-list">' + "".join(f"<li>{base._rich(i)}</li>" for i in b["items"]) + f"</ul>{meta}")
    elif kind == "cards":
        html('<div class="sl-cards">' + "".join(
            f'<div class="sl-infocard sl-tone-{escape(i.get("tone") or "plain")}"><div class="sl-infocard-t">{base._rich(i["title"])}</div>'
            f'<div>{base._rich(i["text"])}</div>{_meta(d, i)}</div>' for i in b["items"]) + "</div>")
    elif kind == "table":
        head = "".join(f'<th scope="col">{base._rich(h)}</th>' for h in b["head"])
        rows = "".join("<tr>" + "".join(f"<td>{base._rich(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
        html(f'<div class="sl-table-wrap" tabindex="0"><table class="sl-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>{meta}')
    elif kind == "figure":
        html(f'<figure class="sl-fig">{_figure_svg(subject_id, b["figure"])}<figcaption><b>{base._rich(b["caption"])}</b>'
             f'<span class="sl-credit">{escape(b.get("credit", ""))}</span></figcaption></figure>')
    elif kind == "note":
        html(f'<div class="sl-note">💡 {base._rich(b["text"])}</div>')
    elif kind == "quote_source":
        html(f'<div class="sx-source sx-ev-{escape(b["kind"])}"><div class="sx-source-k">{EVIDENCE_ICONS[b["kind"]]} '
             f'{escape(EVIDENCE_TITLES[b["kind"]])}</div><p class="sl-p">{base._rich(b["text"])}</p>'
             f'<div class="sx-prov"><b>Where it comes from:</b> {base._rich(b["provenance"])}</div>{meta}</div>')


# --------------------------------------------------------------------------- questions (shared by activities and the knowledge check)

def _qstate() -> dict:
    return SS.setdefault("sx_answers", {})


def _response(q: dict, k: str):
    """The student's response from the widgets, or None when nothing has been chosen yet."""
    kind = q["type"]
    if kind in ("mcq", "map", "image", "scenario"):
        return SS.get(k + "_r")
    if kind == "truefalse":
        v = SS.get(k + "_r")
        return None if v is None else v == "True"
    if kind in ("fill", "short"):
        v = (SS.get(k + "_t") or "").strip()
        return v or None
    if kind == "match":
        given = {left: SS.get(f"{k}_m{i}") for i, (left, _) in enumerate(q["pairs"])}
        return given if all(given.values()) else None
    if kind == "order":
        return list(SS.get(k + "_order") or [])
    return None


def _check(subject_id: str, lesson_id: str, qid: str, k: str, check_index: int | None = None) -> None:
    d = school.lesson(subject_id, lesson_id)
    q = lessons.question(d, qid)
    response = _response(q, k)
    if response is None:
        SS[k + "_empty"] = True
        return
    SS.pop(k + "_empty", None)
    if check_index is not None:
        session = SS.get("sx_checks", {}).get(lesson_id)
        if not session or session.get("key") != k.rsplit("_", 1)[0]:
            return
        result = assess.answer(session, q, check_index, response)
        if result is None:
            return
        session.setdefault("feedback", {})[str(check_index)] = {"correct": result.correct, "explanation": result.explanation,
                                                               "detail": [list(x) for x in result.detail], "marked": result.marked,
                                                               "response": response if q["type"] != "match" else None}
    else:
        result = assess.check(q, response)
    _qstate()[k] = {"correct": result.correct, "explanation": result.explanation, "detail": [list(x) for x in result.detail],
                    "marked": result.marked, "response": response if q["type"] in ("mcq", "map", "image", "scenario", "truefalse") else None}


def _reset(k: str) -> None:
    _qstate().pop(k, None)
    for key in [x for x in list(SS.keys()) if isinstance(x, str) and (x == k + "_r" or x == k + "_t" or x.startswith(k + "_m")
                                                                       or x == k + "_order" or x.startswith(k + "_self"))]:
        SS.pop(key, None)
    SS.pop(k + "_empty", None)


def _move(k: str, i: int, delta: int) -> None:
    order = list(SS.get(k + "_order") or [])
    j = i + delta
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
        SS[k + "_order"] = order


def question(subject_id: str, d: dict, q: dict, k: str, check_index: int | None = None, retry: bool = True) -> dict | None:
    """Render one question with its answer controls and, once answered, its feedback. Returns the stored result."""
    kind = q["type"]
    done = _qstate().get(k)
    lock = done is not None
    with st.container(key=f"sxq_{k}"):
        if kind in ("map", "image"):
            html(f'<figure class="sl-fig sx-qfig">{_figure_svg(subject_id, q["figure"])}'
                 + (f'<figcaption><span class="sl-credit">{escape(q["alt"])}</span></figcaption>' if q.get("alt") else "") + "</figure>")
        prompt = {"truefalse": q.get("statement"), "fill": q.get("text"), "scenario": q.get("situation"), "short": q.get("prompt")}.get(kind) or q.get("q")
        label = {"truefalse": "True or false?", "fill": "Fill in the blank", "scenario": "What should happen?", "short": "Written answer",
                 "match": "Match", "order": "Put in order"}.get(kind, "Choose one answer")
        html(f'<div class="sx-q"><div class="sx-q-k">{escape(label)}</div><div class="sx-q-t">{base._rich(prompt)}</div></div>')
        if kind in ("mcq", "map", "image", "scenario"):
            opts = list(range(len(q["options"])))
            st.radio("Your answer", opts, key=k + "_r", index=None, disabled=lock, label_visibility="collapsed",
                     format_func=lambda i: q["options"][i]["text"])
        elif kind == "truefalse":
            st.radio("Your answer", ["True", "False"], key=k + "_r", index=None, disabled=lock, horizontal=True,
                     label_visibility="collapsed")
        elif kind == "fill":
            st.text_input("Your answer", key=k + "_t", disabled=lock, placeholder="Type the missing word or words")
        elif kind == "short":
            st.text_area("Your answer", key=k + "_t", disabled=lock, height=110,
                         placeholder="Write two or three sentences, then compare with the model answer.")
        elif kind == "match":
            rights = assess.match_options(q, seed=k)
            for i, (left, _) in enumerate(q["pairs"]):
                with st.container(key=f"{k}_mrow{i}", horizontal=True, vertical_alignment="center"):
                    html(f'<div class="sx-match-l">{base._rich(left)}</div>')
                    st.selectbox(f"Match for {base._plain(left)}", rights, key=f"{k}_m{i}", index=None, disabled=lock,
                                 placeholder="Choose…", label_visibility="collapsed")
        elif kind == "order":
            if k + "_order" not in SS:
                SS[k + "_order"] = assess.shuffled_order(q, seed=k)
            order = SS[k + "_order"]
            for i, item in enumerate(order):
                with st.container(key=f"{k}_orow{i}", horizontal=True, vertical_alignment="center"):
                    html(f'<div class="sx-order-item"><span class="sx-order-n">{i + 1}</span>{base._rich(item)}</div>')
                    st.button("Move up", key=f"{k}_up{i}", icon=":material/arrow_upward:", disabled=lock or i == 0,
                              on_click=_move, args=(k, i, -1), help=f"Move “{base._plain(item)}” up")
                    st.button("Move down", key=f"{k}_down{i}", icon=":material/arrow_downward:", disabled=lock or i == len(order) - 1,
                              on_click=_move, args=(k, i, 1), help=f"Move “{base._plain(item)}” down")
        if not lock:
            if SS.get(k + "_empty"):
                st.caption("Choose or type an answer first." if kind != "match" else "Choose a match for every item first.")
            st.button("Compare with the model answer" if kind == "short" else "Check answer", key=f"{k}_check", type="primary",
                      icon=":material/check:", on_click=_check, args=(subject_id, d["id"], q["id"], k, check_index))
            return None
        feedback(q, done, k)
        if retry and check_index is None:
            st.button("Try again", key=f"{k}_retry", icon=":material/refresh:", on_click=_reset, args=(k,))
    return done


def feedback(q: dict, done: dict, k: str) -> None:
    kind = q["type"]
    if not done["marked"]:
        html(f'<div class="feedback sx-fb-self" role="status"><div class="feedback-head"><span>✎ Check your own answer</span></div>'
             f'<p class="feedback-explain">{escape(done["explanation"])}</p>'
             f'<div class="sl-box-t">Model answer</div><p class="sl-p">{base._rich(q["model"])}</p></div>')
        html('<div class="sl-box-t">Does your answer…</div>')
        for i, point in enumerate(q["points"]):
            st.checkbox(base._plain(point), key=f"{k}_self{i}")
        st.caption("This is a self-check to help you improve. Written answers are not marked automatically and are not counted in your score.")
        return
    tone = "correct" if done["correct"] else "wrong"
    head = "✓ Correct!" if done["correct"] else "✕ Not quite."
    if kind == "scenario" and done.get("response") is not None:
        verdict = q["options"][int(done["response"])]["verdict"]
        head = ("✓ " if verdict == "best" else "◐ " if verdict == "acceptable" else "✕ ") + VERDICT_TITLES[verdict]
    extra = ""
    if kind == "match":
        extra = '<ul class="sx-detail">' + "".join(
            f'<li class="{"ok" if ok else "bad"}"><span aria-hidden="true">{"✓" if ok else "✕"}</span> {base._rich(left)} → '
            f'{base._rich(given or "—")}' + ("" if ok else f' <small>(correct: {base._rich(right)})</small>') + "</li>"
            for left, given, right, ok in done["detail"]) + "</ul>"
    elif kind == "order":
        extra = '<ol class="sx-detail">' + "".join(
            f'<li class="{"ok" if ok else "bad"}"><span aria-hidden="true">{"✓" if ok else "✕"}</span> {base._rich(right)}'
            + ("" if ok else f' <small>(you put: {base._rich(given or "—")})</small>') + "</li>"
            for _, right, given, ok in done["detail"]) + "</ol>"
        if not done["correct"]:
            extra = '<div class="sl-box-t">The correct order</div>' + extra
    html(f'<div class="feedback feedback-{tone}" role="status"><div class="feedback-head"><span>{escape(head)}</span></div>'
         f'<p class="feedback-explain">{base._rich(done["explanation"])}</p>{extra}</div>')


# --------------------------------------------------------------------------- activities

def _akey(d: dict, a: dict, suffix: str = "") -> str:
    return f"sx_{d['id']}_{a['id']}{suffix}"


def activity(subject_id: str, d: dict, a: dict) -> None:
    html(f'<p class="sx-instr">🧭 {base._rich(a["instructions"])}</p>')
    kind = a["type"]
    if kind == "explorer":
        _explorer(subject_id, d, a)
    elif kind == "timeline":
        _timeline(d, a)
    elif kind == "investigation":
        _investigation(subject_id, d, a)
    elif kind == "story":
        _story(subject_id, d, a)
    elif kind == "practice":
        for q in a["questions"]:
            question(subject_id, d, q, f"sx_{d['id']}_{q['id']}")
    elif kind == "diagram":
        _diagram(subject_id, d, a)


def _explorer(subject_id: str, d: dict, a: dict) -> None:
    items = {i["id"]: i for i in a["items"]}
    k = _akey(d, a)
    if a.get("figure"):
        html(f'<figure class="sl-fig">{_figure_svg(subject_id, a["figure"])}<figcaption><span class="sl-credit">'
             'Modern Nigeria, for reference only: the map marks where places are today and does not show historical boundaries. '
             'Positions are approximate.</span></figcaption></figure>')
    choice = st.pills("Choose an item to explore", list(items), key=k, format_func=lambda i: items[i]["title"],
                      default=a["items"][0]["id"], required=True)
    i = items.get(choice or a["items"][0]["id"])
    facts = "".join(f"<div><dt>{escape(f[0])}</dt><dd>{base._rich(f[1])}</dd></div>" for f in i.get("facts", []))
    html(f'<div class="sx-explore" aria-live="polite"><div class="sl-card-title">{escape(i["title"])}</div>'
         + (f'<div class="sl-muted">{escape(i["subtitle"])}</div>' if i.get("subtitle") else "")
         + (f'<dl class="sx-facts">{facts}</dl>' if facts else "") + f'<p class="sl-p">{base._rich(i["text"])}</p>{_meta(d, i)}</div>')


def _timeline(d: dict, a: dict) -> None:
    k = _akey(d, a)
    events = a["events"]
    rows = "".join(
        f'<li class="{"sx-approx" if e["approx"] else "sx-exact"}"><span class="sx-when">{escape(e["when"])}</span>'
        f'<span class="sx-ev-title">{base._rich(e["title"])}</span>'
        f'{base._chip("Approximate date" if e["approx"] else "Exact date", "teal" if e["approx"] else "ok")}</li>' for e in events)
    html(f'<ol class="sx-timeline" aria-label="Timeline, earliest first">{rows}</ol>')
    choice = st.selectbox("Read about an event", list(range(len(events))), key=k,
                          format_func=lambda i: f'{events[i]["when"]} · {base._plain(events[i]["title"])}')
    e = events[choice or 0]
    html(f'<div class="sx-explore" aria-live="polite"><div class="sl-kicker">{escape(e["when"])} · '
         f'{"approximate: estimated from evidence" if e["approx"] else "exact: recorded at the time"}</div>'
         f'<div class="sl-card-title">{base._rich(e["title"])}</div><p class="sl-p">{base._rich(e["background"])}</p>{_meta(d, e)}</div>')
    html('<p class="sl-muted">Dates marked “c.” (circa) or “about” are estimates. BC dates count down towards year 1; AD dates count up.</p>')


def _investigation(subject_id: str, d: dict, a: dict) -> None:
    html('<div class="sx-sources">' + "".join(
        f'<div class="sx-source sx-ev-{escape(s["kind"])}"><div class="sx-source-k">{EVIDENCE_ICONS[s["kind"]]} '
        f'Source {chr(65 + n)} · {escape(EVIDENCE_TITLES[s["kind"]])}</div><div class="sl-card-title">{escape(s["title"])}</div>'
        f'<p class="sl-p">{base._rich(s["text"])}</p><div class="sx-prov"><b>Where it comes from:</b> {base._rich(s["provenance"])}</div>'
        f'{_meta(d, s)}</div>' for n, s in enumerate(a["sources"])) + "</div>")
    html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">Ask of every source</div><ul class="sl-list"><li>Who made it, and when?</li>'
         '<li>Why was it made?</li><li>What can it tell us, and what can it not tell us?</li><li>Does other evidence agree?</li></ul></div>')
    for n, q in enumerate(a["questions"], 1):
        html(f'<h4 class="sl-h4">Question {n}</h4>')
        question(subject_id, d, q, f"sx_{d['id']}_{q['id']}")


def _next_chapter(k: str, total: int) -> None:
    SS[k] = min(SS.get(k, 0) + 1, total - 1)


def _story(subject_id: str, d: dict, a: dict) -> None:
    k = _akey(d, a, "_open")
    html(f'<div class="sl-note">📖 {base._rich(a["note"])}</div>')
    chapters = a["chapters"]
    opened = min(SS.get(k, 0), len(chapters) - 1)
    for n, c in enumerate(chapters[:opened + 1]):
        with st.container(key=f"{k}_ch{n}"):
            html(f'<div class="sx-chapter"><div class="sl-kicker">Chapter {n + 1} of {len(chapters)}</div>'
                 f'<div class="sl-card-title">{escape(c["title"])}</div>' + "".join(f'<p class="sl-p">{base._rich(p)}</p>' for p in c["text"]) + "</div>")
            for j, ins in enumerate(c.get("inspect", [])):
                with st.expander(f"🔍 Inspect: {ins['label']}", key=f"{k}_ins{n}_{j}"):
                    html(f'<p class="sl-p">{base._rich(ins["text"])}</p>')
            qk = f"sx_{d['id']}_{c['question']['id']}"
            question(subject_id, d, c["question"], qk)
            if n == opened and n + 1 < len(chapters):
                st.button("Next chapter", key=f"{k}_next{n}", type="primary", icon=":material/arrow_forward:", icon_position="right",
                          disabled=qk not in _qstate(), on_click=_next_chapter, args=(k, len(chapters)),
                          help="Answer this chapter's question to continue.")
    if opened + 1 == len(chapters) and f"sx_{d['id']}_{chapters[-1]['question']['id']}" in _qstate():
        html('<div class="sl-box"><div class="sl-box-t">End of the story</div><p class="sl-p">Look back: which parts were documented facts, and which were interpretations?</p></div>')


def _diagram(subject_id: str, d: dict, a: dict) -> None:
    nodes = {n["id"]: n for n in a["nodes"]}
    k = _akey(d, a)
    hub = a["nodes"][0]
    html('<div class="sx-diagram" role="list">' + "".join(
        f'<div class="sx-node{" sx-hub" if n is hub else ""}" role="listitem"><b>{escape(n["title"])}</b>'
        f'<span>{escape(", ".join(nodes[x]["title"] for x in n.get("links", []) if x != hub["id"]) or ("Connected to all" if n is hub else "Linked to " + hub["title"]))}</span></div>'
        for n in a["nodes"]) + "</div>")
    choice = st.pills("Explore an institution", list(nodes), key=k, format_func=lambda i: nodes[i]["title"], default=hub["id"], required=True)
    n = nodes.get(choice or hub["id"])
    links = [nodes[x]["title"] for x in n.get("links", [])]
    html(f'<div class="sx-explore" aria-live="polite"><div class="sl-card-title">{escape(n["title"])}</div>'
         f'<p class="sl-p">{base._rich(n["text"])}</p>'
         + (f'<div class="sl-muted"><b>Connected to:</b> {escape(", ".join(links))}</div>' if links else "") + f'{_meta(d, n)}</div>')
    for q in a.get("questions", []):
        question(subject_id, d, q, f"sx_{d['id']}_{q['id']}")


# --------------------------------------------------------------------------- knowledge check

def _start_check(lesson_id: str) -> None:
    d = school.lesson(_subject(), lesson_id)
    session = assess.new_session(lesson_id, d["assessment"])
    session["key"] = f"sxc_{lesson_id}_{random.randrange(10**6)}"
    SS.setdefault("sx_checks", {})[lesson_id] = session
    for key in [x for x in _qstate() if x.startswith(f"sxc_{lesson_id}_")]:
        _qstate().pop(key, None)


def _check_next(lesson_id: str, index: int) -> None:
    session = SS.get("sx_checks", {}).get(lesson_id)
    if not session or not assess.advance(session, index):
        return
    SS.school_scroll = True
    if session["finished"] and not session.get("recorded"):
        session["recorded"] = True
        subject_id = _subject()
        d = school.lesson(subject_id, lesson_id)
        base._put(subject_id, lesson_id, lessons.record_check(base.progress(subject_id).get(lesson_id), session))
        who = base._who()
        if who and school_store.enabled() and base._loaded(subject_id):
            t = assess.tally(session)
            try:
                school_store.record_attempt(who["profile_id"], subject_id, lesson_id, t["correct"], t["marked"],
                                            [x for x in session["answers"] if x["marked"]], d.get("version", 1))
            except Exception:
                SS.school_store_error = True


def knowledge_check(subject_id: str, d: dict) -> None:
    lesson_id = d["id"]
    session = SS.get("sx_checks", {}).get(lesson_id)
    marked = sum(1 for q in d["assessment"] if q["type"] != "short")
    if not session:
        rec = base.progress(subject_id).get(lesson_id) or {}
        html(f'<p class="sl-p">{len(d["assessment"])} questions of different kinds: {marked} are marked automatically, and '
             f'{len(d["assessment"]) - marked} written answer{"s are" if len(d["assessment"]) - marked != 1 else " is"} checked by you against a model answer. '
             'Every answer comes with an explanation.</p>'
             + (f'<p class="sl-muted">Your best score so far: {rec["best"]}/10 ({rec["attempts"]} attempt{"s" if rec["attempts"] != 1 else ""}).</p>'
                if rec.get("attempts") else ""))
        st.button("Start the knowledge check", key=f"sx_check_start_{lesson_id}", type="primary", icon=":material/quiz:",
                  on_click=_start_check, args=(lesson_id,))
        return
    if session["finished"]:
        _check_result(subject_id, d, session)
        return
    index = session["index"]
    q = lessons.question(d, session["items"][index])
    t = assess.tally(session)
    html(f'<div class="sl-readline"><span>Question {index + 1} of {len(session["items"])}</span><span>{t["correct"]} correct so far</span></div>'
         + base._bar(100 * len(session["answers"]) // len(session["items"]), "Knowledge check progress"))
    k = f'{session["key"]}_{index}'
    with st.container(key="sl_question_card"):
        done = question(subject_id, d, q, k, check_index=index, retry=False)
    if done is not None:
        last = index + 1 == len(session["items"])
        st.button("See my result" if last else "Next question", key=f"sx_check_next_{lesson_id}_{index}", type="primary",
                  icon=":material/arrow_forward:", icon_position="right", on_click=_check_next, args=(lesson_id, index))


def _check_result(subject_id: str, d: dict, session: dict) -> None:
    t = assess.tally(session)
    score = assess.score_out_of(session, 10)
    good = score >= school.REVISE_BELOW * 10
    rec = base.progress(subject_id).get(d["id"]) or {}
    with st.container(key="sl_result"):
        html(f'<div class="sl-result {"sl-result-good" if good else "sl-result-revise"}"><div class="sl-result-score">{t["correct"]}<small>/{t["marked"]}</small></div>'
             f'<div><div class="sl-card-title">{t["correct"]} of {t["marked"]} marked questions correct ({t["percent"]}%). '
             + ("Well done!" if good else "Keep going: revise the lesson and try again.") + '</div>'
             f'<div class="sl-muted">Score on the progress scale: {score}/10 · best {rec.get("best", score)}/10 · attempts {rec.get("attempts", 1)}'
             + (f' · {t["written"]} written answer{"s" if t["written"] != 1 else ""} self-checked (not counted)' if t["written"] else "") + '</div>'
             + ("" if good else '<div class="sl-why">↻ This lesson now shows “Needs revision” (best score below 6/10). Your completion is not affected.</div>')
             + "</div></div>")
        rows = []
        for i, a in enumerate(session["answers"]):
            q = lessons.question(d, a["id"])
            fb = session.get("feedback", {}).get(str(i), {})
            prompt = q.get("q") or q.get("statement") or q.get("text") or q.get("situation") or q.get("prompt")
            mark = "✎" if not a["marked"] else ("✓" if a["correct"] else "✕")
            cls = "ok" if a["correct"] else ("" if not a["marked"] else "bad")
            rows.append(f'<li class="{cls}"><span aria-hidden="true">{mark}</span> {base._rich(prompt)}<br><small>{escape(fb.get("explanation", ""))}</small></li>')
        with st.expander("Your answers with explanations", key="sl_review_answers", expanded=not good):
            html('<ul class="sl-answers-review">' + "".join(rows) + "</ul>")
        with st.container(key="sl_result_actions", horizontal=True):
            st.button("Try the knowledge check again", key="sl_again", type="primary", icon=":material/refresh:",
                      on_click=_start_check, args=(d["id"],))
            st.button("My progress", key="sl_result_progress", icon=":material/insights:", on_click=base.go, args=("progress",))


# --------------------------------------------------------------------------- lesson pages

def page_body(subject_id: str, d: dict, page: dict) -> None:
    kind = page["kind"]
    html(f'<h3 class="sl-page-title">{escape(page["title"])}</h3>')
    if kind not in ("check",):
        with st.expander("🔊 Listen to this page", key=f"sx_listen_{d['id']}_{page['id']}"):
            read_aloud(f"{d['id']}-{page['id']}", lessons.page_text(d, page))
    if kind == "intro":
        for p in d["introduction"]:
            html(f'<p class="sl-p">{base._rich(p)}</p>')
        html(f'<div class="sl-box sl-box-gold"><div class="sl-box-t">Why this matters</div><p class="sl-p">{base._rich(d["why"])}</p></div>')
        html('<div class="sl-box"><div class="sl-box-t">Learning objectives: by the end of this lesson you should be able to</div><ul class="sl-list">'
             + "".join(f"<li>{base._rich(o)}</li>" for o in d["objectives"]) + "</ul></div>")
        cur = d["curriculum"]
        topic = next((t for t in lessons.topics(subject_id) if t["id"] == d["topic"]), None)
        html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">Where this fits in the curriculum</div>'
             f'<p class="sl-p">{base._chip(d["class"], "level")} {base._chip(TERM_TITLES.get(d["term"], d["term"]))} '
             + (escape(topic["title"]) if topic else "") + '</p>'
             f'<p class="sl-p"><b>{escape(lessons.VERIFICATION[cur["verification"]])}.</b> {escape(cur["note"])}</p>'
             f'<p class="sl-muted">{escape(base.REVIEW_NOTE)}</p></div>')
    elif kind == "background":
        for b in d["background"]:
            block(subject_id, d, b)
    elif kind == "section":
        for b in page["section"]["blocks"]:
            block(subject_id, d, b)
    elif kind == "figures":
        html('<div class="sx-figures">' + "".join(
            f'<div class="sx-fig-card"><div class="sx-fig-k">{KIND_ICONS[k["kind"]]} {escape(k["kind"].title())}</div>'
            f'<div class="sl-card-title">{escape(k["name"])}</div>'
            + (f'<div class="sl-kicker">{escape(k["when"])}' + (" · approximate" if k.get("approx") else "") + "</div>" if k.get("when") else "")
            + f'<p class="sl-p">{base._rich(k["text"])}</p>{_meta(d, k)}</div>' for k in d["key_figures"]) + "</div>")
    elif kind == "cause":
        html('<div class="sx-causes">' + "".join(
            f'<div class="sx-cause"><div><span class="sx-ce-k">Cause</span>{base._rich(c["cause"])}</div>'
            f'<div class="sx-arrow" aria-hidden="true">→</div><div><span class="sx-ce-k">Effect</span>{base._rich(c["effect"])}</div>'
            f'<div class="sx-sig"><span class="sx-ce-k">Why it matters</span>{base._rich(c["significance"])}</div></div>'
            for c in d["cause_effect"]) + "</div>")
    elif kind == "activity":
        activity(subject_id, d, page["activity"])
    elif kind == "terms":
        html('<dl class="sl-defs">' + "".join(f"<div><dt>{base._rich(t)}</dt><dd>{base._rich(m)}</dd></div>" for t, m in d["key_terms"]) + "</dl>")
    elif kind == "summary":
        html('<div class="sl-box"><div class="sl-box-t">Summary</div><ul class="sl-list">'
             + "".join(f"<li>{base._rich(x)}</li>" for x in d["summary"]) + "</ul></div>")
    elif kind == "check":
        knowledge_check(subject_id, d)
    elif kind == "further":
        html('<div class="sl-box sl-box-quiet"><div class="sl-box-t">Further learning</div><ul class="sl-list">'
             + "".join(f'<li><b>{base._rich(f["title"])}</b>: {base._rich(f["why"])}</li>' for f in d["further"]) + "</ul></div>")
        html('<h4 class="sl-h4">Sources used in this lesson</h4><ol class="sl-refs">' + "".join(
            f'<li><a href="{escape(s["url"], quote=True)}" target="_blank" rel="noopener">{escape(s["title"])}</a> '
            f'<span class="sl-muted">({escape(s["kind"])})</span></li>' for s in d["sources"]) + "</ol>")
        cur = lessons.curriculum(subject_id)
        ids = set(d["curriculum"].get("sources", []))
        html('<h4 class="sl-h4">Curriculum references</h4><ul class="sl-refs">' + "".join(
            f'<li><a href="{escape(s["url"], quote=True)}" target="_blank" rel="noopener">{escape(s["title"])}</a></li>'
            for s in cur["sources"] if s["id"] in ids or s["id"] == "fme-2025") + "</ul>")
        html('<p class="sl-muted">Labels in this lesson: <b>Documented fact</b> (recorded evidence), <b>Oral tradition</b> (handed down by '
             'word of mouth), <b>Historians’ interpretation</b> (a conclusion drawn from evidence), <b>Approximate date</b> (an estimate) '
             'and <b>Disputed</b> (historians disagree).</p>')


def lesson_view() -> None:
    subject_id, lesson_id = _subject(), SS.school_lesson
    if lesson_id not in school.lesson_ids(subject_id):
        SS.school_view = "topics"
        topics_view()
        return
    d = _d(lesson_id)
    pages = school.pages(d)
    total = len(pages)
    rec = base.progress(subject_id).get(lesson_id) or school.move_to(None, 0, total, pages)
    here = school.page_index(pages, rec.get("page_id"), rec.get("page", 0))
    pct = school.reading_percent(rec, total)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("Back to topics", key="sl_back_topics", icon=":material/arrow_back:", on_click=base.go, args=("topics",))
        st.button("My progress", key="sl_lesson_progress", icon=":material/insights:", on_click=base.go, args=("progress",))
    with st.container(key="sl_reader_head"):
        html(f'<div class="sl-kicker">{escape(school.subject(subject_id)["title"])} · {escape(d["class"])} · '
             f'{escape(TERM_TITLES.get(d["term"], ""))}</div><h2 class="sl-lesson-title">{escape(d["title"])}</h2>'
             f'<div class="sl-card-meta">{base._status_chips(rec)}{_status_for(d)}</div>'
             f'<div class="sl-readline"><span>Page {here + 1} of {total}</span><span>{pct}% read</span></div>{base._bar(pct, "Reading progress")}')
    side, main = st.columns([1, 3], gap="medium")
    with side, st.container(key="sl_contents"):
        html('<div class="sl-box-t">Contents</div>')
        for i, p in enumerate(pages):
            seen = i <= rec.get("furthest", 0)
            st.button(("● " if i == here else ("✓ " if seen else "◦ ")) + p["title"], key=f"sl_toc_{i}",
                      type="primary" if i == here else "secondary", width="stretch", on_click=base.go, args=("lesson", None, i))
    with main, st.container(key="sl_reader"):
        jump_key = f"sl_jump_{lesson_id}"
        SS[jump_key] = here
        with st.container(key="sl_jump_box"):
            st.selectbox("Lesson contents", list(range(total)), key=jump_key,
                         format_func=lambda i: f"{i + 1}. {pages[i]['title']}", on_change=base._jump, args=(jump_key,))
        with st.container(key=f"sl_page_{pages[here]['kind']}"):
            page_body(subject_id, d, pages[here])
        with st.container(key="sl_pager", horizontal=True):
            st.button("Previous page", key="sl_prev_page", icon=":material/chevron_left:", disabled=here == 0,
                      on_click=base._turn, args=(-1,))
            st.button("Next page", key="sl_next_page", type="primary", icon=":material/chevron_right:", icon_position="right",
                      disabled=here + 1 >= total, on_click=base._turn, args=(1,))
        with st.container(key="sl_lesson_actions"):
            done = bool(rec.get("completed"))
            ready = school.can_complete(rec, total)
            with st.container(key="sl_status_row", horizontal=True, vertical_alignment="center"):
                if done:
                    st.button("Completed · undo", key="sl_uncomplete", icon=":material/check_circle:",
                              on_click=base._complete, args=(False,), help="Marks the lesson as not complete. Your scores are kept.")
                else:
                    st.button("Mark lesson complete", key="sl_complete", icon=":material/task_alt:", disabled=not ready,
                              type="primary" if ready else "secondary", on_click=base._complete, args=(True,))
                on = bool(rec.get("revision"))
                st.button("Remove from revision" if on else "Add to revision", key="sl_revision",
                          icon=":material/bookmark_remove:" if on else ":material/bookmark_add:", on_click=base._revision, args=(not on,))
            if not done and not ready:
                st.caption("Reach the last page to mark this lesson complete. Your revision list is separate, and a low "
                           "knowledge-check score never removes completion.")
            reasons = school.revision_reasons(rec)
            if reasons:
                html(f'<div class="sl-why">↻ Needs revision: {escape("; ".join(reasons)).replace("practice score", "knowledge-check score")}</div>')
        before, after = school.neighbours(subject_id, lesson_id)
        with st.container(key="sl_lesson_nav", horizontal=True):
            st.button(f"Previous lesson · {_d(before)['short']}" if before else "Previous lesson",
                      key="sl_prev_lesson", icon=":material/skip_previous:", disabled=not before, on_click=base.go, args=("lesson", before))
            st.button(f"Next lesson · {_d(after)['short']}" if after else "Next lesson",
                      key="sl_next_lesson", icon=":material/skip_next:", icon_position="right", disabled=not after,
                      on_click=base.go, args=("lesson", after))
    base._scroll_to(".st-key-sl_reader_head")


# --------------------------------------------------------------------------- progress dashboard

def progress_view() -> None:
    subject_id = _subject()
    prog = base.progress(subject_id)
    o = school.overview(subject_id, prog)
    with st.container(key="sl_topbar", horizontal=True, vertical_alignment="center"):
        st.button("School Learning", key="sl_progress_home", icon=":material/arrow_back:", on_click=base.go, args=("home",))
        st.button("Back to topics", key="sl_progress_topics", icon=":material/list:", on_click=base.go, args=("topics",))
    base._guest_offer_box()
    html(f'<div class="sl-intro"><h2>My School Learning progress</h2><p>{escape(school.subject(subject_id)["title"])} · '
         'academic progress only, kept separately from quiz points, badges and rewards.</p></div>')
    base._overview_tiles(o)
    nxt = lessons.suggested_next(subject_id, prog)
    if nxt:
        d = _d(nxt)
        with st.container(key="sx_next"):
            html(f'<div class="sl-continue"><div class="sl-kicker">Suggested next lesson</div>'
                 f'<div class="sl-continue-title">{escape(d["title"])}</div><div class="sl-muted">{escape(d["class"])} · '
                 f'{escape(TERM_TITLES.get(d["term"], ""))}</div></div>')
            st.button("Open the suggested lesson", key="sx_next_btn", type="primary", icon=":material/menu_book:",
                      on_click=base.go, args=("lesson", nxt))
    if o["recent"]:
        html('<div class="sl-box-t">Recently studied</div>')
        with st.container(key="sl_recent", horizontal=True):
            for lesson_id in o["recent"]:
                st.button(_d(lesson_id)["title"], key=f"sl_recent_{lesson_id}", icon=":material/history:",
                          on_click=base.go, args=("lesson", lesson_id))
    html('<h3 class="sl-h">By class and term</h3>')
    rows = []
    for c in lessons.classes_with_lessons(subject_id):
        for t in c["terms"]:
            p = lessons.progress_by(subject_id, prog, c["id"], t["id"])
            if p["lessons"]:
                rows.append(f'<tr><th scope="row">{escape(c["title"])}</th><td data-label="Term">{escape(TERM_TITLES.get(t["id"], t["id"]))}</td>'
                            f'<td data-label="Lessons">{p["lessons"]}</td><td data-label="Started">{p["started"]}</td>'
                            f'<td data-label="Completed">{p["completed"]} ({p["percent"]}%)</td></tr>')
    html('<div class="sl-table-wrap" tabindex="0"><table class="sl-table sl-progress-table"><thead><tr><th scope="col">Class</th>'
         '<th scope="col">Term</th><th scope="col">Lessons</th><th scope="col">Started</th><th scope="col">Completed</th></tr></thead>'
         f'<tbody>{"".join(rows) or "<tr><td colspan=5>No lessons yet.</td></tr>"}</tbody></table></div>')
    html('<h3 class="sl-h">Lessons</h3>')
    rows = []
    for lesson_id in school.lesson_ids(subject_id):
        d = _d(lesson_id)
        rec = prog.get(lesson_id)
        total = len(school.pages(d))
        best = f'{rec["best"]}/10' if rec and rec.get("attempts") else "—"
        tried = f'{rec.get("correct", 0)} of {rec.get("answered", 0)}' if rec and rec.get("attempts") else "—"
        reasons = "; ".join(school.revision_reasons(rec)).replace("practice score", "check score") or "—"
        rows.append(f'<tr><th scope="row">{escape(d["title"])}</th><td data-label="Class">{escape(d["class"])}</td>'
                    f'<td data-label="Status">{base._status_chips(rec)}</td><td data-label="Read">{school.reading_percent(rec, total)}%</td>'
                    f'<td data-label="Best score">{escape(best)}</td><td data-label="Marked answers correct">{escape(tried)}</td>'
                    f'<td data-label="Revision">{escape(reasons)}</td></tr>')
    html('<div class="sl-table-wrap" tabindex="0"><table class="sl-table sl-progress-table"><thead><tr><th scope="col">Lesson</th>'
         '<th scope="col">Class</th><th scope="col">Status</th><th scope="col">Read</th><th scope="col">Best score</th>'
         f'<th scope="col">Marked answers correct</th><th scope="col">Revision</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    with st.expander("How progress is calculated", key="sl_rules"):
        html('<ul class="sl-list">'
             '<li><b>Not started:</b> you have not opened the lesson. <b>In progress:</b> opened but not marked complete.</li>'
             '<li><b>Completed:</b> you pressed “Mark lesson complete” after reaching the last page. A score never removes it.</li>'
             '<li><b>Best score:</b> your best knowledge-check result, shown out of 10. Only automatically marked questions count; '
             'written answers are self-checked.</li>'
             '<li><b>Needs revision:</b> you added the lesson to your revision list, or your best score is below 6/10.</li>'
             '<li><b>Suggested next lesson:</b> the lesson you were last working on, or the next one not completed in the class you '
             'studied most recently.</li></ul>')
    base._storage_note()
    html(f'<p class="sl-disclaimer">🎓 {escape(base.NOT_REWARDS)}</p>')
