"""School Learning — interactive subjects: Nigerian History (Primary–JSS) and Citizenship and Heritage Studies (SSS).

Covers the curriculum metadata, content validation, the assessment engine, progress (by class and term, suggested
next lesson, the knowledge-check record), device storage for several subjects, read-aloud, Geography compatibility,
separation from rewards and Friends & Family 10, and the real app (Streamlit AppTest): class selection, terms, lesson
loading, every activity type, the knowledge check, anonymous use, empty and incomplete content.
"""
import ast
import copy
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import assess, lessons, school  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
NH, CHS, GEO = "nigerian-history", "citizenship-heritage", "geography"
SLICE = {NH: ["p4-historical-sites", "jss1-sources-of-history"], CHS: ["sss1-citizenship"]}


def all_lessons():
    for subject_id, ids in SLICE.items():
        for lesson_id in ids:
            yield subject_id, school.lesson(subject_id, lesson_id)


# =========================================================================== curriculum metadata

class CurriculumTests(unittest.TestCase):
    def test_subjects_are_available_and_interactive(self):
        for subject_id in (NH, CHS):
            s = school.subject(subject_id)
            self.assertEqual((s["status"], s["engine"]), ("available", "interactive"))
            self.assertTrue(school.interactive(subject_id))
        self.assertFalse(school.interactive(GEO))
        self.assertEqual({s["id"] for s in school.subjects()}, {GEO, NH, CHS})

    def test_classes_terms_and_topics(self):
        self.assertEqual([c["title"] for c in lessons.classes(NH)],
                         [f"Primary {n}" for n in range(1, 7)] + ["JSS 1", "JSS 2", "JSS 3"])
        self.assertEqual([c["title"] for c in lessons.classes(CHS)], ["SSS 1", "SSS 2", "SSS 3"])
        for subject_id in (NH, CHS):
            cur = lessons.curriculum(subject_id)
            self.assertIn("fme-2025", {s["id"] for s in cur["sources"]})
            for c in cur["classes"]:
                for t in c["terms"]:
                    self.assertIn(t["id"], lessons.TERM_IDS)
                    for tp in t["topics"]:
                        # nothing is presented as checked against the official NERDC document
                        self.assertIn(tp["verification"], ("scheme", "enrichment"), tp["id"])
        self.assertEqual(lessons.topic_count(CHS), 9)
        for cid in ("sss-2", "sss-3"):                      # not yet checked: no invented topics, an honest note
            c = lessons.class_(CHS, cid)
            self.assertEqual(lessons.topics(CHS, cid), [])
            self.assertTrue(c["note"])

    def test_lessons_are_attached_in_curriculum_order(self):
        self.assertEqual(lessons.lesson_ids(NH), SLICE[NH])
        self.assertEqual(lessons.lesson_ids(NH, "primary-4", "third"), ["p4-historical-sites"])
        self.assertEqual(lessons.lesson_ids(NH, "jss-1", "first"), ["jss1-sources-of-history"])
        self.assertEqual(lessons.lesson_ids(NH, "jss-1", "second"), [])
        self.assertEqual(lessons.lesson_ids(NH, "primary-1"), [])
        self.assertEqual(lessons.lesson_ids(CHS), SLICE[CHS])
        self.assertEqual(lessons.counts(NH), {"lessons": 2, "reviewed": 0, "draft": 2, "topics": lessons.topic_count(NH),
                                              "classes": ["Primary 4", "JSS 1"]})

    def test_no_exam_preparation_or_official_claims_for_chs(self):
        texts = [json.dumps(school.subject(CHS), ensure_ascii=False), json.dumps(lessons.curriculum(CHS), ensure_ascii=False),
                 json.dumps(school.lesson(CHS, "sss1-citizenship"), ensure_ascii=False)]
        for text in texts:
            low = text.lower()
            self.assertNotIn("wassce", low)
            self.assertNotIn("waec", low)
            self.assertNotIn("exam preparation", low)
        self.assertIn("does not prepare for any examination", lessons.curriculum(CHS)["note"])
        for subject_id, d in all_lessons():
            low = json.dumps(d, ensure_ascii=False).lower()
            for claim in ("approved by nerdc", "endorsed by nerdc", "official nerdc syllabus", "certified by", "approved by the ministry"):
                self.assertNotIn(claim, low, d["id"])

    def test_curriculum_validation_rejects_mistakes(self):
        good = lessons.curriculum(NH)
        bad = copy.deepcopy(good)
        bad["classes"][0]["terms"][0]["topics"][0]["verification"] = "official-ish"
        with self.assertRaises(lessons.ContentError):
            lessons.validate_curriculum(bad)
        bad = copy.deepcopy(good)
        bad["classes"][0]["terms"][0]["topics"][0]["sources"] = ["no-such-source"]
        with self.assertRaises(lessons.ContentError):
            lessons.validate_curriculum(bad)


