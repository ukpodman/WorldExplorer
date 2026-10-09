"""Pure-logic tests (no Streamlit needed).  Run:  python -m unittest discover tests"""
import json
import random
from itertools import combinations
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import quiz as q  # noqa: E402
from core.data import (AREAS, COLLECTIONS, CONTINENTS, COUNTRIES, COUNTRY_BY_ID, DEFAULT_COLLECTION, STATES,  # noqa: E402
                       get_countries, load_political_records, normalize_country, valid_political_record)
from core.i18n import LANGUAGES, STRINGS, missing_translations, render_parts, translate  # noqa: E402

BASE = {"continent": "World", "country_id": "all", "category": "Mixed", "difficulty": "Medium", "count": 50,
        "timer": False, "collection": DEFAULT_COLLECTION, "flags": True}
LEADERS = load_political_records(date(2026, 10, 8))
AREAS_LIST = ["World", "Africa", "Asia", "Europe", "Oceania"]
DIFFICULTIES_LIST = list(q.DIFFICULTIES)
QUESTION_COUNTS = q.QUESTION_COUNTS
REF = json.loads((ROOT / "data" / "reference" / "un_membership.json").read_text(encoding="utf-8"))
CURATION = json.loads((ROOT / "data" / "reference" / "curation.json").read_text(encoding="utf-8"))
RAW = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
STATE_NAMES = {c["name"] for c in STATES}


def every_round(counts=(25,), seeds=(1,), collections=COLLECTIONS, areas=AREAS):
    for collection in collections:
        for area in areas:
            for category in q.CATEGORIES:
                for difficulty in q.DIFFICULTIES:
                    for count in counts:
                        for seed in seeds:
                            settings = dict(BASE, continent=area, category=category, difficulty=difficulty,
                                            count=count, collection=collection)
                            yield settings, q.generate_quiz(settings, seed=seed, leaders=LEADERS)


class CoverageTests(unittest.TestCase):
    def test_every_un_member_and_observer_is_included(self):
        self.assertEqual(len(REF["members"]), 193)
        self.assertEqual(len(REF["observers"]), 2)
        ids = {c["id"] for c in COUNTRIES}
        self.assertEqual(sorted(set(REF["members"]) - ids), [])
        self.assertEqual(sorted(set(REF["observers"]) - ids), [])
        self.assertEqual(len(STATES), 195)
        self.assertEqual({c["id"] for c in STATES}, set(REF["members"]) | set(REF["observers"]))

    def test_ids_unique_and_holy_see_counted_once(self):
        ids = [c["id"] for c in RAW]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(c["id"] == "VAT" for c in RAW), 1)
        self.assertEqual(COUNTRY_BY_ID["VAT"]["status"], "un_observer")
        self.assertNotIn("HOLY", ids)

    def test_statuses_are_explicit_and_territories_not_called_states(self):
        for c in COUNTRIES:
            if c["id"] in REF["members"]:
                self.assertEqual(c["status"], "un_member", c["id"])
            elif c["id"] in REF["observers"]:
                self.assertEqual(c["status"], "un_observer", c["id"])
            else:
                self.assertNotIn(c["status"], ("un_member", "un_observer"), c["id"])
        self.assertEqual(COUNTRY_BY_ID["XKX"]["status"], "limited_recognition")
        self.assertEqual(COUNTRY_BY_ID["ESH"]["status"], "disputed_territory")
        self.assertEqual(COUNTRY_BY_ID["PRI"]["status"], "territory")

    def test_excluded_places_absent_and_counts_match_report(self):
        report = json.loads((ROOT / "data" / "reference" / "coverage.json").read_text(encoding="utf-8"))
        for uid in CURATION["excluded"]:
            self.assertNotIn(uid, COUNTRY_BY_ID)
        self.assertEqual(report["counts"]["total"], len(COUNTRIES))
        self.assertEqual(report["missing_from_collection"], [])
        self.assertEqual(report["duplicate_upstream_ids"], [])

    def test_every_place_reachable_from_every_view_filter(self):
        everything = get_countries(collection=COLLECTIONS[1])
        self.assertEqual(len(everything), len(COUNTRIES))
        for c in COUNTRIES:
            for continent in c["continents"]:
                self.assertIn(c, get_countries(continent, collection=COLLECTIONS[1]))
            self.assertEqual(get_countries(country_id=c["id"], collection=COLLECTIONS[1]), [c])
            self.assertTrue(c["flag"], c["id"])

    def test_corrected_facts_preserved(self):
        self.assertEqual(COUNTRY_BY_ID["LKA"]["borders"], [])
        self.assertNotIn("LKA", COUNTRY_BY_ID["IND"]["borders"])
        self.assertEqual([x["role"] for x in COUNTRY_BY_ID["BOL"]["capitals"]], ["constitutional capital", "seat of government"])
        self.assertEqual(len(COUNTRY_BY_ID["ZAF"]["capitals"]), 3)
        self.assertEqual(COUNTRY_BY_ID["MDA"]["languages"], ["Romanian"])
        self.assertEqual(COUNTRY_BY_ID["RUS"]["continents"], ["Europe", "Asia"])
        self.assertFalse(COUNTRY_BY_ID["ISR"]["capital_question"])

    def test_borders_are_symmetric(self):
        for c in COUNTRIES:
            for other in c["borders"]:
                self.assertIn(c["id"], COUNTRY_BY_ID[other]["borders"], f"{c['id']}–{other}")


