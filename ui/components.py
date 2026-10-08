"""Reusable interface pieces: header, hero banners, settings drawer, credits."""
from __future__ import annotations

import base64
import hashlib
import io
from html import escape
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

from core import accounts
from core.data import COUNTRIES, CONTINENTS, PHOTOS, get_countries, get_country
from core.i18n import LANGUAGES
from core.quiz import CATEGORIES

from .state import PAGES, formatter, navigate, open_settings, scope_label, t

STYLES = Path(__file__).resolve().parent.parent / "assets" / "styles.css"
MAX_UPLOAD_BYTES = 2_000_000


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def inject_styles() -> None:
    html(f"<style>{STYLES.read_text(encoding='utf-8')}</style>")


def e(text) -> str:
    """Translate then HTML-escape."""
    return escape(t(text))


# --------------------------------------------------------------------------- artwork

def globe_art() -> str:
    """Decorative orbital globe (not a map)."""
    return ('<svg viewBox="0 0 320 300" fill="none" aria-hidden="true">'
            '<defs><radialGradient id="ocean"><stop stop-color="#399a9a"/><stop offset="1" stop-color="#113b53"/></radialGradient></defs>'
            '<circle cx="160" cy="145" r="115" fill="url(#ocean)" stroke="#73bdb9" stroke-width="1.5"/>'
            '<g stroke="#b3e1d3" opacity=".45"><ellipse cx="160" cy="145" rx="54" ry="115"/><ellipse cx="160" cy="145" rx="92" ry="115"/>'
            '<ellipse cx="160" cy="145" rx="115" ry="42"/><ellipse cx="160" cy="145" rx="115" ry="84"/><path d="M45 145h230M160 30v230"/></g>'
            '<ellipse cx="160" cy="145" rx="152" ry="63" transform="rotate(-28 160 145)" stroke="#e9c17a" stroke-width="1.5" stroke-dasharray="4 6"/>'
            '<circle cx="269" cy="76" r="7" fill="#f3cf84"/><circle cx="57" cy="225" r="5" fill="#81d5c5"/>'
            '<circle cx="204" cy="119" r="5" fill="#fff1c4"/><circle cx="204" cy="119" r="13" stroke="#fff1c4" opacity=".5"/>'
            f'<text x="160" y="289" text-anchor="middle" fill="#aacbd1" font-size="10" font-family="Segoe UI,Arial" letter-spacing="4">{e("A WORLD TO DISCOVER")}</text></svg>')


CONTINENT_SHADES = {"Africa": "#23645c", "Asia": "#48667e", "Europe": "#606574",
                    "South America": "#27756b", "North America": "#305d79", "Oceania": "#288287"}


def cover_style(country: dict) -> str:
    photo = PHOTOS.get(country["id"])
    if photo:
        return f"background-image:url('{escape(photo['url'], quote=True)}');"
    shade = CONTINENT_SHADES.get(country["continent"], "#23645c")
    return f"background-image:radial-gradient(ellipse at 80% 10%,{shade},#102d40);"


def hero(kicker, title, description, *, variant: str = "") -> None:
    """variant: "" (standard), "tall" (beside the quiz setup) or "compact" (during a round)."""
    tags = "" if variant == "compact" else (
        '<div class="hero-tags">'
        f'<span>{e(t("{n} countries", n=len(COUNTRIES)))}</span>'
        f'<span>{e(t("{n} continents", n=len(CONTINENTS)))}</span>'
        f'<span>{e(t("{n} quiz categories", n=len(CATEGORIES) - 1))}</span></div>')
    css = f" hero-{variant}" if variant else ""
    html(f'<section class="hero{css}"><div class="hero-copy"><div class="hero-kicker">{e(kicker)}</div>'
         f'<div class="hero-title">{e(title)}</div><div class="hero-description">{e(description)}</div>{tags}</div>'
         f'<div class="hero-art">{globe_art()}</div></section>')


