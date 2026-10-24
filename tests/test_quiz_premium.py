"""Premium Quiz (Project Atlas): the presentation changes, with the quiz engine and scoring untouched."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")


def answer(at, i, correct=True):
    q = at.session_state["quiz"]
    qn = q["questions"][i]
    pick = qn["answer"] if correct else next(c for c in qn["choices"] if c != qn["answer"])
    at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(pick)}").click().run()


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class PremiumQuizTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def markdown(self, at):
        return "\n".join(str(m.value) for m in at.markdown)

    def start(self, count=5):
        at = self.new(page="Quiz")
        at.button_group(key="filter_count").set_value(count).run()
        at.button(key="start_quiz").click().run()
        return at

    def test_home_has_the_atlas_heading_and_names_the_region(self):
        at = self.new(page="Quiz")
        text = self.markdown(at)
        self.assertIn('class="atlas-head quiz-head"', text)              # shown (not the hidden "playing" variant)
        self.assertIn("Test what you know.", text)
        self.assertIn('class="quiz-where"', text)
        self.assertIn("World · UN member and observer states", text)       # region and places, from the setup
        self.assertEqual([e.value for e in at.exception], [])

    def test_heading_is_marked_hidden_during_a_question(self):
        at = self.start()
        self.assertIn("quiz-head playing", self.markdown(at))

    def test_feedback_shows_the_country_photograph_from_the_shared_collection(self):
        import core.data
        at = self.start()
        q = at.session_state["quiz"]["questions"][0]
        rec = {"file": "File:Test_view.jpg", "caption": "A test view", "author": "A. Photographer", "license": "CC BY-SA 4.0",
               "license_url": "https://creativecommons.org/licenses/by-sa/4.0", "url": "https://upload.wikimedia.org/x/Test_view.jpg",
               "page": "https://commons.wikimedia.org/wiki/File:Test_view.jpg", "width": 1600, "height": 1067, "verified": "2026-10-23"}
        with mock.patch.dict(core.data.PHOTO_RECORDS, {q["country_id"]: rec}):
            answer(at, 0, correct=False)
        text = self.markdown(at)
        self.assertIn('class="photo-frame quiz-photo-frame"', text)
        for part in ("A test view", "A. Photographer", "CC BY-SA 4.0", 'loading="lazy"', 'width="1600" height="1067"'):
            self.assertIn(part, text)
        self.assertIn("Correct answer", text)                              # the existing feedback is still there
        # secondary details (points arithmetic, colour key) are kept, folded into one closed native section
        self.assertIn('<details class="feedback-more"><summary>Points and answer key</summary>', text)
        self.assertIn("Dashed red border = wrong answer", text)
        self.assertEqual([e.value for e in at.exception], [])

    def test_no_photograph_without_a_verified_record(self):
        import core.data
        import urllib.request
        at = self.start()
        q = at.session_state["quiz"]["questions"][0]
        with mock.patch.dict(core.data.PHOTO_RECORDS), mock.patch.object(urllib.request, "urlopen", side_effect=OSError("offline")):
            core.data.PHOTO_RECORDS.pop(q["country_id"], None)
            answer(at, 0)
        self.assertNotIn('<figure class="photo-frame quiz-photo-frame"', self.markdown(at))
        self.assertTrue(any(b.key and b.key.startswith("next_") for b in at.button))   # Next is still offered

    def test_results_keep_scoring_and_fold_details_and_review(self):
        at = self.start()
        q = at.session_state["quiz"]
        for i in range(5):
            answer(at, i, correct=i % 2 == 0)
            at.button(key=f"next_{q['serial']}_{i}").click().run()
        quiz = at.session_state["quiz"]
        self.assertTrue(quiz["finished"])
        self.assertEqual(sum(1 for h in quiz["history"] if h["correct"]), 3)
        self.assertEqual(quiz["score"], sum(h["points"]["total"] for h in quiz["history"]) + quiz["perfect_bonus"])
        details = [x for x in at.expander if x.proto.label == "Round details"]
        self.assertEqual(len(details), 1)
        self.assertFalse(details[0].proto.expanded)
        self.assertIn("Average response time", " ".join(c.value for c in details[0].caption))
        reviews = [x for x in at.expander if x.proto.label.startswith(("✕", "⏱", "✓"))]
        self.assertTrue(reviews)
        self.assertFalse(any(x.proto.expanded for x in reviews))           # a compact list: every answer starts closed
        for key in ("play_again", "change_settings", "results_explore"):
            self.assertIn(key, [b.key for b in at.button])
        self.assertEqual([e.value for e in at.exception], [])

    def test_new_strings_are_translated(self):
        import json
        strings = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))["strings"]
        for s in ("The quiz", "Test what you know.", "Round details", "Points and answer key"):
            self.assertEqual(len(strings[s]), 4, s)
            self.assertTrue(all(strings[s]), s)


if __name__ == "__main__":
    unittest.main()
