"""School Learning (V24): content, reading progress, practice, saving (off by default), the Learn subtabs and the
proposed database migration (run against a throwaway local PostgreSQL when one is installed)."""
import ast
import glob
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


class ContentTests(unittest.TestCase):
    def test_seven_lessons_load_and_validate(self):
        ids = school.lesson_ids(GEO)
        self.assertEqual(ids, ["ng-physical-setting", "ng-climate", "ng-vegetation-soils", "ng-population-settlement",
                               "ng-resources-agriculture", "ng-transport-industry", "ng-trade-tourism-environment"])
        for n, lesson_id in enumerate(ids, 1):
            d = school.lesson(GEO, lesson_id)
            self.assertEqual(d["number"], n)
            self.assertGreaterEqual(len(d["practice"]), 12)
            for key in ("objectives", "intro", "definitions", "worked", "exam_tips", "checks", "summary", "structured", "references"):
                self.assertTrue(d[key], f"{lesson_id}: {key} empty")
            self.assertTrue(all(r["url"].startswith("https://") for r in d["references"]))

    def test_every_figure_exists_and_uses_styled_classes(self):
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        used = set()
        for lesson_id in school.lesson_ids(GEO):
            for s in school.lesson(GEO, lesson_id)["sections"]:
                for b in s["blocks"]:
                    if b["type"] == "figure":
                        svg = school.figure(GEO, b["src"])
                        self.assertTrue(svg.lstrip().startswith("<svg") and "<script" not in svg)
                        self.assertTrue(b.get("credit"))
                        used.add(b["src"])
                    if b["type"] == "photo":
                        from core.data import PHOTOS
                        self.assertIn(b["src"].removeprefix("country:"), PHOTOS)   # only the app's licensed photos
        self.assertEqual(len(used), 9)
        classes = set()
        for path in glob.glob(str(ROOT / "data/school/geography/figures/*.svg")):
            for group in re.findall(r'class="([^"]+)"', Path(path).read_text(encoding="utf-8")):
                classes.update(group.split())
        unstyled = sorted(c for c in classes if "." + c not in css and not re.fullmatch(r"bar-\d|sl-map|sl-chart|west", c))
        self.assertEqual(unstyled, [])
        self.assertIn('html[data-we-theme="dark"] .sl-fig', css)

    def test_bad_lessons_are_rejected(self):
        d = dict(school.lesson(GEO, "ng-climate"))
        bad = dict(d, practice=d["practice"][:5])
        with self.assertRaises(school.ContentError):
            school.validate_lesson(bad)
        q = dict(d["practice"][0], answer=7)
        with self.assertRaises(school.ContentError):
            school.validate_lesson(dict(d, practice=[q] + d["practice"][1:]))
        with self.assertRaises(school.ContentError):
            school.lesson(GEO, "not-a-lesson")
        with self.assertRaises(school.ContentError):
            school.figure(GEO, "../secrets")

    def test_curriculum_states_review_and_no_approval_claim(self):
        cur = school.curriculum(GEO)
        self.assertEqual(cur["review_status"], "pending")
        self.assertIn("not approved or endorsed by WAEC or NERDC", cur["status_note"])
        self.assertEqual(school.topic_count(GEO), 34)
        planned = [s for s in school.subjects() if s["status"] == "planned"]
        self.assertEqual({s["id"] for s in planned}, {"nigerian-history", "citizenship-heritage"})
        with self.assertRaises(school.ContentError):
            school.curriculum("nigerian-history")


