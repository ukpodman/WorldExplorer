"""Friends & Family 10: provisional rewards for the private pilot.

The same scenarios run against the in-memory store (core/rewards_store.MemoryStore) and, when PostgreSQL is
installed, against the real SQL (supabase/friends_family10_migration.sql) in a throwaway local database, so the app's
rules and the database's rules cannot drift apart. Pure calculation tests (tiers, caps, allocation, rounding) run on
core/pilot_rewards.py directly.
"""
import sys
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import pilot_rewards as pr  # noqa: E402
from core import rewards  # noqa: E402
from core.rewards import LAGOS, Settings  # noqa: E402
from core.rewards_store import MemoryStore, StoreError  # noqa: E402
import pg_harness  # noqa: E402

OWNER = "owner@example.com"
TERMS = "2026-11-05#test0000000000000"
CUR = rewards.month_key()
LAST = rewards.previous_month(CUR)          # an ended month: it can be settled
EARLIER = rewards.previous_month(LAST)
CLUSTER = None


def setUpModule():
    global CLUSTER
    if pg_harness.available() and pg_harness.PILOT.exists() and pg_harness.FF10.exists():
        try:
            CLUSTER = pg_harness.Cluster()
        except Exception as error:  # pragma: no cover
            print("local PostgreSQL could not start:", error)


def tearDownModule():
    if CLUSTER:
        CLUSTER.stop()


def pid(n):
    return f"{n:064x}"


def when(day: str, hour=9, minute=0, second=0) -> datetime:
    """A moment on a Lagos calendar day."""
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hour, minute, second, tzinfo=LAGOS)


def rows(*specs):
    """Pure-engine activity rows: (kind, subject, datetime)."""
    return [{"kind": k, "subject": s, "at": t.isoformat(), "day": pr.lagos_day(t), "detail": None} for k, s, t in specs]


# ============================================================================ pure calculations

class TierTests(unittest.TestCase):
    def test_tier_table_is_cumulative_and_each_tier_needs_the_ones_below(self):
        self.assertEqual(pr.tier_for(14, 5, 3, True), 0)            # under 15 minutes: ₦0 whatever else
        self.assertEqual(pr.tier_for(15, 0, 0, False), 0)           # 15 minutes but no quiz
        self.assertEqual(pr.tier_for(15, 1, 0, False), 1)
        self.assertEqual(pr.tier_for(30, 1, 0, False), 1)           # 30 minutes needs a second quiz
        self.assertEqual(pr.tier_for(30, 2, 0, False), 2)
        self.assertEqual(pr.tier_for(45, 2, 0, False), 2)           # 45 minutes needs a new country
        self.assertEqual(pr.tier_for(45, 2, 1, False), 3)
        self.assertEqual(pr.tier_for(60, 2, 1, False), 3)           # 60 minutes needs the Daily Challenge
        self.assertEqual(pr.tier_for(60, 2, 1, True), 4)
        self.assertEqual(pr.tier_for(60, 1, 1, True), 1)            # a missing lower milestone caps the tier
        self.assertEqual(pr.tier_for(600, 9, 9, True), 4)           # beyond 60 minutes: still the top tier
        self.assertEqual([pr.tier_amount(t) for t in range(5)], [0, 100, 250, 350, 500])

    def test_daily_amounts_are_totals_not_added_together(self):
        self.assertEqual(max(pr.tier_amount(t) for t in range(5)), pr.DAILY_MAX)

    def test_next_milestones(self):
        self.assertEqual(pr.next_milestones(None), ["15 more minutes of active learning", "1 more qualifying quiz"])
        top = pr.DaySummary("2026-09-01", 3600, 60, 2, True, 1, 50, 50, 4, 500)
        self.assertEqual(pr.next_milestones(top), [])
        three = pr.DaySummary("2026-09-01", 2700, 45, 2, False, 1, 30, 30, 3, 350)
        self.assertEqual(pr.next_milestones(three), ["15 more minutes of active learning",
                                                     "complete today's Daily Challenge"])


class ActiveTimeTests(unittest.TestCase):
    def test_gaps_count_up_to_the_inactivity_limit(self):
        d = "2026-09-01"
        r = rows(("view", "a", when(d, 9, 0)), ("view", "b", when(d, 9, 2)), ("view", "c", when(d, 9, 30)))
        self.assertEqual(pr.active_seconds(r), 120 + pr.INACTIVITY_SECONDS)   # the 28-minute pause counts 3 minutes

    def test_a_single_interaction_or_an_open_page_counts_nothing(self):
        self.assertEqual(pr.active_seconds(rows(("view", "a", when("2026-09-01")))), 0)
        self.assertEqual(pr.active_seconds([]), 0)

    def test_overlapping_tabs_never_count_twice(self):
        d = "2026-09-01"
        tab_a = [("view", f"a{i}", when(d, 9, i)) for i in range(0, 31)]
        tab_b = [("answer", f"b{i}", when(d, 9, i, 30)) for i in range(0, 30)]
        self.assertEqual(pr.active_seconds(rows(*tab_a)), 30 * 60)
        self.assertEqual(pr.active_seconds(rows(*(tab_a + tab_b))), 30 * 60)   # same half hour, counted once

    def test_repeating_the_same_action_is_ignored(self):
        d = "2026-09-01"
        history = rows(("country", "NGA", when(d, 9, 0)))
        self.assertFalse(pr.accept(history, "country", "NGA", when(d, 9, 9, 59)))   # within 10 minutes
        self.assertTrue(pr.accept(history, "country", "NGA", when(d, 9, 10)))
        self.assertTrue(pr.accept(history, "country", "GHA", when(d, 9, 1)))        # a different country
        self.assertFalse(pr.accept(history, "refresh", "x", when(d, 9, 1)))        # unknown kinds never count
        self.assertFalse(pr.accept(history, "view", "  ", when(d, 9, 1)))

    def test_days_follow_the_lagos_calendar(self):
        late = when("2026-09-01", 23, 59)
        early = when("2026-09-02", 0, 1)
        days = pr.day_summaries(rows(("view", "a", late), ("view", "b", early)))
        self.assertEqual([d.day for d in days], ["2026-09-01", "2026-09-02"])
        self.assertEqual([d.seconds for d in days], [0, 0])                 # no time is carried over midnight


