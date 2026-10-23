"""The four pages: Explore, Learn, Quiz and Badges."""
from __future__ import annotations

import base64
import math
from datetime import date
from html import escape

import streamlit as st

from core import accounts, photos, records
from core import daily as daily_engine
from core import learn as learn_engine
from core import badges as badge_engine
from core import quiz as engine
from core.data import (AREAS, COLLECTIONS, WORLD, COUNTRIES, DEFAULT_COLLECTION, PHOTO_RECORDS, STATE_STATUSES, STATUS_LABELS, STATUSES, flag_image,
                       get_countries, get_country, load_political_records)
from core.quiz import CATEGORIES, DIFFICULTIES, QUESTION_COUNTS, currency_label

from . import music, owner, rewards_hooks, rewards_page, sound, state, world_map
from . import school as school_ui
from .components import e, hero, html, status_chip
from .state import country_formatter, country_label, formatter, parts, t

CONTINENTS_LIST = list(AREAS[1:])
EXPLORE_PAGE_SIZE = 10  # list rows per page: the list fits the box without inner scrolling


def _flag(country: dict, width: int, alt: str) -> None:
    image = flag_image(country)
    if image:
        st.image(image, width=width, alt=alt)


# --------------------------------------------------------------------------- Explore
# Project Atlas (Premium Digital Atlas V2). A heading ("Where would you like to go?") with a search for any country,
# then one large panel. World view: the interactive map fills the panel, with the continent pills (the map's key)
# underneath. Choosing a continent (map, pill or search) keeps the map in the panel, zoomed to that continent, and
# opens its countries beside it (desktop/tablet) or under it (phones): a list with the flag left of each name, and the
# chosen country in the same place as the list (with a way back to the list). One selection state drives everything;
# nothing here starts a quiz or touches an unfinished round.

def _turn_page(delta: int) -> None:
    st.session_state.explore_page = max(0, st.session_state.explore_page + delta)
    state.remember_explore_filters()


def _filters_changed() -> None:
    st.session_state.explore_page = 0
    state.remember_explore_filters()


def _browser_places(selection: str) -> list[dict]:
    """Places for the box under the current "Places to include" setting (the same lists the quiz uses)."""
    return get_countries(selection if selection in CONTINENTS_LIST else "World", collection=st.session_state.scope_collection)


def _count_text(selection: str) -> str:
    """"countries", or "countries and territories" when the list includes territories (counted from the dataset)."""
    places = _browser_places(selection)
    if all(c["status"] in STATE_STATUSES for c in places):
        return t("{n} countries", n=len(places))
    return t("{n} countries and territories", n=len(places))


def _filtered(places: list[dict], selection: str) -> list[dict]:
    """"Search Africa…" and a filter icon (status and places to include) above the list."""
    state.restore_explore_filters()
    statuses = ["all"] + [s for s in STATUSES if any(c["status"] == s for c in places)]
    if st.session_state.get("explore_status") not in statuses:
        st.session_state.explore_status = "all"
    chosen = st.session_state.explore_status
    where = t(selection) if selection in CONTINENTS_LIST else t("All countries")
    with st.container(key="explore_filters", horizontal=True, vertical_alignment="center"):
        query = st.text_input(t("Search countries or capitals"), key="explore_search", on_change=_filters_changed,
                              placeholder=t("Search {place}…", place=where), label_visibility="collapsed",
                              icon=":material/search:")
        active = chosen != "all" or st.session_state.scope_collection != DEFAULT_COLLECTION
        with st.popover(t("Filters"), icon=":material/filter_list:", key="explore_filter_menu",
                        help=t("Status and places to include") + (" •" if active else "")):
            if len(statuses) > 2:
                labels = {"all": t("All statuses"), **{s: t(STATUS_LABELS[s]) for s in STATUSES}}
                chosen = st.selectbox(t("Status"), statuses, format_func=labels.get, key="explore_status",
                                      on_change=_filters_changed)
            if st.session_state.get("explore_places") != st.session_state.scope_collection:
                st.session_state.explore_places = st.session_state.scope_collection  # follows Settings
            st.selectbox(t("Places to include"), COLLECTIONS, format_func=formatter(COLLECTIONS), key="explore_places",
                         on_change=state.apply_explore_places)
    state.remember_explore_filters()
    needle = query.strip().casefold()
    out = []
    for c in places:
        if chosen != "all" and c["status"] != chosen:
            continue
        names = [c["name"], t(c["name"]), c.get("official_name", "")] + [x["name"] for x in c["capitals"]]
        if needle and not any(needle in n.casefold() for n in names):
            continue
        out.append(c)
    return out if needle else sorted(out, key=lambda c: _alpha_key(t(c["name"])))


def _alpha_key(name: str) -> str:
    """Alphabetical order that ignores accents and case ("Åland" with the A's, "Côte d'Ivoire" with the C's)."""
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)).casefold()


PHOTO_SIZES = {"detail-photo-frame": "(max-width: 900px) 100vw, 480px", "learn-photo-frame": "(max-width: 900px) 100vw, 640px"}


def _photo_figure(photo: dict, cls: str) -> str:
    """A country photograph (Wikimedia Commons) with its description and full credit underneath.

    Mobile-friendly: the browser picks the smallest Commons thumbnail that is sharp enough for the screen (srcset),
    loads it lazily and asynchronously, and the stored size reserves the right proportions before it arrives (no
    jump, no stretching). If it cannot load, a calm placeholder of the same proportions says so (CSS) and the
    credit line stays. The description is in the caption, so the image itself is decorative for screen readers."""
    src, srcset = photos.sources(photo)
    w, h = photo.get("width"), photo.get("height")
    dims = f' width="{int(w)}" height="{int(h)}" style="aspect-ratio:{int(w)}/{int(h)}"' if w and h else ""
    responsive = f' srcset="{escape(srcset, quote=True)}" sizes="{PHOTO_SIZES.get(cls, "100vw")}"' if srcset else ""
    licence = escape(photo["license"])
    if photo.get("license_url"):
        licence = f'<a href="{escape(photo["license_url"], quote=True)}" target="_blank" rel="noopener">{licence}</a>'
    credit = (f'{e("Photo")}: {escape(photo["author"])} · {licence} · '
              f'<a href="{escape(photo["page"], quote=True)}" target="_blank" rel="noopener">Wikimedia Commons</a>')
    return (f'<figure class="photo-frame {cls}"><img src="{escape(src, quote=True)}"{responsive}{dims} alt="" loading="lazy" '
            f'decoding="async" referrerpolicy="no-referrer" data-fail="{e("Photo unavailable")}"><figcaption><span class="photo-caption">{escape(photo["caption"])}</span>'
            f'<span class="photo-credit">{credit}</span></figcaption></figure>')


def _country_photo(c: dict) -> dict | None:
    return photos.resolve(PHOTO_RECORDS.get(c["id"]))


def _flag_img(c: dict, cls: str, alt: str = "") -> str:
    image = flag_image(c)
    if not image:
        return f'<span class="{cls}"></span>'
    label = f'alt="{escape(alt, quote=True)}"' if alt else 'alt="" aria-hidden="true"'
    return f'<img class="{cls}" src="data:image/webp;base64,{base64.b64encode(image).decode()}" {label}>'


def _country_row(c: dict, current: str | None) -> None:
    """One list row (flag, name, capital, ›). The whole row is one button that opens the country on the right."""
    picked = c["id"] == current
    with st.container(key=f"country_row_{c['id']}{'_on' if picked else ''}"):
        capitals = " · ".join(x["name"] for x in c["capitals"]) or t("No capital listed")
        html(f'<div class="row-copy">{_flag_img(c, "row-flag")}<div><div class="row-name">{e(c["name"])}{status_chip(c)}</div>'
             f'<div class="row-capital">{escape(capitals)}</div></div></div>')
        st.button(t("Discover {name}", name=c["name"]), key=f"discover_{c['id']}", icon=":material/chevron_right:",
                  type="primary" if picked else "secondary", on_click=state.explore_pick, args=(c["id"],))


