"""V21 manual cash withdrawals: the rules (core/withdrawals.py), the in-memory store and the real SQL
(supabase/withdrawals_migration.sql on a throwaway local PostgreSQL when one is installed).

Dates are relative to today in Nigeria: M1 and M2 are the two completed months before the current month CUR.
Run:  python -m unittest discover -s tests -p test_withdrawals.py"""
import sys
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import rewards, withdrawals  # noqa: E402
from core.rewards import Settings  # noqa: E402
from core.rewards_store import MemoryStore, StoreError  # noqa: E402
import pg_harness  # noqa: E402

TODAY = withdrawals.today()
CUR = withdrawals.month_of(TODAY)
M2 = rewards.previous_month(CUR)
M1 = rewards.previous_month(M2)
OWNER = "owner@example.com"
DECL = {k: True for k in withdrawals.DECLARATIONS}
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


# ============================================================================ pure rules

class RuleTests(unittest.TestCase):
    def test_month_and_period_labels_in_five_languages(self):
        self.assertEqual(withdrawals.period_label(["2026-10"]), "October 2026")
        self.assertEqual(withdrawals.period_label(["2026-10", "2026-09"]), "September 2026 – October 2026")
        self.assertEqual(withdrawals.month_name("2026-10", "Deutsch"), "Oktober 2026")
        self.assertEqual(withdrawals.month_name("2026-10", "Español"), "octubre 2026")
        self.assertEqual(withdrawals.month_name("2026-10", "Русский"), "октябрь 2026")
        self.assertEqual(withdrawals.month_name("2026-10", "中文（普通话）"), "2026年10月")

    def test_nigeria_dates(self):
        # 23:30 UTC on 31 October is already 1 November in Lagos (UTC+1)
        late = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(withdrawals.today(now=late), date(2026, 11, 1))
        self.assertEqual(withdrawals.lagos_date("2026-10-31T23:30:00+00:00"), date(2026, 11, 1))
        self.assertEqual(withdrawals.today("2026-12-05"), date(2026, 12, 5))

    def test_references(self):
        ref = withdrawals.new_reference(date(2026, 11, 14))
        self.assertRegex(ref, withdrawals.REFERENCE_RE)
        self.assertTrue(ref.startswith("WD-202611-"))

    def test_waiting_period_and_completed_months(self):
        account = {"profile_id": "p", "membership": "member", "terms_version": "t", "age_confirmed": True,
                   "residence_confirmed": True, "review": "ok", "test": False}
        enrol = [{"profile_id": "p", "status": "enrolled", "reserved_amount": 1000, "test": False,
                  "created_at": "2026-10-03T08:00:00+00:00"}]
        events = [{"profile_id": "p", "month": m, "amount": a, "test": False}
                  for m, a in (("2026-09", 650), ("2026-10", 900), ("2026-11", 400))]
        settings = {"live_requests": True, "min_days": 30}
        st = withdrawals.status(account, settings, enrol, events, [], [], [], [], as_of=None,
                                now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(st["reasons"], ["waiting_period"])          # 3 Oct + 30 days = 2 Nov
        self.assertEqual(st["days_left"], 1)
        st = withdrawals.status(account, settings, enrol, events, [], [], [], [],
                                now=datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
        self.assertTrue(st["eligible"])
        self.assertEqual(st["amount"], 1550)                          # November's 400 waits for the month to close
        self.assertEqual([m["month"] for m in st["months"]], ["2026-09", "2026-10"])
        self.assertEqual(st["totals"]["current_month"], 400)

    def test_names_and_fingerprints(self):
        self.assertEqual(withdrawals.normalize_name("  Ádé   OKAFOR "), withdrawals.normalize_name("okafor ade"))
        key = "k" * 40
        fp = withdrawals.fingerprint(key, "058", "0123456789")
        self.assertRegex(fp, r"^[0-9a-f]{64}$")
        self.assertEqual(fp, withdrawals.fingerprint(key, " 058 ", "012-345-6789"))
        self.assertNotEqual(fp, withdrawals.fingerprint("x" * 40, "058", "0123456789"))   # keyed
        self.assertNotIn("0123456789", fp)
        for bad in (("short", "058", "0123456789"), (key, "058", "12345"), (key, "", "0123456789")):
            with self.assertRaises(ValueError):
                withdrawals.fingerprint(*bad)

    def test_identity_flags_never_block(self):
        a = {"profile_id": "a", "legal_name": "Ade Okafor", "bank_fingerprint": "f" * 64, "test": False}
        b = {"profile_id": "b", "legal_name": "okafor  ade", "bank_fingerprint": "f" * 64, "test": False}
        flags = withdrawals.identity_flags(a, [a, b], [{"profile_id": "a", "display_name": "Ade O."}])
        self.assertEqual(len(flags), 2)
        self.assertTrue(flags[0].startswith("Repeated identity"))
        self.assertTrue(flags[1].startswith("Duplicate bank account"))
        flags = withdrawals.identity_flags(a, [a], [{"profile_id": "a", "display_name": "Sunny Day"}])
        self.assertEqual(len(flags), 1)
        self.assertIn("Google account name", flags[0])

    def test_transitions(self):
        t = withdrawals.transition_error
        self.assertIsNone(t("pending_review", "review"))
        self.assertEqual(t("pending_review", "approve"), "verification_required")
        self.assertIsNone(t("pending_review", "approve", beneficiary=True, eligibility=True))
        self.assertEqual(t("under_review", "reject", note=""), "reason_required")
        self.assertEqual(t("paid", "reject", note="late"), "request_closed")
        self.assertEqual(t("approved", "review"), "invalid_transition")
        self.assertIsNone(t("approved", "hold", note="checking the bank name"))

    def test_accounting_by_earning_and_payment_month(self):
        # earned 800 in September and 900 in October, withdrawn and paid in November
        events = [{"profile_id": "p", "month": "2026-09", "amount": 800}, {"profile_id": "p", "month": "2026-10", "amount": 900}]
        requests = [{"id": 1, "status": "paid", "amount": 1700, "profile_id": "p"}]
        reservations = [{"request_id": 1, "month": "2026-09", "amount": 800, "status": "paid"},
                        {"request_id": 1, "month": "2026-10", "amount": 900, "status": "paid"}]
        payments = [{"request_id": 1, "amount": 1700, "payment_month": "2026-11"}]
        earning = {r["Earning month"]: r for r in withdrawals.by_earning_month(events, reservations, requests, [])}
        self.assertEqual(earning["2026-09"]["Earned (liability)"], 800)
        self.assertEqual(earning["2026-10"]["Paid"], 900)
        self.assertNotIn("2026-11", earning)                                    # not new November rewards
        cash = withdrawals.by_payment_month(payments, [])
        self.assertEqual(cash, [{"Payment month": "2026-11", "Withdrawals paid": 1700, "Monthly reviews paid": 0,
                                 "Cash paid": 1700, "Payments": 1}])
        s = withdrawals.summary(requests, payments, events, reservations, [], 50000, "2026-09-01", "2026-11")
        self.assertEqual(s["paid_amount"], 1700)
        self.assertEqual(s["allocated"], 150000)
        self.assertEqual(s["remaining_budget"], 150000 - 1700)                  # counted once, not twice

    def test_rejected_months_return_to_budget_only_when_refused(self):
        events = [{"profile_id": "p", "month": "2026-09", "amount": 500}]
        released = [{"request_id": 1, "month": "2026-09", "amount": 500, "status": "released"}]
        refused = [{"request_id": 1, "month": "2026-09", "amount": 500, "status": "disqualified"}]
        req = [{"id": 1, "status": "rejected", "amount": 500}]
        self.assertEqual(withdrawals.summary(req, [], events, released, [], 1000, "2026-09-01", "2026-09")["remaining_budget"], 500)
        self.assertEqual(withdrawals.summary(req, [], events, refused, [], 1000, "2026-09-01", "2026-09")["remaining_budget"], 1000)


class EmailTests(unittest.TestCase):
    CFG = {"smtp_host": "smtp.example.com", "smtp_port": 587, "sender": "noreply@example.com",
           "owner_to": ["owner@example.com"], "username": "u", "password": "p"}

    def test_off_until_configured(self):
        from core import notify
        self.assertEqual(notify.send({}, "s", "b"), "not_configured")
        self.assertEqual(notify.send({"smtp_host": "x"}, "s", "b"), "not_configured")

    def test_message_and_delivery(self):
        from core import notify
        sent = []

        class FakeSMTP:
            def __init__(self, host, port): self.host = host
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def login(self, user, password): pass
            def send_message(self, message): sent.append(message)
        subject, body = notify.withdrawal_message({"reference": "WD-202611-ABCD", "player": "Ade", "amount": 850,
                                                   "requested_at": "2026-11-14T10:00:00+00:00"}, test=False)
        self.assertEqual(notify.send(self.CFG, subject, body, smtp_factory=FakeSMTP), "sent")
        text = sent[0].get_content()
        for part in ("Ade", "WD-202611-ABCD", "₦850", "2026-11-14"):
            self.assertIn(part, text)
        self.assertIn("TEST RECORD", notify.withdrawal_message({"amount": 1}, test=True)[0])

    def test_failure_never_raises(self):
        from core import notify

        def broken(host, port):
            raise OSError("network down")
        self.assertEqual(notify.send(self.CFG, "s", "b", smtp_factory=broken), "failed")


class SupabaseRestTests(unittest.TestCase):
    """The exact REST calls the live app sends to Supabase (PostgREST) for withdrawals."""

    def setUp(self):
        from core.rewards_store import SupabaseStore
        self.calls = []
        self.store = SupabaseStore("https://abc.supabase.co/", "sb_secret_TEST")

    def fake(self, body):
        import json
        from unittest import mock

        class Response:
            def read(self, *_): return json.dumps(body).encode()
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def opener(request, timeout=None):
            self.calls.append(request)
            return Response()
        return mock.patch("urllib.request.urlopen", opener)

    def body(self, n=-1):
        import json
        return json.loads(self.calls[n].data)

    def test_rpc_names_and_arguments_match_the_sql(self):
        import re
        sql = (ROOT / "supabase" / "withdrawals_migration.sql").read_text()
        params = {name: set(re.findall(r"(p_\w+)\s", args)) for name, args in
                  re.findall(r"create or replace function public\.(reward_cashout_\w+)\(([^)]*)\)", sql)}
        with self.fake({"eligible": False, "reasons": ["not_live"]}):
            self.store.cashout_status("p" * 64)
        with self.fake({"id": 1, "reference": "WD-202611-ABCD"}):
            self.store.request_cashout("p" * 64, "Ade Okafor", DECL, 850, None, ["flag"])
            self.store.decide_cashout(1, "approve", OWNER, "ok", True, True)
            self.store.pay_cashout(1, 850, "2026-11-20", "TRX", OWNER)
        with self.fake(0):
            self.store.fingerprint_cashout(1, "f" * 64, OWNER)
        for request in self.calls:
            name = request.full_url.rsplit("/", 1)[1]
            self.assertTrue(request.full_url.startswith("https://abc.supabase.co/rest/v1/rpc/reward_cashout_"))
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(set(self.body(self.calls.index(request))), params[name], name)
            self.assertEqual(request.headers["Apikey"], "sb_secret_TEST")
        self.assertEqual(self.body(1)["p_declarations"], DECL)                # sent as JSON (jsonb)
        self.assertEqual(self.body(1)["p_expected_amount"], 850)

    def test_reads_and_notification_updates(self):
        with self.fake([]):
            self.store.notifications(unread=True)
            self.store.cashout_requests("p" * 64)
            self.store.mark_notification_read(7, OWNER)
        self.assertIn("/rest/v1/reward_owner_notifications?select=*&read_at=is.null", self.calls[0].full_url)
        self.assertIn("profile_id=eq." + "p" * 64, self.calls[1].full_url)  # a player only reads their own rows
        self.assertEqual(self.calls[2].get_method(), "PATCH")
        self.assertIn("id=eq.7", self.calls[2].full_url)
        self.assertEqual(set(self.body(2)), {"read_at", "read_by"})

    def test_missing_migration_is_detected(self):
        import io, urllib.error
        from unittest import mock

        def missing(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {},
                                         io.BytesIO(b'{"code":"PGRST205","message":"table not found"}'))
        with mock.patch("urllib.request.urlopen", missing):
            self.assertEqual(self.store.cashout_health(), "missing_tables")


# ============================================================================ store scenarios (memory + SQL)

class Scenarios:
    """Run against MemoryStore and the real SQL. Subclasses provide make_store() and backdate()."""

    def make_store(self):
        raise NotImplementedError

    def backdate(self, s, profile, days):
        raise NotImplementedError

    def setup_store(self, live=True, payouts=True):
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{M1}-01"), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"live_requests": live, "real_payouts": payouts,
                                                        "owner_emails": [OWNER]})
        return s

    def earn(self, s, p, month, active=0, quizzes=0, countries=0):
        """Rewards in `month` (25 per active day, 10 per quiz, 5 per country; daily limits respected)."""
        days = 28 if month < CUR else max(TODAY.day, 1)
        for i in range(active):
            s.add_event(p, "active_day", f"{month}-{1 + i % days:02d}", f"{month}-{1 + i % days:02d}", reward=True,
                        test=False)
        for i in range(quizzes):
            d = f"{month}-{1 + (i // 3) % days:02d}"
            s.add_event(p, "quiz", f"q-{month}-{i}", d, reward=True, test=False)
        for i in range(countries):
            d = f"{month}-{1 + (i // 5) % days:02d}"
            s.add_event(p, "country", f"c{i}", d, reward=True, test=False)

    def player(self, s, n, test=False, joined_days_ago=45, m1=650, m2=900, current=55):
        p = pid(n)
        s.ensure_account(p, f"p{n}@example.com", f"Player {n}", True, test)
        s.join(p, M1)
        for m in (M2, CUR):
            s.enrol(p, m)
        self.backdate(s, p, joined_days_ago)
        plans = {650: (20, 15, 0), 900: (20, 30, 20), 55: (1, 3, 0), 0: (0, 0, 0), 300: (12, 0, 0)}
        for month, amount in ((M1, m1), (M2, m2), (CUR, current)):
            self.earn(s, p, month, *plans[amount])
        return p

    # ------------------------------------------------------------------ eligibility

    def test_whole_balance_of_completed_months(self):
        s = self.setup_store()
        p = self.player(s, 1)
        st = s.cashout_status(p)
        self.assertTrue(st["eligible"], st["reasons"])
        self.assertEqual(st["amount"], 1550)
        self.assertEqual([m["month"] for m in st["months"]], [M1, M2])
        self.assertEqual(st["totals"]["current_month"], 55)                 # the incomplete month is excluded
        self.assertEqual(st["totals"]["earned"], 1605)
        self.assertEqual(st["totals"]["unpaid"], 1605)

    def test_waiting_period_from_original_enrolment(self):
        s = self.setup_store()
        p = self.player(s, 1, joined_days_ago=10)
        st = s.cashout_status(p)
        self.assertFalse(st["eligible"])
        self.assertEqual(st["reasons"], ["waiting_period"])
        self.assertIn(st["days_left"], (19, 20, 21))                         # 30 − 10 (± the Lagos day boundary)
        with self.assertRaises(StoreError) as caught:
            s.request_cashout(p, "Ade Okafor", DECL, 1550)
        self.assertIn("waiting_period", str(caught.exception))

    def test_real_requests_stay_off_until_live(self):
        s = self.setup_store(live=False)
        p = self.player(s, 1)
        st = s.cashout_status(p)
        self.assertEqual(st["reasons"], ["not_live"])
        self.assertFalse(st["live"])
        with self.assertRaises(StoreError):
            s.request_cashout(p, "Ade Okafor", DECL, 1550)

    def test_not_joined_suspended_or_on_hold(self):
        s = self.setup_store()
        s.ensure_account(pid(9), None, "Nobody", True)
        self.assertIn("not_joined", s.cashout_status(pid(9))["reasons"])
        p = self.player(s, 1)
        s.update_account(p, {"review": "hold"})
        self.assertIn("account_on_hold", s.cashout_status(p)["reasons"])
        s.update_account(p, {"review": "ok", "membership": "suspended"})
        self.assertIn("suspended", s.cashout_status(p)["reasons"])

    def test_left_programme_keeps_earned_rewards_withdrawable(self):
        s = self.setup_store()
        p = self.player(s, 1)
        s.leave(p, CUR)
        st = s.cashout_status(p)
        self.assertTrue(st["eligible"], st["reasons"])
        self.assertEqual(st["amount"], 1550)

    # ------------------------------------------------------------------ requests

    def test_request_reserves_months_and_notifies_owner(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "  Ade Okafor ", DECL, 1550)
        self.assertRegex(req["reference"], withdrawals.REFERENCE_RE)
        self.assertEqual((req["status"], req["amount"], req["legal_name"]), ("pending_review", 1550, "Ade Okafor"))
        self.assertEqual(sorted(req["months"]), [M1, M2])
        self.assertEqual({(m["month"], m["status"]) for m in s.cashout_months(p)}, {(M1, "reserved"), (M2, "reserved")})
        notes = s.notifications(unread=True)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["details"]["reference"], req["reference"])
        self.assertEqual(notes[0]["details"]["amount"], 1550)
        st = s.cashout_status(p)
        self.assertEqual(st["totals"]["pending"], 1550)
        self.assertEqual(st["amount"], 0)
        self.assertEqual(st["open_request"]["reference"], req["reference"])
        self.assertNotIn("legal_name", st["open_request"])                   # identity details stay with the owner
        self.assertIn("open_request", st["reasons"])

    def test_duplicate_and_changed_requests_are_refused(self):
        s = self.setup_store()
        p = self.player(s, 1)
        with self.assertRaises(StoreError) as caught:
            s.request_cashout(p, "Ade Okafor", DECL, 1500)                   # not the amount the player saw
        self.assertIn("amount_changed", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            s.request_cashout(p, "A", DECL, 1550)
        self.assertIn("legal_name_required", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            s.request_cashout(p, "Ade Okafor", dict(DECL, name_match=False), 1550)
        self.assertIn("declarations_required", str(caught.exception))
        s.request_cashout(p, "Ade Okafor", DECL, 1550)
        with self.assertRaises(StoreError) as caught:
            s.request_cashout(p, "Ade Okafor", DECL, 1550)
        self.assertIn("not_eligible", str(caught.exception))
        self.assertEqual(len(s.cashout_requests(p)), 1)

    # ------------------------------------------------------------------ owner decisions and payment

    def test_only_owners_decide(self):
        s = self.setup_store()
        req = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        for call in (lambda: s.decide_cashout(req["id"], "review", "someone@example.com"),
                     lambda: s.pay_cashout(req["id"], 1550, TODAY.isoformat(), None, "someone@example.com"),
                     lambda: s.fingerprint_cashout(req["id"], "a" * 64, "someone@example.com")):
            with self.assertRaises(StoreError) as caught:
                call()
            self.assertIn("not_owner", str(caught.exception))

    def test_approve_never_pays_and_mark_paid_records_exact_amount_once(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(req["id"], 1550, TODAY.isoformat(), None, OWNER)
        self.assertIn("not_approved", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            s.decide_cashout(req["id"], "approve", OWNER)
        self.assertIn("verification_required", str(caught.exception))
        approved = s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertEqual((approved["status"], approved["approved_by"]), ("approved", OWNER))
        self.assertEqual(s.cashout_payments(), [])                           # approval moved no money
        self.assertEqual(s.cashout_status(p)["totals"]["approved"], 1550)
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(req["id"], 1500, TODAY.isoformat(), None, OWNER)
        self.assertIn("amount_mismatch", str(caught.exception))
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(req["id"], 1550, (TODAY + timedelta(days=3)).isoformat(), None, OWNER)
        self.assertIn("payment_date_in_future", str(caught.exception))
        pay = s.pay_cashout(req["id"], 1550, TODAY.isoformat(), "TRX-001", OWNER)
        self.assertEqual((pay["amount"], pay["recorded_by"], pay["payment_month"]), (1550, OWNER, CUR))
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(req["id"], 1550, TODAY.isoformat(), "TRX-002", OWNER)
        self.assertIn("already_paid", str(caught.exception))
        self.assertEqual(len(s.cashout_payments()), 1)
        self.assertEqual(s.cashout_request(req["id"])["status"], "paid")
        self.assertEqual({m["status"] for m in s.cashout_months(p)}, {"paid"})
        st = s.cashout_status(p)
        self.assertEqual((st["totals"]["paid"], st["amount"], st["totals"]["unpaid"]), (1550, 0, 55))
        self.assertIn("no_earnings", st["reasons"])                          # paid months can never be requested again
        with self.assertRaises(StoreError):
            s.decide_cashout(req["id"], "reject", OWNER, note="too late")      # a paid request is closed

    def test_bank_reference_used_once(self):
        s = self.setup_store()
        first = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        second = s.request_cashout(self.player(s, 2), "Bola Ade", DECL, 1550)
        for req in (first, second):
            s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        s.pay_cashout(first["id"], 1550, TODAY.isoformat(), "TRX-9", OWNER)
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(second["id"], 1550, TODAY.isoformat(), "trx-9", OWNER)
        self.assertIn("duplicate_reference", str(caught.exception))
        self.assertEqual(s.cashout_request(second["id"])["status"], "approved")

    def test_hold_review_and_reject_rules(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        with self.assertRaises(StoreError) as caught:
            s.decide_cashout(req["id"], "hold", OWNER, note="")
        self.assertIn("reason_required", str(caught.exception))
        held = s.decide_cashout(req["id"], "hold", OWNER, note="Bank name differs; asked the player")
        self.assertEqual((held["status"], held["decision_note"]), ("on_hold", "Bank name differs; asked the player"))
        self.assertEqual(s.notifications(unread=True), [])                    # handled
        self.assertEqual(s.decide_cashout(req["id"], "review", OWNER)["status"], "under_review")
        approved = s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(s.decide_cashout(req["id"], "hold", OWNER, note="Recheck")["status"], "on_hold")

    def test_rejection_releases_earnings_unless_disqualified(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        rejected = s.decide_cashout(req["id"], "reject", OWNER, note="Name does not match the bank account")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual({m["status"] for m in s.cashout_months(p)}, {"released"})
        st = s.cashout_status(p)
        self.assertTrue(st["eligible"], st["reasons"])                        # available again for a legitimate request
        self.assertEqual(st["amount"], 1550)
        again = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        s.decide_cashout(again["id"], "reject", OWNER, note="Duplicate account confirmed", disqualify=True)
        self.assertEqual({m["status"] for m in s.cashout_months(p) if m["request_id"] == again["id"]}, {"disqualified"})
        st = s.cashout_status(p)
        self.assertEqual((st["amount"], st["totals"]["refused"], st["totals"]["unpaid"]), (0, 1550, 55))
        with self.assertRaises(StoreError):
            s.decide_cashout(again["id"], "approve", OWNER, beneficiary=True, eligibility=True)

    def test_fingerprint_matches_other_people(self):
        s = self.setup_store()
        first = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        second = s.request_cashout(self.player(s, 2), "Bola Ade", DECL, 1550)
        fp = withdrawals.fingerprint("k" * 40, "058", "0123456789")
        self.assertEqual(s.fingerprint_cashout(first["id"], fp, OWNER), 0)
        self.assertEqual(s.fingerprint_cashout(second["id"], fp, OWNER), 1)
        self.assertEqual(s.cashout_request(second["id"])["bank_fingerprint"], fp)
        with self.assertRaises(StoreError):
            s.fingerprint_cashout(second["id"], "0123456789", OWNER)          # never a raw number

    # ------------------------------------------------------------------ integrity

    def test_records_change_only_through_the_functions(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        attempts = (
            lambda: s.update("reward_cashout_requests", {"id": req["id"]}, {"status": "paid"}),
            lambda: s.update("reward_cashout_requests", {"id": req["id"]}, {"amount": 5000}),
            lambda: s.update("reward_cashout_months", {"request_id": req["id"]}, {"status": "released"}),
            lambda: s.insert("reward_cashout_payments", {"request_id": req["id"], "profile_id": p, "amount": 1550,
                                                         "payment_date": TODAY.isoformat(), "payment_month": CUR,
                                                         "recorded_by": OWNER}),
            lambda: s.delete("reward_cashout_requests", {"id": req["id"]}),
            lambda: s.update("reward_owner_notifications", {"request_id": req["id"]}, {"title": "changed"}),
        )
        for attempt in attempts:
            with self.assertRaises(StoreError):
                attempt()
        self.assertEqual(s.cashout_request(req["id"])["status"], "pending_review")
        note = s.notifications()[0]
        s.mark_notification_read(note["id"], OWNER)                          # read status may change
        self.assertEqual(s.notifications(unread=True), [])

    def test_monthly_review_cannot_pay_a_requested_month(self):
        s = self.setup_store()
        p = self.player(s, 1)
        s.update_account(p, {"verification": "verified"})
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        s.open_payment(p, M1, False, OWNER)
        with self.assertRaises(StoreError) as caught:
            s.update_payment(p, M1, {"status": "approved", "approved_amount": 650}, OWNER)
        self.assertIn("withdrawal", str(caught.exception))
        s.decide_cashout(req["id"], "reject", OWNER, note="Requested by mistake")
        s.update_payment(p, M1, {"status": "approved", "approved_amount": 650}, OWNER)   # released: allowed again
        st = s.cashout_status(p)
        self.assertEqual([m["month"] for m in st["months"]], [M2])            # an approved monthly review excludes M1
        self.assertEqual(st["amount"], 900)

    def test_delivered_defaults_are_off(self):
        s = self.make_store()
        cfg = s.cashout_settings()
        self.assertEqual((cfg["live_requests"], cfg["real_payouts"], list(cfg["owner_emails"])), (False, False, []))

    def test_real_approval_and_payment_need_the_database_payout_switch(self):
        s = self.setup_store(payouts=False)
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        with self.assertRaises(StoreError) as caught:
            s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertIn("payouts_disabled", str(caught.exception))
        self.assertEqual(s.decide_cashout(req["id"], "hold", OWNER, note="Waiting for launch")["status"], "on_hold")
        s.update("reward_cashout_settings", {"id": 1}, {"real_payouts": True})
        s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        s.update("reward_cashout_settings", {"id": 1}, {"real_payouts": False})
        with self.assertRaises(StoreError) as caught:
            s.pay_cashout(req["id"], 1550, TODAY.isoformat(), None, OWNER)
        self.assertIn("payouts_disabled", str(caught.exception))
        self.assertEqual(s.cashout_payments(), [])

    def test_paid_withdrawal_settles_each_month_in_reward_payments_once(self):
        s = self.setup_store()
        p = self.player(s, 1)
        s.open_payment(p, M1, False, OWNER)                                  # an existing monthly review is reused
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        self.assertEqual(s.account(p)["verification"], "verified")           # the owner confirmed eligibility
        s.pay_cashout(req["id"], 1550, TODAY.isoformat(), "TRX-1", OWNER)
        rows = {r["month"]: r for r in s.payments(profile_id=p)}
        self.assertEqual({m: (r["status"], r["paid_amount"], r["reference"]) for m, r in rows.items()},
                         {M1: ("paid", 650, req["reference"]), M2: ("paid", 900, req["reference"])})
        self.assertIn(req["reference"], rows[M1]["remarks"])
        self.assertEqual(s.cashout_status(p)["totals"]["paid"], 1550)         # counted once, not 3,100
        with self.assertRaises(StoreError):                                   # a settled month stays frozen
            s.update_payment(p, M1, {"status": "rejected"}, OWNER)
        events = s.events()
        summary = withdrawals.summary(s.cashout_requests(), s.cashout_payments(), events, s.cashout_months(),
                                      s.payments(), 50000, f"{M1}-01", CUR)
        self.assertEqual(summary["paid_amount"], 1550)
        earning = {r["Earning month"]: r for r in withdrawals.by_earning_month(events, s.cashout_months(),
                                                                                s.cashout_requests(), s.payments())}
        self.assertEqual((earning[M1]["Paid"], earning[M2]["Paid"]), (650, 900))
        cash = withdrawals.by_payment_month(s.cashout_payments(), s.payments())
        self.assertEqual([(r["Payment month"], r["Cash paid"]) for r in cash], [(CUR, 1550)])
        figures = rewards.budget_figures(s.settings(), s.enrolments(M1), s.events(month=M1), s.payments(month=M1))
        self.assertEqual(figures["paid"], 650)                                # the existing Overview sees it too

    def test_notifications_wait_until_handled(self):
        s = self.setup_store()
        first = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        second = s.request_cashout(self.player(s, 2), "Bola Ade", DECL, 1550)
        later = self.reopen(s)                                                 # e.g. the app restarted meanwhile
        unread = later.notifications(unread=True)
        self.assertEqual({n["request_id"] for n in unread}, {first["id"], second["id"]})
        later.decide_cashout(first["id"], "review", OWNER)                     # handling marks it read
        self.assertEqual([n["request_id"] for n in later.notifications(unread=True)], [second["id"]])
        later.mark_notification_read(unread[0]["id"] if unread[0]["request_id"] == second["id"] else unread[1]["id"],
                                     OWNER)
        self.assertEqual(later.notifications(unread=True), [])
        self.assertEqual(len(later.notifications()), 2)                        # kept as history

    def test_test_accounts_simulate_and_stay_isolated(self):
        s = self.setup_store(live=False, payouts=False)
        real = self.player(s, 1, joined_days_ago=5)
        with self.assertRaises(StoreError):
            s.cashout_status(real, as_of=(TODAY + timedelta(days=40)).isoformat())   # simulation: test accounts only
        tester = self.player(s, 2, test=True, joined_days_ago=0)
        self.assertIn("waiting_period", s.cashout_status(tester)["reasons"])
        later = (TODAY + timedelta(days=40)).isoformat()
        st = s.cashout_status(tester, as_of=later)
        self.assertTrue(st["eligible"], st["reasons"])                        # live switch does not apply to tests
        self.assertEqual(st["amount"], 1605)                                  # the current month has closed by then
        req = s.request_cashout(tester, "Owner Test", DECL, 1605, as_of=later)
        self.assertTrue(req["test"])
        s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        pay = s.pay_cashout(req["id"], 1605, later, None, OWNER)
        self.assertTrue(pay["test"])
        real_rows = [r for r in s.cashout_requests() if not r["test"]]
        real_pay = [r for r in s.cashout_payments() if not r["test"]]
        self.assertEqual((real_rows, real_pay), ([], []))
        self.assertEqual(s.notifications()[0]["test"], True)
        s.clear_test_data(OWNER)
        self.assertEqual((s.cashout_requests(), s.cashout_payments(), s.notifications()), ([], [], []))
        self.assertTrue(s.cashout_status(real))                               # real data untouched


class MemoryWithdrawalTests(Scenarios, unittest.TestCase):
    def make_store(self):
        return MemoryStore()

    def reopen(self, s):
        return s                                                              # memory: the same process

    def backdate(self, s, profile, days):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        for e in s.tables["reward_enrolments"]:
            if e["profile_id"] == profile:
                e["created_at"] = stamp

    def test_parallel_requests_one_wins(self):
        s = self.setup_store()
        p = self.player(s, 1)
        results = []

        def go():
            try:
                results.append(s.request_cashout(p, "Ade Okafor", DECL, 1550)["reference"])
            except StoreError as error:
                results.append(str(error))
        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for r in results if r.startswith("WD-")), 1)


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
class SqlWithdrawalTests(Scenarios, unittest.TestCase):
    def make_store(self):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        return pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db())

    def reopen(self, s):
        return pg_harness.PsqlStore(CLUSTER, s.db)                           # a new connection, nothing in memory

    def backdate(self, s, profile, days):
        CLUSTER.psql(s.db, f"update public.reward_enrolments set created_at = now() - interval '{int(days)} days' "
                           f"where profile_id = '{profile}'", "service_role")

    def test_browser_roles_have_no_access(self):
        s = self.setup_store()
        p = self.player(s, 1)
        s.request_cashout(p, "Ade Okafor", DECL, 1550)
        for role in ("anon", "authenticated"):
            for sql in ("select count(*) from public.reward_cashout_requests",
                        "select count(*) from public.reward_cashout_months",
                        "select count(*) from public.reward_cashout_payments",
                        "select count(*) from public.reward_owner_notifications",
                        "select count(*) from public.reward_cashout_settings",
                        f"select public.reward_cashout_status('{p}', null)",
                        "update public.reward_cashout_settings set live_requests = true",
                        "select public.reward_cashout_pay(1, 1550, current_date, null, 'owner@example.com')"):
                with self.assertRaises(StoreError, msg=f"{role}: {sql}"):
                    CLUSTER.psql(s.db, sql, role)
        rls = CLUSTER.psql(s.db, "select bool_and(relrowsecurity) from pg_class where relname in "
                                 "('reward_cashout_settings','reward_cashout_requests','reward_cashout_months',"
                                 "'reward_cashout_payments','reward_owner_notifications')")
        self.assertEqual(rls, "t")

    def test_migration_is_rerunnable_and_keeps_data(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        CLUSTER.psql_file(s.db, pg_harness.MIGRATION)
        CLUSTER.psql_file(s.db, pg_harness.SCHEMA)
        self.assertEqual(s.cashout_request(req["id"])["status"], "pending_review")
        self.assertTrue(s.cashout_settings()["live_requests"])               # settings are not reset
        self.assertEqual(len(s.events(p)), len(s.events(p)))

    def test_audit_log_records_requests_and_payments(self):
        s = self.setup_store()
        req = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        s.pay_cashout(req["id"], 1550, TODAY.isoformat(), None, OWNER)
        actions = [a["action"] for a in s.audit()]
        self.assertIn("reward_cashout_requests_insert", actions)
        self.assertIn("reward_cashout_payments_insert", actions)
        self.assertGreaterEqual(actions.count("reward_cashout_requests_update"), 2)
        with self.assertRaises(StoreError):
            CLUSTER.psql(s.db, "delete from public.reward_audit_log", "service_role")

    def _parallel(self, s, fn, n=6):
        results, stores = [], [pg_harness.PsqlStore(CLUSTER, s.db) for _ in range(n)]

        def go(store):
            try:
                results.append(fn(store))
            except StoreError as error:
                results.append(error)
        threads = [threading.Thread(target=go, args=(x,)) for x in stores]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_simultaneous_requests_one_wins(self):
        s = self.setup_store()
        p = self.player(s, 1)
        results = self._parallel(s, lambda x: x.request_cashout(p, "Ade Okafor", DECL, 1550))
        self.assertEqual(sum(1 for r in results if isinstance(r, dict)), 1)
        self.assertEqual(len(s.cashout_requests(p)), 1)
        self.assertEqual(len(s.cashout_months(p)), 2)

    def test_simultaneous_mark_paid_records_one_payment(self):
        s = self.setup_store()
        req = s.request_cashout(self.player(s, 1), "Ade Okafor", DECL, 1550)
        s.decide_cashout(req["id"], "approve", OWNER, beneficiary=True, eligibility=True)
        results = self._parallel(s, lambda x: x.pay_cashout(req["id"], 1550, TODAY.isoformat(), None, OWNER))
        self.assertEqual(sum(1 for r in results if isinstance(r, dict)), 1)
        self.assertEqual(len(s.cashout_payments()), 1)

    def test_sql_and_python_status_agree(self):
        s = self.setup_store()
        p = self.player(s, 1)
        req = s.request_cashout(p, "Ade Okafor", DECL, 1550)
        s.decide_cashout(req["id"], "reject", OWNER, note="Check", disqualify=False)
        tables = {t: s.select(t) for t in ("reward_enrolments", "reward_activity_events", "reward_cashout_months",
                                            "reward_payments", "reward_cashout_requests", "reward_cashout_payments")}
        expected = withdrawals.status(s.account(p), s.cashout_settings(), tables["reward_enrolments"],
                                      tables["reward_activity_events"], tables["reward_cashout_months"],
                                      tables["reward_payments"], tables["reward_cashout_requests"],
                                      tables["reward_cashout_payments"])
        got = s.cashout_status(p)
        for key in ("eligible", "reasons", "amount", "months", "joined_on", "eligible_on", "days_left", "totals"):
            self.assertEqual(got[key], expected[key], key)


if __name__ == "__main__":
    unittest.main()
