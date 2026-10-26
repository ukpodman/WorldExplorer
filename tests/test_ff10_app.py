"""Friends & Family 10 in the running app: the participant's progress card, learning-time recording from real
interactions, and the Owner's management tab with the monthly settlement (in-memory store, published sample legal
documents)."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import legal_fixtures  # noqa: E402

from core import rewards  # noqa: E402
from core.rewards import LAGOS  # noqa: E402

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
LAST = rewards.previous_month(rewards.month_key())


def lagos(day: str, minute: int) -> str:
    y, m, d = map(int, day.split("-"))
    return (datetime(y, m, d, 0, 5, tzinfo=LAGOS) + timedelta(minutes=minute)).isoformat()


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class FF10AppTests(unittest.TestCase):
    def setUp(self):
        import importlib
        self.hooks = sys.modules.get("ui.rewards_hooks") or importlib.import_module("ui.rewards_hooks")
        self.hooks._memory_store.clear()
        self.hooks._health_cache.clear()
        self.s = self.hooks._memory_store()
        self.s.tables["reward_cashout_settings"][0]["owner_emails"] = [OWNER["email"]]
        self.s.set_participation_terms("pilot", legal_fixtures.pilot_terms_id(), OWNER["email"])
        self.s.set_pilot(True, OWNER["email"], confirmed=True)

    def app(self, who, page="Rewards", public=False, legal=True):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.secrets["rewards"] = {"enabled": public}
        if legal:
            at.secrets["legal"] = legal_fixtures.secrets()
        at.secrets["analytics"] = {"owner_emails": [OWNER["email"]]}
        at.session_state["page"] = page
        if page == "Owner":
            at.session_state["owner_tab"] = "💰 Rewards & Referral Management"
        self.s.tables["reward_program_settings"][0]["public_enabled"] = public
        patches = [mock.patch("core.accounts.identity", return_value=dict(who) if who else None),
                   mock.patch.object(self.hooks, "_supabase", return_value=self.s),
                   mock.patch.object(self.hooks, "store_health", return_value="ok")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return at

    def join(self, who, approve=True):
        self.s.ensure_account(who["profile_id"], who["email"], who["name"], True, False)
        self.s.invite(who["email"], OWNER["email"])
        app = self.s.apply_founding(who["profile_id"], "Lagos", None, True, True, True,
                                    terms_version=legal_fixtures.pilot_terms_id())
        if approve:
            self.s.decide_founding(app["id"], "approve", OWNER["email"])
        return who["profile_id"]

    def record(self, pid, kind, subject, at, detail=None):
        return self.s.rpc("pilot_record_activity_at", {"p_profile": pid, "p_kind": kind, "p_subject": subject,
                                                       "p_detail": detail, "p_at": at})

    def session(self, pid, day, minutes, quizzes=0, new=0, challenge=False, tag=""):
        for i in range(minutes + 1):
            self.record(pid, "view", f"{tag}{day}:{i}", lagos(day, i))
        for q in range(quizzes):
            self.record(pid, "quiz", f"{tag}q{day}:{q}", lagos(day, 1), {"questions": 10, "avg_seconds": 7})
        for c in range(new):
            self.record(pid, "country", f"{tag}C{day}:{c}", lagos(day, 2))
        if challenge:
            self.record(pid, "challenge", f"daily:{day}", lagos(day, 3))

    def text(self, at):
        return " ".join(str(m.value) for m in list(at.markdown) + list(at.info) + list(at.success) + list(at.caption)
                        + list(at.warning) + list(at.subheader))

    # ---- participant dashboard
    def test_participant_sees_todays_progress_and_provisional_rewards(self):
        pid = self.join(FRIEND)
        today = rewards.day_key()
        self.session(pid, today, 45, quizzes=2, new=1)
        at = self.app(FRIEND).run()
        self.assertEqual([e.value for e in at.exception], [])
        text = self.text(at)
        self.assertIn("Today's learning progress", text)
        self.assertIn("45 / 60 minutes", text)
        self.assertIn("₦350 / ₦500", text)
        self.assertIn("₦350 / ₦7,000", text)
        self.assertIn("Next milestone: 15 more minutes of active learning; complete today's Daily Challenge.", text)
        self.assertIn("Provisional rewards are estimates until the month is settled", text)
        self.assertIn("paid in naira by bank transfer", text)
        self.assertNotIn("not payable", text)
        self.assertNotIn("payments are currently disabled", text)
        self.assertNotIn("guaranteed", text.lower())
        self.assertNotIn("Test mode", text)

    def test_daily_maximum_message_discourages_more_screen_time(self):
        pid = self.join(FRIEND)
        self.session(pid, rewards.day_key(), 75, quizzes=2, new=1, challenge=True)
        text = self.text(self.app(FRIEND).run())
        self.assertIn("60 / 60 minutes", text)
        self.assertIn("₦500 / ₦500", text)
        self.assertIn("Rewards stop increasing for today", text)

    def test_settled_months_show_provisional_and_final_amounts(self):
        pid = self.join(FRIEND)
        for d in range(1, 15):
            self.session(pid, f"{LAST}-{d:02d}", 60, quizzes=2, new=1, challenge=True, tag=f"d{d}")
        preview = self.s.ff10_preview(LAST)
        self.s.ff10_settle(LAST, OWNER["email"], preview["fingerprint"], confirmed=True)
        text = self.text(self.app(FRIEND).run())
        self.assertIn(f"{LAST}: ₦7,000 provisional → ₦7,000 final allocation · Waiting for the Owner's review", text)

    def test_progress_texts_in_five_languages(self):
        import ast
        import json
        strings = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))["strings"]
        from ui import ff10_ui
        texts = set(ff10_ui.TIER_TEXT) | set(ff10_ui.LINE_TEXT.values()) - {"Paid"}
        for node in ast.walk(ast.parse((ROOT / "ui" / "ff10_ui.py").read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "t" and node.args:
                arg = node.args[0]
                for v in ([arg] if isinstance(arg, ast.Constant) else
                          [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else []):
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        texts.add(v.value)
        for text in texts:
            self.assertIn(text, strings, text)
            self.assertEqual(len(strings[text]), 4, text)
            self.assertTrue(all(strings[text]), text)
        pid = self.join(FRIEND)
        self.session(pid, rewards.day_key(), 20, quizzes=1)
        for language, words in (("Deutsch", "Heutiger Lernfortschritt"), ("Español", "Progreso de aprendizaje de hoy"),
                                ("中文（普通话）", "今日学习进度"), ("Русский", "Прогресс обучения за сегодня")):
            at = self.app(FRIEND)
            at.session_state["app_language"] = language
            at.run()
            self.assertEqual([e.value for e in at.exception], [])
            self.assertIn(words, self.text(at), language)

    # ---- the private terms: own approval record, acceptance before earning
    def test_participants_accept_updated_terms_before_earning(self):
        old = "2026-10-01#old0000000000000"
        self.s.set_participation_terms("pilot", old, OWNER["email"])
        self.s.ensure_account(FRIEND["profile_id"], FRIEND["email"], FRIEND["name"], True, False)
        self.s.invite(FRIEND["email"], OWNER["email"])
        app = self.s.apply_founding(FRIEND["profile_id"], "Lagos", None, True, True, True, terms_version=old)
        self.s.decide_founding(app["id"], "approve", OWNER["email"])
        self.s.set_participation_terms("pilot", legal_fixtures.pilot_terms_id(), OWNER["email"])   # new approved terms
        at = self.app(FRIEND).run()
        self.assertEqual([e.value for e in at.exception], [])
        text = self.text(at)
        self.assertIn("Please accept the current Friends & Family 10 terms", text)
        self.assertNotIn("Today's learning progress", text)
        labels = [x.label for x in at.expander]
        self.assertTrue(any("Friends & Family 10 terms" in x for x in labels), labels)
        self.assertTrue(any("Friends & Family 10 privacy notice" in x for x in labels), labels)
        self.assertIn(f"Approved by {legal_fixtures.APPROVED_BY} on {legal_fixtures.APPROVED_ON}.", text)
        quiz = self.app(FRIEND, page="Quiz").run()                                   # learning is not recorded yet
        quiz.button(key="start_quiz").click().run()
        q = quiz.session_state["quiz"]
        qn = q["questions"][0]
        quiz.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        self.assertEqual(self.s.ff10_activity(FRIEND["profile_id"]), [])
        at = self.app(FRIEND).run()
        self.assertTrue(at.button(key="ff10_accept").disabled)
        at.checkbox(key="ff10_accept_confirm").check().run()
        at.button(key="ff10_accept").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertTrue(self.s.ff10_terms_accepted(FRIEND["profile_id"]))
        self.assertIn("Today's learning progress", self.text(at))
        self.assertIsNotNone(self.record(FRIEND["profile_id"], "view", "NGA", lagos(rewards.day_key(), 1)))

    def test_owner_sees_the_approval_record_and_the_10_place_counter(self):
        self.join(FRIEND)
        at = self.app(OWNER, page="Owner").run()
        self.assertEqual([e.value for e in at.exception], [])
        html = " ".join(str(h.proto.body) for h in at.get("html"))
        self.assertIn("Private-pilot approval record", html)
        self.assertIn(legal_fixtures.APPROVED_BY, html)
        self.assertIn(legal_fixtures.APPROVED_ON, html)
        self.assertIn(legal_fixtures.checksum("pilot"), html)
        self.assertIn(legal_fixtures.checksum("pilot_privacy"), html)
        self.assertIn("1 / 10 approved", html)
        self.assertNotIn("/ 50", html)
        labels = [x.label for x in at.tabs]
        self.assertIn("Public (OFF) · Overview", labels)
        self.assertNotIn("Overview", labels)

    def test_people_who_are_not_approved_see_no_progress(self):
        self.join(FRIEND, approve=False)
        at = self.app(FRIEND).run()
        self.assertNotIn("Today's learning progress", self.text(at))

    # ---- learning time comes from real interactions
    def test_quiz_answers_and_learn_navigation_are_recorded_for_participants_only(self):
        pid = self.join(FRIEND)
        at = self.app(FRIEND, page="Quiz").run()
        at.button(key="start_quiz").click().run()
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        kinds = [r["kind"] for r in self.s.ff10_activity(pid)]
        self.assertIn("answer", kinds)
        self.assertTrue(all(not r["test"] for r in self.s.ff10_activity(pid)))
        self.s.ensure_account(STRANGER["profile_id"], STRANGER["email"], STRANGER["name"], True, False)
        at = self.app(STRANGER, page="Quiz").run()
        at.button(key="start_quiz").click().run()
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        self.assertEqual(self.s.ff10_activity(STRANGER["profile_id"]), [])
        self.assertGreater(at.session_state["points"], 0)                        # educational points unchanged

    def test_nothing_is_recorded_while_the_pilot_is_off(self):
        pid = self.join(FRIEND)
        self.s.set_pilot(False, OWNER["email"])
        at = self.app(FRIEND, page="Quiz").run()
        at.button(key="start_quiz").click().run()
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual(self.s.ff10_activity(pid), [])

    # ---- owner dashboard
    def owner_tab_text(self, at):
        return self.text(at)

    def test_owner_tab_figures_and_settlement(self):
        pid = self.join(FRIEND)
        for d in range(1, 4):
            self.session(pid, f"{LAST}-{d:02d}", 30, quizzes=2, tag=f"d{d}")       # 3 × ₦250
        self.session(pid, rewards.day_key(), 15, quizzes=1)                         # today ₦100
        at = self.app(OWNER, page="Owner").run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("📊 F&F 10 rewards", [t.label for t in at.tabs])
        html = " ".join(str(h.proto.body) for h in at.get("html"))
        for label in ("Approved participants", "1 / 10", "Monthly budget", "₦50,000", "Provisional this month",
                      "Remaining budget", "₦49,900", "Pending settlement reviews"):
            self.assertIn(label, html, label)
        self.assertIn("Ada Friend", html)
        self.assertTrue(at.button(key="ff10_settle").disabled)                     # needs the confirmation
        self.assertIn("₦750", html)                                                # last month's preview
        at.checkbox(key="ff10_settle_confirm").check().run()
        at.button(key="ff10_settle").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual(self.s.ff10_settlements()[0]["total_final"], 750)
        self.assertEqual(self.s.ff10_lines(LAST, pid)[0]["status"], "pending_review")
        approve = next(b for b in at.button if b.label == "✅ Approve allocation")
        approve.click().run()
        self.assertEqual(self.s.ff10_lines(LAST, pid)[0]["status"], "approved")
        self.assertFalse(self.s.cashout_settings()["real_payouts"])

    def test_owner_authorises_verifies_and_records_a_bank_transfer(self):
        pid = self.join(FRIEND)
        for d in range(1, 3):
            self.session(pid, f"{LAST}-{d:02d}", 30, quizzes=2, tag=f"d{d}")       # 2 × ₦250
        self.s.ff10_settle(LAST, OWNER["email"], self.s.ff10_preview(LAST)["fingerprint"], confirmed=True)
        self.s.ff10_decide(LAST, pid, "approve", OWNER["email"])
        at = self.app(OWNER, page="Owner").run()
        self.assertEqual([e.value for e in at.exception], [])
        html = " ".join(str(h.proto.body) for h in at.get("html"))
        self.assertIn("Public Rewards OFF", html)
        self.assertNotIn("❌", html)                                               # every readiness check passes
        self.assertTrue(at.button(key="ff10_payments_on").disabled)                # needs the confirmation
        at.checkbox(key="ff10_payments_confirm").check().run()
        at.button(key="ff10_payments_on").click().run()
        self.assertTrue(self.s.ff10_payments_enabled())
        at.text_input(key="ff10_ben_name").input("Ada Friend")
        at.text_input(key="ff10_ben_bank").input("Example Bank")
        at.text_input(key="ff10_ben_last4").input("1234")
        at.checkbox(key="ff10_ben_confirm").check()
        next(b for b in at.button if b.label == "Save verification").click().run()
        self.assertEqual(self.s.ff10_beneficiaries()[0]["account_last4"], "1234")
        at.number_input(key="ff10_pay_amount").set_value(500)
        at.text_input(key="ff10_pay_ref").input("FT26110512345")
        at.checkbox(key="ff10_pay_confirm").check()
        next(b for b in at.button if b.label == "Record payment").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        payment = self.s.ff10_payments(LAST)[0]
        self.assertEqual((payment["amount"], payment["bank_reference"], payment["beneficiary_name"]),
                         (500, "FT26110512345", "Ada Friend"))
        self.assertEqual(self.s.ff10_lines(LAST, pid)[0]["status"], "paid")
        self.assertIn("FT26110512345", " ".join(str(h.proto.body) for h in at.get("html")))   # the ledger
        self.assertFalse(self.s.public_status()["enabled"])
        self.assertEqual((self.s.cashout_settings()["real_payouts"], self.s.cashout_settings()["live_requests"]),
                         (False, False))
        text = self.text(self.app(FRIEND).run())
        self.assertIn(f"{LAST}: ₦500 provisional → ₦500 final allocation · Paid by bank transfer", text)

    def test_payments_cannot_be_authorised_without_the_legal_requirements(self):
        at = self.app(OWNER, page="Owner", legal=False)
        legal_fixtures.use_real()
        self.addCleanup(legal_fixtures.use_real)
        at.run()
        self.assertEqual([e.value for e in at.exception], [])
        html = " ".join(str(h.proto.body) for h in at.get("html"))
        self.assertIn("❌", html)
        self.assertIn("Operator verified", html)
        self.assertTrue(at.button(key="ff10_payments_on").disabled)
        self.assertTrue(at.checkbox(key="ff10_payments_confirm").disabled)
        self.assertFalse(self.s.ff10_payments_enabled())

    def test_owner_excludes_a_suspicious_day(self):
        pid = self.join(FRIEND)
        self.session(pid, f"{LAST}-02", 30, quizzes=2)
        at = self.app(OWNER, page="Owner").run()
        at.selectbox(key="ff10_pick_month").select(LAST).run()
        at.text_input(key="ff10_review_reason").input("Answers far too fast")
        next(b for b in at.button if b.label == "Exclude this day").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual(self.s.ff10_ledger(pid, LAST)[0]["amount"], 0)
        self.assertTrue(self.s.ff10_reviews()[0]["excluded"])

    def test_no_ff10_tab_once_public_rewards_are_on(self):
        at = self.app(OWNER, page="Owner", public=True).run()
        self.assertNotIn("📊 F&F 10 rewards", [t.label for t in at.tabs])

    def test_owner_test_records_are_marked_test(self):
        self.s.ensure_account(OWNER["profile_id"], OWNER["email"], OWNER["name"], True, True)
        at = self.app(OWNER, page="Quiz").run()
        at.button(key="start_quiz").click().run()
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        rows = self.s.ff10_activity(OWNER["profile_id"])
        self.assertTrue(rows)
        self.assertTrue(all(r["test"] for r in rows))
        self.assertEqual(self.s.ff10_preview(rewards.month_key())["lines"], [])     # never settled


if __name__ == "__main__":
    unittest.main()
