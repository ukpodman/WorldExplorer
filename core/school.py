"""School Learning: subjects, curricula, lessons, reading progress and topic practice (no Streamlit here).

Content lives in data/school/ as JSON, one file per lesson, so new lessons and new subjects (Nigerian History,
Citizenship and Heritage Studies) are added as data without changing the interface code.

School Learning is study only. Nothing here touches World Explorer points, badges, quiz statistics, rewards or
withdrawals: practice scores are kept in their own progress records.

Structure: school (Nigerian secondary) → subject → class level (SSS 1–3; JSS later) → curriculum topic → lesson →
practice → progress. Lessons and question banks are data; this module only reads and checks them.

Progress record for one lesson (all optional; missing means "not started"):
    page        int   the page the student was reading (their reading position)
    page_id     str   the same position as a stable page id (survives corrected lessons that add or move pages)
    furthest    int   the furthest page reached (reading progress)
    completed   bool  the student marked the lesson complete (allowed once the last page has been reached)
    revision    bool  the student added the lesson to their revision list (independent of completion)
    best, last  int   best and latest practice score (out of PRACTICE_SIZE)
    attempts    int   finished practice sessions
    answered, correct  int   practice questions answered and answered correctly, in total
    recent      list  ids of the most recently asked questions (the next round avoids them where possible)
    version     int   the lesson's content version when the student last opened it
    practised_at, completed_at, updated_at   ISO timestamps (UTC)

Progress rules (shown to students on the dashboard):
    Not started  no record. In progress  opened but not marked complete. Completed  marked complete after reaching
    the last page; never undone by a practice score. Needs revision  added to the revision list by the student, or a
    best practice score below 6/10; shown alongside the reading status, so a completed lesson can still need revision.
    Reading progress = (furthest page + 1) / pages. Average practice score = mean of each practised lesson's best score.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "school"
PRACTICE_SIZE = 10
BANK_MIN = 20               # every lesson's question bank has at least this many questions
RECENT_KEEP = 20            # how many recently asked question ids are remembered per lesson
DIFFICULTIES = ("easy", "medium", "hard")
REVISE_BELOW = 0.6          # a best practice score below 60% suggests revision
BLOCK_TYPES = {"p", "h", "list", "cards", "table", "figure", "photo", "note"}
PAGE_KINDS = ("intro", "section", "definitions", "examples", "check", "review")


class ContentError(ValueError):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def subjects() -> list[dict]:
    return _read(ROOT / "subjects.json")["subjects"]


def subject(subject_id: str) -> dict | None:
    return next((s for s in subjects() if s["id"] == subject_id), None)


def interactive(subject_id: str) -> bool:
    """Nigerian History and Citizenship and Heritage Studies use the interactive lesson engine (core/lessons.py)."""
    return (subject(subject_id) or {}).get("engine") == "interactive"


@lru_cache(maxsize=8)
def curriculum(subject_id: str) -> dict:
    s = subject(subject_id)
    if not s or s.get("status") != "available":
        raise ContentError(f"subject {subject_id!r} is not available")
    if interactive(subject_id):
        from . import lessons
        return lessons.curriculum(subject_id)
    return _read(ROOT / s["curriculum"])


def lesson_ids(subject_id: str) -> list[str]:
    """Lessons in curriculum order (only topics that have a full lesson)."""
    if interactive(subject_id):
        from . import lessons
        return lessons.lesson_ids(subject_id)
    return [t["id"] for sec in curriculum(subject_id)["sections"] for t in sec["topics"] if t.get("lesson")]


def topic_count(subject_id: str) -> int:
    if interactive(subject_id):
        from . import lessons
        return lessons.topic_count(subject_id)
    return sum(len(sec["topics"]) for sec in curriculum(subject_id)["sections"])


@lru_cache(maxsize=64)
def lesson(subject_id: str, lesson_id: str) -> dict:
    if interactive(subject_id):
        from . import lessons
        return lessons.lesson(subject_id, lesson_id)
    if lesson_id not in lesson_ids(subject_id):
        raise ContentError(f"unknown lesson {lesson_id!r}")
    data = _read(ROOT / subject_id / "lessons" / f"{lesson_id}.json")
    validate_lesson(data)
    return data


@lru_cache(maxsize=64)
def figure(subject_id: str, name: str) -> str:
    """An SVG diagram (trusted, generated by tools/build_school_figures.py)."""
    if not name.replace("_", "").isalnum():
        raise ContentError(f"bad figure name {name!r}")
    return (ROOT / subject_id / "figures" / f"{name}.svg").read_text(encoding="utf-8")


def validate_lesson(d: dict) -> None:
    """Fail loudly on content mistakes (tests run this for every lesson)."""
    need = ("id", "subject", "number", "title", "level", "version", "review_status", "objectives", "intro", "sections",
            "definitions", "exam_tips", "checks", "summary", "practice", "structured", "references")
    missing = [k for k in need if k not in d]
    if missing:
        raise ContentError(f"{d.get('id')}: missing {missing}")
    ids = {s["id"] for s in d["sections"]}
    if len(ids) != len(d["sections"]):
        raise ContentError(f"{d['id']}: duplicate section ids")
    for s in d["sections"]:
        for b in s["blocks"]:
            if b.get("type") not in BLOCK_TYPES:
                raise ContentError(f"{d['id']}/{s['id']}: unknown block {b.get('type')!r}")
    if len(d["practice"]) < BANK_MIN:
        raise ContentError(f"{d['id']}: needs at least {BANK_MIN} practice questions")
    for s in d["sections"]:
        for b in s["blocks"]:
            if b.get("type") == "figure" and not b.get("credit"):
                raise ContentError(f"{d['id']}/{s['id']}: figure {b.get('src')} has no credit")
    qids = set()
    for q in d["practice"]:
        if q["id"] in qids:
            raise ContentError(f"{d['id']}: duplicate question id {q['id']}")
        qids.add(q["id"])
        if len(q["options"]) != 4 or len(set(q["options"])) != 4 or not 0 <= q["answer"] < 4:
            raise ContentError(f"{d['id']}/{q['id']}: needs four different options and a valid answer")
        if q.get("section") not in ids:
            raise ContentError(f"{d['id']}/{q['id']}: section {q.get('section')!r} not in lesson")
        if not q.get("explanation"):
            raise ContentError(f"{d['id']}/{q['id']}: missing explanation")
        if q.get("difficulty") not in DIFFICULTIES or q.get("subject") != d["subject"] or q.get("topic") != d["id"]:
            raise ContentError(f"{d['id']}/{q['id']}: needs difficulty, subject and topic identifiers")


def pages(d: dict) -> list[dict]:
    """The lesson as pages, read one at a time: the student's reading position is a page index."""
    if d.get("format") == "interactive":
        from . import lessons
        return lessons.pages(d)
    out = [{"kind": "intro", "id": "intro", "title": "Introduction and objectives"}]
    out += [{"kind": "section", "id": s["id"], "title": s["title"], "section": s} for s in d["sections"]]
    out.append({"kind": "definitions", "id": "definitions", "title": "Key definitions"})
    out.append({"kind": "examples", "id": "examples", "title": "Worked examples and exam tips"})
    out.append({"kind": "check", "id": "check", "title": "Check your understanding"})
    out.append({"kind": "review", "id": "review", "title": "Summary and exam-style questions"})
    return out


