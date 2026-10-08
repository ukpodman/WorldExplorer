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
        self.assertEqual(quiz["event"]["kind"], "complete")

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
        self.assertEqual(q.score_answer(True, "Expert", 20, 15, used_hint=True)["total"], 200 + 150 - 25)


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


if __name__ == "__main__":
    unittest.main()
