"""WORLD EXPLORER FOUNDING 50 (Option B: anyone can apply, only the Owner approves).

Runs the same scenarios on the in-memory store and on the real SQL (local PostgreSQL, supabase/founding50_migration.sql
loaded after the other migrations), then checks the player and Owner screens in the running app. No shortcuts here:
applications go through reward_founding_apply and decisions through the owner's reward_founding_decide.
Run:  python -m unittest discover -s tests -p test_founding50.py"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import legal_fixtures  # noqa: E402  (completed sample documents for published-legal tests)
from core import rewards as rewards_module  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))

from core import founding, rewards, withdrawals  # noqa: E402
from core.rewards import Settings  # noqa: E402
from core.rewards_store import MemoryStore, StoreError  # noqa: E402
import pg_harness  # noqa: E402
from pg_harness import literal  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

PUBLIC_TERMS = rewards_module.TERMS_VERSION              # the public programme rules (future public enrolment)
TERMS = "2026-11-05#test0000000000000"   # approved participation terms recorded in the test stores
OWNER = "owner@example.com"
TODAY = withdrawals.today()
CUR = withdrawals.month_of(TODAY)
M2 = rewards.previous_month(CUR)
M1 = rewards.previous_month(M2)
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


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class Scenarios:
    # ---- store specific
    def make_store(self):
        raise NotImplementedError

    def reopen(self, s):
        raise NotImplementedError

    def raw_application(self, s, profile, **changes):
        """Change an application directly, bypassing the functions (test set-up of times only)."""
        raise NotImplementedError

    def raw_enrolment(self, s, profile, month, **changes):
        raise NotImplementedError

    # ---- helpers
    def store(self, max_places=50, budget=50000, cap=1000):
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{M1}-01", max_places=max_places, monthly_budget=budget,
                                 monthly_cap=cap), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER], "live_requests": True,
                                                        "real_payouts": True})   # local test database only
        s.set_public(True, OWNER, confirmed=True)
        # these tests cover public applications ("anyone can apply"), which now also need invitation-only switched
        # off — a separate, confirmed owner decision (supabase/pilot_invitations_migration.sql); the invitation-only
        # pilot has its own tests (PilotInvitationTests)
        s.set_participation_terms("public", TERMS, OWNER)             # the approved public programme rules
        s.set_invitation_only(False, OWNER, confirmed=True)
        return s

    def person(self, s, n, test=False):
        s.ensure_account(pid(n), f"p{n}@example.com", f"Player {n}", True, test)
        return pid(n)

    def apply(self, s, n, state="Lagos", note=None, test=False):
        p = self.person(s, n, test)
        return s.apply_founding(p, state, note, True, True, True, terms_version=TERMS)

    def approve(self, s, n, note=None):
        app = s.founding_application(pid(n))
        return s.decide_founding(app["id"], "approve", OWNER, note)

    def decide(self, s, n, action, note=None, actor=OWNER):
        return s.decide_founding(s.founding_application(pid(n))["id"], action, actor, note)

    def quiz(self, s, p, key, day=None, test=False):
        return s.add_event(p, "quiz", key, day or TODAY.isoformat(), reward=True, test=test)

    # ------------------------------------------------------------------ applying

    def test_anyone_signed_in_can_apply_once(self):
        s = self.store()
        app = self.apply(s, 1, note="I love geography")
        self.assertEqual((app["status"], app["state"], app["test"], app["seen_at"]), ("pending", "Lagos", False, None))
        self.assertEqual(app["note"], "I love geography")
        with self.assertRaises(StoreError) as caught:                 # a second application is refused
            s.apply_founding(pid(1), "Kano", None, True, True, True, terms_version=TERMS)
        self.assertIn("already_applied", str(caught.exception))
        self.assertEqual(len(s.founding_applications()), 1)
        self.assertEqual(s.founding_application(pid(1))["state"], "Lagos")   # the first one is unchanged

    def test_duplicate_rows_are_refused_by_the_table_itself(self):
        s = self.store()
        self.apply(s, 1)
        with self.assertRaises(StoreError):
            s.insert(founding.TABLE, {"profile_id": pid(1), "state": "Lagos", "age_confirmed": True,
                                      "residence_confirmed": True, "terms_version": "x"})
        self.assertEqual(len(s.founding_applications()), 1)

    def test_application_needs_declarations_a_state_and_a_short_note(self):
        s = self.store()
        p = self.person(s, 1)
        for args, error in (((p, "Lagos", None, False, True, True), "declarations_required"),
                            ((p, "Lagos", None, True, False, True), "declarations_required"),
                            ((p, "Lagos", None, True, True, False), "declarations_required"),
                            ((p, None, None, True, True, True), "state_required"),
                            ((p, "London", None, True, True, True), "state_required"),
                            ((p, "Lagos", "x" * 301, True, True, True), "note_too_long")):
            with self.assertRaises(StoreError, msg=args) as caught:
                s.apply_founding(*args)
            self.assertIn(error, str(caught.exception))
        self.assertEqual(s.founding_applications(), [])
        with self.assertRaises(StoreError) as caught:                 # no account, no application
            s.apply_founding(pid(99), "Lagos", None, True, True, True, terms_version=TERMS)
        self.assertIn("no_account", str(caught.exception))

    def test_real_applications_wait_for_the_public_switch_test_accounts_never_count(self):
        s = self.store()
        s.set_public(False, OWNER)
        with self.assertRaises(StoreError) as caught:
            self.apply(s, 1)
        self.assertIn("programme_off", str(caught.exception))
        app = self.apply(s, 2, test=True)                             # owner/tester simulation
        self.assertTrue(app["test"])
        self.assertTrue(self.approve(s, 2)["test"])
        s.set_public(True, OWNER, confirmed=True)
        self.apply(s, 1)
        self.assertEqual(founding.dashboard([a for a in s.founding_applications() if not a["test"]], [], [], 50,
                                            CUR)["available"], 50)

    def test_suspended_accounts_cannot_apply(self):
        s = self.store()
        p = self.person(s, 1)
        s.update_account(p, {"membership": "suspended"})
        with self.assertRaises(StoreError) as caught:
            s.apply_founding(p, "Lagos", None, True, True, True, terms_version=TERMS)
        self.assertIn("suspended", str(caught.exception))

    # ------------------------------------------------------------------ the Owner decides

    def test_only_the_owner_can_decide_or_clear_notifications(self):
        s = self.store()
        self.apply(s, 1)
        app_id = s.founding_application(pid(1))["id"]
        for actor in (pid(1), "player@example.com", "", None):
            with self.assertRaises(StoreError, msg=actor) as caught:
                s.decide_founding(app_id, "approve", actor)
            self.assertIn("not_owner", str(caught.exception))
            with self.assertRaises(StoreError):
                s.mark_founding_seen(actor)
        self.assertEqual(s.founding_application(pid(1))["status"], "pending")

    def test_applications_cannot_be_changed_or_deleted_around_the_functions(self):
        s = self.store()
        self.apply(s, 1)
        for changes in ({"status": "approved"}, {"first_approved_at": ago(1)}, {"seen_at": ago(0)}):
            with self.assertRaises(StoreError, msg=changes):
                s.update(founding.TABLE, {"profile_id": pid(1)}, changes)
        with self.assertRaises(StoreError):
            s.delete(founding.TABLE, {"profile_id": pid(1)})
        s = self.reopen(s)
        self.assertEqual(s.founding_application(pid(1))["status"], "pending")

    def test_approve_waitlist_and_reject_with_the_reason_rules(self):
        s = self.store()
        for n in (1, 2, 3):
            self.apply(s, n)
        self.assertEqual(self.decide(s, 2, "waitlist")["status"], "waitlist")       # no reason needed
        with self.assertRaises(StoreError) as caught:                                 # reject needs a reason
            self.decide(s, 3, "reject")
        self.assertIn("reason_required", str(caught.exception))
        self.assertEqual(self.decide(s, 3, "reject", "Not resident in Nigeria")["status"], "rejected")
        approved = self.approve(s, 1)
        self.assertEqual(approved["status"], "approved")
        self.assertIsNotNone(approved["first_approved_at"])
        with self.assertRaises(StoreError) as caught:
            self.approve(s, 1)
        self.assertIn("no_change", str(caught.exception))
        with self.assertRaises(StoreError) as caught:                 # taking a place away needs a reason
            self.decide(s, 1, "waitlist")
        self.assertIn("reason_required", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            self.decide(s, 1, "promote")
        self.assertIn("invalid_action", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            s.decide_founding(9999, "approve", OWNER)
        self.assertIn("unknown_application", str(caught.exception))
        self.assertEqual(founding.counts(s.founding_applications()),
                         {"pending": 0, "approved": 1, "waitlist": 1, "rejected": 1, "total": 3})

    def test_at_most_max_places_approved_participants(self):
        s = self.store(max_places=2)
        for n in (1, 2, 3):
            self.apply(s, n)
        self.apply(s, 9, test=True)
        self.approve(s, 1)
        self.approve(s, 2)
        with self.assertRaises(StoreError) as caught:
            self.approve(s, 3)
        self.assertIn("places_full", str(caught.exception))
        self.assertEqual(self.approve(s, 9)["status"], "approved")   # test applications never take a real place
        self.decide(s, 3, "waitlist")
        self.decide(s, 2, "waitlist", "Inactive for a month")          # a place becomes free
        self.assertEqual(self.approve(s, 3)["status"], "approved")
        s = self.reopen(s)
        self.assertEqual(sorted(a["profile_id"] for a in s.founding_applications("approved") if not a["test"]),
                         sorted([pid(1), pid(3)]))

    def test_every_change_is_audited(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        self.decide(s, 1, "waitlist", "Paused for review")
        self.decide(s, 1, "reject", "Duplicate account")
        actions = [(a["action"], a["actor"]) for a in s.audit()]
        for expected in (("founding_applied", pid(1)), ("founding_approved", OWNER), ("founding_waitlist", OWNER),
                         ("founding_rejected", OWNER)):
            self.assertIn(expected, actions)
        rejected = next(a for a in s.audit() if a["action"] == "founding_rejected")
        self.assertEqual(rejected["new_value"]["note"], "Duplicate account")
        self.assertEqual(rejected["old_value"]["status"], "waitlist")

    def test_new_applications_notify_the_owner_until_seen(self):
        s = self.store()
        self.apply(s, 1)
        self.apply(s, 2)
        self.assertEqual(sum(1 for a in s.founding_applications() if not a.get("seen_at")), 2)
        self.assertEqual(s.mark_founding_seen(OWNER, s.founding_application(pid(1))["id"]), 1)
        s = self.reopen(s)
        self.assertEqual([a["profile_id"] for a in s.founding_applications() if not a.get("seen_at")], [pid(2)])
        self.decide(s, 2, "waitlist")                                 # deciding also clears it
        self.assertEqual([a for a in s.founding_applications() if not a.get("seen_at")], [])

    # ------------------------------------------------------------------ only approved participants earn

    def test_not_approved_real_accounts_cannot_enrol_or_join(self):
        s = self.store()
        for n, step in ((1, None), (2, "pending"), (3, "waitlist"), (4, "rejected")):
            p = self.person(s, n)
            if step:
                s.apply_founding(p, "Lagos", None, True, True, True, terms_version=TERMS)
                if step != "pending":
                    self.decide(s, n, {"waitlist": "waitlist", "rejected": "reject"}[step], "No")
            for attempt in (lambda: s.join(p, CUR), lambda: s.enrol(p, CUR)):
                with self.assertRaises(StoreError, msg=(n, step)) as caught:
                    attempt()
                self.assertIn("not_approved", str(caught.exception))
            self.assertIsNone(s.enrolment(p, CUR))
        self.apply(s, 5)
        self.approve(s, 5)
        self.assertEqual(s.join(pid(5), CUR)["status"], "enrolled")

    def test_not_approved_activity_is_recorded_with_no_money(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), CUR)
        self.assertGreater(self.quiz(s, pid(1), "q1")["amount"], 0)
        # an approval that is no longer valid (e.g. changed while an award was on its way): the event trigger itself
        # refuses money, even though the person still has an enrolment
        self.raw_application(s, pid(1), status="pending")
        row = self.quiz(s, pid(1), "q2")
        self.assertEqual((row["amount"], row["reason"]), (0, "not_approved"))
        self.assertEqual(len(s.events(pid(1))), 2)                    # the activity itself is kept
        p = self.person(s, 2)                                         # never approved: no enrolment, no money
        row = self.quiz(s, p, "q1")
        self.assertEqual(row["amount"], 0)
        t = self.person(s, 3, test=True)                              # owner/tester simulations still earn (test)
        s.join(t, CUR)
        self.assertGreater(self.quiz(s, t, "q1", test=True)["amount"], 0)
        self.raw_application(s, pid(1), status="approved")
        self.assertGreater(self.quiz(s, pid(1), "q3")["amount"], 0)
        self.assertEqual(s.events(pid(1))[1]["amount"], 0)            # nothing is paid retroactively

    def test_waiting_list_promotion_moves_approved_people_only(self):
        s = self.store(budget=1000, cap=1000)                         # room for one participant this month
        for n in (1, 2):
            self.apply(s, n)
            self.approve(s, n)
        self.assertEqual(s.join(pid(1), CUR)["status"], "enrolled")
        self.assertEqual(s.join(pid(2), CUR)["status"], "waitlist")
        self.raw_application(s, pid(2), status="waitlist")             # e.g. changed while a promotion was pending
        s.leave(pid(1), CUR)
        self.assertEqual(s.promote(CUR, OWNER), 0)
        self.assertEqual(s.enrolment(pid(2), CUR)["status"], "waitlist")
        self.raw_application(s, pid(2), status="approved")
        self.assertEqual(s.promote(CUR, OWNER), 1)
        self.assertEqual(s.enrolment(pid(2), CUR)["status"], "enrolled")

    def test_budget_places_and_monthly_maximum_are_unchanged(self):
        s = self.store()
        st = s.settings()
        self.assertEqual((st.monthly_budget, st.max_places, st.monthly_cap), (50000, 50, 1000))
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), CUR)
        for i in range(400):
            self.quiz(s, pid(1), f"q{i}", day=f"{CUR}-{1 + i % max(TODAY.day, 1):02d}")
        self.assertLessEqual(sum(e["amount"] for e in s.events(pid(1))), 1000)
        self.assertEqual(s.enrolment(pid(1), CUR)["reserved_amount"], 1000)

    # ------------------------------------------------------------------ taking a place away

    def test_removing_an_approved_participant_frees_the_place_and_keeps_earnings(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), CUR)
        self.quiz(s, pid(1), "q1")
        earned = sum(e["amount"] for e in s.events(pid(1)))
        self.assertGreater(earned, 0)
        account_before = s.account(pid(1))
        self.decide(s, 1, "waitlist", "Inactive")
        enrolment = s.enrolment(pid(1), CUR)
        self.assertEqual(enrolment["status"], "withdrawn")            # place and unused budget freed
        self.assertEqual(enrolment["reserved_amount"], earned)
        self.assertEqual(sum(e["amount"] for e in s.events(pid(1))), earned)   # earnings untouched
        after = s.account(pid(1))
        for key in ("membership", "verification", "referral_code", "age_confirmed", "residence_confirmed"):
            self.assertEqual(after.get(key), account_before.get(key), key)
        self.assertEqual((self.quiz(s, pid(1), "q2") or {}).get("amount"), 0)   # no new money while off the list

    def test_past_months_are_untouched_when_a_place_is_taken_away(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), M2)
        s.enrol(pid(1), CUR)
        self.decide(s, 1, "waitlist", "Inactive")
        self.assertEqual(s.enrolment(pid(1), M2)["status"], "enrolled")
        self.assertEqual(s.enrolment(pid(1), CUR)["status"], "withdrawn")

    def test_rejected_after_approval_cannot_be_paid_waiting_list_still_can(self):
        s = self.store()
        for n in (1, 2):
            self.apply(s, n)
            self.approve(s, n)
            s.join(pid(n), M1)
            s.update_account(pid(n), {"verification": "verified"})
            for i in range(6):
                self.quiz(s, pid(n), f"q{i}", day=f"{M1}-{1 + i // 3:02d}")
            s.open_payment(pid(n), M1, False, OWNER)
        self.decide(s, 1, "reject", "Duplicate account found")
        self.decide(s, 2, "waitlist", "Paused")
        with self.assertRaises(StoreError) as caught:
            s.update_payment(pid(1), M1, {"status": "approved", "approved_amount": 60}, OWNER)
        self.assertIn("founding_not_approved", str(caught.exception))
        self.assertEqual(s.payment(pid(1), M1)["status"], "pending_review")
        self.assertEqual(s.update_payment(pid(2), M1, {"status": "approved", "approved_amount": 60}, OWNER)["status"],
                         "approved")
        self.assertIn("not_approved", s.cashout_status(pid(1))["reasons"])
        self.assertNotIn("not_approved", s.cashout_status(pid(2))["reasons"])

    def eligible_participant(self, s, n):
        """Approved, verified, took a place 40 days ago and earned in a completed month."""
        self.apply(s, n)
        self.approve(s, n)
        s.join(pid(n), M1)
        s.update_account(pid(n), {"verification": "verified"})
        for i in range(6):
            self.quiz(s, pid(n), f"q{i}", day=f"{M1}-{1 + i // 3:02d}")
        self.raw_application(s, pid(n), first_approved_at=ago(41), approved_at=ago(41))
        self.raw_enrolment(s, pid(n), M1, enrolled_at=ago(40), created_at=ago(40))
        status = s.cashout_status(pid(n))
        self.assertTrue(status["eligible"], status["reasons"])
        return s.request_cashout(pid(n), f"Player {n} Okafor", {k: True for k in withdrawals.DECLARATIONS},
                                 status["amount"])

    def test_withdrawals_of_rejected_participants_cannot_be_approved_or_paid(self):
        s = self.store()
        first = self.eligible_participant(s, 1)
        second = self.eligible_participant(s, 2)
        self.decide(s, 1, "reject", "Duplicate account found")
        with self.assertRaises(StoreError) as caught:
            s.decide_cashout(first["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertIn("founding_not_approved", str(caught.exception))
        self.assertEqual(s.cashout_request(first["id"])["status"], "pending_review")
        approved = s.decide_cashout(second["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertEqual(approved["status"], "approved")
        self.decide(s, 2, "reject", "Fraud found after approval")      # approved, then rejected: no payment
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(second["id"], approved["amount"], TODAY.isoformat(), "TRX-1", OWNER)
        self.assertIn("founding_not_approved", str(caught.exception))
        self.assertEqual(s.cashout_payments(), [])

    def test_waiting_list_participants_keep_earned_withdrawals(self):
        s = self.store()
        req = self.eligible_participant(s, 1)
        self.decide(s, 1, "waitlist", "Paused")
        approved = s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        paid = s.pay_cashout(req["id"], approved["amount"], TODAY.isoformat(), "TRX-9", OWNER)
        self.assertEqual(paid["amount"], approved["amount"])

    # ------------------------------------------------------------------ the 30-day withdrawal clock

    def test_withdrawal_needs_approval(self):
        s = self.store()
        p = self.person(s, 1)
        status = s.cashout_status(p)
        self.assertFalse(status["eligible"])
        self.assertIn("not_approved", status["reasons"])
        self.assertIn("not_enrolled", status["reasons"])

    def test_waiting_period_starts_at_the_first_enrolment_after_approval(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), M1)
        s.enrol(pid(1), CUR)
        # the account and the application are old; one enrolment is from before the (first) approval
        self.raw_application(s, pid(1), applied_at=ago(90), first_approved_at=ago(40), approved_at=ago(40))
        self.raw_enrolment(s, pid(1), M1, enrolled_at=ago(60), created_at=ago(60))
        self.raw_enrolment(s, pid(1), CUR, enrolled_at=ago(20), created_at=ago(20))
        status = s.cashout_status(pid(1))
        self.assertEqual(str(status["joined_on"]), withdrawals.lagos_date(ago(20)).isoformat())
        self.assertIn("waiting_period", status["reasons"])
        self.assertEqual(int(status["days_left"]), 10)
        self.raw_enrolment(s, pid(1), CUR, enrolled_at=ago(31), created_at=ago(31))
        status = s.cashout_status(pid(1))
        self.assertNotIn("waiting_period", status["reasons"])
        self.assertNotIn("not_approved", status["reasons"])

    def test_applying_or_approval_alone_never_starts_the_clock(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        self.raw_application(s, pid(1), applied_at=ago(90), first_approved_at=ago(60), approved_at=ago(60))
        status = s.cashout_status(pid(1))
        self.assertIsNone(status.get("joined_on"))
        self.assertIn("not_enrolled", status["reasons"])

    def test_eligible_only_with_30_days_and_verified_earnings_from_a_completed_month(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), CUR)
        self.quiz(s, pid(1), "now")                                   # current month only: not yet available
        self.raw_application(s, pid(1), first_approved_at=ago(50), approved_at=ago(50))
        self.raw_enrolment(s, pid(1), CUR, enrolled_at=ago(45), created_at=ago(45))
        status = s.cashout_status(pid(1))
        self.assertIn("no_earnings", status["reasons"])
        self.assertFalse(status["eligible"])

    def test_live_switches_are_never_touched(self):
        s = self.store()
        before = s.cashout_settings()
        self.apply(s, 1)
        self.approve(s, 1)
        self.decide(s, 1, "reject", "Test")
        after = s.cashout_settings()
        self.assertEqual((before["live_requests"], before["real_payouts"]),
                         (after["live_requests"], after["real_payouts"]))
        self.assertTrue(s.public_status()["enabled"])                 # decisions never change the public switch

    # ------------------------------------------------------------------ Friends & Family 10: invitation only
    # (supabase/pilot_invitations_migration.sql; the same rules in MemoryStore and in the real SQL)

    def pilot_store(self, terms=True):
        """Fresh store with defaults: public OFF, pilot OFF, invitation-only ON (approved terms recorded)."""
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{M1}-01"), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER]})
        if terms:
            s.set_participation_terms("pilot", TERMS, OWNER)
        return s

    def refused(self, s, n, reason, test=False):
        with self.assertRaises(StoreError) as caught:
            self.apply(s, n, test=test)
        self.assertIn(reason, str(caught.exception))

    def test_defaults_keep_the_pilot_closed_and_invitation_only(self):
        s = self.pilot_store()
        self.assertEqual({k: s.pilot_status()[k] for k in ("installed", "enabled", "invitation_only")},
                         {"installed": True, "enabled": False, "invitation_only": True})
        s.invite("p1@example.com", OWNER)
        self.refused(s, 1, "programme_off")                           # invited, but nothing is open yet

    def test_public_switch_alone_never_admits_uninvited_people(self):
        s = self.pilot_store()
        s.set_public(True, OWNER, confirmed=True)
        self.refused(s, 1, "not_invited")                             # an ordinary member of the public
        s.invite("P2@Example.com ", OWNER, "a friend")                # stored lower-case and trimmed
        self.refused_with(s, 2, PUBLIC_TERMS, "terms_required")       # no public terms approved yet (NULL-safe)
        s.set_participation_terms("public", PUBLIC_TERMS, OWNER)
        self.assertEqual(self.apply_with(s, 2, PUBLIC_TERMS)["status"], "pending")   # invited, public rules accepted

    def test_pilot_admits_invited_people_only_whatever_invitation_only_says(self):
        s = self.pilot_store()
        s.set_pilot(True, OWNER, confirmed=True)
        s.invite("p1@example.com", OWNER)
        self.assertEqual(self.apply(s, 1)["status"], "pending")
        self.refused(s, 2, "not_invited")
        s.set_participation_terms("public", PUBLIC_TERMS, OWNER)
        s.set_invitation_only(False, OWNER, confirmed=True)           # meant for public enrolment only
        self.refused(s, 3, "not_invited")                             # the pilot still needs an invitation
        self.assertTrue(self.apply(s, 4, test=True)["test"])          # owner/tester simulation still works

    def test_separately_authorised_public_enrolment(self):
        s = self.pilot_store()
        s.set_public(True, OWNER, confirmed=True)
        s.set_participation_terms("public", PUBLIC_TERMS, OWNER)
        s.set_invitation_only(False, OWNER, confirmed=True)
        app = s.apply_founding(self.person(s, 1), "Lagos", None, True, True, True, terms_version=PUBLIC_TERMS)
        self.assertEqual(app["status"], "pending")                    # public applications, still owner-approved

    def test_pilot_switches_are_owner_only_confirmed_and_guarded(self):
        s = self.pilot_store()
        for call, reason in ((lambda: s.set_pilot(True, "p1@example.com", confirmed=True), "not_owner"),
                             (lambda: s.set_pilot(True, OWNER), "confirmation_required"),
                             (lambda: s.set_invitation_only(False, OWNER), "confirmation_required"),
                             (lambda: s.invite("p1@example.com", "p1@example.com"), "not_owner"),
                             (lambda: s.invite("not an email", OWNER), "invalid_email"),
                             (lambda: s.revoke_invitation("nobody@example.com", OWNER), "not_invited")):
            with self.assertRaises(StoreError) as caught:
                call()
            self.assertIn(reason, str(caught.exception))
        for column, value in (("pilot_enabled", True), ("invitation_only", False)):
            with self.assertRaises(StoreError):                       # not through the ordinary settings update
                s.update("reward_program_settings", {"id": 1}, {column: value})
        self.assertEqual((s.pilot_status()["enabled"], s.pilot_status()["invitation_only"]), (False, True))

    def test_revoked_invitations_stop_new_applications_only(self):
        s = self.pilot_store()
        s.set_pilot(True, OWNER, confirmed=True)
        for n in (1, 2):
            s.invite(f"p{n}@example.com", OWNER)
        self.apply(s, 1)
        s.revoke_invitation("p1@example.com", OWNER)
        s.revoke_invitation("p2@example.com", OWNER)
        self.refused(s, 2, "not_invited")
        self.assertEqual(s.founding_application(pid(1))["status"], "pending")   # existing application unchanged
        self.assertFalse(s.pilot_invited("p1@example.com"))
        s.invite("p2@example.com", OWNER)                             # invited again
        self.assertTrue(s.pilot_invited("p2@example.com"))
        actions = [a["action"] for a in s.select("reward_audit_log", None, order="id")]
        for action in ("pilot_on", "pilot_invited", "pilot_revoked"):
            self.assertIn(action, actions)

    def test_approved_pilot_participants_earn_nothing_and_cannot_enrol(self):
        s = self.pilot_store()
        s.set_pilot(True, OWNER, confirmed=True)
        s.invite("p1@example.com", OWNER)
        self.apply(s, 1)
        self.approve(s, 1)                                            # the owner approves as before
        with self.assertRaises(StoreError):                           # the public programme is OFF: no enrolment
            s.join(pid(1), CUR)
        row = self.quiz(s, pid(1), "q1")
        self.assertEqual(row["amount"], 0)                            # activity is recorded, ₦0
        self.assertEqual(sum(e["amount"] for e in s.events(pid(1))), 0)

    def test_applicants_must_accept_the_approved_terms_version(self):
        s = self.pilot_store(terms=False)
        with self.assertRaises(StoreError) as caught:                 # no approved terms: the pilot cannot start
            s.set_pilot(True, OWNER, confirmed=True)
        self.assertIn("terms_required", str(caught.exception))
        s.set_participation_terms("pilot", "2026-11-05#aaaaaaaaaaaaaaaa", OWNER)
        s.set_pilot(True, OWNER, confirmed=True)
        s.invite("p1@example.com", OWNER)
        s.invite("p2@example.com", OWNER)
        p = self.person(s, 1)
        for version in (None, "2026-10-24#bbbbbbbbbbbbbbbb", rewards_module.TERMS_VERSION):   # old, other or missing
            with self.assertRaises(StoreError) as caught:
                s.apply_founding(p, "Lagos", None, True, True, True, terms_version=version)
            self.assertIn("terms_outdated", str(caught.exception), version)
        app = s.apply_founding(p, "Lagos", None, True, True, True, terms_version="2026-11-05#aaaaaaaaaaaaaaaa")
        self.assertEqual(app["terms_version"], "2026-11-05#aaaaaaaaaaaaaaaa")   # the accepted version is kept
        s.set_participation_terms("pilot", "2026-12-01#cccccccccccccccc", OWNER)   # terms changed and re-approved
        self.assertEqual(s.founding_application(p)["terms_version"], "2026-11-05#aaaaaaaaaaaaaaaa")   # history kept
        with self.assertRaises(StoreError) as caught:
            s.apply_founding(self.person(s, 2), "Lagos", None, True, True, True,
                             terms_version="2026-11-05#aaaaaaaaaaaaaaaa")
        self.assertIn("terms_outdated", str(caught.exception))
        log = [a for a in s.select("reward_audit_log", None, order="id")]
        self.assertEqual([a["action"] for a in log].count("pilot_terms_set"), 2)
        applied = next(a for a in log if a["action"] == "founding_applied")
        self.assertEqual((applied.get("new_value") or {}).get("terms_version"), "2026-11-05#aaaaaaaaaaaaaaaa")

    def test_only_the_owner_records_the_terms_and_not_through_settings(self):
        s = self.pilot_store(terms=False)
        for call, reason in ((lambda: s.set_participation_terms("pilot", "v#1", "p1@example.com"), "not_owner"),
                             (lambda: s.set_participation_terms("pilot", "  ", OWNER), "invalid_value"),
                             (lambda: s.set_participation_terms("other", "v#1", OWNER), "invalid_mode")):
            with self.assertRaises(StoreError) as caught:
                call()
            self.assertIn(reason, str(caught.exception))
        with self.assertRaises(StoreError):
            s.update("reward_program_settings", {"id": 1}, {"pilot_terms_version": "v#1"})
        with self.assertRaises(StoreError):
            s.update("reward_program_settings", {"id": 1}, {"public_terms_version": "v#1"})
        self.assertIsNone(s.pilot_status()["terms_version"])

    # ---- regression: the two ways in validate their own approved terms independently

    def modes_store(self):
        """Pilot ON with its approved pilot terms; public terms approved; public switch OFF; invitation-only ON."""
        s = self.pilot_store(terms=False)
        s.set_participation_terms("pilot", TERMS, OWNER)
        s.set_participation_terms("public", PUBLIC_TERMS, OWNER)
        s.set_pilot(True, OWNER, confirmed=True)
        s.invite("p1@example.com", OWNER)
        return s

    def apply_with(self, s, n, terms):
        return s.apply_founding(self.person(s, n), "Lagos", None, True, True, True, terms_version=terms)

    def refused_with(self, s, n, terms, reason):
        with self.assertRaises(StoreError, msg=(n, terms)) as caught:
            self.apply_with(s, n, terms)
        self.assertIn(reason, str(caught.exception))

    def test_regression_1_invited_pilot_participant_applies_with_the_pilot_terms(self):
        s = self.modes_store()
        app = self.apply_with(s, 1, TERMS)
        self.assertEqual((app["status"], app["terms_version"]), ("pending", TERMS))

    def test_regression_2_uninvited_people_cannot_join_the_restricted_pilot(self):
        s = self.modes_store()
        for terms in (TERMS, PUBLIC_TERMS):
            self.refused_with(s, 2, terms, "not_invited")
        s.set_participation_terms("public", PUBLIC_TERMS, OWNER)
        s.set_invitation_only(False, OWNER, confirmed=True)         # even with public applications allowed ...
        self.refused_with(s, 2, TERMS, "not_invited")               # ... the pilot needs an invitation (public is OFF)
        self.assertIsNone(s.founding_application(pid(2)))

    def test_regression_3_public_applicants_use_the_public_terms_only_after_separate_authorisation(self):
        s = self.modes_store()
        s.set_public(True, OWNER, confirmed=True)
        self.refused_with(s, 3, PUBLIC_TERMS, "not_invited")        # public ON alone: not authorised yet
        s.set_invitation_only(False, OWNER, confirmed=True)         # public enrolment separately authorised
        self.refused_with(s, 3, TERMS, "terms_outdated")            # the pilot terms are not the public rules
        app = self.apply_with(s, 3, PUBLIC_TERMS)
        self.assertEqual((app["status"], app["terms_version"]), ("pending", PUBLIC_TERMS))

    def test_regression_3b_public_authorisation_needs_approved_public_terms(self):
        s = self.pilot_store(terms=False)
        with self.assertRaises(StoreError) as caught:
            s.set_invitation_only(False, OWNER, confirmed=True)
        self.assertIn("terms_required", str(caught.exception))

    def test_regression_4_outdated_or_incorrect_terms_are_rejected(self):
        s = self.modes_store()
        s.invite("p2@example.com", OWNER)
        self.refused_with(s, 1, PUBLIC_TERMS, "terms_outdated")     # public rules through the pilot
        self.refused_with(s, 1, "2026-10-24#0000000000000000", "terms_outdated")   # an older pilot version
        self.refused_with(s, 1, "made-up", "terms_outdated")
        self.refused_with(s, 1, None, "terms_outdated")             # the app's old default
        s.set_participation_terms("pilot", "2026-12-01#1111111111111111", OWNER)   # pilot terms updated
        self.refused_with(s, 2, TERMS, "terms_outdated")            # the previously approved version is now outdated
        self.assertEqual(self.apply_with(s, 2, "2026-12-01#1111111111111111")["status"], "pending")
        self.assertIsNone(s.founding_application(pid(1)))           # nothing recorded for the refused attempts

    def test_regression_4b_missing_approved_terms_never_admit_anyone(self):
        """No approved terms recorded for the way in: refused in SQL as in Python (a NULL comparison is not a pass)."""
        s = self.pilot_store(terms=False)
        s.set_public(True, OWNER, confirmed=True)
        s.invite("p1@example.com", OWNER)
        for terms in (PUBLIC_TERMS, TERMS, "anything"):
            self.refused_with(s, 1, terms, "terms_required")
        self.assertIsNone(s.founding_application(pid(1)))

    def test_regression_6_payouts_stay_disabled_for_pilot_participants(self):
        s = self.modes_store()
        self.apply_with(s, 1, TERMS)
        self.approve(s, 1)
        self.assertFalse(s.cashout_settings()["real_payouts"])      # the database payment switch is untouched
        self.assertFalse(s.cashout_settings()["live_requests"])
        self.assertEqual(self.quiz(s, pid(1), "q1")["amount"], 0)   # ₦0 while the public programme is OFF

    def test_founding_places_setting_is_capped_at_fifty(self):
        """The public Founding 50 setting; the private pilot's own limit of 10 is tested in test_ff10."""
        s = self.pilot_store()
        s.set_pilot(True, OWNER, confirmed=True)
        self.assertEqual(s.settings().max_places, 50)
        problems = s.save_settings(Settings(start_date=f"{M1}-01", max_places=51), OWNER)
        self.assertTrue(any("limited to 50" in p for p in problems))


