"""The four pages: Explore, Learn, Quiz and Badges."""
from __future__ import annotations

import math
from html import escape

import streamlit as st

from core import quiz as engine
from core.data import AREAS, PHOTOS, get_countries, get_country, load_political_records, neighbours
from core.quiz import CATEGORIES, DIFFICULTIES, QUESTION_COUNTS, currency_label

from . import state
from .components import cover_style, e, globe_art, hero, html, photo_credits
from .state import formatter, parts, t

EXPLORE_PAGE_SIZE = 9
FEATURED = ("NGA", "JPN", "ITA", "BRA")


# --------------------------------------------------------------------------- Explore

def _reset_explore_page() -> None:
    st.session_state.explore_page = 0


def _turn_page(delta: int) -> None:
    st.session_state.explore_page = max(0, st.session_state.explore_page + delta)


def _country_card(c: dict) -> None:
    with st.container(key=f"country_card_{c['id']}"):
        artwork = "" if c["id"] in PHOTOS else globe_art()
        capitals = " · ".join(x["name"] for x in c["capitals"])
        html(f'<div class="destination-cover" role="img" aria-label="{escape(c["name"], quote=True)}" style="{cover_style(c)}">'
             f'{artwork}<span class="destination-id">{c["id"]}</span></div>'
             f'<div class="destination-copy"><div class="destination-region">{e(c["continent"])}</div>'
             f'<div class="destination-name">{escape(c["name"])}</div>'
             f'<div class="destination-capital">{escape(capitals)}</div></div>')
        st.button(t("Discover →"), key=f"discover_{c['id']}", use_container_width=True, on_click=state.learn, args=(c["id"],))


def explore() -> None:
    available = state.scoped_countries()
    feature = next((c for code in FEATURED for c in available if c["id"] == code), available[0])
    photo = PHOTOS.get(feature["id"])
    with st.container(key="atlas_feature"):
        html(f'<div class="feature-scene" style="{cover_style(feature)}"></div>'
             f'<div class="feature-copy"><div class="feature-kicker">{e("Featured destination")}</div>'
             f'<div class="feature-title">{escape(feature["name"])}.<br>{e("A world of discovery.")}</div>'
             f'<div class="feature-description">{e("Explore places. Build knowledge. Find your next challenge.")}</div>'
             f'<div class="feature-place">{escape(photo["caption"]) if photo else e(feature["continent"])}</div></div>')
        st.button(t("Discover country →"), key="featured_discover", type="primary", use_container_width=True,
                  on_click=state.learn, args=(feature["id"],))

    with st.container(key="explore_scope"):
        area, change = st.columns([4, 1], vertical_alignment="center")
        area.markdown(f'<div class="browse-scope">{escape(state.scope_label())}</div>', unsafe_allow_html=True)
        change.button(t("Change"), key="atlas_scope_change", use_container_width=True, on_click=state.open_settings)

    collection, invitation = st.columns([2.35, 1], gap="large")
    with collection:
        query = st.text_input(t("Search countries or capitals"), key="explore_search", on_change=_reset_explore_page)
        needle = query.strip().casefold()
        if needle:
            entries = [c for c in available if needle in c["name"].casefold()
                       or any(needle in x["name"].casefold() for x in c["capitals"])]
        else:  # photographed destinations first, then alphabetical
            entries = sorted(available, key=lambda c: (c["id"] not in PHOTOS, c["name"]))
        if not entries:
            st.info(t("No countries match your search."))
        else:
            pages = math.ceil(len(entries) / EXPLORE_PAGE_SIZE)
            page = st.session_state.explore_page = min(st.session_state.explore_page, pages - 1)
            batch = entries[page * EXPLORE_PAGE_SIZE:(page + 1) * EXPLORE_PAGE_SIZE]
            for row in range(0, len(batch), 3):
                for column, country in zip(st.columns(3), batch[row:row + 3]):
                    with column:
                        _country_card(country)
            if pages > 1:
                with st.container(key="explore_pagination"):
                    previous, status, following = st.columns([1, 2, 1], vertical_alignment="center")
                    previous.button(t("Previous"), key="explore_previous", disabled=page == 0,
                                    use_container_width=True, on_click=_turn_page, args=(-1,))
                    status.caption(t("Page {page} of {pages} · {count} countries", page=page + 1, pages=pages, count=len(entries)))
                    following.button(t("Next"), key="explore_next", disabled=page + 1 >= pages,
                                     use_container_width=True, on_click=_turn_page, args=(1,))
    with invitation:
        with st.container(key="atlas_quiz"):
            html(f'<div class="feature-kicker">{e("Your next adventure")}</div>'
                 '<div class="challenge-compass" aria-hidden="true">✧</div>'
                 f'<div class="challenge-title">{e("Your next challenge")}</div>'
                 f'<div class="challenge-note">{e("Capitals, currencies, languages and more.")}</div>')
            st.button(t("Take a quiz →"), key="atlas_take_quiz", type="primary", use_container_width=True,
                      on_click=state.navigate, args=("Quiz",))
        html(f'<div class="atlas-small">{e("Explore at your pace.")}</div>')
    photo_credits()