def neighbours(subject_id: str, lesson_id: str) -> tuple[str | None, str | None]:
    ids = lesson_ids(subject_id)
    i = ids.index(lesson_id)
    return (ids[i - 1] if i > 0 else None), (ids[i + 1] if i + 1 < len(ids) else None)


# --------------------------------------------------------------------------- progress

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def page_index(pages_: list[dict], page_id: str | None, fallback: int = 0) -> int:
    """The current index of a page id (lessons may gain or reorder pages when corrected); else the fallback."""
    for i, p in enumerate(pages_):
        if p["id"] == page_id:
            return i
    return max(0, min(fallback, len(pages_) - 1))


def clean_record(rec, total_pages: int, page_ids: list[str] | None = None) -> dict | None:
    """A saved record, made safe (wrong types and out-of-range values dropped). With page_ids, the reading
    position follows its stable page id, so a corrected lesson never sends the student back to the start."""
    if not isinstance(rec, dict):
        return None
    out = {}
    for key in ("page", "furthest", "best", "last", "attempts", "answered", "correct", "version"):
        v = rec.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[key] = v
    for key in ("completed", "revision"):
        if isinstance(rec.get(key), bool):
            out[key] = rec[key]
    for key in ("practised_at", "completed_at", "updated_at"):
        if isinstance(rec.get(key), str) and len(rec[key]) <= 40:
            out[key] = rec[key]
    if isinstance(rec.get("page_id"), str) and len(rec["page_id"]) <= 64:
        out["page_id"] = rec["page_id"]
    recent = rec.get("recent")
    if isinstance(recent, list):
        out["recent"] = [x for x in recent if isinstance(x, str) and len(x) <= 32][-RECENT_KEEP:]
    last_page = max(total_pages - 1, 0)
    if page_ids and out.get("page_id") in page_ids:
        out["page"] = page_ids.index(out["page_id"])
    out["page"] = min(out.get("page", 0), last_page)
    out["furthest"] = max(min(out.get("furthest", 0), last_page), out["page"])
    for key in ("best", "last"):
        if key in out:
            out[key] = min(out[key], PRACTICE_SIZE)
    if "correct" in out:
        out["correct"] = min(out["correct"], out.get("answered", 0))
    return out