def _list_head(selection: str) -> None:
    """← World map | the continent."""
    continent = selection if selection in CONTINENTS_LIST else None
    with st.container(key="browser_head", horizontal=True, vertical_alignment="center"):
        st.button(t("World map"), key="continent_back", icon=":material/arrow_back:", on_click=state.explore_close,
                  help=t("Back to the world map"))
        emblem = world_map.emblem_svg(continent, 30) if continent else world_map.globe_svg(30)
        html(f'<div class="stage-title">{emblem}<div><h2 class="continent-title" tabindex="-1">{escape(_selection_title(selection))}</h2>'
             f'<div class="continent-count">{escape(_count_text(selection))}</div></div></div>')


def _country_list(selection: str, current: str | None) -> None:
    _list_head(selection)
    _selection_overview(selection)
    entries = _filtered(_browser_places(selection), selection)
    with st.container(key="explore_grid"):
        if not entries:
            st.info(t("No countries match your search."))
            return
        pages = math.ceil(len(entries) / EXPLORE_PAGE_SIZE)
        page = st.session_state.explore_page = min(st.session_state.explore_page, pages - 1)
        with st.container(key="explore_rows"):
            for country in entries[page * EXPLORE_PAGE_SIZE:(page + 1) * EXPLORE_PAGE_SIZE]:  # never the whole list
                _country_row(country, current)
        with st.container(key="explore_pagination", horizontal=True, vertical_alignment="center"):
            st.button(t("Previous"), key="explore_previous", icon=":material/chevron_left:", disabled=page == 0,
                      on_click=_turn_page, args=(-1,), type="tertiary")
            st.caption(f"{page + 1} / {pages}")
            st.button(t("Next"), key="explore_next", icon=":material/chevron_right:", icon_position="right",
                      disabled=page + 1 >= pages, on_click=_turn_page, args=(1,), type="tertiary")


FACT_ICONS = {  # small generic line icons for the fact tiles
    "capital": '<path d="M3 21h18M5 21V10m14 11V10M9 21v-7h6v7M2 10l10-6 10 6z"/>',
    "currency": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    "language": '<path d="M4 5h9M8.5 3v2M6 5c.8 3.6 3 6.4 6 8M11 5c-1 4-3.6 7.2-7 9M13 21l4.5-10 4.5 10M14.6 17.5h5.8"/>',
    "area": '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
}


def _fact(kind: str, label: str, value: str) -> str:
    icon = (f'<svg class="fact-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{FACT_ICONS[kind]}</svg>')
    return f'<div class="detail-fact">{icon}<div><span>{e(label)}</span><b>{escape(value)}</b></div></div>'


def _country_detail(c: dict, selection: str) -> None:
    """The right side of the box: what there is to discover about the chosen country."""
    back = t("Countries of {continent}", continent=selection) if selection in CONTINENTS_LIST else t("All countries")
    st.button(back, key="country_back", icon=":material/arrow_back:", on_click=state.explore_back_to_list,
              help=t("Back to the list"))
    region = " · ".join([" / ".join(t(x) for x in c["continents"]), c["region"]]).strip(" ·")
    html(f'<div class="detail-head">{_flag_img(c, "detail-flag", t("Flag of {name}", name=c["name"]))}<div>'
         f'<h3 class="detail-name" tabindex="-1">{e(c["name"])}</h3>'
         f'<div class="detail-region">{escape(region)}{status_chip(c)}</div></div></div>')
    photo = _country_photo(c)
    if photo:
        html(_photo_figure(photo, "detail-photo-frame"))
    else:   # no verified photograph yet: where the country is, instead of an empty space
        svg = _locator_svg(c)
        if svg:
            html(f'<figure class="learn-map detail-locator">{svg}<figcaption>{e("Where {name} is", name=c["name"])} · '
                 f'{e("Map data: Natural Earth (public domain)")}</figcaption></figure>')
    none = t("Not included yet")
    capitals = "; ".join(f"{x['name']} ({t(x['role'])})" if len(c["capitals"]) > 1 else x["name"] for x in c["capitals"]) or t("No capital listed")
    html('<div class="detail-facts">'
         + _fact("capital", "Capital", capitals)
         + _fact("currency", "Currency", ", ".join(map(currency_label, c["currencies"])) or none)
         + _fact("language", "Languages", ", ".join(c["languages"]) or none)
         + _fact("area", "Total area", f"{c['area_km2']:,.0f} km²" if c["area_km2"] else none) + "</div>")
    allowed = {x["id"] for x in get_countries(collection=st.session_state.scope_collection)}
    shown, hidden = learn_engine.split_neighbours(c, allowed)
    with st.expander(t("Neighbours") + (f" ({len(shown)})" if shown else ""), icon=":material/group:", key="detail_neighbours",
                     **rewards_hooks.expander_hook("detail_neighbours", c["id"])):
        if not c["borders"]:
            st.caption(t("{name} has no land borders with other places in this dataset.", name=c["name"]))
        if shown:
            with st.container(key="detail_neighbour_list", horizontal=True):
                for n in shown:
                    st.button(t(n["name"]), key=f"nbx_{n['id']}", on_click=rewards_hooks.explored,
                              args=(c["id"], state.explore_pick, n["id"]),
                              help=t("Discover {name}", name=n["name"]))
        if hidden:
            st.caption(t("Not shown with your current places setting: {names}. To include territories, choose them in ☰ Settings → Places to include.",
                         names=", ".join(t(n["name"]) for n in hidden)))
    with st.expander(t("Landmarks") + (f" ({len(c['landmarks'])})" if c["landmarks"] else ""), icon=":material/landscape:",
                     key="detail_landmarks", **rewards_hooks.expander_hook("detail_landmarks", c["id"])):
        if c["landmarks"]:
            st.markdown(" · ".join(f"[{s['name']}]({s['source']})" for s in c["landmarks"]))
        else:
            st.caption(t("Not included yet"))
    st.button(t("Quiz {name}", name=c["name"]), key="detail_quiz", type="primary", icon=":material/help:", width="stretch",
              on_click=rewards_hooks.explored, args=(c["id"], state.quiz_on_country, c["id"]),
              help=t("Opens the quiz setup with this country selected."))
    st.button(t("Learn about {name}", name=c["name"]), key="detail_learn", type="tertiary", icon=":material/menu_book:",
              on_click=rewards_hooks.explored, args=(c["id"], state.learn, c["id"]))


def _selection_overview(selection: str) -> None:
    """A compact strip above the list: real badge progress for the continent and its quiz."""
    continent = selection if selection in CONTINENTS_LIST else None
    with st.container(key="continent_overview", horizontal=True, vertical_alignment="center"):
        if continent:
            b = _continent_badge(continent)
            html(f'<div class="overview-strip"><div class="detail-empty"><div class="overview-badge"><b>{escape(_badge_name(b))}</b>'
                 f'<span class="award-state {"earned" if b["earned"] else ""}">{e("Earned") if b["earned"] else e("In progress")}</span>'
                 f'<span class="head-track" role="progressbar" aria-valuemin="0" aria-valuemax="{b["target"]}" aria-valuenow="{b["value"]}">'
                 f'<span style="width:{100 * b["value"] / b["target"]:.0f}%"></span></span>'
                 f'<span class="overview-progress">{e("{value} of {target} correct answers about {continent}", value=b["value"], target=b["target"], continent=continent)}</span></div></div></div>')
        else:
            html(f'<div class="overview-strip"><div class="detail-empty"><p>{e("Choose a country in the list to discover it here.")}</p></div></div>')
        _continent_quiz_button(selection)