class SchemaTests(unittest.TestCase):
    def test_every_record_is_valid(self):
        for raw in RAW:
            c = normalize_country(raw)
            self.assertIsNotNone(c, raw.get("id"))
            self.assertIn(c["continent"], CONTINENTS)
            self.assertTrue(set(c["continents"]) <= set(CONTINENTS))
            for field in ("capitals", "currencies", "languages", "borders", "domains", "calling_codes", "landmarks"):
                self.assertIsInstance(c[field], list, (c["id"], field))
            self.assertTrue(all(set(x) == {"name", "role"} for x in c["capitals"]))
            for lang in LANGUAGES[1:]:
                self.assertTrue(c["names"].get(lang), (c["id"], lang))

    def test_bad_records_are_rejected(self):
        self.assertIsNone(normalize_country({"id": "X"}))
        self.assertIsNone(normalize_country({"id": "X", "name": "X", "continent": "Atlantis"}))
        self.assertIsNone(normalize_country("not a record"))

    def test_missing_fields_only_remove_their_questions(self):
        sparse = normalize_country({"id": "ZZZ", "name": "Sparseland", "continent": "Europe", "status": "un_member"})
        self.assertIsNotNone(sparse)
        rng = random.Random(0)
        for category in q.CATEGORIES:
            items = q.question_candidates(sparse, category, "Expert", rng, {})
            for item in items:
                self.assertNotIn(item["family"], ("Capitals", "Currency", "Languages", "Flags", "Internet domains"))
        kinds = {i["family"] for i in q.question_candidates(sparse, "Mixed", "Easy", rng, {})}
        self.assertIn("Continents", kinds)

    def test_political_records_expire_and_dates_not_advanced(self):
        rec = {"names": ["A"], "title": "King", "source": "https://x", "verified_on": "2026-10-05"}
        self.assertTrue(valid_political_record(rec, date(2026, 10, 8)))
        self.assertFalse(valid_political_record(rec, date(2026, 10, 5) + timedelta(days=31)))
        self.assertFalse(valid_political_record(dict(rec, source="http://x"), date(2026, 10, 8)))
        self.assertEqual(load_political_records(date(2030, 1, 1)), {})
        bundled = json.loads((ROOT / "data" / "heads_of_state.json").read_text(encoding="utf-8"))
        self.assertTrue(all(r["verified_on"] <= "2026-10-08" for r in bundled.values()))


class AmbiguityTests(unittest.TestCase):
    """Every question has exactly one defensible answer among distinct choices."""

    @classmethod
    def setUpClass(cls):
        cls.rounds = list(every_round(counts=(25,), seeds=(1, 2)))
        cls.questions = [x for _, (qs, _) in cls.rounds for x in qs]

    def test_structure(self):
        self.assertGreater(len(self.questions), 5000)
        for x in self.questions:
            self.assertEqual(x["choices"].count(x["answer"]), 1, x["id"])
            self.assertEqual(len(set(x["choices"])), len(x["choices"]), x["id"])
            self.assertIn(len(x["choices"]), (2, 4), x["id"])
            self.assertTrue(x["explanation"] and x["source"].startswith("https://"), x["id"])

    def test_country_answers_are_states(self):
        country_prompts = re.compile(r"which country(?!-code)|which of these countries|In which country|Identify the country", re.I)
        for x in self.questions:
            template = x["prompt"][0][0]
            if country_prompts.search(template) and x["family"] not in ("Neighbours",):
                for choice in x["choices"]:
                    self.assertIn(choice, STATE_NAMES, (x["id"], choice))

    def test_specific_distractor_rules(self):
        lookalike = {frozenset(p) for p in CURATION["flag_lookalikes"]}
        names_to_id = {c["name"]: c["id"] for c in COUNTRIES}
        global_langs = set(CURATION["global_languages"])
        for x in self.questions:
            c = COUNTRY_BY_ID[x["country_id"]]
            wrong = [ch for ch in x["choices"] if ch != x["answer"]]
            if x["family"] == "Currency":
                self.assertFalse(any("(USD)" in w or "(EUR)" in w for w in wrong), x["id"])
            if x["family"] == "Languages":
                for w in wrong:
                    self.assertNotIn(w, global_langs, x["id"])
                    self.assertNotIn(w, c["languages"], x["id"])
            if x["family"] == "Flags":
                ids = [names_to_id[ch] for ch in x["choices"]]
                for a, b in combinations(ids, 2):
                    self.assertNotIn(frozenset((a, b)), lookalike, x["id"])
            if x["family"] in ("Internet domains", "Calling codes"):
                owners = q.DOMAIN_OWNERS if x["family"] == "Internet domains" else q.CODE_OWNERS
                self.assertEqual(owners[x["answer"]], {c["id"]}, x["id"])
            if x["family"] == "Landlocked":
                flags = [COUNTRY_BY_ID[names_to_id[ch]]["landlocked"] for ch in x["choices"]]
                self.assertEqual(sum(flags), 1, x["id"])
            if x["family"] == "Size comparisons":
                a, b = (COUNTRY_BY_ID[names_to_id[ch]]["area_km2"] for ch in x["choices"])
                self.assertGreater(max(a, b) / min(a, b), 1.2)
            if x["family"] == "Neighbour clues":
                clue_names = {v for _, f in x["prompt"] for k, v in f.items() if k in ("first", "second")}
                self.assertFalse(clue_names & set(x["choices"]), x["id"])
            if x["family"] == "Neighbours":
                for w in wrong:
                    self.assertNotIn(names_to_id[w], c["borders"], x["id"])
            if x["family"] == "Continents":
                self.assertEqual(len(c["continents"]), 1, x["id"])

    def test_answers_not_given_away(self):
        for x in self.questions:
            prompt = render_parts(x["prompt"])
            if x["family"] in ("Landmarks", "Country Identification") and x["answer"] in STATE_NAMES:
                self.assertFalse(q.reveals(prompt, x["answer"]), (x["id"], prompt))
            if x["family"] == "Continents":
                self.assertFalse(q.reveals(x["answer"], COUNTRY_BY_ID[x["country_id"]]["name"]), x["id"])