# --------------------------------------------------------------------------- Learn

def learn() -> None:
    hero("The country collection", "Get to know the world.",
         "Build your knowledge, one country at a time. The details make all the difference.")
    ids = [c["id"] for c in state.scoped_countries()]
    if st.session_state.get("learn_country") not in ids:
        st.session_state.learn_country = ids[0]
    c = get_country(st.selectbox(t("Choose a country"), ids, format_func=lambda i: get_country(i)["name"], key="learn_country"))
    with st.container(key="learn_card"):
        html(f'<div class="country-top"><span class="country-code">{c["id"]}</span>'
             f'<span class="country-region">{escape(c["region"])}</span></div>')
        st.subheader(c["name"])
        facts = [("Continent / region", f"{t(c['continent'])} · {c['region']}"),
                 ("Capital roles", "; ".join(f"{x['name']} ({t(x['role'])})" for x in c["capitals"])),
                 ("Currencies", ", ".join(map(currency_label, c["currencies"])) or t("Not included yet")),
                 ("Official languages in this collection", ", ".join(c["official_languages"]) or t("Not included yet"))]
        tiles = "".join(f'<div class="fact-tile"><div class="fact-label">{e(label)}</div>'
                        f'<div class="fact-value">{escape(value)}</div></div>' for label, value in facts)
        html(f'<div class="fact-grid">{tiles}</div>')
        near = neighbours(c)
        if near:
            st.write(t("Neighbours in this collection: {names}", names=", ".join(n["name"] for n in near)))
        if c["landmarks"]:
            st.write(t("Landmarks") + ": " + " · ".join(f"[{s['name']}]({s['source']})" for s in c["landmarks"]))
        leader = load_political_records().get(c["id"])
        if leader:
            st.write(t("Head of state: **{names}** ({title}).", names=" / ".join(leader["names"]), title=leader["title"]))
            st.caption(t("Political record verified {date}.", date=leader["verified_on"]))
            st.markdown(f"[{t('Political source')}]({leader['source']})")
        st.markdown(f"[{t('Country data source')}]({c['source']})")
        if c.get("capital_source"):
            st.markdown(f"[{t('Capital-role source')}]({c['capital_source']})")


# --------------------------------------------------------------------------- Quiz

def _reset_country_filter() -> None:
    st.session_state.filter_country = "all"


