"""Reliability checks with simulated services: answer timing, signed-in profiles across visits, old profiles,
and what players see when saving or loading is unavailable.

Google sign-in and Supabase are replaced by stand-ins (a fixed verified identity and an in-memory table), so these
tests show the app's own behaviour — not that the live Google client or the live Supabase project are configured.
"""
import sys
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
        self.assertIn("Saved to your account", self.footer(at))
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
        self.assertIn("Saved to your account", self.footer(at))
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