def reading_percent(rec: dict | None, total_pages: int) -> int:
    if not rec or total_pages <= 0:
        return 0
    return round(100 * (rec.get("furthest", 0) + 1) / total_pages)


def can_complete(rec: dict | None, total_pages: int) -> bool:
    return bool(rec) and rec.get("furthest", 0) >= total_pages - 1


def revision_reasons(rec: dict | None) -> list[str]:
    """Why a lesson needs revision; a completed lesson can still need it."""
    if not rec:
        return []
    out = []
    if rec.get("revision"):
        out.append("On your revision list")
    if rec.get("attempts") and rec.get("best") is not None and rec["best"] < REVISE_BELOW * PRACTICE_SIZE:
        out.append(f"Best practice score {rec['best']}/{PRACTICE_SIZE}")
    return out


def status(rec: dict | None) -> str:
    """Reading status only: 'Not started', 'In progress' or 'Completed'. Revision is shown separately."""
    if not rec:
        return "Not started"
    return "Completed" if rec.get("completed") else "In progress"


def states(rec: dict | None) -> list[str]:
    """Every state that applies: the reading status, plus 'Needs revision' when it applies (filters use this)."""
    return [status(rec)] + (["Needs revision"] if revision_reasons(rec) else [])


STATE_FILTERS = ("All", "Not started", "In progress", "Completed", "Needs revision")


def updated_since(rec: dict | None, d: dict) -> bool:
    """The lesson has been corrected or extended since the student last opened it."""
    return bool(rec) and isinstance(rec.get("version"), int) and rec["version"] < d.get("version", 1)


def move_to(rec: dict | None, page: int, total_pages: int, pages_: list[dict] | None = None, version: int | None = None) -> dict:
    rec = dict(rec or {})
    page = max(0, min(page, total_pages - 1))
    rec["page"] = page
    rec["furthest"] = max(rec.get("furthest", 0), page)
    if pages_:
        rec["page_id"] = pages_[page]["id"]
    if version is not None:
        rec["version"] = version
    rec["updated_at"] = now_iso()
    return rec


def set_completed(rec: dict | None, total_pages: int, done: bool = True) -> dict:
    rec = dict(rec or {})
    if done and not can_complete(rec, total_pages):
        return rec
    rec["completed"] = done
    if done:
        rec["completed_at"] = now_iso()
    rec["updated_at"] = now_iso()
    return rec


def set_revision(rec: dict | None, on: bool) -> dict:
    rec = dict(rec or {})
    rec["revision"] = bool(on)
    rec["updated_at"] = now_iso()
    return rec


def record_practice(rec: dict | None, score: int, asked: list[str] | None = None, answered: int | None = None) -> dict:
    """A finished practice round. Completion is never changed by a score; a low best score adds 'Needs revision'."""
    rec = dict(rec or {})
    score = max(0, min(int(score), PRACTICE_SIZE))
    rec["last"] = score
    rec["best"] = max(rec.get("best", 0), score) if rec.get("attempts") else score
    rec["attempts"] = rec.get("attempts", 0) + 1
    rec["answered"] = rec.get("answered", 0) + (PRACTICE_SIZE if answered is None else int(answered))
    rec["correct"] = rec.get("correct", 0) + score
    if asked:
        recent = [x for x in rec.get("recent", []) if x not in asked] + list(asked)
        rec["recent"] = recent[-RECENT_KEEP:]
    rec["practised_at"] = rec["updated_at"] = now_iso()
    return rec


def overview(subject_id: str, progress: dict) -> dict:
    """Numbers for the dashboard (rules in the module docstring)."""
    ids = lesson_ids(subject_id)
    recs = [progress.get(i) for i in ids]
    done = sum(1 for r in recs if r and r.get("completed"))
    going = sum(1 for r in recs if r and not r.get("completed"))
    scores = [r["best"] for r in recs if r and r.get("attempts")]
    revise = sum(1 for r in recs if revision_reasons(r))
    answered = sum((r or {}).get("answered", 0) for r in recs)
    correct = sum((r or {}).get("correct", 0) for r in recs)
    recent = sorted((r.get("updated_at", ""), i) for i, r in zip(ids, recs) if r and r.get("updated_at"))
    return {"lessons": len(ids), "completed": done, "in_progress": going, "not_started": len(ids) - done - going,
            "revise": revise, "answered": answered, "correct": correct,
            "average": round(100 * sum(scores) / (len(scores) * PRACTICE_SIZE)) if scores else None,
            "recent": [i for _, i in reversed(recent)][:3]}


