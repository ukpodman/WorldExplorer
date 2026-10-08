"""The four pages: Explore, Learn, Quiz and Badges."""
from __future__ import annotations

import math
from html import escape

import streamlit as st

from core import quiz as engine
from core.data import (AREAS, COLLECTIONS, PHOTOS, STATUS_LABELS, STATUSES, flag_image, get_countries,
                       get_country, load_political_records, neighbours)
from core.quiz import CATEGORIES, DIFFICULTIES, QUESTION_COUNTS, currency_label

from . import sound, state
from .components import e, hero, html, photo_credits, status_chip
from .state import country_formatter, country_label, formatter, parts, t

EXPLORE_PAGE_SIZE = 9
FEATURED = ("NGA", "JPN", "ITA", "BRA")


def _flag(country: dict, width: int, alt: str) -> None:
    image = flag_image(country)
    if image:
        st.image(image, width=width, alt=alt)


# --------------------------------------------------------------------------- Explore

def _reset_explore_page() -> None:
    st.session_state.explore_page = 0


def _turn_page(delta: int) -> None:
    st.session_state.explore_page = max(0, st.session_state.explore_page + delta)


def _country_card(c: dict) -> None:
    with st.container(key=f"country_card_{c['id']}"):
        _flag(c, 120, t("Flag of {name}", name=c["name"]))
        capitals = " · ".join(x["name"] for x in c["capitals"]) or t("No capital listed")
        html(f'<div class="destination-copy"><div class="destination-region">{e(c["continent"])}{status_chip(c)}</div>'
             f'<div class="destination-name">{e(c["name"])}</div>'
             f'<div class="destination-capital">{escape(capitals)}</div></div>')
        st.button(t("Discover →"), key=f"discover_{c['id']}", width="stretch", on_click=state.learn, args=(c["id"],),
                  help=t("Learn about {name}", name=c["name"]))


def _filtered(available: list[dict]) -> list[dict]:
    with st.container(key="explore_filters"):
        search, continent, status = st.columns([2, 1, 1])
        query = search.text_input(t("Search countries or capitals"), key="explore_search", on_change=_reset_explore_page)
        present = [a for a in AREAS if a == "World" or any(a in c["continents"] for c in available)]
        area = continent.selectbox(t("Continent"), present, format_func=formatter(present), key="explore_continent",
                                   on_change=_reset_explore_page)
        statuses = ["all"] + [s for s in STATUSES if any(c["status"] == s for c in available)]
        labels = {"all": t("All statuses"), **{s: t(STATUS_LABELS[s]) for s in STATUSES}}
        chosen = status.selectbox(t("Status"), statuses, format_func=labels.get, key="explore_status",
                                  on_change=_reset_explore_page, disabled=len(statuses) <= 2)
    needle = query.strip().casefold()
    out = []
    for c in available:
        if area != "World" and area not in c["continents"]:
            continue
        if chosen != "all" and c["status"] != chosen:
            continue
        names = [c["name"], t(c["name"]), c.get("official_name", "")] + [x["name"] for x in c["capitals"]]
        if needle and not any(needle in n.casefold() for n in names):
            continue
        out.append(c)
    return out if needle else sorted(out, key=lambda c: (c["id"] not in PHOTOS, t(c["name"])))


