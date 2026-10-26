"""School Learning — interactive lesson engine for Nigerian History and Citizenship and Heritage Studies (no Streamlit).

Data-driven: a subject's curriculum (classes → terms → topics) and its lessons are JSON files in data/school/<subject>/.
Adding a lesson is adding a file and listing its id under a topic; no interface code changes. Geography keeps its own
format (core/school.py); core.school dispatches here for subjects whose subjects.json entry has "engine": "interactive".

Curriculum file (<subject>/curriculum.json)
    subject, version, note, sources [{id, title, url, kind, note}],
    classes [{id, title, stage, note?, terms [{id, title, topics [{id, title, verification, sources, objectives?,
              lessons [lesson ids]}]}]}]
    verification of a topic: "official"   checked against the official NERDC curriculum document
                             "scheme"     listed in published schemes of work that say they follow the NERDC
                                          curriculum, NOT yet checked against the official document
                             "enrichment" additional World Explorer material, not part of the prescribed curriculum

Lesson file (<subject>/lessons/<id>.json), "format": "interactive" (figure blocks name their SVG in "figure") — the parts A–K of a full lesson:
    introduction, why (A) · objectives (B) · background (C, blocks) · sections (D, [{id, title, blocks}]) ·
    key_figures (E, [{name, kind, text, when?, approx?}]) · cause_effect (F, [{cause, effect, significance}]) ·
    activities (G, at least two) · key_terms (H) · summary (I) · assessment (J, questions for core.assess) ·
    further (K, [{title, why}]) and sources ([{id, title, url, kind}])
    plus id, subject, class, term, topic, title, short, minutes, version, stage ("primary" | "secondary"),
    review_status ("draft" | "reviewed" | "published") and curriculum {verification, note, sources}.
    Primary lessons are shorter: background and cause_effect are optional for them.
    Any block or item may carry "basis" (fact | tradition | interpretation | disputed | approximate) and "src"
    (source ids), shown to students so they can tell documented facts from traditions and interpretations.

Activity types: explorer (selectable places, kingdoms, sites or heritage items, optional map), timeline (events in
order, precise or approximate dates), investigation (sources to examine with questions), story (chapters with
things to inspect and a question each), practice (any assessment questions: ordering, matching, scenarios …) and
diagram (institutions and how they relate).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import assess

ROOT = Path(__file__).resolve().parent.parent / "data" / "school"
REVIEW_STATUSES = ("draft", "reviewed", "published")
FINISHED = ("reviewed", "published")            # only these are presented as finished lessons
VERIFICATION = {"official": "Checked against the official NERDC curriculum",
                "scheme": "Listed in published schemes of work (not yet checked against the official NERDC document)",
                "enrichment": "Additional World Explorer material (not part of the prescribed curriculum)"}
BASIS = {"fact": "Documented fact", "tradition": "Oral tradition", "interpretation": "Historians’ interpretation",
         "disputed": "Disputed", "approximate": "Approximate date"}
BLOCK_TYPES = {"p", "h", "list", "cards", "table", "figure", "note", "quote_source"}
ACTIVITY_TYPES = ("explorer", "timeline", "investigation", "story", "practice", "diagram")
SOURCE_KINDS = ("official", "law", "museum", "academic", "reference", "scheme", "news")
EVIDENCE_KINDS = ("oral", "archaeological", "written", "art", "interpretation")
TERM_IDS = ("first", "second", "third", "unassigned")
ID = re.compile(r"[a-z0-9][a-z0-9-]{1,60}")
ASSESS_MIN = {"primary": 6, "secondary": 8}


class ContentError(ValueError):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def curriculum(subject_id: str) -> dict:
    data = _read(ROOT / subject_id / "curriculum.json")
    validate_curriculum(data)
    return data


def classes(subject_id: str) -> list[dict]:
    return curriculum(subject_id)["classes"]


def class_(subject_id: str, class_id: str) -> dict | None:
    return next((c for c in classes(subject_id) if c["id"] == class_id), None)


def topics(subject_id: str, class_id: str | None = None, term_id: str | None = None) -> list[dict]:
    out = []
    for c in classes(subject_id):
        if class_id and c["id"] != class_id:
            continue
        for t in c["terms"]:
            if term_id and t["id"] != term_id:
                continue
            out.extend(t["topics"])
    return out


def topic_count(subject_id: str) -> int:
    return len(topics(subject_id))


def _lesson_path(subject_id: str, lesson_id: str) -> Path:
    return ROOT / subject_id / "lessons" / f"{lesson_id}.json"


def lesson_ids(subject_id: str, class_id: str | None = None, term_id: str | None = None) -> list[str]:
    """Lessons in curriculum order (class → term → topic), only those whose file exists."""
    out = []
    for t in topics(subject_id, class_id, term_id):
        for lesson_id in t.get("lessons", []):
            if lesson_id not in out and _lesson_path(subject_id, lesson_id).exists():
                out.append(lesson_id)
    return out


@lru_cache(maxsize=64)
def lesson(subject_id: str, lesson_id: str) -> dict:
    if lesson_id not in lesson_ids(subject_id):
        raise ContentError(f"unknown lesson {lesson_id!r}")
    data = _read(_lesson_path(subject_id, lesson_id))
    validate_lesson(data)
    return data


def finished(d: dict) -> bool:
    return d.get("review_status") in FINISHED


def classes_with_lessons(subject_id: str) -> list[dict]:
    return [c for c in classes(subject_id) if lesson_ids(subject_id, c["id"])]


def counts(subject_id: str) -> dict:
    """Numbers for the subject card: lessons by review status, curriculum topics, classes with lessons."""
    ids = lesson_ids(subject_id)
    reviewed = sum(1 for i in ids if finished(lesson(subject_id, i)))
    return {"lessons": len(ids), "reviewed": reviewed, "draft": len(ids) - reviewed, "topics": topic_count(subject_id),
            "classes": [c["title"] for c in classes_with_lessons(subject_id)]}


def figure(subject_id: str, name: str) -> str:
    if not ID.fullmatch(name.replace("_", "-")):
        raise ContentError(f"bad figure name {name!r}")
    return (ROOT / subject_id / "figures" / f"{name}.svg").read_text(encoding="utf-8")


def figure_names(subject_id: str) -> set[str]:
    folder = ROOT / subject_id / "figures"
    return {p.stem for p in folder.glob("*.svg")} if folder.exists() else set()


# --------------------------------------------------------------------------- validation

def validate_curriculum(c: dict) -> None:
    for key in ("subject", "version", "note", "sources", "classes"):
        if key not in c:
            raise ContentError(f"curriculum: missing {key}")
    source_ids = {s["id"] for s in c["sources"]}
    seen = set()
    for cl in c["classes"]:
        if not ID.fullmatch(cl.get("id", "")) or not cl.get("title") or cl.get("stage") not in ("Primary", "JSS", "SSS"):
            raise ContentError(f"curriculum: bad class {cl.get('id')!r}")
        for term in cl.get("terms", []):
            if term.get("id") not in TERM_IDS or not term.get("title"):
                raise ContentError(f"curriculum {cl['id']}: bad term {term.get('id')!r}")
            for t in term.get("topics", []):
                if not ID.fullmatch(t.get("id", "")) or t["id"] in seen or not t.get("title"):
                    raise ContentError(f"curriculum: bad or duplicate topic {t.get('id')!r}")
                seen.add(t["id"])
                if t.get("verification") not in VERIFICATION:
                    raise ContentError(f"curriculum {t['id']}: verification must be one of {list(VERIFICATION)}")
                if not set(t.get("sources", [])) <= source_ids or (t["verification"] != "enrichment" and not t.get("sources")):
                    raise ContentError(f"curriculum {t['id']}: unknown or missing source ids")


def _blocks(lesson_id: str, where: str, blocks: list, src_ids: set[str], figures: set[str] | None) -> None:
    for b in blocks:
        kind = b.get("type")
        if kind not in BLOCK_TYPES:
            raise ContentError(f"{lesson_id}/{where}: unknown block {kind!r}")
        if kind == "figure":
            if not b.get("credit") or not b.get("caption") or (figures is not None and b.get("figure") not in figures):
                raise ContentError(f"{lesson_id}/{where}: figure {b.get('figure')!r} needs a caption, a credit and a file")
        if kind == "quote_source" and (b.get("kind") not in EVIDENCE_KINDS or not b.get("text") or not b.get("provenance")):
            raise ContentError(f"{lesson_id}/{where}: quote_source needs kind, text and provenance")
        _basis(lesson_id, where, b, src_ids)
        for item in b.get("items", []) if isinstance(b.get("items"), list) else []:
            if isinstance(item, dict):
                _basis(lesson_id, where, item, src_ids)


def _basis(lesson_id: str, where: str, item: dict, src_ids: set[str]) -> None:
    if "basis" in item and item["basis"] not in BASIS:
        raise ContentError(f"{lesson_id}/{where}: unknown basis {item['basis']!r}")
    if not set(item.get("src", [])) <= src_ids:
        raise ContentError(f"{lesson_id}/{where}: unknown source ids {item.get('src')}")


def _questions(lesson_id: str, where: str, qs: list, qids: set[str], figures: set[str] | None) -> None:
    for q in qs:
        try:
            assess.validate(q, figures)
        except assess.QuestionError as error:
            raise ContentError(f"{lesson_id}/{where}: {error}") from None
        if q["id"] in qids:
            raise ContentError(f"{lesson_id}: duplicate question id {q['id']}")
        qids.add(q["id"])


def validate_lesson(d: dict, figures: set[str] | None = None) -> None:
    """Fail loudly on content mistakes (the tests run this for every lesson)."""
    need = ["format", "id", "subject", "class", "term", "topic", "title", "short", "minutes", "version", "stage",
            "review_status", "curriculum", "introduction", "why", "objectives", "sections", "key_figures",
            "activities", "key_terms", "summary", "assessment", "further", "sources"]
    if d.get("stage") == "secondary":
        need += ["background", "cause_effect"]
    missing = [k for k in need if not d.get(k) and d.get(k) is not False]
    if missing:
        raise ContentError(f"{d.get('id')}: missing {missing}")
    lid = d["id"]
    if d["format"] != "interactive" or d["stage"] not in ("primary", "secondary") or d["term"] not in TERM_IDS:
        raise ContentError(f"{lid}: format, stage or term invalid")
    if d["review_status"] not in REVIEW_STATUSES:
        raise ContentError(f"{lid}: review_status must be one of {REVIEW_STATUSES}")
    if d["curriculum"].get("verification") not in VERIFICATION or not d["curriculum"].get("note"):
        raise ContentError(f"{lid}: curriculum needs verification and note")
    src_ids = {s["id"] for s in d["sources"]}
    if len(src_ids) != len(d["sources"]) or not all(s.get("title") and s.get("url", "").startswith("https://")
                                                    and s.get("kind") in SOURCE_KINDS for s in d["sources"]):
        raise ContentError(f"{lid}: every source needs a unique id, title, https url and known kind")
    if figures is None:
        figures = figure_names(d["subject"])
    _blocks(lid, "background", d.get("background", []), src_ids, figures)
    sec_ids = set()
    for s in d["sections"]:
        if not ID.fullmatch(s.get("id", "")) or s["id"] in sec_ids or not s.get("title"):
            raise ContentError(f"{lid}: bad or duplicate section id {s.get('id')!r}")
        sec_ids.add(s["id"])
        _blocks(lid, s["id"], s.get("blocks", []), src_ids, figures)
    for k in d["key_figures"]:
        if not k.get("name") or not k.get("text") or k.get("kind") not in ("person", "place", "event", "institution", "object"):
            raise ContentError(f"{lid}: key figure needs name, text and kind")
        _basis(lid, "key_figures", k, src_ids)
    for ce in d.get("cause_effect", []):
        if not all(ce.get(x) for x in ("cause", "effect", "significance")):
            raise ContentError(f"{lid}: cause_effect items need cause, effect and significance")
    qids: set[str] = set()
    acts = d["activities"]
    if len(acts) < 2:
        raise ContentError(f"{lid}: needs at least two interactive activities")
    act_ids = set()
    for a in acts:
        if a.get("type") not in ACTIVITY_TYPES or not ID.fullmatch(a.get("id", "")) or a["id"] in act_ids:
            raise ContentError(f"{lid}: bad activity {a.get('id')!r} ({a.get('type')!r})")
        act_ids.add(a["id"])
        if not a.get("title") or not a.get("instructions"):
            raise ContentError(f"{lid}/{a['id']}: needs title and instructions")
        _activity(lid, a, src_ids, qids, figures)
    if len(d["assessment"]) < ASSESS_MIN[d["stage"]]:
        raise ContentError(f"{lid}: needs at least {ASSESS_MIN[d['stage']]} assessment questions")
    _questions(lid, "assessment", d["assessment"], qids, figures)
    if not any(q["type"] not in ("mcq", "truefalse") for q in d["assessment"]):
        raise ContentError(f"{lid}: the assessment needs more than multiple-choice and true/false questions")
    if not all(isinstance(t, list) and len(t) == 2 and all(t) for t in d["key_terms"]):
        raise ContentError(f"{lid}: key_terms are [term, meaning] pairs")
    if not all(f.get("title") and f.get("why") for f in d["further"]):
        raise ContentError(f"{lid}: further learning items need title and why")


def _activity(lid: str, a: dict, src_ids: set[str], qids: set[str], figures: set[str] | None) -> None:
    kind, where = a["type"], f"{lid}/{a['id']}"
    if kind == "explorer":
        items = a.get("items") or []
        if len(items) < 3 or len({i["id"] for i in items}) != len(items) or not all(i.get("title") and i.get("text") for i in items):
            raise ContentError(f"{where}: explorer needs at least three items with id, title and text")
        if a.get("figure") and figures is not None and a["figure"] not in figures:
            raise ContentError(f"{where}: unknown figure {a['figure']!r}")
        for i in items:
            _basis(lid, a["id"], i, src_ids)
    elif kind == "timeline":
        events = a.get("events") or []
        if len(events) < 4 or not all(e.get("title") and e.get("when") and isinstance(e.get("sort"), (int, float))
                                      and isinstance(e.get("approx"), bool) and e.get("background") for e in events):
            raise ContentError(f"{where}: timeline needs at least four events with title, when, sort, approx, background")
        if [e["sort"] for e in events] != sorted(e["sort"] for e in events):
            raise ContentError(f"{where}: timeline events must be listed in chronological order")
        for e in events:
            _basis(lid, a["id"], e, src_ids)
    elif kind == "investigation":
        sources = a.get("sources") or []
        if len(sources) < 3 or not all(s.get("kind") in EVIDENCE_KINDS and s.get("title") and s.get("text") and s.get("provenance")
                                       for s in sources):
            raise ContentError(f"{where}: investigation needs at least three sources with kind, title, text, provenance")
        for s in sources:
            _basis(lid, a["id"], s, src_ids)
        if len(a.get("questions") or []) < 2:
            raise ContentError(f"{where}: investigation needs at least two questions")
        _questions(lid, a["id"], a["questions"], qids, figures)
    elif kind == "story":
        chapters = a.get("chapters") or []
        if len(chapters) < 3 or not all(c.get("title") and c.get("text") and c.get("question") for c in chapters):
            raise ContentError(f"{where}: story needs at least three chapters with title, text and a question")
        if not a.get("note"):
            raise ContentError(f"{where}: story needs a note on what is documented")
        _questions(lid, a["id"], [c["question"] for c in chapters], qids, figures)
    elif kind == "practice":
        if not a.get("questions"):
            raise ContentError(f"{where}: practice needs questions")
        _questions(lid, a["id"], a["questions"], qids, figures)
    elif kind == "diagram":
        nodes = a.get("nodes") or []
        ids = {n.get("id") for n in nodes}
        if len(nodes) < 3 or len(ids) != len(nodes) or not all(n.get("title") and n.get("text") for n in nodes):
            raise ContentError(f"{where}: diagram needs at least three nodes with id, title and text")
        if not all(set(n.get("links", [])) <= ids for n in nodes):
            raise ContentError(f"{where}: diagram links must point to nodes")
        if "questions" in a:
            _questions(lid, a["id"], a["questions"], qids, figures)


# --------------------------------------------------------------------------- pages

def pages(d: dict) -> list[dict]:
    """The lesson as pages (stable ids, so a student's reading position survives corrections)."""
    out = [{"kind": "intro", "id": "intro", "title": "Introduction and objectives"}]
    if d.get("background"):
        out.append({"kind": "background", "id": "background", "title": "Background"})
    out += [{"kind": "section", "id": s["id"], "title": s["title"], "section": s} for s in d["sections"]]
    out.append({"kind": "figures", "id": "key-figures", "title": "Key people, places and events"})
    if d.get("cause_effect"):
        out.append({"kind": "cause", "id": "cause-effect", "title": "Cause and effect"})
    out += [{"kind": "activity", "id": "act-" + a["id"], "title": a["title"], "activity": a} for a in d["activities"]]
    out.append({"kind": "terms", "id": "key-terms", "title": "Key terms"})
    out.append({"kind": "summary", "id": "summary", "title": "Summary"})
    out.append({"kind": "check", "id": "knowledge-check", "title": "Knowledge check"})
    out.append({"kind": "further", "id": "further", "title": "Further learning and sources"})
    return out


def question(d: dict, qid: str) -> dict:
    for q in d["assessment"]:
        if q["id"] == qid:
            return q
    for a in d["activities"]:
        for q in a.get("questions", []) + [c["question"] for c in a.get("chapters", [])]:
            if q["id"] == qid:
                return q
    raise ContentError(f"{d['id']}: unknown question {qid!r}")


def all_questions(d: dict) -> list[dict]:
    out = list(d["assessment"])
    for a in d["activities"]:
        out += a.get("questions", []) + [c["question"] for c in a.get("chapters", [])]
    return out


def page_text(d: dict, page: dict) -> str:
    """Plain text of a page for read-aloud (headings, paragraphs and lists; no markup)."""
    def clean(s) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"\1", str(s))

    def blocks(bs) -> list[str]:
        out = []
        for b in bs:
            if b["type"] in ("p", "h", "note"):
                out.append(clean(b["text"]))
            elif b["type"] == "list":
                out += [clean(i) for i in b["items"]]
            elif b["type"] == "cards":
                out += [clean(i["title"]) + ". " + clean(i["text"]) for i in b["items"]]
            elif b["type"] == "quote_source":
                out.append(clean(b["text"]))
        return out

    kind = page["kind"]
    parts = [page["title"]]
    if kind == "intro":
        parts += [clean(p) for p in d["introduction"]] + [clean(d["why"])] + ["Learning objectives."] + [clean(o) for o in d["objectives"]]
    elif kind == "background":
        parts += blocks(d["background"])
    elif kind == "section":
        parts += blocks(page["section"]["blocks"])
    elif kind == "figures":
        parts += [f"{k['name']}. {clean(k['text'])}" for k in d["key_figures"]]
    elif kind == "cause":
        parts += [f"Cause: {clean(c['cause'])} Effect: {clean(c['effect'])} Why it matters: {clean(c['significance'])}"
                  for c in d["cause_effect"]]
    elif kind == "activity":
        parts.append(clean(page["activity"]["instructions"]))
    elif kind == "terms":
        parts += [f"{t}: {clean(m)}" for t, m in d["key_terms"]]
    elif kind == "summary":
        parts += [clean(s) for s in d["summary"]]
    elif kind == "further":
        parts += [f"{f['title']}. {clean(f['why'])}" for f in d["further"]]
    return " ".join(p.strip() for p in parts if p)


