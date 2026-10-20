"""Streamlit tests (need streamlit installed).  Run:  python -m unittest discover tests

They drive the real app with streamlit.testing.v1.AppTest and exercise the account
code with a stand-in for Streamlit's session, secrets and user objects. They cannot
contact Google or Supabase.
"""
import sys
import types
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
LANGS = ("English", "Deutsch", "Español", "中文（普通话）", "Русский")


def audio_count(at) -> int:
    return len(at.get("audio"))


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class AppTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def assertClean(self, at, context=""):
        self.assertEqual([e.value for e in at.exception], [], context)

    def test_every_page_in_every_language(self):
        for lang in LANGS:
            at = self.new(app_language=lang)
            self.assertClean(at, lang)
            for page in ("Learn", "Quiz", "Badges", "Explore"):
                at.button(key=f"nav_{page}").click().run()
                self.assertClean(at, f"{lang} {page}")

    def test_explore_paginates_and_filters(self):
        at = self.new(explore_selected="Europe")
        cards = [b for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertEqual(len(cards), 10)  # ten list rows per page, never hundreds at once
        at.text_input(key="explore_search").input("Bern").run()
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("discover_")], ["discover_CHE"])
        at = self.new(scope_collection="All countries and territories", explore_selected="Africa")
        at.selectbox(key="explore_status").select("territory").run()
        self.assertClean(at)
        self.assertTrue(any("Territory or dependency" in m.value for m in at.markdown))
        if not at.button(key="explore_next").disabled:
            at.button(key="explore_next").click().run()
        self.assertClean(at)

    def test_learn_shows_status_flag_and_corrected_facts(self):
        at = self.new(page="Learn", learn_country="LKA")
        self.assertClean(at)
        text = " ".join(m.value for m in at.markdown)
        self.assertTrue(any("has no land borders with other places in this dataset." in c.value for c in at.caption))
        self.assertGreaterEqual(len(at.get("image")), 1)
        at = self.new(page="Learn", learn_country="VAT")
        self.assertIn("UN observer state", " ".join(m.value for m in at.markdown))

    def _play_round(self, at, wrong_every=2):
        at.button(key="nav_Quiz").click().run()
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        self.assertClean(at)
        quiz = at.session_state["quiz"]
        for i in range(len(quiz["questions"])):
            question = at.session_state["quiz"]["questions"][i]
            page = " ".join(m.value for m in at.markdown) + " ".join(b.label for b in at.button)
            self.assertNotIn("Correct answer", page)  # nothing revealed before submission
            pick = question["answer"] if i % wrong_every else next(c for c in question["choices"] if c != question["answer"])
            serial = at.session_state["quiz"]["serial"]
            at.button(key=f"answer_{serial}_{i}_{question['choices'].index(pick)}").click().run()
            self.assertTrue(at.session_state["quiz"]["resolved"])
            yield at
            at.button(key=f"next_{serial}_{i}").click().run()
        self.assertTrue(at.session_state["quiz"]["finished"])

    def test_full_round_with_missed_review(self):
        at = self.new()
        for _ in self._play_round(at):
            pass
        self.assertClean(at)
        subheaders = [h.value for h in at.subheader]
        self.assertIn("Review missed answers", subheaders)
        missed = [x for x in at.session_state["quiz"]["history"] if not x["correct"]]
        self.assertEqual(len([e for e in at.expander if e.label.startswith("✕")]), len(missed))

    def test_sound_off_by_default_and_never_replayed(self):
        at = self.new()
        self.assertFalse(at.session_state["sound_enabled"])
        for step in self._play_round(at):
            self.assertEqual(audio_count(step), 0)
        at = self.new(sound_enabled=True, sound_volume=40)
        for step in self._play_round(at):
            self.assertEqual(audio_count(step), 1)        # one short sound right after answering
            step.run()
            self.assertEqual(audio_count(step), 0)        # a rerun never replays it
        self.assertEqual(audio_count(at), 1)              # round-complete sound on the results page
        at.run()
        self.assertEqual(audio_count(at), 0)

    def test_single_country_and_small_pool(self):
        at = self.new(page="Quiz")
        at.selectbox(key="filter_continent").select("Europe").run()
        at.selectbox(key="filter_country").select("VAT").run()
        at.button_group(key="filter_count").set_value(50).run()
        info = " ".join(i.value for i in at.info)
        self.assertIn("This round will contain", info)
        at.button(key="start_quiz").click().run()
        self.assertClean(at)
        questions = at.session_state["quiz"]["questions"]
        self.assertLess(len(questions), 50)
        self.assertLessEqual(sum(x["answer"] == "Vatican City" for x in questions), 1)

    def test_guest_sign_in_fallback_without_secrets(self):
        at = self.new(settings_open=True)
        self.assertClean(at)
        google = at.button(key="profile_google")
        self.assertTrue(google.disabled)
        self.assertTrue(any("keep playing as a guest" in i.value for i in at.info))


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class RefinementTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    def test_quiz_me_carries_country_and_keeps_active_round(self):
        at = self.new(page="Learn", learn_country="JPN")
        at.button(key="learn_quiz_me").click().run()
        self.assertEqual(at.session_state["page"], "Quiz")
        self.assertEqual((at.session_state["filter_continent"], at.session_state["filter_country"]), ("Asia", "JPN"))
        self.assertEqual([e.value for e in at.exception], [])
        at.button(key="start_quiz").click().run()
        serial = at.session_state["quiz"]["serial"]
        at.button(key="nav_Learn").click().run()
        at.button(key="learn_quiz_me").click().run()
        self.assertEqual(at.session_state["quiz"]["serial"], serial)          # the round was not discarded
        self.assertFalse(at.session_state["quiz"]["finished"])
        self.assertTrue(any("round in progress" in i.value for i in at.info))

    def test_quiz_me_on_a_territory_switches_to_all_places(self):
        at = self.new(page="Learn", learn_country="PRI")
        at.button(key="learn_quiz_me").click().run()
        self.assertEqual(at.session_state["filter_collection"], "All countries and territories")
        self.assertEqual(at.session_state["filter_country"], "PRI")
        self.assertEqual([e.value for e in at.exception], [])

    def test_quiz_filters_survive_leaving_the_page(self):
        at = self.new(page="Quiz")
        at.selectbox(key="filter_category").select("Capitals").run()
        at.button_group(key="filter_difficulty").set_value("Expert").run()
        at.button(key="nav_Explore").click().run()
        at.button(key="nav_Badges").click().run()
        at.button(key="nav_Quiz").click().run()
        self.assertEqual(at.selectbox(key="filter_category").value, "Capitals")
        self.assertEqual(at.button_group(key="filter_difficulty").value, "Expert")
        self.assertEqual([w.value for w in at.warning], [])

    def test_badges_recorded_once_from_quiz_activity(self):
        at = self.new(page="Badges")
        self.assertEqual(at.session_state["stats"]["answered"], 0)        # opening Badges records nothing
        at.run()
        self.assertEqual(at.session_state["stats"]["answered"], 0)
        at.button(key="nav_Quiz").click().run()
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        for i in range(5):
            quiz = at.session_state["quiz"]
            q = quiz["questions"][i]
            at.button(key=f"answer_{quiz['serial']}_{i}_{q['choices'].index(q['answer'])}").click().run()
            at.run()                                                     # extra reruns must not double count
            at.button(key=f"next_{quiz['serial']}_{i}").click().run()
        stats = at.session_state["stats"]
        self.assertEqual((stats["answered"], stats["correct"]), (5, 5))
        self.assertEqual(at.session_state["rounds_finished"], 1)
        self.assertTrue(any("New badge earned" in s.value for s in at.success))
        at.run(); at.run()
        self.assertEqual(at.session_state["stats"]["answered"], 5)
        at.button(key="nav_Badges").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertTrue(any("Earned badges" in m.value for m in at.markdown))

    # ---------------------------------------------------------------- compact layout (8 per page, badges)

    def _walk_explore(self, at):
        """Click Next until the last page; return the Discover keys of every page in order."""
        pages = []
        while True:
            self.assertEqual([e.value for e in at.exception], [])
            pages.append([b.key for b in at.button if b.key and b.key.startswith("discover_")])
            if at.button(key="explore_next").disabled:
                return pages
            at.button(key="explore_next").click().run()

    def test_every_country_reachable_once_through_pagination(self):
        from core.data import get_countries
        continents = ("Africa", "Asia", "Europe", "North America", "South America", "Oceania")
        for collection, total in (("UN member and observer states", 195), ("All countries and territories", 244)):
            seen = set()
            for continent in continents:
                at = self.new(scope_collection=collection, explore_selected=continent)
                pages = self._walk_explore(at)
                keys = [k for page in pages for k in page]
                self.assertEqual(len(keys), len(set(keys)), (collection, continent))                 # no duplicates
                self.assertTrue(all(len(p) == 10 for p in pages[:-1]) and 1 <= len(pages[-1]) <= 10)  # no gaps
                self.assertIn(f"/ {len(pages)}", " ".join(c.value for c in at.caption))
                self.assertTrue(any(f">{len(keys)} countries" in m.value for m in at.markdown if 'class="continent-count"' in m.value))
                expected = {c["id"] for c in get_countries(continent, collection=collection)}
                self.assertEqual({k.removeprefix("discover_") for k in keys}, expected, (collection, continent))
                seen |= expected
            self.assertEqual(len(seen), total)        # every place is reachable through its continent
        for filters in ({"explore_status": "territory"}, {"explore_search": "an"}):
            at = self.new(scope_collection="All countries and territories", explore_selected="Europe")
            for key, value in filters.items():
                (at.text_input(key=key).input(value) if key == "explore_search" else at.selectbox(key=key).select(value)).run()
            pages = self._walk_explore(at)
            keys = [k for page in pages for k in page]
            self.assertEqual(len(keys), len(set(keys)), filters)
            self.assertIn(f"/ {len(pages)}", " ".join(c.value for c in at.caption))

    def test_explore_has_no_second_challenge_card(self):
        """The Daily Challenge banner is the only challenge entry on Explore — also when nothing matches."""
        from core.i18n import translate
        for lang in LANGS:
            at = self.new(app_language=lang, explore_selected="Asia")
            for search in ("", "zzzz-no-match"):
                if search:
                    at.text_input(key="explore_search").input(search).run()
                keys = [b.key for b in at.button]
                self.assertNotIn("atlas_take_quiz", keys, (lang, search))
                self.assertIn("explore_daily", keys, (lang, search))                  # the challenge stays
                text = " ".join(m.value for m in at.markdown)
                self.assertNotIn(translate("Your next challenge", lang), text, (lang, search))
                self.assertNotIn("atlas_quiz", str(at), (lang, search))
            self.assertTrue(any(translate("No countries match your search.", lang) in i.value for i in at.info))
            self.assertEqual([e.value for e in at.exception], [], lang)

    def test_eighth_card_takes_the_old_challenge_slot(self):
        at = self.new(explore_selected="Asia")
        keys = [b.key for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertEqual(len(keys), 10)
        at.button(key="explore_next").click().run()
        second = [b.key for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertEqual(len(second), 10)
        self.assertFalse(set(keys) & set(second))                    # page 2 starts with the ninth country
        at.button(key=second[7]).click().run()                        # the arrow shows the country beside the list
        self.assertEqual((at.session_state["page"], at.session_state["explore_country"]), ("Explore", second[7].removeprefix("discover_")))
        at.button(key="detail_learn").click().run()
        self.assertEqual(at.session_state["page"], "Learn")

    def test_seventh_card_discover_opens_learn(self):
        at = self.new(explore_selected="Africa")
        seventh = [b.key for b in at.button if b.key and b.key.startswith("discover_")][6]
        at.button(key=seventh).click().run()
        code = seventh.removeprefix("discover_")
        self.assertEqual(at.session_state["explore_country"], code)
        self.assertTrue(any('class="detail-name"' in m.value for m in at.markdown))          # discovered on the right
        self.assertNotIn("world_map_frame", str([c for c in at.markdown if "map-heading" in c.value]))
        at.button(key="detail_learn").click().run()
        self.assertEqual(at.session_state["page"], "Learn")
        self.assertEqual(at.session_state["learn_country"], code)

    def test_badges_show_each_badge_once_and_viewing_changes_nothing(self):
        from core import badges
        stats = badges.empty_stats()
        stats.update(answered=12, correct=9, flags_correct=4)
        at = self.new(page="Badges", stats=stats, points=450, rounds_finished=2)
        self.assertEqual([e.value for e in at.exception], [])
        markup = " ".join(m.value for m in at.markdown)
        status = badges.evaluate(stats, 450, 2)
        for b in status:
            name = b["name"].format(**b["fields"]) if b["fields"] else b["name"]
            self.assertEqual(markup.count(f'<div class="award-name">{name}</div>'), 1, name)
        earned, upcoming, rest = badges.arrange(status)
        more = [e for e in at.expander if e.label.startswith("See all badges")]
        self.assertEqual(len(more), 1)
        self.assertIn(f"({len(rest)} more)", more[0].label)
        before = (dict(at.session_state["stats"]), at.session_state["points"], at.session_state["rounds_finished"])
        at.run(); at.run()
        self.assertEqual((dict(at.session_state["stats"]), at.session_state["points"], at.session_state["rounds_finished"]), before)

    # ---------------------------------------------------------------- quiz experience (streaks, facts, records)

    def test_stale_double_clicks_never_count_twice(self):
        """A double click can deliver a second, stale callback before the page redraws: it must change nothing."""
        from ui import state as ui_state
        fake = fake_streamlit(logged_in=False)
        with mock.patch.object(ui_state, "st", fake):
            ui_state.init()
            settings = {"continent": "World", "country_id": "all", "category": "Capitals", "difficulty": "Medium",
                        "count": 5, "timer": False, "flags": True}
            self.assertTrue(ui_state.start_round(settings))
            ss = fake.session_state
            serial = ss.quiz["serial"]
            for i in range(5):
                answer = ss.quiz["questions"][i]["answer"]
                ui_state.answer(answer, serial, i)
                ui_state.answer(answer, serial, i)                  # stale second click on the answer
                ui_state.next_question(serial, i)
                ui_state.next_question(serial, i)                   # stale second click on Next / View results
            self.assertEqual(len(ss.quiz["history"]), 5)
            self.assertEqual((ss.rounds_finished, ss.stats["answered"], ss.stats["correct"]), (1, 5, 5))
            self.assertEqual(ss.points, ss.quiz["score"])
            self.assertEqual((ss.records["best_streak"], len(ss.records["scores"])), (5, 1))
            self.assertEqual(ss.stats["perfect_rounds"], 1)

    def _answer_all(self, at, correct=True, double=False):
        quiz = at.session_state["quiz"]
        for i in range(len(quiz["questions"])):
            quiz = at.session_state["quiz"]
            qn = quiz["questions"][i]
            pick = qn["answer"] if correct else next(c for c in qn["choices"] if c != qn["answer"])
            key = f"answer_{quiz['serial']}_{i}_{qn['choices'].index(pick)}"
            at.button(key=key).click().run()
            if double:
                at.run()                                            # unrelated reruns record nothing
                at.run()
            at.button(key=f"next_{quiz['serial']}_{i}").click().run()
            if double and i + 1 < len(quiz["questions"]):
                self.assertEqual(at.session_state["quiz"]["index"], i + 1)
        return at

    def test_streak_multiplier_records_and_no_double_counting(self):
        at = self.new(page="Quiz")
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        self._answer_all(at, correct=True, double=True)
        quiz = at.session_state["quiz"]
        self.assertTrue(quiz["finished"])
        self.assertEqual([h["points"]["multiplier"] for h in quiz["history"]], [1, 1, 2, 2, 3])
        self.assertEqual(len(quiz["history"]), 5)
        self.assertEqual(at.session_state["points"], quiz["score"])  # totals match the round exactly once
        self.assertEqual(at.session_state["rounds_finished"], 1)
        self.assertEqual(at.session_state["stats"]["correct"], 5)
        records = at.session_state["records"]
        self.assertEqual((records["best_streak"], len(records["scores"])), (5, 1))
        markup = " ".join(m.value for m in at.markdown)
        self.assertIn("First score for these settings", markup)
        self.assertIn("Gold medal", markup)
        self.assertIn("Perfect round", markup)
        for _ in range(3):
            at.run()
        self.assertEqual((at.session_state["rounds_finished"], at.session_state["records"]["best_streak"]), (1, 5))
        at.button(key="play_again").click().run()
        self.assertEqual(at.session_state["quiz"]["streak"], 0)        # a new round starts without a streak
        self._answer_all(at, correct=False)
        markup = " ".join(m.value for m in at.markdown)
        self.assertIn("Your best for these settings", markup)
        self.assertIn("Keep practising", markup)
        self.assertEqual(len(at.session_state["records"]["scores"]), 1)
        self.assertEqual(at.session_state["rounds_finished"], 2)
        self.assertEqual([e.value for e in at.exception], [])

    def test_feedback_shows_points_multiplier_and_a_fact(self):
        at = self.new(page="Quiz")
        at.button(key="start_quiz").click().run()
        quiz = at.session_state["quiz"]
        page = " ".join(m.value for m in at.markdown)
        self.assertNotIn("Did you know?", page)                       # nothing revealed before submission
        qn = quiz["questions"][0]
        at.button(key=f"answer_{quiz['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        page = " ".join(m.value for m in at.markdown)
        self.assertIn("Base 125 × 1 = 125", page)
        record = at.session_state["quiz"]["history"][0]
        if record["fact"]:
            self.assertIn("Did you know?", page)

    def test_active_round_survives_other_pages(self):
        at = self.new(page="Quiz")
        at.button(key="start_quiz").click().run()
        quiz = at.session_state["quiz"]
        qn = quiz["questions"][0]
        at.button(key=f"answer_{quiz['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        before = (quiz["serial"], quiz["index"], quiz["score"], quiz["streak"], len(quiz["history"]), at.session_state["points"])
        for page in ("Explore", "Learn", "Badges", "Quiz"):
            at.button(key=f"nav_{page}").click().run()
        quiz = at.session_state["quiz"]
        self.assertEqual((quiz["serial"], quiz["index"], quiz["score"], quiz["streak"], len(quiz["history"]), at.session_state["points"]), before)
        self.assertEqual([e.value for e in at.exception], [])

    def test_results_in_every_language(self):
        for lang in LANGS:
            at = self.new(page="Quiz", app_language=lang)
            at.button_group(key="filter_count").set_value(5).run()
            at.button(key="start_quiz").click().run()
            self._answer_all(at, correct=True)
            self.assertEqual([e.value for e in at.exception], [], lang)

    # ---------------------------------------------------------------- Learn: navigation, sections, size comparison

    def test_learn_navigation_and_dropdown_sync(self):
        at = self.new(page="Learn", learn_country="FRA")
        at.button(key="learn_next_top").click().run()
        self.assertEqual(at.session_state["learn_country"], "GAB")             # alphabetical, as in the dropdown
        self.assertEqual(at.selectbox(key="learn_country").value, "GAB")
        at.button(key="learn_prev_bottom").click().run()
        self.assertEqual(at.selectbox(key="learn_country").value, "FRA")
        at.button(key="nb_DEU").click().run()                                    # neighbour button
        self.assertEqual((at.session_state["learn_country"], at.selectbox(key="learn_country").value), ("DEU", "DEU"))
        self.assertEqual(at.session_state["page"], "Learn")
        for _ in range(5):
            before = at.session_state["learn_country"]
            at.button(key="learn_surprise").click().run()
            self.assertNotEqual(at.session_state["learn_country"], before)
        self.assertEqual([e.value for e in at.exception], [])

    def test_learn_respects_collection_and_one_country_scope(self):
        at = self.new(page="Learn", learn_country="ESP")
        self.assertNotIn("nb_GIB", [b.key for b in at.button])
        self.assertTrue(any("Gibraltar" in c.value for c in at.caption))       # excluded neighbour explained
        self.assertEqual(at.session_state["scope_collection"], "UN member and observer states")  # setting untouched
        at = self.new(page="Learn", learn_country="ESP", scope_collection="All countries and territories")
        self.assertIn("nb_GIB", [b.key for b in at.button])
        at = self.new(page="Learn", scope_mode="One country", scope_country="NGA", learn_country="NGA")
        for key in ("learn_prev_top", "learn_next_top", "learn_surprise", "learn_next_bottom"):
            self.assertTrue(at.button(key=key).disabled, key)
        self.assertTrue(any("Only one country" in c.value for c in at.caption))
        at = self.new(page="Learn", learn_country="ISL")
        self.assertTrue(any("no land borders" in c.value for c in at.caption))
        self.assertEqual([e.value for e in at.exception], [])

    def test_learn_sections_start_collapsed_and_hold_the_details(self):
        at = self.new(page="Learn", learn_country="FRA")
        self.assertFalse([b.key for b in at.button if b.key and b.key.startswith("recall_")])   # recall cards removed
        sections = {x.label.split(" (")[0]: x for x in at.expander}
        for name in ("Neighbours", "Landmarks", "Compare country size", "More details"):
            self.assertIn(name, sections)
            self.assertFalse(sections[name].proto.expanded, name)                # all start collapsed
        self.assertEqual(sections["Neighbours"].label, "Neighbours (8)")
        markup = " ".join(m.value for m in at.markdown)
        self.assertIn("French Republic", markup)                                # official name kept (More details)
        self.assertIn("+33", markup)                                           # calling code kept (More details)
        at = self.new(page="Learn", learn_country="ZAF")
        markup = " ".join(m.value for m in at.markdown)
        self.assertIn("Republic of South Africa", markup)                       # official name kept (More details)
        self.assertIn("Pretoria (administrative capital); Cape Town (legislative capital)", markup)  # roles kept in the tile
        self.assertIn("Calling codes and internet domains", markup)
        self.assertIn("learn_surprise", [b.key for b in at.button])
        self.assertEqual([e.value for e in at.exception], [])

    def test_learn_navigation_keeps_an_unfinished_quiz(self):
        at = self.new(page="Quiz")
        at.button(key="start_quiz").click().run()
        quiz = at.session_state["quiz"]
        qn = quiz["questions"][0]
        at.button(key=f"answer_{quiz['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        snapshot = (quiz["serial"], quiz["index"], quiz["score"], len(quiz["history"]))
        at.button(key="nav_Learn").click().run()
        for key in ("learn_next_top", "learn_surprise", "learn_prev_bottom"):
            at.button(key=key).click().run()
        at.selectbox(key="learn_country").select("FRA").run()
        at.button(key="nb_DEU").click().run()
        at.button(key="nav_Quiz").click().run()
        quiz = at.session_state["quiz"]
        self.assertEqual((quiz["serial"], quiz["index"], quiz["score"], len(quiz["history"])), snapshot)
        self.assertFalse(quiz["finished"])

    def test_size_reference_is_remembered(self):
        at = self.new(page="Learn", learn_country="FRA")
        at.selectbox(key="size_reference_select").select("DEU").run()
        self.assertEqual(at.session_state["size_reference"], "DEU")
        self.assertIn("France is about 1.5 times the size of Germany.", " ".join(m.value for m in at.markdown))
        at.button(key="nav_Explore").click().run()
        at.button(key="nav_Learn").click().run()
        self.assertEqual(at.selectbox(key="size_reference_select").value, "DEU")
        at.selectbox(key="size_reference_select").select("FRA").run()        # same country
        self.assertTrue(any("different country" in c.value for c in at.caption))
        at = self.new(page="Learn", learn_country="SJM", size_reference="FRA")  # SJM has no recorded area
        self.assertEqual([e.value for e in at.exception], [])
        self.assertTrue(any("not recorded" in c.value for c in at.caption))

    # ---------------------------------------------------------------- Explore: exploration area, Settings, Quiz settings

    def _settings_area(self, at, mode, value=None, collection=None):
        """Apply an exploration area the way "Apply settings" does (staged, applied at the start of the next run)."""
        ss = at.session_state
        at.session_state["pending_preferences"] = {
            "scope_mode": mode, "scope_continent": value if mode == "One continent" else "World",
            "scope_country": value if mode == "One country" else "all",
            "scope_collection": collection or ss["scope_collection"]}
        at.run()

    def test_exploration_area_lives_in_settings_and_is_shared(self):
        at = self.new()
        self.assertNotIn("explore_area_toggle", [b.key for b in at.button])            # Explore is map-first now
        self._settings_area(at, "One continent", "Asia")
        ss = at.session_state
        self.assertEqual((ss["scope_mode"], ss["scope_continent"]), ("One continent", "Asia"))
        self.assertEqual((ss["filter_continent"], ss["quiz_prefs"]["filter_continent"]), ("Asia", "Asia"))  # quiz setup
        at.button(key="nav_Learn").click().run()
        from core.data import get_country
        self.assertEqual(get_country(at.session_state["learn_country"])["continent"], "Asia")   # Learn moved inside
        at.button(key="nav_Quiz").click().run()
        self.assertEqual(at.selectbox(key="filter_continent").value, "Asia")
        at.button(key="nav_Explore").click().run()                                    # the map still shows every continent
        at.button(key="continent_btn_Europe").click().run()
        self.assertTrue([b for b in at.button if b.key and b.key.startswith("discover_")])
        self.assertEqual(at.button(key="settings_menu").label, "Settings")            # accessible name, icon on screen
        self.assertEqual([e.value for e in at.exception], [])

    def test_area_change_resets_pagination_and_search(self):
        at = self.new(explore_selected="Asia")
        at.button(key="explore_next").click().run()
        at.text_input(key="explore_search").input("an").run()
        self._settings_area(at, "All countries", collection="All countries and territories")
        self.assertEqual((at.session_state["explore_page"], at.session_state["explore_search"]), (0, ""))
        self.assertEqual(len([b for b in at.button if b.key and b.key.startswith("discover_")]), 10)
        self.assertEqual([e.value for e in at.exception], [])

    def test_area_change_and_quiz_settings_keep_an_unfinished_round(self):
        at = self.new(page="Quiz")
        at.button(key="start_quiz").click().run()
        quiz = at.session_state["quiz"]
        qn = quiz["questions"][0]
        at.button(key=f"answer_{quiz['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        snapshot = (quiz["serial"], quiz["index"], quiz["score"], len(quiz["history"]), at.session_state["points"])
        at.button(key="nav_Explore").click().run()
        self._settings_area(at, "One continent", "Europe")
        at.button(key="nav_Quiz").click().run()
        at.button(key="quiz_settings").click().run()                                 # renamed from "Change"
        self.assertTrue(at.session_state["show_setup"])
        self.assertTrue(any("round in progress" in i.value for i in at.info))
        quiz = at.session_state["quiz"]
        self.assertEqual((quiz["serial"], quiz["index"], quiz["score"], len(quiz["history"]), at.session_state["points"]), snapshot)
        self.assertFalse(quiz["finished"])
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- Daily challenge, day streak, mistakes

    def _finish(self, at, correct_pattern):
        for i, ok in enumerate(correct_pattern):
            q = at.session_state["quiz"]
            qn = q["questions"][i]
            pick = qn["answer"] if ok else next(c for c in qn["choices"] if c != qn["answer"])
            at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(pick)}").click().run()
            at.button(key=f"next_{q['serial']}_{i}").click().run()

    def test_daily_first_attempt_counts_and_replays_change_nothing(self):
        from datetime import date
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 10)):
            at = self.new()
            at.button(key="explore_daily").click().run()
            self.assertEqual((at.session_state["quiz"]["mode"], at.session_state["page"]), ("daily", "Quiz"))
            self._finish(at, [True, False, True, True, False])
            ss = at.session_state
            self.assertEqual(ss["daily"]["results"]["2026-10-10"]["correct"], 3)
            self.assertEqual((ss["daily"]["streak"], ss["rounds_finished"]), (1, 1))
            self.assertEqual(len(ss["mistakes"]), 2)
            share = [c.value for c in at.code]
            self.assertEqual(share, ["World Explorer · Daily 2026-10-10 · 3/5 🟩🟥🟩🟩🟥 · 🔥 1"])
            before = (ss["points"], ss["rounds_finished"], dict(ss["stats"]), dict(ss["daily"]["results"]), list(map(str, ss["mistakes"])))
            at.button(key="play_again").click().run()
            self.assertEqual(at.session_state["quiz"]["mode"], "daily_replay")
            self._finish(at, [True] * 5)
            ss = at.session_state
            self.assertEqual((ss["points"], ss["rounds_finished"], dict(ss["stats"]), dict(ss["daily"]["results"]),
                              list(map(str, ss["mistakes"]))), before)
            self.assertTrue(any("Practice replay" in m.value for m in at.markdown))
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 11)):   # next day continues the streak
            at.button(key="nav_Explore").click().run()
            at.button(key="explore_daily").click().run()
            self.assertEqual(at.session_state["quiz"]["mode"], "daily")
            self._finish(at, [True] * 5)
            self.assertEqual(at.session_state["daily"]["streak"], 2)
        self.assertEqual([e.value for e in at.exception], [])

    def test_daily_and_regular_rounds_never_discard_each_other(self):
        from datetime import date
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 10)):
            at = self.new(page="Quiz")
            at.button(key="start_quiz").click().run()
            q = at.session_state["quiz"]; qn = q["questions"][0]
            at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
            regular = (q["serial"], q["score"], len(q["history"]))
            at.button(key="quiz_settings").click().run()
            at.button(key="setup_daily").click().run()                                # daily starts, regular is kept aside
            self.assertEqual(at.session_state["quiz"]["mode"], "daily")
            self.assertEqual(at.session_state["parked_rounds"]["regular"]["serial"], regular[0])
            q = at.session_state["quiz"]; qn = q["questions"][0]
            at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
            at.button(key="quiz_settings").click().run()
            at.button(key="resume_regular").click().run()                             # back to the regular round
            q = at.session_state["quiz"]
            self.assertEqual((q["serial"], q["score"], len(q["history"])), regular)
            self.assertEqual(at.session_state["parked_rounds"]["daily"]["mode"], "daily")   # daily kept in turn
            at.button(key="nav_Explore").click().run()
            self.assertEqual(at.button(key="explore_daily").label, "Continue today's challenge")
            at.button(key="explore_daily").click().run()
            self.assertEqual((at.session_state["quiz"]["mode"], len(at.session_state["quiz"]["history"])), ("daily", 1))
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- daily results across midnight UTC

    def _progress(self, at):
        ss = at.session_state
        return (ss["points"], ss["rounds_finished"], repr(ss["stats"]), repr(ss["records"]), repr(ss["daily"]),
                repr(ss["mistakes"]))

    def _texts(self, at):
        return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)

    def test_replay_completed_across_midnight_then_new_day_challenge(self):
        from datetime import date
        day1, day2 = date(2026, 10, 10), date(2026, 10, 11)
        with mock.patch("core.daily.utc_today", return_value=day1):
            at = self.new()
            at.button(key="explore_daily").click().run()
            self._finish(at, [True, False, True, True, False])                  # counted: 3/5 on 10 Oct
            at.button(key="play_again").click().run()
            self.assertEqual(at.session_state["quiz"]["mode"], "daily_replay")
            self._finish(at, [True, True, True, True])                           # 4 of 5 answered before midnight
            before = self._progress(at)
        with mock.patch("core.daily.utc_today", return_value=day2):
            q = at.session_state["quiz"]
            qn = q["questions"][4]
            at.button(key=f"answer_{q['serial']}_4_{qn['choices'].index(qn['answer'])}").click().run()
            at.button(key=f"next_{q['serial']}_4").click().run()                 # replay finishes after midnight
            self.assertEqual([x.value for x in at.exception], [])
            self.assertEqual(self._progress(at), before)                         # the replay changed nothing
            text = self._texts(at)
            self.assertIn("Saved result for 2026-10-10: 3/5.", text)
            self.assertNotIn("today", text.split("Practice replay")[1].split(".")[0].lower())
            self.assertIn("Today's challenge is ready.", text)
            self.assertEqual([c.value for c in at.code], ["World Explorer · Daily 2026-10-10 · 3/5 · 🔥 1"])
            self.assertEqual(at.button(key="play_again").label, "Today's challenge · 5 questions")
            at.button(key="play_again").click().run()                            # the new day's challenge counts
            self.assertEqual((at.session_state["quiz"]["mode"], at.session_state["quiz"]["day"]), ("daily", "2026-10-11"))
            self._finish(at, [True] * 5)
            daily = at.session_state["daily"]
            self.assertEqual((daily["streak"], daily["last"], daily["results"]["2026-10-11"]["correct"]), (2, "2026-10-11", 5))
            self.assertEqual(daily["results"]["2026-10-10"]["correct"], 3)       # yesterday's saved result untouched
            self.assertEqual(at.code[0].value, "World Explorer · Daily 2026-10-11 · 5/5 🟩🟩🟩🟩🟩 · 🔥 2")
        self.assertEqual([x.value for x in at.exception], [])

    def test_reopening_yesterdays_results_after_midnight(self):
        from datetime import date
        day1, day2 = date(2026, 10, 10), date(2026, 10, 11)
        # 1) yesterday's practice replay results reopened after midnight (the reported crash)
        with mock.patch("core.daily.utc_today", return_value=day1):
            at = self.new()
            at.button(key="explore_daily").click().run()
            self._finish(at, [True, True, False, True, False])                   # counted: 3/5
            at.button(key="play_again").click().run()
            self._finish(at, [True] * 5)                                         # replay finished the same day
            before = self._progress(at)
        with mock.patch("core.daily.utc_today", return_value=day2):
            at.run()
            self.assertEqual([x.value for x in at.exception], [])
            self.assertEqual(self._progress(at), before)
            self.assertIn("Saved result for 2026-10-10: 3/5.", self._texts(at))
            self.assertEqual([c.value for c in at.code], ["World Explorer · Daily 2026-10-10 · 3/5 · 🔥 1"])
        # 2) yesterday's counted results reopened after midnight: labelled with their own date, never as today's
        with mock.patch("core.daily.utc_today", return_value=day1):
            at = self.new()
            at.button(key="explore_daily").click().run()
            self._finish(at, [True, True, False, True, False])
            before = self._progress(at)
        with mock.patch("core.daily.utc_today", return_value=day2):
            at.run()
            text = self._texts(at)
            self.assertEqual([x.value for x in at.exception], [])
            self.assertIn("Your result for 2026-10-10 is saved.", text)
            self.assertNotIn("Today's result is saved", text)
            self.assertEqual([c.value for c in at.code], ["World Explorer · Daily 2026-10-10 · 3/5 🟩🟩🟥🟩🟥 · 🔥 1"])
            self.assertEqual(self._progress(at), before)                         # showing results records nothing
            self.assertEqual(at.button(key="play_again").label, "Today's challenge · 5 questions")

    def test_daily_results_without_a_saved_result(self):
        from datetime import date
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 10)):
            at = self.new()
            at.button(key="explore_daily").click().run()
            self._finish(at, [True] * 5)
            at.button(key="play_again").click().run()
            self._finish(at, [False] * 5)
            daily = at.session_state["daily"]
            daily["results"] = {}                                                 # e.g. history trimmed or not loaded
            at.session_state["daily"] = daily
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 11)):
            at.run()
            self.assertEqual([x.value for x in at.exception], [])
            self.assertIn("No saved result was found for 2026-10-10.", self._texts(at))
            self.assertEqual(list(at.code), [])                                   # nothing to share
            q = at.session_state["quiz"]
            q["day"] = None                                                       # a round without a valid date
            at.session_state["quiz"] = q
            at.run()
            self.assertEqual([x.value for x in at.exception], [])
            self.assertIn("No saved result was found for –.", self._texts(at))
            at.button(key="play_again").click().run()
            self.assertEqual((at.session_state["quiz"]["mode"], at.session_state["quiz"]["day"]), ("daily", "2026-10-11"))

    def test_quiz_setup_daily_entry(self):
        at = self.new(page="Quiz")   # one compact daily card at the top of the Quiz page (phones and desktops)
        self.assertEqual(at.button(key="setup_daily").label, "Start")
        at.button(key="setup_daily").click().run()
        self.assertEqual(at.session_state["quiz"]["mode"], "daily")
        self.assertEqual([e.value for e in at.exception], [])

    # ---------------------------------------------------------------- Quiz page V23

    def test_v23_setup_three_essentials_and_advanced_settings(self):
        import inspect
        from ui import pages
        at = self.new(page="Quiz")
        self.assertEqual(at.selectbox(key="filter_category").value, "Mixed")          # the existing defaults
        self.assertEqual(at.button_group(key="filter_difficulty").value, "Medium")
        self.assertEqual(at.button_group(key="filter_count").value, 10)
        self.assertEqual(list(at.button_group(key="filter_difficulty").options), ["Easy", "Medium", "Difficult", "Expert"])
        self.assertEqual([str(o) for o in at.button_group(key="filter_count").options], ["5", "10", "15", "20", "25", "50"])
        src = inspect.getsource(pages._setup)
        advanced = src[src.index('st.expander(t("Advanced quiz settings")'):src.index("state.remember_quiz_filters()")]
        for key in ("filter_timer", "filter_flags", "filter_collection", "filter_continent", "filter_country"):
            self.assertIn(f'key="{key}"', advanced)                                  # all other options kept, under Advanced
        self.assertNotIn("How well do you know your world?", inspect.getsource(pages.quiz))   # no decorative banner
        at.toggle(key="filter_timer").set_value(True).run()                            # options still work as before
        at.selectbox(key="filter_category").select("Capitals").run()
        at.button_group(key="filter_difficulty").set_value("Expert").run()
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        s = at.session_state["quiz"]["settings"]
        self.assertEqual((s["category"], s["difficulty"], s["count"], s["timer"]), ("Capitals", "Expert", 5, True))
        self.assertEqual([e.value for e in at.exception], [])

    def test_v23_round_one_answer_hint_feedback_and_results(self):
        from core import quiz as engine
        at = self.new(page="Quiz")
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        self.assertFalse(any(b.key == "start_quiz" for b in at.button))                 # setup hidden during the round
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        self.assertTrue(any("Question 1 of 5" in str(m.value) for m in at.markdown))
        if len(qn["choices"]) == 4:                                                     # hint: one wrong option removed
            at.button(key=f"hint_{q['serial']}_0").click().run()
            self.assertEqual(at.session_state["quiz"]["hints_remaining"], engine.HINTS_PER_ROUND - 1)
            self.assertEqual(at.button(key=f"hint_{q['serial']}_0").label, "Hint used")
        before = at.session_state["points"]
        right = qn["choices"].index(qn["answer"])
        at.button(key=f"answer_{q['serial']}_0_{right}").click().run()
        gained = at.session_state["points"] - before
        self.assertGreater(gained, 0)
        self.assertEqual(len(at.session_state["quiz"]["history"]), 1)
        wrong = next(i for i, c in enumerate(qn["choices"]) if c != qn["answer"])
        self.assertTrue(at.button(key=f"answer_{q['serial']}_0_{wrong}").disabled)        # one answer per question
        at.run()                                                                        # a rerun (refresh) records nothing more
        self.assertEqual((len(at.session_state["quiz"]["history"]), at.session_state["points"] - before), (1, gained))
        self.assertTrue(any("Correct!" in str(m.value) for m in at.markdown))
        for i in range(5):
            qq = at.session_state["quiz"]
            if i:
                qi = qq["questions"][i]
                at.button(key=f"answer_{qq['serial']}_{i}_{qi['choices'].index(qi['answer'])}").click().run()
            at.button(key=f"next_{qq['serial']}_{i}").click().run()
        self.assertTrue(at.session_state["quiz"]["finished"])
        self.assertEqual(at.session_state["rounds_finished"], 1)
        texts = " ".join(str(m.value) for m in at.markdown)
        for label in ("Quiz complete", "Accuracy", "Correct answers", "Points earned", "Best answer streak"):
            self.assertIn(label, texts)
        self.assertEqual(at.button(key="change_settings").label, "Try another category")
        at.button(key="results_explore").click().run()
        self.assertEqual(at.session_state["page"], "Explore")
        self.assertEqual([e.value for e in at.exception], [])

    def test_v23_next_question_advances_once_and_redraws_only_the_quiz(self):
        import inspect
        from ui import pages
        src = inspect.getsource(pages._active_round)
        self.assertIn("on_click=state.next_question, args=(serial, index)", src)       # one run per Next click
        self.assertIn("hint_slot, feedback_slot, script_slot = st.empty(), st.empty(), st.empty()", src)   # fixed positions
        self.assertLess(src.index("_round_progress(quiz)"), src.index("_bring_into_view"))   # nothing inserted on top
        at = self.new(page="Quiz")
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        for i in range(4):
            q = at.session_state["quiz"]; qn = q["questions"][i]
            at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(qn['answer'])}").click().run()
            at.button(key=f"next_{q['serial']}_{i}").click().run()
            self.assertEqual(at.session_state["quiz"]["index"], i + 1)                   # exactly one question further
        self.assertEqual([e.value for e in at.exception], [])

    def test_page_change_uses_the_other_slot_and_same_page_reruns_keep_it(self):
        at = self.new()
        self.assertEqual((at.session_state["view_page"], at.session_state["view_slot"]), ("Explore", 0))
        at.run()
        self.assertEqual(at.session_state["view_slot"], 0)                                 # same page: same slot
        at.button(key="nav_Quiz").click().run()
        self.assertEqual((at.session_state["view_page"], at.session_state["view_slot"]), ("Quiz", 1))
        at.button(key="nav_Learn").click().run()
        self.assertEqual((at.session_state["view_page"], at.session_state["view_slot"]), ("Learn", 0))
        self.assertEqual([e.value for e in at.exception], [])

    def test_v23_answer_colours_follow_position_not_correctness(self):
        import inspect
        from ui import pages
        src = inspect.getsource(pages._active_round)
        self.assertIn('key=f"ans{pos}_{style}"', src)            # colour slot = position on screen
        css = (Path(APP).parent / "assets" / "styles.css").read_text(encoding="utf-8")
        block = css[css.index("Quiz page V23"):]
        for n, letter in enumerate("ABCD"):
            self.assertIn(f'[class*="st-key-ans{n}_"] button::before {{ content:"{letter}"', block)
        self.assertIn('flex-direction:column !important', block)   # one column of answers on phones
        self.assertNotIn("@keyframes", block)                      # no new animations

    def test_practise_mistakes_round_clears_correct_answers(self):
        at = self.new(page="Quiz")
        at.button_group(key="filter_count").set_value(5).run()
        at.button(key="start_quiz").click().run()
        self._finish(at, [False, False, True, True, True])
        self.assertEqual(len(at.session_state["mistakes"]), 2)
        at.button(key="results_practise").click().run()
        self.assertEqual(at.session_state["quiz"]["mode"], "practice")
        n = len(at.session_state["quiz"]["questions"])
        self._finish(at, [True] * n)
        self.assertEqual(at.session_state["mistakes"], [])
        self.assertEqual([e.value for e in at.exception], [])

    def test_flag_questions_label_in_every_language(self):
        from core.i18n import translate
        for lang in LANGS:
            at = self.new(page="Quiz", app_language=lang)
            labels = [tg.label for tg in at.toggle]
            self.assertIn(translate("Flag questions", lang), labels, lang)


