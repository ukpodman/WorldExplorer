"""School Learning (V24): content and question banks, reading progress, practice, search and filters, guest and
signed-in progress (with a stand-in for the Supabase REST calls), the Learn subtabs, the World Geography locator map,
and the proposed database migration with its row-level security (run against a throwaway local PostgreSQL)."""
import ast
import glob
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pg_harness  # noqa: E402
from core import school, school_store  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
GEO = "geography"
USER = "a" * 64
OTHER = "b" * 64
LESSONS = ["ng-physical-setting", "ng-climate", "ng-vegetation-soils", "ng-population-settlement",
           "ng-resources-agriculture", "ng-transport-industry", "ng-trade-tourism-environment"]


# =========================================================================== content

class ContentTests(unittest.TestCase):
    def test_seven_complete_lessons(self):
        self.assertEqual(school.lesson_ids(GEO), LESSONS)
        for n, lesson_id in enumerate(LESSONS, 1):
            d = school.lesson(GEO, lesson_id)
            self.assertEqual((d["number"], d["subject"], d["review_status"], d["version"]), (n, GEO, "pending", 1))
            self.assertTrue(set(d["level"]) <= {"SSS 1", "SSS 2", "SSS 3"} and d["level"])
            for key, least in (("objectives", 4), ("intro", 1), ("sections", 4), ("definitions", 8), ("worked", 2),
                               ("exam_tips", 3), ("checks", 5), ("structured", 3), ("summary", 4), ("references", 3)):
                self.assertGreaterEqual(len(d[key]), least, f"{lesson_id}: {key}")
            words = sum(len(json.dumps(s["blocks"], ensure_ascii=False).split()) for s in d["sections"])
            self.assertGreater(words, 700, f"{lesson_id}: lesson notes are too short ({words} words)")
            self.assertTrue(any(b["type"] == "figure" for s in d["sections"] for b in s["blocks"]), lesson_id)
            self.assertTrue(all(r["url"].startswith("https://") for r in d["references"]))
            for q in d["structured"]:
                self.assertTrue(q["model"] and q["points"] and q["marks"] > 0)

    def test_question_banks(self):
        ids = []
        for lesson_id in LESSONS:
            d = school.lesson(GEO, lesson_id)
            self.assertGreaterEqual(len(d["practice"]), 20)
            sections = {s["id"] for s in d["sections"]}
            levels = {q["difficulty"] for q in d["practice"]}
            self.assertEqual(levels, {"easy", "medium", "hard"}, lesson_id)
            for q in d["practice"]:
                ids.append(q["id"])
                self.assertEqual((q["subject"], q["topic"]), (GEO, lesson_id))
                self.assertIn(q["section"], sections)
                self.assertEqual(len(set(q["options"])), 4)
                self.assertTrue(q["explanation"].strip())
        self.assertGreaterEqual(len(ids), 140)
        self.assertEqual(len(ids), len(set(ids)), "question ids must be unique across lessons")

    def test_worked_calculations_are_right(self):
        """The arithmetic in the new calculation questions (checked here, not by hand)."""
        def q(lesson_id, qid):
            d = school.lesson(GEO, lesson_id)
            x = school.question(d, qid)
            return x["options"][x["answer"]]
        self.assertEqual(q("ng-population-settlement", "po13"), f"{600_000 // 1_500} people per km²")
        self.assertEqual(q("ng-climate", "cl15"), f"{30 - 6.5 * (1200 - 200) / 1000} °C")
        self.assertEqual(q("ng-transport-industry", "ti21"), f"{156 // 78} hours")
        self.assertEqual(q("ng-trade-tourism-environment", "tt14"), f"a surplus of ₦{18 - 15} trillion")
        self.assertEqual(q("ng-climate", "cl7"), "4 °C")

    def test_figures_exist_have_credits_and_theme_classes(self):
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        used = set()
        for lesson_id in LESSONS:
            for s in school.lesson(GEO, lesson_id)["sections"]:
                for b in s["blocks"]:
                    if b["type"] == "figure":
                        svg = school.figure(GEO, b["src"])
                        self.assertTrue(svg.lstrip().startswith("<svg") and "<script" not in svg and "role=\"img\"" in svg)
                        used.add(b["src"])
                    if b["type"] == "photo":
                        from core.data import PHOTOS
                        self.assertIn(b["src"].removeprefix("country:"), PHOTOS)   # only the app's licensed photos
        self.assertEqual(len(used), 9)
        classes = set()
        for path in glob.glob(str(ROOT / "data/school/geography/figures/*.svg")):
            for group in re.findall(r'class="([^"]+)"', Path(path).read_text(encoding="utf-8")):
                classes.update(group.split())
        self.assertEqual(sorted(c for c in classes if "." + c not in css and not re.fullmatch(r"bar-\d|sl-map|sl-chart|west", c)), [])
        self.assertIn('html[data-we-theme="dark"] .sl-fig', css)

    def test_bad_content_is_rejected(self):
        d = dict(school.lesson(GEO, "ng-climate"))
        for bad in (dict(d, practice=d["practice"][:12]),
                    dict(d, practice=[dict(d["practice"][0], answer=7)] + d["practice"][1:]),
                    dict(d, practice=[dict(d["practice"][0], difficulty="tricky")] + d["practice"][1:]),
                    dict(d, practice=[dict(d["practice"][0], topic="other")] + d["practice"][1:]),
                    {k: v for k, v in d.items() if k != "level"}):
            with self.assertRaises(school.ContentError):
                school.validate_lesson(bad)
        with self.assertRaises(school.ContentError):
            school.lesson(GEO, "not-a-lesson")
        with self.assertRaises(school.ContentError):
            school.figure(GEO, "../secrets")

    def test_curriculum_levels_objectives_and_no_approval_claim(self):
        cur = school.curriculum(GEO)
        self.assertEqual((cur["review_status"], school.topic_count(GEO)), ("pending", 34))
        self.assertIn("not approved or endorsed by WAEC or NERDC", cur["status_note"])
        for sec in cur["sections"]:
            for t in sec["topics"]:
                self.assertTrue(t["level"] and t["objectives"], t["id"])
        self.assertIn("No question is guaranteed", cur["exam_guidance"]["note"])
        text = json.dumps([school.lesson(GEO, i) for i in LESSONS] + [cur], ensure_ascii=False).lower()
        text = text.replace("no question is guaranteed to appear", "")
        for claim in ("approved by waec", "endorsed by nerdc", "certified by", "guaranteed to appear", "will appear in waec"):
            self.assertNotIn(claim, text)
        planned = [s for s in school.subjects() if s["status"] == "planned"]
        self.assertEqual({s["id"] for s in planned}, {"nigerian-history", "citizenship-heritage"})
        with self.assertRaises(school.ContentError):
            school.curriculum("nigerian-history")


