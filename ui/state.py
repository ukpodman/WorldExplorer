"""Session state, translation shortcut and the callbacks that drive a round."""
from __future__ import annotations

import time
from datetime import date

import streamlit as st

from core import badges, daily, records
from core import quiz as engine
from core.data import COLLECTIONS, CONTINENTS, DEFAULT_COLLECTION, get_countries, get_country, load_political_records
from core.i18n import DEFAULT_LANGUAGE, render_parts, translate

PAGES = ("Explore", "Learn", "Quiz", "Badges")
RECENT_COUNTRIES, RECENT_FACTS = 40, 160

DEFAULTS = {
    "page": "Explore", "app_language": DEFAULT_LANGUAGE, "settings_open": False,
    "profile_name": "", "profile_photo": "", "photo_upload_digest": None,
    "scope_mode": "All countries", "scope_continent": "World", "scope_country": "all",
    "scope_collection": DEFAULT_COLLECTION,
    "points": 0, "rounds_finished": 0, "recent": [], "recent_facts": [],
    "sound_enabled": False, "sound_volume": 40,
    "quiz": None, "quiz_serial": 0, "show_setup": False, "review_mode": "missed",
    "explore_page": 0, "profile_save_error": False, "size_reference": "",
}


def init() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, list(value) if isinstance(value, list) else value)
    if badges.sanitize_stats(st.session_state.get("stats")) is None:
        st.session_state.stats = badges.empty_stats()
    if records.sanitize_records(st.session_state.get("records")) is None:
        st.session_state.records = records.empty_records()
    if daily.sanitize_daily(st.session_state.get("daily")) is None:
        st.session_state.daily = daily.empty_daily()
    if daily.sanitize_mistakes(st.session_state.get("mistakes")) is None:
        st.session_state.mistakes = []


# --------------------------------------------------------------------------- language

def language() -> str:
    return st.session_state.get("app_language", DEFAULT_LANGUAGE)


def t(text, **fields):
    return translate(text, language(), **fields)


def parts(template_parts) -> str:
    return render_parts(template_parts, language())


def formatter(values):
    """format_func for selectboxes: show translated labels, keep canonical values."""
    labels = {v: t(v) for v in values}
    return lambda v: labels.get(v, str(v))


def country_label(country_id: str) -> str:
    return t(get_country(country_id)["name"])


def country_formatter(all_label: str | None = None):
    """format_func for country selectboxes, with the current language captured up front."""
    lang = language()
    names = {}

    def label(country_id):
        if country_id == "all":
            return all_label or "all"
        if country_id not in names:
            names[country_id] = translate(get_country(country_id)["name"], lang)
        return names[country_id]
    return label


# --------------------------------------------------------------------------- navigation & scope

def navigate(page: str) -> None:
    st.session_state.page = page


def learn(country_id: str) -> None:
    st.session_state.learn_country = country_id
    navigate("Learn")


def learn_ids() -> list[str]:
    """Country order for Learn: the exploration scope, in the same order as the dropdown."""
    return [c["id"] for c in scoped_countries()]


def learn_step(delta: int) -> None:
    """Previous / Next. Only the Learn selection changes; an unfinished quiz round is untouched."""
    target = learn_step_target(delta)
    if target:
        st.session_state.learn_country = target


def learn_step_target(delta: int):
    from core.learn import step
    return step(learn_ids(), st.session_state.get("learn_country"), delta)


def learn_surprise() -> None:
    from core.learn import surprise
    target = surprise(learn_ids(), st.session_state.get("learn_country"))
    if target:
        st.session_state.learn_country = target


def remember_size_reference() -> None:
    """Copy the comparison choice out of the widget so it survives leaving Learn (and is saved with profiles)."""
    st.session_state.size_reference = st.session_state.get("size_reference_select") or ""


def open_settings() -> None:
    st.session_state.settings_open = True
    st.session_state.explore_area_open = False  # never show the same exploration controls twice