class RoundTests(unittest.TestCase):
    def test_no_fact_repeats_in_a_round(self):
        for settings, (questions, capacity) in every_round(counts=(50,), seeds=(3,), collections=COLLECTIONS[:1]):
            facts = [f for x in questions for f in x["facts"]]
            self.assertEqual(len(facts), len(set(facts)), settings)
            self.assertLessEqual(len(questions), max(capacity, 0) or len(questions))

    def test_reworded_and_reversed_facts_share_a_key(self):
        rng = random.Random(0)
        france = COUNTRY_BY_ID["FRA"]
        items = q.question_candidates(france, "Mixed", "Expert", rng, {})
        capital_facts = [i["facts"] for i in items if "capital:FRA:Paris" in i["facts"]]
        self.assertGreaterEqual(len(capital_facts), 3)  # forward, reverse, identification, true/false
        settings = dict(BASE, country_id="FRA", continent="Europe", difficulty="Expert")
        for seed in range(10):
            questions, _ = q.generate_quiz(settings, seed=seed, leaders={})
            self.assertLessEqual(sum("capital:FRA:Paris" in x["facts"] for x in questions), 1)

    def test_recent_facts_avoided_when_alternatives_exist(self):
        settings = dict(BASE, count=10)
        first, _ = q.generate_quiz(settings, seed=11, leaders={})
        seen_facts = [f for x in first for f in x["facts"]]
        seen_countries = [x["country_id"] for x in first]
        second, _ = q.generate_quiz(settings, recent=seen_countries, recent_facts=seen_facts, seed=12, leaders={})
        self.assertFalse(set(seen_facts) & {f for x in second for f in x["facts"]})
        self.assertFalse(set(seen_countries) & {x["country_id"] for x in second})

    def test_rounds_balance_countries_and_families(self):
        questions, _ = q.generate_quiz(dict(BASE, count=20), seed=5, leaders={})
        from collections import Counter
        self.assertEqual(max(Counter(x["country_id"] for x in questions).values()), 1)
        self.assertGreaterEqual(len({x["family"] for x in questions}), 8)

    def test_single_country_rounds(self):
        for c in STATES:
            settings = dict(BASE, country_id=c["id"], continent=c["continent"], count=25)
            questions, capacity = q.generate_quiz(settings, seed=1, leaders=LEADERS)
            self.assertTrue(questions, c["id"])
            self.assertEqual(len(questions), min(25, capacity), c["id"])
            self.assertLessEqual(sum(x["answer"] == c["name"] for x in questions), 1, c["id"])
            facts = [f for x in questions for f in x["facts"]]
            self.assertEqual(len(facts), len(set(facts)), c["id"])

    def test_small_pool_is_honest(self):
        settings = dict(BASE, country_id="VAT", continent="Europe", count=50)
        questions, capacity = q.generate_quiz(settings, seed=0, leaders=LEADERS)
        self.assertLess(len(questions), 50)
        self.assertEqual(len(questions), capacity)
        again, capacity2 = q.generate_quiz(settings, seed=1, leaders=LEADERS)
        self.assertEqual(capacity, capacity2)

    def test_territories_only_with_all_places(self):
        un, _ = q.generate_quiz(dict(BASE, count=50), seed=2, leaders={})
        self.assertTrue(all(COUNTRY_BY_ID[x["country_id"]]["status"] in ("un_member", "un_observer") for x in un))
        self.assertEqual(q.generate_quiz(dict(BASE, country_id="PRI", continent="North America"), seed=1, leaders={}), ([], 0))
        pr, _ = q.generate_quiz(dict(BASE, country_id="PRI", continent="North America", collection=COLLECTIONS[1]),
                                seed=1, leaders={})
        self.assertTrue(pr)

    def test_invalid_settings(self):
        self.assertEqual(q.generate_quiz(dict(BASE, count=7)), ([], 0))
        self.assertEqual(q.generate_quiz(dict(BASE, country_id="ZZZ")), ([], 0))
        self.assertEqual(q.generate_quiz(dict(BASE, collection="Moon")), ([], 0))
        self.assertEqual(q.generate_quiz({}), ([], 0))
        legacy = {k: v for k, v in BASE.items() if k not in ("collection", "flags")}
        self.assertTrue(q.generate_quiz(dict(legacy, count=5), seed=0, leaders={})[0])

    def test_shared_monarch_is_not_a_distractor(self):
        settings = dict(BASE, category="Heads of State", country_id="CAN", continent="North America")
        questions, _ = q.generate_quiz(settings, seed=0, leaders=LEADERS)
        self.assertEqual(questions[0]["choices"].count("Charles III"), 1)

    def test_missed_review_only_after_finish(self):
        questions, available = q.generate_quiz(dict(BASE, count=5, category="Capitals"), seed=0, leaders={})
        quiz = q.new_round(BASE, questions, available, serial=1)
        self.assertEqual(q.missed(quiz), [])
        for i in range(len(questions)):
            item = q.current_question(quiz)
            wrong = next(c for c in item["choices"] if c != item["answer"])
            q.resolve(quiz, wrong if i % 2 else item["answer"], now=1)
            self.assertEqual(q.missed(quiz), [])  # nothing exposed mid-round
            q.advance(quiz)
        self.assertEqual(len(q.missed(quiz)), 2)


