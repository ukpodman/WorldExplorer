"""Quiz answer colours, the Quiz settings panel and the optional background music.

Google sign-in and Supabase are replaced by the same stand-ins as test_reliability.py (a fixed verified identity and
an in-memory table). The music itself plays in the browser; these tests cover what the server decides: the switch,
the saved choice, the marker the browser player follows, and that none of it touches the round or its saving.
"""
import re
import unittest
from datetime import date
from unittest import mock

from test_reliability import APP, STORAGE, USER, AppTest, FakeTable, answer

from core import accounts
from ui import music


def html_bodies(at) -> list[str]:
    return [h.proto.body for h in at.get("html")]


def marker(at) -> str | None:
    for body in html_bodies(at):
        m = re.search(r'class="we-music-marker" data-on="(\d)"', body)
        if m:
            return m.group(1)
    return None


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class BackgroundMusicTests(unittest.TestCase):

    def visit(self, table=None, signed_in=True):
        at = AppTest.from_file(APP, default_timeout=60)
        patches = [mock.patch("core.daily.utc_today", return_value=date(2026, 10, 11))]
        if signed_in:
            at.secrets["profiles"] = STORAGE
            patches += [mock.patch("core.accounts.identity", lambda: dict(USER)),
                        mock.patch("core.accounts._request", table.request)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return at.run()

    def start(self, at, count=5):
        at.button(key="nav_Quiz").click().run()
        at.button_group(key="filter_count").set_value(count).run()
        at.button(key="start_quiz").click().run()

    def test_music_is_off_by_default_and_only_the_quiz_page_has_the_marker(self):
        at = self.visit(FakeTable({}))
        self.assertFalse(at.session_state["music_on"])
        self.assertIsNone(marker(at))                         # Explore: no marker, so the player stays silent
        at.button(key="nav_Quiz").click().run()
        self.assertEqual(marker(at), "0")                     # Quiz page, choice off
        self.assertFalse(at.toggle(key="music_switch_setup").value)
        at.button(key="nav_Learn").click().run()
        self.assertIsNone(marker(at))
        self.assertEqual([e.value for e in at.exception], [])

    def test_switching_music_on_during_a_round_keeps_the_round_and_saves_once(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at)
        answer(at, 0, True)
        quiz = at.session_state["quiz"]
        before = (quiz["serial"], quiz["index"], quiz["resolved"], quiz["score"], at.session_state["points"],
                  [q["answer"] for q in quiz["questions"]])
        writes = table.writes
        at.toggle(key="music_switch_play").set_value(True).run()
        quiz = at.session_state["quiz"]
        after = (quiz["serial"], quiz["index"], quiz["resolved"], quiz["score"], at.session_state["points"],
                 [q["answer"] for q in quiz["questions"]])
        self.assertEqual(before, after)                       # same round, same question, nothing scored again
        self.assertTrue(at.session_state["music_on"])
        self.assertEqual(table.writes - writes, 1)            # one save, for the changed choice
        row = table.rows[USER["profile_id"]]
        self.assertTrue(row["music_on"])
        self.assertEqual(row["active_round"]["current"]["index"], 0)   # the unfinished round is still saved
        self.assertEqual(len(row["active_round"]["current"]["history"]), 1)
        self.assertEqual(marker(at), "1")
        at.run(); at.run()                                    # reruns write nothing more
        self.assertEqual(table.writes - writes, 1)
        self.assertEqual([e.value for e in at.exception], [])

    def test_choice_comes_back_in_a_new_session_and_the_quiz_can_still_be_continued(self):
        table = FakeTable({})
        at = self.visit(table)
        self.start(at)
        answer(at, 0, True)
        q = at.session_state["quiz"]
        at.button(key=f"next_{q['serial']}_0").click().run()
        at.toggle(key="music_switch_play").set_value(True).run()
        again = self.visit(table)                             # refresh / closed browser
        self.assertTrue(again.session_state["music_on"])
        self.assertTrue(again.session_state["round_waiting"])
        again.button(key="explore_continue_go").click().run()
        self.assertEqual(again.session_state["quiz"]["index"], 1)
        self.assertEqual(marker(again), "1")
        self.assertTrue(again.toggle(key="music_switch_play").value)
        again.toggle(key="music_switch_play").set_value(False).run()
        self.assertFalse(table.rows[USER["profile_id"]]["music_on"])
        self.assertEqual([e.value for e in again.exception], [])

    def test_guest_can_switch_music_for_the_session(self):
        at = self.visit(signed_in=False)
        at.button(key="nav_Quiz").click().run()
        at.toggle(key="music_switch_setup").set_value(True).run()
        self.assertTrue(at.session_state["music_on"])
        self.assertEqual(marker(at), "1")
        self.assertEqual([e.value for e in at.exception], [])

    def test_change_quiz_setup_still_opens_setup_and_keeps_the_round(self):
        at = self.visit(FakeTable({}))
        self.start(at)
        serial = at.session_state["quiz"]["serial"]
        at.button(key="quiz_settings").click().run()
        self.assertTrue(at.session_state["show_setup"])
        self.assertEqual(at.session_state["quiz"]["serial"], serial)
        self.assertEqual([e.value for e in at.exception], [])


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class AnswerLabelTests(unittest.TestCase):

    def round(self):
        at = AppTest.from_file(APP, default_timeout=60)
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 11)):
            at.run()
            at.button(key="nav_Quiz").click().run()
            at.button_group(key="filter_count").set_value(5).run()
            at.toggle(key="filter_flags").set_value(False).run()
            at.button(key="start_quiz").click().run()
        return at

    def labels(self, at, i):
        q = at.session_state["quiz"]
        qn = q["questions"][i]
        return {c: at.button(key=f"answer_{q['serial']}_{i}_{k}").label for k, c in enumerate(qn["choices"])}, qn

    def test_wrong_choice_and_right_answer_are_labelled_in_words(self):
        at = self.round()
        answer(at, 0, False)
        labels, qn = self.labels(at, 0)
        picked = at.session_state["quiz"]["selected"]
        self.assertIn("✕ Your answer · Wrong", labels[picked])
        self.assertIn("✓ Correct answer", labels[qn["answer"]])
        for c, label in labels.items():
            if c not in (picked, qn["answer"]):
                self.assertNotIn("✓", label); self.assertNotIn("✕", label)

    def test_right_choice_is_labelled_as_your_correct_answer(self):
        at = self.round()
        answer(at, 0, True)
        labels, qn = self.labels(at, 0)
        self.assertIn("✓ Your answer · Correct", labels[qn["answer"]])
        self.assertEqual(sum("✓" in v or "✕" in v for v in labels.values()), 1)

    def test_before_answering_no_card_carries_a_result_mark(self):
        at = self.round()
        labels, _ = self.labels(at, 0)
        self.assertFalse(any("✓" in v or "✕" in v for v in labels.values()))


class MusicPlayerScriptTests(unittest.TestCase):

    def test_player_script_survives_the_html_cleaner(self):
        # The cleaner drops a whole script containing "<" followed by a letter, digit, "/" or "!".
        inner = music.PLAYER[music.PLAYER.index(">") + 1:music.PLAYER.rindex("</script>")]
        self.assertNotIn("<", inner)
        self.assertIn("W.__weMusic", inner)                   # installed once per tab

    def test_player_is_quiet_and_has_one_instance_guard(self):
        self.assertLessEqual(music.VOLUME, 0.08)
        self.assertIn("if(W.__weMusic){W.__weMusic.poll();return;}", music.PLAYER)
        self.assertIn("visibilitychange", music.PLAYER)
        self.assertIn("pagehide", music.PLAYER)

    def test_saved_choice_must_be_true_or_false(self):
        self.assertEqual(accounts.sanitize_profile({"music_on": True}), {"music_on": True})
        self.assertEqual(accounts.sanitize_profile({"music_on": "yes"}), {})
        self.assertEqual(accounts.sanitize_profile({"music_on": 1}), {})


if __name__ == "__main__":
    unittest.main()