class ProgressTests(unittest.TestCase):
    def test_reading_position_completion_and_revision_are_separate(self):
        total = 10
        rec = school.move_to(None, 3, total)
        self.assertEqual((rec["page"], rec["furthest"], school.status(rec)), (3, 3, "In progress"))
        self.assertFalse(school.can_complete(rec, total))
        self.assertNotIn("completed", school.set_completed(rec, total))          # cannot complete before the last page
        rec = school.move_to(rec, 1, total)                                      # going back keeps the furthest page
        self.assertEqual((rec["page"], rec["furthest"]), (1, 3))
        rec = school.move_to(rec, 99, total)
        self.assertEqual(rec["page"], 9)
        rec = school.set_completed(rec, total)
        self.assertEqual(school.status(rec), "Completed")
        self.assertEqual(school.revision_reasons(rec), [])
        rec = school.set_revision(rec, True)
        self.assertEqual(school.status(rec), "Completed")                        # still completed, also on revision list
        self.assertEqual(school.revision_reasons(rec), ["On your revision list"])
        rec = school.record_practice(school.set_revision(rec, False), 4)
        self.assertEqual(school.revision_reasons(rec), ["Best practice score 4/10"])
        rec = school.record_practice(rec, 8)
        self.assertEqual((rec["best"], rec["last"], rec["attempts"], school.revision_reasons(rec)), (8, 8, 2, []))
        rec = school.record_practice(rec, 3)
        self.assertEqual((rec["best"], rec["last"]), (8, 3))

    def test_saved_records_are_cleaned(self):
        rec = school.clean_record({"page": 50, "furthest": "x", "best": 99, "completed": "yes", "revision": True,
                                   "attempts": -1, "updated_at": "2026-01-01"}, 10)
        self.assertEqual(rec, {"page": 9, "furthest": 9, "best": 10, "revision": True, "updated_at": "2026-01-01"})
        self.assertIsNone(school.clean_record("junk", 10))

    def test_overview_and_continue_target(self):
        prog = {"ng-climate": {"page": 2, "furthest": 2, "updated_at": "2026-10-02"},
                "ng-physical-setting": {"page": 8, "furthest": 8, "completed": True, "best": 9, "attempts": 1, "updated_at": "2026-10-03"},
                "ng-vegetation-soils": {"page": 1, "furthest": 1, "best": 3, "attempts": 1, "updated_at": "2026-10-01"}}
        o = school.overview(GEO, prog)
        self.assertEqual((o["lessons"], o["completed"], o["in_progress"], o["revise"], o["average"]), (7, 1, 2, 1, 60))
        self.assertEqual(school.continue_target(GEO, prog), "ng-climate")           # most recent unfinished lesson
        self.assertEqual(school.continue_target(GEO, {}), "ng-physical-setting")
        self.assertEqual(school.neighbours(GEO, "ng-physical-setting"), (None, "ng-climate"))
        self.assertEqual(school.neighbours(GEO, "ng-trade-tourism-environment"), ("ng-transport-industry", None))


class PracticeTests(unittest.TestCase):
    def test_ten_shuffled_questions_and_double_answer_safety(self):
        d = school.lesson(GEO, "ng-climate")
        s = school.new_practice(d, seed=3)
        self.assertEqual(len(s["items"]), 10)
        self.assertEqual(len({i["id"] for i in s["items"]}), 10)
        right = s["items"][0]["order"].index(school.question(d, s["items"][0]["id"])["answer"])
        self.assertTrue(school.answer(s, d, 0, right))
        self.assertFalse(school.answer(s, d, 0, (right + 1) % 4))        # a double click cannot answer twice
        self.assertFalse(school.answer(s, d, 1, 0))                      # nor answer ahead
        self.assertTrue(school.advance(s, 0))
        self.assertFalse(school.advance(s, 0))                           # nor skip twice
        for i in range(1, 10):
            school.answer(s, d, i, 0)
            school.advance(s, i)
        self.assertTrue(s["finished"])
        self.assertFalse(school.answer(s, d, 9, 1))
        self.assertGreaterEqual(school.score(s), 1)
        self.assertEqual(len(s["answers"]), 10)


