"""Reliability checks with simulated services: answer timing, signed-in profiles across visits, old profiles,
and what players see when saving or loading is unavailable.

Google sign-in and Supabase are replaced by stand-ins (a fixed verified identity and an in-memory table), so these
tests show the app's own behaviour — not that the live Google client or the live Supabase project are configured.
"""
import json
import sys
import time
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
STORAGE = {"url": "https://example.supabase.co", "server_key": "sb_secret_test"}
USER = {"iss": "https://accounts.google.com", "sub": "abc", "name": "Ada", "email": "ada@example.com",
        "email_verified": True, "profile_id": "f" * 64}


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def monotonic(self):
        return self.now


def answer(at, i, correct=True):
    q = at.session_state["quiz"]
    qn = q["questions"][i]
    pick = qn["answer"] if correct else next(c for c in qn["choices"] if c != qn["answer"])
    at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(pick)}").click().run()


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class TimingTests(unittest.TestCase):
    def test_untimed_daily_round_measures_real_answer_times(self):
        clock = Clock()
        fake_time = types.SimpleNamespace(monotonic=clock.monotonic, time=__import__("time").time)
        with mock.patch("core.quiz.time", fake_time), mock.patch("ui.state.time", fake_time), \
                mock.patch("core.daily.utc_today", return_value=date(2026, 10, 11)):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.button(key="explore_daily").click().run()            # question 1 shown at t=1000
            clock.now += 6.4
            answer(at, 0)
            first = at.session_state["quiz"]["history"][0]
            self.assertAlmostEqual(first["elapsed"], 6.4, places=3)   # was always 0.0 before the fix
            self.assertEqual(first["points"]["speed"], 0)            # untimed: no speed points
            self.assertEqual(first["points"]["total"], 125)          # Medium base, first in a row
            q = at.session_state["quiz"]
            at.button(key=f"next_{q['serial']}_0").click().run()     # question 2 shown
            clock.now += 2.0
            at.button(key="nav_Learn").click().run()                 # away for a long time: the clock pauses
            clock.now += 300
            at.button(key="nav_Quiz").click().run()
            clock.now += 1.5
            answer(at, 1)
            self.assertAlmostEqual(at.session_state["quiz"]["history"][1]["elapsed"], 3.5, places=3)
            for i in range(2, 5):
                at.button(key=f"next_{q['serial']}_{i - 1}").click().run()
                clock.now += 4.0
                answer(at, i)
            at.button(key=f"next_{q['serial']}_4").click().run()
            captions = " ".join(c.value for c in at.caption)
            self.assertIn("Average response time: 4.4 seconds", captions)   # (6.4 + 3.5 + 4 + 4 + 4) / 5
            self.assertEqual([e.value for e in at.exception], [])