def _continent_quiz_button(selection: str) -> None:
    continent = selection if selection in CONTINENTS_LIST else None
    st.button(t("Quiz {name}", name=t(continent)) if continent else t("Quiz all countries"), key="continent_quiz",
              type="primary", icon=":material/help:", width="stretch", on_click=state.quiz_continent, args=(selection,),
              help=t("Opens the quiz setup with {continent} selected.", continent=continent) if continent
              else t("Opens the quiz setup for all countries."))


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
    return t("Replay today's challenge") if d["done"] else t("Start today's challenge")


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


def _explore_topbar(d: dict) -> None:
    """One line under the map: real day streak, points and badges (number above its label), and the Daily Challenge
    (Start / Continue / Replay)."""
    ss = st.session_state
    status = badge_engine.evaluate(ss.stats, ss.points, ss.rounds_finished)
    earned = sum(1 for b in status if b["earned"])
    streak = daily_engine.current_streak(ss.daily, state.today())
    tiles = (("streak", "🔥", str(streak), "Day streak"), ("points", "★", f"{ss.points:,}", "Points"),
             ("badges", "🏅", f"{earned}/{len(status)}", "Badges"))
    with st.container(key="explore_topbar", horizontal=True, vertical_alignment="center"):
        html('<div class="explore-summary" role="list">' + "".join(
            f'<div class="summary-tile summary-{cls}" role="listitem" title="{e(label)}"><span class="summary-icon" aria-hidden="true">{icon}</span>'
            f'<b>{value}</b><span class="summary-label">{e(label)}</span></div>' for cls, icon, value, label in tiles) + "</div>")
        st.button(_daily_short_label(d), key="explore_daily", type="primary" if not d["done"] else "secondary",
                  icon=":material/arrow_forward:", icon_position="right", on_click=state.start_daily,
                  help=_daily_button_label(d) + " · " + _streak_text(d))


def _continent_badge(continent: str) -> dict:
    ss = st.session_state
    badge_id = "continent_" + continent.lower().replace(" ", "_")
    return next(b for b in badge_engine.evaluate(ss.stats, ss.points, ss.rounds_finished) if b["id"] == badge_id)


def _continent_buttons() -> None:
    """Continent pills under the map: "All" and the six continents, each with its map colour as a dot (CSS), so the
    pills double as the map's key. Same as tapping the map. They stay under the map while a continent is open, so
    another continent is one tap away; the open one is marked (primary)."""
    selection = state.explore_selection()
    with st.container(key="continent_buttons", horizontal=True):
        st.button(t("All"), key="browse_all", on_click=state.explore_select, args=(WORLD,), icon=":material/public:",
                  type="primary" if selection == WORLD else "secondary",
                  help=t("All continents") + " · " + t("Opens the country list without a continent filter."))
        for continent in CONTINENTS_LIST:
            st.button(t(continent), key=f"continent_btn_{continent.replace(' ', '_')}",
                      on_click=state.explore_select, args=(continent,),
                      type="primary" if selection == continent else "secondary",
                      help=t("Show the countries of {continent}", continent=continent))


def _find_everywhere() -> None:
    """The heading's search: opens the list of all countries, already filtered by what was typed."""
    ss = st.session_state
    query = (ss.get("explore_find") or "").strip()
    ss.explore_find = ""
    if not query:
        return
    state.explore_select(WORLD)
    ss.explore_country = None
    ss.explore_search = query
    ss.explore_page = 0
    state.remember_explore_filters()


def _explore_heading(selection: str | None) -> None:
    """Overline, the atlas title and (on the world view) a search for any country or capital."""
    with st.container(key="explore_heading", horizontal=True, vertical_alignment="bottom"):
        html(f'<div class="atlas-head map-heading"><div class="atlas-overline">{escape(_count_text(WORLD))} · {e("six continents")}</div>'
             f'<h1 class="atlas-title">{e("Where would you like to go?")}</h1></div>')
        if not selection:
            st.text_input(t("Search any country or capital"), key="explore_find", on_change=_find_everywhere,
                          placeholder=t("Search any country or capital"), label_visibility="collapsed",
                          icon=":material/search:")


def _selection_title(selection: str) -> str:
    if selection in CONTINENTS_LIST:
        return t(selection)
    return t("All countries and territories") if st.session_state.scope_collection != DEFAULT_COLLECTION else t("All countries")


def _map_select() -> None:
    state.explore_select(world_map.selected_value())


def _explore_map(selection: str | None, current: str | None, showing_country: bool) -> None:
    continent = selection if selection in CONTINENTS_LIST else None
    with st.container(key="world_map_frame"):
        world_map.render(continent, {c: t(c) for c in CONTINENTS_LIST},
                         t("World map. Use the continent buttons below to choose a continent."),
                         on_select=_map_select, on_close=state.explore_close, hidden=False,
                         view=selection, detail=current if showing_country else None, focus=continent,
                         oceans={o: t(o) for o in world_map.OCEANS}, antarctica_label=t("Antarctica"),
                         zoom_labels={k: t(v) for k, v in world_map.ZOOM_LABELS.items()})


def explore() -> None:
    d = _daily_status()
    selection = state.explore_selection()
    current = state.explore_country(selection)
    with st.container(key="explore_home"):
        _continue_card("explore")
        _explore_heading(selection)
        showing_country = bool(current) and state.explore_detail_open()  # the country takes the list's place
        stage_key = "explore_stage" if not selection else ("explore_stage_country" if showing_country else "explore_stage_list")
        with st.container(key=stage_key):  # the one exploration panel: the map always, plus the countries when open
            notice = st.session_state.pop("explore_notice", None) if selection else None
            if notice:
                st.info(notice, icon=":material/info:")
            if not selection:
                with st.container(key="stage_map"):
                    _explore_map(selection, current, showing_country)  # the map fills the whole panel
                    _continent_buttons()
            else:
                map_side, list_side = st.columns([1.5, 1], gap="medium")
                with map_side, st.container(key="stage_map"):
                    _explore_map(selection, current, showing_country)
                    _continent_buttons()
                with list_side, st.container(key="stage_panel"):
                    with st.container(key="stage_list"):
                        _country_list(selection, current)
                    if current:
                        with st.container(key="stage_detail"):
                            _country_detail(get_country(current), selection)
        _explore_topbar(d)   # streak, points, badges and the Daily Challenge: one line under the panel


# --------------------------------------------------------------------------- Learn

def _tile(label: str, value: str) -> str:
    return f'<div class="fact-tile"><div class="fact-label">{e(label)}</div><div class="fact-value">{escape(value)}</div></div>'


@st.cache_resource(show_spinner=False)
def _country_shapes() -> dict:
    """Simplified country outlines for the locator map (assets/country_shapes.json, built from Natural Earth)."""
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "assets" / "country_shapes.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"countries": data["countries"], "borders": data.get("borders", [])}
    except (OSError, ValueError, KeyError):
        return {"countries": {}, "borders": []}