def _setup() -> None:
    st.session_state.setdefault("filter_continent", st.session_state.scope_continent)
    st.session_state.setdefault("filter_country", st.session_state.scope_country)
    with st.container(key="settings_card"):
        html(f'<div class="eyebrow">{e("Your next adventure")}</div>')
        st.subheader(t("Build your challenge"))
        one, two = st.columns(2)
        continent = one.selectbox(t("Continent"), AREAS, format_func=formatter(AREAS), key="filter_continent",
                                  on_change=_reset_country_filter)
        ids = ["all"] + [c["id"] for c in get_countries(continent)]
        if st.session_state.filter_country not in ids:
            st.session_state.filter_country = "all"
        all_label = t("All Countries")
        country_id = two.selectbox(t("Country"), ids, key="filter_country",
                                   format_func=lambda i: all_label if i == "all" else get_country(i)["name"])
        left, right = st.columns(2)
        category = left.selectbox(t("Category"), CATEGORIES, format_func=formatter(CATEGORIES), key="filter_category")
        count = left.selectbox(t("Questions"), QUESTION_COUNTS, index=1, key="filter_count")
        difficulty = right.selectbox(t("Difficulty"), DIFFICULTIES, format_func=formatter(DIFFICULTIES), index=1,
                                     key="filter_difficulty")
        timer = right.toggle(t("Timed challenge"), value=False, key="filter_timer",
                             help=t("15 seconds per question on Expert; 20 seconds on other levels."))
        settings = {"continent": continent, "country_id": country_id, "category": category,
                    "difficulty": difficulty, "count": count, "timer": timer}
        round_size, _ = state.preview(settings)
        st.caption(t("Up to {n} questions · no repeated facts in the same round.", n=count))
        if category == "Heads of State":
            st.caption(t("Only recently verified political records are included. Coverage is currently limited."))
        if country_id != "all" and difficulty in ("Difficult", "Expert"):
            st.caption(t("Your chosen country stays selected; difficulty changes question formats and answer choices."))
        if not round_size:
            st.info(t("No verified questions match these filters. Choose Mixed, another country, or a lower difficulty."))
        elif round_size < count:
            st.info(t("This round will contain {n} questions, without repeating the same question.", n=round_size))
        if st.button(t("Start quiz"), key="start_quiz", type="primary", use_container_width=True, disabled=not round_size):
            state.start_round(settings)
            st.rerun()
        if st.session_state.quiz and not st.session_state.quiz["finished"]:
            st.button(t("Return to current round"), use_container_width=True, on_click=state.close_setup)
        with st.expander(t("Scoring and hints")):
            st.write(t("Correct answers earn 100 base points, multiplied by difficulty: Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2."))
            st.write(t("Fast answers earn 25 extra points. Every third correct answer in a streak adds 50; every fifth adds 100. "
                       "A hint removes one wrong option and deducts 25 from a correct answer's award. Each round has three hints."))
            st.write(t("A perfect round without hints adds 250 points × difficulty. Wrong and timed-out answers earn zero. "
                       "You can always use Next to read the explanation at your own pace."))


def _score_strip(quiz) -> None:
    items = (("Round score", f"{quiz['score']:,}"), ("Current streak", quiz["streak"]), ("Hints remaining", quiz["hints_remaining"]))
    html('<div class="score-strip">' + "".join(
        f'<div class="score-item"><div class="score-label">{e(label)}</div><div class="score-value">{value}</div></div>'
        for label, value in items) + "</div>")