class FakeTable:
    """In-memory stand-in for the world_explorer_profiles table."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.fail_reads = self.fail_writes = False
        self.writes = 0

    def request(self, profile_id, payload=None):
        if payload is None:
            if self.fail_reads:
                raise OSError("profiles unreachable")
            return [{"profile": self.rows[profile_id]}] if profile_id in self.rows else []
        if self.fail_writes:
            raise OSError("write failed")
        self.writes += 1
        self.rows[profile_id] = __import__("json").loads(__import__("json").dumps(payload))


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class SignedInProfileTests(unittest.TestCase):
    def visit(self, table, day=date(2026, 10, 11)):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["profiles"] = STORAGE
        patches = [mock.patch("core.accounts.identity", lambda: dict(USER)),
                   mock.patch("core.accounts._request", table.request),
                   mock.patch("core.daily.utc_today", return_value=day)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return at.run()

    def footer(self, at):
        return " ".join(c.value for c in at.caption)

    def finish_daily(self, at, pattern):
        at.button(key="explore_daily").click().run()
        for i, ok in enumerate(pattern):
            answer(at, i, ok)
            q = at.session_state["quiz"]
            at.button(key=f"next_{q['serial']}_{i}").click().run()

    def test_old_profile_loads_and_progress_survives_the_next_visit(self):
        old = {"profile_name": "Okey", "points": 1200, "rounds_finished": 4, "app_language": "English",
               "recent": ["NGA"], "recent_facts": ["capital:NGA:Abuja"]}   # saved before stats, records, daily
        table = FakeTable({USER["profile_id"]: old})
        at = self.visit(table)
        self.assertEqual((at.session_state["points"], at.session_state["rounds_finished"]), (1200, 4))
        self.assertIn("Progress saved to your account", self.footer(at))
        self.finish_daily(at, [True, True, False, True, True])
        saved = table.rows[USER["profile_id"]]
        self.assertEqual(saved["rounds_finished"], 5)
        self.assertEqual(saved["daily"]["results"]["2026-10-11"]["correct"], 4)
        self.assertEqual(saved["profile_name"], "Okey")
        # next visit (new browser session): progress is back and today's challenge only replays
        at2 = self.visit(table)
        self.assertEqual(at2.session_state["points"], saved["points"])
        self.assertEqual(at2.button(key="explore_daily").label, "Replay today's challenge")
        at2.button(key="explore_daily").click().run()
        self.assertEqual(at2.session_state["quiz"]["mode"], "daily_replay")
        self.assertEqual([e.value for e in at2.exception], [])

    def test_save_failure_keeps_progress_and_retries(self):
        table = FakeTable({USER["profile_id"]: {"points": 100}})
        at = self.visit(table)
        table.fail_writes = True
        self.finish_daily(at, [True] * 5)
        self.assertIn("Latest changes not saved online yet", self.footer(at))
        self.assertEqual(table.rows[USER["profile_id"]], {"points": 100})       # nothing half-written
        self.assertGreater(at.session_state["points"], 100)                       # play continues
        table.fail_writes = False
        at.button(key="nav_Badges").click().run()                                 # any next page update retries
        self.assertIn("Progress saved to your account", self.footer(at))
        self.assertEqual(table.rows[USER["profile_id"]]["points"], at.session_state["points"])

    def test_unreachable_profile_is_never_overwritten(self):
        table = FakeTable({USER["profile_id"]: {"points": 9000, "rounds_finished": 30}})
        table.fail_reads = True
        at = self.visit(table)
        self.assertIn("Saved profile not reachable yet · nothing has been overwritten", self.footer(at))
        self.finish_daily(at, [True] * 5)                                          # playing still works
        self.assertEqual(table.writes, 0)
        self.assertEqual(table.rows[USER["profile_id"]]["points"], 9000)
        self.assertEqual([e.value for e in at.exception], [])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class UnfinishedRoundTests(unittest.TestCase):
    """An unfinished round survives a refresh, a closed browser or a lost connection (a new session) for signed-in
    players: it is saved with the profile and offered as "Your quiz is waiting!"."""

    def visit(self, table, day=date(2026, 10, 11)):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["profiles"] = STORAGE
        patches = [mock.patch("core.accounts.identity", lambda: dict(USER)),
                   mock.patch("core.accounts._request", table.request),
                   mock.patch("core.daily.utc_today", return_value=day)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return at.run()

    def start(self, at, count=20, timer=False):
        at.button(key="nav_Quiz").click().run()
        at.button_group(key="filter_count").set_value(count).run()
        if timer:
            at.toggle(key="filter_timer").set_value(True).run()
        at.button(key="start_quiz").click().run()

    def play(self, at, n, start=0):
        for i in range(start, start + n):
            answer(at, i, i % 3 != 0)
            q = at.session_state["quiz"]
            at.button(key=f"next_{q['serial']}_{i}").click().run()

    def test_round_resumes_in_a_new_session_at_the_same_question(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at)
        self.play(at, 10)
        quiz = at.session_state["quiz"]
        before = (quiz["index"], quiz["score"], quiz["correct"], quiz["streak"], quiz["hints_remaining"],
                  [q["answer"] for q in quiz["questions"]], at.session_state["points"])
        saved = table.rows[USER["profile_id"]]["active_round"]["current"]
        self.assertEqual((saved["index"], len(saved["history"])), (10, 10))           # saved after each step
        again = self.visit(table)                                                    # refresh / browser restart
        self.assertTrue(again.session_state["round_waiting"])
        self.assertIn("Your quiz is waiting!", " ".join(str(m.value) for m in again.markdown))
        again.button(key="explore_continue_go").click().run()
        q = again.session_state["quiz"]
        after = (q["index"], q["score"], q["correct"], q["streak"], q["hints_remaining"],
                 [x["answer"] for x in q["questions"]], again.session_state["points"])
        self.assertEqual(before, after)                                               # same round, same points
        self.assertTrue(any("Question 11 of 20" in str(m.value) for m in again.markdown))
        points = again.session_state["points"]
        again.run(); again.run()                                                      # reruns add nothing
        self.assertEqual(again.session_state["points"], points)
        self.play(again, 10, start=10)                                                # finish it
        self.assertTrue(again.session_state["quiz"]["finished"])
        self.assertEqual(again.session_state["rounds_finished"], 1)                   # counted once
        self.assertIsNone(table.rows[USER["profile_id"]]["active_round"])             # nothing left to resume
        self.assertEqual([e.value for e in again.exception], [])

    def test_answered_question_is_not_answered_again_after_a_refresh(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at, count=5)
        answer(at, 0, True)                                                           # answered, Next not pressed
        points = at.session_state["points"]
        again = self.visit(table)
        again.button(key="explore_continue_go").click().run()
        q = again.session_state["quiz"]
        self.assertTrue(q["resolved"])
        self.assertEqual((len(q["history"]), again.session_state["points"]), (1, points))
        self.assertTrue(all(b.disabled for b in again.button if b.key and b.key.startswith(f"answer_{q['serial']}_0_")))

    def test_new_quiz_over_an_unfinished_one_needs_confirmation(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at, count=10)
        self.play(at, 3)
        again = self.visit(table)
        again.button(key="explore_continue_new").click().run()                        # opens setup
        serial = again.session_state["quiz"]["serial"]
        again.button(key="start_quiz").click().run()
        self.assertEqual(again.session_state["quiz"]["serial"], serial)              # not replaced yet
        self.assertTrue(any("will end" in w.value for w in again.warning))
        again.button(key="confirm_new_no").click().run()
        self.assertEqual(again.session_state["quiz"]["index"], 3)                     # kept
        again.button(key="start_quiz").click().run()
        again.button(key="confirm_new_yes").click().run()
        self.assertNotEqual(again.session_state["quiz"]["serial"], serial)           # replaced only after "yes"
        self.assertEqual(again.session_state["quiz"]["index"], 0)

    def test_timed_round_keeps_counting_while_away(self):
        from core import active_round
        table = FakeTable({})
        at = self.visit(table)
        self.start(at, count=5, timer=True)
        data = table.rows[USER["profile_id"]]["active_round"]
        self.assertIsNotNone(data["current"]["presented_wall"])
        # 25 seconds later (the limit is 20 s on Medium): the question counts as timed out, no extra time
        later = time.time() + 25
        quiz, _ = active_round.unpack(data, now_mono=time.monotonic(), now_wall=later)
        from core import quiz as engine
        self.assertGreaterEqual(engine.elapsed(quiz), 24)
        engine.expire_if_due(quiz)
        self.assertTrue(quiz["resolved"] and quiz["history"][-1]["timed_out"])

    def test_outage_never_erases_the_saved_round(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at, count=10)
        self.play(at, 4)
        saved = json.loads(json.dumps(table.rows[USER["profile_id"]]))
        table.fail_reads = True
        down = self.visit(table)                                                      # Supabase unreachable
        self.assertNotIn("Progress saved to your account", " ".join(c.value for c in down.caption))
        down.button(key="nav_Quiz").click().run()
        self.assertEqual(table.rows[USER["profile_id"]], saved)                       # nothing overwritten
        table.fail_reads = False
        back = self.visit(table)
        self.assertTrue(back.session_state["round_waiting"])
        self.assertEqual(back.session_state["quiz"]["index"], 4)

    def test_broken_saved_round_is_ignored_safely(self):
        from core import active_round
        self.assertEqual(active_round.unpack({"v": 1, "current": {"questions": "x"}}), (None, {}))
        self.assertEqual(active_round.unpack("garbage"), (None, {}))
        table = FakeTable({USER["profile_id"]: {"points": 50, "active_round": {"v": 1, "current": {"index": 3}}}})
        at = self.visit(table)
        self.assertFalse(at.session_state.get("round_waiting", False))
        self.assertEqual(at.session_state["points"], 50)
        self.assertEqual([e.value for e in at.exception], [])
