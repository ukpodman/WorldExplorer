"""Friends & Family 10: verified active learning time (activity checks for reading and exploring).

Pure scenarios run on core/pilot_rewards.py. Store scenarios run against the in-memory store and, when PostgreSQL and
the earlier pilot migrations are available, against supabase/friends_family10_active_time_migration.sql in a throwaway
local database. The page script's rules (visible, focused, real input) run in Node when it is installed.
"""
import ast
import json
import shutil
import subprocess
import sys
import tempfile
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
LAST = rewards.previous_month(CUR)
EARLIER = rewards.previous_month(LAST)
CLUSTER = None


def setUpModule():
    global CLUSTER
    if (pg_harness.available() and pg_harness.PILOT.exists() and pg_harness.FF10.exists()
            and pg_harness.FF10_TIME.exists()):
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
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hour, minute, second, tzinfo=LAGOS)


def row(kind, subject, at):
    return {"kind": kind, "subject": subject, "at": at.isoformat(), "day": pr.lagos_day(at), "detail": None}


def beat(at, area="learn"):
    return {"area": area, "at": at.isoformat(), "day": pr.lagos_day(at)}


def old_active_seconds(day_rows):
    """The calculation exactly as it was before this change (for the no-regression check)."""
    times = sorted(pr._dt(r["at"]) for r in day_rows)
    return int(sum(min((b - a).total_seconds(), 180) for a, b in zip(times, times[1:])))