def _active_round() -> None:
    quiz = st.session_state.quiz
    if not quiz or quiz["finished"] or st.session_state.show_setup or st.session_state.page != "Quiz":
        return
    state.expire_if_due()
    q, index, serial = engine.current_question(quiz), quiz["index"], quiz["serial"]
    total, limit = len(quiz["questions"]), engine.time_limit(quiz)
    _score_strip(quiz)
    st.caption(t("Question {n} of {total} · {kind} · {difficulty}", n=index + 1, total=total,
                 kind=q["kind"], difficulty=quiz["settings"]["difficulty"]))
    st.progress((index + quiz["resolved"]) / total)
    with st.container(key="question_card"):
        if limit is not None:
            if quiz["resolved"]:
                st.caption(t("Answer recorded"))
            else:
                remaining = max(0, math.ceil(limit - engine.elapsed(quiz)))
                st.caption(t("Time remaining: {n} seconds", n=remaining))
                st.progress(remaining / limit)
        st.subheader(parts(q["prompt"]))
        for row in range(0, len(q["choices"]), 2):
            for column, choice in zip(st.columns(2), q["choices"][row:row + 2]):
                pos = q["choices"].index(choice)
                style, label = "neutral_answer", t(choice)
                if quiz["resolved"] and choice == q["answer"]:
                    style, label = "correct_answer", f"✓ {t(choice)} — {t('Correct answer')}"
                elif quiz["resolved"] and choice == quiz["selected"]:
                    style, label = "wrong_answer", f"✕ {t(choice)} — {t('Your answer')}"
                elif choice in quiz["hidden_options"]:
                    label = t("Removed by hint")
                with column, st.container(key=f"{style}_{pos}"):
                    st.button(label, key=f"answer_{serial}_{index}_{pos}", use_container_width=True,
                              disabled=quiz["resolved"] or choice in quiz["hidden_options"],
                              on_click=state.answer, args=(choice, serial, index))
        if not quiz["resolved"] and len(q["choices"]) == 4:
            st.button(t("Use hint · −25 if correct"), key=f"hint_{serial}_{index}",
                      disabled=quiz["hint_used"] or quiz["hints_remaining"] == 0,
                      on_click=state.hint, args=(serial, index))
        if quiz["resolved"]:
            record, explanation = quiz["history"][-1], parts(q["explanation"])
            if record["correct"]:
                st.success(f"{t('Correct!')} {explanation}")
            else:
                prefix = f"{t('Time is up.')} " if record["timed_out"] else ""
                (st.warning if record["timed_out"] else st.error)(
                    f"{prefix}{t('Correct answer')}: {t(q['answer'])}. {explanation}")
            p = quiz["last_points"]
            st.caption(t("+{points} points · Base {base} · Speed +{speed} · Streak +{streak} · Hint −{hint}",
                         points=p["total"], base=p["base"], speed=p["speed"], streak=p["streak"], hint=p["hint"]))
            final = index + 1 == total
            with st.container(key="quiz_next_action"):
                if st.button(t("View results" if final else "Next question →"), type="primary",
                             use_container_width=True, key=f"next_{serial}_{index}"):
                    state.next_question(serial, index)
                    st.rerun()  # full rerun: results and the timer schedule live outside this fragment


def _answer_review(quiz) -> None:
    st.subheader(t("Answer review"))
    for i, record in enumerate(quiz["history"], 1):
        q = record["question"]
        mark = "Correct" if record["correct"] else "Timed out" if record["timed_out"] else "Incorrect"
        with st.expander(f"{i}. {t(mark)} · {parts(q['prompt'])}"):
            st.write(f"{t('Your answer')}: **{t(record['answer']) if record['answer'] else t('Unanswered')}**")
            st.write(f"{t('Correct answer')}: **{t(q['answer'])}**")
            st.write(parts(q["explanation"]))
            st.caption(t("{seconds} seconds · {points} points · {hint}", seconds=f"{record['elapsed']:.1f}",
                         points=record["points"]["total"], hint="Hint used" if record["hint"] else "No hint"))
            country = get_country(q["country_id"])
            st.caption(f"{country['name']} · {t(country['continent'])} · {country['region']}")
            links = [f"[{t('Source')}]({q['source']})"]
            if q.get("extra_source") and q["extra_source"] != q["source"]:
                links.append(f"[{t('Capital-role source')}]({q['extra_source']})")
            st.markdown(" · ".join(links))