def explore() -> None:
    available = state.scoped_countries()
    feature = next((c for code in FEATURED for c in available if c["id"] == code), available[0])
    photo = PHOTOS.get(feature["id"])
    with st.container(key="atlas_feature"):
        scene = (f'style="background-image:url(\'{escape(photo["url"], quote=True)}\')"' if photo else 'class="no-photo"')
        html(f'<div class="feature-scene" {scene} role="img" aria-label="{escape(photo["caption"] if photo else "", quote=True)}"></div>'
             f'<div class="feature-copy"><div class="feature-kicker">{e("Featured destination")}</div>'
             f'<h2 class="feature-title">{e(feature["name"])}</h2>'
             f'<div class="feature-description">{e("Explore places. Build knowledge. Find your next challenge.")}</div>'
             f'<div class="feature-place">{escape(photo["caption"]) if photo else e(feature["continent"])}</div></div>')
        st.button(t("Discover country →"), key="featured_discover", type="primary", width="stretch",
                  on_click=state.learn, args=(feature["id"],))

    with st.container(key="explore_scope"):
        area, change = st.columns([4, 1], vertical_alignment="center")
        area.markdown(f'<div class="browse-scope">{escape(state.scope_label())}</div>', unsafe_allow_html=True)
        change.button(t("Change"), key="atlas_scope_change", width="stretch", on_click=state.open_settings)

    collection, invitation = st.columns([2.6, 1], gap="large")
    with collection:
        entries = _filtered(available)
        if not entries:
            st.info(t("No countries match your search."))
        else:
            pages = math.ceil(len(entries) / EXPLORE_PAGE_SIZE)
            page = st.session_state.explore_page = min(st.session_state.explore_page, pages - 1)
            batch = entries[page * EXPLORE_PAGE_SIZE:(page + 1) * EXPLORE_PAGE_SIZE]  # never render the whole list
            for row in range(0, len(batch), 3):
                for column, country in zip(st.columns(3), batch[row:row + 3]):
                    with column:
                        _country_card(country)
            with st.container(key="explore_pagination"):
                previous, status, following = st.columns([1, 2, 1], vertical_alignment="center")
                previous.button(t("Previous"), key="explore_previous", disabled=page == 0,
                                width="stretch", on_click=_turn_page, args=(-1,))
                status.caption(t("Page {page} of {pages} · {count} countries", page=page + 1, pages=pages, count=len(entries)))
                following.button(t("Next"), key="explore_next", disabled=page + 1 >= pages,
                                 width="stretch", on_click=_turn_page, args=(1,))
    with invitation:
        with st.container(key="atlas_quiz"):
            html(f'<div class="feature-kicker">{e("Your next adventure")}</div>'
                 '<div class="challenge-compass" aria-hidden="true">✧</div>'
                 f'<div class="challenge-title">{e("Your next challenge")}</div>'
                 f'<div class="challenge-note">{e("Capitals, flags, currencies, languages and more.")}</div>')
            st.button(t("Take a quiz →"), key="atlas_take_quiz", type="primary", width="stretch",
                      on_click=state.navigate, args=("Quiz",))
        html(f'<div class="atlas-small">{e("Explore at your pace.")}</div>')
    photo_credits()


# --------------------------------------------------------------------------- Learn

def _tile(label: str, value: str) -> str:
    return f'<div class="fact-tile"><div class="fact-label">{e(label)}</div><div class="fact-value">{escape(value)}</div></div>'


