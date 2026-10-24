"""Friends & Family Pilot in the app: three independent modes, as players and the owner see them.

Public educational access never needs anything; the invitation-only pilot opens for invited people only (pilot switch
+ published pilot documents); public rewards enrolment needs the public switches AND invitation-only switched off.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import legal_fixtures  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

OWNER = {"iss": "https://accounts.google.com", "sub": "o1", "email": "owner@example.com", "email_verified": True,
         "name": "Owner", "profile_id": "a" * 64}
FRIEND = {"iss": "https://accounts.google.com", "sub": "f1", "email": "friend@example.com", "email_verified": True,
          "name": "Ada Friend", "profile_id": "b" * 64}
STRANGER = {"iss": "https://accounts.google.com", "sub": "s1", "email": "stranger@example.com", "email_verified": True,
            "name": "Sam Stranger", "profile_id": "c" * 64}


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class PilotAppTests(unittest.TestCase):
    def setUp(self):
        import importlib
        self.hooks = sys.modules.get("ui.rewards_hooks") or importlib.import_module("ui.rewards_hooks")
        self.hooks._memory_store.clear()
        self.hooks._health_cache.clear()
        self.s = self.hooks._memory_store()
        self.s.tables["reward_cashout_settings"][0]["owner_emails"] = [OWNER["email"]]

    def app(self, who, page="Rewards", public=False, legal=True, rewards_enabled=False):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.secrets["rewards"] = {"enabled": rewards_enabled}
        if legal:
            at.secrets["legal"] = legal_fixtures.secrets()
        at.secrets["analytics"] = {"owner_emails": [OWNER["email"]]}
        at.session_state["page"] = page
        if page == "Owner":
            at.session_state["owner_tab"] = "💰 Rewards & Referral Management"
        self.s.tables["reward_program_settings"][0]["public_enabled"] = public
        for patch in (mock.patch("core.accounts.identity", return_value=dict(who)),
                      mock.patch.object(self.hooks, "_supabase", return_value=self.s),
                      mock.patch.object(self.hooks, "store_health", return_value="ok")):
            patch.start()
            self.addCleanup(patch.stop)
        return at

    def pilot_on(self, terms=None):
        """Record the approved pilot terms (the published sample documents) and switch the pilot on."""
        self.s.set_participation_terms("pilot", terms or legal_fixtures.pilot_terms_id(), OWNER["email"])
        self.s.set_pilot(True, OWNER["email"], confirmed=True)

    def text(self, at):
        return " ".join(str(m.value) for m in list(at.markdown) + list(at.info) + list(at.warning) + list(at.caption))

    def button(self, at, label):
        return next((b for b in at.button if b.label == label), None)

    def test_stranger_sees_no_rewards_page_while_only_the_pilot_is_open(self):
        self.pilot_on()
        self.s.invite(FRIEND["email"], OWNER["email"])
        at = self.app(STRANGER).run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("This page is not available.", [i.value for i in at.info])
        self.assertIsNone(self.s.account(STRANGER["profile_id"]))      # nothing is created for them

    def test_invited_friend_applies_and_sees_no_money_parts(self):
        self.pilot_on()
        self.s.invite(FRIEND["email"], OWNER["email"])
        at = self.app(FRIEND).run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIsNotNone(self.button(at, "Apply to the Friends & Family Pilot"))
        at.selectbox(key="rw_f_state").select("Kano")
        for key in ("rw_f_adult", "rw_f_resident", "rw_f_terms"):
            at.checkbox(key=key).check()
        at.button[[b.label for b in at.button].index("Apply to the Friends & Family Pilot")].click().run()
        app = self.s.founding_application(FRIEND["profile_id"])
        self.assertEqual(app["status"], "pending")
        self.assertEqual(app["terms_version"], legal_fixtures.pilot_terms_id())   # the version shown and accepted
        self.assertIn("No payments are available during the pilot", self.text(at))
        labels = [b.label for b in at.button]
        self.assertNotIn("Join", labels)                              # no joining, earning or invitation links
        self.assertFalse(any("invitation link" in s.lower() for s in labels))

    def test_pilot_wording_and_the_published_pilot_terms(self):
        self.pilot_on()
        self.s.invite(FRIEND["email"], OWNER["email"])
        at = self.app(FRIEND).run()
        text = self.text(at)
        self.assertIn("World Explorer — Friends & Family Pilot", text)
        self.assertIn("Educational points and badges have no monetary value", text)
        self.assertIn("Friends & Family Pilot: Participation Terms", text)            # the actual pilot terms
        self.assertIn(f"Friends & Family Pilot terms ({legal_fixtures.VERSION})", [x.label.split(" ", 1)[1] for x in at.expander])
        self.assertNotIn("pilot programme rules", text)                              # not the old rewards rules
        for money in ("earn rewards", "₦", "Founding 50"):
            self.assertNotIn(money, text, money)
        self.assertIsNotNone(self.button(at, "Apply to the Friends & Family Pilot"))
        self.assertIsNotNone(self.button(at, "🤝 Friends & Family Pilot"))           # the menu entry, no 💰

    def test_changed_pilot_terms_pause_applications_until_recorded_again(self):
        self.pilot_on(terms="2026-10-01#0000000000000000")                         # an older approved version
        self.s.invite(FRIEND["email"], OWNER["email"])
        at = self.app(FRIEND).run()
        self.assertIsNone(self.button(at, "Apply to the Friends & Family Pilot"))
        self.assertIn("Applications are closed at the moment", self.text(at))
        self.s.set_participation_terms("pilot", legal_fixtures.pilot_terms_id(), OWNER["email"])   # the owner records them
        self.hooks._health_cache.clear()
        at = self.app(FRIEND).run()
        self.assertIsNotNone(self.button(at, "Apply to the Friends & Family Pilot"))

    def test_pilot_stays_closed_until_the_pilot_documents_are_published(self):
        self.pilot_on()
        self.s.invite(FRIEND["email"], OWNER["email"])
        at = self.app(FRIEND, legal=False).run()
        self.assertIn("This page is not available.", [i.value for i in at.info])

    def test_public_switch_on_does_not_let_strangers_apply(self):
        self.s.tables["reward_program_settings"][0]["public_enabled"] = True
        at = self.app(STRANGER, public=True, rewards_enabled=True).run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIsNone(self.button(at, "Apply for the Founding 50"))
        self.assertIsNone(self.button(at, "Apply to the Friends & Family Pilot"))
        self.assertIn("by invitation only", self.text(at))
        self.assertIsNone(self.s.founding_application(STRANGER["profile_id"]))

    def test_owner_invites_and_switches_the_pilot_in_the_dashboard(self):
        at = self.app(OWNER, page="Owner").run()
        tab = next(t for t in at.tabs if t.label.startswith("🌟 Founding 50"))
        at.session_state["rw_tab"] = tab.label
        self.assertEqual([e.value for e in at.exception], [])
        at.text_input(key="pilot_invite_email").input("Friend@Example.com")
        at.button[[b.label for b in at.button].index("Add invitation")].click().run()
        self.assertTrue(self.s.pilot_invited("friend@example.com"))
        self.assertIsNone(next((b for b in at.button if b.key == "pilot_on" and not b.disabled), None))   # needs the tick
        at.button(key="pilot_terms_record").click().run()                          # record the approved terms
        self.assertEqual(self.s.pilot_status()["terms_version"], legal_fixtures.pilot_terms_id())
        at.checkbox(key="pilot_on_confirm").check().run()
        at.button(key="pilot_on").click().run()
        self.assertTrue(self.s.pilot_status()["enabled"])
        self.assertEqual([e.value for e in at.exception], [])

    # ---- regression 5 and 6

    def test_regression_5_public_educational_access_stays_unrestricted(self):
        """With the pilot open and invitation-only, guests and uninvited signed-in people still use everything
        educational: Explore, Learn, Quiz (a full answer) and Badges, with no application or invitation."""
        self.pilot_on()
        self.s.invite(FRIEND["email"], OWNER["email"])
        for who in (None, STRANGER):
            for page in ("Explore", "Learn", "Quiz", "Badges"):
                at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
                at.secrets["legal"] = legal_fixtures.secrets()
                at.session_state["page"] = page
                if who:
                    patch = mock.patch("core.accounts.identity", return_value=dict(who))
                    patch.start()
                    self.addCleanup(patch.stop)
                at.run()
                self.assertEqual([e.value for e in at.exception], [], (who and who["email"], page))
                self.assertNotIn("This page is not available.", [i.value for i in at.info], page)
                if page == "Quiz":
                    at.button(key="start_quiz").click().run()
                    q = at.session_state["quiz"]
                    qn = q["questions"][0]
                    at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
                    self.assertTrue(at.session_state["quiz"]["history"][0]["correct"])
                    self.assertGreater(at.session_state["points"], 0)          # educational points still count
                patch.stop() if who else None

    def test_regression_6_all_payouts_remain_disabled(self):
        """Pilot open with published documents: no money switch is on, so nothing can be requested or paid."""
        hooks = self.hooks
        self.pilot_on()
        with mock.patch.object(hooks.legal, "config", return_value=legal_fixtures.secrets()), \
                mock.patch.object(hooks, "config", return_value={}):              # default [rewards]: nothing set
            self.assertTrue(hooks.pilot_open())
            self.assertFalse(hooks.enabled())                                     # public rewards closed
            self.assertFalse(hooks.payouts_active())
            self.assertFalse(hooks.withdrawals_active())
        settings = self.s.cashout_settings()
        self.assertEqual((settings["live_requests"], settings["real_payouts"]), (False, False))


if __name__ == "__main__":
    unittest.main()