class AllocationTests(unittest.TestCase):
    def test_within_budget_everybody_keeps_their_amount_and_the_rest_is_unspent(self):
        prov = {pid(1): 7000, pid(2): 1000, pid(3): 0}
        self.assertEqual(pr.allocate(prov), prov)
        preview = pr.settlement_preview({}, LAST)
        self.assertEqual((preview["total_final"], preview["unspent"]), (0, 50_000))

    def test_ten_participants_at_7000_get_5000_each(self):
        prov = {pid(n): 7000 for n in range(1, 11)}
        self.assertEqual(set(pr.allocate(prov).values()), {5000})

    def test_proportional_shares_with_exact_whole_naira_rounding(self):
        prov = {pid(1): 7000, pid(2): 6999, pid(3): 6998, pid(4): 7000, pid(5): 7000, pid(6): 7000, pid(7): 7000,
                pid(8): 3333, pid(9): 7000, pid(10): 1}
        final = pr.allocate(prov)
        self.assertEqual(sum(final.values()), 50_000)                       # exactly the budget, never more
        for p, v in prov.items():
            self.assertLessEqual(final[p], v)
            exact = v * 50_000 / sum(prov.values())
            self.assertLess(abs(final[p] - exact), 1)                       # within one naira of the exact share
        self.assertEqual(final, pr.allocate(dict(reversed(list(prov.items())))))   # deterministic

    def test_ties_are_broken_by_profile_id(self):
        prov = {pid(n): 7000 for n in range(1, 4)}
        final = pr.allocate(prov, budget=10_000)                            # 3333.33 each: one extra naira
        self.assertEqual([final[pid(n)] for n in range(1, 4)], [3334, 3333, 3333])

    def test_no_one_receives_more_than_7000(self):
        self.assertEqual(pr.allocate({pid(1): 9000}), {pid(1): 7000})


# ============================================================================ store scenarios (memory + SQL)

