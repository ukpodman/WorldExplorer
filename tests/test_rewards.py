"""Rewards programme tests: the rules engine, the in-memory store and the real SQL schema (on a throwaway local
PostgreSQL when one is installed).  Run:  python -m unittest tests.test_rewards"""
import json
import random
import subprocess
import sys
import threading
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import rewards  # noqa: E402
from core.rewards import Settings  # noqa: E402
from core.rewards_store import MemoryStore, StoreError, SupabaseStore  # noqa: E402
import pg_harness  # noqa: E402
import founding_fixtures  # noqa: E402

MONTH, DAY = "2026-10", "2026-10-13"
CLUSTER = None


def setUpModule():
    global CLUSTER
    if pg_harness.available():
        try:
            CLUSTER = pg_harness.Cluster()
        except Exception as error:  # pragma: no cover - environment specific
            print("local PostgreSQL could not start:", error)
            CLUSTER = None


def tearDownModule():
    if CLUSTER:
        CLUSTER.stop()


def pid(n) -> str:
    return f"{n:064x}"


def day(n) -> str:
    return f"2026-10-{n:02d}"


# ============================================================================ rules engine

class EngineTests(unittest.TestCase):
    def test_defaults_match_approved_structure(self):
        s = Settings()
        self.assertEqual(s.monthly_cap, 1000)
        self.assertEqual({k: s.category_cap(k) for k in rewards.KINDS},
                         {"active_day": 500, "quiz": 300, "country": 200, "referral": 200})
        self.assertEqual(sum(s.category_cap(k) for k in rewards.KINDS), 1200)
        self.assertEqual(sum(s.category_cap(k) for k in ("active_day", "quiz", "country")), 1000)  # no referrals
        self.assertEqual(s.places_by_budget(), 50)
        self.assertEqual(s.validate(), [])

    def test_validate_rejects_unsafe_settings(self):
        self.assertTrue(Settings(quiz_amount=-1).validate())
        self.assertTrue(Settings(monthly_cap=0).validate())
        self.assertTrue(Settings(active_day_amount=10).validate())   # 1000 no longer reachable without referrals
        self.assertTrue(Settings(start_date="soon").validate())
        self.assertEqual(Settings.from_row({"quiz_amount": "12", "paused": 1, "start_date": "2026-11-01T00:00"}),
                         Settings(quiz_amount=12, paused=True, start_date="2026-11-01"))

    def test_lagos_days_and_months(self):
        late = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)   # 00:30 on 1 November in Lagos
        self.assertEqual(rewards.day_key(late), "2026-11-01")
        self.assertEqual(rewards.month_key(late), "2026-11")
        self.assertEqual(rewards.previous_month("2026-01"), "2025-12")
        self.assertTrue(rewards.programme_started(Settings(), late))
        self.assertFalse(rewards.programme_started(Settings(start_date="2027-01-01"), late))

    def test_codes(self):
        rng = random.Random(1)
        codes = {rewards.new_referral_code(rng) for _ in range(500)}
        self.assertTrue(all(rewards.valid_code(c) for c in codes))
        for bad in ("WE7X9", "we7x92", "WE0O1I", "XX7X92", None, 7):
            self.assertFalse(rewards.valid_code(bad))
        self.assertTrue(rewards.valid_code("WE7X92"))

    def test_event_keys_are_deterministic(self):
        self.assertEqual(rewards.event_key("p", "quiz", "r1", MONTH), rewards.event_key("p", "quiz", "r1", "2026-11"))
        self.assertNotEqual(rewards.event_key("p", "country", "ng", MONTH),
                            rewards.event_key("p", "country", "ng", "2026-11"))   # once per country per month
        self.assertEqual(rewards.event_key("p", "referral", "q", MONTH), "referral:q")
        with self.assertRaises(ValueError):
            rewards.event_key("p", "login", "x", MONTH)

    def _run(self, plan, settings=None, eligible=True):
        settings = settings or Settings()
        events = []
        for kind, d in plan:
            amount, _ = rewards.award(kind, events, d, settings, eligible)
            events.append({"kind": kind, "day": d, "amount": amount})
        return events

    def test_daily_and_monthly_limits(self):
        events = self._run([("quiz", DAY)] * 5)
        self.assertEqual([e["amount"] for e in events], [10, 10, 10, 0, 0])
        events = self._run([("country", DAY)] * 7)
        self.assertEqual(sum(e["amount"] for e in events), 25)
        plan = [("quiz", day(d)) for d in range(1, 15) for _ in range(3)]
        self.assertEqual(sum(e["amount"] for e in self._run(plan)), 300)
        self.assertEqual(sum(e["amount"] for e in self._run([("active_day", day(d)) for d in range(1, 31)])), 500)
        self.assertEqual(sum(e["amount"] for e in self._run([("referral", DAY)] * 6)), 200)

    def test_combined_cap_is_strictly_1000_and_reachable_without_referrals(self):
        plan = []
        for d in range(1, 31):
            plan += [("active_day", day(d))] + [("quiz", day(d))] * 3 + [("country", day(d))] * 5
        events = self._run(plan)
        self.assertEqual(sum(e["amount"] for e in events), 1000)
        plan += [("referral", day(30))] * 4
        self.assertEqual(sum(e["amount"] for e in self._run(plan)), 1000)
        # referrals first, then everything else: still exactly 1000, with a partial last award
        plan = [("referral", day(1))] * 4 + plan[:-4]
        events = self._run(plan)
        self.assertEqual(sum(e["amount"] for e in events), 1000)

    def test_award_reasons(self):
        self.assertEqual(rewards.award("quiz", [], DAY, Settings(), False), (0, "not_enrolled"))
        self.assertEqual(rewards.award("quiz", [], DAY, Settings(paused=True), True), (0, "paused"))
        full = [{"kind": "active_day", "day": day(d), "amount": 25} for d in range(1, 21)]
        full += [{"kind": "quiz", "day": day(d), "amount": 10} for d in range(1, 31)]
        full += [{"kind": "country", "day": day(d), "amount": 5} for d in range(1, 37)]
        self.assertEqual(rewards.award("country", full, day(31), Settings(), True), (5, "awarded"))   # 980 earned
        amount, reason = rewards.award("referral", full, day(31), Settings(), True)
        self.assertEqual((amount, reason), (20, "partial_cap"))   # 980 earned: only 20 left

    def test_qualifying_quiz(self):
        q = {"finished": True, "mode": "regular", "questions": [1] * 5, "history": [1] * 5}
        self.assertTrue(rewards.qualifying_quiz(q))
        self.assertFalse(rewards.qualifying_quiz(dict(q, questions=[1] * 4, history=[1] * 4)))
        self.assertFalse(rewards.qualifying_quiz(dict(q, finished=False)))
        self.assertFalse(rewards.qualifying_quiz(dict(q, mode="daily_replay")))
        self.assertFalse(rewards.qualifying_quiz(dict(q, history=[1] * 3)))
        self.assertTrue(rewards.qualifying_quiz(dict(q, mode="daily")))

    def test_active_day_needs_real_activity(self):
        self.assertFalse(rewards.active_day_due([]))
        self.assertFalse(rewards.active_day_due([{"kind": "country", "subject": "ng"}] * 2))
        self.assertTrue(rewards.active_day_due([{"kind": "country", "subject": "ng"},
                                                {"kind": "country", "subject": "gh"}]))
        self.assertTrue(rewards.active_day_due([{"kind": "quiz", "subject": "r"}]))

    def test_referral_qualification(self):
        events = [{"kind": "active_day", "subject": day(d)} for d in range(1, 4)]
        events += [{"kind": "quiz", "subject": f"r{i}"} for i in range(5)]
        events += [{"kind": "country", "subject": f"c{i}"} for i in range(9)]
        totals = rewards.activity_totals(events)
        self.assertFalse(rewards.referral_qualifies(totals))
        self.assertEqual(rewards.referral_progress(totals)["countries"], (9, 10))
        events.append({"kind": "country", "subject": "c9"})
        self.assertTrue(rewards.referral_qualifies(rewards.activity_totals(events)))

    def test_budget_figures_separate_reserved_earned_approved_paid(self):
        enrol = [{"status": "enrolled", "reserved_amount": 1000}] * 3 + [{"status": "waitlist", "reserved_amount": 0}]
        enrol += [{"status": "withdrawn", "reserved_amount": 40}]
        events = [{"amount": 300}, {"amount": 100}]
        pays = [{"status": "pending_review", "earned": 100}, {"status": "approved", "approved_amount": 250},
                {"status": "paid", "approved_amount": 50, "paid_amount": 50}]
        f = rewards.budget_figures(Settings(), enrol, events, pays)
        self.assertEqual((f["allocated"], f["reserved"], f["earned"], f["pending"], f["approved"], f["paid"]),
                         (50000, 3040, 400, 100, 300, 50))
        self.assertEqual((f["unreserved"], f["participants"], f["waitlist"], f["average"]), (46960, 3, 1, 133))

    def test_fraud_signals_are_proportionate(self):
        self.assertEqual(rewards.fraud_signals({}, [], [], []), [])
        fast = [{"kind": "quiz", "day": DAY, "detail": {"avg_seconds": 0.8}}] * 3
        self.assertTrue(any("Unusual quiz" in f for f in rewards.fraud_signals({}, fast, [], [])))
        burst = [{"created_at": f"2026-10-13T0{h}:00:00+00:00", "status": "pending"} for h in range(5)]
        self.assertTrue(any("registrations" in f for f in rewards.fraud_signals({}, [], burst, [])))
        tries = [{"outcome": "existing_account"}] * 2 + [{"outcome": "self"}]
        self.assertTrue(any("Duplicate" in f for f in rewards.fraud_signals({}, [], [], tries)))
        quick = [{"status": "qualified", "created_at": "2026-10-01T00:00:00Z", "qualified_at": "2026-10-02T00:00:00Z"}]
        self.assertTrue(any("earning" in f for f in rewards.fraud_signals({}, [], quick * 2, [])))
        self.assertTrue(rewards.fraud_signals({"review": "hold"}, [], [], []))
        # a household sharing one device: two normal accounts produce no signals at all
        normal = [{"kind": "quiz", "day": DAY, "detail": {"avg_seconds": 6}}] * 3
        self.assertEqual(rewards.fraud_signals({"review": "ok"}, normal, [], [{"outcome": "attributed"}]), [])

    def test_payment_transitions(self):
        t = rewards.payment_transition
        self.assertEqual(t({"status": "pending_review"}, "approved", None, 400)[0],
                         {"status": "approved", "approved_amount": 400})
        self.assertTrue(t({"status": "pending_review"}, "approved", 500, 400)[1])
        self.assertTrue(t({"status": "pending_review"}, "paid", None, 400)[1])          # never straight to paid
        changes, error = t({"status": "approved", "approved_amount": 300}, "paid", None, 400)
        self.assertEqual((changes, error), ({"status": "paid", "paid_amount": 300}, None))
        self.assertTrue(t({"status": "approved", "approved_amount": 300}, "paid", 301, 400)[1])
        self.assertTrue(t({"status": "paid", "approved_amount": 300}, "rejected", None, 400)[1])
        self.assertEqual(t({"status": "approved", "approved_amount": 300}, "rejected", None, 400)[0]["approved_amount"], 0)
        self.assertTrue(t({}, "maybe", None, 1)[1])


