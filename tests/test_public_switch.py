"""Public Rewards Programme ON/OFF (owner switch): owner-only changes, persistence, audit, enrolment and earning
restrictions while OFF, preservation of existing records, and the dashboard's honest status. Runs on the in-memory
store, on the real SQL (local PostgreSQL) and in the running app.
Run:  python -m unittest discover -s tests -p test_public_switch.py"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import rewards, withdrawals  # noqa: E402
from core.rewards import Settings  # noqa: E402
from core.rewards_store import MemoryStore, StoreError  # noqa: E402
import pg_harness  # noqa: E402
import founding_fixtures  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

OWNER = "owner@example.com"
MONTH, DAY = rewards.month_key(), rewards.day_key()
CLUSTER = None


def setUpModule():
    global CLUSTER
    if pg_harness.available():
        try:
            CLUSTER = pg_harness.Cluster()
        except Exception as error:  # pragma: no cover
            print("local PostgreSQL could not start:", error)


def tearDownModule():
    if CLUSTER:
        CLUSTER.stop()


def pid(n):
    return f"{n:064x}"


class Scenarios:
    def make_store(self):
        raise NotImplementedError

    def reopen(self, s):
        raise NotImplementedError

    def store(self):
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{MONTH}-01"), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER]})
        return s

    def member(self, s, n, test=False):
        s.ensure_account(pid(n), f"p{n}@example.com", f"P{n}", True, test)
        return s.join(pid(n), MONTH)

    def quiz(self, s, n, k, test=False):
        return s.add_event(pid(n), "quiz", f"q{n}-{k}", DAY, reward=True, test=test)

    # ------------------------------------------------------------------ the switch itself

    def test_off_by_default_and_limits_unchanged(self):
        s = self.store()
        status = s.public_status()
        self.assertEqual((status["installed"], status["enabled"]), (True, False))
        st = s.settings()
        self.assertEqual((st.monthly_budget, st.max_places, st.monthly_cap, st.paused), (50000, 50, 1000, False))

    def test_only_listed_owners_can_change_it(self):
        s = self.store()
        for actor in ("player@example.com", "", "OWNER@example.com.evil", None):
            with self.assertRaises(StoreError) as caught:
                s.set_public(True, actor, confirmed=True)
            self.assertIn("not_owner", str(caught.exception))
        self.assertFalse(s.public_status()["enabled"])

    def test_switching_on_needs_explicit_confirmation(self):
        s = self.store()
        with self.assertRaises(StoreError) as caught:
            s.set_public(True, OWNER)
        self.assertIn("confirmation_required", str(caught.exception))
        self.assertFalse(s.public_status()["enabled"])
        s.set_public(True, OWNER, confirmed=True)
        self.assertTrue(s.public_status()["enabled"])
        s.set_public(False, OWNER)                                    # switching OFF never needs it
        self.assertFalse(s.public_status()["enabled"])

    def test_status_persists(self):
        s = self.store()
        s.set_public(True, OWNER, confirmed=True)
        later = self.reopen(s)                                        # e.g. after an app restart
        status = later.public_status()
        self.assertEqual((status["enabled"], status["changed_by"]), (True, OWNER))
        self.assertIsNotNone(status["changed_at"])

    def test_cannot_be_changed_around_the_owner_function(self):
        s = self.store()
        with self.assertRaises(StoreError):
            s.update("reward_program_settings", {"id": 1}, {"public_enabled": True})
        s.set_public(True, OWNER, confirmed=True)
        stale = s.settings()                                          # the ordinary settings form
        s.save_settings(Settings(**{**stale.as_row(), "quiz_amount": 10}), OWNER)
        self.assertTrue(s.public_status()["enabled"])                 # saving settings never reverts the switch
        s.save_settings(Settings(**{**stale.as_row(), "paused": True}), OWNER)
        self.assertTrue(s.public_status()["enabled"])                 # the pause is a separate setting
        self.assertTrue(s.settings().paused)

    def test_every_change_is_audited(self):
        s = self.store()
        s.set_public(True, OWNER, confirmed=True)
        s.set_public(False, OWNER)
        actions = [(a["action"], a["actor"]) for a in s.audit()]
        self.assertIn(("public_programme_on", OWNER), actions)
        self.assertIn(("public_programme_off", OWNER), actions)
        refused = [a for a in s.audit() if a["actor"] == "player@example.com"]
        self.assertEqual(refused, [])

    # ------------------------------------------------------------------ while OFF

    def test_off_blocks_new_real_enrolments_but_not_test_accounts(self):
        s = self.store()
        s.ensure_account(pid(1), "p1@example.com", "P1", True, False)
        with self.assertRaises(StoreError) as caught:
            s.join(pid(1), MONTH)
        self.assertIn("programme_off", str(caught.exception))
        self.assertIsNone(s.enrolment(pid(1), MONTH))
        self.assertEqual(self.member(s, 2, test=True)["status"], "enrolled")   # owner/tester simulations work

    def test_off_blocks_new_real_rewards_but_records_activity(self):
        s = self.store()
        s.set_public(True, OWNER, confirmed=True)
        self.member(s, 1)
        s.set_public(False, OWNER)
        row = self.quiz(s, 1, 0)
        self.assertEqual((int(row["amount"]), row["reason"]), (0, "programme_off"))
        self.member(s, 2, test=True)
        self.assertEqual(int(self.quiz(s, 2, 0, test=True)["amount"]), 10)  # test records unaffected

    def test_off_blocks_waiting_list_promotion(self):
        s = self.store()
        s.save_settings(Settings(start_date=f"{MONTH}-01", max_places=1), OWNER)
        s.set_public(True, OWNER, confirmed=True)
        self.member(s, 1)
        self.assertEqual(self.member(s, 2)["status"], "waitlist")
        s.save_settings(Settings(start_date=f"{MONTH}-01", max_places=2), OWNER)
        s.set_public(False, OWNER)
        with self.assertRaises(StoreError):
            s.promote(MONTH, OWNER)
        self.assertEqual(s.enrolment(pid(2), MONTH)["status"], "waitlist")

    def test_switching_off_preserves_existing_records_and_balances(self):
        s = self.store()
        s.set_public(True, OWNER, confirmed=True)
        self.member(s, 1)
        for k in range(3):
            self.quiz(s, 1, k)
        before = {"events": s.events(pid(1)), "enrolment": s.enrolment(pid(1), MONTH), "account": s.account(pid(1)),
                  "summary": rewards.summarize(s.events(pid(1), MONTH)), "cash": s.cashout_status(pid(1))["totals"]}
        s.set_public(False, OWNER)
        self.assertEqual(s.events(pid(1)), before["events"])
        self.assertEqual(s.enrolment(pid(1), MONTH), before["enrolment"])
        self.assertEqual(s.account(pid(1)), before["account"])
        self.assertEqual(rewards.summarize(s.events(pid(1), MONTH))["total"], 30)
        self.assertEqual(s.cashout_status(pid(1))["totals"], before["cash"])  # balances unchanged
        s.leave(pid(1), MONTH)                                        # leaving stays possible while OFF
        self.assertEqual(s.enrolment(pid(1), MONTH)["status"], "withdrawn")
        s.set_public(True, OWNER, confirmed=True)                     # and switching back ON loses nothing
        self.assertEqual(rewards.summarize(s.events(pid(1), MONTH))["total"], 30)

    def test_never_touches_payment_switches(self):
        s = self.store()
        before = s.cashout_settings()
        s.set_public(True, OWNER, confirmed=True)
        s.set_public(False, OWNER)
        after = s.cashout_settings()
        self.assertEqual((after["live_requests"], after["real_payouts"]), (before["live_requests"], before["real_payouts"]))
        self.assertEqual((after["live_requests"], after["real_payouts"]), (False, False))


class MemoryPublicSwitchTests(Scenarios, unittest.TestCase):
    def make_store(self):
        return founding_fixtures.auto_approve(MemoryStore())   # approved for Founding 50 (see test_founding50)

    def reopen(self, s):
        return s


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
class SqlPublicSwitchTests(Scenarios, unittest.TestCase):
    def make_store(self):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        return founding_fixtures.auto_approve(pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db()))

    def reopen(self, s):
        return pg_harness.PsqlStore(CLUSTER, s.db)                   # a new connection, nothing in memory

    def test_browser_roles_cannot_use_the_switch(self):
        s = self.store()
        for role in ("anon", "authenticated"):
            for sql in ("select public.reward_set_public_programme(true, 'owner@example.com', true)",
                        "update public.reward_program_settings set public_enabled = true"):
                with self.assertRaises(StoreError, msg=f"{role}: {sql}"):
                    CLUSTER.psql(s.db, sql, role)
        with self.assertRaises(StoreError):                           # nor can the server key bypass the function
            CLUSTER.psql(s.db, "update public.reward_program_settings set public_enabled = true", "service_role")
        self.assertFalse(s.public_status()["enabled"])

    def test_migration_is_rerunnable_and_never_switches_on(self):
        s = self.store()
        CLUSTER.psql_file(s.db, pg_harness.PUBLIC)
        self.assertFalse(s.public_status()["enabled"])
        s.set_public(True, OWNER, confirmed=True)
        CLUSTER.psql_file(s.db, pg_harness.PUBLIC)
        CLUSTER.psql_file(s.db, pg_harness.SCHEMA)
        self.assertTrue(s.public_status()["enabled"])                 # an owner's choice is kept, not reset


# ============================================================================ in the running app

OWNER_ID = {"iss": "https://accounts.google.com", "sub": "o1", "email": OWNER, "email_verified": True,
            "name": "Owner", "profile_id": "a" * 64}
PLAYER = {"iss": "https://accounts.google.com", "sub": "p2", "email": "player@example.com", "email_verified": True,
          "name": "Player", "profile_id": "b" * 64}


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class PublicSwitchAppTests(unittest.TestCase):
    def setUp(self):
        from ui import rewards_hooks
        self.hooks = rewards_hooks
        rewards_hooks._memory_store.clear()
        rewards_hooks._health_cache.clear()
        self.s = rewards_hooks._memory_store()

    def app(self, who, enabled=True, page="Owner"):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.secrets["rewards"] = {"enabled": enabled, "tester_emails": ["player@example.com"]}
        at.secrets["analytics"] = {"owner_emails": [OWNER]}
        at.session_state["page"] = page
        if page == "Owner":   # the owner opens the rewards tab (the dashboard draws only the open tab)
            at.session_state["owner_tab"] = "💰 Rewards & Referral Management"
        patch = mock.patch("core.accounts.identity", return_value=dict(who))
        patch.start()
        self.addCleanup(patch.stop)
        return at

    def tiles(self, at):
        return " ".join(str(h.proto) for h in at.get("html"))

    def test_players_cannot_reach_the_switch(self):
        at = self.app(PLAYER).run()
        self.assertTrue(any("not available" in i.value for i in at.info))
        self.assertEqual([b for b in at.button if b.key in ("rw_public_off",)], [])
        self.assertNotIn("Public Rewards Programme", " ".join(m.value for m in at.markdown))

    def test_owner_switches_on_with_confirmation_and_off(self):
        at = self.app(OWNER_ID).run()
        self.assertEqual([x.value for x in at.exception], [])
        self.assertIn("Public Rewards Programme", " ".join(m.value for m in at.markdown))
        self.assertIn("DISABLED", self.tiles(at))
        submit = next(b for b in at.button if b.label == "Switch public participation ON")
        submit.click().run()                                          # boxes not ticked
        self.assertTrue(any("tick both confirmations" in e.value for e in at.error))
        self.assertFalse(self.s.public_status()["enabled"])
        at.checkbox(key="rw_public_legal").check()
        at.checkbox(key="rw_public_payments").check()
        next(b for b in at.button if b.label == "Switch public participation ON").click().run()
        self.assertTrue(self.s.public_status()["enabled"])
        self.assertTrue(any("switched ON" in x.value for x in at.success))
        self.assertIn("ENABLED", self.tiles(at))
        self.assertIn(("public_programme_on", OWNER), [(a["action"], a["actor"]) for a in self.s.audit()])
        at.button(key="rw_public_off").click().run()
        self.assertFalse(self.s.public_status()["enabled"])
        self.assertIn("DISABLED", self.tiles(at))

    def test_deployment_switch_off_is_never_shown_as_on(self):
        self.s.tables["reward_program_settings"][0]["public_enabled"] = True   # owner switch ON in the database
        at = self.app(OWNER_ID, enabled=False).run()
        html = self.tiles(at)
        self.assertIn("DISABLED", html)
        self.assertNotIn("ENABLED</b>", html)
        self.assertTrue(any("Blocked by the deployment safety switch" in x.value for x in at.info))
        self.assertFalse(self.hooks.enabled())

    def test_on_button_disabled_while_the_deployment_switch_is_off(self):
        at = self.app(OWNER_ID, enabled=False).run()
        button = next(b for b in at.button if b.label == "Switch public participation ON")
        self.assertTrue(button.disabled)

    def test_paused_is_shown_separately(self):
        self.s.tables["reward_program_settings"][0]["public_enabled"] = True
        self.s.tables["reward_program_settings"][0]["paused"] = True
        at = self.app(OWNER_ID).run()
        self.assertIn("PAUSED", self.tiles(at))
        self.assertTrue(any("paused" in w.value for w in at.warning))

    def test_players_see_rewards_only_when_both_switches_are_on(self):
        ordinary = dict(PLAYER, email="someone@example.com", profile_id="c" * 64)
        at = self.app(ordinary, page="Explore").run()                 # owner switch OFF
        self.assertEqual([b for b in at.button if b.key == "rewards_menu"], [])
        self.s.tables["reward_program_settings"][0]["public_enabled"] = True
        self.hooks._health_cache.clear()
        at = self.app(ordinary, page="Explore").run()
        self.assertTrue([b for b in at.button if b.key == "rewards_menu"])


if __name__ == "__main__":
    unittest.main()