# =========================================================================== progress, search, practice

class ProgressTests(unittest.TestCase):
    def test_states_completion_and_revision_rules(self):
        d = school.lesson(GEO, "ng-climate")
        pages = school.pages(d)
        total = len(pages)
        rec = school.move_to(None, 3, total, pages, 1)
        self.assertEqual((rec["page"], rec["page_id"], school.states(rec)), (3, pages[3]["id"], ["In progress"]))
        self.assertNotIn("completed", school.set_completed(rec, total))           # not before the last page
        rec = school.move_to(rec, 1, total, pages)                                  # going back keeps the furthest page
        self.assertEqual((rec["page"], rec["furthest"]), (1, 3))
        rec = school.set_completed(school.move_to(rec, 99, total, pages), total)
        self.assertEqual(school.states(rec), ["Completed"])
        rec = school.record_practice(rec, 3, ["cl1"], 10)                           # a poor score keeps completion
        self.assertEqual(school.states(rec), ["Completed", "Needs revision"])
        self.assertTrue(rec["completed"])
        rec = school.record_practice(school.set_revision(rec, True), 9, ["cl2"], 10)
        self.assertEqual(school.revision_reasons(rec), ["On your revision list"])
        self.assertEqual((rec["best"], rec["last"], rec["attempts"], rec["answered"], rec["correct"]), (9, 9, 2, 20, 12))

    def test_reading_position_survives_a_corrected_lesson(self):
        d = school.lesson(GEO, "ng-climate")
        ids = [p["id"] for p in school.pages(d)]
        saved = {"page": 2, "page_id": "rainfall", "furthest": 2}
        clean = school.clean_record(saved, len(ids), ids)                           # the page moved: follow its id
        self.assertEqual(ids[clean["page"]], "rainfall")
        self.assertTrue(school.updated_since({"version": 1}, dict(d, version=2)))
        self.assertFalse(school.updated_since({"version": 1}, d))

    def test_saved_records_are_cleaned(self):
        rec = school.clean_record({"page": 50, "furthest": "x", "best": 99, "completed": "yes", "revision": True,
                                   "attempts": -1, "answered": 5, "correct": 9, "recent": ["a", 3, "b"], "updated_at": "2026-01-01"}, 10)
        self.assertEqual(rec, {"page": 9, "furthest": 9, "best": 10, "revision": True, "answered": 5, "correct": 5,
                               "recent": ["a", "b"], "updated_at": "2026-01-01"})
        self.assertIsNone(school.clean_record("junk", 10))

    def test_overview_continue_and_recent(self):
        prog = {"ng-climate": {"page": 2, "furthest": 2, "updated_at": "2026-10-02"},
                "ng-physical-setting": {"page": 8, "furthest": 8, "completed": True, "best": 9, "attempts": 1, "answered": 10,
                                        "correct": 9, "updated_at": "2026-10-03"},
                "ng-vegetation-soils": {"page": 1, "furthest": 1, "best": 3, "attempts": 1, "answered": 10, "correct": 3,
                                        "updated_at": "2026-10-01"}}
        o = school.overview(GEO, prog)
        self.assertEqual((o["lessons"], o["completed"], o["in_progress"], o["not_started"], o["revise"], o["average"], o["answered"]),
                         (7, 1, 2, 4, 1, 60, 20))
        self.assertEqual(o["recent"], ["ng-physical-setting", "ng-climate", "ng-vegetation-soils"])
        self.assertEqual(school.continue_target(GEO, prog), "ng-climate")
        self.assertEqual(school.continue_target(GEO, {}), "ng-physical-setting")
        self.assertEqual(school.neighbours(GEO, "ng-physical-setting"), (None, "ng-climate"))
        self.assertEqual(school.neighbours(GEO, "ng-trade-tourism-environment"), ("ng-transport-industry", None))

    def test_search_and_filters(self):
        self.assertEqual(school.find_lessons(GEO, {}, "harmattan"), ["ng-climate"])
        self.assertIn("ng-transport-industry", school.find_lessons(GEO, {}, "ports"))
        self.assertEqual(school.find_lessons(GEO, {}, section="physical"), [])
        self.assertEqual(len(school.find_lessons(GEO, {}, section="regional")), 7)
        self.assertEqual(school.find_lessons(GEO, {}, level="SSS 1")[0], "ng-physical-setting")
        prog = {"ng-climate": {"page": 1, "revision": True}}
        self.assertEqual(school.find_lessons(GEO, prog, state="Needs revision"), ["ng-climate"])
        self.assertEqual(len(school.find_lessons(GEO, prog, state="Not started")), 6)
        self.assertEqual([t["id"] for _, t in school.find_topics(GEO, "gis")], ["gis-concepts", "gis-data"])
        self.assertEqual(len(school.find_topics(GEO)), 27)                         # topics without lessons ("coming soon")


