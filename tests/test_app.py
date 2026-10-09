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
LANGS = ("English", "Deutsch", "Español", "中文（普通话）")


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
        at = self.new()
        cards = [b for b in at.button if b.key and b.key.startswith("discover_")]
        self.assertEqual(len(cards), 7)  # seven per page, never hundreds of cards at once
        at.text_input(key="explore_search").input("Bern").run()
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("discover_")], ["discover_CHE"])
        at = self.new(scope_collection="All countries and territories")
        at.selectbox(key="explore_status").select("territory").run()
        self.assertClean(at)
        self.assertTrue(any("Territory or dependency" in m.value for m in at.markdown))
        at.button(key="explore_next").click().run()
        self.assertClean(at)

    def test_learn_shows_status_flag_and_corrected_facts(self):
        at = self.new(page="Learn", learn_country="LKA")
        self.assertClean(at)
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("No land borders with other places in this collection.", text)
        self.assertGreaterEqual(len(at.get("image")), 1)
        at = self.new(page="Learn", learn_country="VAT")
        self.assertIn("UN observer state", " ".join(m.value for m in at.markdown))

    def _play_round(self, at, wrong_every=2):
        at.button(key="nav_Quiz").click().run()
        at.selectbox(key="filter_count").select(5).run()
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
        at.selectbox(key="filter_count").select(50).run()
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
        at.selectbox(key="filter_difficulty").select("Expert").run()
        at.button(key="nav_Explore").click().run()
        at.button(key="nav_Badges").click().run()
        at.button(key="nav_Quiz").click().run()
        self.assertEqual(at.selectbox(key="filter_category").value, "Capitals")
        self.assertEqual(at.selectbox(key="filter_difficulty").value, "Expert")
        self.assertEqual([w.value for w in at.warning], [])

    def test_badges_recorded_once_from_quiz_activity(self):
        at = self.new(page="Badges")
        self.assertEqual(at.session_state["stats"]["answered"], 0)        # opening Badges records nothing
        at.run()
        self.assertEqual(at.session_state["stats"]["answered"], 0)
        at.button(key="nav_Quiz").click().run()
        at.selectbox(key="filter_count").select(5).run()
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

    # ---------------------------------------------------------------- compact layout (7 per page, badges)

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
        cases = [({}, {}),
                 ({"scope_collection": "All countries and territories"}, {}),
                 ({"scope_collection": "All countries and territories"}, {"explore_continent": "Europe"}),
                 ({"scope_collection": "All countries and territories"}, {"explore_status": "territory"}),
                 ({}, {"explore_search": "an"})]
        for state, filters in cases:
            at = self.new(**state)
            for key, value in filters.items():
                (at.text_input(key=key).input(value) if key == "explore_search" else at.selectbox(key=key).select(value)).run()
            pages = self._walk_explore(at)
            keys = [k for page in pages for k in page]
            self.assertEqual(len(keys), len(set(keys)), (state, filters))                       # no duplicates
            self.assertTrue(all(len(p) == 7 for p in pages[:-1]) and 1 <= len(pages[-1]) <= 7)  # no gaps
            caption = " ".join(c.value for c in at.caption)
            self.assertIn(f"· {len(keys)} countries", caption, (state, filters))
            if not filters:  # unfiltered: exactly the places in the chosen collection
                everything = get_countries(collection="All countries and territories")
                expected = {c["id"] for c in everything if state or c["status"] in ("un_member", "un_observer")}
                self.assertEqual(len(expected), 244 if state else 195)
                self.assertEqual({k.removeprefix("discover_") for k in keys}, expected)

    def test_seventh_card_discover_opens_learn(self):
        at = self.new()
        seventh = [b.key for b in at.button if b.key and b.key.startswith("discover_")][6]
        at.button(key=seventh).click().run()
        self.assertEqual(at.session_state["page"], "Learn")
        self.assertEqual(at.session_state["learn_country"], seventh.removeprefix("discover_"))

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
        at.selectbox(key="filter_count").select(5).run()
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
            at.selectbox(key="filter_count").select(5).run()
            at.button(key="start_quiz").click().run()
            self._answer_all(at, correct=True)
            self.assertEqual([e.value for e in at.exception], [], lang)

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
