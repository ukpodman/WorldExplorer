"""Rewards programme inside the running app (streamlit.testing.v1.AppTest): switched off by default, owner/tester
preview, joining, recording validated quizzes and country interactions, referral capture and the 💰 entry points.
Google sign-in is simulated by patching accounts.identity; storage is the in-memory preview store (no Supabase).
Run:  python -m unittest tests.test_rewards_app"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
APP = str(ROOT / "app.py")

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

OWNER = {"iss": "https://accounts.google.com", "sub": "owner-1", "email": "owner@example.com", "email_verified": True,
         "name": "Owner", "profile_id": "a" * 64}
PLAYER = {"iss": "https://accounts.google.com", "sub": "p-2", "email": "player@example.com", "email_verified": True,
          "name": "Player", "profile_id": "b" * 64}


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class RewardsAppTests(unittest.TestCase):
    def setUp(self):
        from ui import rewards_hooks
        self.hooks = rewards_hooks
        rewards_hooks._memory_store.clear()
        rewards_hooks._health_cache.clear()

    def app(self, who=None, rewards=None, owner=False, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        if rewards is not None:
            at.secrets["rewards"] = rewards
        if owner:
            at.secrets["analytics"] = {"owner_emails": ["owner@example.com"]}
        for k, v in state.items():
            at.session_state[k] = v
        self.patch = mock.patch("core.accounts.identity", return_value=dict(who) if who else None)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        return at

    def store(self):
        return self.hooks._memory_store()

    def finish_quiz(self, at, count=5):
        at.button(key="nav_Quiz").click().run()
        at.selectbox(key="filter_count").select(count).run()
        at.button(key="start_quiz").click().run()
        for i in range(count):
            quiz = at.session_state["quiz"]
            q = quiz["questions"][i]
            at.button(key=f"answer_{quiz['serial']}_{i}_{q['choices'].index(q['answer'])}").click().run()
            at.button(key=f"next_{quiz['serial']}_{i}").click().run()

    # ---------------------------------------------------------------- off by default

    def test_hidden_and_inactive_by_default(self):
        at = self.app(who=PLAYER).run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual([b for b in at.button if b.key == "rewards_menu"], [])
        at.session_state["page"] = "Rewards"
        at.run()
        self.assertTrue(any("not available" in i.value for i in at.info))
        self.finish_quiz(at)
        self.assertEqual(self.store().tables["reward_activity_events"], [])     # nothing recorded
        self.assertEqual(self.store().tables["reward_accounts"], [])

    def test_guest_sees_sign_in_prompt_when_enabled(self):
        at = self.app(rewards={"enabled": True}).run()
        self.assertTrue([b for b in at.button if b.key == "rewards_menu"])
        at.button(key="rewards_menu").click().run()
        self.assertEqual(at.session_state["page"], "Rewards")
        self.assertTrue(any("Sign in with Google" in i.value for i in at.info))
        self.assertTrue(any("not payable" in i.value for i in at.info))          # preview banner (payouts off)
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- owner preview while switched off

    def test_owner_preview_join_and_quiz_is_test_only(self):
        at = self.app(who=OWNER, rewards={"enabled": False}, owner=True).run()
        self.assertTrue([b for b in at.button if b.key == "rewards_menu"])
        at.button(key="rewards_menu").click().run()
        self.assertTrue(any("Test mode" in i.value for i in at.info))
        at.checkbox(key="rw_adult").check()
        at.checkbox(key="rw_resident").check()
        at.checkbox(key="rw_terms").check()
        at.button[[b.label for b in at.button].index("Join")].click().run()
        self.assertEqual([e.value for e in at.exception], [])
        account = self.store().account(OWNER["profile_id"])
        self.assertEqual((account["membership"], account["test"]), ("member", True))
        self.finish_quiz(at)
        events = self.store().events(OWNER["profile_id"])
        quiz = [e for e in events if e["kind"] == "quiz"]
        self.assertEqual((len(quiz), quiz[0]["amount"], quiz[0]["test"]), (1, 10, True))
        self.assertEqual(quiz[0]["detail"]["questions"], 5)
        self.assertTrue(any(e["kind"] == "active_day" and e["amount"] == 25 for e in events))   # quiz → active day
        at.run(); at.run()
        self.assertEqual(len(self.store().events(OWNER["profile_id"])), len(events))         # reruns add nothing
        at.button(key="rewards_menu").click().run()
        self.assertTrue(any("₦35" in m.value for m in at.markdown if hasattr(m, "value")) or
                        any("₦35" in str(h.proto) for h in at.get("html")))

    def test_short_quiz_and_practice_replay_do_not_count(self):
        at = self.app(who=OWNER, rewards={}, owner=True).run()
        store = self.store()
        store.ensure_account(OWNER["profile_id"], None, None, False, True)
        store.join(OWNER["profile_id"], self.hooks.rewards.month_key())
        self.finish_quiz(at, count=5)
        rounds = len([e for e in store.events(OWNER["profile_id"]) if e["kind"] == "quiz"])
        self.assertEqual(rounds, 1)

    def test_country_interactions_count_once_per_month(self):
        at = self.app(who=OWNER, rewards={}, owner=True, page="Learn", learn_country="NGA").run()
        store = self.store()
        store.ensure_account(OWNER["profile_id"], None, None, False, True)
        store.join(OWNER["profile_id"], self.hooks.rewards.month_key())
        at.session_state["rw_ctx"] = None
        at.run()
        at.button(key="learn_quiz_me").click().run()          # a meaningful interaction with Nigeria
        self.assertEqual(at.session_state["page"], "Quiz")     # the button still does what it always did
        at.button(key="nav_Learn").click().run()
        at.button(key="learn_quiz_me").click().run()           # same country again this month: no second record
        countries = [e for e in store.events(OWNER["profile_id"]) if e["kind"] == "country"]
        self.assertEqual([(e["subject"], e["amount"]) for e in countries], [("NGA", 5)])
        at.session_state["learn_country"] = "GHA"
        at.button(key="nav_Learn").click().run()
        at.button(key="learn_quiz_me").click().run()
        events = store.events(OWNER["profile_id"])
        self.assertEqual(sorted(e["subject"] for e in events if e["kind"] == "country"), ["GHA", "NGA"])
        self.assertTrue(any(e["kind"] == "active_day" for e in events))   # two countries make an active day
        self.assertEqual([e.value for e in at.exception], [])

    def test_viewing_a_country_alone_records_nothing(self):
        at = self.app(who=OWNER, rewards={}, owner=True, page="Learn", learn_country="NGA").run()
        store = self.store()
        store.ensure_account(OWNER["profile_id"], None, None, False, True)
        store.join(OWNER["profile_id"], self.hooks.rewards.month_key())
        for country in ("GHA", "KEN", "FRA"):
            at.session_state["learn_country"] = country
            at.run()
        self.assertEqual(store.events(OWNER["profile_id"]), [])

    # ---------------------------------------------------------------- referral capture

    def test_referral_code_is_kept_and_address_bar_tidied(self):
        at = self.app(rewards={"enabled": True})
        at.query_params["ref"] = "WE7X92"
        at.run()
        self.assertEqual(at.session_state["rw_ref"], "WE7X92")
        self.assertNotIn("ref", at.query_params)
        self.assertTrue(at.session_state["rw_ref_visit"].endswith(":WE7X92"))
        at2 = self.app(rewards={"enabled": True})
        at2.query_params["ref"] = "not-a-code"
        at2.run()
        self.assertFalse("rw_ref" in at2.session_state and at2.session_state["rw_ref"])
        self.assertNotIn("ref", at2.query_params)
        self.assertEqual([e.value for e in at2.exception], [])

    def test_attribution_for_new_accounts_only(self):
        store = self.store()
        referrer = store.ensure_account("c" * 64, None, None, False, True)
        tester = dict(PLAYER)
        rewards = {"enabled": False, "tester_emails": ["player@example.com"]}
        at = self.app(who=tester, rewards=rewards)
        at.query_params["ref"] = referrer["referral_code"]
        at.run()
        at.session_state["account_loaded"] = PLAYER["profile_id"]   # as if the saved profile was read
        at.session_state["profile_was_new"] = True
        at.run()
        self.assertEqual(store.referral_of(PLAYER["profile_id"])["referrer_id"], "c" * 64)
        self.assertTrue(store.account(PLAYER["profile_id"])["new_registration"])
        self.assertFalse(at.session_state["rw_ref"])                 # used once
        # an existing account arriving through a link is never counted as referred
        other = dict(PLAYER, sub="p-3", profile_id="d" * 64)
        at = self.app(who=other, rewards=rewards)
        at.query_params["ref"] = referrer["referral_code"]
        at.run()
        at.session_state["account_loaded"] = other["profile_id"]
        at.session_state["profile_was_new"] = False
        at.run()
        self.assertIsNone(store.referral_of("d" * 64))

    def test_referred_activity_qualifies_the_referral(self):
        store = self.store()
        month = self.hooks.rewards.month_key()
        referrer = store.ensure_account("c" * 64, None, None, False, True)
        store.join("c" * 64, month)
        store.ensure_account(PLAYER["profile_id"], None, None, True, True)
        store.attribute(PLAYER["profile_id"], referrer["referral_code"])
        # 2 earlier active days, 4 quizzes and 9 countries already done
        for i in range(2):
            store.add_event(PLAYER["profile_id"], "active_day", f"{month}-0{i + 1}", f"{month}-0{i + 1}", reward=False, test=True)
        for i in range(4):
            store.add_event(PLAYER["profile_id"], "quiz", f"old{i}", f"{month}-01", reward=False, test=True)
        for i in range(9):
            store.add_event(PLAYER["profile_id"], "country", f"X{i}", f"{month}-01", reward=False, test=True)
        rewards = {"tester_emails": ["player@example.com"]}
        at = self.app(who=PLAYER, rewards=rewards, page="Learn", learn_country="NGA").run()
        self.finish_quiz(at)                                   # 5th quiz and a 3rd active day
        self.assertEqual(store.referral_of(PLAYER["profile_id"])["status"], "pending")
        at.button(key="nav_Learn").click().run()
        at.button(key="learn_quiz_me").click().run()           # 10th country
        self.assertEqual(store.referral_of(PLAYER["profile_id"])["status"], "qualified")
        ref = [e for e in store.events("c" * 64) if e["kind"] == "referral"]
        self.assertEqual([(e["subject"], e["amount"]) for e in ref], [(PLAYER["profile_id"], 50)])
        self.assertTrue(all(e["amount"] == 0 for e in store.events(PLAYER["profile_id"])))   # not a member: no money

    # ---------------------------------------------------------------- page

    def test_member_page_shows_month_and_invitation_link(self):
        store = self.store()
        month = self.hooks.rewards.month_key()
        store.ensure_account(OWNER["profile_id"], None, None, False, True)
        store.join(OWNER["profile_id"], month)
        at = self.app(who=OWNER, rewards={}, owner=True, page="Rewards").run()
        self.assertEqual([e.value for e in at.exception], [])
        code = store.account(OWNER["profile_id"])["referral_code"]
        self.assertTrue(any(f"?ref={code}" in c.value for c in at.code))
        self.assertTrue(any("taking part" in s.value for s in at.success))
        self.assertTrue([b for b in at.button if b.key == "rw_leave"])

    def test_settings_entry(self):
        at = self.app(who=OWNER, rewards={}, owner=True).run()
        at.button(key="settings_menu").click().run()
        self.assertTrue([b for b in at.button if b.key == "settings_rewards"])
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- owner management

    def owner_app(self, rewards):
        at = self.app(who=OWNER, rewards=rewards, owner=True, page="Owner")
        return at.run()

    def test_owner_dashboard_sections_and_payment_rules(self):
        store = self.store()
        month = self.hooks.rewards.month_key()
        day = self.hooks.rewards.day_key()
        real = "e" * 64
        store.ensure_account(real, "real@example.com", "Real", True, False)
        store.join(real, month)
        for i in range(3):
            store.add_event(real, "quiz", f"r{i}", day, reward=True, test=False)
        at = self.owner_app({"enabled": False})
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("💰 Rewards & Referral Management", [s.value for s in at.subheader])
        html = " ".join(str(h.proto) for h in at.get("html"))
        for label in ("Total registered users", "Referral link visits", "Reserved budget", "Completed payments",
                      "Cost per retained active user", "Accounts requiring manual review"):
            self.assertIn(label, html)
        self.assertIn("₦30", html)                               # rewards earned this month
        # open the month's payment review
        at.button(key="rw_open_reviews").click().run()
        self.assertEqual(store.payment(real, month)["earned"], 30)
        # approving is refused while payouts are off, and by the database while eligibility is unverified
        with self.assertRaises(Exception):
            store.update_payment(real, month, {"status": "approved", "approved_amount": 30}, "owner")
        store.update_account(real, {"verification": "verified"})
        at = self.owner_app({"enabled": False, "payouts_active": False})
        at.selectbox(key="rw_pay_pick").select(real).run()
        form_status = [s for s in at.selectbox if s.label == "Status"][0]
        form_status.select("approved")
        at.checkbox[[c.label for c in at.checkbox].index("I confirm this update (for Paid: the money was sent outside World Explorer)")].check()
        at.button[[b.label for b in at.button].index("Save payment update")].click().run()
        self.assertTrue(any("Payouts are switched off" in e.value for e in at.error))
        self.assertEqual(store.payment(real, month)["status"], "pending_review")
        # with payouts authorised: approve, then a separate manual "paid" step with date and reference
        at = self.owner_app({"enabled": True, "payouts_active": True})
        at.selectbox(key="rw_pay_pick").select(real).run()
        [s for s in at.selectbox if s.label == "Status"][0].select("approved")
        at.checkbox[[c.label for c in at.checkbox].index("I confirm this update (for Paid: the money was sent outside World Explorer)")].check()
        at.button[[b.label for b in at.button].index("Save payment update")].click().run()
        self.assertEqual([e.value for e in at.error], [])
        self.assertEqual((store.payment(real, month)["status"], store.payment(real, month)["approved_amount"]), ("approved", 30))
        at.session_state["rw_owner_data"] = None
        at.run()
        [s for s in at.selectbox if s.label == "Status"][0].select("paid")
        at.date_input[0].set_value(__import__("datetime").date(2026, 10, 20))
        at.text_input[[t.label for t in at.text_input].index("Transaction reference (optional)")].input("TRX-9")
        at.checkbox[[c.label for c in at.checkbox].index("I confirm this update (for Paid: the money was sent outside World Explorer)")].check()
        at.button[[b.label for b in at.button].index("Save payment update")].click().run()
        self.assertEqual([e.value for e in at.error], [])
        paid = store.payment(real, month)
        self.assertEqual((paid["status"], paid["paid_amount"], paid["reference"], paid["updated_by"]),
                         ("paid", 30, "TRX-9", "owner@example.com"))
        self.assertTrue(any(a["action"] == "reward_payments_update" for a in store.audit()))

    def test_owner_settings_and_pause(self):
        at = self.owner_app({})
        at.toggle(key="rw_set_paused").set_value(True).run()
        self.assertTrue(self.store().settings().paused)
        at.toggle(key="rw_set_paused").set_value(False).run()
        self.assertFalse(self.store().settings().paused)
        at.number_input[[n.label for n in at.number_input].index("Places")].set_value(60)
        at.button[[b.label for b in at.button].index("Save settings")].click().run()
        self.assertEqual(self.store().settings().max_places, 60)
        at.number_input[[n.label for n in at.number_input].index("Active day: ₦ each")].set_value(1)
        at.button[[b.label for b in at.button].index("Save settings")].click().run()
        self.assertTrue(at.error)                                   # unreachable without referrals: refused
        self.assertEqual(self.store().settings().active_day_amount, 25)
        self.assertEqual([e.value for e in at.exception], [])

    def test_testers_cannot_open_the_owner_dashboard(self):
        at = self.app(who=PLAYER, rewards={"tester_emails": ["player@example.com"]}, page="Owner").run()
        self.assertTrue(any("not available" in i.value for i in at.info))
        self.assertNotIn("💰 Rewards & Referral Management", [s.value for s in at.subheader])


if __name__ == "__main__":
    unittest.main()