class PracticeTests(unittest.TestCase):
    def test_round_double_answer_safety_and_areas(self):
        d = school.lesson(GEO, "ng-climate")
        s = school.new_practice(d, seed=3)
        self.assertEqual(len({i["id"] for i in s["items"]}), 10)
        right = s["items"][0]["order"].index(school.question(d, s["items"][0]["id"])["answer"])
        self.assertTrue(school.answer(s, d, 0, right))
        self.assertFalse(school.answer(s, d, 0, (right + 1) % 4))        # a double click cannot answer twice
        self.assertFalse(school.answer(s, d, 1, 0))                      # nor answer ahead
        self.assertTrue(school.advance(s, 0))
        self.assertFalse(school.advance(s, 0))
        for i in range(1, 10):
            item = s["items"][i]
            wrong = next(p for p in range(4) if item["order"][p] != school.question(d, item["id"])["answer"])
            school.answer(s, d, i, wrong)
            school.advance(s, i)
        self.assertTrue(s["finished"])
        self.assertEqual(school.score(s), 1)
        areas = school.areas_to_revise(s, d)
        self.assertEqual(sum(n for _, n in areas), 9)
        self.assertTrue(all(sec["id"] in {x["id"] for x in d["sections"]} for sec, _ in areas))

    def test_retry_avoids_recent_questions(self):
        d = school.lesson(GEO, "ng-climate")
        first = school.new_practice(d, seed=1)
        rec = school.record_practice(None, 5, [i["id"] for i in first["items"]], 10)
        second = school.new_practice(d, seed=2, recent=rec["recent"])
        self.assertFalse({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})
        rec = school.record_practice(rec, 6, [i["id"] for i in second["items"]], 10)
        third = school.new_practice(d, seed=3, recent=rec["recent"])            # bank of 21: one fresh question left
        self.assertEqual(len({i["id"] for i in third["items"]} - set(rec["recent"])), len(d["practice"]) - 20)


# =========================================================================== storage