def _locator_svg(c: dict) -> str | None:
    """A small map centred on the country: it is highlighted, its surroundings drawn in a quiet land colour, and a
    marker shows where it is (tiny places are only a marker). Classes are coloured by styles.css for light and dark.
    Only the outlines that fall inside the view are sent, so the map stays small (typically 5–40 KB)."""
    shapes = _country_shapes()["countries"]
    me = shapes.get(c["id"])
    if not me:
        return None
    x0, y0, x1, y1 = me["b"]
    w, h = max(x1 - x0, 6.0), max(y1 - y0, 4.0)
    width, height = max(w * 3.2, 46.0), max(h * 3.2, 28.75)
    width, height = (max(width, height * 1.6), max(height, width / 1.6))
    width, height = min(width, 1000.0), min(height, 625.0)
    vx, vy = (x0 + x1) / 2 - width / 2, (y0 + y1) / 2 - height / 2
    land = []
    for code, shape in shapes.items():
        a0, b0, a1, b1 = shape.get("a", shape["b"])
        # neighbours of similar size keep their full outline (borders line up); very large ones use the lighter one
        main_width = shape["b"][2] - shape["b"][0]
        outline = shape["p"] if (width <= 110 and main_width <= 3 * width) or not shape.get("q") else shape["q"]
        if code != c["id"] and outline and a1 >= vx and a0 <= vx + width and b1 >= vy and b0 <= vy + height:
            land.append(outline)
    lines = [b["d"] for b in _country_shapes()["borders"]
             if b["b"][2] >= vx and b["b"][0] <= vx + width and b["b"][3] >= vy and b["b"][1] <= vy + height] if width <= 400 else []
    cx, cy = me["c"]
    r = width / 95
    label = escape(t("Map showing the location of {name}", name=c["name"]), quote=True)
    return (f'<svg class="locator" viewBox="{vx:.1f} {vy:.1f} {width:.1f} {height:.1f}" role="img" aria-label="{label}" '
            f'preserveAspectRatio="xMidYMid slice"><rect class="lm-sea" x="{vx:.1f}" y="{vy:.1f}" width="{width:.1f}" height="{height:.1f}"/>'
            f'<path class="lm-land" d="{"".join(land)}"/>' + (f'<path class="lm-me" d="{me["p"]}"/>' if me["p"] else "")
            + (f'<path class="lm-border" d="{"".join(lines)}"/>' if lines else "")
            + f'<circle class="lm-ring" cx="{cx}" cy="{cy}" r="{r * 2.2:.2f}"/><circle class="lm-pin" cx="{cx}" cy="{cy}" r="{r:.2f}"/></svg>')


def _learn_map(c: dict) -> None:
    svg = _locator_svg(c)
    if not svg:
        return
    html(f'<figure class="learn-map">{svg}<figcaption><b>{e("Where {name} is", name=c["name"])}</b>'
         f'<span>{e("Map data: Natural Earth (public domain)")}</span></figcaption></figure>')


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
        continent = st.session_state.get("learn_continent") or "All"
        where = t(continent) if continent != "All" else state.scope_label()
        st.caption(t("{n} of {total} · {scope}", n=scope.index(current) + 1, total=len(scope), scope=where))
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
                    st.button(t(n["name"]), key=f"nb_{n['id']}", on_click=rewards_hooks.explored,
                              args=(c["id"], state.learn, n["id"]),
                              help=t("Learn about {name}", name=n["name"]))
        if hidden:
            st.caption(t("Not shown with your current places setting: {names}. To include territories, choose them in ☰ Settings → Places to include.",
                         names=", ".join(t(n["name"]) for n in hidden)))


def _size_comparison(c: dict) -> None:
    with st.expander(t("Compare country size"), key="compare_size", **rewards_hooks.expander_hook("compare_size", c["id"])):
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


LEARN_TABS = {"world": "🌍 World Geography", "school": "📚 School Learning"}


def _keep_learn_tab() -> None:
    st.session_state.learn_tab_saved = st.session_state.get("learn_tab") or "world"


def learn() -> None:
    """Learn has two parts: 🌍 World Geography (the country collection) and 📚 School Learning (ui/school.py).
    The choice is remembered for the visit; World Geography is the default."""
    # Project Atlas: the same calm heading as Explore (no banner)
    html(f'<div class="atlas-head learn-head"><div class="atlas-overline">{e("The country collection")}</div>'
         f'<h1 class="atlas-title">{e("Get to know the world.")}</h1></div>')
    ss = st.session_state
    if ss.get("learn_tab") not in LEARN_TABS:
        ss.learn_tab = ss.get("learn_tab_saved") if ss.get("learn_tab_saved") in LEARN_TABS else "world"
    with st.container(key="learn_tabs"):
        st.segmented_control(t("Learn"), list(LEARN_TABS), key="learn_tab", required=True, label_visibility="collapsed",
                             format_func=lambda k: LEARN_TABS[k].split(" ", 1)[0] + " " + t(LEARN_TABS[k].split(" ", 1)[1]),
                             on_change=_keep_learn_tab, width="stretch")
    if ss.learn_tab == "school":
        school_ui.render()
        return
    _world_learn()


def _learn_search_pick(country_id: str) -> None:
    ss = st.session_state
    ss.learn_search = ""
    if country_id not in state.learn_ids():
        ss.learn_continent = ss.learn_continent_pick = "All"
    state.learn(country_id)


def _learn_continent_changed() -> None:
    ss = st.session_state
    ss.learn_continent = ss.get("learn_continent_pick") or "All"
    ids = state.learn_ids()
    if ss.get("learn_country") not in ids and ids:
        ss.learn_country = ids[0]


def _learn_finder() -> None:
    """Phone-friendly finding: a search box (country, official name or capital) with tappable results, and continent
    filter chips that scroll sideways on phones. The chips only narrow Learn's own list (and Previous / Next)."""
    ss = st.session_state
    scope = state.scoped_countries()
    continents = [x for x in CONTINENTS_LIST if any(x in c["continents"] for c in scope)]
    with st.container(key="learn_finder"):
        query = st.text_input(t("Search countries or capitals"), key="learn_search", label_visibility="collapsed",
                              placeholder=t("Search countries or capitals") + "…", icon=":material/search:")
        needle = query.strip().casefold()
        if needle:
            found = [c for c in scope if any(needle in n.casefold() for n in
                     [c["name"], t(c["name"]), c.get("official_name", "")] + [x["name"] for x in c["capitals"]])]
            found.sort(key=lambda c: (not t(c["name"]).casefold().startswith(needle), t(c["name"])))
            if not found:
                st.caption(t("No country or capital matches your search."))
            with st.container(key="learn_results"):
                for c in found[:6]:
                    capitals = " · ".join(x["name"] for x in c["capitals"])
                    st.button(f'{t(c["name"])}' + (f" — {capitals}" if capitals else ""), key=f"learn_hit_{c['id']}",
                              width="stretch", on_click=_learn_search_pick, args=(c["id"],))
        if len(continents) > 1:
            if ss.get("learn_continent") not in ["All"] + continents:
                ss.learn_continent = "All"
            if ss.get("learn_continent_pick") not in ["All"] + continents:
                ss.learn_continent_pick = ss.learn_continent
            st.pills(t("Filter by continent"), ["All"] + continents, key="learn_continent_pick", required=True,
                     format_func=lambda x: t("All continents") if x == "All" else t(x), label_visibility="collapsed",
                     on_change=_learn_continent_changed)
        else:
            ss.learn_continent = "All"


def _world_learn() -> None:
    with st.container(key="learn_toolbar"):
        _learn_finder()
        _learn_picker_row()
    _learn_country()


def _learn_picker_row() -> None:
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
                        width="stretch", icon=":material/shuffle:")


def _learn_intro(c: dict) -> str:
    """One sentence built only from the dataset (region and land borders), never invented. States only: a
    territory keeps its status note instead."""
    if c["status"] not in STATE_STATUSES:
        return ""
    neighbours = sum(1 for b in c["borders"] if get_country(b) and get_country(b)["status"] in STATE_STATUSES)
    if neighbours:
        return t("{name} is a country in {region}, bordered by {n} {n:plural:country|countries}.",
                 name=c["name"], region=c["region"], n=neighbours)
    return t("{name} is a country in {region} with no land borders.", name=c["name"], region=c["region"])


