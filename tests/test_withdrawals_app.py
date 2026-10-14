"""V21 withdrawals inside the running app (streamlit.testing.v1.AppTest): the grey/green button, the application
form, the owner notification, approval, the two-step "Mark as paid", switches and test-mode simulation. Google sign-in
is simulated by patching accounts.identity; storage is the in-memory preview store (the same rules as the SQL).
Run:  python -m unittest discover -s tests -p test_withdrawals_app.py"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
APP = str(ROOT / "app.py")

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

from core import rewards, withdrawals  # noqa: E402
from core.rewards import Settings  # noqa: E402

OWNER = {"iss": "https://accounts.google.com", "sub": "owner-1", "email": "owner@example.com", "email_verified": True,
         "name": "Owner", "profile_id": "a" * 64}
PLAYER = {"iss": "https://accounts.google.com", "sub": "p-2", "email": "player@example.com", "email_verified": True,
          "name": "Ade Player", "profile_id": "b" * 64}
CUR = withdrawals.month_of(withdrawals.today())
M2 = rewards.previous_month(CUR)
M1 = rewards.previous_month(M2)
DECL = {k: True for k in withdrawals.DECLARATIONS}


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class WithdrawalAppTests(unittest.TestCase):
    def setUp(self):
        from ui import rewards_hooks
        self.hooks = rewards_hooks
        rewards_hooks._memory_store.clear()
        rewards_hooks._health_cache.clear()
        self.s = rewards_hooks._memory_store()
        self.s.save_settings(Settings(start_date=f"{M1}-01"), "owner@example.com")

    def app(self, who, live=True, payouts=False, page="Rewards", **rewards_cfg):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["rewards"] = {"enabled": True, "tester_emails": ["player@example.com"], "withdrawals_active": live,
                                 "payouts_active": payouts, **rewards_cfg}
        at.secrets["analytics"] = {"owner_emails": ["owner@example.com"]}
        at.session_state["page"] = page
        patch = mock.patch("core.accounts.identity", return_value=dict(who))
        patch.start()
        self.addCleanup(patch.stop)
        return at

    def player(self, pid="b" * 64, test=False, days_ago=45, live=True, name="Ade Player", real_payouts=True):
        s = self.s
        s.ensure_account(pid, "player@example.com", name, True, test)
        s.join(pid, M2)
        s.enrol(pid, CUR)
        stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        for e in s.tables["reward_enrolments"]:
            if e["profile_id"] == pid:
                e["created_at"] = stamp
        for i in range(20):
            d = f"{M2}-{1 + i:02d}"
            s.add_event(pid, "active_day", d, d, reward=True, test=test)
        for i in range(30):
            s.add_event(pid, "quiz", f"q{i}", f"{M2}-{1 + i // 3:02d}", reward=True, test=test)
        for i in range(10):
            s.add_event(pid, "country", f"C{i}", f"{M2}-{1 + i // 5:02d}", reward=True, test=test)
        s.tables["reward_cashout_settings"][0].update(live_requests=live, real_payouts=real_payouts,
                                                      owner_emails=["owner@example.com"])
        return pid

    def button(self, at, key):
        return next((b for b in at.button if b.key == key), None)

    # ---------------------------------------------------------------- player

    def test_grey_button_counts_down_the_waiting_period(self):
        self.player(days_ago=18)
        at = self.app(PLAYER).run()
        self.assertEqual([x.value for x in at.exception], [])
        grey = self.button(at, "rw_withdraw_grey")
        self.assertIsNotNone(grey)
        self.assertTrue(grey.disabled)
        self.assertIn("Available in", grey.label)
        self.assertIsNone(self.button(at, "rw_withdraw_go"))

    def test_grey_until_live_for_real_accounts(self):
        self.player(live=False)
        at = self.app(PLAYER, live=True).run()
        self.assertIn("official launch", self.button(at, "rw_withdraw_grey").label)

    def test_request_flow_creates_one_pending_request_and_notifies_the_owner(self):
        self.player()
        at = self.app(PLAYER).run()
        go = self.button(at, "rw_withdraw_go")
        self.assertEqual(go.label, "💰 Request Withdrawal — ₦850")
        go.click().run()
        at.text_input(key="rw_cash_legal").input("Ade Player")
        for k in withdrawals.DECLARATIONS[:3]:
            at.checkbox(key=f"rw_cash_decl_{k}").check()
        at.button(key="FormSubmitter:rw_cash_form-Submit Withdrawal Request").click().run()
        self.assertTrue(any("all four" in x.value for x in at.error))           # every declaration is required
        self.assertEqual(self.s.cashout_requests(), [])
        at.checkbox(key="rw_cash_decl_false_information").check()
        at.button(key="FormSubmitter:rw_cash_form-Submit Withdrawal Request").click().run()
        self.assertEqual([x.value for x in at.exception], [])
        reqs = self.s.cashout_requests()
        self.assertEqual(len(reqs), 1)
        self.assertEqual((reqs[0]["status"], reqs[0]["amount"], reqs[0]["legal_name"]), ("pending_review", 850, "Ade Player"))
        page = " ".join(m.value for m in at.markdown)
        self.assertIn("Withdrawal Request Submitted", page)
        self.assertIn(reqs[0]["reference"], page)
        self.assertIsNone(self.button(at, "rw_withdraw_go"))                      # no second request possible
        notes = self.s.notifications(unread=True)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["email_status"], "not_configured")             # optional e-mail never blocks

    def test_translated_button_in_five_languages(self):
        self.player()
        expected = {"Deutsch": "Auszahlung beantragen", "Español": "Solicitar retiro", "中文（普通话）": "申请提现",
                    "Русский": "Запросить вывод"}
        for language, text in expected.items():
            at = self.app(PLAYER)
            at.session_state["app_language"] = language
            at.run()
            self.assertIn(text, self.button(at, "rw_withdraw_go").label, language)

    # ---------------------------------------------------------------- owner

    def owner_tab(self, payouts=True):
        at = self.app(OWNER, payouts=payouts, page="Owner").run()
        self.assertEqual([x.value for x in at.exception], [])
        return at

    def test_owner_notification_review_approve_and_two_step_payment(self):
        pid = self.player()
        req = self.s.request_cashout(pid, "Ade Player", DECL, 850)
        at = self.owner_tab()
        self.assertTrue(any("1 new withdrawal request" in w.value for w in at.warning))
        self.assertTrue(any(t.label.startswith("💳 Withdrawals (1)") for t in at.tabs))   # unread requests
        self.assertTrue(any("NEW WITHDRAWAL REQUEST" in m.value for m in at.markdown))
        open_btn = next(b for b in at.button if b.key and b.key.startswith("rw_note_open_"))
        open_btn.click().run()
        self.assertEqual(self.s.notifications(unread=True), [])                  # opened = read
        approve = next(b for b in at.button if b.label == "Approve")
        approve.click().run()                                                    # checks not ticked
        self.assertTrue(any("Confirm both checks" in x.value for x in at.error))
        for c in at.checkbox:
            if c.label.startswith(("I confirmed the player's eligibility", "I verified that the bank account")):
                c.check()
        next(b for b in at.button if b.label == "Approve").click().run()
        self.assertEqual(self.s.cashout_request(req["id"])["status"], "approved")
        self.assertEqual(self.s.cashout_payments(), [])                          # approval moved no money
        next(c for c in at.checkbox if c.label.startswith("I have transferred")).check()
        next(b for b in at.button if b.label == "Mark as paid…").click().run()
        self.assertEqual(self.s.cashout_payments(), [])                          # first step: confirmation only
        self.assertTrue(any("Final confirmation" in w.value for w in at.warning))
        next(b for b in at.button if b.label == "Confirm and record payment").click().run()
        pays = self.s.cashout_payments()
        self.assertEqual(len(pays), 1)
        self.assertEqual((pays[0]["amount"], pays[0]["recorded_by"]), (850, "owner@example.com"))
        self.assertEqual(self.s.cashout_request(req["id"])["status"], "paid")
        self.assertTrue(any("payment of ₦850 recorded" in x.value for x in at.success))

    def test_payouts_off_blocks_real_approval_in_the_dashboard(self):
        pid = self.player()
        self.s.request_cashout(pid, "Ade Player", DECL, 850)
        at = self.owner_tab(payouts=False)
        next(b for b in at.button if b.key and b.key.startswith("rw_note_open_")).click().run()
        approve = next(b for b in at.button if b.label == "Approve")
        self.assertTrue(approve.disabled)
        self.assertTrue(any("payouts_active = false" in i.value for i in at.info))

    def test_reject_needs_an_explanation_and_releases_the_earnings(self):
        pid = self.player()
        req = self.s.request_cashout(pid, "Ade Player", DECL, 850)
        at = self.owner_tab()
        next(b for b in at.button if b.key and b.key.startswith("rw_note_open_")).click().run()
        next(b for b in at.button if b.label == "Reject").click().run()
        self.assertTrue(any("reason" in x.value for x in at.error))
        at.text_area(key=f"rw_cash_no_r_{req['id']}").input("The bank account belongs to someone else")
        next(b for b in at.button if b.label == "Reject").click().run()
        self.assertEqual(self.s.cashout_request(req["id"])["status"], "rejected")
        self.assertTrue(self.s.cashout_status(pid)["eligible"])

    def test_database_payout_switch_blocks_real_approval_even_with_the_app_switch_on(self):
        pid = self.player(real_payouts=False)
        req = self.s.request_cashout(pid, "Ade Player", DECL, 850)
        at = self.owner_tab(payouts=True)
        next(b for b in at.button if b.key and b.key.startswith("rw_note_open_")).click().run()
        for c in at.checkbox:
            if c.label.startswith(("I confirmed the player's eligibility", "I verified that the bank account")):
                c.check()
        next(b for b in at.button if b.label == "Approve").click().run()
        self.assertTrue(any("real_payouts = false" in x.value for x in at.error))
        self.assertEqual(self.s.cashout_request(req["id"])["status"], "pending_review")

    def test_notifications_wait_for_the_owner_and_count_unread(self):
        a = self.player()
        b = self.player(pid="c" * 64, name="Bola Ade")
        self.s.request_cashout(a, "Ade Player", DECL, 850)          # submitted while the owner was away
        self.s.request_cashout(b, "Bola Ade", DECL, 850)
        at = self.owner_tab()
        self.assertTrue(any("2 new withdrawal requests" in w.value for w in at.warning))
        self.assertTrue(any("Notifications (2 unread)" in m.value for m in at.markdown))
        self.assertTrue(any(t.label == "💳 Withdrawals (2)" for t in at.tabs))
        at.run()                                                    # still there until handled
        self.assertTrue(any("Notifications (2 unread)" in m.value for m in at.markdown))
        next(b for b in at.button if b.key and b.key.startswith("rw_note_open_")).click().run()
        self.assertTrue(any("Notifications (1 unread)" in m.value for m in at.markdown))
        self.assertTrue(any("1 new withdrawal request " in w.value for w in at.warning))

    def test_no_english_left_in_other_languages(self):
        """Every player-visible withdrawal text is translated (except names, references, amounts and dates)."""
        import json
        strings = json.load(open(ROOT / "data" / "translations.json", encoding="utf-8"))["strings"]
        from ui import withdraw_ui
        english = set(withdraw_ui.DECLARATION_TEXT.values()) | {x for pair in withdraw_ui.PLAYER_STATUS.values()
                                                                 for x in pair}
        english |= {label for _, label in withdraw_ui.BLOCKED if label}
        english |= {"Withdraw your rewards", "Total earned", "Available now", "Pending withdrawal",
                    "Remaining unpaid", "Eligibility requirements", "Legal name", "Submit Withdrawal Request",
                    "Withdrawal history", "Verified available balance", "Eligible earning period",
                    withdrawals.TEST_LABEL}
        self.player(days_ago=18)                                      # locked
        b = self.player(pid="c" * 64, name="Bola Ade")                # pending
        self.s.request_cashout(b, "Bola Ade", DECL, 850)
        self.player(pid="d" * 64, name="Chi Eze")                     # eligible: the form is opened
        for language in ("Deutsch", "Español", "中文（普通话）", "Русский"):
            for pid in ("b" * 64, "c" * 64, "d" * 64):
                at = self.app(dict(PLAYER, profile_id=pid))
                at.session_state["app_language"] = language
                at.run()
                if pid == "d" * 64:
                    self.button(at, "rw_withdraw_go").click().run()
                    self.assertIsNotNone(at.text_input(key="rw_cash_legal"))
                texts = [m.value for m in at.markdown] + [c.value for c in at.caption] + \
                        [x.label for x in at.button] + [w.value for w in at.warning] + \
                        [x.value for x in at.subheader] + [x.label for x in at.checkbox] + \
                        [x.label for x in at.text_input]
                page = "\n".join(texts)
                index = ["Deutsch", "Español", "中文（普通话）", "Русский"].index(language)
                for text in english:
                    self.assertIn(text, strings, f"missing translation for '{text}'")
                    self.assertNotEqual(strings[text][index], text, f"{language}: '{text}' is not translated")
                    self.assertNotIn(text, page, f"{language}: untranslated '{text}' on the page")

    # ---------------------------------------------------------------- test mode

    def test_test_account_simulation(self):
        pid = self.player(pid="a" * 64, test=True, days_ago=0, live=False, name="Owner")
        at = self.app(OWNER, live=False).run()
        self.assertEqual([x.value for x in at.exception], [])
        self.assertIn("Available in", self.button(at, "rw_withdraw_grey").label)
        self.assertTrue(any(withdrawals.TEST_LABEL in w.value for w in at.warning))
        at.number_input(key="rw_sim_days").set_value(31).run()
        go = self.button(at, "rw_withdraw_go")
        self.assertIsNotNone(go)                                                 # simulated: waiting period passed
        go.click().run()
        at.text_input(key="rw_cash_legal").input("Owner Test")
        for k in withdrawals.DECLARATIONS:
            at.checkbox(key=f"rw_cash_decl_{k}").check()
        at.button(key="FormSubmitter:rw_cash_form-Submit Withdrawal Request").click().run()
        req = self.s.cashout_requests(pid)[0]
        self.assertTrue(req["test"])
        self.assertIsNotNone(req["simulated_as_of"])
        self.assertEqual([r for r in self.s.cashout_requests() if not r["test"]], [])


if __name__ == "__main__":
    unittest.main()
