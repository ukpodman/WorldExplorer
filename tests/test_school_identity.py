"""School Learning progress must never move silently between identities (Project Atlas review, risks 1 and 2).

Scenarios: account A → sign out → account B in the same browser session; the opt-in device cookie on a shared browser;
guest progress → signing in (only an explicit import may add it to the account); and per-subject loading."""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
GEO = "geography"
A = "a" * 64
B = "b" * 64


class FakeTables:
    def __init__(self):
        self.progress, self.attempts, self.loads = {}, [], []

    def call(self, method, route, body=None, prefer=None, user_id=None):
        if method == "GET":
            uid = re.search(r"user_id=eq\.([0-9a-f]{64})", route).group(1)
            subject = re.search(r"subject=eq\.([a-z0-9-]+)", route).group(1)
            self.loads.append((uid, subject))
            return [dict(r, lesson_id=k[2]) for k, r in self.progress.items() if k[0] == uid and k[1] == subject]
        if route.startswith("/rest/v1/school_lesson_progress"):
            key = (body["user_id"], body["subject"], body["lesson_id"])
            self.progress[key] = {**self.progress.get(key, {}), **{k: v for k, v in body.items() if k not in ("user_id", "subject", "lesson_id")}}
        else:
            self.attempts.append(body)
        return None

    def lessons_of(self, uid):
        return sorted(k[2] for k in self.progress if k[0] == uid)


class Who:
    """A switchable signed-in identity (None = signed out)."""
    def __init__(self):
        self.profile_id = None

    def __call__(self):
        return None if self.profile_id is None else {"profile_id": self.profile_id, "name": "x", "iss": "x", "sub": self.profile_id[:4]}