class Scenarios:
    def make_store(self):
        raise NotImplementedError

    def record_at(self, s, profile, kind, subject, at, detail=None):
        """Record with a chosen time (tests only; the app always uses the database clock)."""
        raise NotImplementedError

    # ---- helpers
    def store(self):
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{EARLIER}-01"), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER]})
        s.set_participation_terms("pilot", TERMS, OWNER)
        s.set_pilot(True, OWNER, confirmed=True)
        return s

    def participant(self, s, n, approve=True, test=False):
        email = f"p{n}@example.com"
        s.ensure_account(pid(n), email, f"Player {n}", True, test)
        if test:
            return pid(n)
        s.invite(email, OWNER)
        app = s.apply_founding(pid(n), "Lagos", None, True, True, True, terms_version=TERMS)
        if approve:
            s.decide_founding(app["id"], "approve", OWNER)
        return pid(n)

    def record_many(self, s, p, specs):
        for kind, subject, at, detail in specs:
            self.record_at(s, p, kind, subject, at, detail)

    def learn(self, s, p, day, minutes, quizzes=0, new_countries=0, challenge=False, start=9, tag=""):
        """A learning session: one interaction a minute for `minutes` minutes, with the milestones inside it."""
        t0 = when(day, start)
        specs = [("view", f"{tag}{day}:{start}:{i}", t0 + timedelta(minutes=i), None) for i in range(minutes + 1)]
        specs += [("quiz", f"{tag}quiz:{day}:{start}:{q}", t0 + timedelta(minutes=1, seconds=q),
                   {"questions": 10, "avg_seconds": 6.5}) for q in range(quizzes)]
        specs += [("country", f"{tag}{day}:{start}:C{c}", t0 + timedelta(minutes=2, seconds=c), None)
                  for c in range(new_countries)]
        if challenge:
            specs.append(("challenge", f"daily:{day}", t0 + timedelta(minutes=3), None))
        self.record_many(s, p, specs)

    def top_day(self, s, p, day, tag=""):
        self.learn(s, p, day, 60, quizzes=2, new_countries=1, challenge=True, tag=tag)

    def ledger(self, s, p, month=LAST):
        return {str(d["day"])[:10]: d for d in s.ff10_ledger(p, month)}

    def raises(self, reason, fn, *args, **kwargs):
        with self.assertRaises(StoreError) as caught:
            fn(*args, **kwargs)
        self.assertIn(reason, str(caught.exception))

    # ---- 1. at most 10 approved participants
    def test_at_most_ten_approved_participants(self):
        s = self.store()
        for n in range(1, 11):
            self.participant(s, n)
        self.participant(s, 11, approve=False)
        app = s.founding_application(pid(11))
        self.raises("places_full", s.decide_founding, app["id"], "approve", OWNER)
        s.decide_founding(app["id"], "waitlist", OWNER)                     # the waiting list still works
        first = s.founding_application(pid(1))
        s.decide_founding(first["id"], "reject", OWNER, "Left the pilot")  # a place is freed
        s.decide_founding(app["id"], "approve", OWNER)
        self.assertEqual(sum(1 for a in s.founding_applications("approved") if not a["test"]), 10)

    # ---- 2. invitation-only access and approved participants only
    def test_only_invited_and_approved_participants_are_recorded(self):
        s = self.store()
        s.ensure_account(pid(1), "stranger@example.com", "Stranger", True, False)
        self.raises("not_invited", s.apply_founding, pid(1), "Lagos", None, True, True, True, terms_version=TERMS)
        self.raises("not_participant", self.record_at, s, pid(1), "view", "x", when(LAST + "-03"))
        pending = self.participant(s, 2, approve=False)
        self.raises("not_participant", self.record_at, s, pending, "view", "x", when(LAST + "-03"))
        p = self.participant(s, 3)
        self.assertIsNotNone(self.record_at(s, p, "view", "x", when(LAST + "-03")))
        s.set_pilot(False, OWNER)                                          # pilot switched off: nothing recorded
        self.raises("pilot_closed", self.record_at, s, p, "view", "y", when(LAST + "-03", 10))

    def test_test_accounts_are_recorded_as_test_and_never_settled(self):
        s = self.store()
        t = self.participant(s, 9, test=True)
        self.top_day(s, t, LAST + "-04")
        self.assertTrue(all(r["test"] for r in s.ff10_activity(t)))
        self.assertEqual(s.ff10_preview(LAST)["lines"], [])

    def test_unknown_kinds_and_empty_subjects_are_refused(self):
        s = self.store()
        p = self.participant(s, 1)
        self.raises("invalid_activity", self.record_at, s, p, "page_open", "x", when(LAST + "-03"))
        self.raises("invalid_activity", self.record_at, s, p, "view", " ", when(LAST + "-03"))

    # ---- 3. daily earning calculations (cumulative tiers)
    def test_daily_tiers(self):
        s = self.store()
        p = self.participant(s, 1)
        self.learn(s, p, LAST + "-01", 14, quizzes=3, new_countries=2, challenge=True)   # under 15 minutes
        self.learn(s, p, LAST + "-02", 15, quizzes=1)
        self.learn(s, p, LAST + "-03", 30, quizzes=2)
        self.learn(s, p, LAST + "-04", 45, quizzes=2, new_countries=1)
        self.top_day(s, p, LAST + "-05")
        self.learn(s, p, LAST + "-06", 90, quizzes=1, new_countries=1, challenge=True)   # long, one quiz only
        got = {d: (r["minutes"], r["tier"], r["amount"]) for d, r in self.ledger(s, p).items()}
        self.assertEqual(got, {LAST + "-01": (14, 0, 0), LAST + "-02": (15, 1, 100), LAST + "-03": (30, 2, 250),
                               LAST + "-04": (45, 3, 350), LAST + "-05": (60, 4, 500), LAST + "-06": (90, 1, 100)})

    def test_new_country_means_never_explored_before(self):
        s = self.store()
        p = self.participant(s, 1)
        self.learn(s, p, LAST + "-01", 45, quizzes=2, new_countries=1, tag="a")
        self.record_at(s, p, "country", f"a{LAST}-01:9:C0", when(LAST + "-02", 8))   # the same country again
        self.learn(s, p, LAST + "-02", 45, quizzes=2)
        days = self.ledger(s, p)
        self.assertEqual((days[LAST + "-01"]["new_countries"], days[LAST + "-01"]["tier"]), (1, 3))
        self.assertEqual((days[LAST + "-02"]["new_countries"], days[LAST + "-02"]["tier"]), (0, 2))

    # ---- 4. active-learning verification
    def test_idle_time_refreshes_and_repeats_add_nothing(self):
        s = self.store()
        p = self.participant(s, 1)
        day = LAST + "-07"
        self.record_at(s, p, "quiz", "q1", when(day, 9, 0))
        self.record_at(s, p, "view", "NGA", when(day, 9, 1))
        self.assertIsNone(self.record_at(s, p, "view", "NGA", when(day, 9, 4)))    # the same again: ignored
        self.assertIsNone(self.record_at(s, p, "view", "NGA", when(day, 9, 7)))
        self.record_at(s, p, "view", "GHA", when(day, 11, 0))                    # two hours idle in between
        r = self.ledger(s, p)[day]
        self.assertEqual(r["seconds"], 60 + pr.INACTIVITY_SECONDS)
        self.assertEqual((r["minutes"], r["amount"]), (4, 0))
        self.assertEqual(len(s.ff10_activity(p)), 3)

    def test_two_tabs_at_once_count_once(self):
        s = self.store()
        p = self.participant(s, 1)
        day = LAST + "-08"
        self.learn(s, p, day, 20, quizzes=1, tag="tab1-")
        self.learn(s, p, day, 20, tag="tab2-")                                     # the same 20 minutes again
        self.assertEqual(self.ledger(s, p)[day]["minutes"], 20)

    def test_activity_time_comes_from_the_database_clock(self):
        s = self.store()
        p = self.participant(s, 1)
        row = s.ff10_record(p, "view", "NGA")
        stamp = rewards._dt(row["at"])
        self.assertLess(abs((stamp - datetime.now(LAGOS)).total_seconds()), 120)
        self.assertEqual(str(row["day"])[:10], rewards.day_key())
        self.assertIsNone(s.ff10_record(p, "view", "NGA"))                       # an immediate repeat is ignored

    # ---- 5. ₦500 per day and 6. ₦7,000 per month
    def test_daily_maximum_and_monthly_maximum(self):
        s = self.store()
        p = self.participant(s, 1)
        for d in range(1, 16):                                                   # 15 top days = ₦7,500 uncapped
            self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"d{d}-")
        days = self.ledger(s, p)
        self.assertTrue(all(r["amount"] <= 500 for r in days.values()))
        self.assertEqual([days[f"{LAST}-{d:02d}"]["amount"] for d in (13, 14, 15)], [500, 500, 0])
        self.assertEqual(sum(r["amount"] for r in days.values()), 7000)
        self.assertEqual(s.ff10_preview(LAST)["lines"][0]["provisional"], 7000)

    def test_monthly_maximum_cuts_the_last_day_partially(self):
        s = self.store()
        p = self.participant(s, 1)
        for d in range(1, 14):
            self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"d{d}-")                    # 13 × ₦500 = ₦6,500
        self.learn(s, p, f"{LAST}-14", 45, quizzes=2, new_countries=1, tag="x")   # ₦350 → ₦6,850
        self.top_day(s, p, f"{LAST}-15", tag="y")                                  # ₦500 → ₦150 left
        days = self.ledger(s, p)
        self.assertEqual((days[f"{LAST}-14"]["amount"], days[f"{LAST}-15"]["amount"]), (350, 150))
        self.assertEqual(sum(r["amount"] for r in days.values()), 7000)

    # ---- 7, 8, 9, 12, 13. shared budget, proportional allocation, rounding, zero activity, unused budget
    def test_ten_full_participants_share_50000(self):
        s = self.store()
        for n in range(1, 11):
            p = self.participant(s, n)
            for d in range(1, 15):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")
        preview = s.ff10_preview(LAST)
        self.assertEqual((preview["total_provisional"], preview["total_final"], preview["scaled"]), (70000, 50000, True))
        self.assertEqual({line["final"] for line in preview["lines"]}, {5000})

    def test_unequal_engagement_rounding_and_zero_activity(self):
        s = self.store()
        people = [self.participant(s, n) for n in range(1, 6)]
        plan = {0: 14, 1: 14, 2: 14, 3: 14, 4: 13}            # 4 × ₦7,000 + ₦6,500 = ₦34,500 (within budget)
        for i, days in plan.items():
            for d in range(1, days + 1):
                self.top_day(s, people[i], f"{LAST}-{d:02d}", tag=f"{i}-{d}-")
        zero = self.participant(s, 6)                         # approved, no activity: not in the settlement
        preview = s.ff10_preview(LAST)
        self.assertEqual((preview["total_final"], preview["unspent"], preview["scaled"]), (34500, 15500, False))
        self.assertNotIn(zero, [line["profile_id"] for line in preview["lines"]])
        extra = [self.participant(s, n) for n in (7, 8)]      # two more full participants: ₦48,500 → over budget
        for i, p in enumerate(extra):
            for d in range(1, 15):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"x{i}-{d}-")
        preview = s.ff10_preview(LAST)
        self.assertEqual((preview["total_provisional"], preview["total_final"], preview["unspent"]), (48500, 48500, 1500))
        self.learn(s, people[4], f"{LAST}-20", 45, quizzes=2, new_countries=1, tag="more")   # +₦350 → +₦500 cap
        self.top_day(s, people[4], f"{LAST}-21", tag="more2")
        preview = s.ff10_preview(LAST)
        lines = {line["profile_id"]: line for line in preview["lines"]}
        self.assertEqual(preview["total_provisional"], 49000)
        self.assertEqual(lines[people[4]]["final"], 7000)
        self.assertFalse(preview["scaled"])

    def test_over_budget_allocation_matches_the_python_rule_exactly(self):
        s = self.store()
        amounts = {}
        for n in range(1, 11):
            p = self.participant(s, n)
            for d in range(1, 11 + (n % 4)):                     # 10..13 top days: ₦5,000..₦6,500
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")
            self.learn(s, p, f"{LAST}-20", 15, quizzes=1, tag=f"{n}-e")   # +₦100: uneven totals
            amounts[p] = 500 * (10 + n % 4) + 100
        preview = s.ff10_preview(LAST)
        self.assertEqual(preview["total_provisional"], sum(amounts.values()))
        self.assertTrue(preview["scaled"])
        self.assertEqual({line["profile_id"]: line["final"] for line in preview["lines"]}, pr.allocate(amounts))
        self.assertEqual(preview["total_final"], 50000)

    # ---- 10, 11, 14. settlement: immutable, once, exactly as previewed, owner approval
    def settled(self, s):
        p1, p2 = self.participant(s, 1), self.participant(s, 2)
        self.top_day(s, p1, LAST + "-02")
        self.learn(s, p2, LAST + "-02", 15, quizzes=1)
        preview = s.ff10_preview(LAST)
        s.ff10_settle(LAST, OWNER, preview["fingerprint"], confirmed=True)
        return p1, p2

    def test_settlement_needs_the_owner_confirmation_an_ended_month_and_the_previewed_allocation(self):
        s = self.store()
        p = self.participant(s, 1)
        self.top_day(s, p, LAST + "-02")
        fp = s.ff10_preview(LAST)["fingerprint"]
        self.raises("not_owner", s.ff10_settle, LAST, "someone@example.com", fp, True)
        self.raises("confirmation_required", s.ff10_settle, LAST, OWNER, fp, False)
        self.raises("month_not_ended", s.ff10_settle, CUR, OWNER, fp, True)
        self.raises("preview_changed", s.ff10_settle, LAST, OWNER, "0" * 64, True)       # forged
        self.raises("preview_changed", s.ff10_settle, LAST, OWNER, "", True)             # missing
        row = s.ff10_settle(LAST, OWNER, fp, confirmed=True)
        self.assertEqual((row["total_final"], row["total_provisional"], row["budget"]), (500, 500, 50000))
        self.assertEqual(row["fingerprint"], fp)                                         # what the owner confirmed
        self.raises("already_settled", s.ff10_settle, LAST, OWNER, fp, True)

    # ---- settlement integrity: the complete allocation, not only the total
    def test_fingerprint_is_the_same_in_the_database_and_in_python(self):
        s = self.store()
        for n in (1, 2, 3):
            p = self.participant(s, n)
            for d in range(1, 13 + n):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")
        preview = s.ff10_preview(LAST)
        self.assertRegex(preview["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(preview["fingerprint"], pr.fingerprint(LAST, preview["budget"], preview["total_provisional"],
                                                                preview["total_final"], preview["lines"]))

    def test_regression_changed_individual_allocations_with_the_same_total_over_budget(self):
        """Over budget the final total is always ₦50,000: excluding one participant's day changes every share but
        not the total. The old preview must be refused."""
        s = self.store()
        people = [self.participant(s, n) for n in range(1, 9)]
        for n, p in enumerate(people):
            for d in range(1, 15):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")                 # 8 × ₦7,000 = ₦56,000
        before = s.ff10_preview(LAST)
        s.ff10_review_day(people[0], LAST + "-03", True, OWNER, "Automated pattern")
        after = s.ff10_preview(LAST)
        self.assertEqual((before["total_final"], after["total_final"]), (50000, 50000))  # the same total…
        self.assertNotEqual([x["final"] for x in before["lines"]], [x["final"] for x in after["lines"]])
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])                  # …a different allocation
        self.raises("preview_changed", s.ff10_settle, LAST, OWNER, before["fingerprint"], True)
        self.assertEqual(s.ff10_settlements(), [])
        s.ff10_settle(LAST, OWNER, after["fingerprint"], confirmed=True)
        self.assertEqual({x["profile_id"]: x["final"] for x in s.ff10_lines(LAST)},
                         {x["profile_id"]: x["final"] for x in after["lines"]})

    def test_regression_amounts_moved_between_participants_within_budget(self):
        """Within budget: one participant loses ₦250, another gains ₦250 — same provisional and final totals."""
        s = self.store()
        a, b = self.participant(s, 1), self.participant(s, 2)
        self.learn(s, a, LAST + "-02", 30, quizzes=2, tag="a")                       # ₦250
        self.learn(s, b, LAST + "-02", 15, quizzes=1, tag="b")                       # ₦100
        before = s.ff10_preview(LAST)
        s.ff10_review_day(a, LAST + "-02", True, OWNER, "Shared account")             # a: ₦0
        self.learn(s, b, LAST + "-03", 30, quizzes=2, tag="b2")                      # b: ₦350
        after = s.ff10_preview(LAST)
        self.assertEqual((before["total_provisional"], before["total_final"]), (350, 350))
        self.assertEqual((after["total_provisional"], after["total_final"]), (350, 350))
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.raises("preview_changed", s.ff10_settle, LAST, OWNER, before["fingerprint"], True)

    def test_day_review_racing_a_settlement_never_both_succeed(self):
        s = self.store()
        people = [self.participant(s, n) for n in (1, 2, 3)]
        for n, p in enumerate(people):
            for d in range(1, 3):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")
        fp = s.ff10_preview(LAST)["fingerprint"]
        results = {}

        def settle():
            try:
                s.ff10_settle(LAST, OWNER, fp, confirmed=True)
                results["settle"] = "ok"
            except StoreError as error:
                results["settle"] = str(error)

        def review():
            try:
                s.ff10_review_day(people[1], LAST + "-01", True, OWNER, "Late review")
                results["review"] = "ok"
            except StoreError as error:
                results["review"] = str(error)

        threads = [threading.Thread(target=settle), threading.Thread(target=review)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if results["settle"] == "ok":
            self.assertIn("month_settled", results["review"])
            self.assertEqual(s.ff10_lines(LAST, people[1])[0]["provisional"], 1000)
        else:
            self.assertIn("preview_changed", results["settle"])
            self.assertEqual(results["review"], "ok")
            self.assertEqual(s.ff10_settlements(), [])

    # ---- invitation-only, independently of Public Rewards
    def matrix_case(self, pilot_on, public_on, invited, approved):
        s = self.store()                                   # pilot ON, invitation-only ON, pilot terms recorded
        s.set_participation_terms("public", rewards.TERMS_VERSION, OWNER)
        p = self.participant(s, 1, approve=approved)
        if not invited:
            s.revoke_invitation("p1@example.com", OWNER)    # the approval (or application) stays; the invitation goes
        if public_on:
            s.set_public(True, OWNER, confirmed=True)
        if not pilot_on:
            s.set_pilot(False, OWNER)
        try:
            return self.record_at(s, p, "view", "NGA", when(LAST + "-05")) is not None
        except StoreError as error:
            self.assertTrue(any(r in str(error) for r in ("pilot_closed", "not_participant")), str(error))
            return False

    def test_invitation_matrix_pilot_public_invited_approved(self):
        import itertools
        for pilot_on, public_on, invited, approved in itertools.product((True, False), repeat=4):
            with self.subTest(pilot_on=pilot_on, public_on=public_on, invited=invited, approved=approved):
                self.assertEqual(self.matrix_case(pilot_on, public_on, invited, approved),
                                 pilot_on and invited and approved)

    def test_public_programme_stays_separate_from_the_pilot(self):
        """Public Rewards ON with public applications allowed: an uninvited public participant is approved under the
        public programme (not limited by the 10 pilot places) but never enters the pilot; invited pilot members still
        need one of the 10 pilot places."""
        s = self.store()
        for n in range(1, 11):
            self.participant(s, n)                                                       # 10 pilot members
        s.set_participation_terms("public", rewards.TERMS_VERSION, OWNER)
        s.set_public(True, OWNER, confirmed=True)
        s.set_invitation_only(False, OWNER, confirmed=True)
        s.ensure_account(pid(20), "public@example.com", "Public Player", True, False)
        app = s.apply_founding(pid(20), "Lagos", None, True, True, True, terms_version=rewards.TERMS_VERSION)
        self.assertEqual(s.decide_founding(app["id"], "approve", OWNER)["status"], "approved")
        self.raises("not_participant", self.record_at, s, pid(20), "view", "NGA", when(LAST + "-05"))
        self.participant(s, 11, approve=False)                                           # an 11th invited person
        eleventh = s.founding_application(pid(11))
        self.raises("places_full", s.decide_founding, eleventh["id"], "approve", OWNER)
        self.assertIsNotNone(self.record_at(s, pid(1), "view", "NGA", when(LAST + "-05")))

    # ---- acceptance of the current approved private terms
    def test_new_terms_must_be_accepted_before_earning_again(self):
        s = self.store()
        p = self.participant(s, 1)                                   # applied with the recorded terms: accepted
        self.assertTrue(s.ff10_terms_accepted(p))
        self.assertIsNotNone(self.record_at(s, p, "view", "NGA", when(LAST + "-05")))
        s.set_participation_terms("pilot", "2026-12-01#new0000000000000", OWNER)    # the owner records new terms
        self.assertFalse(s.ff10_terms_accepted(p))
        self.raises("not_participant", self.record_at, s, p, "view", "GHA", when(LAST + "-05", 10))
        self.raises("not_participant", s.ff10_verify_beneficiary, p, "Player One", "Bank", "1234", OWNER, True)
        self.raises("terms_outdated", s.ff10_accept_terms, p, TERMS)                  # the old version
        row = s.ff10_accept_terms(p, "2026-12-01#new0000000000000")
        self.assertEqual(row["terms_version"], "2026-12-01#new0000000000000")
        self.assertTrue(s.ff10_terms_accepted(p))
        self.assertIsNotNone(self.record_at(s, p, "view", "GHA", when(LAST + "-05", 11)))
        s.ff10_accept_terms(p, "2026-12-01#new0000000000000")                        # accepting again is harmless
        self.assertIn("pilot_terms_accepted", [a["action"] for a in s.audit()])
        with self.assertRaises(StoreError):
            s.delete("pilot_terms_acceptances", {"profile_id": p})

    def test_only_approved_invited_participants_can_accept(self):
        s = self.store()
        pending = self.participant(s, 1, approve=False)
        self.raises("not_participant", s.ff10_accept_terms, pending, TERMS)
        p = self.participant(s, 2)
        s.revoke_invitation("p2@example.com", OWNER)
        self.raises("not_participant", s.ff10_accept_terms, p, TERMS)

    def test_revoking_an_invitation_stops_recording_at_once(self):
        s = self.store()
        p = self.participant(s, 1)
        self.assertIsNotNone(self.record_at(s, p, "view", "NGA", when(LAST + "-05")))
        s.revoke_invitation("p1@example.com", OWNER)
        self.raises("not_participant", self.record_at, s, p, "view", "GHA", when(LAST + "-05", 10))
        self.assertEqual(s.founding_application(p)["status"], "approved")                # the decision is unchanged

    def test_settled_amounts_never_change(self):
        s = self.store()
        p1, p2 = self.settled(s)
        lines = {line["profile_id"]: line for line in s.ff10_lines(LAST)}
        self.assertEqual((lines[p1]["final"], lines[p2]["final"]), (500, 100))
        self.assertTrue(all(line["status"] == "pending_review" for line in lines.values()))
        self.raises("month_settled", self.record_at, s, p1, "view", "late", when(LAST + "-28"))
        self.raises("month_settled", s.ff10_review_day, p1, LAST + "-02", True, OWNER, "late change")
        with self.assertRaises(StoreError):
            s.update("pilot_settlement_lines", {"month": LAST, "profile_id": p1}, {"final": 7000})
        with self.assertRaises(StoreError):
            s.update("pilot_settlement_lines", {"month": LAST, "profile_id": p1}, {"status": "approved"})
        with self.assertRaises(StoreError):
            s.delete("pilot_settlements", {"month": LAST})
        with self.assertRaises(StoreError):
            s.update("pilot_activity", {"profile_id": p1}, {"subject": "changed"})
        self.assertEqual(s.ff10_lines(LAST, p1)[0]["final"], 500)

    def test_owner_approval_of_each_line(self):
        s = self.store()
        p1, p2 = self.settled(s)
        self.raises("not_owner", s.ff10_decide, LAST, p1, "approve", "someone@example.com")
        self.raises("reason_required", s.ff10_decide, LAST, p2, "withhold", OWNER)
        self.assertEqual(s.ff10_decide(LAST, p1, "approve", OWNER)["status"], "approved")
        self.assertEqual(s.ff10_decide(LAST, p2, "withhold", OWNER, "Suspicious pattern")["status"], "withheld")
        self.raises("no_change", s.ff10_decide, LAST, p1, "approve", OWNER)
        self.raises("reason_required", s.ff10_decide, LAST, p2, "approve", OWNER)   # reversing needs a reason
        self.assertEqual(s.ff10_decide(LAST, p2, "approve", OWNER, "Checked with the participant")["status"],
                         "approved")
        actions = [a["action"] for a in s.audit()]
        self.assertIn("pilot_settled", actions)
        self.assertIn("pilot_line_withheld", actions)

    def test_excluded_days_earn_nothing_and_free_the_monthly_maximum(self):
        s = self.store()
        p = self.participant(s, 1)
        self.top_day(s, p, LAST + "-02")
        self.top_day(s, p, LAST + "-03", tag="b")
        self.raises("reason_required", s.ff10_review_day, p, LAST + "-02", True, OWNER)
        self.raises("not_owner", s.ff10_review_day, p, LAST + "-02", True, "x@example.com", "no")
        s.ff10_review_day(p, LAST + "-02", True, OWNER, "Very fast answers")
        days = self.ledger(s, p)
        self.assertEqual((days[LAST + "-02"]["amount"], days[LAST + "-02"]["excluded"]), (0, True))
        self.assertEqual(s.ff10_preview(LAST)["total_provisional"], 500)
        s.ff10_review_day(p, LAST + "-02", False, OWNER)                           # restored
        self.assertEqual(s.ff10_preview(LAST)["total_provisional"], 1000)

    # ---- 10, 11. duplicates and concurrency
    def test_concurrent_identical_interactions_are_recorded_once(self):
        s = self.store()
        p = self.participant(s, 1)
        moment = when(LAST + "-09", 10)
        results = []

        def go():
            try:
                results.append(self.record_at(s, p, "quiz", "round-77", moment))
            except StoreError as error:
                results.append(error)

        threads = [threading.Thread(target=go) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for r in results if isinstance(r, dict) and r.get("id") is not None), 1)
        self.assertEqual(len([r for r in s.ff10_activity(p) if r["kind"] == "quiz"]), 1)

    def test_concurrent_settlements_finalise_once(self):
        s = self.store()
        p = self.participant(s, 1)
        self.top_day(s, p, LAST + "-02")
        fp = s.ff10_preview(LAST)["fingerprint"]
        outcomes = []

        def go():
            try:
                outcomes.append(s.ff10_settle(LAST, OWNER, fp, confirmed=True)["month"])
            except StoreError as error:
                outcomes.append(str(error))

        threads = [threading.Thread(target=go) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(outcomes.count(LAST), 1, outcomes)
        self.assertEqual(sum("already_settled" in o for o in outcomes), 3, outcomes)
        self.assertEqual(len(s.ff10_lines(LAST)), 1)

    # ---- 15, 16. public rewards stay OFF; real cash payments only through the private-pilot mechanism
    def approved_line(self, s, verify=True):
        p1, p2 = self.settled(s)
        s.ff10_decide(LAST, p1, "approve", OWNER)
        if verify:
            s.ff10_verify_beneficiary(p1, "Player One", "Example Bank", "4321", OWNER, confirmed=True)
        return p1, p2

    def pay(self, s, p, amount=None, ref="TRF-0001", day=None, confirmed=True, actor=OWNER):
        amount = s.ff10_lines(LAST, p)[0]["final"] if amount is None else amount
        return s.ff10_record_payment(LAST, p, amount, day or rewards.day_key(), ref, actor, confirmed)

    def test_payments_need_the_owners_authorisation_and_public_stays_off(self):
        s = self.store()
        p1, _ = self.approved_line(s)
        self.raises("payments_disabled", self.pay, s, p1)
        self.raises("not_owner", s.ff10_set_payments, True, "someone@example.com", True)
        self.raises("confirmation_required", s.ff10_set_payments, True, OWNER, False)
        self.assertTrue(s.ff10_set_payments(True, OWNER, confirmed=True)["payments_enabled"])
        self.assertTrue(s.ff10_payments_enabled())
        self.assertFalse(s.public_status()["enabled"])                                  # Public Rewards OFF
        cash = s.cashout_settings()
        self.assertEqual((cash["live_requests"], cash["real_payouts"]), (False, False))  # public payouts untouched
        event = s.add_event(p1, "quiz", "q-public", rewards.day_key(), reward=True, test=False)
        self.assertEqual(int(event["amount"]), 0)        # the public ledger still pays ₦0 while public is OFF
        self.raises("use_pilot_record_payment", s.rpc, "pilot_mark_paid",
                    {"p_month": LAST, "p_profile": p1, "p_actor": OWNER, "p_reference": "x"})   # the old path is closed
        s.ff10_set_payments(False, OWNER)                                               # suspend again
        self.raises("payments_disabled", self.pay, s, p1)
        self.assertIn("pilot_payments_on", [a["action"] for a in s.audit()])

    def test_authorisation_needs_the_recorded_pilot_terms(self):
        s = self.make_store()
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER]})
        self.raises("terms_required", s.ff10_set_payments, True, OWNER, True)
        with self.assertRaises(StoreError):                                             # only through the function
            s.update("pilot_reward_settings", {"id": 1}, {"payments_enabled": True})
        self.assertFalse(s.ff10_payments_enabled())

    def test_recording_a_manual_bank_transfer(self):
        s = self.store()
        p1, _ = self.approved_line(s)
        s.ff10_set_payments(True, OWNER, confirmed=True)
        row = self.pay(s, p1, ref="  FT2611051234  ")
        self.assertEqual((row["amount"], row["bank_reference"], row["beneficiary_name"], row["bank_name"],
                          row["account_last4"], row["status"], row["recorded_by"]),
                         (500, "FT2611051234", "Player One", "Example Bank", "4321", "paid", OWNER))
        self.assertEqual(str(row["paid_on"])[:10], rewards.day_key())
        line = s.ff10_lines(LAST, p1)[0]
        self.assertEqual((line["status"], line["payment_reference"]), ("paid", "FT2611051234"))
        self.assertEqual(len(s.ff10_payments(LAST)), 1)
        self.assertIn("pilot_payment_recorded", [a["action"] for a in s.audit()])
        self.raises("already_paid", self.pay, s, p1, ref="FT-other")                     # never twice
        with self.assertRaises(StoreError):
            s.update("pilot_payments", {"id": row["id"]}, {"amount": 7000})
        with self.assertRaises(StoreError):
            s.delete("pilot_payments", {"id": row["id"]})
        self.raises("already_paid", s.ff10_decide, LAST, p1, "withhold", OWNER, "too late")

    def test_payment_safeguards(self):
        s = self.store()
        p1, p2 = self.approved_line(s, verify=False)
        s.ff10_set_payments(True, OWNER, confirmed=True)
        self.raises("not_owner", self.pay, s, p1, actor="someone@example.com")
        self.raises("confirmation_required", self.pay, s, p1, confirmed=False)
        self.raises("beneficiary_not_verified", self.pay, s, p1)
        s.ff10_verify_beneficiary(p1, "Player One", "Example Bank", "4321", OWNER, confirmed=True)
        self.raises("not_approved", self.pay, s, p2)                                     # still pending review
        self.raises("amount_mismatch", self.pay, s, p1, amount=499)
        self.raises("amount_mismatch", self.pay, s, p1, amount=501)
        self.raises("reference_required", self.pay, s, p1, ref=" ")
        tomorrow = (rewards.lagos_now() + __import__("datetime").timedelta(days=1)).date().isoformat()
        self.raises("invalid_date", self.pay, s, p1, day=tomorrow)
        yesterday = (rewards.lagos_now() - __import__("datetime").timedelta(days=1)).date().isoformat()
        self.raises("invalid_date", self.pay, s, p1, day=yesterday)                      # before the settlement
        self.raises("not_settled", s.ff10_record_payment, EARLIER, p1, 500, rewards.day_key(), "X-1234", OWNER, True)
        self.pay(s, p1, ref="REF-1111")
        s.ff10_verify_beneficiary(p2, "Player Two", "Other Bank", "9876", OWNER, confirmed=True)
        s.ff10_decide(LAST, p2, "approve", OWNER)
        self.raises("duplicate_reference", self.pay, s, p2, ref="REF-1111")              # a reference is used once
        s.ff10_decide(LAST, p2, "withhold", OWNER, "Identity mismatch")
        self.raises("not_approved", self.pay, s, p2, ref="REF-2222")                     # withheld: never paid

    def test_beneficiary_verification_keeps_only_the_last_four_digits(self):
        s = self.store()
        p = self.participant(s, 1)
        self.raises("invalid_account_last4", s.ff10_verify_beneficiary, p, "Player One", "Bank", "0123456789",
                    OWNER, True)
        self.raises("confirmation_required", s.ff10_verify_beneficiary, p, "Player One", "Bank", "6789", OWNER, False)
        self.raises("not_owner", s.ff10_verify_beneficiary, p, "Player One", "Bank", "6789", "x@example.com", True)
        s.ensure_account(pid(30), "stranger@example.com", "Stranger", True, False)
        self.raises("not_participant", s.ff10_verify_beneficiary, pid(30), "Stranger", "Bank", "6789", OWNER, True)
        row = s.ff10_verify_beneficiary(p, "Player One", "Bank", "6789", OWNER, True, "Checked ID and account name")
        self.assertEqual((row["account_last4"], row["verified"]), ("6789", True))
        self.assertNotIn("0123456789", str(s.ff10_beneficiaries()))

    def test_full_month_paid_within_the_budget(self):
        s = self.store()
        people = [self.participant(s, n) for n in range(1, 9)]
        for n, p in enumerate(people):
            for d in range(1, 15):
                self.top_day(s, p, f"{LAST}-{d:02d}", tag=f"{n}-{d}-")                     # ₦56,000 → ₦50,000
        s.ff10_settle(LAST, OWNER, s.ff10_preview(LAST)["fingerprint"], confirmed=True)
        s.ff10_set_payments(True, OWNER, confirmed=True)
        for n, p in enumerate(people):
            s.ff10_decide(LAST, p, "approve", OWNER)
            s.ff10_verify_beneficiary(p, f"Player {n + 1}", "Example Bank", f"{1000 + n}", OWNER, True)
            self.pay(s, p, ref=f"TRF-{n:04d}")
        total = sum(int(r["amount"]) for r in s.ff10_payments(LAST))
        self.assertEqual(total, 50000)
        self.assertLessEqual(total, s.ff10_settlements()[0]["total_final"])
        self.assertTrue(all(line["status"] == "paid" for line in s.ff10_lines(LAST)))

    def test_concurrent_payment_attempts_pay_once(self):
        s = self.store()
        p1, _ = self.approved_line(s)
        s.ff10_set_payments(True, OWNER, confirmed=True)
        outcomes = []

        def go(i):
            try:
                outcomes.append(self.pay(s, p1, ref=f"TRF-{i:04d}")["bank_reference"])
            except StoreError as error:
                outcomes.append(str(error))

        threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(o.startswith("TRF-") for o in outcomes), 1, outcomes)
        self.assertEqual(sum("already_paid" in o for o in outcomes), 3, outcomes)
        self.assertEqual(len(s.ff10_payments(LAST)), 1)

    # ---- 17. existing records are untouched
    def test_existing_records_are_untouched(self):
        s = self.store()
        p = self.participant(s, 1)
        before = {t: s.select(t) for t in ("reward_activity_events", "reward_enrolments", "reward_payments")}
        self.top_day(s, p, LAST + "-02")
        s.ff10_settle(LAST, OWNER, s.ff10_preview(LAST)["fingerprint"], confirmed=True)
        for table, rows_before in before.items():
            self.assertEqual(s.select(table), rows_before, table)
        self.assertEqual(s.founding_application(p)["status"], "approved")


