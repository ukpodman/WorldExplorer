"""The four pages: Explore, Learn, Quiz and Badges."""
from __future__ import annotations

import base64
import math
from datetime import date
from html import escape

import streamlit as st

from core import accounts, records
from core import daily as daily_engine
from core import learn as learn_engine
from core import badges as badge_engine
from core import quiz as engine
from core.data import (AREAS, COLLECTIONS, COUNTRIES, DEFAULT_COLLECTION, PHOTOS, STATUS_LABELS, STATUSES, flag_image, get_countries,
                       get_country, load_political_records)
from core.quiz import CATEGORIES, DIFFICULTIES, QUESTION_COUNTS, currency_label

from . import sound, state
from .components import e, hero, html, photo_credits, status_chip
from .state import country_formatter, country_label, formatter, parts, t

CONTINENTS_LIST = list(AREAS[1:])
EXPLORE_PAGE_SIZE = 7  # desktop: 3 + challenge card in row 1, 4 in row 2
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


# --------------------------------------------------------------------------- Daily challenge & mistakes

def _daily_status() -> dict:
    day = state.today()
    done = daily_engine.completed(st.session_state.daily, day)
    secs = daily_engine.seconds_until_next()
    return {"day": day, "done": done, "in_progress": state.daily_round_in_progress() is not None,
            "streak": daily_engine.current_streak(st.session_state.daily, day), "best": st.session_state.daily["best"],
            "next": t("New challenge in {hours} h {minutes} min (00:00 UTC).", hours=secs // 3600, minutes=secs % 3600 // 60)}


def _daily_button_label(d: dict) -> str:
    if d["in_progress"]:
        return t("Continue today's challenge")
    if d["done"]:
        return t("Play today's challenge again")
    return t("Today's challenge · {n} questions", n=daily_engine.DAILY_COUNT)


def _daily_short_label(d: dict) -> str:
    if d["in_progress"]:
        return t("Continue today's challenge")
    return t("Replay today's challenge") if d["done"] else t("Today's challenge")


def _streak_text(d: dict) -> str:
    if d["done"]:
        return t("Today: {correct}/{total} · 🔥 Day streak: {n}", correct=d["done"]["correct"], total=d["done"]["total"], n=d["streak"])
    if d["streak"]:
        return t("🔥 Day streak: {n} · play today to keep it", n=d["streak"])
    return t("Five questions a day, the same for everyone.")


def _practise_button(key: str) -> None:
    n = len(st.session_state.mistakes)
    if n:
        st.button(t("Practise mistakes ({n})", n=n), key=key, on_click=state.start_practice, width="stretch",
                  help=t("A round built from questions you missed. Correct answers clear them from the list."))


def _challenge() -> None:
    d = _daily_status()
    with st.container(key="atlas_quiz"):
        html(f'<div class="feature-kicker">{e("Your next adventure")}</div>'
             f'<div class="challenge-title">{e("Your next challenge")}</div>'
             f'<div class="challenge-note daily-note">{escape(_streak_text(d))}</div>')
        with st.container(key="challenge_actions", horizontal=True):
            st.button(_daily_short_label(d), key="explore_daily", type="primary", on_click=state.start_daily,
                      help=t("Five questions a day, the same for everyone."))
            st.button(t("Take a quiz →"), key="atlas_take_quiz", on_click=state.navigate, args=("Quiz",))


def _exploration_area() -> None:
    """Area summary with an "Exploration area" button that opens a compact inline section (closed by default).
    It edits the same shared preferences as Settings and applies changes immediately."""
    is_open = st.session_state.get("explore_area_open", False)
    with st.container(key="explore_scope", horizontal=True, vertical_alignment="center"):
        html(f'<div class="browse-scope">{escape(state.scope_label())}</div>')
        st.button(t("Exploration area"), key="explore_area_toggle", icon=":material/expand_less:" if is_open else ":material/expand_more:",
                  on_click=state.toggle_exploration_area,
                  help=t("Hide the exploration area options") if is_open else t("Choose which countries Explore, Learn and the quiz use"))
    if not is_open:
        return
    ss = st.session_state

    def initial(key, options, current):
        """Default index only for a widget's first render; afterwards its own state (kept valid by the callback) wins."""
        return {} if key in ss else {"index": options.index(current) if current in options else 0}

    with st.container(key="explore_area_panel"):
        modes = list(accounts.SCOPE_MODES)
        collection = st.selectbox(t("Places to include"), COLLECTIONS, format_func=formatter(COLLECTIONS), key="explore_area_collection",
                                  on_change=state.apply_exploration_area, **initial("explore_area_collection", COLLECTIONS, ss.scope_collection))
        with st.container(key="explore_area_row", horizontal=True):
            mode = st.selectbox(t("Exploration area"), modes, format_func=formatter(modes), key="explore_area_mode",
                                on_change=state.apply_exploration_area, **initial("explore_area_mode", modes, ss.scope_mode))
            if mode == "One continent":
                st.selectbox(t("Continent"), CONTINENTS_LIST, format_func=formatter(CONTINENTS_LIST), key="explore_area_continent",
                             on_change=state.apply_exploration_area, **initial("explore_area_continent", CONTINENTS_LIST, ss.scope_continent))
            elif mode == "One country":
                ids = [c["id"] for c in get_countries(collection=collection)]
                st.selectbox(t("Country"), ids, format_func=country_formatter(), key="explore_area_country",
                             on_change=state.apply_exploration_area, **initial("explore_area_country", ids, ss.scope_country))
        st.caption(t("Changes apply right away to Explore, Learn and the next quiz setup. Your current round is kept."))


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

    _exploration_area()

    entries = _filtered(available)  # filters span the full width, above the cards and the challenge card
    with st.container(key="explore_grid"):
        if not entries:
            message, side = st.columns([3, 1])
            message.info(t("No countries match your search."))
            with side:
                _challenge()
        else:
            pages = math.ceil(len(entries) / EXPLORE_PAGE_SIZE)
            page = st.session_state.explore_page = min(st.session_state.explore_page, pages - 1)
            batch = entries[page * EXPLORE_PAGE_SIZE:(page + 1) * EXPLORE_PAGE_SIZE]  # never render the whole list
            # Desktop: two rows of four equal columns. Row 1 = three countries + the challenge card,
            # row 2 = countries four to seven, so the seventh sits directly under the challenge card.
            # On phones CSS moves the challenge card after the list; nothing is rendered twice.
            first = st.columns(4)
            for column, country in zip(first[:3], batch[:3]):
                with column:
                    _country_card(country)
            with first[3]:
                _challenge()
            if len(batch) > 3:
                for column, country in zip(st.columns(4), batch[3:]):
                    with column:
                        _country_card(country)
            with st.container(key="explore_pagination"):
                previous, status, following = st.columns([1, 2, 1], vertical_alignment="center")
                previous.button(t("Previous"), key="explore_previous", disabled=page == 0,
                                width="stretch", on_click=_turn_page, args=(-1,))
                status.caption(t("Page {page} of {pages} · {count} countries", page=page + 1, pages=pages, count=len(entries)))
                following.button(t("Next"), key="explore_next", disabled=page + 1 >= pages,
                                 width="stretch", on_click=_turn_page, args=(1,))
    photo_credits()


# --------------------------------------------------------------------------- Learn

def _tile(label: str, value: str) -> str:
    return f'<div class="fact-tile"><div class="fact-label">{e(label)}</div><div class="fact-value">{escape(value)}</div></div>'


def _learn_media(c: dict) -> None:
    """A licensed destination photo when one is bundled; otherwise the flag on a calm continent-tinted panel."""
    photo = PHOTOS.get(c["id"])
    if photo:
        html(f'<div class="learn-photo" role="img" aria-label="{escape(photo["caption"], quote=True)}" '
             f'style="background-image:url(\'{escape(photo["url"], quote=True)}\')"></div>')
        st.caption(f"{photo['caption']} — {photo['author']} · [{photo['license']}]({photo['license_url']})")
        with st.container(key="learn_flag_small"):
            _flag(c, 96, t("Flag of {name}", name=c["name"]))
    else:
        with st.container(key=f"learn_flag_panel_{c['continent'].replace(' ', '_')}"):
            _flag(c, 200, t("Flag of {name}", name=c["name"]))


def _learn_nav(current: str, where: str) -> None:
    """Previous / Next. The top row is desktop-only (hidden by CSS on phones and tablets); the bottom row is everywhere.
    They only change the Learn selection, never a quiz round."""
    movable = state.learn_step_target(1) is not None
    with st.container(key=f"learn_nav_{where}", horizontal=True):
        st.button(t("← Previous"), key=f"learn_prev_{where}", disabled=not movable, on_click=state.learn_step, args=(-1,))
        st.button(t("Next →"), key=f"learn_next_{where}", disabled=not movable, on_click=state.learn_step, args=(1,))


def _learn_position(current: str) -> None:
    scope = state.learn_ids()
    if current in scope and len(scope) == 1:
        st.caption(t("Only one country is in your exploration area ({scope}).", scope=state.scope_label()))
    elif current in scope:
        st.caption(t("{n} of {total} · {scope}", n=scope.index(current) + 1, total=len(scope), scope=state.scope_label()))
    else:
        st.caption(t("Outside your exploration area ({scope}). Next and Previous return to it.", scope=state.scope_label()))


def _neighbour_buttons(c: dict) -> None:
    """Collapsed "Neighbours" section on phones and tablets; shown open (summary hidden) on desktop by CSS."""
    allowed = {x["id"] for x in get_countries(collection=st.session_state.scope_collection)}
    shown, hidden = learn_engine.split_neighbours(c, allowed)
    html(f'<div class="learn-section desk-only">{e("Neighbours")}</div>')
    label = t("Neighbours") + (f" ({len(shown)})" if shown else "")
    with st.expander(label, key="learn_neighbours_box"):
        if not c["borders"]:
            st.caption(t("{name} has no land borders with other places in this dataset.", name=c["name"]))
        if shown:
            # Each button carries its bundled flag as a small background image, so the whole chip is one tap target.
            rules = "".join(f'.stApp .st-key-nb_{n["id"]} button{{background-image:url("data:image/webp;base64,'
                            f'{base64.b64encode(flag_image(n)).decode()}") !important}}' for n in shown if flag_image(n))
            html(f"<style>{rules}</style>")
            with st.container(key="learn_neighbours", horizontal=True):
                for n in shown:
                    st.button(t(n["name"]), key=f"nb_{n['id']}", on_click=state.learn, args=(n["id"],),
                              help=t("Learn about {name}", name=n["name"]))
        if hidden:
            st.caption(t("Not shown with your current places setting: {names}. To include territories, choose them in ☰ Settings → Places to include.",
                         names=", ".join(t(n["name"]) for n in hidden)))


def _size_comparison(c: dict) -> None:
    with st.expander(t("Compare country size"), key="compare_size"):
        options = [x["id"] for x in COUNTRIES if x["area_km2"]]
        if "size_reference_select" not in st.session_state:  # restore the remembered choice (session or profile)
            saved = st.session_state.get("size_reference")
            st.session_state.size_reference_select = saved if saved in options else None
        ref_id = st.selectbox(t("Compare with"), options, format_func=country_formatter(), key="size_reference_select",
                              placeholder=t("Choose a country"), on_change=state.remember_size_reference)
        if not ref_id:
            st.caption(t("Choose a country to compare total areas."))
            return
        result = learn_engine.compare_areas(c, get_country(ref_id))
        if result["kind"] == "same":
            st.caption(t("Choose a different country to compare."))
        elif result["kind"] == "missing":
            for m in result["missing"]:
                st.caption(t("Total area is not recorded for {name} in this dataset.", name=m["name"]))
        else:
            big, small = result["larger"], result["smaller"]
            rows = ""
            for x in (c, get_country(ref_id)):
                width = result["bars"][x["id"]]
                rows += (f'<div class="size-row"><div class="size-label"><b>{e(x["name"])}</b>'
                         f'<span>{x["area_km2"]:,.0f} km²</span></div>'
                         f'<div class="size-track"><div class="size-bar{" tiny" if width < learn_engine.MIN_VISIBLE else ""}" '
                         f'style="width:{max(width, 0.0):.2f}%"></div></div></div>')
            if result["similar"]:
                sentence = t("{name} and {other} are about the same size.", name=big["name"], other=small["name"])
            else:
                sentence = t("{name} is about {ratio} times the size of {other}.", name=big["name"],
                             ratio=learn_engine.ratio_text(result["ratio"]), other=small["name"])
            share = t("less than 1") if result["share"] < 1 else f"{result['share']:.0f}"
            detail = t("{other} covers about {share}% of the total area of {name}.", other=small["name"], share=share, name=big["name"])
            html(f'<div class="size-compare" role="img" aria-label="{escape(sentence, quote=True)}">'
                 f'<div class="size-title">{e("Total area")}</div>{rows}</div>'
                 f'<p class="size-sentence"><b>{escape(sentence)}</b> {escape(detail)}</p>')
            if result["tiny"]:
                st.caption(t("At this scale the bar for {name} is too small to show, so it appears as a thin marker.", name=small["name"]))
        st.markdown(f"{t('Total area')}: [{t('Country data source')}]({c['source']}) · "
                    + t("Dataset version {date}", date=c.get("data_date", "")))


def _open_sections_on_desktop(country_id: str) -> None:
    """On wide screens (> 1024 px) open the Neighbours and Landmarks sections once, as if clicked, so the
    desktop page keeps showing them; CSS then hides their summaries. Phones and tablets keep them collapsed.
    Without JavaScript the sections simply stay collapsible everywhere."""
    st.html(f"""<script data-country="{escape(country_id, quote=True)}">
      (function () {{
        if (window.innerWidth <= 1024) return;
        var tries = 0;
        (function open() {{
          var done = 0;
          ['learn_neighbours_box', 'learn_landmarks_box'].forEach(function (key) {{
            var d = document.querySelector('.st-key-' + key + ' details');
            if (!d) return;
            if (!d.open && !d.dataset.weAuto) {{ d.dataset.weAuto = '1'; d.querySelector('summary').click(); }}
            done++;
          }});
          if (done < 1 && tries++ < 20) setTimeout(open, 100);
        }})();
      }})();
    </script>""", unsafe_allow_javascript=True)


def _source_lines(c: dict, leader: dict | None) -> None:
    """Head of state and source links (shown once: on desktop below the facts, on phones/tablets in More details)."""
    if leader:
        st.write(t("Head of state: **{names}** ({title}).", names=" / ".join(leader["names"]), title=leader["title"]))
        st.caption(t("Political record verified {date}.", date=leader["verified_on"]))
        st.markdown(f"[{t('Political source')}]({leader['source']})")
    st.markdown(f"[{t('Country data source')}]({c['source']}) · " + t("Dataset version {date}", date=c.get("data_date", "")))
    if c.get("capital_source"):
        st.markdown(f"[{t('Capital-role source')}]({c['capital_source']})")


def learn() -> None:
    hero("The country collection", "Get to know the world.",
         "Build your knowledge, one country at a time. The details make all the difference.", variant="compact")
    ids = state.learn_ids()
    requested = st.session_state.get("learn_country")
    if get_country(requested) and requested not in ids:
        ids = [requested] + ids  # opened from a neighbour, quiz review or link outside the current area: still show it
    elif requested not in ids:
        st.session_state.learn_country = ids[0]
    with st.container(key="learn_picker"):
        pick, surprise = st.columns([5, 1], vertical_alignment="bottom")
        chosen = pick.selectbox(t("Choose a country"), ids, format_func=country_formatter(), key="learn_country")
        others = [i for i in state.learn_ids() if i != chosen]
        surprise.button(t("Surprise me"), key="learn_surprise", disabled=not others, on_click=state.learn_surprise,
                        width="stretch")
    c = get_country(chosen)
    _learn_position(c["id"])
    _learn_nav(c["id"], "top")
    none = t("Not included yet")
    leader = load_political_records().get(c["id"])
    flag = flag_image(c)
    small_flag = (f'<img class="name-flag" src="data:image/webp;base64,{base64.b64encode(flag).decode()}" alt="" aria-hidden="true">'
                  if flag else "")
    region = " · ".join([" / ".join(t(x) for x in c["continents"]), c["region"]]).strip(" ·")
    with st.container(key="learn_card"):
        top, art = st.columns([3, 2], vertical_alignment="center", gap="large")
        with top:
            # Desktop keeps code, region and official name here; phones and tablets show a small flag beside the
            # name and one region line, with the code and official name in "More details".
            html(f'<div class="country-top desk-only"><span class="country-code">{c["id"]}</span>'
                 f'<span class="country-region">{escape(c["region"])}</span>{status_chip(c)}</div>'
                 f'<div class="name-row">{small_flag}<h2 class="country-name">{e(c["name"])}</h2></div>'
                 f'<div class="official-name desk-only">{escape(c.get("official_name", ""))}</div>'
                 f'<div class="region-line mobile-only">{escape(region)}{status_chip(c)}</div>')
            if c["status_note"]:
                st.caption(t(c["status_note"]))
            with st.container(key="learn_quiz_action"):
                st.button(t("Quiz me on this country"), key="learn_quiz_me", type="primary",
                          on_click=state.quiz_on_country, args=(c["id"],),
                          help=t("Opens the quiz setup with this country selected."))
        with art:
            _learn_media(c)
        capitals = "; ".join(f"{x['name']} ({t(x['role'])})" for x in c["capitals"]) or t("No capital listed")
        codes = " · ".join(c["calling_codes"] + c["domains"]) or none
        facts = [("Continent / region", region, True),
                 ("Capital roles", capitals, False),
                 ("Currencies", ", ".join(map(currency_label, c["currencies"])) or none, False),
                 ("Languages with official status or wide use", ", ".join(c["languages"]) or none, False),
                 ("Total area", f"{c['area_km2']:,.0f} km²" if c["area_km2"] else none, False),
                 ("Calling codes and internet domains", codes, True)]
        html('<div class="fact-grid">' + "".join(_tile(label, value).replace('class="fact-tile"', 'class="fact-tile desk-only"', 1)
                                               if extra else _tile(label, value) for label, value, extra in facts) + "</div>")
        for note in (c.get("capital_note"), c.get("currency_note")):
            if note:
                st.caption("ⓘ " + t(note))
        _neighbour_buttons(c)
        if c["landmarks"]:
            html(f'<div class="learn-section desk-only">{e("Landmarks")}</div>')
            with st.expander(t("Landmarks") + f" ({len(c['landmarks'])})", key="learn_landmarks_box"):
                st.markdown(" · ".join(f"[{s['name']}]({s['source']})" for s in c["landmarks"]))
        _size_comparison(c)
        _open_sections_on_desktop(c["id"])
        with st.container(key="learn_meta_desktop"):
            _source_lines(c, leader)
        with st.expander(t("More details"), key="learn_more"):
            details = [("Official name", c.get("official_name") or none), ("Country code", c["id"]),
                       ("Calling codes and internet domains", codes)]
            html('<div class="more-details">' + "".join(f'<div><span>{e(k)}</span><b>{escape(v)}</b></div>' for k, v in details) + "</div>")
            _source_lines(c, leader)
    _learn_nav(c["id"], "bottom")


# --------------------------------------------------------------------------- Quiz

def _reset_country_filter() -> None:
    st.session_state.filter_country = "all"


def _where_summary(collection: str, continent: str, country_id: str) -> str:
    place = country_label(country_id) if country_id != "all" else t(continent)
    return " · ".join([place, t(collection)])


def _daily_box(box_key: str, button_key: str) -> None:
    """Compact Daily Challenge entry: title, status line and one Start / Continue / Replay button."""
    d = _daily_status()
    with st.container(key=box_key, horizontal=True, vertical_alignment="center"):
        title = e("Today's challenge")  # kept outside the f-string (Python < 3.12 forbids backslashes there)
        generic = "" if d["done"] or d["streak"] else " generic"  # the plain description is hidden on phones
        later = f'<span class="daily-next">{escape(d["next"])}</span>' if d["done"] else ""  # hidden on phones too
        html(f'<div class="daily-head"><span class="daily-icon" aria-hidden="true">📅</span><div><b>{title}</b>'
             f'<span class="daily-status{generic}">{escape(_streak_text(d))}</span>{later}</div></div>')
        st.button(t("Continue") if d["in_progress"] else t("Replay") if d["done"] else t("Start"), key=button_key,
                  type="primary" if not d["done"] else "secondary", on_click=state.start_daily,
                  help=_daily_button_label(d))


def _setup() -> None:
    state.restore_quiz_filters()
    with st.container(key="settings_card"):
        _daily_box("daily_box", "setup_daily")  # phones; tablets and desktops show it beside the setup (see quiz())
        for group, kept in state.parked_rounds().items():
            st.button(_return_label(group, kept) + f" ({kept['index'] + 1}/{len(kept['questions'])})", key=f"resume_{group}", width="stretch",
                      on_click=state.resume_round, args=(group,))
        html(f'<div class="eyebrow">{e("Your next adventure")}</div>')
        st.subheader(t("Build your challenge"))
        active = st.session_state.quiz
        if active and not active["finished"]:
            if active.get("mode", "regular") == "regular":
                st.info(t("You have a round in progress. Starting a new quiz replaces it; use “Return to current round” to continue it."))
            else:
                st.info(t("Your current round is kept if you start a new quiz; you can return to it from here."))

        with st.container(key="what_box"):
            html(f'<div class="setup-section">{e("What to practise")}</div>')
            category = st.selectbox(t("Category"), CATEGORIES, format_func=formatter(CATEGORIES), key="filter_category")
            left, right = st.columns(2)
            difficulty = left.selectbox(t("Difficulty"), DIFFICULTIES, format_func=formatter(DIFFICULTIES), key="filter_difficulty")
            count = right.selectbox(t("Questions"), QUESTION_COUNTS, key="filter_count")
            with st.container(key="setup_toggles", horizontal=True, gap="large"):
                timer = st.toggle(t("Timed challenge"), key="filter_timer",
                                  help=t("15 seconds per question on Expert; 20 seconds on other levels."))
                flags = True
                if category == "Mixed":
                    flags = st.toggle(t("Flag questions"), key="filter_flags",
                                      help=t("Flag questions show an image. Turn them off if you use a screen reader."))

        with st.container(key="where_box"):
            collection = st.session_state.filter_collection
            summary_slot = st.empty()
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
            summary_slot.markdown(f'<div class="setup-section">{e("Where")}'
                                  f'<span class="where-summary">{escape(_where_summary(collection, continent, country_id))}</span></div>',
                                  unsafe_allow_html=True)
        state.remember_quiz_filters()

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
        with st.container(key="start_box"):
            if st.button(t("Start quiz"), key="start_quiz", type="primary", width="stretch", disabled=not round_size):
                state.start_round(settings)
                st.rerun()
            if st.session_state.quiz and not st.session_state.quiz["finished"]:
                st.button(t("Return to current round"), width="stretch", on_click=state.close_setup)
        with st.expander(t("Scoring and hints")):
            st.write(t("Correct answers earn 100 base points, multiplied by difficulty: Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2."))
            st.write(t("Answer streak: the 1st and 2nd correct answers in a row earn the base points, the 3rd and 4th earn double, "
                       "and from the 5th on they earn triple. A wrong answer or a timeout resets the streak, and every round starts at 0."))
            st.write(t("Fast answers add 25 points. A hint removes one wrong option and deducts 25 from that answer; a hinted "
                       "answer still counts for the streak. Only the base points are multiplied. Each round has three hints."))
            st.write(t("A perfect round without hints adds 250 points × difficulty (never multiplied by the streak). Wrong and "
                       "timed-out answers earn zero."))
            st.write(t("Medals depend on accuracy only: gold from 90%, silver from 70%, bronze from 50%."))


# Restrained accent per question category (text contrast >= 4.5:1 on white), always shown with an icon and words.
CATEGORY_STYLES = {"Capitals": ("capitals", "🏛"), "Flags": ("flags", "⚑"), "Currency": ("currency", "¤"),
                   "Languages": ("languages", "💬"), "Landmarks": ("landmarks", "⛰"),
                   "Country Identification": ("identification", "🔎"), "Geography / General Facts": ("geography", "🧭"),
                   "Continents": ("continents", "🌍"), "True or False": ("truefalse", "⚖"), "Heads of State": ("leaders", "👤")}


def _fresh(event_id: str) -> bool:
    """True the first time an event is drawn, so animations play once and never on later reruns."""
    shown = st.session_state.setdefault("effects_shown", [])
    if event_id in shown:
        return False
    shown.append(event_id)
    del shown[:-50]
    return True


def _score_strip(quiz) -> None:
    streak = quiz["streak"]
    multiplier = engine.streak_multiplier(streak) if streak else 1
    chip = f'<span class="mult-chip">×{multiplier}</span>' if multiplier > 1 else ""
    items = (("Round score", f"{quiz['score']:,}"), ("Streak", f"{streak}{chip}"), ("Hints remaining", quiz["hints_remaining"]))
    html('<div class="score-strip">' + "".join(
        f'<div class="score-item"><div class="score-label">{e(label)}</div><div class="score-value">{value}</div></div>'
        for label, value in items) + "</div>")


def _feedback(quiz, q, record, fresh: bool) -> None:
    """Outcome, points with the streak multiplier, the explanation and one sourced fact."""
    p, final = record["points"], quiz["index"] + 1 == len(quiz["questions"])
    previous = quiz["history"][-2]["streak"] if len(quiz["history"]) > 1 else 0
    if record["correct"]:
        tone, icon, head = "correct", "✓", e("Correct!")
    elif record["timed_out"]:
        tone, icon, head = "timeout", "⏱", e("Time is up.") + " " + e("Correct answer") + f": <b>{escape(t(q['answer']))}</b>"
    else:
        tone, icon, head = "wrong", "✕", e("Not quite.") + " " + e("Correct answer") + f": <b>{escape(t(q['answer']))}</b>"
    badge = f'<span class="points-chip">+{p["total"]:,}</span>' if record["correct"] else ""
    if record["correct"] and p["multiplier"] > 1:
        badge += f'<span class="mult-chip">{e("Streak ×{m}", m=p["multiplier"])}</span>'
    notes = []
    if record["correct"]:
        line = [e("Base {base} × {multiplier} = {boosted}", base=p["base"], multiplier=p["multiplier"], boosted=p["base"] * p["multiplier"])]
        if p["speed"]:
            line.append(e("Speed +{speed}", speed=p["speed"]))
        if p["hint"]:
            line.append(e("Hint −{hint}", hint=p["hint"]))
        notes.append(" · ".join(line))
        if not final:
            notes.append(e("Next correct answer: ×{m}", m=engine.streak_multiplier(record["streak"] + 1)))
    elif previous:
        notes.append(e("Streak reset (was {n}). The next correct answer starts again at ×1.", n=previous))
    fact = record.get("fact")
    fact_html = ""
    if fact:
        link = f' <a href="{escape(fact["source"], quote=True)}" target="_blank" rel="noopener">{e("Source")}</a>' if fact.get("source") else ""
        fact_html = f'<p class="fact-line"><b>{e("Did you know?")}</b> {escape(parts(fact["parts"]))}{link}</p>'
    source = f'<a href="{escape(q["source"], quote=True)}" target="_blank" rel="noopener">{e("Source")}</a>'
    html(f'<div class="feedback feedback-{tone}{" fx" if fresh else ""}" role="status">'
         f'<div class="feedback-head"><span class="feedback-icon" aria-hidden="true">{icon}</span><span>{head}</span>'
         + (f'<span class="feedback-chips">{badge}</span>' if badge else "") + '</div>'
         f'<p class="feedback-explain">{escape(parts(q["explanation"]))} {source}</p>{fact_html}'
         + "".join(f'<p class="feedback-note">{n}</p>' for n in notes) + "</div>")


def _active_round() -> None:
    quiz = st.session_state.quiz
    if not quiz or quiz["finished"] or st.session_state.show_setup or st.session_state.page != "Quiz":
        return
    state.expire_if_due()
    q, index, serial = engine.current_question(quiz), quiz["index"], quiz["serial"]
    total, limit = len(quiz["questions"]), engine.time_limit(quiz)
    slug, icon = CATEGORY_STYLES.get(q["kind"], ("geography", "🧭"))
    fresh = quiz["resolved"] and _fresh(quiz["event"]["id"])
    with st.container(key=f"quizcat_{slug}"):
        _score_strip(quiz)
        st.caption(t("Question {n} of {total} · {difficulty}", n=index + 1, total=total, difficulty=quiz["settings"]["difficulty"]))
        st.progress((index + quiz["resolved"]) / total)
        with st.container(key="question_card"):
            html(f'<div class="cat-chip"><span aria-hidden="true">{icon}</span> {e(q["kind"])}</div>')
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
                    _flag(get_country(q["flag"]), 360, t("Flag to identify. No text description is available for flag images."))
            # Short answers sit two per row on phones too, so the question and all choices fit on one screen.
            compact = all(len(t(c)) <= 22 for c in q["choices"])
            with st.container(key="answers_grid" if compact else "answers_list"):
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
                        if fresh and style != "neutral_answer":
                            style += "_fx"  # one-off emphasis; the key changes back on the next rerun
                        with column, st.container(key=f"{style}_{pos}"):
                            st.button(label, key=f"answer_{serial}_{index}_{pos}", width="stretch",
                                      disabled=quiz["resolved"] or choice in quiz["hidden_options"],
                                      on_click=state.answer, args=(choice, serial, index))
            if not quiz["resolved"] and len(q["choices"]) == 4:
                st.button(t("Use hint · −25 if correct"), key=f"hint_{serial}_{index}",
                          disabled=quiz["hint_used"] or quiz["hints_remaining"] == 0,
                          on_click=state.hint, args=(serial, index))
            if quiz["resolved"]:
                _feedback(quiz, q, quiz["history"][-1], fresh)
                sound.play_event(quiz["event"])
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


MEDAL_LABELS = {"gold": "Gold medal", "silver": "Silver medal", "bronze": "Bronze medal"}


def _practise_for(badge_id: str) -> None:
    """Open quiz setup aimed at the nearest badge (a continent or flags)."""
    if badge_id.startswith("continent_"):
        continent = next(c for c in AREAS if "continent_" + c.lower().replace(" ", "_") == badge_id)
        st.session_state.update(filter_continent=continent, filter_country="all", filter_category="Mixed")
    elif badge_id == "flag_spotter":
        st.session_state.update(filter_category="Flags")
    state.remember_quiz_filters()
    state.open_setup()


def _settings_label(settings: dict, total: int) -> str:
    country = get_country(settings["country_id"])
    items = [t(settings["continent"]), country_label(country["id"]) if country else t("All Countries"),
             t(settings["category"]), t(settings["difficulty"]), t("{n} questions", n=total),
             t("Timed") if settings["timer"] else t("Untimed")]
    if settings["category"] == "Mixed":
        items.append(t("Flag questions") if settings.get("flags", True) else t("No flag questions"))
    if settings.get("collection", DEFAULT_COLLECTION) != DEFAULT_COLLECTION:
        items.append(t("incl. territories"))
    return " · ".join(items)


def _round_day(quiz: dict) -> date | None:
    """The date a daily round belongs to (its own "day"), or None if it is missing or invalid."""
    try:
        return date.fromisoformat(quiz.get("day") or "")
    except (TypeError, ValueError):
        return None


def _daily_result(quiz, replay: bool) -> None:
    """Daily status on the results card. The round's own date decides which saved result is shown and shared, so a
    round from yesterday reopened after midnight UTC never shows (or crashes on) today's state. Today's challenge
    (availability, streak, next start) comes from _daily_status() and is kept separate."""
    d = _daily_status()
    day = _round_day(quiz)
    label = day.isoformat() if day else "–"
    saved = daily_engine.completed(st.session_state.daily, day) if day else None
    if replay:
        if saved:
            text = e("Points, badges and your day streak are unchanged. Saved result for {date}: {correct}/{total}.",
                     date=label, correct=saved["correct"], total=saved["total"])
        else:
            text = e("Points, badges and your day streak are unchanged. No saved result was found for {date}.", date=label)
        html(f'<div class="daily-result replay"><b>{e("Practice replay")}</b> · {text}</div>')
    else:
        if not saved:
            note = ""
        elif day == d["day"]:
            note = e("Today's result is saved. Come back tomorrow to keep your streak.")
        else:
            note = e("Your result for {date} is saved.", date=label)
        html(f'<div class="daily-result"><span class="daily-flame" aria-hidden="true">🔥</span><div><b>{e("Day streak: {n}", n=d["streak"])}</b> · '
             f'{e("Best: {n}", n=d["best"])}' + (f'<br><span>{note}</span>' if note else "") + '</div></div>')
    if saved:
        grid = daily_engine.share_grid(quiz["history"]) if not replay else ""
        # The streak is only known for the latest completed day; an older day is shared without one.
        streak = st.session_state.daily["streak"] if st.session_state.daily["last"] == label else None
        st.caption(t("Share your result (no answers included):"))
        st.code(daily_engine.share_text(day, saved["correct"], saved["total"], streak, grid), language=None)
    st.caption(d["next"] if d["done"] else t("Today's challenge is ready."))


def _return_label(group: str, kept: dict) -> str:
    """Button label for a kept (parked) round; a daily round from an earlier day names its date."""
    if group == "daily" and kept.get("day") != state.today().isoformat():
        return t("Return to the daily challenge of {date}", date=kept.get("day") or "–")
    return t({"daily": "Return to today's challenge", "practice": "Return to mistake practice"}.get(group, "Return to your quiz round"))


def _results(quiz) -> None:
    stats, settings = engine.statistics(quiz), quiz["settings"]
    sound.play_event(quiz["event"])
    mode = quiz.get("mode", "regular")
    replay = mode == "daily_replay"
    outcome = None if replay else (quiz.get("records_outcome") or records.update(st.session_state.records, quiz))
    won = records.medal(stats["accuracy"])
    fresh = _fresh(quiz["event"]["id"] + ":results")
    with st.container(key="result_card"):
        medal = (f'<div class="medal medal-{won}" role="img" aria-label="{e(MEDAL_LABELS[won])}"><span aria-hidden="true">★</span>'
                 f'<small>{e(MEDAL_LABELS[won])}</small></div>') if won else \
                f'<div class="medal medal-none"><small>{e("Keep practising")}</small></div>'
        html(f'<div class="eyebrow">{e("Challenge complete")}</div>'
             f'<div class="result-hero{" fx" if fresh else ""}">{medal}'
             f'<div class="result-stat"><b>{stats["accuracy"]:.0f}%</b><span>{e("Accuracy")} · {e("{correct} of {total} correct", correct=stats["correct"], total=stats["total"])}</span></div>'
             f'<div class="result-stat"><b>{stats["score"]:,}</b><span>{e("points")} · {e("Best streak")} {stats["best_streak"]}</span></div></div>')
        if quiz["perfect_bonus"]:
            html(f'<div class="perfect-banner{" fx" if fresh else ""}" role="status"><span class="sparkles" aria-hidden="true">✦ ✧ ✦</span>'
                 f'{e("Perfect round without hints: +{points} bonus points.", points=quiz["perfect_bonus"])}</div>')
        if mode in ("daily", "daily_replay"):
            _daily_result(quiz, replay)
        chips = []
        if replay:
            pass
        elif outcome["first_score"]:
            chips.append(("record", e("First score for these settings: {score}", score=f"{stats['score']:,}")))
        elif outcome["new_score"]:
            chips.append(("record new", e("New best for these settings! Previous best: {score}", score=f"{outcome['previous_score']:,}")))
        else:
            chips.append(("record", e("Your best for these settings: {score}", score=f"{outcome['best_score']:,}")))
        if replay:
            pass
        elif outcome["new_streak"]:
            chips.append(("record new", e("New streak record: {n} in a row", n=outcome["best_streak"])))
        else:
            chips.append(("record", e("Streak record (any round): {n}", n=outcome["best_streak"])))
        if chips:
            html('<div class="record-row">' + "".join(f'<span class="{cls}">{text}</span>' for cls, text in chips) + "</div>")
        if mode == "daily":
            st.caption(t("Records compare your daily challenges."))
        elif mode == "practice":
            st.caption(t("Records compare your mistake-practice rounds."))
        elif not replay:
            st.caption(t("Records compare rounds with the same settings: {settings}", settings=_settings_label(settings, stats["total"])))
        if accounts.connection_state() == "guest":
            st.caption(t("Guest records last for this browser session."))
        st.caption(t("Incorrect / unanswered: {wrong} · Timed out: {timeout} · Average response time: {seconds} seconds",
                     wrong=stats["incorrect"], timeout=stats["timed_out"], seconds=f"{stats['average_time']:.1f}"))
        status = badge_engine.evaluate(st.session_state.stats, st.session_state.points, st.session_state.rounds_finished)
        before = set(quiz.get("badges_before", []))
        new = [b for b in status if b["earned"] and b["id"] not in before]
        if new and "badges_before" in quiz:
            st.success(t("New badge earned: {names}", names=", ".join(_badge_name(b) for b in new)), icon="🏅")
        upcoming = badge_engine.arrange(status, upcoming=1)[1]
        if upcoming:
            b = upcoming[0]
            with st.container(key="next_badge"):
                html(f'<div class="next-badge"><span class="award-medal locked" aria-hidden="true">{b["symbol"]}</span><div>'
                     f'<b>{e("Closest badge: {name}", name=_badge_name(b))}</b> · {e("{value} of {target}", value=b["value"], target=b["target"])}'
                     f'<br><span>{escape(t(b["description"], **b["fields"]))}</span></div></div>')
                if b["id"].startswith("continent_") or b["id"] == "flag_spotter":
                    label = (t("Practise {continent}", continent=b["fields"]["continent"]) if b["fields"] else t("Practise flags"))
                    st.button(label, key="practise_badge", on_click=_practise_for, args=(b["id"],))
        one, two = st.columns(2)
        if mode in ("daily", "daily_replay"):
            d = _daily_status()
            if _round_day(quiz) == d["day"] and d["done"] and not d["in_progress"]:
                one.button(t("Play again (practice)"), type="primary", width="stretch", key="play_again", on_click=state.start_daily,
                           help=t("Replays today's questions. Points, badges and your day streak stay as they are."))
            else:  # the round is from an earlier day (after midnight UTC): offer today's challenge itself
                one.button(_daily_button_label(d), type="primary", width="stretch", key="play_again", on_click=state.start_daily)
        elif mode == "practice":
            if st.session_state.mistakes:
                one.button(t("Practise again"), type="primary", width="stretch", key="play_again", on_click=state.start_practice)
            else:
                one.button(t("Take a quiz →"), type="primary", width="stretch", key="play_again", on_click=state.open_setup)
        elif one.button(t("Play again"), type="primary", width="stretch", key="play_again"):
            state.start_round(settings)
            st.rerun()
        two.button(t("Change settings"), width="stretch", on_click=state.open_setup, key="change_settings")
        if mode != "practice":
            _practise_button("results_practise")
        for group, kept in state.parked_rounds().items():
            st.button(_return_label(group, kept) + f" ({kept['index'] + 1}/{len(kept['questions'])})", key=f"results_resume_{group}",
                      width="stretch", on_click=state.resume_round, args=(group,))
    missed = engine.missed(quiz)
    with st.container(key="review_card"):
        st.subheader(t("Review missed answers") if missed else t("Answer review"))
        if not missed:
            st.success(t("No missed answers in this round — well done."), icon="🌟")
        labels = {"missed": t("Missed only"), "all": t("All answers")}
        mode = st.segmented_control(t("Show"), ["missed", "all"], key="review_mode", required=True,
                                    format_func=labels.get) or "missed"
        records_shown = quiz["history"] if mode == "all" else [h for h in quiz["history"] if not h["correct"]]
        for i, record in enumerate(quiz["history"], 1):
            if record in records_shown:
                _review_entry(i, record)


def quiz() -> None:
    current = st.session_state.quiz
    if not current or st.session_state.show_setup:
        intro, setup = st.columns([1, 1.15], gap="large")
        with intro:
            _daily_box("daily_box_wide", "intro_daily")  # tablets and desktops: above the banner, beside the setup
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
        mode = current.get("mode", "regular")
        if mode in ("daily", "daily_replay"):
            heading = e("Daily challenge") + (" · " + e("practice replay") if mode == "daily_replay" else "")
            line = escape(current.get("day") or "") + " · " + e("{n} questions", n=len(current["questions"]))
        elif mode == "practice":
            heading, line = e("Practising mistakes"), e("{n} questions", n=len(current["questions"]))
        else:
            country = get_country(s["country_id"])
            label = country_label(country["id"]) if country else t(s["continent"])
            heading, line = e("Current challenge"), f'{escape(label)} · {e(s["difficulty"])} · {e(s["category"])}'
        summary.markdown(f'<div class="round-label">{heading}</div><div class="round-summary">{line}</div>',
                         unsafe_allow_html=True)
        action.button(t("Quiz settings"), key="quiz_settings", width="stretch", on_click=state.open_setup,
                      help=t("Opens quiz setup. Your current round is kept until you start a new one."))
    if current["finished"]:
        _results(current)
    else:
        # Only timed rounds tick; untimed rounds rerun on interaction alone.
        st.fragment(run_every=1 if s["timer"] else None)(_active_round)()


# --------------------------------------------------------------------------- Badges

def _badge_name(b: dict) -> str:
    return t(b["name"], **b["fields"]) if b["fields"] else t(b["name"])


def _award_card(b: dict) -> None:
    with st.container(key=f"award_card_{b['id']}"):
        html(f'<div class="award-head"><div class="award-medal {"" if b["earned"] else "locked"}" aria-hidden="true">{b["symbol"]}</div>'
             f'<div><div class="award-name">{escape(_badge_name(b))}</div>'
             f'<span class="award-state {"earned" if b["earned"] else ""}">{e("Earned" if b["earned"] else "In progress")}</span></div></div>')
        st.caption(t(b["description"], **b["fields"]))
        st.progress(b["value"] / b["target"], text=t("{value} of {target}", value=b["value"], target=b["target"]))


def _award_grid(group: list[dict]) -> None:
    for row in range(0, len(group), 3):
        for column, b in zip(st.columns(3), group[row:row + 3]):
            with column:
                _award_card(b)


def badges() -> None:
    hero("Your explorer passport", "Badges",
         "Every right answer is a step forward. Collect milestones as your knowledge grows.", variant="compact")
    points, rounds = st.session_state.points, st.session_state.rounds_finished
    status = badge_engine.evaluate(st.session_state.stats, points, rounds)  # read-only: viewing never changes progress
    earned, upcoming, rest = badge_engine.arrange(status)
    html('<div class="badge-stats">'
         f'<div><b>{points:,}</b><span>{e("Points")}</span></div>'
         f'<div><b>{rounds}</b><span>{e("Rounds")}</span></div>'
         f'<div><b>{len(earned)}/{len(status)}</b><span>{e("Badges")}</span></div>'
         f'<div><b>🔥 {daily_engine.current_streak(st.session_state.daily, state.today())}</b><span>{e("Day streak")}</span></div></div>'
         f'<p class="badge-note">{e("Badges count answers and rounds you complete. Progress is saved with your account when you are signed in.")}</p>')
    st.caption(t("Best day streak: {n} · Daily challenges completed: {count}", n=st.session_state.daily["best"],
                 count=len(st.session_state.daily["results"])))
    _practise_button("badges_practise")
    html(f'<h2 class="badge-section">{e("Earned badges")}</h2>')
    if earned:
        _award_grid(earned)
    else:
        html(f'<p class="badge-empty">{e("No badges yet. Answer quiz questions to earn your first one.")}</p>')
    if upcoming:
        html(f'<h2 class="badge-section">{e("Next goals")}</h2>')
        _award_grid(upcoming)
    if rest:
        # Opening the list only reveals cards; it does not rerun the script or touch progress.
        with st.expander(t("See all badges ({count} more)", count=len(rest)), key="badges_more"):
            _award_grid(rest)


ROUTES = {"Explore": explore, "Learn": learn, "Quiz": quiz, "Badges": badges}