# =========================================================================== content

class ContentTests(unittest.TestCase):
    def test_vertical_slice_is_complete_and_valid(self):
        for subject_id, d in all_lessons():
            lessons.validate_lesson(d)
            self.assertEqual(d["review_status"], "draft", d["id"])        # not yet reviewed: never presented as finished
            self.assertFalse(lessons.finished(d))
            cls = lessons.class_(subject_id, lessons.class_id_of(subject_id, d["class"]))
            self.assertIsNotNone(cls, d["id"])
            self.assertEqual(d["stage"], "primary" if d["class"].startswith("Primary") else "secondary")
            topic = next(t for t in lessons.topics(subject_id) if t["id"] == d["topic"])
            self.assertIn(d["id"], topic["lessons"])
            kinds = [p["kind"] for p in lessons.pages(d)]
            for part in ("intro", "section", "figures", "activity", "terms", "summary", "check", "further"):
                self.assertIn(part, kinds, d["id"])                       # parts A–K
            self.assertGreaterEqual(len(d["activities"]), 2)
            types = {q["type"] for q in d["assessment"]}
            self.assertTrue(types - {"mcq", "truefalse"})
            ids = [p["id"] for p in lessons.pages(d)]
            self.assertEqual(len(ids), len(set(ids)))

    def test_assessment_variety_across_the_slice(self):
        types = set()
        for _, d in all_lessons():
            types |= {q["type"] for q in lessons.all_questions(d)}
        self.assertEqual(types, set(assess.TYPES))                     # every question type is used in real content

    def test_activity_types_used(self):
        used = {a["type"] for _, d in all_lessons() for a in d["activities"]}
        self.assertEqual(used, set(lessons.ACTIVITY_TYPES))

    def test_stories_have_no_invented_dialogue(self):
        for _, d in all_lessons():
            for a in d["activities"]:
                if a["type"] != "story":
                    continue
                self.assertIn("No conversations or quotations have been made up", a["note"])
                for c in a["chapters"]:
                    for p in c["text"]:
                        self.assertFalse(re.search(r"[“”\"]", p), p)

    def test_dates_are_labelled_exact_or_approximate(self):
        for _, d in all_lessons():
            for a in d["activities"]:
                if a["type"] == "timeline":
                    for e in a["events"]:
                        if e["approx"]:
                            self.assertRegex(e["when"], r"c\.|about|probably|centur|\d+s", e["title"])
            for k in d["key_figures"]:
                if k.get("approx"):
                    self.assertTrue(k.get("basis") in ("approximate", "interpretation", "tradition"), k["name"])

    def test_map_shows_modern_nigeria_only(self):
        svg = lessons.figure(NH, "ng_historic_sites")
        self.assertIn("Modern Nigeria (for reference)", svg)
        self.assertIn("site positions approximate", svg)

    def test_figures_and_sources_resolve(self):
        for subject_id, d in all_lessons():
            names = lessons.figure_names(d["subject"])
            for q in lessons.all_questions(d):
                if q.get("figure"):
                    self.assertIn(q["figure"], names)
            for s in d["sources"]:
                self.assertTrue(s["url"].startswith("https://"))

    def test_validation_rejects_broken_lessons(self):
        d = school.lesson(NH, "jss1-sources-of-history")
        cases = []
        x = copy.deepcopy(d); x["activities"] = x["activities"][:1]; cases.append(x)
        x = copy.deepcopy(d); x["review_status"] = "approved"; cases.append(x)
        x = copy.deepcopy(d); x["background"] = []; cases.append(x)                         # secondary needs background
        x = copy.deepcopy(d); x["sections"][0]["blocks"][0]["src"] = ["nowhere"]; cases.append(x)
        x = copy.deepcopy(d); x["assessment"] = [q for q in x["assessment"] if q["type"] in ("mcq", "truefalse")] * 3; cases.append(x)
        x = copy.deepcopy(d)
        tl = next(a for a in x["activities"] if a["type"] == "timeline"); tl["events"].reverse(); cases.append(x)
        x = copy.deepcopy(d)
        st_ = next(a for a in x["activities"] if a["type"] == "story"); st_.pop("note"); cases.append(x)
        x = copy.deepcopy(d)
        sc = next(q for q in x["assessment"] if q["type"] == "scenario")
        for o in sc["options"]:
            o["verdict"] = "best"
        cases.append(x)
        x = copy.deepcopy(d)
        im = next(q for q in x["assessment"] if q["type"] == "image"); im["figure"] = "missing_figure"; cases.append(x)
        for n, bad in enumerate(cases):
            with self.subTest(case=n), self.assertRaises(lessons.ContentError):
                lessons.validate_lesson(bad)

    def test_empty_and_unknown_content_is_safe(self):
        with self.assertRaises(ValueError):            # ContentError (a ValueError; other tests may reload core modules)
            school.lesson(NH, "no-such-lesson")
        self.assertEqual(lessons.lesson_ids(CHS, "sss-2"), [])
        self.assertEqual(lessons.progress_by(CHS, {}, "sss-2"), {"lessons": 0, "completed": 0, "started": 0, "percent": 0})
        self.assertEqual(lessons.topics(NH, "no-such-class"), [])