# ============================================================================ store scenarios (memory + SQL)

class StoreScenarios:
    """Run against MemoryStore and against the real SQL (PsqlStore). Subclasses provide make_store()."""

    def make_store(self, settings: Settings | None = None):
        raise NotImplementedError

    def member(self, store, n, new=True, test=False, month=MONTH):
        store.ensure_account(pid(n), f"p{n}@example.com", f"P{n}", new, test)
        return store.join(pid(n), month)

    def test_account_codes_are_permanent_and_unique(self):
        s = self.make_store()
        first = s.ensure_account(pid(1), "a@example.com", "A", True)
        again = s.ensure_account(pid(1), "a@example.com", "A", False)
        self.assertEqual(first["referral_code"], again["referral_code"])
        self.assertTrue(again["new_registration"])              # first answer is kept
        codes = {s.ensure_account(pid(n), None, None, False)["referral_code"] for n in range(2, 40)}
        self.assertEqual(len(codes), 38)
        self.assertEqual(s.account_by_code(first["referral_code"])["profile_id"], pid(1))

    def test_not_enrolled_earns_nothing_but_activity_is_recorded(self):
        s = self.make_store()
        s.ensure_account(pid(1), None, None, True)
        row = s.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False)
        self.assertEqual((row["amount"], row["reason"]), (0, "not_enrolled"))
        self.assertIsNone(s.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False))   # repeat ignored
        self.assertEqual(len(s.events(pid(1))), 1)

    def test_join_needs_declarations_and_caps_hold(self):
        s = self.make_store()
        status = self.member(s, 1)
        self.assertEqual((status["status"], status["reserved_amount"]), ("enrolled", 1000))
        acc = s.account(pid(1))
        self.assertTrue(acc["age_confirmed"] and acc["residence_confirmed"])
        self.assertEqual(acc["verification"], "provisional")
        got = [s.add_event(pid(1), "quiz", f"r{i}", DAY, reward=True, test=False)["amount"] for i in range(4)]
        self.assertEqual(got, [10, 10, 10, 0])
        self.assertEqual(s.events(pid(1))[-1]["reason"], "day_limit")
        got = [s.add_event(pid(1), "country", f"c{i}", DAY, reward=True, test=False)["amount"] for i in range(6)]
        self.assertEqual(got, [5] * 5 + [0])
        self.assertIsNone(s.add_event(pid(1), "country", "c0", DAY, reward=True, test=False))  # once per month
        self.assertEqual(s.add_event(pid(1), "active_day", DAY, DAY, reward=True, test=False)["amount"], 25)
        self.assertIsNone(s.add_event(pid(1), "active_day", DAY, DAY, reward=True, test=False))

    def test_full_month_reaches_exactly_1000(self):
        s = self.make_store()
        self.member(s, 1)
        for d in range(1, 32):
            s.add_event(pid(1), "active_day", day(d), day(d), reward=True, test=False)
            for i in range(3):
                s.add_event(pid(1), "quiz", f"q{d}-{i}", day(d), reward=True, test=False)
            for i in range(5):
                s.add_event(pid(1), "country", f"c{d}-{i}", day(d), reward=True, test=False)
            s.add_event(pid(1), "referral", pid(100 + d), day(d), reward=True, test=False)
        events = s.events(pid(1), MONTH)
        total = sum(e["amount"] for e in events)
        self.assertEqual(total, 1000)
        by = rewards.summarize(events)
        self.assertLessEqual(by["active_day"]["amount"], 500)
        self.assertLessEqual(by["quiz"]["amount"], 300)
        self.assertLessEqual(by["country"]["amount"], 200)
        self.assertLessEqual(by["referral"]["amount"], 200)

    def test_paused_and_start_date(self):
        s = self.make_store(Settings(start_date="2026-10-15"))
        self.member(s, 1)
        self.assertEqual(s.add_event(pid(1), "quiz", "r1", "2026-10-14", reward=True, test=False)["reason"],
                         "not_started")
        self.assertEqual(s.add_event(pid(1), "quiz", "r2", "2026-10-15", reward=True, test=False)["amount"], 10)
        self.assertEqual(s.save_settings(Settings(start_date="2026-10-15", paused=True), "owner@example.com"), [])
        self.assertEqual(s.add_event(pid(1), "quiz", "r3", "2026-10-15", reward=True, test=False)["reason"], "paused")
        s.ensure_account(pid(2), None, None, True)
        s.update_account(pid(2), {"membership": "member", "age_confirmed": True, "residence_confirmed": True,
                                  "terms_version": rewards.TERMS_VERSION})
        with self.assertRaises(StoreError) as caught:
            s.enrol(pid(2), MONTH)
        self.assertIn("paused", str(caught.exception))

    def test_unsafe_settings_are_refused(self):
        s = self.make_store()
        self.assertTrue(s.save_settings(Settings(active_day_amount=1), "o"))
        with self.assertRaises(StoreError):
            s.update("reward_program_settings", {"id": 1}, {"active_day_amount": 1})
        self.assertEqual(s.settings().active_day_amount, 25)

    def test_places_budget_and_waitlist(self):
        s = self.make_store(Settings(max_places=2, monthly_budget=50000))
        self.assertEqual([self.member(s, n)["status"] for n in (1, 2, 3, 4)],
                         ["enrolled", "enrolled", "waitlist", "waitlist"])
        self.assertEqual([e["waitlist_position"] for e in s.enrolments(MONTH) if e["status"] == "waitlist"], [1, 2])
        # earnings, then withdraw: what was earned stays reserved, the place moves to the waiting list
        s.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False)
        s.withdraw(pid(1), MONTH, pid(1))
        self.assertEqual(s.enrolment(pid(1), MONTH)["reserved_amount"], 10)
        self.assertEqual(s.add_event(pid(1), "quiz", "r2", DAY, reward=True, test=False)["reason"], "not_enrolled")
        self.assertEqual(s.events(pid(1))[0]["amount"], 10)                      # earned reward kept
        self.assertEqual(s.promote(MONTH, "owner"), 1)
        self.assertEqual(s.enrolment(pid(3), MONTH)["status"], "enrolled")
        self.assertEqual(s.enrolment(pid(4), MONTH)["status"], "waitlist")
        # budget limits too: lowering the budget never removes anyone already enrolled
        settings = s.settings()
        settings.monthly_budget, settings.max_places = 1000, 10
        self.assertEqual(s.save_settings(settings, "owner"), [])
        self.assertEqual(s.promote(MONTH), 0)
        self.assertEqual(sum(1 for e in s.enrolments(MONTH) if e["status"] == "enrolled"), 2)
        settings.monthly_budget = 50000
        s.save_settings(settings, "owner")
        self.assertEqual(s.promote(MONTH), 1)
        # a new joiner never jumps the queue
        self.assertEqual(self.member(s, 5)["status"], "enrolled")

    def test_enrolment_is_idempotent_and_requires_membership(self):
        s = self.make_store()
        first = self.member(s, 1)
        self.assertEqual(s.enrol(pid(1), MONTH)["created_at"], first["created_at"])
        s.ensure_account(pid(2), None, None, True)
        with self.assertRaises(StoreError) as caught:
            s.enrol(pid(2), MONTH)
        self.assertIn("not_member", str(caught.exception))

    def test_test_accounts_never_use_real_budget_or_become_payable(self):
        s = self.make_store(Settings(max_places=1))
        self.member(s, 9, test=True)
        self.assertEqual(self.member(s, 1)["status"], "enrolled")    # tester did not take the only place
        self.assertEqual(s.add_event(pid(9), "quiz", "t1", DAY, reward=True, test=True)["amount"], 10)
        forced = s.add_event(pid(9), "quiz", "t2", DAY, reward=True, test=False)   # a tester cannot create real rows
        self.assertEqual((forced["test"], forced["amount"]), (True, 10))
        self.assertTrue(all(e["test"] for e in s.events(pid(9))))
        s.update_account(pid(9), {"verification": "verified"})
        s.open_payment(pid(9), MONTH, True, "owner")
        with self.assertRaises(StoreError):
            s.update_payment(pid(9), MONTH, {"status": "approved", "approved_amount": 10}, "owner")
        s.clear_test_data("owner")
        self.assertEqual(s.events(pid(9)), [])
        self.assertEqual(s.enrolment(pid(1), MONTH)["status"], "enrolled")

    def test_events_and_real_records_are_frozen(self):
        s = self.make_store()
        self.member(s, 1)
        s.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False)
        with self.assertRaises(StoreError):
            s.update("reward_activity_events", {"profile_id": pid(1)}, {"amount": 0})
        with self.assertRaises(StoreError):
            s.delete("reward_activity_events", {"profile_id": pid(1)})
        with self.assertRaises(StoreError):
            s.clear_test_data("owner") or s.delete("reward_enrolments", {"profile_id": pid(1)})
        self.assertEqual(s.events(pid(1))[0]["amount"], 10)

    def test_referrals(self):
        s = self.make_store()
        a = s.ensure_account(pid(1), None, None, False)                 # an existing user may refer people
        s.ensure_account(pid(2), None, None, True)
        s.ensure_account(pid(3), None, None, False)                     # existing account: not a new referral
        code = a["referral_code"]
        self.assertEqual(s.record_visit("v1", code), "visit")
        self.assertEqual(s.record_visit("v1", code), "visit")           # same session counted once
        self.assertEqual(s.record_visit("v2", "WEZZZZ"), "unknown_code")
        self.assertEqual(s.attribute(pid(1), code), "self")
        self.assertEqual(s.attribute(pid(3), code), "existing_account")
        self.assertEqual(s.attribute(pid(2), code, "v1"), "attributed")
        self.assertEqual(s.attribute(pid(2), code), "already_referred")
        b = s.account(pid(2))
        s.ensure_account(pid(4), None, None, True)
        self.assertEqual(s.attribute(pid(4), b["referral_code"]), "attributed")   # chains are fine
        # circular: 2 referred by 1; 1 cannot be referred by 2 (1 is existing anyway, so use new accounts)
        s.ensure_account(pid(5), None, None, True)
        s.ensure_account(pid(6), None, None, True)
        self.assertEqual(s.attribute(pid(6), s.account(pid(5))["referral_code"]), "attributed")
        self.assertEqual(s.attribute(pid(5), s.account(pid(6))["referral_code"]), "circular")
        self.assertEqual([v["outcome"] for v in s.visits(pid(1))], ["attributed"])
        self.assertEqual(len(s.visits()), 2)
        self.assertEqual([r["referred_id"] for r in s.referrals(pid(1))], [pid(2)])
        s.update_referral(pid(2), {"status": "qualified", "qualified_at": "2026-10-20T10:00:00+00:00"})
        self.assertEqual(s.referral_of(pid(2))["status"], "qualified")

    def test_referral_reward_only_once(self):
        s = self.make_store()
        self.member(s, 1)
        self.assertEqual(s.add_event(pid(1), "referral", pid(2), DAY, reward=True, test=False)["amount"], 50)
        self.assertIsNone(s.add_event(pid(1), "referral", pid(2), day(20), reward=True, test=False))

    def test_payment_workflow(self):
        s = self.make_store()
        self.member(s, 1)
        for i in range(3):
            s.add_event(pid(1), "quiz", f"r{i}", DAY, reward=True, test=False)
        p = s.open_payment(pid(1), MONTH, False, "owner@example.com")
        self.assertEqual((p["earned"], p["status"]), (30, "pending_review"))
        self.assertEqual(s.open_payment(pid(1), MONTH, False, "owner")["earned"], 30)   # not duplicated
        with self.assertRaises(StoreError):    # provisional eligibility is not enough to approve money
            s.update_payment(pid(1), MONTH, {"status": "approved", "approved_amount": 30}, "owner")
        s.update_account(pid(1), {"verification": "verified"})
        with self.assertRaises(StoreError):
            s.update_payment(pid(1), MONTH, {"status": "approved", "approved_amount": 31}, "owner")
        with self.assertRaises(StoreError):
            s.update_payment(pid(1), MONTH, {"status": "paid", "paid_amount": 30, "payment_date": DAY}, "owner")
        s.update_payment(pid(1), MONTH, {"status": "approved", "approved_amount": 25}, "owner")
        with self.assertRaises(StoreError):
            s.update_payment(pid(1), MONTH, {"status": "paid", "paid_amount": 30, "payment_date": DAY}, "owner")
        with self.assertRaises(StoreError):    # paid needs a date
            s.update_payment(pid(1), MONTH, {"status": "paid", "paid_amount": 25}, "owner")
        done = s.update_payment(pid(1), MONTH, {"status": "paid", "paid_amount": 25, "payment_date": DAY,
                                                "reference": "TRX-1", "remarks": "bank transfer"}, "owner")
        self.assertEqual((done["status"], done["paid_amount"]), ("paid", 25))
        with self.assertRaises(StoreError):
            s.update_payment(pid(1), MONTH, {"status": "rejected"}, "owner")
        s.update_payment(pid(1), MONTH, {"remarks": "receipt sent"}, "owner")      # remarks stay editable
        with self.assertRaises(StoreError):
            s.delete("reward_payments", {"profile_id": pid(1)})
        actions = [a["action"] for a in s.audit()]
        self.assertGreaterEqual(actions.count("reward_payments_update"), 3)
        self.assertIn("reward_payments_insert", actions)
        self.assertTrue(all(a["actor"] for a in s.audit() if a["action"].startswith("reward_payments")))

    def test_audit_covers_settings_and_reviews(self):
        s = self.make_store()
        s.ensure_account(pid(1), None, None, True)
        s.save_settings(Settings(quiz_amount=11), "owner@example.com")
        s.update_account(pid(1), {"review": "hold", "review_note": "check"})
        s.update_account(pid(1), {"display_name": "renamed"})                # not an audited field
        actions = [(a["action"], a["actor"]) for a in s.audit()]
        self.assertIn(("reward_program_settings_update", "owner@example.com"), actions)
        self.assertEqual(sum(1 for a, _ in actions if a == "reward_accounts_update"), 1)
        with self.assertRaises(StoreError):
            s.update("reward_audit_log", {}, {"actor": "x"})