def _learn_country() -> None:
    """Project Atlas Learn: introduction and key facts beside the photograph (the main picture), then a band with the
    compact locator map beside neighbours, landmarks and the size comparison. One Previous / Next, at the top."""
    c = get_country(st.session_state.learn_country)
    with st.container(key="learn_status", horizontal=True, vertical_alignment="center"):
        _learn_position(c["id"])
        _learn_nav(c["id"], "top")
    none = t("Not included yet")
    leader = load_political_records().get(c["id"])
    flag = flag_image(c)
    small_flag = (f'<img class="name-flag" src="data:image/webp;base64,{base64.b64encode(flag).decode()}" alt="" aria-hidden="true">'
                  if flag else "")
    region = " · ".join([" / ".join(t(x) for x in c["continents"]), c["region"]]).strip(" ·")
    capitals = "; ".join(f"{x['name']} ({t(x['role'])})" for x in c["capitals"]) or t("No capital listed")
    codes = " · ".join(c["calling_codes"] + c["domains"]) or none
    photo = _country_photo(c)
    intro = _learn_intro(c)
    with st.container(key="learn_card"):
        text_side, picture_side = st.columns([1, 1.12], vertical_alignment="top", gap="large")
        with text_side:
            html(f'<div class="country-top"><span class="country-code">{c["id"]}</span>'
                 f'<span class="country-region">{escape(region)}</span>{status_chip(c)}</div>'
                 f'<div class="name-row">{small_flag}<h2 class="country-name">{e(c["name"])}</h2></div>'
                 f'<div class="official-name">{escape(c.get("official_name", ""))}</div>'
                 + (f'<p class="learn-intro">{escape(intro)}</p>' if intro else ""))
            if c["status_note"]:
                st.caption(t(c["status_note"]))
            facts = [("capital", "Capital roles", capitals),
                     ("currency", "Currencies", ", ".join(map(currency_label, c["currencies"])) or none),
                     ("language", "Languages with official status or wide use", ", ".join(c["languages"]) or none),
                     ("area", "Total area", f"{c['area_km2']:,.0f} km²" if c["area_km2"] else none)]
            html('<div class="fact-grid learn-facts">' + "".join(_fact(kind, label, value) for kind, label, value in facts) + "</div>")
            for note in (c.get("capital_note"), c.get("currency_note")):
                if note:
                    st.caption("ⓘ " + t(note))
            with st.container(key="learn_quiz_action"):
                st.button(t("Quiz me on this country"), key="learn_quiz_me", type="primary", icon=":material/help:",
                          on_click=rewards_hooks.explored, args=(c["id"], state.quiz_on_country, c["id"]),
                          help=t("Opens the quiz setup with this country selected."))
        with picture_side:
            if photo:
                html(_photo_figure(photo, "learn-photo-frame"))       # the photograph is the main picture
            else:
                _learn_map(c)                                          # no verified photo yet: the map is the picture
        with st.container(key="learn_band"):
            if photo:
                map_side, more_side = st.columns([1, 1.6], vertical_alignment="top", gap="large")
                with map_side, st.container(key="learn_map_compact"):
                    _learn_map(c)                                      # compact: context, not the centrepiece
                with more_side, st.container(key="learn_more_side"):
                    _learn_sections(c)
            else:
                with st.container(key="learn_more_side"):
                    _learn_sections(c)
        _open_sections_on_desktop(c["id"])
        with st.container(key="learn_meta_desktop"):
            _source_lines(c, leader)
        with st.expander(t("More details"), key="learn_more", **rewards_hooks.expander_hook("learn_more", c["id"])):
            details = [("Official name", c.get("official_name") or none), ("Country code", c["id"]),
                       ("Calling codes and internet domains", codes)]
            html('<div class="more-details">' + "".join(f'<div><span>{e(k)}</span><b>{escape(v)}</b></div>' for k, v in details) + "</div>")
            _source_lines(c, leader)


def _learn_sections(c: dict) -> None:
    _neighbour_buttons(c)
    if c["landmarks"]:
        html(f'<div class="learn-section desk-only">{e("Landmarks")}</div>')
        with st.expander(t("Landmarks") + f" ({len(c['landmarks'])})", key="learn_landmarks_box"):
            st.markdown(" · ".join(f"[{s['name']}]({s['source']})" for s in c["landmarks"]))
    _size_comparison(c)


# --------------------------------------------------------------------------- Quiz

def _reset_country_filter() -> None:
    st.session_state.filter_country = "all"


def _where_summary(collection: str, continent: str, country_id: str) -> str:
    place = country_label(country_id) if country_id != "all" else t(continent)
    return " · ".join([place, t(collection)])


# Small inline icons for the quiz page (decorative; the words next to them carry the meaning).
QUIZ_ICONS = {
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
    "star": '<svg viewBox="0 0 24 24" fill="#E2B55A" stroke="#B58A3A" stroke-width="1.2" aria-hidden="true"><path d="M12 3l2.6 5.6 6 .7-4.5 4.1 1.2 6L12 16.4 6.7 19.4l1.2-6L3.4 9.3l6-.7z"/></svg>',
    "medal": '<svg viewBox="0 0 24 24" fill="none" stroke="#B58A3A" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="14" r="6"/><path d="M8.5 3h7l-2 5.5h-3z"/></svg>',
    "clock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    "bulb": '<svg viewBox="0 0 24 24" fill="none" stroke="#B58A3A" stroke-width="1.7" aria-hidden="true"><path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/></svg>',
    "trend": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 16l5-5 4 4 7-7M15 8h5v5"/></svg>',
    "bars": '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="13" width="4" height="7" rx="1"/><rect x="10" y="9" width="4" height="11" rx="1"/><rect x="16" y="5" width="4" height="15" rx="1" opacity=".35"/></svg>',
}


def _continue_card(key: str) -> None:
    """ "Your quiz is waiting!" — after a refresh, a closed browser or a lost connection, the unfinished round saved
    with the account is offered here (Explore and Quiz). Continuing restores it exactly; nothing is scored again."""
    ss = st.session_state
    q = ss.get("quiz")
    if not (ss.get("round_waiting") and q and not q["finished"]):
        return
    s, mode = q["settings"], q.get("mode", "regular")
    if mode in ("daily", "daily_replay"):
        what = t("Daily challenge")
    elif mode == "practice":
        what = t("Practising mistakes")
    else:
        what = f"{t(s['category'])} · {t(s['difficulty'])}"
    number = min(q["index"] + 1 + (1 if q["resolved"] else 0), len(q["questions"]))
    title = e("Your quiz is waiting!")
    progress = e("Question {n} of {total}", n=number, total=len(q["questions"]))
    earned = e("{points} points earned so far", points="{:,}".format(q["score"]))
    with st.container(key=f"{key}_continue", horizontal=True, vertical_alignment="center"):
        html(f'<div class="continue-text"><b>🎮 {title}</b><span>{escape(what)} · {progress} · ⭐ {earned}</span></div>')
        with st.container(key=f"{key}_continue_actions", horizontal=True):
            st.button(t("Continue quiz"), key=f"{key}_continue_go", type="primary", on_click=state.continue_round)
            st.button(t("Start a new quiz"), key=f"{key}_continue_new", on_click=state.review_new_quiz)


def _daily_box(box_key: str, button_key: str) -> None:
    """Compact Daily Challenge card: title, status line and one Start / Continue / Replay button."""
    d = _daily_status()
    with st.container(key=box_key, horizontal=True, vertical_alignment="center"):
        title = e("Today's challenge")  # kept outside the f-string (Python < 3.12 forbids backslashes there)
        html(f'<div class="daily-head"><span class="daily-icon">{QUIZ_ICONS["calendar"]}</span><div><b>{title}</b>'
             f'<span class="daily-status">{escape(_streak_text(d))}</span></div></div>')
        st.button(t("Continue") if d["in_progress"] else t("Replay") if d["done"] else t("Start"), key=button_key,
                  type="primary" if not d["done"] else "secondary", on_click=state.start_daily,
                  help=_daily_button_label(d))