class StoreTests(unittest.TestCase):
    def test_off_by_default_and_needs_both_switches(self):
        from core import accounts
        cases = [({}, True, False), ({"progress_storage": "supabase"}, False, False), ({"progress_storage": "supabase"}, True, True)]
        for section, ready, expected in cases:
            with mock.patch.object(accounts, "_secret_section", return_value=section), \
                    mock.patch.object(accounts, "storage_ready", return_value=ready):
                self.assertEqual(school_store.enabled(), expected)

    def test_rows_hold_only_progress_and_question_ids(self):
        row = school_store.row(USER, GEO, "ng-climate", {"page": 2, "furthest": 4, "secret": "x", "revision": True,
                                                         "recent": ["cl1"], "version": 1, "page_id": "itd"})
        self.assertEqual(row, {"user_id": USER, "subject": GEO, "lesson_id": "ng-climate", "page": 2, "furthest": 4,
                               "revision": True, "recent_questions": ["cl1"], "content_version": 1, "page_id": "itd"})
        att = school_store.attempt_row(USER, GEO, "ng-climate", 7, 10, [{"id": "cl1", "chosen": 2, "correct": True}])
        self.assertEqual(att["answers"], [{"q": "cl1", "ok": True}])
        for bad in (("bob@example.com", GEO, "ng-climate"), (USER, "geo;drop", "ng-climate"), (USER, GEO, "../x")):
            with self.assertRaises(ValueError):
                school_store.row(*bad, {})

    def test_load_maps_columns_back(self):
        rows = [{"lesson_id": "ng-climate", "page": 3, "recent_questions": ["cl2"], "content_version": 1, "completed": True}]
        with mock.patch.object(school_store, "_call", return_value=rows) as call:
            self.assertEqual(school_store.load(USER, GEO), {"ng-climate": {"page": 3, "recent": ["cl2"], "version": 1, "completed": True}})
        self.assertIn("/rest/v1/school_lesson_progress?", call.call_args[0][1])
        self.assertIn(f"user_id=eq.{USER}", call.call_args[0][1])

    def test_requests_use_dedicated_tables_only(self):
        calls = []
        with mock.patch.object(school_store, "_call", side_effect=lambda *a, **k: calls.append(a) or []):
            school_store.load(USER, GEO)
            school_store.save(USER, GEO, "ng-climate", {"page": 1})
            school_store.record_attempt(USER, GEO, "ng-climate", 5, 10, [])
        self.assertTrue(all(c[1].startswith(("/rest/v1/school_lesson_progress", "/rest/v1/school_practice_attempts")) for c in calls))

    def test_user_token(self):
        import base64
        import hashlib
        import hmac
        token = school_store.user_token(USER, "s3cret", now=1_000)
        head, body, sig = token.split(".")
        pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
        claims = json.loads(base64.urlsafe_b64decode(pad(body)))
        self.assertEqual(claims, {"role": "authenticated", "we_profile_id": USER, "iat": 1000, "exp": 1300, "aud": "authenticated"})
        good = base64.urlsafe_b64encode(hmac.new(b"s3cret", f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertEqual(sig, good)
        with self.assertRaises(ValueError):
            school_store.user_token("someone@example.com", "s3cret")
        from core import accounts
        with mock.patch.object(accounts, "_secret_section", return_value={"access": "user_token", "jwt_secret": "x"}):
            self.assertEqual(school_store.access_mode(), "server")              # needs the anon key too
        with mock.patch.object(accounts, "_secret_section", return_value={"access": "user_token", "jwt_secret": "x", "anon_key": "k"}):
            self.assertEqual(school_store.access_mode(), "user_token")

    def test_school_code_never_touches_rewards_or_quiz(self):
        for path in ("core/school.py", "core/school_store.py", "ui/school.py"):
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            for banned in ("rewards", "rewards_store", "rewards_hooks", "withdrawals", "badges", "quiz", "records", "daily",
                           "founding", "analytics", "founding_ui", "withdraw_ui"):
                self.assertNotIn(banned, names, f"{path} imports {banned}")
            docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef)) and ast.get_docstring(n)}
            strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
            self.assertFalse([x for x in strings if "world_explorer_profiles" in x or "reward_" in x], path)


class DeviceStorageTests(unittest.TestCase):
    def test_pack_and_unpack(self):
        from ui import school as ui
        prog = {"ng-climate": {"page": 3, "page_id": "rainfall", "furthest": 5, "completed": False, "revision": True, "best": 7,
                               "last": 6, "attempts": 2, "answered": 20, "correct": 13, "version": 1, "updated_at": "2026-10-20T08:00:00+00:00"},
                "not-a-lesson": {"page": 1}}
        with mock.patch.object(ui, "SS", {"school_subject": GEO}):
            value = ui.device_pack(prog)
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", value) and len(value) < 3500)
            subject, back = ui.device_unpack(value)
        self.assertEqual(subject, GEO)
        self.assertEqual(set(back), {"ng-climate"})
        rec = back["ng-climate"]
        rainfall = [p["id"] for p in school.pages(school.lesson(GEO, "ng-climate"))].index("rainfall")
        self.assertEqual((rec["page"], rec["page_id"], rec["furthest"], rec["revision"], rec["best"], rec["attempts"], rec["correct"]),
                         (rainfall, "rainfall", 5, True, 7, 2, 13))   # the position follows its page id
        for junk in ("", "not base64 !!", "eyJ2IjoxfQ"):
            self.assertEqual(ui.device_unpack(junk)[1], {})
        from core import cookies
        self.assertTrue(cookies.NAMES["we_school"].match(value))