class ScoringTests(unittest.TestCase):
    def make(self, timer=False, n=3):
        questions, available = q.generate_quiz(dict(BASE, count=5, timer=timer, category="Capitals"), seed=0, leaders={})
        return q.new_round(dict(BASE, timer=timer), questions[:n], available, serial=1)

    def test_perfect_round(self):
        quiz = self.make()
        for _ in range(3):
            q.elapsed(quiz, now=0)
            self.assertGreater(q.resolve(quiz, q.current_question(quiz)["answer"], now=1), 0)
            q.advance(quiz)
        self.assertTrue(quiz["finished"])
        self.assertEqual(quiz["perfect_bonus"], round(250 * 1.25))
        self.assertEqual(quiz["event"]["kind"], "perfect")  # a perfect round has its own celebration event

    def test_answers_are_recorded_once_and_events_unique(self):
        quiz = self.make()
        answer = q.current_question(quiz)["answer"]
        q.resolve(quiz, answer, now=1)
        first_event = quiz["event"]["id"]
        self.assertEqual(q.resolve(quiz, answer, now=1), 0)
        self.assertEqual(len(quiz["history"]), 1)
        q.advance(quiz)
        q.resolve(quiz, q.current_question(quiz)["answer"], now=1)
        self.assertNotEqual(first_event, quiz["event"]["id"])

    def test_timeout_and_late_hint(self):
        quiz = self.make(timer=True)
        q.elapsed(quiz, now=100)
        self.assertEqual(q.expire_if_due(quiz, now=110), 0)
        q.expire_if_due(quiz, now=125)
        self.assertTrue(quiz["history"][-1]["timed_out"])
        quiz = self.make(timer=True)
        q.elapsed(quiz, now=0)
        self.assertFalse(q.use_hint(quiz, now=30))
        self.assertEqual(quiz["hints_remaining"], 3)

    def test_hint_hides_a_wrong_option(self):
        quiz = self.make()
        self.assertTrue(q.use_hint(quiz, random.Random(0), now=0))
        question = q.current_question(quiz)
        self.assertNotIn(question["answer"], quiz["hidden_options"])
        self.assertEqual(q.resolve(quiz, quiz["hidden_options"][0], now=1), 0)
        self.assertFalse(quiz["resolved"])
        self.assertEqual(q.resolve(quiz, question["answer"], now=1), 125 + 25 - 25)

    def test_scoring(self):
        self.assertEqual(q.score_answer(False, "Expert", 1, 5)["total"], 0)
        self.assertEqual(q.score_answer(True, "Easy", 1, 1)["total"], 125)
        self.assertEqual(q.score_answer(True, "Expert", 20, 15, used_hint=True)["total"], 200 * 3 - 25)