def _quiz_top() -> None:
    """The compact cards at the top of the Quiz page: today's challenge, points, badges and the next daily start.
    Phones show a small title line instead of the statistics card, and hide both during a round (CSS)."""
    ss, d = st.session_state, _daily_status()
    status = badge_engine.evaluate(ss.stats, ss.points, ss.rounds_finished)   # read-only, as on Explore
    earned = sum(1 for b in status if b["earned"])
    badges_text = f"{earned}/{len(status)}"
    with st.container(key="quiz_top"):
        html(f'<div class="quiz-phone-title"><b>{e("Quiz")}</b><span>{e("{points} points", points=f"{ss.points:,}")} · '
             f'{e("{badges} badges", badges=badges_text)}</span></div>')
        daily, numbers = st.columns([1.05, 1.6], gap="small")
        with daily:
            _daily_box("daily_box", "setup_daily")
        next_text = d["next"] if d["done"] else t("Today's challenge is ready.")
        with numbers:
            html(f'<div class="quiz-stats">'
                         f'<div class="qs-item"><span class="qs-ico">{QUIZ_ICONS["star"]}</span><div><b>{ss.points:,}</b><span>{e("Points")}</span></div></div>'
                         f'<div class="qs-item"><span class="qs-ico">{QUIZ_ICONS["medal"]}</span><div><b>{badges_text}</b><span>{e("Badges")}</span></div></div>'
                         f'<div class="qs-item"><span class="qs-ico teal">{QUIZ_ICONS["clock"]}</span><div><span class="qs-next">{escape(next_text)}</span></div></div>'
                         f'</div>')


def _advanced_summary(settings: dict) -> str:
    items = [t("Timed") if settings["timer"] else t("Untimed")]
    if settings["category"] == "Mixed":
        items.append(t("Flag questions") if settings["flags"] else t("No flag questions"))
    items.append(_where_summary(settings["collection"], settings["continent"], settings["country_id"]))
    return " · ".join(items)


def _setup() -> dict:
    """The compact setup: Category, Difficulty and Questions, then the other options under Advanced quiz settings.
    The widgets keep their keys (filter_*), so the saved quiz filters and the round settings work exactly as before."""
    state.restore_quiz_filters()
    ss = st.session_state
    with st.container(key="settings_card"):
        for group, kept in state.parked_rounds().items():
            st.button(_return_label(group, kept) + f" ({kept['index'] + 1}/{len(kept['questions'])})", key=f"resume_{group}", width="stretch",
                      on_click=state.resume_round, args=(group,))
        html(f'<div class="setup-title"><b>{e("Set up your quiz")}</b>'
             f'<span>{e("Three choices, then play. Everything else is under Advanced.")}</span></div>')
        active = ss.quiz
        _continue_card("setup")
        if active and not active["finished"] and not ss.get("round_waiting"):
            if active.get("mode", "regular") == "regular":
                st.info(t("You have a round in progress. Starting a new quiz replaces it; use “Return to current round” to continue it."))
            else:
                st.info(t("Your current round is kept if you start a new quiz; you can return to it from here."))

        category = st.selectbox(t("Category"), CATEGORIES, format_func=formatter(CATEGORIES), key="filter_category")
        difficulty = st.segmented_control(t("Difficulty"), DIFFICULTIES, format_func=formatter(DIFFICULTIES),
                                          key="filter_difficulty", required=True, width="stretch") or ss.filter_difficulty
        count = st.segmented_control(t("Questions"), QUESTION_COUNTS, key="filter_count", required=True,
                                     width="stretch") or ss.filter_count

        with st.expander(t("Advanced quiz settings"), key="quiz_advanced"):
            timer = st.toggle(t("Timed challenge"), key="filter_timer",
                              help=t("15 seconds per question on Expert; 20 seconds on other levels."))
            flags = True
            if category == "Mixed":
                flags = st.toggle(t("Flag questions"), key="filter_flags",
                                  help=t("Flag questions show an image. Turn them off if you use a screen reader."))
            collection = st.selectbox(t("Places to include"), COLLECTIONS, format_func=formatter(COLLECTIONS),
                                      key="filter_collection", on_change=_reset_country_filter)
            one, two = st.columns(2)
            continent = one.selectbox(t("Continent"), AREAS, format_func=formatter(AREAS), key="filter_continent",
                                      on_change=_reset_country_filter)
            ids = ["all"] + [c["id"] for c in get_countries(continent, collection=collection)]
            if ss.filter_country not in ids:
                ss.filter_country = "all"
            country_id = two.selectbox(t("Country"), ids, key="filter_country",
                                       format_func=country_formatter(t("All Countries")))
            _music_switch("setup")
        state.remember_quiz_filters()

        settings = {"continent": continent, "country_id": country_id, "category": category, "difficulty": difficulty,
                    "count": count, "timer": timer, "collection": collection, "flags": flags}
        st.caption(_advanced_summary(settings))
        round_size, _ = state.preview(settings)
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
            waiting = state.unfinished_regular_round()
            if st.button(t("Start quiz"), key="start_quiz", type="primary", width="stretch", disabled=not round_size,
                         icon=":material/play_arrow:"):
                if waiting is None:
                    state.start_round(settings)
                    st.rerun()
                ss.confirm_new_quiz = True      # an unfinished round would be replaced: ask first
            if waiting is not None and ss.get("confirm_new_quiz"):
                with st.container(key="confirm_new"):
                    n = waiting["index"] + 1 + (1 if waiting["resolved"] else 0)
                    st.warning(t("Start a new quiz? Your unfinished quiz (question {n} of {total}) will end. The points "
                                 "you earned in it stay in your total.", n=min(n, len(waiting["questions"])),
                                 total=len(waiting["questions"])))
                    yes, no = st.columns(2)
                    if yes.button(t("Yes, start a new quiz"), key="confirm_new_yes", type="primary", width="stretch"):
                        ss.confirm_new_quiz = False
                        ss.round_waiting = False
                        state.start_round(settings)
                        st.rerun()
                    if no.button(t("Keep my quiz"), key="confirm_new_no", width="stretch"):
                        ss.confirm_new_quiz = False
                        st.rerun()
            if ss.quiz and not ss.quiz["finished"]:
                st.button(t("Return to current round"), width="stretch", on_click=state.close_setup, key="return_round")
        st.caption(t("Up to {n} questions · no repeated facts in the same round.", n=count))
    return settings


def _start_panel(settings: dict) -> None:
    """Desktop: a welcoming start panel beside the setup (no question is shown before Start). Phones keep only the
    practice button and the scoring rules from it (CSS)."""
    with st.container(key="quiz_intro"):
        html(f'<div class="quiz-intro"><span class="eyebrow">{e("Ready when you are")}</span>'
             f'<b class="quiz-intro-title">{e("Your quiz: {category} · {difficulty} · {n} questions", category=t(settings["category"]), difficulty=t(settings["difficulty"]), n=settings["count"])}</b>'
             f'<p>{e("Capitals, flags, currencies, languages and the places in between. Every question comes from a sourced fact, in a new mix each round.")}</p>'
             f'<div class="quiz-tiles">'
             f'<div class="qt gold"><b>{e("100 points × difficulty")}</b><span>{e("Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2.")}</span></div>'
             f'<div class="qt teal"><b>{e("Streaks up to ×3")}</b><span>{e("The 3rd correct answer in a row earns double, the 5th triple.")}</span></div>'
             f'<div class="qt lilac"><b>{e("{n} hints per round", n=engine.HINTS_PER_ROUND)}</b><span>{e("Each removes one wrong answer (−25 if correct).")}</span></div>'
             f'</div></div>')
        _practise_button("setup_practise")
        with st.expander(t("Scoring and hints"), key="quiz_rules"):
            st.write(t("Correct answers earn 100 base points, multiplied by difficulty: Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2."))
            st.write(t("Answer streak: the 1st and 2nd correct answers in a row earn the base points, the 3rd and 4th earn double, "
                       "and from the 5th on they earn triple. A wrong answer or a timeout resets the streak, and every round starts at 0."))
            st.write(t("In timed rounds, fast answers add 25 points. A hint removes one wrong option and deducts 25 from that "
                       "answer; a hinted answer still counts for the streak. Only the base points are multiplied. Each round "
                       "has three hints."))
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


