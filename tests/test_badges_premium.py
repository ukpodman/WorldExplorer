"""Premium Badges (Project Atlas): the gallery presentation; badge rules and progress come from core/badges.py."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import badges  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")


def _stats(**kw):
    stats = badges.empty_stats()
    by = kw.pop("by", {})
    stats.update(kw)
    stats["correct_by_continent"].update(by)
    return stats


class RemainingTextTests(unittest.TestCase):
    """The 'still needed' line is built only from each badge's own value and target."""

    def setUp(self):
        from ui import pages
        self.pages = pages

    def test_every_badge_has_a_remaining_template(self):
        for b in badges.evaluate(badges.empty_stats(), 0, 0):
            self.assertTrue(self.pages._remaining_text(b), b["id"])

    def test_counts_and_singular(self):
        status = {b["id"]: b for b in badges.evaluate(_stats(flags_correct=8, correct=49, by={"Asia": 4}), 60, 4)}
        self.assertEqual(self.pages._remaining_text(status["flag_spotter"]), "2 more correct flags to unlock.")
        self.assertEqual(self.pages._remaining_text(status["fifty_correct"]), "1 more correct answer to unlock.")
        self.assertEqual(self.pages._remaining_text(status["five_rounds"]), "1 more round to unlock.")
        self.assertEqual(self.pages._remaining_text(status["century"]), "40 more points to unlock.")
        self.assertEqual(self.pages._remaining_text(status["continent_asia"]), "1 more correct answer about Asia to unlock.")

    def test_new_strings_are_translated(self):
        strings = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))["strings"]
        keys = [k for pair in self.pages._REMAINING.values() for k in pair if k] + [
            "Celebrate your progress.", "{earned} of {total} badges earned"]
        for k in keys:
            self.assertEqual(len(strings.get(k, [])), 4, k)
            self.assertTrue(all(strings[k]), k)
            if "{n}" in k:
                self.assertTrue(all("{n}" in v for v in strings[k]), k)


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class BadgesPageTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def test_summary_gallery_and_progress(self):
        stats = _stats(answered=20, correct=12, flags_correct=8, by={"Europe": 3, "Asia": 2})
        at = self.new(page="Badges", stats=stats, points=450, rounds_finished=2)
        self.assertEqual([e.value for e in at.exception], [])
        markup = " ".join(str(m.value) for m in at.markdown)
        status = badges.evaluate(stats, 450, 2)
        earned = [b for b in status if b["earned"]]
        self.assertEqual(len(status), 14)
        self.assertIn(f"{len(earned)} of 14 badges earned", markup)
        self.assertEqual(markup.count('class="award-card earned"'), len(earned))
        self.assertEqual(markup.count('class="award-card locked"'), 14 - len(earned))
        self.assertIn("<b>8/10</b> · 2 more correct flags to unlock.", markup)        # the example in the brief
        self.assertIn('aria-valuenow="8"', markup)
        self.assertIn("Celebrate your progress.", markup)
        # viewing never changes progress
        before = (dict(at.session_state["stats"]), at.session_state["points"], at.session_state["rounds_finished"])
        at.run()
        self.assertEqual((dict(at.session_state["stats"]), at.session_state["points"], at.session_state["rounds_finished"]), before)

    def test_practise_link_for_the_closest_badge_opens_quiz_setup(self):
        stats = _stats(answered=6, correct=4, by={"Africa": 4})   # Africa Explorer is 4/5: the closest badge
        at = self.new(page="Badges", stats=stats, points=0, rounds_finished=0)
        at.button(key="badges_practise_goal").click().run()
        self.assertEqual(at.session_state["filter_continent"], "Africa")
        self.assertEqual(at.session_state["page"], "Quiz")
        self.assertEqual([e.value for e in at.exception], [])

    def test_all_earned_and_none_earned(self):
        at = self.new(page="Badges", stats=badges.empty_stats(), points=0, rounds_finished=0)
        self.assertIn("0 of 14 badges earned", " ".join(str(m.value) for m in at.markdown))
        self.assertIn("No badges yet", " ".join(str(m.value) for m in at.markdown))
        full = _stats(answered=200, correct=120, perfect_rounds=1, flags_correct=10,
                      by={c: 5 for c in badges.CONTINENTS})
        at = self.new(page="Badges", stats=full, points=5000, rounds_finished=6)
        markup = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("14 of 14 badges earned", markup)
        self.assertNotIn('class="award-card locked"', markup)
        self.assertEqual([e.value for e in at.exception], [])


if __name__ == "__main__":
    unittest.main()