class MemoryFoundingTests(Scenarios, unittest.TestCase):
    def make_store(self):
        return MemoryStore()

    def reopen(self, s):
        return s

    def raw_application(self, s, profile, **changes):
        s._founding_row(profile).update(changes)

    def raw_enrolment(self, s, profile, month, **changes):
        next(e for e in s.tables["reward_enrolments"]
             if e["profile_id"] == profile and e["month"] == month).update(changes)


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
@unittest.skipUnless(pg_harness.PILOT.exists(), "supabase/pilot_invitations_migration.sql is not in this checkout, so the "
                     "database rules cannot be loaded into the local test PostgreSQL")
class SqlFoundingTests(Scenarios, unittest.TestCase):
    def make_store(self):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        return pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db())

    def reopen(self, s):
        return pg_harness.PsqlStore(CLUSTER, s.db)                   # a new connection, nothing in memory

    def _set(self, changes):
        return ", ".join(f"{k} = {literal(v)}" + ("::timestamptz" if k.endswith("_at") else "")
                         for k, v in changes.items())

    def raw_application(self, s, profile, **changes):
        CLUSTER.psql(s.db, "alter table public.reward_founding_applications disable trigger reward_founding_guard; "
                           f"update public.reward_founding_applications set {self._set(changes)} "
                           f"where profile_id = {literal(profile)}; "
                           "alter table public.reward_founding_applications enable trigger reward_founding_guard;")

    def raw_enrolment(self, s, profile, month, **changes):
        CLUSTER.psql(s.db, f"update public.reward_enrolments set {self._set(changes)} "
                           f"where profile_id = {literal(profile)} and month = {literal(month)}")

    def test_browser_roles_have_no_access(self):
        s = self.store()
        self.apply(s, 1)
        app_id = s.founding_application(pid(1))["id"]
        for role in ("anon", "authenticated"):
            for sql in ("select * from public.reward_founding_applications",
                        f"select public.reward_founding_apply({literal(pid(2))}, 'Lagos', null, true, true, true, 'x')",
                        f"select public.reward_founding_decide({app_id}, 'approve', {literal(OWNER)}, null)",
                        f"select public.reward_founding_mark_seen({literal(OWNER)}, null)",
                        f"select public.reward_founding_approved({literal(pid(1))})"):
                with self.assertRaises(StoreError, msg=f"{role}: {sql}"):
                    CLUSTER.psql(s.db, sql, role)
        self.assertEqual(s.founding_application(pid(1))["status"], "pending")

    def test_the_server_key_cannot_write_applications_directly(self):
        s = self.store()
        self.apply(s, 1)
        self.person(s, 2)
        for sql in ("update public.reward_founding_applications set status = 'approved', first_approved_at = now()",
                    "insert into public.reward_founding_applications (profile_id, status, state, age_confirmed, "
                    "residence_confirmed, terms_version, first_approved_at) select profile_id, 'approved', 'Lagos', "
                    f"true, true, 'x', now() from public.reward_accounts where profile_id = {literal(pid(2))}",
                    "delete from public.reward_founding_applications"):
            with self.assertRaises(StoreError, msg=sql):
                CLUSTER.psql(s.db, sql, "service_role")
        self.assertEqual(s.founding_application(pid(1))["status"], "pending")

    def test_migration_is_rerunnable_and_keeps_everything(self):
        s = self.store()
        self.apply(s, 1)
        self.approve(s, 1)
        s.join(pid(1), CUR)
        self.quiz(s, pid(1), "q1")
        self.apply(s, 2)
        before = (s.founding_applications(), s.enrolments(), s.events(), s.accounts())
        CLUSTER.psql_file(s.db, pg_harness.FOUNDING)
        CLUSTER.psql_file(s.db, pg_harness.FOUNDING)
        CLUSTER.psql_file(s.db, pg_harness.PILOT)        # re-run after founding50 (documented in the pilot migration)
        after = (s.founding_applications(), s.enrolments(), s.events(), s.accounts())
        self.assertEqual(json.dumps(before, sort_keys=True, default=str), json.dumps(after, sort_keys=True, default=str))
        self.assertEqual(s.founding_application(pid(2))["status"], "pending")     # nobody approved automatically

    def test_migration_on_existing_data_approves_nobody_and_changes_no_record(self):
        db = CLUSTER.fresh_db()
        # a database exactly as before this migration: the earlier three files only
        CLUSTER.psql(db, "drop table public.reward_founding_applications cascade")
        CLUSTER.psql(db, "drop trigger reward_enrolments_founding on public.reward_enrolments; "
                         "drop trigger reward_events_founding on public.reward_activity_events; "
                         "drop trigger reward_payments_founding on public.reward_payments; "
                         "drop trigger reward_cashout_founding on public.reward_cashout_requests")
        CLUSTER.psql_file(db, pg_harness.SCHEMA)
        CLUSTER.psql_file(db, pg_harness.MIGRATION)
        CLUSTER.psql_file(db, pg_harness.PUBLIC)
        s = pg_harness.PsqlStore(CLUSTER, db)
        s.save_settings(Settings(start_date=f"{M1}-01"), OWNER)
        CLUSTER.set_public(db, True)
        s.ensure_account(pid(1), "p1@example.com", "Existing", True, False)
        s.join(pid(1), CUR)
        self.quiz(s, pid(1), "q1")
        before = (s.accounts(), s.enrolments(), s.events(), s.payments())
        CLUSTER.psql_file(db, pg_harness.FOUNDING)
        self.assertEqual(json.dumps(before, sort_keys=True, default=str),
                         json.dumps((s.accounts(), s.enrolments(), s.events(), s.payments()), sort_keys=True,
                                    default=str))
        self.assertEqual(s.founding_applications(), [])
        self.assertEqual(self.quiz(s, pid(1), "q2")["amount"], 0)     # from now on: approval needed to earn
        self.assertIn("not_approved", s.cashout_status(pid(1))["reasons"])