class StreakScoringTests(unittest.TestCase):
    """Streak multiplier, resets, hints and duplicate events (quiz experience update)."""

    def make(self, n=6, timer=False, category="Capitals"):
        questions, available = q.generate_quiz(dict(BASE, count=10, timer=timer, category=category), seed=1, leaders={})
        return q.new_round(dict(BASE, timer=timer, category=category), questions[:n], available, serial=7)

    def play(self, quiz, outcome, hint=False, now=100):
        """Answer the current question right (True), wrong (False) or let it time out (None); 12 s keeps speed bonuses out."""
        question = q.current_question(quiz)
        if hint:
            q.use_hint(quiz, random.Random(0), now=now)
        q.elapsed(quiz, now=now)
        if outcome is None:
            points = q.expire_if_due(quiz, now=now + 60)
        else:
            choice = question["answer"] if outcome else next(c for c in question["choices"]
                                                             if c != question["answer"] and c not in quiz["hidden_options"])
            points = q.resolve(quiz, choice, now=now + 12)
        q.advance(quiz)
        return points

    def test_multiplier_boundaries(self):
        self.assertEqual([q.streak_multiplier(n) for n in range(9)], [1, 1, 1, 2, 2, 3, 3, 3, 3])
        base = round(100 * q.DIFFICULTY_MULTIPLIERS["Medium"])
        self.assertEqual([q.score_answer(True, "Medium", 20, n)["total"] for n in range(1, 8)],
                         [base, base, 2 * base, 2 * base, 3 * base, 3 * base, 3 * base])
        p = q.score_answer(True, "Expert", 1, 3)                     # fast answer: the speed bonus is flat
        self.assertEqual((p["base"], p["multiplier"], p["speed"], p["total"]), (200, 2, 25, 425))
        self.assertEqual(q.score_answer(False, "Expert", 1, 0)["total"], 0)

    def test_round_points_follow_the_streak(self):
        quiz = self.make()
        points = [self.play(quiz, ok) for ok in (True, True, True, True, True, True)]
        self.assertEqual(points, [125, 125, 250, 250, 375, 375])
        self.assertEqual([h["streak"] for h in quiz["history"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(quiz["perfect_bonus"], round(250 * 1.25))  # round bonus is never multiplied
        self.assertEqual(quiz["score"], sum(points) + quiz["perfect_bonus"])

    def test_wrong_answer_and_timeout_reset_the_streak(self):
        quiz = self.make()
        points = [self.play(quiz, ok) for ok in (True, True, True, False, True, True)]
        self.assertEqual(points, [125, 125, 250, 0, 125, 125])
        quiz = self.make(timer=True)
        points = [self.play(quiz, ok) for ok in (True, True, True, None, True, True)]
        self.assertEqual(points, [125, 125, 250, 0, 125, 125])
        self.assertTrue(quiz["history"][3]["timed_out"])
        self.assertEqual(quiz["best_streak"], 3)

    def test_new_round_starts_without_a_streak(self):
        quiz = self.make()
        for _ in range(4):
            self.play(quiz, True)
        fresh = q.new_round(quiz["settings"], quiz["questions"], quiz["available"], serial=8)
        self.assertEqual((fresh["streak"], fresh["best_streak"], fresh["score"]), (0, 0, 0))

    def test_hints_keep_the_streak_and_cost_25_after_multiplying(self):
        quiz = self.make()
        points = [self.play(quiz, True), self.play(quiz, True), self.play(quiz, True, hint=True), self.play(quiz, True)]
        self.assertEqual(points, [125, 125, 2 * 125 - 25, 2 * 125])
        self.assertEqual(quiz["history"][2]["points"]["hint"], 25)
        for _ in range(2):
            self.play(quiz, True)
        self.assertEqual(quiz["perfect_bonus"], 0)                  # a hint rules out the perfect-round bonus

    def test_duplicate_events_change_nothing(self):
        quiz = self.make(n=2)
        answer = q.current_question(quiz)["answer"]
        q.resolve(quiz, answer, now=1)
        snapshot = (quiz["score"], quiz["streak"], len(quiz["history"]))
        self.assertEqual(q.resolve(quiz, answer, now=1), 0)          # double click
        self.assertEqual(q.expire_if_due(quiz, now=999), 0)          # late timer tick
        self.assertEqual((quiz["score"], quiz["streak"], len(quiz["history"])), snapshot)
        q.advance(quiz)
        q.resolve(quiz, q.current_question(quiz)["answer"], now=1)
        self.assertEqual(q.advance(quiz), quiz["perfect_bonus"])
        score = quiz["score"]
        self.assertEqual(q.advance(quiz), 0)                         # finishing twice adds nothing
        self.assertEqual(quiz["score"], score)


class RecordTests(unittest.TestCase):
    def setUp(self):
        from core import records
        self.r = records

    def finished(self, score, streak, **settings):
        return {"settings": dict(BASE, **settings), "score": score, "best_streak": streak}

    def test_medal_thresholds_use_accuracy_only(self):
        cases = {0: None, 49.9: None, 50: "bronze", 69.9: "bronze", 70: "silver", 89.9: "silver", 90: "gold", 100: "gold"}
        for accuracy, expected in cases.items():
            self.assertEqual(self.r.medal(accuracy), expected, accuracy)

    def test_scores_compare_only_equivalent_settings(self):
        rec = self.r.empty_records()
        first = self.r.update(rec, self.finished(800, 3))
        self.assertTrue(first["first_score"])
        self.assertFalse(first["new_score"])
        lower = self.r.update(rec, self.finished(600, 2))
        self.assertEqual((lower["new_score"], lower["best_score"]), (False, 800))
        higher = self.r.update(rec, self.finished(900, 1))
        self.assertEqual((higher["new_score"], higher["previous_score"]), (True, 800))
        other = self.r.update(rec, self.finished(100, 1, count=5))   # different question count: its own record
        self.assertTrue(other["first_score"])
        timed = self.r.update(rec, self.finished(100, 1, timer=True))
        self.assertTrue(timed["first_score"])
        self.assertEqual(self.r.settings_key(dict(BASE, category="Capitals", flags=True)),
                         self.r.settings_key(dict(BASE, category="Capitals", flags=False)))  # flags only matter for Mixed
        self.assertNotEqual(self.r.settings_key(dict(BASE, category="Mixed", flags=True)),
                            self.r.settings_key(dict(BASE, category="Mixed", flags=False)))

    def test_streak_record_and_single_update_per_round(self):
        rec = self.r.empty_records()
        quiz = self.finished(500, 6)
        outcome = self.r.update(rec, quiz)
        self.assertTrue(outcome["new_streak"])
        self.assertIs(self.r.update(rec, quiz), outcome)             # a second call (rerun, double click) is ignored
        self.assertEqual((rec["best_streak"], len(rec["scores"])), (6, 1))
        self.assertFalse(self.r.update(rec, self.finished(10, 4))["new_streak"])
        self.assertEqual(rec["best_streak"], 6)

    def test_sanitize_keeps_old_and_rejects_corrupt_records(self):
        self.assertIsNone(self.r.sanitize_records("corrupt"))
        self.assertEqual(self.r.sanitize_records({}), self.r.empty_records())
        clean = self.r.sanitize_records({"best_streak": -3, "scores": {"a": 5, "b": "x", "c": True}})
        self.assertEqual(clean, {"best_streak": 0, "scores": {"a": 5}})
        many = self.r.empty_records()
        for i in range(self.r.MAX_SCORE_RECORDS + 5):
            self.r.update(many, self.finished(i, 0, count=QUESTION_COUNTS[i % 6], continent=AREAS_LIST[i % len(AREAS_LIST)],
                                              difficulty=DIFFICULTIES_LIST[i // 42 % 4]))
        self.assertLessEqual(len(many["scores"]), self.r.MAX_SCORE_RECORDS)


class FactTests(unittest.TestCase):
    def test_facts_never_repeat_the_tested_fact_or_reveal_later_answers(self):
        from core import facts
        from core.i18n import LANGUAGES, render_parts
        checked = 0
        for seed in range(25):
            for category in ("Mixed", "Capitals", "Geography / General Facts", "Country Identification"):
                questions, _ = q.generate_quiz(dict(BASE, category=category, count=10), seed=seed)
                for i, question in enumerate(questions):
                    fact = facts.pick(questions, i)
                    if fact is None:
                        continue
                    later = set().union(*(set(x["facts"]) for x in questions[i + 1:]))
                    self.assertFalse(set(fact["keys"]) & (set(question["facts"]) | later), (seed, category, i))
                    self.assertTrue(fact["source"].startswith("https://"))
                    for lang in LANGUAGES:
                        self.assertNotIn("{", render_parts(fact["parts"], lang))
                    checked += 1
        self.assertGreater(checked, 500)

    def test_fact_templates_are_translated_and_stable(self):
        from core import facts
        from core.i18n import STRINGS
        from core.data import COUNTRIES
        templates = {tpl for c in COUNTRIES for f in facts.candidates(c) for tpl, _ in f[1]}
        self.assertEqual([x for x in templates if x not in STRINGS], [])
        questions, _ = q.generate_quiz(dict(BASE, count=10), seed=3)
        self.assertEqual([facts.pick(questions, i) for i in range(10)], [facts.pick(questions, i) for i in range(10)])


class LearnHelperTests(unittest.TestCase):
    def setUp(self):
        from core import learn
        self.l = learn

    def test_step_wraps_and_handles_outside_and_single(self):
        ids = ["A", "B", "C"]
        self.assertEqual([self.l.step(ids, "B", 1), self.l.step(ids, "B", -1)], ["C", "A"])
        self.assertEqual([self.l.step(ids, "C", 1), self.l.step(ids, "A", -1)], ["A", "C"])  # wraps round
        self.assertEqual([self.l.step(ids, "X", 1), self.l.step(ids, "X", -1)], ["A", "C"])  # outside the scope
        self.assertIsNone(self.l.step(["A"], "A", 1))
        self.assertEqual(self.l.step(["A"], "X", 1), "A")
        self.assertIsNone(self.l.step([], "A", 1))

    def test_surprise_never_repeats_the_current_country(self):
        rng = random.Random(4)
        for _ in range(50):
            self.assertNotEqual(self.l.surprise(["A", "B", "C"], "B", rng), "B")
        self.assertEqual(self.l.surprise(["A", "B"], "A", rng), "B")
        self.assertIsNone(self.l.surprise(["A"], "A", rng))

    def test_neighbours_follow_the_places_collection(self):
        states = {c["id"] for c in get_countries()}
        everything = {c["id"] for c in get_countries(collection=COLLECTIONS[1])}
        shown, hidden = self.l.split_neighbours(COUNTRY_BY_ID["ESP"], states)
        self.assertEqual([n["id"] for n in hidden], ["GIB"])
        self.assertNotIn("GIB", [n["id"] for n in shown])
        shown, hidden = self.l.split_neighbours(COUNTRY_BY_ID["ESP"], everything)
        self.assertIn("GIB", [n["id"] for n in shown])
        self.assertEqual(hidden, [])
        self.assertEqual(self.l.split_neighbours(COUNTRY_BY_ID["ISL"], states), ([], []))  # no land neighbours

    def test_recall_cards_use_curated_fields(self):
        zaf = {x["kind"]: x for x in self.l.recall_items(COUNTRY_BY_ID["ZAF"])}
        self.assertIn("capitals", zaf["capital"]["question"][0][0])          # several capitals, with roles
        self.assertEqual(len(zaf["capital"]["answer"]), 3)
        isr = {x["kind"]: x for x in self.l.recall_items(COUNTRY_BY_ID["ISR"])}
        self.assertIsNone(isr["capital"]["answer"])                          # disputed capital: omitted, explained
        self.assertTrue(isr["capital"]["note"])
        zwe = {x["kind"]: x for x in self.l.recall_items(COUNTRY_BY_ID["ZWE"])}
        self.assertIsNone(zwe["currency"]["answer"])
        fra = {x["kind"]: x for x in self.l.recall_items(COUNTRY_BY_ID["FRA"])}
        self.assertIn("official status or wide use", fra["languages"]["question"][0][0])
        for c in COUNTRIES:
            for item in self.l.recall_items(c):
                self.assertTrue(item["answer"] or item["note"], (c["id"], item["kind"]))
                for lang in LANGUAGES:
                    if item["question"]:
                        self.assertNotIn("{", render_parts(item["question"], lang))
                    else:
                        self.assertTrue(translate(item["note"], lang))

    def test_area_comparison(self):
        fra, deu = COUNTRY_BY_ID["FRA"], COUNTRY_BY_ID["DEU"]
        r = self.l.compare_areas(deu, fra)
        self.assertEqual((r["kind"], r["larger"]["id"], r["smaller"]["id"]), ("ratio", "FRA", "DEU"))
        self.assertAlmostEqual(r["ratio"], 551695 / 357114)
        self.assertAlmostEqual(r["bars"]["DEU"], 100 * 357114 / 551695)
        self.assertEqual(r["bars"]["FRA"], 100.0)
        self.assertEqual(self.l.ratio_text(r["ratio"]), "1.5")
        self.assertEqual(self.l.compare_areas(fra, fra)["kind"], "same")
        missing = self.l.compare_areas(fra, COUNTRY_BY_ID["SJM"])
        self.assertEqual((missing["kind"], [m["id"] for m in missing["missing"]]), ("missing", ["SJM"]))
        tiny = self.l.compare_areas(COUNTRY_BY_ID["RUS"], COUNTRY_BY_ID["VAT"])
        self.assertTrue(tiny["tiny"])
        self.assertEqual(self.l.ratio_text(tiny["ratio"]), f"{round(17098242 / 0.44):,}")
        self.assertTrue(self.l.compare_areas(COUNTRY_BY_ID["FRA"], dict(fra, id="X", area_km2=540000))["similar"])


class TranslationTests(unittest.TestCase):
    def test_every_language_complete(self):
        self.assertEqual(missing_translations(), [])

    def test_templates_keep_their_fields(self):
        for key, variants in STRINGS.items():
            fields = sorted(set(re.findall(r"\{(\w+)\}", key)))
            for v in variants:
                self.assertEqual(sorted(set(re.findall(r"\{(\w+)\}", v))), fields, key)

    def test_every_question_renders_in_every_language(self):
        for settings, (questions, _) in every_round(counts=(10,), seeds=(4,), collections=COLLECTIONS[1:]):
            for x in questions:
                for lang in LANGUAGES:
                    for text in (render_parts(x["prompt"], lang), render_parts(x["explanation"], lang)):
                        self.assertNotIn("{", text, (x["id"], lang))
                    for choice in x["choices"]:
                        translate(choice, lang)

    def test_vocabulary_and_names_are_translated(self):
        self.assertEqual(translate("{name} is in {continent}.", "Deutsch", name="Japan", continent="Asia"), "Japan liegt in Asien.")
        self.assertEqual(translate("Germany", "Español"), "Alemania")
        self.assertEqual(translate("Germany", "中文（普通话）"), "德国")
        self.assertEqual(translate("Western Europe", "Deutsch"), "Westeuropa")
        self.assertEqual(translate("{name} is in {continent}.", LANGUAGES[0], name="Japan", continent="Asia"), "Japan is in Asia.")


class BadgeTests(unittest.TestCase):
    def setUp(self):
        from core import badges
        self.b = badges

    def test_arrange_shows_earned_then_three_closest_and_never_twice(self):
        cases = [(self.b.empty_stats(), 0, 0)]
        busy = self.b.empty_stats(); busy.update(answered=40, correct=30, flags_correct=7)
        cases.append((busy, 300, 3))
        for stats, points, rounds in cases:
            status = self.b.evaluate(stats, points, rounds)
            earned, upcoming, rest = self.b.arrange(status)
            ids = [b["id"] for b in earned + upcoming + rest]
            self.assertEqual(sorted(ids), sorted(b["id"] for b in self.b.BADGES))   # all 14, each once
            self.assertEqual(len(ids), 14)
            self.assertTrue(all(b["earned"] for b in earned))
            self.assertFalse(any(b["earned"] for b in upcoming + rest))
            self.assertLessEqual(len(upcoming), 3)
            ratio = lambda b: b["value"] / b["target"]
            if rest:
                self.assertGreaterEqual(min(map(ratio, upcoming)), max(map(ratio, rest)))
            self.assertEqual([b["id"] for b in earned], [b["id"] for b in status if b["earned"]])  # catalogue order
        self.assertEqual(self.b.evaluate(busy, 300, 3), self.b.evaluate(busy, 300, 3))  # evaluating is read-only

    def test_existing_badges_keep_their_rules(self):
        earned = self.b.earned_ids(self.b.empty_stats(), points=120, rounds=1)
        self.assertEqual(earned, {"first_steps", "century", "round_finisher"})  # old profiles keep what they had
        self.assertEqual(self.b.earned_ids(self.b.empty_stats(), 0, 0), set())

    def test_progress_comes_from_recorded_answers(self):
        stats = self.b.empty_stats()
        flag_q = {"family": "Flags", "country_id": "JPN"}
        for _ in range(10):
            self.b.record_answer(stats, flag_q, True)
        self.b.record_answer(stats, {"family": "Capitals", "country_id": "FRA"}, False)
        self.assertEqual((stats["answered"], stats["correct"], stats["flags_correct"]), (11, 10, 10))
        self.assertEqual(stats["correct_by_continent"]["Asia"], 10)
        earned = self.b.earned_ids(stats, points=1000, rounds=0)
        self.assertIn("flag_spotter", earned)
        self.assertIn("continent_asia", earned)
        self.assertNotIn("globetrotter", earned)
        status = {x["id"]: x for x in self.b.evaluate(stats, 1000, 0)}
        self.assertEqual((status["globetrotter"]["value"], status["globetrotter"]["target"]), (1, 6))

    def test_perfect_round_counted_once_per_round(self):
        stats = self.b.empty_stats()
        self.b.record_round(stats, {"perfect_bonus": 250})
        self.b.record_round(stats, {"perfect_bonus": 0})
        self.assertEqual(stats["perfect_rounds"], 1)

    def test_stored_stats_are_validated(self):
        self.assertIsNone(self.b.sanitize_stats("nope"))
        clean = self.b.sanitize_stats({"correct": 4, "answered": -2, "flags_correct": True,
                                       "correct_by_continent": {"Asia": 3, "Mars": 9, "Europe": "x"}})
        self.assertEqual(clean["correct"], 4)
        self.assertEqual(clean["answered"], 0)
        self.assertEqual(clean["flags_correct"], 0)
        self.assertEqual(clean["correct_by_continent"]["Asia"], 3)
        self.assertNotIn("Mars", clean["correct_by_continent"])
        self.assertEqual(self.b.sanitize_stats({}), self.b.empty_stats())

    def test_badge_text_translated(self):
        for b in self.b.BADGES:
            for _ in LANGUAGES[1:]:
                self.assertIn(b["name"], STRINGS, b["id"])
                self.assertIn(b["description"], STRINGS, b["id"])
        self.assertEqual(translate("{continent} Explorer", "Deutsch", continent="Africa"), "Afrika-Entdecker")


if __name__ == "__main__":
    unittest.main()