class FakeState(dict):
    __getattr__ = dict.__getitem__

    def __setattr__(self, key, value):
        self[key] = value


def fake_streamlit(logged_in=True, secrets=None, url="https://world-explorer.streamlit.app/"):
    st = types.SimpleNamespace(session_state=FakeState(), secrets=secrets or {}, context=types.SimpleNamespace(url=url))

    class User(dict):
        is_logged_in = logged_in
    st.user = User(iss="https://accounts.google.com", sub="123", name="Ada", email="ada@example.com") if logged_in else User()
    return st


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class AccountTests(unittest.TestCase):
    def setUp(self):
        from core import accounts
        self.accounts = accounts
        self.storage = {"profiles": {"url": "https://example.supabase.co", "server_key": "sb_secret_test"}}

    def test_old_profiles_load_unchanged_and_sound_stays_off(self):
        old = {"profile_name": "Okey", "points": 1200, "rounds_finished": 4, "app_language": "Deutsch",
               "scope_mode": "One continent", "scope_continent": "Africa", "scope_country": "all",
               "recent": ["NGA"], "recent_facts": ["capital:NGA:Abuja"], "unknown_future_key": 1}
        clean = self.accounts.sanitize_profile(old)
        self.assertEqual(clean["points"], 1200)
        self.assertNotIn("unknown_future_key", clean)
        self.assertNotIn("sound_enabled", clean)  # missing → the session default (off) is kept
        self.assertNotIn("stats", clean)          # missing → empty statistics; points and rounds unchanged
        self.assertEqual(self.accounts.sanitize_profile({"stats": {"correct": 3}})["stats"]["correct"], 3)
        self.assertNotIn("stats", self.accounts.sanitize_profile({"stats": "corrupt"}))
        bad = self.accounts.sanitize_profile({"sound_enabled": "yes", "sound_volume": 400, "points": -5,
                                              "scope_collection": "Mars", "profile_photo": "http://x"})
        self.assertEqual(bad, {})
        self.assertEqual(self.accounts.sanitize_profile({"sound_enabled": True, "sound_volume": 30}),
                         {"sound_enabled": True, "sound_volume": 30})
        self.assertNotIn("records", clean)        # older profiles have no records: empty records, totals unchanged
        saved = {"records": {"best_streak": 7, "scores": {"x": 900}}, "points": 50}
        self.assertEqual(self.accounts.sanitize_profile(saved), saved)
        self.assertNotIn("records", self.accounts.sanitize_profile({"records": ["corrupt"]}))
        self.assertIn("records", self.accounts.PROFILE_KEYS)
        self.assertNotIn("size_reference", clean)  # older profiles: no reference country until one is chosen
        self.assertNotIn("daily", clean)           # older profiles: no daily history or mistakes yet
        self.assertNotIn("mistakes", clean)
        self.assertEqual(self.accounts.sanitize_profile({"daily": {"streak": 3, "best": 5, "last": "2026-10-09", "results": {}}})["daily"]["best"], 5)
        self.assertNotIn("mistakes", self.accounts.sanitize_profile({"mistakes": "corrupt"}))
        self.assertEqual(self.accounts.sanitize_profile({"size_reference": "DEU"}), {"size_reference": "DEU"})
        self.assertEqual(self.accounts.sanitize_profile({"size_reference": ""}), {"size_reference": ""})
        self.assertEqual(self.accounts.sanitize_profile({"size_reference": "XXX"}), {})
        self.assertEqual(self.accounts.sanitize_profile({"size_reference": 5}), {})

    def test_connection_failure_never_overwrites(self):
        st = fake_streamlit(secrets=self.storage)
        st.session_state.update(points=0, profile_name="")
        calls = []

        def failing(profile_id, payload=None):
            calls.append(payload)
            raise OSError("network down")
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.accounts, "_request", failing):
            self.accounts.restore_profile(now=1000)
            self.assertEqual(self.accounts.connection_state(), "loading_failed")
            self.accounts.save_profile()
            self.assertEqual(calls, [None])               # only the read was attempted, never a write
            self.accounts.restore_profile(now=1010)        # within the retry delay: no new request
            self.assertEqual(len(calls), 1)
            self.accounts.restore_profile(now=1100)        # retried after the delay
            self.assertEqual(len(calls), 2)

    def test_successful_load_then_save(self):
        st = fake_streamlit(secrets=self.storage)
        st.session_state.update(points=0, profile_name="")
        writes = []

        def fake_request(profile_id, payload=None):
            if payload is None:
                return [{"profile": {"points": 900, "profile_name": "Okey"}}]
            writes.append(payload)
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.accounts, "_request", fake_request):
            self.accounts.restore_profile(now=0)
            self.assertEqual(st.session_state.points, 900)
            self.accounts.save_profile()
            self.assertEqual(writes, [])                  # nothing changed, nothing written
            st.session_state.points = 1000
            self.accounts.save_profile()
            self.assertEqual(writes[0]["points"], 1000)
            self.assertEqual(self.accounts.connection_state(), "saved")

    def test_sign_in_diagnosis(self):
        auth = {"redirect_uri": "https://world-explorer.streamlit.app/oauth2callback", "cookie_secret": "x",
                "google": {"client_id": "id", "client_secret": "s",
                           "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}}
        cases = [({}, "not_configured"),
                 ({"auth": dict(auth, redirect_uri="https://world-explorer.streamlit.app/")}, "callback_path"),
                 ({"auth": dict(auth, redirect_uri="http://world-explorer.streamlit.app/oauth2callback")}, "not_https"),
                 ({"auth": dict(auth, redirect_uri="http://localhost:8502/oauth2callback")}, "origin_mismatch"),
                 ({"auth": auth}, None)]
        for secrets, problem in cases:
            st = fake_streamlit(logged_in=False, secrets=secrets)
            with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.accounts, "_authlib_ready", lambda: True):
                result = self.accounts.auth_diagnosis("google")
            self.assertEqual(result["problem"], problem, secrets)
            self.assertEqual(result["expected"], "https://world-explorer.streamlit.app/oauth2callback")
            self.assertNotIn("cookie_secret", str(result))
            self.assertNotIn("client_secret", str(result))
        st = fake_streamlit(logged_in=False, secrets={"auth": auth})
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.accounts, "_authlib_ready", lambda: False):
            self.assertEqual(self.accounts.auth_diagnosis("google")["problem"], "authlib_missing")


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class ScriptCleanerTests(unittest.TestCase):
    """Streamlit's HTML cleaner drops a whole <script> that contains "<" followed by a letter, digit, "/" or "!"
    inside it. The theme script was dropped that way, so the page followed the device theme instead of the theme
    Streamlit showed (white on cream / dark on navy when they differed)."""

    def _inner(self, markup):
        return markup.split(">", 1)[1].rsplit("</script>", 1)[0]

    def test_scripts_survive_the_html_cleaner(self):
        import re
        from ui import components
        for name in ("THEME_SYNC", "GPC_SYNC"):
            for part in getattr(components, name).split("<script")[1:]:
                self.assertIsNone(re.search(r"<[A-Za-z0-9/!]", self._inner("<script" + part)), name)
        src = (Path(APP).parent / "ui" / "pages.py").read_text(encoding="utf-8")
        body = src[src.index("def _bring_into_view"):src.index("def _active_round")]
        script = body[body.index("<script>") + 8:body.index("</script>")]
        self.assertIsNone(re.search(r"<[A-Za-z0-9/!]", script))