def learn() -> None:
    hero("The country collection", "Get to know the world.",
         "Build your knowledge, one country at a time. The details make all the difference.")
    ids = [c["id"] for c in state.scoped_countries()]
    requested = st.session_state.get("learn_country")
    if get_country(requested) and requested not in ids:
        ids = [requested] + ids  # opened from a quiz review or link outside the current area: still show it
    elif requested not in ids:
        st.session_state.learn_country = ids[0]
    c = get_country(st.selectbox(t("Choose a country"), ids, format_func=country_formatter(), key="learn_country"))
    none = t("Not included yet")
    with st.container(key="learn_card"):
        top, art = st.columns([3, 1], vertical_alignment="center")
        with top:
            html(f'<div class="country-top"><span class="country-code">{c["id"]}</span>'
                 f'<span class="country-region">{escape(c["region"])}</span>{status_chip(c)}</div>'
                 f'<h2 class="country-name">{e(c["name"])}</h2>'
                 f'<div class="official-name">{escape(c.get("official_name", ""))}</div>')
            if c["status_note"]:
                st.caption(t(c["status_note"]))
        with art:
            _flag(c, 180, t("Flag of {name}", name=c["name"]))
        capitals = "; ".join(f"{x['name']} ({t(x['role'])})" for x in c["capitals"]) or t("No capital listed")
        facts = [("Continent / region", " · ".join([" / ".join(t(x) for x in c["continents"]), c["region"]]).strip(" ·")),
                 ("Capital roles", capitals),
                 ("Currencies", ", ".join(map(currency_label, c["currencies"])) or none),
                 ("Languages with official status or wide use", ", ".join(c["languages"]) or none),
                 ("Total area", f"{c['area_km2']:,.0f} km²" if c["area_km2"] else none),
                 ("Calling codes and internet domains", " · ".join(c["calling_codes"] + c["domains"]) or none)]
        html('<div class="fact-grid">' + "".join(_tile(label, value) for label, value in facts) + "</div>")
        for note in (c.get("capital_note"), c.get("currency_note")):
            if note:
                st.caption("ⓘ " + t(note))
        near = neighbours(c)
        st.write(t("Neighbours in this collection: {names}", names=", ".join(t(n["name"]) for n in near))
                 if near else t("No land borders with other places in this collection."))
        if c["landmarks"]:
            st.write(t("Landmarks") + ": " + " · ".join(f"[{s['name']}]({s['source']})" for s in c["landmarks"]))
        leader = load_political_records().get(c["id"])
        if leader:
            st.write(t("Head of state: **{names}** ({title}).", names=" / ".join(leader["names"]), title=leader["title"]))
            st.caption(t("Political record verified {date}.", date=leader["verified_on"]))
            st.markdown(f"[{t('Political source')}]({leader['source']})")
        st.markdown(f"[{t('Country data source')}]({c['source']}) · " + t("Dataset version {date}", date=c.get("data_date", "")))
        if c.get("capital_source"):
            st.markdown(f"[{t('Capital-role source')}]({c['capital_source']})")


# --------------------------------------------------------------------------- Quiz

def _reset_country_filter() -> None:
    st.session_state.filter_country = "all"