class MemoryStoreTests(StoreScenarios, unittest.TestCase):
    def make_store(self, settings=None):
        # owner switch ON and every account approved for Founding 50 in these scenarios (tested in test_founding50)
        return founding_fixtures.auto_approve(MemoryStore(settings, public_enabled=True))


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
class SqlStoreTests(StoreScenarios, unittest.TestCase):
    def make_store(self, settings=None):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        store = pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db())
        CLUSTER.set_public(store.db, True)   # owner switch ON for these scenarios (default OFF)
        if settings:
            row = settings.as_row()
            store.update("reward_program_settings", {"id": 1}, row)
        return founding_fixtures.auto_approve(store)   # every account approved for Founding 50 (see test_founding50)

    def test_browser_roles_have_no_access(self):
        store = self.make_store()
        store.ensure_account(pid(1), None, None, True)
        for role in ("anon", "authenticated"):
            for sql in ("select count(*) from public.reward_accounts",
                        "select count(*) from public.reward_activity_events",
                        "select count(*) from public.reward_payments",
                        "select count(*) from public.reward_monthly_summary",
                        "select count(*) from public.reward_audit_log",
                        f"select public.reward_enrol('{pid(1)}', '{MONTH}')",
                        f"select public.reward_ensure_account('{pid(2)}', null, null, true, false)",
                        "update public.reward_program_settings set paused = true"):
                with self.assertRaises(StoreError, msg=f"{role}: {sql}"):
                    CLUSTER.psql(store.db, sql, role)
        rls = CLUSTER.psql(store.db, "select bool_and(relrowsecurity) from pg_class where relname in "
                                     "('reward_program_settings','reward_accounts','reward_enrolments',"
                                     "'reward_activity_events','user_referrals','reward_referral_visits',"
                                     "'reward_payments','reward_audit_log')")
        self.assertEqual(rls, "t")

    def test_schema_is_rerunnable_and_keeps_data(self):
        store = self.make_store()
        self.member(store, 1)
        store.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False)
        CLUSTER.psql_file(store.db, pg_harness.SCHEMA)
        self.assertEqual(store.events(pid(1))[0]["amount"], 10)
        self.assertEqual(store.enrolment(pid(1), MONTH)["status"], "enrolled")

    def test_monthly_summary_view(self):
        store = self.make_store()
        self.member(store, 1)
        store.add_event(pid(1), "quiz", "r1", DAY, reward=True, test=False)
        store.add_event(pid(1), "country", "ng", DAY, reward=True, test=False)
        row = store.select("reward_monthly_summary", {"profile_id": pid(1)})[0]
        self.assertEqual((row["total_amount"], row["quizzes"], row["countries"]), (15, 1, 1))

    def test_simultaneous_enrolments_never_exceed_places(self):
        store = self.make_store(Settings(max_places=3))
        for n in range(1, 13):
            store.ensure_account(pid(n), None, None, True)
            store.update_account(pid(n), {"membership": "member", "age_confirmed": True, "residence_confirmed": True,
                                          "terms_version": rewards.TERMS_VERSION})
        procs = [subprocess.Popen(["psql", "-h", CLUSTER.dir, "-p", CLUSTER.port, "-U", "postgres", "-d", store.db,
                                   "-Atqc", f"set role service_role; select (public.reward_enrol('{pid(n)}', '{MONTH}')).status"],
                                  stdout=subprocess.PIPE, text=True) for n in range(1, 13)]
        results = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(results.count("enrolled"), 3, results)
        self.assertEqual(results.count("waitlist"), 9)
        positions = sorted(e["waitlist_position"] for e in store.enrolments(MONTH) if e["status"] == "waitlist")
        self.assertEqual(positions, list(range(1, 10)))

    def test_simultaneous_awards_never_exceed_caps(self):
        store = self.make_store()
        self.member(store, 1)
        procs = []
        for i in range(10):
            key = f"quiz:{pid(1)}:race{i}"
            sql = (f"set role service_role; insert into public.reward_activity_events "
                   f"(event_key, profile_id, kind, subject, month, day, amount) values "
                   f"('{key}', '{pid(1)}', 'quiz', 'race{i}', '{MONTH}', '{DAY}', 1)")
            procs.append(subprocess.Popen(["psql", "-h", CLUSTER.dir, "-p", CLUSTER.port, "-U", "postgres",
                                           "-d", store.db, "-Atqc", sql], stdout=subprocess.PIPE, text=True))
        for p in procs:
            p.communicate()
        self.assertEqual(sum(e["amount"] for e in store.events(pid(1))), 30)   # 3 quizzes a day

    def test_sql_and_python_rules_agree(self):
        """Random activity sequences give identical amounts and reasons in SQL and in rewards.award()."""
        rng = random.Random(42)
        for trial in range(3):
            settings = Settings(quiz_max_day=rng.choice([2, 3]), country_max_day=rng.choice([3, 5]),
                                monthly_cap=rng.choice([600, 1000]))
            sql, mem = self.make_store(settings), founding_fixtures.auto_approve(MemoryStore(settings, public_enabled=True))
            for store in (sql, mem):
                self.member(store, 1)
            for i in range(160):
                kind = rng.choice(rewards.KINDS)
                d = day(rng.randint(1, 31))
                subject = d if kind == "active_day" else f"s{rng.randint(0, 60)}"
                a = sql.add_event(pid(1), kind, subject, d, reward=True, test=False)
                b = mem.add_event(pid(1), kind, subject, d, reward=True, test=False)
                self.assertEqual(a is None, b is None)
                if a:
                    self.assertEqual((a["amount"], a["reason"]), (b["amount"], b["reason"]), (trial, i, kind, d))
            self.assertLessEqual(sum(e["amount"] for e in sql.events(pid(1))), settings.monthly_cap)