# =========================================================================== assessment engine

class AssessTests(unittest.TestCase):
    def q(self, qid):
        for _, d in all_lessons():
            for q in lessons.all_questions(d):
                if q["id"] == qid:
                    return q
        raise KeyError(qid)

    def test_choice_types_explain_right_and_wrong(self):
        q = self.q("jss1-q1")
        right = assess.check(q, q["answer"])
        wrong = assess.check(q, (q["answer"] + 1) % len(q["options"]))
        self.assertTrue(right.correct)
        self.assertFalse(wrong.correct)
        self.assertIn("Correct answer:", wrong.explanation)
        self.assertIn(q["options"][(q["answer"] + 1) % len(q["options"])]["why"], wrong.explanation)

    def test_true_false_fill_match_order(self):
        tf = self.q("jss1-q2")
        self.assertTrue(assess.check(tf, False).correct)
        self.assertFalse(assess.check(tf, True).correct)
        fill = self.q("jss1-q3")
        self.assertTrue(assess.check(fill, "  Corroboration. ").correct)
        self.assertFalse(assess.check(fill, "evidence").correct)
        self.assertTrue(assess.check(self.q("sss1-q2"), "Years").correct)
        m = self.q("jss1-q7")
        good = {left: right for left, right in m["pairs"]}
        self.assertTrue(assess.check(m, good).correct)
        swapped = dict(good)
        a, b = list(good)[:2]
        swapped[a], swapped[b] = good[b], good[a]
        r = assess.check(m, swapped)
        self.assertFalse(r.correct)
        self.assertEqual([ok for *_, ok in r.detail], [False, False, True])
        o = self.q("jss1-q5")
        self.assertTrue(assess.check(o, list(o["items"])).correct)
        self.assertFalse(assess.check(o, list(reversed(o["items"]))).correct)
        self.assertNotEqual(assess.shuffled_order(o, seed=1), o["items"])

    def test_scenario_and_short(self):
        sc = self.q("sss1-sc-1")
        best = next(i for i, o in enumerate(sc["options"]) if o["verdict"] == "best")
        self.assertTrue(assess.check(sc, best).correct)
        poor = next(i for i, o in enumerate(sc["options"]) if o["verdict"] == "poor")
        r = assess.check(sc, poor)
        self.assertFalse(r.correct)
        self.assertIn("The best response:", r.explanation)
        short = self.q("sss1-q10")
        r = assess.check(short, "Rights and duties go together because …")
        self.assertEqual((r.correct, r.marked), (None, False))       # never auto-marked
        self.assertIn("not marked automatically", r.explanation)

    def test_map_and_image_questions(self):
        for qid in ("p4-q2", "jss1-q4"):
            q = self.q(qid)
            self.assertTrue(assess.check(q, q["answer"]).correct)

    def test_session_answers_once_and_tallies_marked_only(self):
        d = school.lesson(CHS, "sss1-citizenship")
        s = assess.new_session(d["id"], d["assessment"], seed=1)
        for i, qid in enumerate(s["items"]):
            q = lessons.question(d, qid)
            resp = {"mcq": q.get("answer"), "truefalse": q.get("answer"), "fill": (q.get("answers") or [""])[0],
                    "match": {l: r for l, r in q.get("pairs", [])}, "order": q.get("items"),
                    "scenario": next((n for n, o in enumerate(q.get("options", [])) if o.get("verdict") == "best"), 0),
                    "short": "my answer"}[q["type"]]
            self.assertIsNotNone(assess.answer(s, q, i, resp))
            self.assertIsNone(assess.answer(s, q, i, resp))               # a double click cannot answer twice
            self.assertTrue(assess.advance(s, i))
        self.assertTrue(s["finished"])
        t = assess.tally(s)
        self.assertEqual((t["marked"], t["correct"], t["written"], t["percent"]), (9, 9, 1, 100))
        self.assertEqual(assess.score_out_of(s), 10)

    def test_validate_rejects_malformed_questions(self):
        bad = [{"id": "x1", "type": "mcq", "q": "?", "options": [{"text": "a", "why": "w"}], "answer": 0},
               {"id": "x2", "type": "short", "prompt": "?", "model": "m", "points": ["one"]},
               {"id": "x3", "type": "match", "q": "?", "pairs": [["a", "b"], ["c", "d"]], "explain": "e"},
               {"id": "x4", "type": "image", "q": "?", "figure": "f", "options": [{"text": "a", "why": "w"}, {"text": "b", "why": "w"}], "answer": 0},
               {"id": "x5", "type": "dragdrop"}]
        for q in bad:
            with self.subTest(q=q["id"]), self.assertRaises(assess.QuestionError):
                assess.validate(q, figures={"f"})