def scoped_countries() -> list[dict]:
    """The places Explore, Learn and the quiz defaults work with, per the settings drawer."""
    mode, collection = st.session_state.scope_mode, st.session_state.scope_collection
    if mode == "One country":
        country = get_country(st.session_state.scope_country)
        if country and get_countries(country_id=country["id"], collection=collection):
            return [country]
    if mode == "One continent":
        found = get_countries(st.session_state.scope_continent, collection=collection)
        if found:
            return found
    return get_countries(collection=collection)


def scope_label() -> str:
    mode = st.session_state.scope_mode
    if mode == "One country" and get_country(st.session_state.scope_country):
        return country_label(st.session_state.scope_country)
    area = t(st.session_state.scope_continent) if mode == "One continent" else t("All countries")
    if st.session_state.scope_collection != DEFAULT_COLLECTION:
        area += " · " + t("incl. territories")
    return area


def _after_scope_change() -> None:
    """Keep every page consistent after the exploration area or places collection changes (Settings or Explore):
    quiz setup defaults follow the new area, Explore returns to page 1 with its filters cleared, and Learn moves to a
    country inside the new area if its current one is no longer included. An unfinished quiz round is untouched."""
    st.session_state.filter_continent = st.session_state.scope_continent
    st.session_state.filter_country = st.session_state.scope_country
    st.session_state.filter_collection = st.session_state.scope_collection
    st.session_state.quiz_prefs = {**st.session_state.get("quiz_prefs", {}),
                                   "filter_continent": st.session_state.scope_continent,
                                   "filter_country": st.session_state.scope_country,
                                   "filter_collection": st.session_state.scope_collection}
    st.session_state.explore_page = 0
    st.session_state.explore_search = ""
    st.session_state.pop("explore_continent", None)
    st.session_state.pop("explore_status", None)
    ids = [c["id"] for c in scoped_countries()]
    if st.session_state.get("learn_country") not in ids:
        st.session_state.learn_country = ids[0]


def normalized_scope(mode: str, continent: str, country_id: str, collection: str) -> dict:
    """The same selection rules as Settings: a country must exist in the chosen places collection (otherwise the
    first one is used) and its continent becomes the area; a continent applies only in "One continent" mode."""
    if collection not in COLLECTIONS:
        collection = DEFAULT_COLLECTION
    if mode == "One country":
        ids = [c["id"] for c in get_countries(collection=collection)]
        country_id = country_id if country_id in ids else ids[0]
        continent = get_country(country_id)["continent"]
    elif mode == "One continent":
        continent, country_id = (continent if continent in CONTINENTS else CONTINENTS[0]), "all"
    else:
        mode, continent, country_id = "All countries", "World", "all"
    return {"scope_mode": mode, "scope_continent": continent, "scope_country": country_id, "scope_collection": collection}


def apply_pending_preferences() -> None:
    """Settings are staged in the dialog and applied at the start of the next run,
    before any widget that depends on them is drawn."""
    pending = st.session_state.pop("pending_preferences", None)
    if not pending:
        return
    st.session_state.update(pending)
    _after_scope_change()


def apply_exploration_area() -> None:
    """Explore's inline "Exploration area" controls: apply the change right away to the shared preferences."""
    ss = st.session_state
    chosen = normalized_scope(ss.get("explore_area_mode", ss.scope_mode),
                              ss.get("explore_area_continent", ss.scope_continent),
                              ss.get("explore_area_country", ss.scope_country),
                              ss.get("explore_area_collection", ss.scope_collection))
    if all(ss.get(k) == v for k, v in chosen.items()):
        return
    ss.update(chosen)
    # Keep the inline widgets on valid values (e.g. a country that is not in the newly chosen places).
    if chosen["scope_mode"] == "One country":
        ss.explore_area_country = chosen["scope_country"]
    elif chosen["scope_mode"] == "One continent":
        ss.explore_area_continent = chosen["scope_continent"]
    _after_scope_change()