# =========================================================================== app (real Streamlit AppTest)

class FakeTables:
    """In-memory stand-in for the two School Learning tables behind school_store._call (no network)."""
    def __init__(self):
        self.progress, self.attempts = {}, []

    def call(self, method, route, body=None, prefer=None, user_id=None):
        if method == "GET":
            uid = re.search(r"user_id=eq\.([0-9a-f]{64})", route).group(1)
            return [dict(r, lesson_id=k[2]) for k, r in self.progress.items() if k[0] == uid]
        if route.startswith("/rest/v1/school_lesson_progress"):
            key = (body["user_id"], body["subject"], body["lesson_id"])
            self.progress[key] = {**self.progress.get(key, {}), **{k: v for k, v in body.items() if k not in ("user_id", "subject", "lesson_id")}}
        else:
            self.attempts.append(body)
        return None


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class SchoolAppTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def clean(self, at):
        self.assertEqual([e.value for e in at.exception], [])

    def keys(self, at, prefix):
        return [b.key for b in at.button if b.key and b.key.startswith(prefix)]

    def test_world_geography_default_controls_and_map(self):
        at = self.new(page="Learn", learn_country="NGA")
        self.clean(at)
        self.assertEqual(at.session_state["learn_tab"], "world")
        for key in ("learn_prev_top", "learn_next_bottom", "learn_surprise", "learn_quiz_me"):
            self.assertIn(key, [b.key for b in at.button])
        self.assertFalse(self.keys(at, "sl_"))
        maps = [m.value for m in at.markdown if '<figure class="learn-map"' in m.value]
        self.assertEqual(len(maps), 1)
        self.assertIn('class="lm-me"', maps[0])
        self.assertLess(len(maps[0]), 100_000)
        self.assertTrue(any('class="photo-frame learn-photo-frame"' in m.value for m in at.markdown))   # photo kept

    def test_search_and_continent_filter(self):
        at = self.new(page="Learn", learn_country="FRA")
        at.text_input(key="learn_search").input("Abuja").run()
        self.assertEqual(self.keys(at, "learn_hit_"), ["learn_hit_NGA"])
        at.button(key="learn_hit_NGA").click().run()
        self.assertEqual((at.session_state["learn_country"], at.text_input(key="learn_search").value), ("NGA", ""))
        at.button_group(key="learn_continent_pick").set_value("Europe").run()
        self.clean(at)
        from core.data import get_country
        for _ in range(3):
            self.assertIn("Europe", get_country(at.session_state["learn_country"])["continents"])
            at.button(key="learn_next_top").click().run()

    def test_tabs_keep_each_others_place(self):
        at = self.new(page="Learn", learn_country="KEN")
        at.segmented_control(key="learn_tab").set_value("school").run()
        at.button(key="sl_open_geography").click().run()
        at.button(key="sl_read_ng-climate").click().run()
        at.button(key="sl_next_page").click().run()
        at.segmented_control(key="learn_tab").set_value("world").run()
        self.assertEqual(at.session_state["learn_country"], "KEN")
        at.button(key="nav_Quiz").click().run()
        at.button(key="nav_Learn").click().run()
        self.assertEqual((at.session_state["learn_tab"], at.session_state["school_view"]), ("world", "lesson"))
        at.segmented_control(key="learn_tab").set_value("school").run()
        self.clean(at)
        self.assertEqual(at.session_state["school_progress"][GEO]["ng-climate"]["page"], 1)

    def test_guest_full_study_flow_without_points(self):
        at = self.new(page="Learn", learn_tab_saved="school")
        self.clean(at)
        before = {k: (at.session_state[k] if k in at.session_state else None)
                  for k in ("points", "earned_badges", "quiz", "rounds_finished", "stats", "streak")}
        self.assertTrue(any("You are learning as a guest" in m.value for m in at.markdown))
        self.assertEqual(self.keys(at, "sl_open_"), ["sl_open_geography"])          # planned subjects have no button
        at.text_input(key="sl_subject_search").input("citizenship").run()
        self.assertEqual(self.keys(at, "sl_open_"), [])
        at.text_input(key="sl_subject_search").input("").run()
        at.button(key="sl_open_geography").click().run()
        at.text_input(key="sl_topic_search").input("census").run()
        self.assertEqual(self.keys(at, "sl_read_"), ["sl_read_ng-population-settlement"])
        at.text_input(key="sl_topic_search").input("").run()
        at.button(key="sl_read_ng-climate").click().run()
        self.assertTrue(at.button(key="sl_complete").disabled)
        for _ in range(3):
            at.button(key="sl_next_page").click().run()
        self.assertTrue(any('class="sl-fig"' in m.value for m in at.markdown))       # the ITD map (page 4)
        at.selectbox(key="sl_jump_ng-climate").select(10).run()
        at.button(key="sl_complete").click().run()
        at.button(key="sl_revision").click().run()
        rec = at.session_state["school_progress"][GEO]["ng-climate"]
        self.assertTrue(rec["completed"] and rec["revision"])
        at.button(key="sl_next_lesson").click().run()
        self.assertEqual(at.session_state["school_lesson"], "ng-vegetation-soils")
        at.button(key="sl_prev_lesson").click().run()
        self.assertEqual(at.session_state["school_progress"][GEO]["ng-climate"]["page"], 10)   # back where it was
        at.button(key="sl_practise_now").click().run()
        s = at.session_state["school_practice"]
        for i in range(10):
            at.button(key=f"sl_ans_{s['token']}_{i}_0").click().run()
            self.assertTrue(any(c.key and c.key.startswith("sl_feedback_") for c in at.get("flex_container") + at.get("vertical_block"))
                            or any("feedback feedback-" in m.value for m in at.markdown))
            at.button(key=f"sl_next_{s['token']}_{i}").click().run()
        self.clean(at)
        rec = at.session_state["school_progress"][GEO]["ng-climate"]
        self.assertEqual((rec["attempts"], rec["answered"], rec["completed"]), (1, 10, True))     # completion kept
        self.assertTrue(any("of 10 correct" in m.value for m in at.markdown))
        first = {a["id"] for a in at.session_state["school_practice"]["answers"]}
        at.button(key="sl_again").click().run()
        self.assertFalse(first & {i["id"] for i in at.session_state["school_practice"]["items"]})   # no repeats
        at.button(key="sl_practice_back").click().run()
        at.button(key="sl_lesson_progress").click().run()
        self.clean(at)
        self.assertTrue(any("Questions attempted" in m.value for m in at.markdown))
        after = {k: (at.session_state[k] if k in at.session_state else None) for k in before}
        self.assertEqual(after, before)                                             # no points, badges or quiz changes

    def test_filters_by_status(self):
        at = self.new(page="Learn", learn_tab_saved="school", school_view="topics",
                      school_progress={GEO: {"ng-climate": {"page": 2, "furthest": 2, "revision": True}}})
        at.button_group(key="sl_state").set_value("Needs revision").run()
        self.assertEqual(self.keys(at, "sl_read_"), ["sl_read_ng-climate"])
        at.button_group(key="sl_state").set_value("Not started").run()
        self.assertEqual(len(self.keys(at, "sl_read_")), 6)
        at.selectbox(key="sl_section").select("physical").run()
        self.assertEqual(self.keys(at, "sl_read_"), [])
        self.clean(at)

    def test_signed_in_progress_is_saved_and_restored(self):
        fake = FakeTables()
        who = {"profile_id": USER, "name": "Student", "iss": "https://accounts.google.com", "sub": "1"}
        self.new()   # warm-up: the app may reload its modules on its first run, so patch the loaded ones afterwards
        with mock.patch("core.accounts.identity", return_value=who), \
                mock.patch("core.school_store.enabled", return_value=True), \
                mock.patch("core.school_store._call", side_effect=fake.call):
            at = self.new(page="Learn", learn_tab_saved="school")
            self.assertTrue(any("saved to your account" in m.value for m in at.markdown))
            at.button(key="sl_open_geography").click().run()
            at.button(key="sl_read_ng-climate").click().run()
            at.button(key="sl_next_page").click().run()
            at.button(key="sl_next_page").click().run()
            at.button(key="sl_revision").click().run()
            self.clean(at)
            saved = fake.progress[(USER, GEO, "ng-climate")]
            self.assertEqual((saved["page"], saved["page_id"], saved["revision"]), (2, "airmasses", True))
            # a new session (another device, or after closing the browser) continues where the student stopped
            at2 = self.new(page="Learn", learn_tab_saved="school")
            self.clean(at2)
            self.assertEqual(at2.session_state["school_progress"][GEO]["ng-climate"]["page"], 2)
            at2.button(key="sl_continue_btn").click().run()
            self.assertEqual((at2.session_state["school_view"], at2.session_state["school_lesson"]), ("lesson", "ng-climate"))
        self.assertFalse(any(k[0] == OTHER for k in fake.progress))

    def test_storage_failure_is_reported_not_hidden(self):
        who = {"profile_id": USER, "name": "Student", "iss": "x", "sub": "1"}
        self.new()
        with mock.patch("core.accounts.identity", return_value=who), \
                mock.patch("core.school_store.enabled", return_value=True), \
                mock.patch("core.school_store._call", side_effect=OSError("tables not installed")):
            at = self.new(page="Learn", learn_tab_saved="school")
            self.clean(at)
            self.assertTrue(any("could not reach your saved School Learning progress" in m.value for m in at.markdown))
            self.assertFalse(any("is saved to your account" in m.value for m in at.markdown))

    def test_opening_a_country_from_explore_returns_to_world_geography(self):
        at = self.new(page="Explore", explore_selected="Africa", explore_search="Nigeria",   # the list is alphabetical
                      learn_tab_saved="school", learn_continent="Europe")
        at.button(key="discover_NGA").click().run()
        at.button(key="detail_learn").click().run()
        self.clean(at)
        self.assertEqual((at.session_state["page"], at.session_state["learn_tab"], at.session_state["learn_country"]),
                         ("Learn", "world", "NGA"))
        self.assertEqual(at.session_state["learn_continent"], "All")