def _round_progress(quiz) -> None:
    """Question n of N, this round's points, answer streak and hints left, and a colourful progress bar."""
    index, total, streak = quiz["index"], len(quiz["questions"]), quiz["streak"]
    multiplier = engine.streak_multiplier(streak) if streak else 1
    mult = f' <small class="mult">×{multiplier}</small>' if multiplier > 1 else ""
    done = index + quiz["resolved"]
    html(f'<div class="q-progress"><div class="q-progress-top"><b class="q-count">{e("Question {n} of {total}", n=index + 1, total=total)}</b>'
         f'<span class="q-chips">'
         f'<span class="q-chip score" title="{e("Points this round")}"><span class="q-ico">{QUIZ_ICONS["star"]}</span><b>{quiz["score"]:,}</b><small>{e("Points this round")}</small></span>'
         f'<span class="q-chip streak" title="{e("Answer streak")}"><span class="q-ico">{QUIZ_ICONS["trend"]}</span><b>{streak}{mult}</b><small>{e("Answer streak")}</small></span>'
         f'<span class="q-chip hints" title="{e("Hints left")}"><span class="q-ico">{QUIZ_ICONS["bulb"]}</span><b>{quiz["hints_remaining"]}</b><small>{e("Hints left")}</small></span>'
         f'</span></div>'
         f'<div class="q-bar" role="progressbar" aria-label="{e("Round progress")}" aria-valuemin="0" aria-valuemax="{total}" aria-valuenow="{done}">'
         f'<span style="width:{100 * done / total:.1f}%"></span></div></div>')


def _feedback(quiz, q, record, fresh: bool) -> tuple[str, str]:
    """Outcome with the points (and the streak multiplier) as the head; the explanation, one sourced fact and the
    points breakdown as the body. The Next button goes between them on phones (see _active_round)."""
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
    head_html = (f'<div class="feedback feedback-{tone} feedback-top{" fx" if fresh else ""}" role="status">'
                 f'<div class="feedback-head"><span class="feedback-icon" aria-hidden="true">{icon}</span><span>{head}</span>'
                 + (f'<span class="feedback-chips">{badge}</span>' if badge else "") + '</div></div>')
    body_html = (f'<div class="feedback feedback-{tone} feedback-body">'
                 f'<p class="feedback-explain">{escape(parts(q["explanation"]))} {source}</p>{fact_html}'
                 + "".join(f'<p class="feedback-note">{n}</p>' for n in notes)
                 + f'<p class="answer-key"><span class="key-ok" aria-hidden="true">✓</span>{e("Solid green border = correct answer")}'
                   f'<span class="key-bad" aria-hidden="true">✕</span>{e("Dashed red border = wrong answer")}</p></div>')
    return head_html, body_html


def _bring_into_view(selector: str, block: str, token: str) -> None:
    """Once per event: scroll the element into view only if it is off screen (short phones, landscape, flag images).
    A tiny one-off script; smooth unless the visitor prefers reduced motion. (No "<" in it: the HTML cleaner drops
    scripts containing "<" followed by a letter or digit.)"""
    sel = selector.replace("'", "")
    token = "".join(ch for ch in token if ch.isalnum() or ch in ":-_")   # makes each script new, so it runs once per event
    st.html("<script>/*" + token + "*/(function(){let n=0;const go=()=>{const el=[...document.querySelectorAll('" + sel + "')].find(x=>x.offsetParent);"
            "if(!el){if(40>n++)setTimeout(go,50);return;}const r=el.getBoundingClientRect();"
            "if(0>r.top||r.bottom>innerHeight){el.scrollIntoView({block:'" + block + "',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}};"
            "setTimeout(go,60);})();</script>", unsafe_allow_javascript=True)


def _active_round() -> None:
    quiz = st.session_state.quiz
    if not quiz or quiz["finished"] or st.session_state.show_setup or st.session_state.page != "Quiz":
        return
    state.expire_if_due()
    engine.mark_presented(quiz)  # the answer clock starts when the question is shown (timed and untimed)
    q, index, serial = engine.current_question(quiz), quiz["index"], quiz["serial"]
    total, limit = len(quiz["questions"]), engine.time_limit(quiz)
    slug, icon = CATEGORY_STYLES.get(q["kind"], ("geography", "🧭"))
    fresh = quiz["resolved"] and _fresh(quiz["event"]["id"])
    new_question = not quiz["resolved"] and _fresh(f"question:{serial}:{index}")
    # Every part of the question keeps the same position from one question to the next (optional parts sit in their
    # own fixed slots), so Streamlit updates the elements in place. When positions shifted, the previous question's
    # answers and feedback were redrawn as new elements and the old ones stayed on screen until the run ended: the
    # box that flashed under the new question.
    # A fixed key: the category colour comes from the category tag (CSS :has), so a new category does not rebuild it.
    with st.container(key="quizcat_q"):
        _round_progress(quiz)
        with st.container(key="question_card"):
            html(f'<div class="q-tags"><span class="cat-chip cat-{slug}"><span aria-hidden="true">{icon}</span> {e(q["kind"])}</span>'
                 f'<span class="diff-chip"><span class="q-ico">{QUIZ_ICONS["bars"]}</span>{e(quiz["settings"]["difficulty"])}</span></div>')
            if limit is not None:   # timed rounds only (the same for the whole round)
                with st.empty().container():
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
        # Four neutral answer cards; only the letter badge has a colour (blue, violet, amber, slate: never red or
        # green, so no card looks right or wrong before answering). Two per row on wider screens, one column on
        # phones (CSS). After answering, only the right answer (green, solid border, ✓ and a label) and a wrong
        # choice (red, dashed border, ✕ and a label) keep colour; the others fade.
        with st.container(key="answers_grid"):
            for row in (0, 2):
                if row >= len(q["choices"]):   # True/False: the second row's slot is emptied (no leftover row)
                    st.empty()
                    continue
                for column, choice in zip(st.columns(2), q["choices"][row:row + 2]):
                    pos = q["choices"].index(choice)
                    style, label = "neutral_answer", t(choice)
                    if quiz["resolved"] and choice == q["answer"]:
                        tag = "✓ " + (t("Your answer · Correct") if choice == quiz["selected"] else t("Correct answer"))
                        style, label = "correct_answer", f"{t(choice)} `{tag}`"
                    elif quiz["resolved"] and choice == quiz["selected"]:
                        style, label = "wrong_answer", f"{t(choice)} `✕ {t('Your answer · Wrong')}`"
                    elif choice in quiz["hidden_options"]:
                        style, label = "hidden_answer", t("Removed by hint")
                    if fresh and style in ("correct_answer", "wrong_answer"):
                        style += "_fx"  # one-off emphasis; the key changes back on the next rerun
                    with column, st.container(key=f"ans{pos}_{style}"):
                        st.button(label, key=f"answer_{serial}_{index}_{pos}", width="stretch",
                                  disabled=quiz["resolved"] or choice in quiz["hidden_options"],
                                  on_click=state.answer, args=(choice, serial, index))
        hint_slot, feedback_slot, script_slot = st.empty(), st.empty(), st.empty()   # fixed slots, filled or left empty
        if not quiz["resolved"] and len(q["choices"]) == 4:
            with hint_slot.container(key="hint_row", horizontal=True, vertical_alignment="center"):
                html(f'<div class="hint-text"><span class="q-ico">{QUIZ_ICONS["bulb"]}</span><span><b>{e("Need a hint?")}</b> '
                     f'{e("Removes one wrong answer · −25 if correct · {n} of {total} left", n=quiz["hints_remaining"], total=engine.HINTS_PER_ROUND)}</span></div>')
                st.button(t("Hint used") if quiz["hint_used"] else t("Show hint"), key=f"hint_{serial}_{index}",
                          disabled=quiz["hint_used"] or quiz["hints_remaining"] == 0,
                          on_click=state.hint, args=(serial, index))
        if quiz["resolved"]:
            record = quiz["history"][-1]
            head_html, body_html = _feedback(quiz, q, record, fresh)
            final = index + 1 == total
            tone = "correct" if record["correct"] else "timeout" if record["timed_out"] else "wrong"
            with feedback_slot.container(key=f"quiz_feedback_{tone}"):
                html(head_html)
                with st.container(key="quiz_next_action"):
                    label = t("View results" if final else "Next question →")
                    if final:
                        # The results card lives outside this quiz section, so the last question reloads the page.
                        if st.button(label, type="primary", width="stretch", key=f"next_{serial}_{index}"):
                            state.next_question(serial, index)
                            st.rerun()
                    else:
                        # One click = one question: the callback advances exactly once (it checks serial and index)
                        # and only this quiz section is redrawn, not the whole page.
                        st.button(label, type="primary", width="stretch", key=f"next_{serial}_{index}",
                                  on_click=state.next_question, args=(serial, index))
                html(body_html)
                sound.play_event(quiz["event"])
        if fresh:          # after answering: Next on screen
            with script_slot:
                _bring_into_view(".st-key-quiz_next_action button", "center", f"a{serial}-{index}")
        elif new_question:  # after Start or Next: the question on screen, from its top
            with script_slot:
                _bring_into_view(".st-key-quiz_play", "start", f"q{serial}-{index}")
    # Answers and Next redraw only this section, so the profile is saved here too (the same existing save, which writes
    # only when something changed), exactly as often as before.
    accounts.save_profile()


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