def continue_target(subject_id: str, progress: dict) -> str:
    """The lesson to continue: the most recently used unfinished one, else the first not completed, else lesson 1."""
    ids = lesson_ids(subject_id)
    open_ = [(progress[i].get("updated_at", ""), i) for i in ids if progress.get(i) and not progress[i].get("completed")]
    if open_:
        return max(open_)[1]
    return next((i for i in ids if not (progress.get(i) or {}).get("completed")), ids[0])


def topic_section(subject_id: str, topic_id: str) -> str | None:
    """The curriculum section (e.g. 'regional') that a topic or lesson belongs to."""
    return next((sec["id"] for sec in curriculum(subject_id)["sections"] for t in sec["topics"] if t["id"] == topic_id), None)


def _matches(text: str, needle: str) -> bool:
    return not needle or needle in text.replace("**", "").casefold()


def find_lessons(subject_id: str, progress: dict, query: str = "", section: str = "All", state: str = "All",
                 level: str = "All") -> list[str]:
    """Lesson ids matching a search (title, objectives, section titles and key terms), a curriculum section, a class
    level and a learning state."""
    needle = query.strip().casefold()
    out = []
    for lesson_id in lesson_ids(subject_id):
        d = lesson(subject_id, lesson_id)
        if state != "All" and state not in states(progress.get(lesson_id)):
            continue
        if section != "All" and topic_section(subject_id, lesson_id) != section:
            continue
        if level != "All" and level not in d.get("level", []):
            continue
        text = " ".join([d["title"], d.get("short", "")] + d["objectives"] + [x["title"] for x in d["sections"]]
                        + [t for t, _ in d.get("definitions", d.get("key_terms", []))] + d.get("level", [])
                        + ([d["class"]] if d.get("class") else []))
        if _matches(text, needle):
            out.append(lesson_id)
    return out


def find_topics(subject_id: str, query: str = "", section: str = "All", level: str = "All",
                with_lessons: bool = False) -> list[tuple[dict, dict]]:
    """(section, topic) pairs of the curriculum matching a search, section and level. By default only topics
    without a lesson yet (the lessons are listed separately)."""
    needle = query.strip().casefold()
    out = []
    for sec in curriculum(subject_id)["sections"]:
        if section != "All" and sec["id"] != section:
            continue
        for t in sec["topics"]:
            if t.get("lesson") and not with_lessons:
                continue
            if level != "All" and level not in t.get("level", []):
                continue
            if _matches(" ".join([t["title"], sec["title"]] + t.get("objectives", []) + t.get("level", [])), needle):
                out.append((sec, t))
    return out


# --------------------------------------------------------------------------- practice

def new_practice(d: dict, seed: int | None = None, recent: list[str] | None = None) -> dict:
    """Ten questions from the lesson's bank, in a random order, each with its options shuffled. Questions asked in the
    student's most recent rounds are used only when there are not enough others, so a retry is not a repeat."""
    rnd = random.Random(seed)
    recent = set(recent or [])
    fresh = [q for q in d["practice"] if q["id"] not in recent]
    used = [q for q in d["practice"] if q["id"] in recent]
    rnd.shuffle(fresh)
    rnd.shuffle(used)
    qs = (fresh + used)[:PRACTICE_SIZE]
    rnd.shuffle(qs)
    return {"lesson": d["id"], "items": [{"id": q["id"], "order": rnd.sample(range(4), 4)} for q in qs],
            "index": 0, "answers": [], "finished": False}


def question(d: dict, qid: str) -> dict:
    return next(q for q in d["practice"] if q["id"] == qid)


def answer(session: dict, d: dict, index: int, choice_pos: int) -> bool:
    """Record an answer once (a double click or a rerun cannot answer twice). Returns True if it was recorded."""
    if session["finished"] or index != session["index"] or len(session["answers"]) != index:
        return False
    item = session["items"][index]
    original = item["order"][choice_pos]
    q = question(d, item["id"])
    session["answers"].append({"id": q["id"], "chosen": original, "correct": original == q["answer"]})
    return True


def advance(session: dict, index: int) -> bool:
    if index != session["index"] or len(session["answers"]) != index + 1:
        return False
    if index + 1 >= len(session["items"]):
        session["finished"] = True
    else:
        session["index"] = index + 1
    return True


def score(session: dict) -> int:
    return sum(1 for a in session["answers"] if a["correct"])


def areas_to_revise(session: dict, d: dict) -> list[tuple[dict, int]]:
    """Lesson sections behind the missed questions, most missed first: (section, number missed)."""
    missed: dict[str, int] = {}
    for a in session["answers"]:
        if not a["correct"]:
            sec = question(d, a["id"])["section"]
            missed[sec] = missed.get(sec, 0) + 1
    by_id = {s["id"]: s for s in d["sections"]}
    return [(by_id[k], n) for k, n in sorted(missed.items(), key=lambda kv: -kv[1]) if k in by_id]