class MemoryFF10Tests(Scenarios, unittest.TestCase):
    def make_store(self):
        return MemoryStore()

    def record_at(self, s, profile, kind, subject, at, detail=None):
        return s.rpc("pilot_record_activity_at", {"p_profile": profile, "p_kind": kind, "p_subject": subject,
                                                  "p_detail": detail, "p_at": at.isoformat()})

    def test_settlement_inserts_cannot_be_forged_through_the_table(self):
        s = self.store()
        with self.assertRaises(StoreError):
            s.insert("pilot_settlements", {"month": LAST, "budget": 50000, "total_provisional": 0, "total_final": 0,
                                           "participants": 0, "scaled": False, "finalised_by": OWNER})


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
@unittest.skipUnless(pg_harness.PILOT.exists() and pg_harness.FF10.exists(),
                     "supabase/pilot_invitations_migration.sql or friends_family10_migration.sql is not in this "
                     "checkout, so the database rules cannot be loaded into the local test PostgreSQL")
class SqlFF10Tests(Scenarios, unittest.TestCase):
    def make_store(self):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        return pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db())

    def record_at(self, s, profile, kind, subject, at, detail=None):
        root = pg_harness.PsqlStore(CLUSTER, s.db, role="postgres")          # the timed variant is not granted
        return s._one(root.rpc("pilot_record_activity_at", {"p_profile": profile, "p_kind": kind, "p_subject": subject,
                                                            "p_detail": detail, "p_at": at.isoformat()})) or None

    def record_many(self, s, p, specs):
        """One psql call for a whole session (each interaction is still a separate function call)."""
        from pg_harness import literal
        sql = ";\n".join(f"select public.pilot_record_activity_at({literal(p)}, {literal(k)}, {literal(sub)}, "
                         f"{literal(d)}::jsonb, {literal(at.isoformat())}::timestamptz)" for k, sub, at, d in specs)
        CLUSTER.psql(s.db, sql + ";", "postgres")

    def test_the_app_key_cannot_choose_the_time_or_write_tables(self):
        s = self.store()
        p = self.participant(s, 1)
        self.raises("permission denied", s.rpc, "pilot_record_activity_at",
                    {"p_profile": p, "p_kind": "view", "p_subject": "x", "p_detail": None,
                     "p_at": when(LAST + "-01").isoformat()})
        for table in ("pilot_activity", "pilot_settlements", "pilot_settlement_lines", "pilot_day_reviews"):
            with self.assertRaises(StoreError, msg=table):
                s.insert(table, {"profile_id": p, "month": LAST, "day": LAST + "-01"})

    def test_day_reviews_wait_for_a_settlement_in_progress(self):
        """A settlement holds the exclusive month lock; a day review for that month waits for it (shared lock)."""
        import subprocess
        import time
        s = self.store()
        p = self.participant(s, 1)
        self.top_day(s, p, LAST + "-02")
        holder = subprocess.Popen(
            ["psql", "-h", CLUSTER.dir, "-p", CLUSTER.port, "-U", "postgres", "-d", s.db, "-q", "-c",
             f"begin; select pg_advisory_xact_lock(hashtext('ff10:month:{LAST}')); select pg_sleep(2); commit;"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        start = time.monotonic()
        s.ff10_review_day(p, LAST + "-02", True, OWNER, "Checked")
        waited = time.monotonic() - start
        holder.wait()
        self.assertGreater(waited, 1.0)

    def test_browser_roles_have_no_access(self):
        s = self.store()
        for role in ("anon", "authenticated"):
            for sql in ("select count(*) from public.pilot_activity",
                        "select count(*) from public.pilot_settlement_lines",
                        "select public.pilot_settlement_preview('2026-01')"):
                with self.assertRaises(StoreError, msg=(role, sql)):
                    CLUSTER.psql(s.db, sql, role)

    def test_migration_is_rerunnable_and_keeps_everything(self):
        s = self.store()
        p1, _ = self.settled(s)
        CLUSTER.psql_file(s.db, pg_harness.FF10)
        self.assertEqual(len(s.ff10_lines(LAST)), 2)
        self.assertEqual(s.ff10_lines(LAST, p1)[0]["final"], 500)


if __name__ == "__main__":
    unittest.main()