# =========================================================================== migration on a throwaway PostgreSQL

AUTH_STUB = """
create schema if not exists auth;
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''), nullif(current_setting('request.jwt.claims', true), ''))::jsonb $$;
grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.jwt() to anon, authenticated, service_role;
"""


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
class MigrationTests(unittest.TestCase):
    """The proposed migration on a throwaway local PostgreSQL with the Supabase roles (never the real database).
    auth.jwt() is stubbed exactly as Supabase defines it (reads request.jwt.claims)."""

    @classmethod
    def setUpClass(cls):
        cls.cluster = pg_harness.Cluster()
        cls.db = cls.cluster.fresh_db()
        cls.before = cls.cluster.psql(cls.db, "select count(*) from pg_tables where schemaname = 'public'")
        cls.cluster.psql(cls.db, AUTH_STUB)
        sql = ROOT / "supabase" / "school_learning_migration.sql"
        cls.cluster.psql_file(cls.db, sql)
        cls.cluster.psql_file(cls.db, sql)   # safe to run twice
        cls.base_db = cls.db                 # base migration only (recommended "server" mode)
        cls.db = cls.cluster.fresh_db()      # base + optional per-student policies ("user_token" mode)
        cls.cluster.psql(cls.db, AUTH_STUB)
        cls.cluster.psql_file(cls.db, sql)
        cls.cluster.psql_file(cls.db, ROOT / "supabase" / "school_learning_user_token_policies.sql")
        cls.cluster.psql_file(cls.db, ROOT / "supabase" / "school_learning_user_token_policies.sql")

    @classmethod
    def tearDownClass(cls):
        cls.cluster.stop()

    def q(self, sql, role=None, as_user=None):
        if as_user:
            sql = (f"select set_config('request.jwt.claims', '{{\"role\":\"authenticated\",\"we_profile_id\":\"{as_user}\"}}', false);\n"
                   + sql)
        return self.cluster.psql(self.db, sql, role)

    def test_adds_only_the_two_school_tables(self):
        after = self.cluster.psql(self.base_db, "select count(*) from pg_tables where schemaname = 'public'")
        self.assertEqual(int(after), int(self.before) + 2)
        text = (ROOT / "supabase" / "school_learning_migration.sql").read_text(encoding="utf-8")
        text += (ROOT / "supabase" / "school_learning_user_token_policies.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
        self.assertEqual(sorted(set(re.findall(r"public\.(\w+)", body))), ["school_lesson_progress", "school_practice_attempts"])
        self.assertNotRegex(body.lower(), r"\b(drop table|truncate|delete from|alter table public\.(?!school_))")

    def test_server_role_and_constraints(self):
        E = pg_harness.StoreError
        self.q(f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'ng-climate', 2, 4) "
               "on conflict (user_id, subject, lesson_id) do update set page = excluded.page", "service_role")
        self.q(f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total, answers) values ('{USER}', 'geography', 'ng-climate', 7, 10, '[{{\"q\":\"cl1\",\"ok\":true}}]')", "service_role")
        for bad in ("insert into school_lesson_progress (user_id, subject, lesson_id) values ('someone@example.com', 'geography', 'x')",
                    f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'y', 5, 2)",
                    f"insert into school_lesson_progress (user_id, subject, lesson_id, answered, correct) values ('{USER}', 'geography', 'z', 1, 2)",
                    f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total) values ('{USER}', 'geography', 'x', 11, 10)",
                    f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total, answers) values ('{USER}', 'geography', 'x', 1, 10, '{{}}')"):
            with self.assertRaises(E):
                self.q(bad, "service_role")
        with self.assertRaises(E):
            self.q("update school_practice_attempts set score = 10", "service_role")    # attempts are never edited

    def test_each_student_reaches_only_their_own_rows(self):
        E = pg_harness.StoreError
        self.q(f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'ng-vegetation-soils', 1, 1)",
               "authenticated", as_user=USER)
        self.assertEqual(self.q("select count(*) from school_lesson_progress where lesson_id = 'ng-vegetation-soils'", "authenticated",
                                as_user=USER).splitlines()[-1], "1")
        self.assertEqual(self.q("select count(*) from school_lesson_progress", "authenticated", as_user=OTHER).splitlines()[-1], "0")
        with self.assertRaises(E):   # cannot write rows for someone else
            self.q(f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'ng-climate-x')",
                   "authenticated", as_user=OTHER)
        self.assertEqual(self.q(f"update school_lesson_progress set page = 3 where user_id = '{USER}' returning 1", "authenticated",
                                as_user=OTHER).splitlines()[1:], [])
        self.q(f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total) values ('{USER}', 'geography', 'ng-climate', 5, 10)",
               "authenticated", as_user=USER)
        with self.assertRaises(E):
            self.q("update school_practice_attempts set score = 9", "authenticated", as_user=USER)
        # a token without the claim (for example a Supabase Auth sign-in) sees nothing
        self.assertEqual(self.q("select set_config('request.jwt.claims', '{\"role\":\"authenticated\",\"sub\":\"x\"}', false); "
                                "select count(*) from school_lesson_progress", "authenticated").splitlines()[-1], "0")

    def test_server_mode_base_migration_gives_browser_roles_nothing(self):
        E = pg_harness.StoreError
        for role in ("anon", "authenticated"):
            for sql in ("select * from school_lesson_progress", "select * from school_practice_attempts",
                        f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'z')"):
                with self.assertRaises(E):
                    self.cluster.psql(self.base_db, (f"select set_config('request.jwt.claims', '{{\"we_profile_id\":\"{USER}\"}}', false); " if role == "authenticated" else "") + sql, role)
        self.assertEqual(self.cluster.psql(self.base_db, "select count(*) from pg_policies where tablename like 'school_%'"), "0")
        self.cluster.psql(self.base_db, f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'ng-climate') on conflict do nothing", "service_role")

    def test_base_rerun_after_optional_policies_closes_browser_access(self):
        """Round 2: if the optional token policies were applied earlier and the base file is run again, the base
        revokes the browser-role grants. The five policies remain in the catalogue but cannot be used without grants."""
        E = pg_harness.StoreError
        db = self.cluster.fresh_db()
        self.cluster.psql(db, AUTH_STUB)
        base = ROOT / "supabase" / "school_learning_migration.sql"
        self.cluster.psql_file(db, base)
        self.cluster.psql_file(db, ROOT / "supabase" / "school_learning_user_token_policies.sql")
        self.cluster.psql_file(db, base)                                   # base re-run (server mode chosen later)
        self.assertEqual(self.cluster.psql(db, "select count(*) from pg_policies where tablename like 'school_%'"), "5")
        claims = f"select set_config('request.jwt.claims', '{{\"we_profile_id\":\"{USER}\"}}', false); "
        for sql in ("select * from school_lesson_progress", "select * from school_practice_attempts"):
            with self.assertRaises(E):
                self.cluster.psql(db, claims + sql, "authenticated")
        grants = self.cluster.psql(db, "select count(*) from information_schema.role_table_grants where table_name like 'school_%' "
                                       "and grantee in ('anon', 'authenticated', 'PUBLIC')")
        self.assertEqual(grants, "0")
        self.cluster.psql(db, f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'ng-climate')", "service_role")

    def test_public_key_has_no_access(self):
        E = pg_harness.StoreError
        for sql in ("select * from school_lesson_progress", "select * from school_practice_attempts",
                    f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'z')"):
            with self.assertRaises(E):
                self.q(sql, "anon")
        self.assertEqual(self.q("select bool_and(relrowsecurity) from pg_class where relname in ('school_lesson_progress', 'school_practice_attempts')"), "t")
        self.assertEqual(self.q("select count(*) from pg_policies where tablename like 'school_%'"), "5")


if __name__ == "__main__":
    unittest.main()