# ============================================================================ Supabase REST requests

class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self, *_):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class SupabaseStoreTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.store = SupabaseStore("https://abc.supabase.co/", "sb_secret_TEST")

    def fake(self, body):
        def opener(request, timeout=None):
            self.calls.append(request)
            return FakeResponse(body)
        return unittest.mock.patch("urllib.request.urlopen", opener)

    def test_select_filters_and_paging(self):
        with self.fake([{"a": 1}]):
            rows = self.store.select("reward_activity_events", {"profile_id": "p", "test": False,
                                                                "kind": ("in", ["quiz", "country"])}, order="created_at")
        self.assertEqual(rows, [{"a": 1}])
        url = self.calls[0].full_url
        self.assertTrue(url.startswith("https://abc.supabase.co/rest/v1/reward_activity_events?select=*"))
        for part in ("profile_id=eq.p", "test=is.false", "kind=in.(quiz,country)", "order=created_at", "limit=1000",
                     "offset=0"):
            self.assertIn(part, url)
        headers = {k.lower(): v for k, v in self.calls[0].header_items()}
        self.assertEqual(headers["apikey"], "sb_secret_TEST")
        self.assertNotIn("authorization", headers)                  # new secret keys go in apikey only

    def test_event_insert_ignores_duplicates_and_returns_stored_row(self):
        with self.fake([{"amount": 10, "reason": "awarded"}]):
            row = self.store.add_event("p" * 64, "quiz", "r1", DAY, reward=True, test=False)
        self.assertEqual(row["amount"], 10)
        request = self.calls[0]
        self.assertIn("on_conflict=event_key", request.full_url)
        self.assertIn("resolution=ignore-duplicates", dict(request.header_items())["Prefer"])
        body = json.loads(request.data)
        self.assertEqual((body["event_key"], body["amount"], body["month"]), (f"quiz:{'p' * 64}:r1", 1, MONTH))
        with self.fake([]):
            self.assertIsNone(self.store.add_event("p" * 64, "quiz", "r1", DAY, reward=True, test=False))

    def test_rpc_and_errors(self):
        with self.fake({"status": "enrolled"}):
            self.assertEqual(self.store.enrol("p", MONTH)["status"], "enrolled")
        self.assertTrue(self.calls[-1].full_url.endswith("/rest/v1/rpc/reward_enrol"))
        legacy = SupabaseStore("https://abc.supabase.co", "eyJ.legacy")
        self.assertEqual(legacy._headers()["Authorization"], "Bearer eyJ.legacy")

        import io
        import urllib.error

        def failing(code, payload):
            def opener(request, timeout=None):
                raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(json.dumps(payload).encode()))
            return unittest.mock.patch("urllib.request.urlopen", opener)

        with failing(400, {"code": "P0001", "message": "paused"}):
            with self.assertRaises(StoreError) as caught:
                self.store.enrol("p", MONTH)
        self.assertEqual(str(caught.exception), "paused")
        with failing(404, {"code": "PGRST205", "message": "Could not find the table"}):
            self.assertEqual(self.store.health(), "missing_tables")

    def test_filter_values_are_encoded(self):
        with self.fake([]):
            self.store.select("reward_accounts", {"email": "a&b=c@example.com"})
        self.assertIn("email=eq.a%26b%3Dc%40example.com", self.calls[0].full_url)