def reported_27_october():
    """39 interactions, 3 qualifying quizzes and the Daily Challenge, 41.8 minutes from first to last, and one pause of
    36.6 minutes: 33.6 minutes not counted, 8.2 verified (8 whole minutes), ₦0."""
    t, out = when("2026-10-27", 18), []
    small = [8] * 36 + [24]                                   # 37 short gaps = 312 s
    kinds = (["answer"] * 5 + ["quiz"]) * 3 + ["answer"] * 5 + ["challenge"]
    kinds += ["view", "country"] * ((39 - len(kinds)) // 2) + ["view"] * ((39 - len(kinds)) % 2)
    times = [t]
    for g in small[:20]:
        times.append(times[-1] + timedelta(seconds=g))
    times.append(times[-1] + timedelta(seconds=2196))         # the long pause (36.6 minutes)
    for g in small[20:]:
        times.append(times[-1] + timedelta(seconds=g))
    for i, (k, at) in enumerate(zip(kinds, times)):
        out.append(row(k, f"{k}:{i}" if k != "challenge" else "daily:2026-10-27", at))
    return out


def reported_26_october():
    """7 interactions, 55.7 minutes, two pauses over 3 minutes: 46.3 minutes not counted, about 9 verified."""
    t = when("2026-10-26", 19)
    gaps = [60, 1569, 44, 50, 1569, 50]                       # 204 s short + two pauses of 26.15 minutes
    times = [t]
    for g in gaps:
        times.append(times[-1] + timedelta(seconds=g))
    return [row("view" if i % 2 else "country", f"c{i}", at) for i, at in enumerate(times)]


# ============================================================================ pure calculations

class ReportedScenarioTests(unittest.TestCase):
    def test_27_october_explains_8_verified_minutes(self):
        rows = reported_27_october()
        self.assertEqual(len(rows), 39)
        tl = pr.timeline(rows)
        self.assertEqual(round(tl["elapsed"] / 60, 1), 41.8)
        self.assertEqual(len(tl["gaps"]), 1)
        self.assertEqual(round(tl["uncredited"] / 60, 1), 33.6)
        self.assertEqual(round(tl["credited"] / 60, 1), 8.2)
        [day] = pr.day_summaries(rows)
        self.assertEqual((day.minutes, day.quizzes, day.challenge, day.tier, day.tier_amount), (8, 3, True, 0, 0))
        self.assertEqual(pr.uncredited_reasons(tl),
                         ["1 pause longer than 3 minutes with no recorded activity: 33.6 minutes not counted"])

    def test_26_october_explains_about_9_verified_minutes(self):
        tl = pr.timeline(reported_26_october())
        self.assertEqual((tl["interactions"], len(tl["gaps"])), (7, 2))
        self.assertEqual(round(tl["elapsed"] / 60, 1), 55.7)
        self.assertEqual(round(tl["uncredited"] / 60, 1), 46.3)
        self.assertEqual(round(tl["credited"] / 60, 1), 9.4)

    def test_reading_through_the_long_pause_would_now_count_but_only_15_minutes_past_the_last_interaction(self):
        rows = reported_27_october()
        times = sorted(pr._dt(r["at"]) for r in rows)
        pause_start = times[20]
        beats = []
        t = pause_start + timedelta(seconds=60)
        while t < times[21]:                                   # the page sends a check each minute while engaged
            if pr.accept_heartbeat(beats, rows, "learn", t):
                beats.append(beat(t))
            t += timedelta(seconds=60)
        self.assertEqual(len(beats), 15)                       # anchor: 15 minutes after the last interaction
        credited = pr.active_seconds(rows, beats)
        self.assertEqual(credited, 312 + 900 + 180)           # short gaps + 15 verified minutes + the 3-minute rule
        self.assertLess(credited, pr.timeline(rows)["elapsed"])
        [day] = pr.day_summaries(rows, beats=beats)
        self.assertEqual((day.minutes, day.heartbeats), (23, 15))
        self.assertEqual(day.tier, 1)                          # 15 min + quizzes: ₦100 (not automatic: needs checks)

    def test_historical_days_without_checks_are_unchanged(self):
        for rows in (reported_27_october(), reported_26_october()):
            self.assertEqual(pr.active_seconds(rows), old_active_seconds(rows))
            self.assertEqual(pr.day_summaries(rows)[0].seconds, old_active_seconds(rows))


class ActiveTimeRuleTests(unittest.TestCase):
    D = "2026-10-28"

    def session(self, beats_every=None, minutes=10, start=None):
        """One interaction, then `minutes` minutes of reading with a check every `beats_every` seconds."""
        t0 = start or when(self.D, 10)
        rows = [row("view", "NG", t0)]
        beats = []
        if beats_every:
            t = t0 + timedelta(seconds=beats_every)
            while t <= t0 + timedelta(minutes=minutes):
                if pr.accept_heartbeat(beats, rows, "learn", t):
                    beats.append(beat(t))
                t += timedelta(seconds=beats_every)
        return rows, beats

    def test_reading_without_clicking_counts(self):
        rows, beats = self.session(60, 10)
        self.assertEqual(len(beats), 10)
        self.assertEqual(pr.active_seconds(rows, beats), 600)

    def test_reading_with_no_checks_counts_only_up_to_the_last_activity(self):
        rows, _ = self.session(None)
        self.assertEqual(pr.active_seconds(rows), 0)           # a single interaction: no time yet

    def test_brief_pauses_count(self):
        t = when(self.D, 11)
        rows = [row("answer", "q:0", t), row("answer", "q:1", t + timedelta(minutes=2, seconds=30))]
        self.assertEqual(pr.active_seconds(rows), 150)
        self.assertEqual(pr.timeline(rows)["gaps"], [])

    def test_inactive_tab_sends_nothing_so_a_long_pause_counts_three_minutes(self):
        t = when(self.D, 12)
        rows = [row("view", "FR", t), row("view", "DE", t + timedelta(minutes=25))]
        self.assertEqual(pr.active_seconds(rows), 180)
        self.assertEqual(round(pr.timeline(rows)["uncredited"] / 60), 22)

    def test_network_interruption_short_is_covered_long_is_not_replayed(self):
        rows, beats = self.session(60, 10)
        lost_short = [b for b in beats if not (3 <= beats.index(b) <= 4)]       # two checks lost (2 minutes)
        self.assertEqual(pr.active_seconds(rows, lost_short), 600)
        lost_long = beats[:2] + beats[8:]                                          # six checks lost
        self.assertEqual(pr.active_seconds(rows, lost_long), 600 - (7 * 60 - 180))

    def test_duplicate_checks_from_tabs_devices_or_reruns_are_ignored(self):
        t0 = when(self.D, 13)
        rows, beats = [row("view", "KE", t0)], []
        for offset in (60, 61, 75, 109, 110, 170):              # two tabs plus reruns
            at = t0 + timedelta(seconds=offset)
            if pr.accept_heartbeat(beats, rows, "explore", at):
                beats.append(beat(at, "explore"))
        self.assertEqual([pr._dt(b["at"]) - t0 for b in beats],
                         [timedelta(seconds=60), timedelta(seconds=110), timedelta(seconds=170)])
        self.assertLessEqual(pr.active_seconds(rows, beats), 170)              # never more than real time

    def test_repeated_interactions_and_page_reruns_add_nothing(self):
        t0 = when(self.D, 14)
        history = []
        for s in range(0, 300, 5):                               # the same country re-sent by reruns every 5 s
            at = t0 + timedelta(seconds=s)
            if pr.accept(history, "view", "GH", at):
                history.append(row("view", "GH", at))
        self.assertEqual(len(history), 1)
        self.assertEqual(pr.active_seconds(history), 0)

    def test_checks_need_a_recent_meaningful_interaction_the_same_day(self):
        t0 = when(self.D, 15)
        rows = [row("view", "EG", t0)]
        self.assertFalse(pr.accept_heartbeat([], rows, "learn", t0 - timedelta(seconds=30)))   # before it
        self.assertTrue(pr.accept_heartbeat([], rows, "learn", t0 + timedelta(seconds=900)))
        self.assertFalse(pr.accept_heartbeat([], rows, "learn", t0 + timedelta(seconds=901)))  # app left open
        late = [row("view", "EG", when(self.D, 23, 58))]
        self.assertFalse(pr.accept_heartbeat([], late, "learn", when("2026-10-29", 0, 1)))       # previous day
        self.assertFalse(pr.accept_heartbeat([], [], "learn", t0))

    def test_school_learning_and_unknown_areas_never_count(self):
        rows = [row("view", "NG", when(self.D, 16))]
        for area in ("school", "badges", "rewards", "", None):
            self.assertFalse(pr.accept_heartbeat([], rows, area, when(self.D, 16, 1)), area)

    def test_daily_limit_of_checks(self):
        t0 = when(self.D, 6)
        beats, rows = [], []
        for i in range(400):
            at = t0 + timedelta(seconds=60 * i)
            if i % 10 == 0:
                rows.append(row("view", f"c{i}", at))             # keeps the anchor fresh
            if pr.accept_heartbeat(beats, rows, "learn", at):
                beats.append(beat(at))
        self.assertEqual(len(beats), pr.HEARTBEAT_DAILY_MAX)

    def test_checks_alone_never_reach_a_reward(self):
        rows, beats = self.session(60, 60)
        rows2 = rows + [row("view", f"x{i}", when(self.D, 10, i * 10)) for i in range(1, 6)]
        beats2 = []
        t = when(self.D, 10)
        while t < when(self.D, 11, 10):
            t += timedelta(seconds=60)
            if pr.accept_heartbeat(beats2, rows2, "explore", t):
                beats2.append(beat(t, "explore"))
        [day] = pr.day_summaries(rows2, beats=beats2)
        self.assertGreaterEqual(day.minutes, 60)
        self.assertEqual((day.quizzes, day.tier, day.tier_amount), (0, 0, 0))     # quizzes are still required

    def test_checks_on_a_day_without_interactions_add_nothing(self):
        rows = [row("view", "NG", when(self.D, 10))]
        stray = [beat(when("2026-10-29", 10, m)) for m in range(10)]
        [day] = pr.day_summaries(rows, beats=stray)
        self.assertEqual((day.day, day.seconds, day.heartbeats), (self.D, 0, 0))

    def test_reward_structure_is_unchanged(self):
        self.assertEqual((pr.MAX_PARTICIPANTS, pr.DAILY_MAX, pr.MONTHLY_MAX, pr.MONTHLY_BUDGET),
                         (10, 500, 7_000, 50_000))
        self.assertEqual(pr.TIERS, ((100, 15, 1, 0, False), (250, 30, 2, 0, False), (350, 45, 2, 1, False),
                                    (500, 60, 2, 1, True)))
        self.assertEqual((pr.INACTIVITY_SECONDS, pr.REPEAT_SECONDS), (180, 600))

    def test_sql_uses_the_same_values(self):
        sql = (ROOT / "supabase" / "friends_family10_active_time_migration.sql").read_text()
        self.assertIn(f"make_interval(secs => {pr.HEARTBEAT_MIN_GAP})", sql)
        self.assertIn(f"make_interval(secs => {pr.ANCHOR_SECONDS})", sql)
        self.assertIn(f">= {pr.HEARTBEAT_DAILY_MAX}", sql)
        self.assertIn("area in ('explore', 'learn', 'quiz')", sql)
        self.assertNotIn("update public.pilot_activity", sql)
        self.assertNotIn("delete from", sql.lower())
        self.assertNotIn("pilot_reward_settings set", sql)


class AuditTests(unittest.TestCase):
    def test_read_only_audit_for_26_and_27_october(self):
        rows = reported_26_october() + reported_27_october()
        before = json.dumps(rows, sort_keys=True)
        report = pr.audit_days(rows, [], ["2026-10-26", "2026-10-27"])
        self.assertEqual(json.dumps(rows, sort_keys=True), before)              # nothing changed
        d26, d27 = report
        self.assertEqual((d26["interactions"], len(d26["gaps"]), d26["minutes"]), (7, 2, 9))
        self.assertEqual((d27["interactions"], d27["quizzes"], d27["challenge"], d27["minutes"]), (39, 3, True, 8))
        self.assertEqual(round(d27["gaps"][0]["seconds"] / 60, 1), 36.6)
        self.assertEqual(d27["gaps"][0]["before"], ("answer", "answer:20"))      # what came just before the pause
        self.assertEqual(round(d27["uncredited"] / 60, 1), 33.6)

    def test_audit_module_has_no_write_calls(self):
        src = (ROOT / "ui" / "owner_ff10.py").read_text()
        body = src.split("def _time_audit", 1)[1].split("\ndef ", 1)[0]
        for call in ("ff10_review_day", "rpc(", "insert(", "update(", "delete(", "_act("):
            self.assertNotIn(call, body)


# ============================================================================ the page script (Node)

def _page_js() -> str:
    tree = ast.parse((ROOT / "ui" / "ff10_heartbeat.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "JS":
            return node.value.value
    raise AssertionError("JS not found")


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class PageScriptTests(unittest.TestCase):
    def run_js(self, scenario: str) -> list:
        harness = r"""
let now = 1_000_000, timers = [], sent = [], listeners = {};
Date.now = () => now;
const doc = { visibilityState: "visible", focus: true, hasFocus() { return this.focus; },
  addEventListener(n, f) { (listeners[n] = listeners[n] || []).push(f); }, querySelectorAll() { return []; } };
globalThis.document = doc;
globalThis.window = { setInterval(f, ms) { timers.push(f); return 1; } };
function fire(n, trusted = true) { (listeners[n] || []).forEach(f => f({ isTrusted: trusted })); }
function advance(sec) { for (let i = 0; i < sec / 10; i++) { now += 10000; timers.forEach(f => f()); } }
const el = { isConnected: true };
""" + _page_js().replace("export default function", "const mount = function") + r"""
mount({ data: { interval: 60, engaged: 75 }, setTriggerValue: (k, v) => sent.push([k, v, now]), parentElement: el });
mount({ data: { interval: 60, engaged: 75 }, setTriggerValue: (k, v) => sent.push([k, v, now]), parentElement: el });
""" + scenario + "\nconsole.log(JSON.stringify(sent.map(s => (s[2] - 1_000_000) / 1000)));"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.mjs"
            path.write_text(harness)
            out = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_engaged_reading_sends_one_check_a_minute(self):
        sent = self.run_js("for (let m = 0; m < 5; m++) { fire('scroll'); advance(60); }")
        self.assertEqual(len(sent), 5)                          # remounting on reruns does not double the timer
        self.assertTrue(all(b - a >= 60 for a, b in zip(sent, sent[1:])))

    def test_nothing_without_real_input(self):
        self.assertEqual(self.run_js("advance(600);"), [])
        self.assertEqual(self.run_js("fire('scroll', false); advance(300);"), [])          # synthetic events
        self.assertEqual(self.run_js("fire('mousemove'); advance(300);"), [])              # mouse movement alone

    def test_input_stops_then_checks_stop(self):
        sent = self.run_js("fire('touchstart'); advance(600);")
        self.assertEqual(sent, [10, 70])                       # never later than 75 s after the last real input

    def test_hidden_or_unfocused_page_sends_nothing(self):
        self.assertEqual(self.run_js("doc.visibilityState = 'hidden'; for (let m = 0; m < 5; m++) { fire('scroll'); advance(60); }"), [])
        self.assertEqual(self.run_js("doc.focus = false; for (let m = 0; m < 5; m++) { fire('keydown'); advance(60); }"), [])

    def test_leaving_the_eligible_page_stops_checks(self):
        self.assertEqual(self.run_js("el.isConnected = false; for (let m = 0; m < 5; m++) { fire('scroll'); advance(60); }"), [])


# ============================================================================ stores (memory and SQL)

class StoreScenarios:
    def make_store(self):
        raise NotImplementedError

    def store(self):
        s = self.make_store()
        s.save_settings(Settings(start_date=f"{EARLIER}-01"), OWNER)
        s.update("reward_cashout_settings", {"id": 1}, {"owner_emails": [OWNER]})
        s.set_participation_terms("pilot", TERMS, OWNER)
        s.set_pilot(True, OWNER, confirmed=True)
        return s

    def record(self, s, p, kind, subject, at):
        raise NotImplementedError

    def heartbeat(self, s, p, area, at):
        raise NotImplementedError

    def participant(self, s, n, test=False):
        raise NotImplementedError

    def raises(self, reason, fn, *args):
        with self.assertRaises(StoreError) as caught:
            fn(*args)
        self.assertIn(reason, str(caught.exception))

    def test_checks_count_as_reading_time_in_the_ledger(self):
        s = self.store()
        p = self.participant(s, 1)
        day = f"{LAST}-10"
        t0 = when(day, 9)
        self.record(s, p, "view", "NG", t0)
        self.record(s, p, "quiz", "q1", t0 + timedelta(seconds=30))
        accepted = [self.heartbeat(s, p, "learn", t0 + timedelta(minutes=m)) for m in range(1, 17)]
        self.assertEqual(sum(1 for a in accepted if a), 15)      # the 16th is past the 15-minute anchor
        led = {str(d["day"])[:10]: d for d in s.ff10_ledger(p, LAST)}
        self.assertEqual((led[day]["minutes"], led[day]["interactions"], led[day]["tier"]), (15, 2, 1))
        self.assertEqual(s.ff10_preview(LAST)["total_provisional"], 100)

    def test_duplicates_and_limits_are_enforced_by_the_database(self):
        s = self.store()
        p = self.participant(s, 1)
        t0 = when(f"{LAST}-11", 9)
        self.record(s, p, "view", "GH", t0)
        self.assertIsNotNone(self.heartbeat(s, p, "explore", t0 + timedelta(seconds=60)))
        self.assertIsNone(self.heartbeat(s, p, "explore", t0 + timedelta(seconds=80)))     # second tab / rerun
        self.assertIsNone(self.heartbeat(s, p, "learn", t0 + timedelta(seconds=109)))
        self.assertIsNotNone(self.heartbeat(s, p, "learn", t0 + timedelta(seconds=110)))
        self.assertIsNone(self.heartbeat(s, p, "learn", t0 + timedelta(minutes=40)))      # app left open
        self.raises("invalid_activity", self.heartbeat, s, p, "school", t0 + timedelta(seconds=200))

    def test_only_participants_while_the_pilot_is_on(self):
        s = self.store()
        p = self.participant(s, 1)
        t0 = when(f"{LAST}-12", 9)
        self.record(s, p, "view", "KE", t0)
        s.ensure_account(pid(9), "stranger@example.com", "Stranger", True, False)
        self.raises("not_participant", self.heartbeat, s, pid(9), "learn", t0 + timedelta(seconds=60))
        s.set_pilot(False, OWNER)
        self.raises("pilot_closed", self.heartbeat, s, p, "learn", t0 + timedelta(seconds=60))

    def test_test_accounts_are_kept_apart(self):
        s = self.store()
        p = self.participant(s, 1)
        t = self.participant(s, 2, test=True)
        t0 = when(f"{LAST}-13", 9)
        self.record(s, t, "view", "EG", t0)
        row = self.heartbeat(s, t, "learn", t0 + timedelta(seconds=60))
        self.assertTrue(row and row["test"])
        self.assertIsNone(self.heartbeat(s, p, "learn", t0 + timedelta(seconds=60)))     # no own interaction
        self.assertEqual(s.ff10_ledger(t, LAST), [])

    def test_existing_earnings_are_preserved(self):
        s = self.store()
        p = self.participant(s, 1)
        day = f"{LAST}-14"
        t0 = when(day, 9)
        for i in range(31):
            self.record(s, p, "view", f"v{i}", t0 + timedelta(minutes=i))
        self.record(s, p, "quiz", "a", t0 + timedelta(minutes=1, seconds=5))
        self.record(s, p, "quiz", "b", t0 + timedelta(minutes=2, seconds=5))
        before = s.ff10_ledger(p, LAST)
        self.assertEqual(before[0]["amount"], 250)
        for m in range(31, 40):                                  # extra reading cannot lower an earned day
            self.heartbeat(s, p, "learn", t0 + timedelta(minutes=m))
        after = s.ff10_ledger(p, LAST)
        self.assertGreaterEqual(after[0]["amount"], before[0]["amount"])
        self.assertEqual(len(s.ff10_activity(p, LAST)), 33)      # interaction records untouched

    def test_records_cannot_be_changed(self):
        s = self.store()
        p = self.participant(s, 1)
        t0 = when(f"{LAST}-15", 9)
        self.record(s, p, "view", "NG", t0)
        self.heartbeat(s, p, "learn", t0 + timedelta(seconds=60))
        with self.assertRaises(StoreError):
            s.delete("pilot_heartbeats", {"profile_id": p})
        with self.assertRaises(StoreError):
            s.insert("pilot_heartbeats", {"profile_id": p, "day": f"{LAST}-15", "area": "learn", "test": False})


class MemoryActiveTimeTests(StoreScenarios, unittest.TestCase):
    def make_store(self):
        return MemoryStore()

    def participant(self, s, n, test=False):
        email = f"p{n}@example.com"
        s.ensure_account(pid(n), email, f"Player {n}", True, test)
        if test:
            return pid(n)
        s.invite(email, OWNER)
        app = s.apply_founding(pid(n), "Lagos", None, True, True, True, terms_version=TERMS)
        s.decide_founding(app["id"], "approve", OWNER)
        return pid(n)

    def record(self, s, p, kind, subject, at):
        return s.rpc("pilot_record_activity_at", {"p_profile": p, "p_kind": kind, "p_subject": subject,
                                                  "p_detail": None, "p_at": at.isoformat()})

    def heartbeat(self, s, p, area, at):
        return s.rpc("pilot_record_heartbeat_at", {"p_profile": p, "p_area": area, "p_at": at.isoformat()})


@unittest.skipUnless(pg_harness.available(), "PostgreSQL is not installed")
@unittest.skipUnless(pg_harness.PILOT.exists() and pg_harness.FF10_TIME.exists(),
                     "the earlier pilot migrations are not in this checkout")
class SqlActiveTimeTests(StoreScenarios, unittest.TestCase):
    def make_store(self):
        if not CLUSTER:
            self.skipTest("local PostgreSQL did not start")
        return pg_harness.PsqlStore(CLUSTER, CLUSTER.fresh_db())

    def participant(self, s, n, test=False):
        email = f"p{n}@example.com"
        s.ensure_account(pid(n), email, f"Player {n}", True, test)
        if test:
            return pid(n)
        s.invite(email, OWNER)
        CLUSTER.approve(s.db, pid(n))
        s.ff10_accept_terms(pid(n), TERMS)
        return pid(n)

    def _root(self, s):
        return pg_harness.PsqlStore(CLUSTER, s.db, role="postgres")      # the timed variants are not granted

    def record(self, s, p, kind, subject, at):
        return s._one(self._root(s).rpc("pilot_record_activity_at", {"p_profile": p, "p_kind": kind, "p_subject": subject,
                                                                    "p_detail": None, "p_at": at.isoformat()})) or None

    def heartbeat(self, s, p, area, at):
        out = s._one(self._root(s).rpc("pilot_record_heartbeat_at", {"p_profile": p, "p_area": area,
                                                                     "p_at": at.isoformat()}))
        return out if out and out.get("id") is not None else None

    def test_the_app_key_cannot_choose_the_time_or_write_checks(self):
        s = self.store()
        p = self.participant(s, 1)
        self.raises("permission denied", s.rpc, "pilot_record_heartbeat_at",
                    {"p_profile": p, "p_area": "learn", "p_at": when(f"{LAST}-01").isoformat()})
        self.raises("permission denied", s.insert, "pilot_heartbeats",
                    {"profile_id": p, "day": f"{LAST}-01", "area": "learn", "test": False})
        for role in ("anon", "authenticated"):
            other = pg_harness.PsqlStore(CLUSTER, s.db, role=role)
            self.raises("permission denied", other.select, "pilot_heartbeats")
            self.raises("permission denied", other.rpc, "pilot_record_heartbeat", {"p_profile": p, "p_area": "learn"})

    def test_ledger_matches_the_python_rules_for_the_reported_days(self):
        s = self.store()
        p = self.participant(s, 1)
        shift = {"2026-10-26": f"{LAST}-26", "2026-10-27": f"{LAST}-27"}
        moved = []
        for r in reported_26_october() + reported_27_october():
            at = pr._dt(r["at"])
            day = shift[r["day"]]
            at = at.replace(year=int(day[:4]), month=int(day[5:7]))
            self.record(s, p, r["kind"], r["subject"], at)
            moved.append(row(r["kind"], r["subject"], at))
        sql = {str(d["day"])[:10]: d["minutes"] for d in s.ff10_ledger(p, LAST)}
        py = {d.day: d.minutes for d in pr.day_summaries(moved)}
        self.assertEqual(sql, py)
        self.assertEqual(sorted(sql.values()), [8, 9])


if __name__ == "__main__":
    unittest.main()