# --------------------------------------------------------------------------- progress (records as in core.school)

def _done(rec) -> bool:
    return bool(rec and rec.get("completed"))


def progress_by(subject_id: str, progress: dict, class_id: str | None = None, term_id: str | None = None) -> dict:
    ids = lesson_ids(subject_id, class_id, term_id)
    done = sum(1 for i in ids if _done(progress.get(i)))
    started = sum(1 for i in ids if progress.get(i))
    return {"lessons": len(ids), "completed": done, "started": started,
            "percent": round(100 * done / len(ids)) if ids else 0}


def suggested_next(subject_id: str, progress: dict) -> str | None:
    """The most recently used unfinished lesson; else the first not completed in the class studied most recently;
    else the first not completed in curriculum order."""
    ids = lesson_ids(subject_id)
    if not ids:
        return None
    open_ = [(progress[i].get("updated_at", ""), i) for i in ids if progress.get(i) and not _done(progress.get(i))]
    if open_:
        return max(open_)[1]
    recent = sorted(((progress[i].get("updated_at", ""), i) for i in ids if progress.get(i)), reverse=True)
    if recent:
        cls = lesson(subject_id, recent[0][1])["class"]
        same = [i for i in ids if lesson(subject_id, i)["class"] == cls and not _done(progress.get(i))]
        if same:
            return same[0]
    return next((i for i in ids if not _done(progress.get(i))), ids[0])


def record_check(rec: dict | None, session: dict) -> dict:
    """A finished knowledge check, in the same record fields as Geography practice (no new columns): best and last
    are the marked score scaled to 10; answered and correct count marked questions only (written answers are
    self-checked and never counted). Completion is never changed by a score."""
    from datetime import datetime, timezone
    t = assess.tally(session)
    rec = dict(rec or {})
    score = assess.score_out_of(session, 10)
    rec["last"] = score
    rec["best"] = max(rec.get("best", 0), score) if rec.get("attempts") else score
    rec["attempts"] = rec.get("attempts", 0) + 1
    rec["answered"] = rec.get("answered", 0) + t["marked"]
    rec["correct"] = rec.get("correct", 0) + t["correct"]
    rec["practised_at"] = rec["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return rec


def class_id_of(subject_id: str, class_title: str) -> str | None:
    return next((c["id"] for c in classes(subject_id) if c["title"] == class_title), None)