class ContinentMapTests(unittest.TestCase):
    """The Explore home: real summary, Daily Challenge, interactive continent map, buttons and details panel."""
    CONTINENTS = ("Africa", "Asia", "Europe", "North America", "South America", "Oceania")

    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    @staticmethod
    def btn(continent):
        return "continent_btn_" + continent.replace(" ", "_")

    def summary(self, at):
        return next(m.value for m in at.markdown if 'class="explore-summary"' in m.value)

    def test_new_explorer_sees_real_zeros(self):
        at = self.new()
        text = self.summary(at)
        self.assertIn("<b>0</b>", text)                        # points and day streak
        self.assertIn("<b>0/14</b>", text)                     # earned badges
        self.assertNotIn("Demo", str(at))
        self.assertEqual([b for b in self.CONTINENTS if self.btn(b) not in [x.key for x in at.button]], [])
        self.assertNotIn("continent_panel_head", str([b.key for b in at.button]))
        self.assertEqual([e.value for e in at.exception], [])

    def test_saved_progress_is_shown(self):
        from core import badges
        stats = badges.empty_stats()
        stats["correct_by_continent"]["Europe"] = 3
        stats["correct"] = 3
        at = self.new(points=1250, rounds_finished=2, stats=stats, explore_selected="Europe")
        text = self.summary(at)
        self.assertIn("<b>1,250</b>", text)
        earned = sum(1 for b in badges.evaluate(stats, 1250, 2) if b["earned"])
        self.assertIn(f"<b>{earned}/14</b>", text)
        head = next(m.value for m in at.markdown if 'class="detail-empty"' in m.value)
        self.assertIn("3 of 5 correct answers about Europe", head)
        self.assertIn('aria-valuenow="3"', head)

    def test_selecting_by_button_opens_details_without_touching_rounds(self):
        at = self.new(page="Quiz")
        at.button(key="start_quiz").click().run()
        q = at.session_state["quiz"]
        qn = q["questions"][0]
        at.button(key=f"answer_{q['serial']}_0_{qn['choices'].index(qn['answer'])}").click().run()
        before = (q["serial"], q["score"], len(q["history"]), q["finished"])
        at.button(key="nav_Explore").click().run()
        for continent in self.CONTINENTS:
            at.button(key=self.btn(continent)).click().run()
            self.assertEqual(at.session_state["explore_selected"], continent)
            self.assertEqual(at.session_state["page"], "Explore")
            # Project Atlas: the map and its pills stay in the panel; the open continent's pill is marked
            self.assertEqual(at.button(key=self.btn(continent)).proto.type, "primary")
            heading = next(m.value for m in at.markdown if 'class="continent-title"' in m.value)
            self.assertIn(continent, heading)
            current = at.session_state["quiz"]
            self.assertEqual((current["serial"], current["score"], len(current["history"]), current["finished"]), before)
            at.button(key="continent_back").click().run()
        at.button(key=self.btn("Asia")).click().run()
        at.button(key="continent_back").click().run()
        self.assertIsNone(at.session_state["explore_selected"])
        self.assertNotIn("continent_back", [b.key for b in at.button])
        self.assertEqual([e.value for e in at.exception], [])

    def test_map_selection_uses_the_same_rules(self):
        from ui import state, world_map
        class Fake(dict):
            __getattr__, __setattr__ = dict.get, dict.__setitem__
        fake = Fake(world_map={"select": "Asia"})
        with mock.patch.object(world_map.st, "session_state", fake), mock.patch.object(state.st, "session_state", fake):
            self.assertEqual(world_map.selected_value(), "Asia")
            state.explore_select(world_map.selected_value())
            self.assertEqual(fake["explore_selected"], "Asia")
            state.explore_select("Atlantis")                      # unknown names are ignored
            self.assertEqual(fake["explore_selected"], "Asia")

    def test_place_counts_come_from_the_dataset(self):
        from core.data import get_countries
        for collection, word in (("UN member and observer states", "countries"),
                                 ("All countries and territories", "countries and territories")):
            for continent in self.CONTINENTS:
                at = self.new(scope_collection=collection, explore_selected=continent)
                n = len(get_countries(continent, collection=collection))
                count = next(m.value for m in at.markdown if 'class="continent-count"' in m.value)
                expected = f"{n} countries" if collection.startswith("UN") else f"{n} {word}"
                self.assertIn(f">{expected}<", count, (collection, continent))

    def test_continent_opens_its_country_cards_in_place_of_the_map(self):
        from core.data import get_country, get_countries
        at = self.new(scope_collection="All countries and territories")
        self.assertFalse([b for b in at.button if b.key and b.key.startswith("discover_")])   # world map only
        self.assertNotIn("explore_search", [x.key for x in at.text_input])
        at.button(key=self.btn("Europe")).click().run()
        cards = [b.key.removeprefix("discover_") for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertEqual(len(cards), 10)
        self.assertTrue(all("Europe" in get_country(c)["continents"] for c in cards))
        at.selectbox(key="explore_status").select("territory").run()                 # status filter
        territories = [b.key.removeprefix("discover_") for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertTrue(territories and all(get_country(c)["status"] == "territory" for c in territories))
        at.selectbox(key="explore_status").select("all").run()
        at.text_input(key="explore_search").input("Bern").run()                       # search within the continent
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("discover_")], ["discover_CHE"])
        at.text_input(key="explore_search").input("").run()
        at.button(key="explore_next").click().run()                                   # pagination
        self.assertEqual(at.session_state["explore_page"], 1)
        at.button(key="continent_back").click().run()
        at.button(key=self.btn("Asia")).click().run()                                 # switching starts again at page 1
        self.assertEqual((at.session_state["explore_page"], at.session_state["explore_search"]), (0, ""))
        n = len(get_countries("Asia", collection="All countries and territories"))
        self.assertTrue(any(f">{n} countries and territories<" in m.value for m in at.markdown if 'class="continent-count"' in m.value))
        self.assertEqual([e.value for e in at.exception], [])

    def test_a_narrower_exploration_area_widens_with_a_notice(self):
        at = self.new(scope_mode="One continent", scope_continent="Asia")
        at.button(key=self.btn("Asia")).click().run()                       # inside the area: nothing changes
        self.assertEqual(at.session_state["scope_mode"], "One continent")
        self.assertFalse(at.info)
        at.button(key="continent_back").click().run()
        at.button(key=self.btn("Europe")).click().run()                     # outside: widened under the usual rules
        ss = at.session_state
        self.assertEqual((ss["scope_mode"], ss["scope_continent"], ss["scope_collection"]),
                         ("All countries", "World", "UN member and observer states"))
        self.assertTrue(any("now includes all countries" in i.value for i in at.info))
        self.assertEqual(len([b for b in at.button if b.key and b.key.startswith("discover_")]), 10)
        at.run()
        self.assertFalse(any("now includes all countries" in i.value for i in at.info))   # said once

    def test_browse_all_countries(self):
        from core.data import get_countries
        at = self.new()
        at.button(key="browse_all").click().run()
        self.assertEqual(at.session_state["explore_selected"], "World")
        self.assertTrue(any(">195 countries<" in m.value for m in at.markdown if 'class="continent-count"' in m.value))
        at.text_input(key="explore_search").input("Bern").run()
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("discover_")], ["discover_CHE"])
        at.text_input(key="explore_search").input("").run()
        at.selectbox(key="explore_places").select("All countries and territories").run()   # compact places control
        self.assertEqual(at.session_state["scope_collection"], "All countries and territories")  # same preference as Settings
        self.assertTrue(any(f">{len(get_countries(collection='All countries and territories'))} countries and territories<" in m.value
                            for m in at.markdown if 'class="continent-count"' in m.value))
        at.button(key="continent_quiz").click().run()
        self.assertEqual((at.session_state["page"], at.session_state["filter_continent"]), ("Quiz", "World"))
        self.assertEqual([e.value for e in at.exception], [])

    def test_switching_continents_resets_filters_but_keeps_places(self):
        at = self.new(scope_collection="All countries and territories")
        at.button(key=self.btn("Europe")).click().run()
        at.selectbox(key="explore_status").select("territory").run()
        at.text_input(key="explore_search").input("a").run()
        at.button(key="continent_back").click().run()
        at.button(key=self.btn("Oceania")).click().run()
        ss = at.session_state
        self.assertEqual((ss["explore_search"], ss["explore_status"], ss["explore_page"]), ("", "all", 0))
        self.assertEqual(ss["scope_collection"], "All countries and territories")

    def test_learn_and_back_restores_the_browser(self):
        at = self.new(scope_collection="All countries and territories")
        at.button(key=self.btn("Europe")).click().run()
        at.selectbox(key="explore_status").select("un_member").run()
        at.text_input(key="explore_search").input("an").run()
        at.button(key="explore_next").click().run()
        page = at.session_state["explore_page"]
        card = [b.key for b in at.button if b.key and b.key.startswith("discover_")][0]
        at.button(key=card).click().run()
        at.button(key="detail_learn").click().run()
        self.assertEqual(at.session_state["page"], "Learn")
        at.button(key="nav_Explore").click().run()
        ss = at.session_state
        self.assertEqual((ss["explore_selected"], ss["explore_search"], ss["explore_status"], ss["explore_page"]),
                         ("Europe", "an", "un_member", page))
        self.assertIn(card, [b.key for b in at.button])
        self.assertEqual([e.value for e in at.exception], [])

    def test_country_shows_beside_the_list_and_back(self):
        at = self.new(explore_selected="Asia")
        self.assertFalse(any('class="detail-name"' in m.value for m in at.markdown))   # nothing chosen yet
        first = [b.key for b in at.button if b.key and b.key.startswith("discover_")][0]
        at.button(key=first).click().run()
        self.assertTrue(any('class="detail-name"' in m.value for m in at.markdown))    # the country, beside the list
        self.assertEqual(at.button(key=first).proto.type, "primary")     # the chosen row is highlighted
        self.assertIn("country_back", [b.key for b in at.button])
        at.button(key="detail_quiz").click().run()                      # quiz me on this country keeps the rules
        self.assertEqual((at.session_state["page"], at.session_state["filter_country"]), ("Quiz", first.removeprefix("discover_")))
        at.button(key="nav_Explore").click().run()
        self.assertEqual(at.session_state["explore_country"], first.removeprefix("discover_"))   # restored on return
        at.button(key="country_back").click().run()                     # phones: back to the list,
        self.assertEqual(at.session_state["explore_country"], first.removeprefix("discover_"))   # still selected
        self.assertFalse(at.session_state["explore_detail_open"])
        self.assertEqual(at.button(key=first).proto.type, "primary")
        at.button(key="continent_back").click().run()
        self.assertFalse([b for b in at.button if b.key and b.key.startswith("discover_")])     # map only again
        self.assertEqual([e.value for e in at.exception], [])

    def test_destination_photo_collapses_when_it_cannot_load(self):
        """Photos are real images without a fixed-height box, with caption and licence in one line underneath."""
        at = self.new(explore_selected="Africa", explore_country="NGA")
        figure = next(m.value for m in at.markdown if 'class="photo-frame detail-photo-frame"' in m.value)
        self.assertIn('<img src="https://upload.wikimedia.org/', figure)
        self.assertNotIn("background-image", figure)
        self.assertIn("CC BY-SA 3.0", figure)
        at = self.new(explore_selected="Africa", explore_country="DZA")         # no bundled photo: nothing at all
        self.assertFalse(any("photo-frame" in m.value for m in at.markdown if "<figure" in m.value))
        at = self.new(page="Learn", learn_country="NGA")
        self.assertTrue(any('class="photo-frame learn-photo-frame"' in m.value for m in at.markdown))

    def test_quiz_this_continent_opens_setup_and_keeps_rounds(self):
        from datetime import date
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 10)):
            at = self.new()
            at.button(key="explore_daily").click().run()             # an unfinished daily round
            daily = at.session_state["quiz"]
            at.button(key="nav_Explore").click().run()
            at.button(key=self.btn("Oceania")).click().run()
            self.assertIs(at.session_state["quiz"]["uid"], daily["uid"])
            at.button(key="continent_quiz").click().run()
            ss = at.session_state
            self.assertEqual((ss["page"], ss["show_setup"]), ("Quiz", True))
            self.assertEqual((ss["filter_continent"], ss["filter_country"]), ("Oceania", "all"))
            self.assertEqual(at.selectbox(key="filter_continent").value, "Oceania")
            self.assertEqual(ss["quiz"]["uid"], daily["uid"])        # nothing started, nothing discarded
            self.assertFalse(ss["quiz"]["finished"])
            self.assertTrue(any("Your current round is kept" in i.value for i in at.info))
            self.assertEqual([e.value for e in at.exception], [])

    def test_daily_states_on_the_explore_home(self):
        from datetime import date
        with mock.patch("core.daily.utc_today", return_value=date(2026, 10, 10)):
            at = self.new()
            self.assertEqual(at.button(key="explore_daily").label, "Start today's challenge")
            at.button(key="explore_daily").click().run()
            self.assertEqual(at.session_state["quiz"]["mode"], "daily")
            at.button(key="nav_Explore").click().run()
            self.assertEqual(at.button(key="explore_daily").label, "Continue today's challenge")
            at.button(key="explore_daily").click().run()
            for i in range(5):
                q = at.session_state["quiz"]
                qn = q["questions"][i]
                at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(qn['answer'])}").click().run()
                at.button(key=f"next_{q['serial']}_{i}").click().run()
            at.button(key="nav_Explore").click().run()
            self.assertEqual(at.button(key="explore_daily").label, "Replay today's challenge")
            self.assertIn("<b>1</b>", self.summary(at))              # day streak 1

    def test_every_language_renders_the_map_home(self):
        from core.i18n import translate
        for lang in LANGS:
            at = self.new(app_language=lang, explore_selected="North America")
            self.assertEqual([e.value for e in at.exception], [], lang)
            self.assertEqual(at.button(key="continent_back").label, translate("World map", lang))
            self.assertEqual(at.button(key="continent_quiz").label,
                             translate("Quiz {name}", lang, name=translate("North America", lang)))
            heading = next(m.value for m in at.markdown if 'class="continent-title"' in m.value)
            self.assertIn(translate("North America", lang), heading)
            at.button(key="continent_back").click().run()
            self.assertEqual(at.button(key=self.btn("South America")).label, translate("South America", lang))
            self.assertEqual(at.button(key="browse_all").label, translate("All", lang))

    # ---- V22 colourful home: map first, colour key, one summary line, no credits box on the home page
    def test_home_order_map_then_pills_then_one_summary_line(self):
        import inspect
        from ui import pages
        src = inspect.getsource(pages.explore)
        # Project Atlas: the heading (title + search) comes first, then the map, its pills, and the summary line
        heading, first_map, pills, bar = (src.find("_explore_heading("), src.find("_explore_map("), src.find("_continent_buttons()"),
                                          src.find("_explore_topbar(d)"))
        self.assertTrue(0 <= heading < first_map < pills < bar, (heading, first_map, pills, bar))
        self.assertIn("world_map.render(", inspect.getsource(pages._explore_map))
        self.assertNotIn("home-welcome", src)                                    # no decorative banner
        at = self.new()
        summary = self.summary(at)
        for label in ("Day streak", "Points", "Badges"):                   # labels are visible now, under the numbers
            self.assertIn(f'<span class="summary-label">{label}</span>', summary)
        self.assertNotIn("Photography credits", [x.label for x in at.expander])

    def test_map_colours_are_distinct_and_readable(self):
        from ui import world_map
        fills = world_map.FILLS
        self.assertEqual(len(set(fills.values())), 6)

        def lum(h):
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
        for name, colour in fills.items():                                 # dark label text stays easy to read
            self.assertGreaterEqual((lum(colour) + 0.05) / (lum("#13202E") + 0.05), 6, name)
        for a, b in (("Europe", "Asia"), ("Africa", "Asia"), ("Europe", "Africa"), ("North America", "South America")):
            self.assertGreater(abs(lum(fills[a]) - lum(fills[b])), 0.1, (a, b))   # neighbours differ in lightness
        css = (Path(APP).parent / "assets" / "styles.css").read_text(encoding="utf-8")
        for name, colour in fills.items():                                 # the pills carry the same colours
            self.assertIn(f'.st-key-continent_btn_{name.replace(" ", "_")} button::before {{ background:{colour}; }}', css)

    def test_map_zoom_and_pan_keep_proportions_and_a_whole_world_button(self):
        from core.i18n import translate
        from ui import world_map
        js = world_map.JS
        self.assertIn("function installZoom", js)
        self.assertIn("h = w / a", js)                                     # the view's shape always matches the screen box,
        self.assertIn('preserveAspectRatio: "xMidYMid meet"', js)          # so the map is never stretched
        self.assertIn('class="zall"', js)                                  # one tap back to the complete world
        self.assertIn("ev.ctrlKey || ev.metaKey", js)                      # plain scrolling still scrolls the page
        self.assertIn("if (dragged)", js)                                  # a drag never opens a continent
        self.assertIn("animate(whole())", js)                              # the globe returns to the complete world
        for gone in ("zexp", "wm-close", "wm-full", "setExpanded"):         # no full-screen viewer any more
            self.assertNotIn(gone, js + world_map.CSS)
        self.assertNotIn(".wm svg", world_map.CSS)                         # styles never reach the small button icons
        for lang in LANGS:
            for label in world_map.ZOOM_LABELS.values():
                self.assertTrue(translate(label, lang), (label, lang))
        at = self.new()
        self.assertEqual([e.value for e in at.exception], [])

    def test_map_stays_light_and_does_not_pile_up_listeners(self):
        from ui import world_map
        js = world_map.JS
        # phones and touch screens draw without the costly texture filters (desktop keeps them)
        self.assertIn('matchMedia("(max-width:700px), (pointer:coarse)")', js)
        self.assertIn('if (!lite) coast.setAttribute("filter", "url(#we-glow)")', js)
        # page-wide pointer listeners once per page, not once per return to Explore; one resize observer
        self.assertIn("if (!window.__weZoomListeners)", js)
        self.assertNotIn('window.addEventListener("pointermove", move', js)
        self.assertIn("window.__weResize.disconnect()", js)
        self.assertNotIn("new ResizeObserver(fit).observe(svg)", js)

    def test_phone_portrait_layout_is_isolated(self):
        css = (Path(APP).parent / "assets" / "styles.css").read_text(encoding="utf-8")
        block = css.split("/* ---------- Explore on phones in portrait (V22 mobile)", 1)[1]
        self.assertIn("@media (max-width:700px) and (orientation:portrait)", block)   # desktop/landscape untouched
        for rule in (".st-key-explore_daily { flex:1 1 100% !important",              # full-width challenge button
                     "white-space:nowrap !important",                                   # on one line
                     ".st-key-app_footer { flex-direction:column !important"):          # small footer, left aligned
            self.assertIn(rule.split(" {")[0], block)
        self.assertIn("flex-wrap:nowrap !important", css.split(".stApp .st-key-continent_buttons {", 1)[1][:200])

    def test_footer_tells_the_truth_about_saving(self):
        src = (Path(APP)).read_text(encoding="utf-8")
        self.assertIn('"guest": "Progress is kept until you reload or close this page"', src)   # a refresh starts afresh
        self.assertIn('"saved": "Progress saved to your account"', src)   # only after a confirmed save
        self.assertNotIn("progress lasts for this browser session", src)
        at = self.new()
        self.assertTrue(any("Progress is kept until you reload or close this page" in c.value for c in at.caption))

    def test_phone_statistics_centre_icon_and_number(self):
        css = (Path(APP).parent / "assets" / "styles.css").read_text(encoding="utf-8")
        block = css.split("/* ---------- Explore on phones in portrait (V22 mobile)", 1)[1]
        self.assertIn('grid-template-areas:". i v ." "l l l l"', block)

    def test_siberia_is_drawn_as_asia_but_russia_stays_in_europe(self):
        from core.data import get_country
        from ui import world_map
        self.assertEqual(get_country("RUS")["continent"], "Europe")         # the country data is unchanged
        x_moscow, _ = world_map._project(37.6, 55.8)
        x_novosibirsk, _ = world_map._project(82.9, 55.0)
        line = [world_map._project(*ll) for ll in world_map.URALS]
        x_urals = min(x for x, y in line if 40 < y < 200)
        self.assertLess(x_moscow, x_urals)
        self.assertGreater(x_novosibirsk, x_urals)
        self.assertIn("west", world_map.SPLIT)
        self.assertIn("east", world_map.SPLIT)
        self.assertIn("we-east", world_map.JS)                              # the eastern part is drawn as Asia
        self.assertIn('["Asia", "url(#we-east)"]', world_map.JS)

    # ---- Project Atlas (Premium Digital Atlas V2) Explore
    def test_heading_search_opens_all_countries_filtered(self):
        at = self.new()
        self.assertTrue(any('class="atlas-title"' in m.value and "Where would you like to go?" in m.value for m in at.markdown))
        at.text_input(key="explore_find").input("Bern").run()
        ss = at.session_state
        self.assertEqual((ss["explore_selected"], ss["explore_search"], ss["explore_page"]), ("World", "Bern", 0))
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("discover_")], ["discover_CHE"])
        self.assertNotIn("explore_find", [x.key for x in at.text_input])       # the list has its own search now
        self.assertEqual([e.value for e in at.exception], [])

    def test_continent_keeps_the_map_in_the_panel_and_zooms_to_it(self):
        from ui import world_map
        seen = []
        real = world_map.render
        with mock.patch.object(world_map, "render", side_effect=lambda *a, **k: (seen.append(k), real(*a, **k))[1]):
            at = self.new()
            at.button(key=self.btn("Africa")).click().run()
        self.assertFalse(seen[-1]["hidden"], "the map must stay visible while the countries are shown")
        self.assertEqual(seen[-1]["focus"], "Africa")
        self.assertIn("Africa", world_map.FOCUS_BOXES)
        self.assertEqual(len([b for b in at.button if b.key and b.key.startswith("discover_")]), 10)
        self.assertEqual([e.value for e in at.exception], [])

    def test_every_country_row_shows_its_flag_left_of_the_name(self):
        at = self.new(explore_selected="Europe")
        rows = [m.value for m in at.markdown if 'class="row-copy"' in m.value]
        self.assertEqual(len(rows), 10)
        for row in rows:
            self.assertLess(row.index('class="row-flag"'), row.index('class="row-name"'), row[:120])
            self.assertIn('src="data:image/webp;base64,', row)

    def test_chosen_country_takes_the_lists_place(self):
        at = self.new(explore_selected="Africa")
        at.button(key="discover_NGA").click().run()
        self.assertTrue(at.session_state["explore_detail_open"])
        self.assertTrue(any('class="detail-name"' in m.value for m in at.markdown))
        at.button(key="country_back").click().run()
        self.assertFalse(at.session_state["explore_detail_open"])
        self.assertEqual(at.button(key="discover_NGA").proto.type, "primary")
        self.assertEqual([e.value for e in at.exception], [])


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class SoundTests(unittest.TestCase):
    def test_generated_tones_are_short_quiet_wavs(self):
        import io
        import wave
        from ui import sound
        for kind in sound.PATTERNS:
            data = sound.tone(kind, 100)
            with wave.open(io.BytesIO(data)) as w:
                self.assertLess(w.getnframes() / w.getframerate(), 0.6)
            peak = max(abs(int.from_bytes(data[44 + i:46 + i], "little", signed=True)) for i in range(0, len(data) - 46, 2))
            self.assertLessEqual(peak, int(0.35 * 32767) + 1)
        self.assertEqual(max(sound.tone("correct", 0)[44:]), 0)


if __name__ == "__main__":
    unittest.main()
