"""Guest → account import must never delete the guest's device backup before the account save is confirmed
(Project Atlas independent review, round 3).

Each test: a guest studies with "Keep my progress on this device" on, then signs in (new browser session) and decides
what to do with the offered guest progress."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_school_identity import APP, GEO, A, B, AppTest, FakeTables, Who, Jar  # noqa: E402  (helpers only)

COOKIE = "we_school"


class FlakyTables(FakeTables):
    """FakeTables whose saves (POST) or loads (GET) can be made to fail like a network or storage outage."""
    def __init__(self):
        super().__init__()
        self.fail_saves = self.fail_loads = False

    def call(self, method, route, body=None, prefer=None, user_id=None):
        if method == "GET" and self.fail_loads:
            raise RuntimeError("storage unavailable")
        if method != "GET" and self.fail_saves:
            raise RuntimeError("storage unavailable")
        return super().call(method, route, body, prefer, user_id)


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class ImportSafetyTests(unittest.TestCase):
    def setUp(self):
        AppTest.from_file(APP, default_timeout=60).run()
        self.fake, self.who, self.jar = FlakyTables(), Who(), Jar()
        self.saving = True
        for p in [mock.patch("core.accounts.identity", side_effect=self.who),
                  mock.patch("core.school_store.enabled", side_effect=lambda: self.saving),
                  mock.patch("core.school_store._call", side_effect=self.fake.call),
                  mock.patch("core.cookies.read", side_effect=self.jar.read),
                  mock.patch("core.cookies.write", side_effect=self.jar.write)]:
            p.start()
            self.addCleanup(p.stop)

    # ---------------------------------------------------------------- helpers
    def session(self):
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["page"] = "Learn"
        at.session_state["learn_tab_saved"] = "school"
        return at.run()

    def guest_with_device_backup(self, lesson_id="ng-climate"):
        at = self.session()
        at.button(key="sl_open_geography").click().run()
        at.button(key=f"sl_read_{lesson_id}").click().run()
        at.button(key="sl_next_page").click().run()
        at.button(key="sl_next_page").click().run()
        at.button(key="sl_back_topics").click().run()
        at.toggle(key="sl_device").set_value(True).run()
        self.assertIn(COOKIE, self.jar.values)
        return self.jar.values[COOKIE]

    def sign_in(self, profile_id):
        self.who.profile_id = profile_id
        at = self.session()                          # Google sign-in starts a new browser session
        self.assertTrue(self.offer_shown(at), "the guest progress was not offered")
        return at

    def offer_shown(self, at):
        return any("as a guest on this device" in m.value for m in at.markdown)

    def notices(self, at):
        return " | ".join(e.value for e in list(at.success) + list(at.info) + list(at.warning) + list(at.error))

    def mine(self, at):
        return sorted((at.session_state["school_progress"].get(GEO) or {}).keys())

    def clean(self, at):
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- scenarios
    def test_storage_disabled_keeps_the_device_backup(self):
        backup = self.guest_with_device_backup()
        self.saving = False                          # account saving switched off
        at = self.sign_in(A)
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.jar.values.get(COOKIE), backup, "the guest backup was deleted although nothing was saved")
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertEqual(self.mine(at), ["ng-climate"], "Add should still make the lesson usable for this visit")
        self.assertIn("for this visit only", self.notices(at))
        self.assertIn("kept on this device", self.notices(at))
        self.assertNotIn("added to your account", self.notices(at).lower())

    def test_save_exception_keeps_the_backup_and_the_offer_then_retry_succeeds(self):
        backup = self.guest_with_device_backup()
        at = self.sign_in(A)
        self.fake.fail_saves = True                  # loading worked; the save fails
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.jar.values.get(COOKIE), backup, "the guest backup was deleted after a failed save")
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertIn("could not be saved to your account", self.notices(at))
        self.assertIn("kept on this device", self.notices(at))
        self.assertTrue(self.offer_shown(at), "the offer must stay so the student can try again")
        self.fake.fail_saves = False                 # storage is back: the same button now saves it
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.fake.lessons_of(A), ["ng-climate"], "the retry did not save the lesson")
        self.assertNotIn(COOKIE, self.jar.values, "after a confirmed save the guest backup should be removed")
        self.assertIn("added to your account", self.notices(at).lower())
        self.assertFalse(self.offer_shown(at))

    def test_failed_account_load_keeps_the_backup(self):
        backup = self.guest_with_device_backup()
        self.fake.fail_loads = True                  # the account's progress could not be loaded
        at = self.sign_in(A)
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.jar.values.get(COOKIE), backup, "the guest backup was deleted while the account was unreachable")
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertIn("could not be saved to your account", self.notices(at))

    def test_successful_save_removes_the_backup_and_says_so(self):
        self.guest_with_device_backup()
        at = self.sign_in(A)
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.fake.lessons_of(A), ["ng-climate"])
        self.assertNotIn(COOKIE, self.jar.values)
        self.assertIn("added to your account", self.notices(at).lower())
        self.assertFalse(self.offer_shown(at))

    def test_failed_import_for_a_is_not_carried_to_b(self):
        """A's import fails (backup kept) → A signs out → B signs in in the same browser session."""
        backup = self.guest_with_device_backup()
        at = self.sign_in(A)
        self.fake.fail_saves = True
        at.button(key="sl_import_guest").click().run()
        self.fake.fail_saves = False
        self.who.profile_id = None
        at.run()
        self.who.profile_id = B
        at.run()
        self.clean(at)
        self.assertEqual(self.fake.lessons_of(B), [], "A's attempted import reached B's account")
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertEqual(self.mine(at), [], "B's session holds the lesson A tried to import")
        self.assertEqual(self.notices(at), "", "A's import message was shown to B")
        self.assertEqual(self.jar.values.get(COOKIE), backup, "the device backup should remain until someone decides")

    def test_all_guest_records_older_than_the_account_adds_nothing_and_says_so(self):
        self.guest_with_device_backup()
        newer = {"page": 5, "furthest": 5, "updated_at": "2999-01-01T00:00:00+00:00"}
        self.fake.progress[(A, GEO, "ng-climate")] = dict(newer)    # the account already has newer progress
        at = self.sign_in(A)
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.fake.progress[(A, GEO, "ng-climate")], newer, "older guest progress overwrote the account")
        msg = self.notices(at)
        self.assertNotIn("added to your account", msg.lower(), "claimed an import although nothing was added")
        self.assertIn("Nothing was added", msg)
        self.assertIn("already has newer progress", msg)
        self.assertNotIn(COOKIE, self.jar.values, "the account is confirmed newer, so the outdated backup may go")
        self.assertFalse(self.offer_shown(at))

    def test_mixed_import_counts_only_the_lessons_actually_added(self):
        at = self.session()                              # guest studies two lessons, device backup on
        at.button(key="sl_open_geography").click().run()
        for lesson_id in ("ng-climate", "ng-vegetation-soils"):
            at.button(key=f"sl_read_{lesson_id}").click().run()
            at.button(key="sl_next_page").click().run()
            at.button(key="sl_back_topics").click().run()
        at.toggle(key="sl_device").set_value(True).run()
        self.fake.progress[(A, GEO, "ng-climate")] = {"page": 5, "furthest": 5, "updated_at": "2999-01-01T00:00:00+00:00"}
        at = self.sign_in(A)
        at.button(key="sl_import_guest").click().run()
        self.clean(at)
        self.assertEqual(self.fake.lessons_of(A), ["ng-climate", "ng-vegetation-soils"])
        self.assertEqual(self.fake.progress[(A, GEO, "ng-climate")]["updated_at"], "2999-01-01T00:00:00+00:00")
        msg = self.notices(at)
        self.assertIn("added to your account (1 lesson)", msg)
        self.assertIn("1 lesson was skipped", msg)

    def test_discard_removes_the_backup_and_imports_nothing(self):
        self.guest_with_device_backup()
        at = self.sign_in(A)
        at.button(key="sl_discard_guest").click().run()
        self.clean(at)
        self.assertNotIn(COOKIE, self.jar.values)
        self.assertEqual(self.fake.lessons_of(A), [])
        self.assertEqual(self.mine(at), [])
        self.assertFalse(self.offer_shown(at))
        self.assertNotIn("added to your account", self.notices(at).lower())


if __name__ == "__main__":
    unittest.main()