def _setup() -> None:
    st.session_state.setdefault("filter_continent", st.session_state.scope_continent)
    st.session_state.setdefault("filter_country", st.session_state.scope_country)
    st.session_state.setdefault("filter_collection", st.session_state.scope_collection)
    with st.container(key="settings_card"):
        html(f'<div class="eyebrow">{e("Your next adventure")}</div>')
        st.subheader(t("Build your challenge"))
        collection = st.selectbox(t("Places to include"), COLLECTIONS, format_func=formatter(COLLECTIONS),
                                  key="filter_collection", on_change=_reset_country_filter)
        one, two = st.columns(2)
        continent = one.selectbox(t("Continent"), AREAS, format_func=formatter(AREAS), key="filter_continent",
                                  on_change=_reset_country_filter)
        ids = ["all"] + [c["id"] for c in get_countries(continent, collection=collection)]
        if st.session_state.filter_country not in ids:
            st.session_state.filter_country = "all"
        country_id = two.selectbox(t("Country"), ids, key="filter_country",
                                   format_func=country_formatter(t("All Countries")))
        left, right = st.columns(2)
        category = left.selectbox(t("Category"), CATEGORIES, format_func=formatter(CATEGORIES), key="filter_category")
        count = left.selectbox(t("Questions"), QUESTION_COUNTS, index=1, key="filter_count")
        difficulty = right.selectbox(t("Difficulty"), DIFFICULTIES, format_func=formatter(DIFFICULTIES), index=1,
                                     key="filter_difficulty")
        timer = right.toggle(t("Timed challenge"), value=False, key="filter_timer",
                             help=t("15 seconds per question on Expert; 20 seconds on other levels."))
        flags = True
        if category == "Mixed":
            flags = right.toggle(t("Include flag questions"), value=True, key="filter_flags",
                                 help=t("Flag questions show an image. Turn them off if you use a screen reader."))
        settings = {"continent": continent, "country_id": country_id, "category": category, "difficulty": difficulty,
                    "count": count, "timer": timer, "collection": collection, "flags": flags}
        round_size, _ = state.preview(settings)
        st.caption(t("Up to {n} questions · no repeated facts in the same round.", n=count))
        if category == "Heads of State":
            st.caption(t("Only recently verified political records are included. Coverage is currently limited."))
        if category == "Flags":
            st.caption(t("Flag questions show an image. Turn them off if you use a screen reader."))
        if country_id != "all":
            st.caption(t("Single-country rounds focus on that country's facts; questions answered by its own name are left out."))
        if not round_size:
            st.info(t("No verified questions match these filters. Choose Mixed, another country, or a lower difficulty."))
        elif round_size < count:
            st.info(t("This round will contain {n} questions, without repeating the same question.", n=round_size))
        if st.button(t("Start quiz"), key="start_quiz", type="primary", width="stretch", disabled=not round_size):
            state.start_round(settings)
            st.rerun()
        if st.session_state.quiz and not st.session_state.quiz["finished"]:
            st.button(t("Return to current round"), width="stretch", on_click=state.close_setup)
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
        if q.get("flag"):
            with st.container(key="quiz_flag"):
                _flag(get_country(q["flag"]), 260, t("Flag to identify. No text description is available for flag images."))
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
                    st.button(label, key=f"answer_{serial}_{index}_{pos}", width="stretch",
                              disabled=quiz["resolved"] or choice in quiz["hidden_options"],
                              on_click=state.answer, args=(choice, serial, index))
        if not quiz["resolved"] and len(q["choices"]) == 4:
            st.button(t("Use hint · −25 if correct"), key=f"hint_{serial}_{index}",
                      disabled=quiz["hint_used"] or quiz["hints_remaining"] == 0,
                      on_click=state.hint, args=(serial, index))
        if quiz["resolved"]:
            record, explanation = quiz["history"][-1], parts(q["explanation"])
            if record["correct"]:
                st.success(f"{t('Correct!')} {explanation}", icon="✅")
            elif record["timed_out"]:
                st.warning(f"{t('Time is up.')} {t('Correct answer')}: {t(q['answer'])}. {explanation}", icon="⏱️")
            else:
                st.error(f"{t('Not quite.')} {t('Correct answer')}: {t(q['answer'])}. {explanation}", icon="❌")
            sound.play_event(quiz["event"])
            p = quiz["last_points"]
            st.caption(t("+{points} points · Base {base} · Speed +{speed} · Streak +{streak} · Hint −{hint}",
                         points=p["total"], base=p["base"], speed=p["speed"], streak=p["streak"], hint=p["hint"]))
            st.markdown(f"[{t('Source')}]({q['source']})")
            final = index + 1 == total
            with st.container(key="quiz_next_action"):
                if st.button(t("View results" if final else "Next question →"), type="primary",
                             width="stretch", key=f"next_{serial}_{index}"):
                    state.next_question(serial, index)
                    st.rerun()  # full rerun: results and the timer schedule live outside this fragment


def _review_entry(i: int, record: dict) -> None:
    q = record["question"]
    mark = "Correct" if record["correct"] else "Timed out" if record["timed_out"] else "Incorrect"
    symbol = "✓" if record["correct"] else "⏱" if record["timed_out"] else "✕"
    with st.expander(f"{symbol} {i}. {t(mark)} · {parts(q['prompt'])}", expanded=not record["correct"]):
        if q.get("flag"):
            _flag(get_country(q["flag"]), 140, t("Flag of {name}", name=get_country(q["flag"])["name"]))
        st.write(f"{t('Your answer')}: **{t(record['answer']) if record['answer'] else t('Unanswered')}**")
        st.write(f"{t('Correct answer')}: **{t(q['answer'])}**")
        st.write(parts(q["explanation"]))
        country = get_country(q["country_id"])
        st.caption(f"{t(country['name'])} · {t(country['continent'])} · {country['region']} · "
                   + t("{seconds} seconds · {points} points · {hint}", seconds=f"{record['elapsed']:.1f}",
                       points=record["points"]["total"], hint="Hint used" if record["hint"] else "No hint"))
        links = [f"[{t('Source')}]({q['source']})"]
        if q.get("extra_source") and q["extra_source"] != q["source"]:
            links.append(f"[{t('Capital-role source')}]({q['extra_source']})")
        st.markdown(" · ".join(links))
        st.button(t("Learn about {name}", name=country["name"]), key=f"review_learn_{i}", on_click=state.learn,
                  args=(country["id"],))