# =========================================================================== progress

class ProgressTests(unittest.TestCase):
    def finished_session(self, d, right: bool):
        s = assess.new_session(d["id"], d["assessment"], seed=2)
        for i, qid in enumerate(s["items"]):
            q = lessons.question(d, qid)
            if q["type"] in ("mcq", "map", "image"):
                resp = q["answer"] if right else (q["answer"] + 1) % len(q["options"])
            elif q["type"] == "truefalse":
                resp = q["answer"] if right else not q["answer"]
            elif q["type"] == "fill":
                resp = q["answers"][0] if right else "zzz"
            elif q["type"] == "match":
                resp = {l: r for l, r in q["pairs"]} if right else {}
            elif q["type"] == "order":
                resp = q["items"] if right else list(reversed(q["items"]))
            elif q["type"] == "scenario":
                resp = next(n for n, o in enumerate(q["options"]) if (o["verdict"] == "best") == right)
            else:
                resp = "text"
            assess.answer(s, q, i, resp)
            assess.advance(s, i)
        return s

    def test_record_check_uses_existing_fields(self):
        d = school.lesson(NH, "p4-historical-sites")
        rec = lessons.record_check(None, self.finished_session(d, False))
        self.assertEqual((rec["best"], rec["last"], rec["attempts"], rec["answered"], rec["correct"]), (0, 0, 1, 8, 0))
        self.assertIn("Best practice score 0/10", school.revision_reasons(rec))
        rec = lessons.record_check(rec, self.finished_session(d, True))
        self.assertEqual((rec["best"], rec["last"], rec["attempts"], rec["answered"], rec["correct"]), (10, 10, 2, 16, 8))
        self.assertEqual(school.revision_reasons(rec), [])
        from core import school_store
        row = school_store.row("a" * 64, NH, d["id"], rec)
        self.assertTrue(set(row) <= {"user_id", "subject", "lesson_id", *school_store.COLUMNS})   # no new columns
        self.assertEqual(school.clean_record(rec, len(lessons.pages(d)))["best"], 10)

    def test_progress_by_class_and_term_and_suggested_next(self):
        prog = {}
        self.assertEqual(lessons.suggested_next(NH, prog), "p4-historical-sites")
        d = school.lesson(NH, "jss1-sources-of-history")
        pages = lessons.pages(d)
        prog["jss1-sources-of-history"] = school.move_to(None, 3, len(pages), pages)
        self.assertEqual(lessons.suggested_next(NH, prog), "jss1-sources-of-history")
        self.assertEqual(lessons.progress_by(NH, prog, "jss-1", "first")["started"], 1)
        prog["jss1-sources-of-history"] = school.set_completed(school.move_to(prog["jss1-sources-of-history"], len(pages) - 1, len(pages), pages), len(pages))
        p = lessons.progress_by(NH, prog, "jss-1")
        self.assertEqual((p["lessons"], p["completed"], p["percent"]), (1, 1, 100))
        self.assertEqual(lessons.progress_by(NH, prog)["percent"], 50)
        self.assertEqual(lessons.suggested_next(NH, prog), "p4-historical-sites")
        o = school.overview(NH, prog)
        self.assertEqual((o["lessons"], o["completed"]), (2, 1))

    def test_page_text_for_read_aloud_has_no_markup(self):
        for _, d in all_lessons():
            for p in lessons.pages(d):
                text = lessons.page_text(d, p)
                self.assertTrue(text.startswith(p["title"]))
                self.assertNotIn("**", text)
                self.assertNotIn("<", text)


# =========================================================================== device storage, compatibility, separation