class Jar:
    """The browser's cookie jar: writes from one session are visible to the next session in the same browser."""
    def __init__(self):
        self.values = {}

    def read(self, name):
        return self.values.get(name)

    def write(self, name, value, max_age):
        if max_age:
            self.values[name] = value
        else:
            self.values.pop(name, None)


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class IdentityTests(unittest.TestCase):
    def setUp(self):
        AppTest.from_file(APP, default_timeout=60).run()   # warm-up: the app may reload its modules on the first run
        self.fake, self.who, self.jar = FakeTables(), Who(), Jar()
        self.saving = True
        patches = [mock.patch("core.accounts.identity", side_effect=self.who),
                   mock.patch("core.school_store.enabled", side_effect=lambda: self.saving),
                   mock.patch("core.school_store._call", side_effect=self.fake.call),
                   mock.patch("core.cookies.read", side_effect=self.jar.read),
                   mock.patch("core.cookies.write", side_effect=self.jar.write)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def session(self):
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["page"] = "Learn"
        at.session_state["learn_tab_saved"] = "school"
        return at.run()

    def study(self, at, lesson_id, pages=2, revise=False):
        if at.session_state["school_view"] != "topics":
            at.button(key="sl_open_geography").click().run()
        at.button(key=f"sl_read_{lesson_id}").click().run()
        for _ in range(pages):
            at.button(key="sl_next_page").click().run()
        if revise:
            at.button(key="sl_revision").click().run()
        at.button(key="sl_back_topics").click().run()

    def clean(self, at):
        self.assertEqual([e.value for e in at.exception], [])

    # ------------------------------------------------------------------ risk 1: account A → sign out → account B
    def test_a_then_b_in_one_session_never_mixes(self):
        self.who.profile_id = A
        at = self.session()
        self.study(at, "ng-climate", revise=True)
        self.assertEqual(self.fake.lessons_of(A), ["ng-climate"])
        self.who.profile_id = None                       # A signs out (same browser session)
        at.run()
        self.who.profile_id = B                          # B signs in
        at.run()
        self.clean(at)
        self.assertEqual(self.fake.lessons_of(B), [], "A's progress was written into B's account")
        self.assertNotIn("ng-climate", (at.session_state["school_progress"].get(GEO) or {}), "B sees A's progress")

    def test_shared_browser_device_cookie_does_not_reach_another_account(self):
        self.saving = False                              # account saving not switched on yet
        self.who.profile_id = A
        at = self.session()
        self.study(at, "ng-climate", revise=True)
        if any(t.key == "sl_device" for t in at.toggle):
            at.toggle(key="sl_device").set_value(True).run()   # V24 offered the device option to signed-in students too
        self.saving = True
        self.who.profile_id = B                          # later, B signs in on the same browser (new session)
        at2 = self.session()
        self.clean(at2)
        self.assertNotIn("ng-climate", (at2.session_state["school_progress"].get(GEO) or {}), "B sees A's device progress")
        self.assertEqual(self.fake.lessons_of(B), [], "A's device progress was written into B's account")

    # ------------------------------------------------------------------ guest → account: explicit import only
    def test_guest_progress_is_offered_not_silently_imported(self):
        at = self.session()                              # guest
        self.study(at, "ng-climate", revise=True)
        at.toggle(key="sl_device").set_value(True).run()  # keep it on this device
        self.assertIn("we_school", self.jar.values)
        self.who.profile_id = A                          # signs in (Google starts a new browser session)
        at2 = self.session()
        self.clean(at2)
        self.assertEqual(self.fake.lessons_of(A), [], "guest progress was copied into the account without asking")
        self.assertNotIn("ng-climate", (at2.session_state["school_progress"].get(GEO) or {}))
        self.assertTrue(any("as a guest on this device" in m.value for m in at2.markdown), "no import offer shown")
        at2.button(key="sl_import_guest").click().run()  # the student chooses to add it
        self.clean(at2)
        self.assertEqual(self.fake.lessons_of(A), ["ng-climate"])
        self.assertTrue(self.fake.progress[(A, GEO, "ng-climate")]["revision"])
        self.assertNotIn("we_school", self.jar.values, "the guest copy stays on the device after importing")
        self.who.profile_id = B                          # B on the same browser later: nothing to import, nothing shown
        at3 = self.session()
        self.assertEqual(self.fake.lessons_of(B), [])
        self.assertFalse(any("as a guest on this device" in m.value for m in at3.markdown))

    def test_guest_progress_can_be_declined(self):
        at = self.session()
        self.study(at, "ng-vegetation-soils")
        at.toggle(key="sl_device").set_value(True).run()
        self.who.profile_id = A
        at2 = self.session()
        at2.button(key="sl_discard_guest").click().run()
        self.clean(at2)
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertNotIn("we_school", self.jar.values)

    def test_signed_in_students_have_no_device_copy(self):
        self.saving = False
        self.who.profile_id = A
        at = self.session()
        self.study(at, "ng-climate")
        self.assertFalse(any(t.key == "sl_device" for t in at.toggle))
        self.assertNotIn("we_school", self.jar.values)

    def test_a_signs_out_and_studies_as_guest_without_seeing_a(self):
        self.who.profile_id = A
        at = self.session()
        self.study(at, "ng-climate")
        self.who.profile_id = None
        at.run()
        self.clean(at)
        self.assertNotIn("ng-climate", (at.session_state["school_progress"].get(GEO) or {}))


class AttrDict(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class SubjectLoadingTests(unittest.TestCase):
    """Risk 2: loading one subject must not mark a second subject as loaded."""

    def test_second_subject_is_loaded_too(self):
        from core import school
        from ui import school as ui
        fake = FakeTables()
        fake.progress[(A, GEO, "ng-climate")] = {"page": 3, "furthest": 3}
        fake.progress[(A, "history-test", "h-1")] = {"page": 1, "furthest": 1}
        real_ids, real_lesson = school.lesson_ids, school.lesson
        fake_lesson = {"id": "h-1", "version": 1, "sections": [{"id": "s1", "title": "S1", "blocks": []}],
                       "intro": [], "objectives": [], "definitions": [], "worked": [], "exam_tips": [], "checks": [], "summary": []}
        ss = AttrDict(school_progress={}, school_subject=GEO)
        with mock.patch.object(ui, "SS", ss), \
                mock.patch.object(ui.accounts, "identity", return_value={"profile_id": A}), \
                mock.patch.object(ui.school_store, "enabled", return_value=True), \
                mock.patch.object(ui.school_store, "_call", side_effect=fake.call), \
                mock.patch.object(ui.school, "lesson_ids", side_effect=lambda s: ["h-1"] if s == "history-test" else real_ids(s)), \
                mock.patch.object(ui.school, "lesson", side_effect=lambda s, i: fake_lesson if s == "history-test" else real_lesson(s, i)):
            ui._restore(GEO)
            ui._restore("history-test")
            ui._restore(GEO)                              # already loaded: no second request
        self.assertEqual(fake.loads, [(A, GEO), (A, "history-test")])
        self.assertEqual(ss["school_progress"]["history-test"]["h-1"]["page"], 1)


if __name__ == "__main__":
    unittest.main()