def _results(quiz) -> None:
    stats, settings = engine.statistics(quiz), quiz["settings"]
    sound.play_event(quiz["event"])
    with st.container(key="result_card"):
        html(f'<div class="eyebrow">{e("Challenge complete")}</div>')
        st.subheader("🏁 " + t("Your results"))
        html(f'<div class="result-number">{stats["score"]:,}<span class="result-unit"> {e("points")}</span></div>')
        first, second, third = st.columns(3)
        first.metric(t("Accuracy"), f"{stats['accuracy']:.0f}%")
        second.metric(t("Correct answers"), f"{stats['correct']} / {stats['total']}")
        third.metric(t("Best streak"), stats["best_streak"])
        st.caption(t("Incorrect / unanswered: {wrong} · Timed out: {timeout} · Average response time: {seconds} seconds",
                     wrong=stats["incorrect"], timeout=stats["timed_out"], seconds=f"{stats['average_time']:.1f}"))
        country = get_country(settings["country_id"])
        st.caption(" · ".join([t(settings["continent"]), country_label(country["id"]) if country else t("All Countries"),
                               t(settings["category"]), t(settings["difficulty"]), t("{n} questions", n=stats["total"])]))
        if quiz["perfect_bonus"]:
            st.success(t("Perfect round without hints: +{points} bonus points.", points=quiz["perfect_bonus"]), icon="🌟")
        one, two = st.columns(2)
        if one.button(t("Play again"), type="primary", width="stretch"):
            state.start_round(settings)
            st.rerun()
        two.button(t("Change settings"), width="stretch", on_click=state.open_setup)
    missed = engine.missed(quiz)
    with st.container(key="review_card"):
        st.subheader(t("Review missed answers") if missed else t("Answer review"))
        if not missed:
            st.success(t("No missed answers in this round — well done."), icon="🌟")
        labels = {"missed": t("Missed only"), "all": t("All answers")}
        mode = st.segmented_control(t("Show"), ["missed", "all"], key="review_mode", required=True,
                                    format_func=labels.get) or "missed"
        records = quiz["history"] if mode == "all" else [h for h in quiz["history"] if not h["correct"]]
        for i, record in enumerate(quiz["history"], 1):
            if record in records:
                _review_entry(i, record)


def quiz() -> None:
    current = st.session_state.quiz
    if not current or st.session_state.show_setup:
        intro, setup = st.columns([1, 1.15], gap="large")
        with intro:
            hero("The world geography challenge", "How well do you know your world?",
                 "Go beyond the familiar. Challenge yourself on capitals, flags, currencies, languages and the places in between.",
                 variant="tall")
        with setup:
            _setup()
        return
    hero("World Quiz", "Every answer takes you further.", "Think carefully. Build a streak. Discover something new.",
         variant="compact")
    with st.container(key="round_bar"):
        summary, action = st.columns([3, 1], vertical_alignment="center")
        s = current["settings"]
        country = get_country(s["country_id"])
        label = country_label(country["id"]) if country else t(s["continent"])
        summary.markdown(f'<div class="round-label">{e("Current challenge")}</div>'
                         f'<div class="round-summary">{escape(label)} · {e(s["difficulty"])} · {e(s["category"])}</div>',
                         unsafe_allow_html=True)
        action.button(t("Change"), width="stretch", on_click=state.open_setup)
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
            html(f'<div class="award-medal {"" if earned else "locked"}" aria-hidden="true">{symbol}</div>')
            st.subheader(t(name))
            html(f'<span class="award-state {"earned" if earned else ""}">{e("Earned" if earned else "In progress")}</span>')
            st.caption(t(description))


ROUTES = {"Explore": explore, "Learn": learn, "Quiz": quiz, "Badges": badges}