# --------------------------------------------------------------------------- header

def header() -> None:
    with st.container(key="app_header"):
        menu, brand, nav = st.columns([.13, 1, 1.3], vertical_alignment="center")
        with brand, st.container(key="header_brand"):
            html('<div class="brand"><div class="brand-symbol"><svg width="28" height="28" viewBox="0 0 28 28" fill="none" '
                 'stroke="currentColor" stroke-width="1.4" aria-hidden="true"><circle cx="14" cy="14" r="11"/>'
                 '<ellipse cx="14" cy="14" rx="5" ry="11"/><path d="M3 14h22M5 8h18M5 20h18"/></svg></div>'
                 '<div><div class="brand-name">World Explorer</div>'
                 f'<div class="brand-note">{e("For curious minds. Across every border.")}</div></div></div>')
        with nav, st.container(key="navigation"):
            for column, page in zip(st.columns(len(PAGES)), PAGES):
                column.button(t(page), key=f"nav_{page}", use_container_width=True,
                              type="primary" if st.session_state.page == page else "secondary",
                              on_click=navigate, args=(page,))
        with menu, st.container(key="header_menu"):
            st.button("☰", key="settings_menu", help=t("Settings"), use_container_width=True, on_click=open_settings)
        photo = st.session_state.profile_photo
        avatar = (f'<img class="header-avatar" src="{escape(photo, quote=True)}" alt="{e("Profile photo")}">' if photo
                  else f'<span class="header-avatar default-avatar" aria-label="{e("Guest explorer")}">●</span>')
        name = st.session_state.profile_name or t("Guest explorer")
        html(f'<div class="profile-note">{avatar}<span>{escape(name)} · {escape(scope_label())}</span></div>')
        st.divider()
    # The flag is consumed here: the dialog survives its own reruns and closes on a full rerun.
    if st.session_state.pop("settings_open", False):
        _settings_dialog()


# --------------------------------------------------------------------------- settings drawer

def _photo_upload() -> None:
    key = f"profile_photo_upload_{st.session_state.get('photo_upload_key', 0)}"
    uploaded = st.file_uploader(t("Profile photo"), type=["jpg", "jpeg", "png", "webp"], key=key)
    if uploaded is None:
        return
    raw = uploaded.getvalue()
    if len(raw) > MAX_UPLOAD_BYTES:
        st.error(t("Please choose a photo smaller than 2 MB."))
        return
    digest = hashlib.sha256(raw).hexdigest()
    if digest == st.session_state.photo_upload_digest:
        return
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.width * original.height > 20_000_000:
                raise ValueError("image too large")
            picture = ImageOps.fit(ImageOps.exif_transpose(original).convert("RGB"), (256, 256))
            buffer = io.BytesIO()
            picture.save(buffer, format="JPEG", quality=85)
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        st.error(t("This photo could not be opened. Please choose another image."))
        return
    st.session_state.profile_photo = accounts.PHOTO_PREFIX + base64.b64encode(buffer.getvalue()).decode()
    st.session_state.photo_upload_digest = digest
    accounts.save_profile()


def _remove_photo() -> None:
    st.session_state.profile_photo = ""
    st.session_state.photo_upload_digest = None
    st.session_state.photo_upload_key = st.session_state.get("photo_upload_key", 0) + 1  # fresh, empty uploader
    accounts.save_profile()