class DeviceAndCompatibilityTests(unittest.TestCase):
    def test_device_cookie_keeps_every_subject(self):
        from core import cookies
        from ui import school as ui
        all_prog = {
            GEO: {"ng-climate": {"page": 2, "page_id": "rainfall", "furthest": 2, "updated_at": "2026-10-20T08:00:00+00:00"}},
            NH: {"jss1-sources-of-history": {"page": 4, "page_id": "examining-sources", "furthest": 6, "best": 7, "attempts": 1,
                                             "answered": 9, "correct": 6, "updated_at": "2026-10-26T08:00:00+00:00"},
                 "bogus": {"page": 1}},
            CHS: {"sss1-citizenship": {"page": 1, "furthest": 1, "revision": True, "updated_at": "2026-10-25T08:00:00+00:00"}},
            "not-a-subject": {"x": {"page": 1}},
        }
        value = ui.device_pack_all(all_prog)
        self.assertTrue(cookies.NAMES["we_school"].match(value))
        back = ui.device_unpack_all(value)
        self.assertEqual(set(back), {GEO, NH, CHS})
        self.assertEqual(set(back[NH]), {"jss1-sources-of-history"})
        rec = back[NH]["jss1-sources-of-history"]
        self.assertEqual((rec["page_id"], rec["best"], rec["correct"]), ("examining-sources", 7, 6))
        self.assertTrue(back[CHS]["sss1-citizenship"]["revision"])
        with mock.patch.object(ui, "SS", {"school_subject": GEO}):            # a version 1 cookie is still read
            v1 = ui.device_pack(all_prog[GEO])
        self.assertEqual(set(ui.device_unpack_all(v1)), {GEO})
        for junk in ("", "%%%", "eyJ2IjoyLCJwIjpbXX0", "WyJ4Il0"):
            self.assertEqual(ui.device_unpack_all(junk), {})

    def test_device_cookie_size_limit_keeps_newest(self):
        from ui import school as ui
        big = {NH: {}}
        with mock.patch.object(ui, "DEVICE_MAX", 160):
            big[NH]["p4-historical-sites"] = {"page": 1, "page_id": "intro", "updated_at": "2026-01-01T00:00:00+00:00"}
            big[NH]["jss1-sources-of-history"] = {"page": 1, "page_id": "intro", "updated_at": "2026-10-01T00:00:00+00:00"}
            value = ui.device_pack_all(big)
            self.assertLessEqual(len(value), 160)
            back = ui.device_unpack_all(value)
        self.assertEqual(set(back.get(NH, {})), {"jss1-sources-of-history"})

    def test_geography_is_unchanged(self):
        self.assertEqual(len(school.lesson_ids(GEO)), 7)
        d = school.lesson(GEO, "ng-climate")
        self.assertNotEqual(d.get("format"), "interactive")
        self.assertEqual([p["kind"] for p in school.pages(d)][-4:], ["definitions", "examples", "check", "review"])
        self.assertEqual(school.topic_count(GEO), 34)
        self.assertEqual(school.subject(GEO)["level"], "SSS 1–3 · WAEC preparation")

    def test_new_school_code_never_touches_rewards(self):
        banned = {"rewards", "rewards_store", "rewards_hooks", "withdrawals", "badges", "quiz", "records", "daily", "founding",
                  "analytics", "founding_ui", "withdraw_ui", "pilot_rewards", "ff10_ui", "owner_ff10", "state", "pages"}
        for path in ("core/lessons.py", "core/assess.py", "ui/school_interactive.py", "ui/school.py", "core/school.py"):
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertFalse(names & banned, f"{path} imports {names & banned}")
            calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            self.assertFalse(calls & {"ping", "note_view", "note_answer", "note_quiz", "note_country", "explored", "_record"}, path)

    def test_mobile_layout_rules(self):
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        start = css.index("/* School Learning — interactive subjects")
        mine = css[start:]
        phone = mine[mine.index("@media (max-width:640px)"):]
        for rule in (".sx-cause { grid-template-columns:1fr; }", ".sx-when { min-width:0; width:100%; }"):
            self.assertIn(rule, phone)
        for grid in (".sx-sources", ".sx-figures", ".sx-diagram", ".sx-facts"):
            self.assertRegex(mine, re.escape(grid) + r" \{[^}]*auto-fit, minmax\(")        # reflows from one to many columns
        self.assertIn('[class*="st-key-sl_card_btns_"] { gap:8px !important; flex-wrap:wrap !important;', mine)
        self.assertIn("min-height:40px", mine)                                          # read-aloud buttons are touch-sized
        self.assertNotIn("draggable", (ROOT / "ui" / "school_interactive.py").read_text(encoding="utf-8"))

    def test_read_aloud_never_autoplays(self):
        from ui import school_interactive as ix
        captured = []
        with mock.patch.object(ix.st, "html", side_effect=lambda body, **kw: captured.append((body, kw))):
            ix.read_aloud("p4-intro", "Hello. This is a test.")
        body, kw = captured[0]
        self.assertTrue(kw.get("unsafe_allow_javascript"))
        script = body[body.index("<script>") + 8:body.index("</script>")]
        self.assertNotIn("<", script)                                     # the HTML cleaner drops '<'
        self.assertNotIn("autoplay", body.lower())
        self.assertIsNone(re.search(r"\bsay\(\)", script))               # speech starts only from a button press
        self.assertIn("addEventListener('click'", script)
        for label in ("Listen", "Pause", "Resume", "Restart", "Stop"):
            self.assertIn(label, body)
        self.assertIn('aria-live="polite"', body)