class OwnerAnalyticsTests(unittest.TestCase):
    def test_activity_overview(self):
        from datetime import timedelta
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        ev = lambda p, days_ago: {"_p": p, "_t": now - timedelta(days=days_ago)}
        events = [ev("a", 0), ev("a", 10), ev("b", 3), ev("c", 40), ev("c", 5), ev("d", 8)]
        o = rewards.activity_overview(events, now)
        self.assertEqual((o["people"], o["dau"], o["wau"], o["mau"]), (4, 1, 3, 4))
        self.assertEqual(o["retention7"], {"n": 2, "d": 3, "pct": 66.7})    # a, c returned; d did not
        self.assertEqual(o["retention30"], {"n": 1, "d": 1, "pct": 100.0})

    def test_referral_and_cost_figures(self):
        refs = [{"status": "pending"}, {"status": "qualified"}, {"status": "approved"}, {"status": "rejected"}]
        r = rewards.referral_overview([{}] * 7, [{}] * 8, refs, [{"kind": "referral", "amount": 50}, {"kind": "quiz", "amount": 10}])
        self.assertEqual((r["links"], r["visits"], r["registrations"], r["approved"], r["pending"]), (7, 8, 4, 1, 1))
        self.assertEqual((r["conversion"], r["success_rate"], r["earnings"]), (50.0, 50.0, 50))
        events = [{"profile_id": "a", "kind": "active_day", "subject": f"d{i}", "amount": 25} for i in range(3)]
        events += [{"profile_id": "b", "kind": "active_day", "subject": "d1", "amount": 25}]
        self.assertEqual(rewards.cost_per_retained(events, ["a", "b"]), {"earned": 100, "retained": 1, "cost": 100})
        self.assertIsNone(rewards.cost_per_retained([], ["a"])["cost"])
        o = rewards.fraud_overview({"a": ["Unusual quiz activity: x", "Marked for manual review by the owner"], "b": []})
        self.assertEqual((o["quiz"], o["review"], o["flagged"], o["duplicates"]), (1, 1, 1, 0))


class MemoryThreadSafety(unittest.TestCase):
    def test_parallel_awards_respect_caps(self):
        s = founding_fixtures.auto_approve(MemoryStore(public_enabled=True))
        s.ensure_account(pid(1), None, None, True)
        s.join(pid(1), MONTH)
        threads = [threading.Thread(target=s.add_event, args=(pid(1), "quiz", f"t{i}", DAY),
                                    kwargs={"reward": True, "test": False}) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(e["amount"] for e in s.events(pid(1))), 30)


if __name__ == "__main__":
    unittest.main()