def _account_controls() -> None:
    who = accounts.identity()
    if who:
        st.caption(f"{t('Signed in')} · {who.get('email') or who.get('name', '')}")
        if st.button(t("Sign out"), key="profile_logout", use_container_width=True):
            accounts.logout()
    else:
        google, email = accounts.provider_ready("google"), accounts.provider_ready("account")
        st.caption(t("Sign in to save your profile and progress across visits."))
        for provider, label, ready in (("google", "Continue with Google", google),
                                       ("account", "Email sign-in / Create account", email)):
            if st.button(t(label), key=f"profile_{provider}", disabled=not ready, use_container_width=True):
                if not accounts.login(provider):
                    st.error(t("Sign-in could not start. Please check the account connection."))
        st.caption(t("Email registration and password reset are available on the secure sign-in screen."
                     if google or email else "Account sign-in is being set up. You can continue as a guest."))
    _photo_upload()
    if st.session_state.profile_photo:
        html(f'<img class="profile-preview" src="{escape(st.session_state.profile_photo, quote=True)}" alt="{e("Profile photo")}">')
        st.button(t("Remove photo"), key="profile_remove_photo", on_click=_remove_photo)
    if st.session_state.profile_save_error:
        st.warning(t("Your saved profile could not be reached. Changes have not been saved online."))


def _settings_body() -> None:
    st.subheader(t("Profile"))
    _account_controls()
    name = st.text_input(t("Display name"), value=st.session_state.profile_name, max_chars=40, key="preferences_name")
    lang = st.selectbox(t("App language"), LANGUAGES, index=LANGUAGES.index(st.session_state.app_language),
                        key="preferences_language")
    st.caption(t("Country names and factual names retain the dataset spelling."))
    st.divider()
    modes = list(accounts.SCOPE_MODES)
    mode = st.selectbox(t("Exploration area"), modes, index=modes.index(st.session_state.scope_mode),
                        format_func=formatter(modes), key="preferences_mode")
    area, country_id = "World", "all"
    if mode == "One continent":
        current = st.session_state.scope_continent
        area = st.selectbox(t("Continent"), CONTINENTS, index=CONTINENTS.index(current) if current in CONTINENTS else 0,
                            format_func=formatter(CONTINENTS), key="preferences_continent")
    elif mode == "One country":
        ids = [c["id"] for c in get_countries()]
        current = st.session_state.scope_country
        country_id = st.selectbox(t("Country"), ids, index=ids.index(current) if current in ids else 0,
                                  format_func=lambda i: get_country(i)["name"], key="preferences_country")
        area = get_country(country_id)["continent"]
    st.caption(t("Area changes update Explore and Learn and the next quiz setup. Your current round is kept."))
    if st.button(t("Apply settings"), key="apply_preferences", type="primary", use_container_width=True):
        st.session_state.pending_preferences = {"profile_name": name.strip(), "app_language": lang,
                                                "scope_mode": mode, "scope_continent": area, "scope_country": country_id}
        st.rerun()
    st.caption(t("Signed-in profiles save online when the account connection is ready. Guest profiles last for this session."))
    data_sources()


def _settings_dialog() -> None:
    st.dialog(t("Settings"), width="small")(_settings_body)()


# --------------------------------------------------------------------------- credits

def data_sources() -> None:
    with st.expander(t("Data sources and coverage")):
        st.markdown("Country data adapted from [mledoze/countries](https://github.com/mledoze/countries), licensed under "
                    "[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The adapted country database in `data/` "
                    "is distributed under the same licence.")
        st.markdown("Landmark locations are adapted from the [UNESCO World Heritage List](https://data.unesco.org/explore/dataset/whc001/), "
                    "checked 8 October 2026; only sites within a single country are used. Areas, domains and calling codes "
                    "follow the country dataset's definitions.")
        st.markdown("Language questions use the official-language lists; missing or uncertain entries are skipped. "
                    "Head-of-state questions use dated, sourced records only, and records older than 30 days are excluded "
                    "until verified again.")


def photo_credits() -> None:
    with st.expander(t("Photography credits")):
        st.caption(t("Photography loads online. Country illustrations are used where no curated photograph is included."))
        for p in PHOTOS.values():
            st.markdown(f"[{p['caption']}]({p['page']}) — {p['author']} · [{p['license']}]({p['license_url']}). "
                        "Cropped for layout; the original is unchanged.")