def _results(quiz) -> None:
    stats, settings = engine.statistics(quiz), quiz["settings"]
    with st.container(key="result_card"):
        html(f'<div class="eyebrow">{e("Challenge complete")}</div>')
        st.subheader(t("Your results"))
        html(f'<div class="result-number">{stats["score"]:,}<span class="result-unit"> {e("points")}</span></div>')
        first, second, third = st.columns(3)
        first.metric(t("Accuracy"), f"{stats['accuracy']:.0f}%")
        second.metric(t("Correct answers"), f"{stats['correct']} / {stats['total']}")
        third.metric(t("Best streak"), stats["best_streak"])
        st.caption(t("Incorrect / unanswered: {wrong} · Timed out: {timeout} · Average response time: {seconds} seconds",
                     wrong=stats["incorrect"], timeout=stats["timed_out"], seconds=f"{stats['average_time']:.1f}"))
        country = get_country(settings["country_id"])
        st.caption(" · ".join([t(settings["continent"]), country["name"] if country else t("All Countries"),
                               t(settings["category"]), t(settings["difficulty"]), t("{n} questions", n=stats["total"])]))
        if quiz["perfect_bonus"]:
            st.success(t("Perfect round without hints: +{points} bonus points.", points=quiz["perfect_bonus"]))
        one, two = st.columns(2)
        if one.button(t("Play again"), type="primary", use_container_width=True):
            state.start_round(settings)
            st.rerun()
        two.button(t("Change settings"), use_container_width=True, on_click=state.open_setup)
        if st.button(t("Review answers"), use_container_width=True):
            st.session_state.review_answers = not st.session_state.review_answers
    if st.session_state.review_answers:
        _answer_review(quiz)


def quiz() -> None:
    current = st.session_state.quiz
    if not current or st.session_state.show_setup:
        intro, setup = st.columns([1, 1.15], gap="large")
        with intro:
            hero("The world geography challenge", "How well do you know your world?",
                 "Go beyond the familiar. Challenge yourself on capitals, currencies, languages and the places in between.",
                 variant="tall")
        with setup:
            _setup()
        return
    hero("World Quiz", "Every answer takes you further.", "Think carefully. Build a streak. Discover something new.",
         variant="compact")
    with st.container(key="settings_card"):
        summary, action = st.columns([3, 1])
        s = current["settings"]
        country = get_country(s["country_id"])
        label = country["name"] if country else t(s["continent"])
        summary.markdown(f'<div class="round-label">{e("Current challenge")}</div>'
                         f'<div class="round-summary">{escape(label)} · {e(s["difficulty"])} · {e(s["category"])}</div>',
                         unsafe_allow_html=True)
        action.button(t("Change"), use_container_width=True, on_click=state.open_setup)
    if current["finished"]:
        _results(current)
    else:
        # Only timed rounds tick; untimed rounds rerun on interaction alone.
        st.fragment(run_every=1 if s["timer"] else None)(_active_round)()


# --------------------------------------------------------------------------- Badges

def badges() -> None:
    hero("Your explorer passport", "Curiosity deserves recognition.",
         "Every right answer is a step forward. Collect milestones as your knowledge grows.")
    points, rounds = st.session_state.points, st.session_state.rounds_finished
    st.caption(t("{points} lifetime session points · {rounds} rounds completed", points=f"{points:,}", rounds=rounds))
    awards = (("First Steps", points > 0, "Answer your first question correctly.", "✦"),
              ("Century", points >= 100, "Earn 100 points.", "★"),
              ("Round Finisher", rounds >= 1, "Complete your first quiz round.", "✓"))
    for i, (column, (name, earned, description, symbol)) in enumerate(zip(st.columns(len(awards)), awards)):
        with column, st.container(key=f"award_card_{i}"):
            html(f'<div class="award-medal {"" if earned else "locked"}">{symbol}</div>')
            st.subheader(t(name))
            html(f'<span class="award-state {"earned" if earned else ""}">{e("Earned" if earned else "In progress")}</span>')
            st.caption(t(description))


ROUTES = {"Explore": explore, "Learn": learn, "Quiz": quiz, "Badges": badges}