def toggle_exploration_area() -> None:
    opening = not st.session_state.get("explore_area_open", False)
    st.session_state.explore_area_open = opening
    if opening:  # start from the shared preferences (they may have changed in Settings meanwhile)
        for key in ("explore_area_collection", "explore_area_mode", "explore_area_continent", "explore_area_country"):
            st.session_state.pop(key, None)


# --------------------------------------------------------------------------- quiz

@st.cache_data(ttl=3600, show_spinner=False)
def round_capacity(settings_items: tuple, today: str) -> tuple[int, int]:
    """(questions in a round, distinct facts available). `today` keeps political records fresh."""
    questions, capacity = engine.generate_quiz(dict(settings_items), seed=0)
    return len(questions), capacity


def preview(settings: dict) -> tuple[int, int]:
    return round_capacity(tuple(sorted(settings.items())), date.today().isoformat())


# Round modes: "regular" (quiz setup), "daily" (first attempt of today's challenge), "daily_replay" (later attempts:
# practice, change nothing), "practice" (mistakes). An unfinished round of another kind is kept aside ("parked"),
# never discarded, and can be resumed.
def _group(mode: str) -> str:
    return "daily" if mode in ("daily", "daily_replay") else mode


def _begin(settings: dict, questions: list[dict], available: int, mode: str, day: str | None = None) -> None:
    ss = st.session_state
    current = ss.quiz
    parked = ss.setdefault("parked_rounds", {})
    if current and not current["finished"] and _group(current.get("mode", "regular")) != _group(mode):
        parked[_group(current.get("mode", "regular"))] = current
    parked.pop(_group(mode), None)
    ss.quiz_serial += 1
    ss.quiz = engine.new_round(settings, questions, available, ss.quiz_serial)
    ss.quiz.update(mode=mode, day=day)
    # Badges held when the round began, so the results screen can name newly earned ones.
    ss.quiz["badges_before"] = sorted(badges.earned_ids(ss.stats, ss.points, ss.rounds_finished))
    ss.review_mode = "missed"
    ss.show_setup = False
    ss.page = "Quiz"


def start_round(settings: dict) -> bool:
    questions, available = engine.generate_quiz(settings, st.session_state.recent, st.session_state.recent_facts)
    if not questions:
        return False
    _begin(settings, questions, available, "regular")
    return True


def today():
    return daily.utc_today()


def daily_round_in_progress():
    """Today's unfinished daily round (active or parked), if any."""
    day = today().isoformat()
    for q in (st.session_state.quiz, st.session_state.get("parked_rounds", {}).get("daily")):
        if q and not q["finished"] and _group(q.get("mode", "regular")) == "daily" and q.get("day") == day:
            return q
    return None


def start_daily() -> None:
    """Start or continue today's challenge. After today's first completed attempt, further attempts are replays."""
    if daily_round_in_progress():
        resume_round("daily")
        return
    day = today()
    questions = daily.daily_questions(day)
    mode = "daily_replay" if daily.completed(st.session_state.daily, day) else "daily"
    _begin(daily.DAILY_SETTINGS, questions, len(questions), mode, day.isoformat())


def start_practice() -> bool:
    questions = daily.practice_questions(st.session_state.mistakes, load_political_records(), limit=10)
    if not questions:
        return False
    settings = dict(daily.DAILY_SETTINGS, count=10)
    _begin(settings, questions, len(questions), "practice")
    return True


def resume_round(group: str) -> None:
    ss = st.session_state
    parked = ss.setdefault("parked_rounds", {})
    target = parked.pop(group, None)
    if target is None:  # already active
        ss.show_setup, ss.page = False, "Quiz"
        return
    current = ss.quiz
    if current and not current["finished"]:
        parked[_group(current.get("mode", "regular"))] = current
    ss.quiz = target
    ss.show_setup, ss.page = False, "Quiz"


def parked_rounds() -> dict:
    return {g: q for g, q in st.session_state.get("parked_rounds", {}).items() if q and not q["finished"]}