def _dismiss_save_invite() -> None:
    st.session_state.save_invite_dismissed = True


def _save_invite() -> None:
    """After a guest's first completed round: offer to keep the progress with Google (dismissible)."""
    from .components import sign_in_button  # local import: components imports this module's state helpers
    if (accounts.identity() is not None or st.session_state.get("save_invite_dismissed")
            or st.session_state.rounds_finished < 1 or not accounts.provider_ready("google")):
        return
    with st.container(key="save_invite"):
        html(f'<div class="save-invite-text"><b>{e("Save your progress with Google")}</b>'
             f'<span>{e("Keep your points, streaks and badges for your next visit, on any device. What you played today comes with you.")}</span></div>')
        with st.container(key="save_invite_actions", horizontal=True):
            sign_in_button("google", "Save your progress with Google", "save_invite_google", primary=True)
            st.button(t("Continue as guest"), key="save_invite_dismiss", on_click=_dismiss_save_invite)


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
        accuracy = stats["accuracy"]
        headline = ("A perfect round. Well done!" if accuracy >= 100 else "Great round. You know your world." if accuracy >= 70
                    else "Good effort. Every round teaches something new.")
        # Replays of today's challenge add nothing to the totals, so their score is shown as the round score only.
        points_label = e("Round score") if replay else e("Points earned")
        points_value = f"{stats['score']:,}" if replay else f"+{stats['score']:,}"
        html(f'<div class="result-top{" fx" if fresh else ""}">{medal}<div class="result-title">'
             f'<span class="eyebrow">{e("Quiz complete")}</span><b>{e(headline)}</b></div></div>'
             f'<div class="result-tiles">'
             f'<div class="rt teal"><b>{accuracy:.0f}%</b><span>{e("Accuracy")}</span></div>'
             f'<div class="rt mint"><b>{e("{correct} of {total}", correct=stats["correct"], total=stats["total"])}</b><span>{e("Correct answers")}</span></div>'
             f'<div class="rt gold"><b>{points_value}</b><span>{points_label}</span></div>'
             f'<div class="rt lilac"><b>{stats["best_streak"]}</b><span>{e("Best answer streak")}</span></div></div>')
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
            earlier = records.earlier_untimed_best(st.session_state.records, quiz)
            if earlier is not None:
                st.caption(t("Untimed rounds no longer give speed points, so a new record starts here. Your earlier best "
                             "for these settings ({score}) is kept.", score=f"{earlier:,}"))
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
        _save_invite()
        one, two, three = st.columns(3)
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
        two.button(t("Try another category"), width="stretch", on_click=state.open_setup, key="change_settings",
                   help=t("Opens quiz setup with your current settings."))
        three.button(t("Explore countries"), width="stretch", on_click=state.navigate, args=("Explore",), key="results_explore")
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


def _music_changed(where: str) -> None:
    ss = st.session_state
    ss.music_on = bool(ss.get(f"music_switch_{where}"))
    ss.music_token = ss.get("music_token", 0) + 1


@st.fragment
def _music_switch(where: str) -> None:
    """The background-music switch. A partial redraw: switching it never reruns the page or the question."""
    ss = st.session_state
    key = f"music_switch_{where}"
    ss[key] = music.enabled()
    st.toggle(t("Relaxing background music"), key=key, on_change=_music_changed, args=(where,),
              help=t("Soft, calm music while you play. Off by default; plays only on the Quiz page and pauses when you leave it or switch apps."))
    token = ss.get("music_token", 0)
    if token and ss.get("music_told") != token:
        ss.music_told = token
        music.tell_player(ss.music_on, token)
        accounts.save_profile()   # the existing save: one write, only because the choice changed


def quiz() -> None:
    current = st.session_state.quiz
    music.player()
    _quiz_top()
    if not current or st.session_state.show_setup:
        # Before a round: the compact setup on the left, a welcoming start panel on the right (no question yet).
        setup, intro = st.columns([1, 1.42], gap="medium")
        with setup:
            settings = _setup()
        with intro:
            _start_panel(settings)
        return
    # During a round the question comes first: no setup, just one slim line with the round and "Quiz settings".
    with st.container(key="quiz_play"):
        with st.container(key="round_bar", horizontal=True, vertical_alignment="center"):
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
                heading = e("Current quiz")
                line = f'{escape(label)} · {e(s["difficulty"])} · {e(s["category"])} · ' + (e("Timed") if s["timer"] else e("Untimed"))
            html(f'<div class="round-line"><span class="round-label">{heading}</span><span class="round-summary">{line}</span></div>')
            # A compact floating panel, closed by default. Opening and closing it happen in the browser only (no
            # rerun), so the round is never redrawn or restarted by it.
            with st.popover(t("Quiz settings"), icon=":material/tune:", key="quiz_settings_menu"):
                html(f'<div class="pop-head"><b>{e("Quiz settings")}</b><button type="button" class="we-pop-close" '
                     f'aria-label="{e("Close quiz settings")}">✕</button></div>'
                     f'<p class="pop-note">{e("Opening or closing this panel never restarts your quiz.")}</p>')
                _music_switch("play")
                st.button(t("Change quiz setup"), key="quiz_settings", on_click=state.open_setup, icon=":material/tune:",
                          width="stretch", help=t("Opens quiz setup. Your current round is kept until you start a new one."))
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


ROUTES = {"Explore": explore, "Learn": learn, "Quiz": quiz, "Badges": badges, "Owner": owner.render,
          "Rewards": rewards_page.render}