# ============================================================================ in the running app

OWNER_ID = {"iss": "https://accounts.google.com", "sub": "o1", "email": OWNER, "email_verified": True,
            "name": "Owner", "profile_id": "a" * 64}
PLAYER = {"iss": "https://accounts.google.com", "sub": "p2", "email": "ada@example.com", "email_verified": True,
          "name": "Ada Player", "profile_id": "b" * 64}


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class FoundingAppTests(unittest.TestCase):
    def setUp(self):
        from ui import rewards_hooks
        self.hooks = rewards_hooks
        rewards_hooks._memory_store.clear()
        rewards_hooks._health_cache.clear()
        self.s = rewards_hooks._memory_store()
        self.s.tables["reward_program_settings"][0]["public_enabled"] = True    # both switches ON for these tests
        self.s.tables["reward_program_settings"][0]["invitation_only"] = False  # public applications authorised
        # the public form accepts the rewards programme rules; the owner recorded them as the approved terms
        self.s.tables["reward_program_settings"][0]["public_terms_version"] = rewards_module.TERMS_VERSION
        self.s.tables["reward_cashout_settings"][0]["owner_emails"] = [OWNER]

    def app(self, who, page="Rewards", language=None):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.secrets["rewards"] = {"enabled": True}
        at.secrets["legal"] = legal_fixtures.secrets()
        at.secrets["analytics"] = {"owner_emails": [OWNER]}
        at.session_state["page"] = page
        if page == "Owner":   # the owner opens the rewards tab (the dashboard draws only the open tab)
            at.session_state["owner_tab"] = "💰 Rewards & Referral Management"
        if language:
            at.session_state["app_language"] = language
        for patch in (mock.patch("core.accounts.identity", return_value=dict(who)),
                      # the in-memory store stands in for the Supabase tables (as for real, non-tester players)
                      mock.patch.object(self.hooks, "_supabase", return_value=self.s),
                      mock.patch.object(self.hooks, "store_health", return_value="ok")):
            patch.start()
            self.addCleanup(patch.stop)
        return at

    def button(self, at, label=None, key=None):
        return next((b for b in at.button if (key and b.key == key) or (label and b.label == label)), None)

    def owner_tab(self, at):
        return next(t for t in at.tabs if t.label.startswith("🌟 Founding 50"))

    def test_player_sees_the_application_not_the_join_form(self):
        at = self.app(PLAYER).run()
        self.assertEqual([x.value for x in at.exception], [])
        self.assertIn("World Explorer Founding 50", " ".join(m.value for m in at.markdown))
        self.assertIsNotNone(self.button(at, "Apply for the Founding 50"))
        self.assertIsNone(self.button(at, "Join"))                    # joining only after the Owner's approval
        self.assertIsNone(self.s.founding_application(PLAYER["profile_id"]))

    def test_apply_flow_creates_one_pending_application_and_notifies_the_owner(self):
        at = self.app(PLAYER).run()
        at.selectbox(key="rw_f_state").select("Kano")
        at.text_area(key="rw_f_note").input("I teach geography")
        for key in ("rw_f_adult", "rw_f_resident", "rw_f_terms"):
            at.checkbox(key=key).check()
        self.button(at, "Apply for the Founding 50").click().run()
        self.assertEqual([x.value for x in at.exception], [])
        app = self.s.founding_application(PLAYER["profile_id"])
        self.assertEqual((app["status"], app["state"], app["note"], app["test"]), ("pending", "Kano",
                                                                                 "I teach geography", False))
        self.assertTrue(any("waiting for review" in x.value for x in at.info))
        self.assertIsNone(self.button(at, "Apply for the Founding 50"))   # no second application
        owner = self.app(OWNER_ID, page="Owner").run()
        self.assertTrue(any("1 new Founding 50 application" in x.value for x in owner.info))
        self.assertIn("(1)", self.owner_tab(owner).label)

    def test_missing_declarations_or_state_send_nothing(self):
        at = self.app(PLAYER).run()
        at.checkbox(key="rw_f_adult").check()
        self.button(at, "Apply for the Founding 50").click().run()
        self.assertTrue(any("all three statements" in x.value for x in at.error))
        for key in ("rw_f_resident", "rw_f_terms"):
            at.checkbox(key=key).check()
        self.button(at, "Apply for the Founding 50").click().run()
        self.assertTrue(any("state of residence" in x.value for x in at.error))
        self.assertIsNone(self.s.founding_application(PLAYER["profile_id"]))

    def test_owner_approves_then_the_player_takes_their_place(self):
        self.s.ensure_account(PLAYER["profile_id"], PLAYER["email"], PLAYER["name"], True, False)
        self.s.apply_founding(PLAYER["profile_id"], "Lagos", None, True, True, True, terms_version=rewards_module.TERMS_VERSION)
        owner = self.app(OWNER_ID, page="Owner").run()
        self.assertIn("(1)", self.owner_tab(owner).label)
        app_id = self.s.founding_application(PLAYER["profile_id"])["id"]
        owner.button(key=f"rw_f_approve_{app_id}").click().run()
        self.assertEqual([x.value for x in owner.exception], [])
        self.assertEqual(self.s.founding_application(PLAYER["profile_id"])["status"], "approved")
        self.assertIn(("founding_approved", OWNER), [(a["action"], a["actor"]) for a in self.s.audit()])
        at = self.app(PLAYER).run()
        self.assertTrue(any("approved" in x.value for x in at.success))
        for key in ("rw_adult", "rw_resident", "rw_terms"):
            at.checkbox(key=key).check()
        self.button(at, "Join").click().run()
        self.assertEqual(self.s.enrolment(PLAYER["profile_id"], rewards.month_key())["status"], "enrolled")
        self.assertIsNotNone(self.s.enrolment(PLAYER["profile_id"], rewards.month_key())["enrolled_at"])

    def test_owner_reject_needs_a_reason(self):
        self.s.ensure_account(PLAYER["profile_id"], PLAYER["email"], PLAYER["name"], True, False)
        self.s.apply_founding(PLAYER["profile_id"], "Lagos", None, True, True, True, terms_version=rewards_module.TERMS_VERSION)
        app_id = self.s.founding_application(PLAYER["profile_id"])["id"]
        owner = self.app(OWNER_ID, page="Owner").run()
        owner.button(key=f"rw_f_reject_{app_id}").click().run()
        self.assertTrue(any("give a reason" in x.value for x in owner.error))
        self.assertEqual(self.s.founding_application(PLAYER["profile_id"])["status"], "pending")
        owner.text_input(key=f"rw_f_note_{app_id}").input("Lives outside Nigeria")
        owner.button(key=f"rw_f_reject_{app_id}").click().run()
        self.assertEqual(self.s.founding_application(PLAYER["profile_id"])["status"], "rejected")
        at = self.app(PLAYER).run()
        self.assertTrue(any("not accepted" in x.value for x in at.warning))
        self.assertNotIn("Lives outside Nigeria", " ".join(m.value for m in at.markdown))   # internal note stays

    def test_players_cannot_reach_the_applications(self):
        self.s.ensure_account(PLAYER["profile_id"], PLAYER["email"], PLAYER["name"], True, False)
        self.s.apply_founding(PLAYER["profile_id"], "Lagos", None, True, True, True, terms_version=rewards_module.TERMS_VERSION)
        at = self.app(PLAYER, page="Owner").run()
        self.assertEqual([t for t in at.tabs if t.label.startswith(("🌟 Founding 50", "🤝 Friends & Family 10"))], [])
        self.assertEqual([b for b in at.button if (b.key or "").startswith("rw_f_approve")], [])

    def test_dashboard_figures(self):
        for n in range(1, 5):
            self.s.ensure_account(pid(n), f"p{n}@example.com", f"P{n}", True, False)
            self.s.apply_founding(pid(n), "Lagos", None, True, True, True, terms_version=rewards_module.TERMS_VERSION)
        ids = {n: self.s.founding_application(pid(n))["id"] for n in range(1, 5)}
        self.s.decide_founding(ids[1], "approve", OWNER)
        self.s.decide_founding(ids[2], "approve", OWNER)
        self.s.decide_founding(ids[3], "waitlist", OWNER)
        self.s.join(pid(1), rewards.month_key())
        self.s.add_event(pid(1), "quiz", "q1", rewards.day_key(), reward=True, test=False)
        owner = self.app(OWNER_ID, page="Owner").run()
        self.assertEqual([x.value for x in owner.exception], [])
        html = " ".join(str(h.proto) for h in owner.get("html"))
        for label, value in (("Places available", "48 / 50"), ("Approved participants", "2"),
                             ("Waiting list", "1"), ("Taking part this month", "1"), ("Active this month", "1")):
            self.assertRegex(html, rf"{label}</span><b>{value}</b>", label)

    def test_without_the_migration_real_players_cannot_join(self):
        with mock.patch.object(self.hooks, "founding_store", return_value=None):
            at = self.app(PLAYER).run()
        self.assertTrue(any("open soon" in x.value for x in at.info))
        self.assertIsNone(self.button(at, "Join"))
        self.assertIsNone(self.button(at, "Apply for the Founding 50"))

    def test_player_texts_in_five_languages(self):
        strings = json.load(open(ROOT / "data" / "translations.json", encoding="utf-8"))["strings"]
        from ui import founding_ui
        english = {founding_ui.TEST_LABEL, *founding_ui.APPLY_ERRORS.values(),
                   *(text for _, text in founding_ui.STATUS_TEXT.values()),
                   "World Explorer Founding 50", "Apply for the Founding 50", "Places available",
                   "State of residence", "🔒 Withdraw — Founding 50 approval needed"}
        for text in english:
            self.assertIn(text, strings, text)
            self.assertEqual(len(strings[text]), 4, text)
            self.assertTrue(all(strings[text]), text)
        for language, word in (("Deutsch", "Bewerbung"), ("Español", "solicitud"), ("中文（普通话）", "申请"),
                               ("Русский", "заявк")):
            at = self.app(PLAYER, language=language).run()
            self.assertEqual([x.value for x in at.exception], [])
            page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
            self.assertIn(word.lower(), page.lower(), language)
            self.assertNotIn("Anyone can apply", page, language)


if __name__ == "__main__":
    unittest.main()