def _tracked(action) -> None:
    """Run a round action; if it recorded an answer, update session totals and
    the recently-asked lists that keep the next round fresh. Daily replays change nothing."""
    quiz = st.session_state.quiz
    before = len(quiz["history"])
    points = action(quiz)
    if len(quiz["history"]) > before and quiz.get("mode") != "daily_replay":
        record = quiz["history"][-1]
        q = record["question"]
        st.session_state.points += points or 0
        badges.record_answer(st.session_state.stats, q, record["correct"])
        daily.note_answer(st.session_state.mistakes, q, record["correct"], quiz["settings"]["difficulty"])
        st.session_state.recent = (st.session_state.recent + [q["country_id"]])[-RECENT_COUNTRIES:]
        st.session_state.recent_facts = (st.session_state.recent_facts + q["facts"])[-RECENT_FACTS:]


def answer(choice, serial: int, index: int) -> None:
    if engine.is_current(st.session_state.quiz, serial, index):
        _tracked(lambda quiz: engine.resolve(quiz, choice, time.monotonic()))


def expire_if_due() -> None:
    if st.session_state.quiz:
        _tracked(engine.expire_if_due)


def hint(serial: int, index: int) -> None:
    if engine.is_current(st.session_state.quiz, serial, index):
        _tracked(lambda quiz: engine.use_hint(quiz) and 0)  # may record a timeout instead


def next_question(serial: int, index: int) -> None:
    quiz = st.session_state.quiz
    if not engine.is_current(quiz, serial, index):
        return
    replay = quiz.get("mode") == "daily_replay"
    bonus = engine.advance(quiz)
    if not replay:
        st.session_state.points += bonus
    if quiz["finished"] and not quiz.get("round_recorded"):
        quiz["round_recorded"] = True  # totals, badge statistics and records change once per round
        if replay:
            return  # practice replay of today's challenge: nothing is recorded
        st.session_state.rounds_finished += 1
        badges.record_round(st.session_state.stats, quiz)
        records.update(st.session_state.records, quiz)
        if quiz.get("mode") == "daily":
            from datetime import date as _date
            daily.record_daily(st.session_state.daily, _date.fromisoformat(quiz["day"]), quiz["correct"],
                               len(quiz["questions"]), quiz["score"])


QUIZ_FILTER_DEFAULTS = {"filter_category": "Mixed", "filter_difficulty": "Medium", "filter_count": 10,
                        "filter_timer": False, "filter_flags": True}


def restore_quiz_filters() -> None:
    """Quiz setup choices survive leaving the Quiz page (Streamlit drops widget state for unrendered widgets)."""
    saved = st.session_state.get("quiz_prefs", {})
    defaults = dict(QUIZ_FILTER_DEFAULTS, filter_collection=st.session_state.scope_collection,
                    filter_continent=st.session_state.scope_continent, filter_country=st.session_state.scope_country)
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = saved.get(key, default)


def remember_quiz_filters() -> None:
    keys = list(QUIZ_FILTER_DEFAULTS) + ["filter_collection", "filter_continent", "filter_country"]
    st.session_state.quiz_prefs = {k: st.session_state[k] for k in keys if k in st.session_state}


def quiz_on_country(country_id: str) -> None:
    """From Learn: open quiz setup for one country. An unfinished round is kept (setup offers to return to it)."""
    country = get_country(country_id)
    if not country:
        return
    collection = st.session_state.scope_collection
    if not get_countries(country_id=country_id, collection=collection):
        collection = COLLECTIONS[1]  # a territory: include all places so it can be selected
    st.session_state.filter_collection = collection
    st.session_state.filter_continent = country["continent"]
    st.session_state.filter_country = country_id
    remember_quiz_filters()
    st.session_state.show_setup = True
    navigate("Quiz")


def open_setup() -> None:
    st.session_state.show_setup = True


def close_setup() -> None:
    st.session_state.show_setup = False
