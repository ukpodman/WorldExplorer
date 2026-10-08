"""Session state, translation shortcut and the callbacks that drive a round."""
from __future__ import annotations

import time
from datetime import date

import streamlit as st

from core import quiz as engine
from core.data import DEFAULT_COLLECTION, get_countries, get_country
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
    "explore_page": 0, "profile_save_error": False,
}


def init() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, list(value) if isinstance(value, list) else value)


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


def open_settings() -> None:
    st.session_state.settings_open = True


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


def apply_pending_preferences() -> None:
    """Settings are staged in the dialog and applied at the start of the next run,
    before any widget that depends on them is drawn."""
    pending = st.session_state.pop("pending_preferences", None)
    if not pending:
        return
    st.session_state.update(pending)
    st.session_state.filter_continent = st.session_state.scope_continent
    st.session_state.filter_country = st.session_state.scope_country
    st.session_state.filter_collection = st.session_state.scope_collection
    st.session_state.explore_page = 0
    st.session_state.explore_search = ""
    st.session_state.pop("explore_continent", None)
    st.session_state.pop("explore_status", None)
    ids = [c["id"] for c in scoped_countries()]
    if st.session_state.get("learn_country") not in ids:
        st.session_state.learn_country = ids[0]


# --------------------------------------------------------------------------- quiz

@st.cache_data(ttl=3600, show_spinner=False)
def round_capacity(settings_items: tuple, today: str) -> tuple[int, int]:
    """(questions in a round, distinct facts available). `today` keeps political records fresh."""
    questions, capacity = engine.generate_quiz(dict(settings_items), seed=0)
    return len(questions), capacity


def preview(settings: dict) -> tuple[int, int]:
    return round_capacity(tuple(sorted(settings.items())), date.today().isoformat())


def start_round(settings: dict) -> bool:
    questions, available = engine.generate_quiz(settings, st.session_state.recent, st.session_state.recent_facts)
    if not questions:
        return False
    st.session_state.quiz_serial += 1
    st.session_state.quiz = engine.new_round(settings, questions, available, st.session_state.quiz_serial)
    st.session_state.review_mode = "missed"
    st.session_state.show_setup = False
    return True


def _tracked(action) -> None:
    """Run a round action; if it recorded an answer, update session totals and
    the recently-asked lists that keep the next round fresh."""
    quiz = st.session_state.quiz
    before = len(quiz["history"])
    points = action(quiz)
    if len(quiz["history"]) > before:
        q = quiz["history"][-1]["question"]
        st.session_state.points += points or 0
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
    st.session_state.points += engine.advance(quiz)
    if quiz["finished"]:
        st.session_state.rounds_finished += 1


def open_setup() -> None:
    st.session_state.show_setup = True


def close_setup() -> None:
    st.session_state.show_setup = False
