"""Run with:  python -m unittest discover tests   (or: pytest)"""
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import quiz as q  # noqa: E402
from core.data import COUNTRIES, COUNTRY_BY_ID, load_political_records, normalize_country, valid_political_record  # noqa: E402
from core.i18n import LANGUAGES, STRINGS, missing_translations, render_parts, translate  # noqa: E402

BASE = {"continent": "World", "country_id": "all", "category": "Mixed", "difficulty": "Medium", "count": 50, "timer": False}


class DataTests(unittest.TestCase):
    def test_records_are_complete(self):
        self.assertGreater(len(COUNTRIES), 80)
        for c in COUNTRIES:
            self.assertTrue(c["capitals"], c["id"])
            self.assertEqual(len(c["id"]), 3)

    def test_borders_are_symmetric_within_collection(self):
        for c in COUNTRIES:
            for other in c["borders"]:
                if other in COUNTRY_BY_ID:
                    self.assertIn(c["id"], COUNTRY_BY_ID[other]["borders"], f"{c['id']}–{other}")

    def test_bad_records_are_rejected(self):
        self.assertIsNone(normalize_country({"id": "X"}))
        self.assertIsNone(normalize_country({"id": "X", "name": "X", "continent": "Atlantis"}))

    def test_political_records_expire(self):
        rec = {"names": ["A"], "title": "King", "source": "https://x", "verified_on": "2026-10-05"}
        self.assertTrue(valid_political_record(rec, date(2026, 10, 8)))
        self.assertFalse(valid_political_record(rec, date(2026, 10, 5) + timedelta(days=31)))
        self.assertFalse(valid_political_record(dict(rec, source="http://x"), date(2026, 10, 8)))
        self.assertEqual(load_political_records(date(2030, 1, 1)), {})


class GenerationTests(unittest.TestCase):
    def check(self, questions):
        for question in questions:
            self.assertEqual(question["choices"].count(question["answer"]), 1, question["id"])
            self.assertEqual(len(set(question["choices"])), len(question["choices"]), question["id"])
            self.assertIn(len(question["choices"]), (2, 4))
            render_parts(question["prompt"])  # every template must format
            render_parts(question["explanation"])

    def test_every_category_and_difficulty(self):
        leaders = load_political_records(date(2026, 10, 8))
        for category in q.CATEGORIES:
            for difficulty in q.DIFFICULTIES:
                settings = dict(BASE, category=category, difficulty=difficulty)
                questions, capacity = q.generate_quiz(settings, seed=1, leaders=leaders)
                self.assertTrue(questions, (category, difficulty))
                self.assertLessEqual(len(questions), capacity)
                self.check(questions)

    def test_no_fact_repeats_in_a_round(self):
        for seed in range(5):
            questions, _ = q.generate_quiz(BASE, seed=seed, leaders={})
            facts = [f for x in questions for f in x["facts"]]
            self.assertEqual(len(facts), len(set(facts)))

    def test_single_country_has_no_self_answering_questions(self):
        settings = dict(BASE, country_id="JPN", difficulty="Expert")
        questions, _ = q.generate_quiz(settings, seed=3, leaders={})
        self.assertTrue(questions)
        for question in questions:
            if question["family"] != "Size comparisons":
                self.assertNotEqual(question["answer"], "Japan", question["id"])

    def test_invalid_settings(self):
        self.assertEqual(q.generate_quiz(dict(BASE, count=7)), ([], 0))
        self.assertEqual(q.generate_quiz(dict(BASE, country_id="ZZZ")), ([], 0))
        self.assertEqual(q.generate_quiz({}), ([], 0))

    def test_shared_monarch_is_not_a_distractor(self):
        leaders = load_political_records(date(2026, 10, 8))
        settings = dict(BASE, category="Heads of State", country_id="CAN", continent="North America")
        questions, _ = q.generate_quiz(settings, seed=0, leaders=leaders)
        self.assertEqual(questions[0]["choices"].count("Charles III"), 1)


class RoundTests(unittest.TestCase):
    def make(self, timer=False, n=3):
        questions, available = q.generate_quiz(dict(BASE, count=5, timer=timer, category="Capitals"), seed=0, leaders={})
        return q.new_round(BASE | {"timer": timer}, questions[:n], available, serial=1)

    def test_perfect_round(self):
        quiz = self.make()
        for i in range(3):
            q.elapsed(quiz, now=0)
            self.assertGreater(q.resolve(quiz, q.current_question(quiz)["answer"], now=1), 0)
            q.advance(quiz)
        self.assertTrue(quiz["finished"])
        self.assertEqual(quiz["perfect_bonus"], round(250 * 1.25))
        self.assertEqual(q.statistics(quiz)["accuracy"], 100)

    def test_answers_are_recorded_once(self):
        quiz = self.make()
        answer = q.current_question(quiz)["answer"]
        q.resolve(quiz, answer, now=1)
        self.assertEqual(q.resolve(quiz, answer, now=1), 0)
        self.assertEqual(len(quiz["history"]), 1)

    def test_timeout(self):
        quiz = self.make(timer=True)
        q.elapsed(quiz, now=100)
        self.assertEqual(q.expire_if_due(quiz, now=110), 0)
        self.assertFalse(quiz["resolved"])
        q.expire_if_due(quiz, now=125)
        self.assertTrue(quiz["history"][-1]["timed_out"])
        self.assertEqual(q.statistics(quiz)["timed_out"], 1)

    def test_late_hint_records_timeout(self):
        quiz = self.make(timer=True)
        q.elapsed(quiz, now=0)
        self.assertFalse(q.use_hint(quiz, now=30))
        self.assertTrue(quiz["history"][-1]["timed_out"])
        self.assertEqual(quiz["hints_remaining"], 3)

    def test_hint_hides_a_wrong_option(self):
        quiz = self.make()
        self.assertTrue(q.use_hint(quiz, random.Random(0), now=0))
        question = q.current_question(quiz)
        self.assertNotIn(question["answer"], quiz["hidden_options"])
        self.assertEqual(q.resolve(quiz, quiz["hidden_options"][0], now=1), 0)  # hidden options cannot be chosen
        self.assertFalse(quiz["resolved"])
        self.assertEqual(q.resolve(quiz, question["answer"], now=1), 125 + 25 - 25)  # Medium base + speed − hint

    def test_scoring(self):
        self.assertEqual(q.score_answer(False, "Expert", 1, 5)["total"], 0)
        self.assertEqual(q.score_answer(True, "Easy", 1, 1)["total"], 125)
        self.assertEqual(q.score_answer(True, "Expert", 20, 15, used_hint=True)["total"], 200 + 150 - 25)


class TranslationTests(unittest.TestCase):
    def test_every_language_complete(self):
        self.assertEqual(missing_translations(), [])

    def test_templates_keep_their_fields(self):
        for key, variants in STRINGS.items():
            fields = sorted(set(__import__("re").findall(r"\{(\w+)\}", key)))
            for v in variants:
                self.assertEqual(sorted(set(__import__("re").findall(r"\{(\w+)\}", v))), fields, key)

    def test_vocabulary_fields_are_translated(self):
        self.assertEqual(translate("{name} is in {continent}.", "Deutsch", name="Japan", continent="Asia"),
                         "Japan liegt in Asien.")
        self.assertEqual(translate("{name} is in {continent}.", LANGUAGES[0], name="Japan", continent="Asia"),
                         "Japan is in Asia.")


if __name__ == "__main__":
    unittest.main()