# =========================================================================== the real app

def answer_for(q: dict, right: bool = True):
    """Widget values that answer a question rightly (or wrongly)."""
    kind = q["type"]
    if kind in ("mcq", "map", "image"):
        return q["answer"] if right else (q["answer"] + 1) % len(q["options"])
    if kind == "scenario":
        return next(n for n, o in enumerate(q["options"]) if (o["verdict"] == "best") == right)
    if kind == "truefalse":
        return "True" if q["answer"] == right else "False"
    if kind == "fill":
        return q["answers"][0] if right else "something else"
    if kind == "short":
        return "A written answer."
    return None


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class InteractiveAppTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=90)
        at.session_state["page"] = "Learn"
        at.session_state["learn_tab_saved"] = "school"
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def clean(self, at):
        self.assertEqual([e.value for e in at.exception], [])

    def keys(self, at, prefix):
        return [b.key for b in at.button if b.key and b.key.startswith(prefix)]

    def text(self, at):
        return "\n".join(m.value for m in at.markdown)

    def fill(self, at, q, k, right=True):
        kind = q["type"]
        if kind in ("mcq", "map", "image", "scenario", "truefalse"):
            at.radio(key=k + "_r").set_value(answer_for(q, right))
        elif kind in ("fill",):
            at.text_input(key=k + "_t").input(answer_for(q, right))
        elif kind == "short":
            at.text_area(key=k + "_t").input(answer_for(q, right))
        elif kind == "match":
            rights = [r for _, r in q["pairs"]]
            for i, (_, r) in enumerate(q["pairs"]):
                at.selectbox(key=f"{k}_m{i}").set_value(r if right else rights[(i + 1) % len(rights)])
        elif kind == "order":
            at.session_state[k + "_order"] = list(q["items"]) if right else list(reversed(q["items"]))
        at.button(key=f"{k}_check").click().run()

    def open_lesson(self, at, subject_id, class_id, lesson_id):
        at.button(key=f"sl_open_{subject_id}").click().run()
        at.button_group(key=f"sx_class_{subject_id}").set_value(class_id).run()
        at.button(key=f"sl_read_{lesson_id}").click().run()
        self.clean(at)

    def go_to(self, at, lesson_id, page_id):
        d = school.lesson(at.session_state["school_subject"], lesson_id)
        at.selectbox(key=f"sl_jump_{lesson_id}").select(lessons.pages(d).index(next(p for p in lessons.pages(d) if p["id"] == page_id))).run()
        self.clean(at)

    def test_home_cards_for_all_three_subjects(self):
        at = self.new()
        self.clean(at)
        self.assertEqual(self.keys(at, "sl_open_"), ["sl_open_geography", "sl_open_nigerian-history", "sl_open_citizenship-heritage"])
        self.assertEqual(self.keys(at, "sl_cont_"), ["sl_cont_geography", "sl_cont_nigerian-history", "sl_cont_citizenship-heritage"])
        page = self.text(at)
        self.assertNotIn("Coming soon", page)
        for expected in ("2 lessons", "0 reviewed · 2 draft", "1 lesson", "Primary 4", "JSS 1", "SSS 1", "topics",
                         "does not earn points, badges, rewards or money"):
            self.assertIn(expected, page)
        self.assertTrue(any("You are learning as a guest" in m.value for m in at.markdown))   # anonymous use, honest storage note
        at.text_input(key="sl_subject_search").input("citizenship").run()
        self.assertEqual(self.keys(at, "sl_open_"), ["sl_open_citizenship-heritage"])

    def test_class_and_term_navigation_with_empty_and_incomplete_content(self):
        at = self.new()
        at.button(key="sl_open_nigerian-history").click().run()
        self.clean(at)
        self.assertEqual(at.session_state["sx_class_nigerian-history"], "primary-4")        # first class that has lessons
        self.assertEqual(at.session_state["sx_term_nigerian-history"], "third")
        self.assertEqual(self.keys(at, "sl_read_"), ["sl_read_p4-historical-sites"])
        at.button_group(key="sx_class_nigerian-history").set_value("primary-1").run()
        self.clean(at)
        self.assertEqual(self.keys(at, "sl_read_"), [])
        self.assertIn("Lesson not written yet", self.text(at))
        at.button_group(key="sx_class_nigerian-history").set_value("primary-5").run()
        self.clean(at)
        self.assertEqual(at.session_state["sx_term_nigerian-history"], "unassigned")
        self.assertTrue(any("do not divide this class's topics into terms" in c.value for c in at.caption))
        at.button_group(key="sx_class_nigerian-history").set_value("jss-1").run()
        self.assertEqual(at.session_state["sx_term_nigerian-history"], "first")
        self.assertEqual(self.keys(at, "sl_read_"), ["sl_read_jss1-sources-of-history"])
        self.assertIn("Covered in the lesson", self.text(at))                             # one lesson, several topics
        at.button_group(key="sx_term_nigerian-history").set_value("second").run()
        self.clean(at)
        self.assertEqual(self.keys(at, "sl_read_"), [])
        at.button(key="sl_back_home").click().run()
        at.button(key="sl_open_citizenship-heritage").click().run()
        at.button_group(key="sx_class_citizenship-heritage").set_value("sss-2").run()
        self.clean(at)
        self.assertIn("will be added once they can be checked", self.text(at))

    def test_full_primary_lesson_and_knowledge_check(self):
        at = self.new()
        before = {k: (at.session_state[k] if k in at.session_state else None) for k in ("points", "earned_badges", "quiz", "stats", "streak")}
        self.open_lesson(at, NH, "primary-4", "p4-historical-sites")
        self.assertTrue(at.button(key="sl_complete").disabled)
        d = school.lesson(NH, "p4-historical-sites")
        seen = 0
        while not at.button(key="sl_next_page").disabled:
            at.button(key="sl_next_page").click().run()
            self.clean(at)
            seen += 1
        self.assertEqual(seen, len(lessons.pages(d)) - 1)
        self.assertIn("Sources used in this lesson", self.text(at))
        self.go_to(at, d["id"], "knowledge-check")
        at.button(key=f"sx_check_start_{d['id']}").click().run()
        session = at.session_state["sx_checks"][d["id"]]
        for i, qid in enumerate(session["items"]):
            q = lessons.question(d, qid)
            k = f'{session["key"]}_{i}'
            self.fill(at, q, k, right=(i % 2 == 0))
            self.clean(at)
            if q["type"] == "short":
                self.assertIn("Model answer", self.text(at))
            at.button(key=f"sx_check_next_{d['id']}_{i}").click().run()
            self.clean(at)
        rec = at.session_state["school_progress"][NH][d["id"]]
        t = assess.tally(at.session_state["sx_checks"][d["id"]])
        self.assertEqual((rec["attempts"], rec["answered"], rec["correct"]), (1, t["marked"], t["correct"]))
        self.assertEqual(rec["best"], round(10 * t["correct"] / t["marked"]))
        self.assertIn("marked questions correct", self.text(at))
        at.button(key="sl_complete").click().run()
        self.assertTrue(at.session_state["school_progress"][NH][d["id"]]["completed"])
        after = {k: (at.session_state[k] if k in at.session_state else None) for k in before}
        self.assertEqual(before, after)                                                  # no points, badges or quiz state
        at.button(key="sl_lesson_progress").click().run()
        self.clean(at)
        page = self.text(at)
        for expected in ("By class and term", "Primary 4", "Third Term", "Suggested next lesson"):
            self.assertIn(expected, page)

    def test_jss_activities_timeline_story_investigation_match(self):
        at = self.new()
        self.open_lesson(at, NH, "jss-1", "jss1-sources-of-history")
        lid = "jss1-sources-of-history"
        d = school.lesson(NH, lid)
        self.go_to(at, lid, "act-timeline")
        self.assertIn("Approximate date", self.text(at))
        self.assertIn("Exact date", self.text(at))
        at.selectbox(key=f"sx_{lid}_timeline").select(5).run()
        self.assertIn("translation", self.text(at))
        self.go_to(at, lid, "act-classify")
        q = lessons.question(d, "jss1-match-1")
        self.fill(at, q, f"sx_{lid}_jss1-match-1", right=False)
        self.assertIn("Not quite", self.text(at))
        self.assertIn("correct:", self.text(at))
        at.button(key=f"sx_{lid}_jss1-match-1_retry").click().run()
        self.fill(at, q, f"sx_{lid}_jss1-match-1", right=True)
        self.assertIn("Correct!", self.text(at))
        self.go_to(at, lid, "act-story-igbo-ukwu")
        k = f"sx_{lid}_story-igbo-ukwu_open"
        self.assertTrue(at.button(key=f"{k}_next0").disabled)                           # answer first to continue
        story = next(a for a in d["activities"] if a["id"] == "story-igbo-ukwu")
        for n, c in enumerate(story["chapters"]):
            self.fill(at, c["question"], f"sx_{lid}_{c['question']['id']}")
            if n + 1 < len(story["chapters"]):
                at.button(key=f"{k}_next{n}").click().run()
                self.clean(at)
        self.assertIn("End of the story", self.text(at))
        self.go_to(at, lid, "act-investigation")
        self.assertIn("Source E", self.text(at))
        short = lessons.question(d, "jss1-inv-4")
        self.fill(at, short, f"sx_{lid}_jss1-inv-4")
        self.assertIn("Check your own answer", self.text(at))
        self.assertIn("not marked automatically", self.text(at))

    def test_order_question_with_move_buttons(self):
        at = self.new()
        self.open_lesson(at, NH, "primary-4", "p4-historical-sites")
        lid = "p4-historical-sites"
        self.go_to(at, lid, "act-order-sites")
        k = f"sx_{lid}_p4-order-1"
        q = lessons.question(school.lesson(NH, lid), "p4-order-1")
        for _ in range(30):                                     # bubble into the right order with buttons only
            order = at.session_state[k + "_order"]
            if order == q["items"]:
                break
            i = next(i for i in range(len(order) - 1) if q["items"].index(order[i]) > q["items"].index(order[i + 1]))
            at.button(key=f"{k}_down{i}").click().run()
        self.assertEqual(at.session_state[k + "_order"], q["items"])
        self.assertTrue(at.button(key=f"{k}_up0").disabled)
        at.button(key=f"{k}_check").click().run()
        self.assertIn("Correct!", self.text(at))

    def test_chs_lesson_scenarios_diagram_and_practice_redirect(self):
        at = self.new()
        self.open_lesson(at, CHS, "sss-1", "sss1-citizenship")
        lid = "sss1-citizenship"
        d = school.lesson(CHS, lid)
        self.go_to(at, lid, "act-civic-scenarios")
        q = lessons.question(d, "sss1-sc-2")
        self.fill(at, q, f"sx_{lid}_sss1-sc-2", right=False)
        self.assertIn("Poor response", self.text(at))
        self.go_to(at, lid, "act-institutions")
        at.button_group(key=f"sx_{lid}_institutions").set_value("nhrc").run()
        self.clean(at)
        self.assertIn("Established 1995", self.text(at))
        self.go_to(at, lid, "acquisition")
        self.assertIn("s. 27", self.text(at))
        self.assertNotIn("WASSCE", self.text(at))
        at.button(key="sl_back_topics").click().run()
        at.button(key=f"sl_practise_{lid}").click().run()                                   # "Knowledge check" opens that page
        self.clean(at)
        rec = at.session_state["school_progress"][CHS][lid]
        self.assertEqual(rec["page_id"], "knowledge-check")

    def test_continue_learning_and_device_storage(self):
        at = self.new()
        at.button(key="sl_cont_citizenship-heritage").click().run()                         # starts the first lesson
        self.clean(at)
        self.assertEqual((at.session_state["school_view"], at.session_state["school_lesson"]), ("lesson", "sss1-citizenship"))
        at.button(key="sl_next_page").click().run()
        at.toggle(key="sl_device").set_value(True).run()
        self.clean(at)
        from ui import school as ui
        self.assertTrue(at.session_state["school_device_on"])
        packed = ui.device_pack_all(at.session_state["school_progress"])
        self.assertIn("sss1-citizenship", ui.device_unpack_all(packed)[CHS])
        at.button(key="sl_back_topics").click().run()
        at.button(key="sl_back_home").click().run()
        self.assertIn("Continue learning", [b.label for b in at.button if b.key == "sl_cont_citizenship-heritage"])

    def test_school_learning_never_records_rewards_activity(self):
        from ui import rewards_hooks
        names = ("ping", "note_view", "note_answer", "note_quiz", "note_country", "explored", "_record")
        with mock.patch.multiple(rewards_hooks, **{n: mock.DEFAULT for n in names}) as mocks:
            at = self.new()
            self.open_lesson(at, NH, "jss-1", "jss1-sources-of-history")
            for _ in range(5):
                at.button(key="sl_next_page").click().run()
            self.go_to(at, "jss1-sources-of-history", "knowledge-check")
            at.button(key="sx_check_start_jss1-sources-of-history").click().run()
            self.clean(at)
        for n, m in mocks.items():
            self.assertFalse(m.called, f"School Learning called rewards_hooks.{n}")

    def test_geography_flow_still_works(self):
        at = self.new()
        at.button(key="sl_open_geography").click().run()
        at.button(key="sl_read_ng-climate").click().run()
        self.clean(at)
        at.button(key="sl_practise_now").click().run()
        self.clean(at)
        self.assertEqual(at.session_state["school_view"], "practice")
        self.assertEqual(len(at.session_state["school_practice"]["items"]), school.PRACTICE_SIZE)


if __name__ == "__main__":
    unittest.main()