class StoreTests(unittest.TestCase):
    def test_off_by_default_and_needs_both_switches(self):
        from core import accounts
        with mock.patch.object(accounts, "_secret_section", return_value={}), mock.patch.object(accounts, "storage_ready", return_value=True):
            self.assertFalse(school_store.enabled())
        with mock.patch.object(accounts, "_secret_section", return_value={"progress_storage": "supabase"}), \
                mock.patch.object(accounts, "storage_ready", return_value=False):
            self.assertFalse(school_store.enabled())
        with mock.patch.object(accounts, "_secret_section", return_value={"progress_storage": "supabase"}), \
                mock.patch.object(accounts, "storage_ready", return_value=True):
            self.assertTrue(school_store.enabled())

    def test_rows_hold_only_progress_and_question_ids(self):
        row = school_store.row(USER, GEO, "ng-climate", {"page": 2, "furthest": 4, "secret": "x", "revision": True})
        self.assertEqual(row, {"user_id": USER, "subject": GEO, "lesson_id": "ng-climate", "page": 2, "furthest": 4, "revision": True})
        att = school_store.attempt_row(USER, GEO, "ng-climate", 7, 10, [{"id": "c1", "chosen": 2, "correct": True}])
        self.assertEqual(att["answers"], [{"q": "c1", "ok": True}])
        for bad in (("bob@example.com", GEO, "ng-climate"), (USER, "geo;drop", "ng-climate"), (USER, GEO, "../x")):
            with self.assertRaises(ValueError):
                school_store.row(*bad, {})

    def test_requests_use_dedicated_tables_only(self):
        calls = []
        with mock.patch.object(school_store, "_call", side_effect=lambda *a, **k: calls.append(a) or []):
            school_store.load(USER, GEO)
            school_store.save(USER, GEO, "ng-climate", {"page": 1})
            school_store.record_attempt(USER, GEO, "ng-climate", 5, 10, [])
        routes = [c[1] for c in calls]
        self.assertTrue(all(r.startswith(("/rest/v1/school_lesson_progress", "/rest/v1/school_practice_attempts")) for r in routes))

    def test_school_code_never_touches_rewards_or_quiz(self):
        for path in ("core/school.py", "core/school_store.py", "ui/school.py"):
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            for banned in ("rewards", "rewards_store", "rewards_hooks", "withdrawals", "badges", "quiz", "records", "daily", "founding", "analytics"):
                self.assertNotIn(banned, names, f"{path} imports {banned}")
            docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef)) and ast.get_docstring(n)}
            strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
            self.assertFalse([x for x in strings if "world_explorer_profiles" in x or "reward_" in x], path)


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class SchoolAppTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def clean(self, at):
        self.assertEqual([e.value for e in at.exception], [])

    def test_world_geography_is_the_default_and_keeps_its_controls(self):
        at = self.new(page="Learn", learn_country="FRA")
        self.clean(at)
        self.assertEqual(at.session_state["learn_tab"], "world")
        keys = {b.key for b in at.button}
        for key in ("learn_prev_top", "learn_next_bottom", "learn_surprise", "learn_quiz_me"):
            self.assertIn(key, keys)
        self.assertFalse(any(k and k.startswith("sl_") for k in keys))

    def test_search_and_continent_filter(self):
        at = self.new(page="Learn", learn_country="FRA")
        at.text_input(key="learn_search").input("Abuja").run()
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("learn_hit_")], ["learn_hit_NGA"])
        at.button(key="learn_hit_NGA").click().run()
        self.assertEqual((at.session_state["learn_country"], at.text_input(key="learn_search").value), ("NGA", ""))
        at.button_group(key="learn_continent_pick").set_value("Europe").run()
        self.clean(at)
        from core.data import get_country
        self.assertIn("Europe", get_country(at.session_state["learn_country"])["continents"])   # moved into the filter
        for _ in range(3):
            at.button(key="learn_next_top").click().run()
            self.assertIn("Europe", get_country(at.session_state["learn_country"])["continents"])  # Next stays inside it

    def test_guest_reads_completes_and_practises_without_points(self):
        at = self.new(page="Learn", learn_tab_saved="school")
        self.clean(at)
        points = at.session_state["points"] if "points" in at.session_state else 0
        badges = list(at.session_state["earned_badges"]) if "earned_badges" in at.session_state else None
        self.assertTrue(any("learning as a guest" in m.value for m in at.markdown))
        at.button(key="sl_open_geography").click().run()
        at.button(key="sl_read_ng-climate").click().run()
        self.assertEqual(at.session_state["school_view"], "lesson")
        self.assertTrue(at.button(key="sl_complete").disabled)            # not before the last page
        at.button(key="sl_next_page").click().run()
        at.button(key="sl_next_page").click().run()
        self.assertTrue(any('class="sl-fig"' in m.value for m in at.markdown))   # page 3: the ITD map
        self.assertEqual(at.session_state["school_progress"][GEO]["ng-climate"]["page"], 2)
        at.selectbox(key="sl_jump_ng-climate").select(9).run()
        at.button(key="sl_complete").click().run()
        at.button(key="sl_revision").click().run()
        rec = at.session_state["school_progress"][GEO]["ng-climate"]
        self.assertTrue(rec["completed"] and rec["revision"])
        at.button(key="sl_back_topics").click().run()
        at.button(key="sl_read_ng-climate").click().run()                   # "Read again" starts from page 1
        self.assertEqual(at.session_state["school_progress"][GEO]["ng-climate"]["page"], 0)
        at.button(key="sl_back_topics").click().run()
        at.button(key="sl_practise_ng-climate").click().run()
        s = at.session_state["school_practice"]
        for i in range(10):
            at.button(key=f"sl_ans_{s['token']}_{i}_0").click().run()
            at.button(key=f"sl_next_{s['token']}_{i}").click().run()
        self.clean(at)
        rec = at.session_state["school_progress"][GEO]["ng-climate"]
        self.assertEqual(rec["attempts"], 1)
        self.assertTrue(any("Your answers" in m.value for m in at.markdown))
        self.assertEqual(at.session_state["points"] if "points" in at.session_state else 0, points)   # no points
        if badges is not None:
            self.assertEqual(list(at.session_state["earned_badges"]), badges)
        self.assertIsNone(at.session_state["quiz"] if "quiz" in at.session_state else None)        # quiz untouched
        at.button(key="sl_result_progress").click().run()
        self.clean(at)
        self.assertEqual(at.session_state["school_view"], "progress")

    def test_opening_a_country_from_elsewhere_returns_to_world_geography(self):
        at = self.new(page="Explore", explore_selected="Africa", learn_tab_saved="school", learn_continent="Europe")
        at.button(key="discover_NGA").click().run()
        at.button(key="detail_learn").click().run()
        self.clean(at)
        self.assertEqual((at.session_state["page"], at.session_state["learn_tab"], at.session_state["learn_country"]),
                         ("Learn", "world", "NGA"))
        self.assertEqual(at.session_state["learn_continent"], "All")


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
class MigrationTests(unittest.TestCase):
    """The proposed migration on a throwaway local PostgreSQL (never the real database)."""

    @classmethod
    def setUpClass(cls):
        cls.cluster = pg_harness.Cluster()
        cls.db = cls.cluster.fresh_db()
        cls.cluster.psql_file(cls.db, ROOT / "supabase" / "school_learning_migration.sql")
        cls.cluster.psql_file(cls.db, ROOT / "supabase" / "school_learning_migration.sql")   # safe to run twice

    @classmethod
    def tearDownClass(cls):
        cls.cluster.stop()

    def q(self, sql, role=None):
        return self.cluster.psql(self.db, sql, role)

    def test_server_role_can_save_and_constraints_hold(self):
        StoreError = pg_harness.StoreError   # the class the harness raises (modules may be reloaded by other tests)
        self.q(f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'ng-climate', 2, 4)", "service_role")
        self.q(f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'ng-climate', 3, 5) "
               "on conflict (user_id, subject, lesson_id) do update set page = excluded.page, furthest = excluded.furthest", "service_role")
        self.assertEqual(self.q(f"select page, furthest from school_lesson_progress where user_id = '{USER}'", "service_role"), "3|5")
        self.q(f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total, answers) values ('{USER}', 'geography', 'ng-climate', 7, 10, '[{{\"q\":\"c1\",\"ok\":true}}]')", "service_role")
        for bad in ("insert into school_lesson_progress (user_id, subject, lesson_id) values ('someone@example.com', 'geography', 'x')",
                    f"insert into school_lesson_progress (user_id, subject, lesson_id, page, furthest) values ('{USER}', 'geography', 'y', 5, 2)",
                    f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total) values ('{USER}', 'geography', 'x', 11, 10)",
                    f"insert into school_practice_attempts (user_id, subject, lesson_id, score, total, answers) values ('{USER}', 'geography', 'x', 1, 10, '{{}}')"):
            with self.assertRaises(StoreError):
                self.q(bad, "service_role")
        with self.assertRaises(StoreError):
            self.q("update school_practice_attempts set score = 10", "service_role")   # attempts are never edited

    def test_browser_roles_have_no_access(self):
        StoreError = pg_harness.StoreError   # the class the harness raises (modules may be reloaded by other tests)
        for role in ("anon", "authenticated"):
            for sql in ("select * from school_lesson_progress", "select * from school_practice_attempts",
                        f"insert into school_lesson_progress (user_id, subject, lesson_id) values ('{USER}', 'geography', 'z')"):
                with self.assertRaises(StoreError):
                    self.q(sql, role)
        self.assertEqual(self.q("select bool_and(relrowsecurity) from pg_class where relname in ('school_lesson_progress', 'school_practice_attempts')"), "t")

    def test_migration_adds_only_school_tables(self):
        text = (ROOT / "supabase" / "school_learning_migration.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
        self.assertEqual(sorted(set(re.findall(r"public\.(\w+)", body))), ["school_lesson_progress", "school_practice_attempts"])


if __name__ == "__main__":
    unittest.main()
