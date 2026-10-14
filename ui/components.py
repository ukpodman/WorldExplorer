"""Reusable interface pieces: header, hero banners, settings drawer, credits."""
from __future__ import annotations

import base64
import hashlib
import io
import time
from html import escape
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

from core import accounts, analytics, cookies
from core.data import COLLECTIONS, CONTINENTS, COUNTRIES, PHOTOS, STATES, STATUS_LABELS, get_countries, get_country
from core.i18n import LANGUAGES
from core.quiz import CATEGORIES

from . import rewards_hooks, sound
from .state import PAGES, country_formatter, formatter, navigate, open_settings, t

STYLES = Path(__file__).resolve().parent.parent / "assets" / "styles.css"
MAX_UPLOAD_BYTES = 2_000_000


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def _stylesheet(version: int) -> str:
    """Cached per file version: an updated styles.css is picked up after a deploy without an app reboot."""
    return STYLES.read_text(encoding="utf-8")


# Follows Streamlit's *effective* theme (system setting, live changes, or an explicit Light/Dark choice in
# Streamlit's settings): reads the background colour Streamlit gives its header and mirrors it as
# <html data-we-theme="light|dark">, which assets/styles.css uses to switch its colour tokens.
THEME_SYNC = """<script data-we-theme-sync="1">
(function () {
  if (window.__weThemeSync) { window.__weThemeSync(); return; }
  var root = document.documentElement, pending = false;
  function luminance(colour) {
    var m = (colour || "").match(/[\\d.]+/g);
    if (!m || m.length < 3 || (m.length > 3 && parseFloat(m[3]) === 0)) return null;
    return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
  }
  function sync() {
    pending = false;
    var probe = document.querySelector('[data-testid="stApp"]');
    if (!probe) return;
    var l = luminance(getComputedStyle(probe).backgroundColor);
    if (l === null) return;
    var mode = l < 0.5 ? "dark" : "light";
    if (root.getAttribute("data-we-theme") !== mode) root.setAttribute("data-we-theme", mode);
  }
  function schedule() { if (!pending) { pending = true; requestAnimationFrame(sync); } }
  window.__weThemeSync = schedule;
  new MutationObserver(schedule).observe(document.head, {childList: true, subtree: true, characterData: true});
  new MutationObserver(schedule).observe(document.body, {attributes: true, subtree: false});
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    (mq.addEventListener ? mq.addEventListener("change", function () { setTimeout(schedule, 50); }) : mq.addListener(schedule));
  }
  window.addEventListener("storage", schedule);
  setInterval(sync, 1500);
  schedule();
})();
</script>"""


# Global Privacy Control reported by the browser (navigator.globalPrivacyControl) is mirrored into the we_gpc
# cookie so the server honours it as well as the Sec-GPC header. When it first appears, the page reloads once so
# the new session starts with measurement off; the reload is skipped if cookies cannot be stored.
GPC_SYNC = """<script data-we-gpc="1">
(function () {
  if (window.__weGpcDone) return; window.__weGpcDone = true;
  var on = navigator.globalPrivacyControl === true, has = /(?:^|; )we_gpc=1/.test(document.cookie);
  var secure = location.protocol === "https:" ? ";Secure" : "";
  if (on && !has) {
    document.cookie = "we_gpc=1;Path=/;Max-Age=31536000;SameSite=Lax" + secure;
    var reloaded = false;
    try { reloaded = sessionStorage.getItem("we_gpc_reloaded") === "1"; sessionStorage.setItem("we_gpc_reloaded", "1"); } catch (e) { reloaded = true; }
    if (/(?:^|; )we_gpc=1/.test(document.cookie) && !reloaded) location.reload();
  } else if (!on && has) {
    document.cookie = "we_gpc=;Path=/;Max-Age=0;SameSite=Lax" + secure;
  }
})();
</script>"""


def inject_styles() -> None:
    html(f"<style>{_stylesheet(STYLES.stat().st_mtime_ns)}</style>")
    st.html(THEME_SYNC + GPC_SYNC, unsafe_allow_javascript=True)  # one element: no extra layout gap


def e(text, **fields) -> str:
    """Translate then HTML-escape."""
    return escape(t(text, **fields))


# --------------------------------------------------------------------------- artwork

def globe_art() -> str:
    """Decorative orbital globe (not a map)."""
    return ('<svg viewBox="0 0 320 300" fill="none" aria-hidden="true" focusable="false">'
            '<defs><radialGradient id="ocean"><stop stop-color="#2f8f92"/><stop offset="1" stop-color="#17283B"/></radialGradient></defs>'
            '<circle cx="160" cy="145" r="115" fill="url(#ocean)" stroke="#5fa7a8" stroke-width="1.5"/>'
            '<g stroke="#cfe3dc" opacity=".4"><ellipse cx="160" cy="145" rx="54" ry="115"/><ellipse cx="160" cy="145" rx="92" ry="115"/>'
            '<ellipse cx="160" cy="145" rx="115" ry="42"/><ellipse cx="160" cy="145" rx="115" ry="84"/><path d="M45 145h230M160 30v230"/></g>'
            '<ellipse cx="160" cy="145" rx="152" ry="63" transform="rotate(-28 160 145)" stroke="#B58A3A" stroke-width="1.5" stroke-dasharray="4 6"/>'
            '<circle cx="269" cy="76" r="6" fill="#d9b670"/><circle cx="57" cy="225" r="4" fill="#8cc5bd"/>'
            '<circle cx="204" cy="119" r="5" fill="#F7F4ED"/><circle cx="204" cy="119" r="13" stroke="#F7F4ED" opacity=".45"/></svg>')


def hero(kicker, title, description, *, variant: str = "") -> None:
    """variant: "" (standard), "tall" (beside the quiz setup) or "compact" (during a round)."""
    tags = "" if variant == "compact" else (
        '<div class="hero-tags">'
        f'<span>{e("{n} UN member and observer states", n=len(STATES))}</span>'
        f'<span>{e("{n} places in total", n=len(COUNTRIES))}</span>'
        f'<span>{e("{n} quiz categories", n=len(CATEGORIES) - 1)}</span></div>')
    css = f" hero-{variant}" if variant else ""
    html(f'<section class="hero{css}"><div class="hero-copy"><div class="hero-kicker">{e(kicker)}</div>'
         f'<h1 class="hero-title">{e(title)}</h1><div class="hero-description">{e(description)}</div>{tags}</div>'
         f'<div class="hero-art">{globe_art()}</div></section>')


def status_chip(country: dict) -> str:
    """Neutral status label; UN members get no chip to keep cards calm."""
    if country["status"] == "un_member":
        return ""
    return f'<span class="status-chip status-{country["status"]}">{e(STATUS_LABELS[country["status"]])}</span>'


# --------------------------------------------------------------------------- header

def header() -> None:
    """Row 1: brand and Explore · Learn · Quiz · Badges. Row 2 (account bar): Sign in with Google for visitors, or the
    signed-in person's photo and name with 💰 Rewards, then ☰. On phones: brand and ☰, account bar, then navigation."""
    with st.container(key="app_header"):
        brand, nav, account, menu = st.columns([1.1, 1.6, 1.2, .22], vertical_alignment="center")
        with brand, st.container(key="header_brand"):
            html('<div class="brand"><div class="brand-symbol" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 28 28" fill="none" '
                 'stroke="currentColor" stroke-width="1.4"><circle cx="14" cy="14" r="11"/>'
                 '<ellipse cx="14" cy="14" rx="5" ry="11"/><path d="M3 14h22M5 8h18M5 20h18"/></svg></div>'
                 '<div><div class="brand-name">World Explorer</div>'
                 f'<div class="brand-note">{e("For curious minds. Across every border.")}</div></div></div>')
        with nav, st.container(key="navigation"):
            for column, page in zip(st.columns(len(PAGES)), PAGES):
                column.button(t(page), key=f"nav_{page}", width="stretch",
                              type="primary" if st.session_state.page == page else "secondary",
                              on_click=navigate, args=(page,))
        with account, st.container(key="header_account", horizontal=True, vertical_alignment="center", gap="small"):
            _account_bar()
        with menu, st.container(key="header_menu"):
            # Shows a ☰ drawn by CSS; its accessible name is the (visually hidden) translated word "Settings".
            st.button(t("Settings"), key="settings_menu", help=t("Settings"), width="stretch", on_click=open_settings)
    # The flag is consumed here: the dialog survives its own reruns and closes on a full rerun.
    if st.session_state.pop("settings_open", False):
        _settings_dialog()


def _avatar_html(who: dict, name: str) -> str:
    """The uploaded profile photo, else the Google photo, else the first letter of the name."""
    photo = st.session_state.profile_photo
    if not photo:
        picture = str(who.get("picture") or "")
        photo = picture if picture.startswith("https://") else ""
    if photo:
        return (f'<img class="account-avatar" src="{escape(photo, quote=True)}" alt="" referrerpolicy="no-referrer">')
    initial = escape((name.strip()[:1] or "?").upper())
    return f'<span class="account-avatar account-initial" aria-hidden="true">{initial}</span>'


def _account_bar() -> None:
    who = accounts.identity()
    if not who:
        _header_sign_in()
        return
    name = (st.session_state.profile_name or str(who.get("name") or "")
            or str(who.get("email") or "").split("@")[0]).strip()
    html(f'<div class="account-chip">{_avatar_html(who, name)}<span class="account-name" title="{escape(name, quote=True)}">'
         f'{escape(name)}</span></div>')
    if rewards_hooks.visible():  # owners/testers while the programme is off; everyone signed in once it is on
        st.button("💰 " + t("Rewards"), key="rewards_menu", width="content",
                  type="primary" if st.session_state.page == "Rewards" else "secondary",
                  on_click=navigate, args=("Rewards",))


def _header_sign_in() -> None:
    """Visible Google sign-in for visitors (the existing sign-in; guest progress is kept as in Settings)."""
    ready = accounts.provider_ready("google")
    note = (t("Sign in to save your profile and progress across visits. You can always play as a guest.") if ready
            else t("Sign-in is not available right now. You can keep playing as a guest; progress lasts for this session."))
    if st.session_state.get("signin_ready") == "google" and accounts.guest_has_progress():
        cookie_script()
        if st.button("🔑 " + t("Continue to Google"), key="header_signin_go", type="primary", width="content",
                     disabled=not ready,
                     help=t("Your guest progress ({points} points) will be added to your account after you sign in. "
                            "An existing saved profile is never replaced.", points=f"{st.session_state.points:,}")):
            if not accounts.login("google"):
                st.toast(t("Sign-in could not start. You can keep playing as a guest."))
        return
    label = "🔑 " + t("Sign in with Google")
    if accounts.guest_has_progress():
        st.button(label, key="header_signin", type="primary", width="content", disabled=not ready, help=note,
                  on_click=_begin_sign_in, args=("google",))
    elif st.button(label, key="header_signin", type="primary", width="content", disabled=not ready, help=note):
        if not accounts.login("google"):
            st.toast(t("Sign-in could not start. You can keep playing as a guest."))


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


SIGN_IN_PROBLEMS = {
    "not_configured": "Sign-in has not been set up for this app yet.",
    "authlib_missing": "The sign-in component is not installed on the server.",
    "callback_path": "The sign-in callback address must end with /oauth2callback.",
    "not_https": "The sign-in callback address must use https:// (except on localhost).",
    "origin_mismatch": "The sign-in callback is configured for a different address than the one you are using.",
}


def _owner_help(diagnosis: dict) -> None:
    with st.expander(t("Sign-in help for the app owner")):
        if diagnosis["problem"]:
            st.write(t(SIGN_IN_PROBLEMS[diagnosis["problem"]]))
        if diagnosis["expected"]:
            st.write(t("Callback address for this app:"))
            st.code(diagnosis["expected"], language=None)
        if diagnosis["configured"] and diagnosis["configured"] != diagnosis["expected"]:
            st.write(t("Callback address currently configured:"))
            st.code(diagnosis["configured"], language=None)
        st.caption(t("If Google shows “Error 400: redirect_uri_mismatch”, the configured callback address is not "
                     "registered on the Google OAuth client. Add exactly the address above under Authorized redirect "
                     "URIs. This is fixed in Google Cloud and the app's secrets, not in the code. See LOGIN_SETUP.md."))


def _account_controls() -> None:
    who = accounts.identity()
    state = accounts.connection_state()
    if who:
        st.caption(f"{t('Signed in')} · {who.get('email') or who.get('name', '')}")
        if state == "loading_failed":
            st.warning(t("Your saved profile could not be reached. Nothing has been overwritten; it will be tried again shortly."))
            st.button(t("Try again now"), key="profile_retry", on_click=accounts.retry_now)
        elif state == "save_failed":
            st.warning(t("Your latest changes could not be saved online yet. They will be saved when the connection returns."))
        elif state == "no_storage":
            st.info(t("Online saving is not set up yet, so progress lasts for this session."))
        if st.button(t("Sign out"), key="profile_logout", width="stretch"):
            accounts.logout()
    else:
        google, email = accounts.auth_diagnosis("google"), accounts.auth_diagnosis("account")
        st.caption(t("Sign in to save your profile and progress across visits. You can always play as a guest."))
        for provider, label, diagnosis in (("google", "Continue with Google", google),
                                           ("account", "Email sign-in / Create account", email)):
            if diagnosis["problem"] == "not_configured" and provider == "account":
                continue  # optional provider: hide it entirely when not set up
            sign_in_button(provider, label, f"profile_{provider}", disabled=not diagnosis["ok"])
        if not google["ok"]:
            st.info(t("Sign-in is not available right now. You can keep playing as a guest; progress lasts for this session."))
        if google["problem"]:
            _owner_help(google)
    _photo_upload()
    if st.session_state.profile_photo:
        html(f'<img class="profile-preview" src="{escape(st.session_state.profile_photo, quote=True)}" alt="{e("Profile photo")}">')
        st.button(t("Remove photo"), key="profile_remove_photo", on_click=_remove_photo)


def cookie_script() -> None:
    """Apply queued cookie writes now (needed inside dialogs, which rerun on their own)."""
    script = cookies.script()
    if script:
        st.html(script, unsafe_allow_javascript=True)


def _begin_sign_in(provider: str) -> None:
    if accounts.guest_has_progress():
        accounts.prepare_handoff()  # keep the guest's progress for the account (two steps: the cookie must be set first)
    st.session_state.signin_ready = provider


def sign_in_button(provider: str, label: str, key: str, *, disabled: bool = False, primary: bool = False) -> None:
    """Sign-in that keeps guest progress. With progress: first click prepares the hand-off and explains it,
    the second ("Continue to Google") leaves for Google's page. Without progress: one click."""
    kind = "primary" if primary else "secondary"
    with st.container(key=key + "_box"):
        _sign_in_body(provider, label, key, disabled, kind)


def _sign_in_body(provider: str, label: str, key: str, disabled: bool, kind: str) -> None:
    if st.session_state.get("signin_ready") == provider and accounts.guest_has_progress():
        cookie_script()
        st.caption(t("Your guest progress ({points} points) will be added to your account after you sign in. "
                     "An existing saved profile is never replaced.", points=f"{st.session_state.points:,}"))
        if st.button(t("Continue to Google") if provider == "google" else t("Continue to sign-in"), key=key + "_go",
                     type="primary", width="stretch", disabled=disabled):
            if not accounts.login(provider):
                st.error(t("Sign-in could not start. You can keep playing as a guest."))
        return
    if accounts.guest_has_progress():
        st.button(t(label), key=key, disabled=disabled, width="stretch", type=kind, on_click=_begin_sign_in, args=(provider,))
    elif st.button(t(label), key=key, disabled=disabled, width="stretch", type=kind):
        if not accounts.login(provider):
            st.error(t("Sign-in could not start. You can keep playing as a guest."))


# --------------------------------------------------------------------------- usage statistics (pilot)

def consent_bar() -> None:
    """One compact question, shown until the visitor answers (only when the owner switched measurement on)."""
    if not analytics.needs_choice():
        return
    with st.container(key="consent_bar", horizontal=True, vertical_alignment="center"):
        html(f'<div class="consent-text"><b>{e("Help improve World Explorer?")}</b> '
             f'{e("Allow anonymous usage statistics for our pilot: visits and finished rounds, with a random id. No names, emails or answers. You can change this in Settings.")}</div>')
        with st.container(key="consent_actions", horizontal=True):
            st.button(t("Allow"), key="consent_allow", type="primary", on_click=analytics.grant)
            st.button(t("No thanks"), key="consent_deny", on_click=analytics.deny)


def _privacy_changed() -> None:
    analytics.grant() if st.session_state.privacy_statistics else analytics.deny()


def _privacy_controls() -> None:
    if not analytics.enabled():
        return
    st.subheader(t("Privacy"))
    gpc = analytics.gpc_active()
    # Always show the real choice: it can change in another tab (synchronised on every run) or by GPC.
    st.session_state.privacy_statistics = st.session_state.get("an_consent") == "granted" and not gpc
    st.toggle(t("Share anonymous usage statistics"), key="privacy_statistics", disabled=gpc, on_change=_privacy_changed)
    cookie_script()
    if gpc:
        st.caption(t("Your browser sends a Global Privacy Control signal, so usage statistics stay off and nothing is "
                     "recorded, even if you allowed them before."))
    st.caption(t("For our pilot we count visits, started and finished rounds and the days you play, with a random id "
                 "kept in this browser (or a one-way code of your account when signed in), plus device type and app "
                 "language. Never names, emails, answers, photos or location. Switching this off stops it at once in "
                 "every open tab of this browser and in your other signed-in sessions, and events not yet sent are "
                 "discarded."))
    if analytics.is_owner():
        if st.button("Owner dashboard", key="owner_dashboard_open", width="stretch"):
            navigate("Owner")
            st.rerun()


# --------------------------------------------------------------------------- feedback

FEEDBACK_PAGES = ("Explore", "Learn", "Quiz", "Badges", "Other")
DEVICES = {"phone": "Phone", "tablet": "Tablet", "desktop": "Computer"}


def _feedback_body() -> None:
    page = st.session_state.page if st.session_state.page in FEEDBACK_PAGES else "Other"
    st.caption(t("We will send only what you see here: the page, your device type, your description and, if you add "
                 "them, contact details — plus the app language and the time. No quiz history or account details."))
    with st.form("feedback_form", border=False):
        where = st.selectbox(t("Page"), FEEDBACK_PAGES, index=FEEDBACK_PAGES.index(page), format_func=t, key="feedback_page")
        devices = list(DEVICES)
        device = st.selectbox(t("Device"), devices, index=devices.index(st.session_state.get("an_device", "desktop")),
                              format_func=lambda d: t(DEVICES[d]), key="feedback_device")
        text = st.text_area(t("What happened, or what could be better?"), max_chars=2000, key="feedback_text")
        contact = st.text_input(t("Contact (optional)"), max_chars=120, key="feedback_contact",
                                help=t("Only if you would like a reply."))
        sent = st.form_submit_button(t("Send feedback"), type="primary", width="stretch")
    if sent:
        last = st.session_state.get("feedback_sent_at", 0.0)
        if not text.strip():
            st.warning(t("Please describe the problem or idea first."))
        elif time.time() - last < 30:
            st.info(t("Thank you — your feedback was already sent."))
        elif analytics.send_feedback(where, device, text, contact):
            st.session_state.feedback_sent_at = time.time()
            st.success(t("Thank you — your feedback was sent."))
        else:
            st.error(t("Feedback could not be sent right now. Your text is still here; please try again later."))


def feedback_button() -> None:
    if analytics.config().get("enabled") and accounts.storage_ready():
        if st.button(t("Send feedback"), key="feedback_open", type="tertiary"):
            st.dialog(t("Send feedback"), width="small")(_feedback_body)()


def _preview_sound() -> None:
    st.session_state.sound_preview_token = st.session_state.get("sound_preview_token", 0) + 1


def _sound_controls() -> tuple[bool, int]:
    st.subheader(t("Sound effects"))
    on = st.toggle(t("Sound effects"), value=st.session_state.sound_enabled, key="preferences_sound")
    volume = st.slider(t("Volume"), 0, 100, value=st.session_state.sound_volume, step=10, key="preferences_volume",
                       disabled=not on)
    st.button(t("Play preview"), key="sound_preview", disabled=not on or volume == 0, on_click=_preview_sound)
    if on and sound.play_preview(st.session_state.get("sound_preview_token", 0), volume):
        st.caption("🔔 " + t("Preview played. If you heard nothing, your browser or device may be blocking sound."))
    st.caption(t("Short, quiet tones for correct answers, incorrect answers and finished rounds. No music."))
    return on, volume


def _rewards_entry() -> None:
    if not rewards_hooks.visible():
        return
    if st.button("💰 " + t("Rewards"), key="settings_rewards", width="stretch"):
        navigate("Rewards")
        st.rerun()
    if analytics.is_owner() and not analytics.enabled():  # with analytics on, the owner button is under Privacy
        if st.button("Owner dashboard", key="owner_rewards_open", width="stretch"):
            navigate("Owner")
            st.rerun()


def _settings_body() -> None:
    st.subheader(t("Profile"))
    _account_controls()
    _rewards_entry()
    name = st.text_input(t("Display name"), value=st.session_state.profile_name, max_chars=40, key="preferences_name")
    lang = st.selectbox(t("App language"), LANGUAGES, index=LANGUAGES.index(st.session_state.app_language),
                        key="preferences_language")
    st.caption(t("Country names are translated; capitals, currencies and languages keep the dataset spelling."))
    st.divider()
    collection = st.selectbox(t("Places to include"), COLLECTIONS, index=COLLECTIONS.index(st.session_state.scope_collection),
                              format_func=formatter(COLLECTIONS), key="preferences_collection")
    modes = list(accounts.SCOPE_MODES)
    mode = st.selectbox(t("Exploration area"), modes, index=modes.index(st.session_state.scope_mode),
                        format_func=formatter(modes), key="preferences_mode")
    area, country_id = "World", "all"
    if mode == "One continent":
        current = st.session_state.scope_continent
        area = st.selectbox(t("Continent"), CONTINENTS, index=CONTINENTS.index(current) if current in CONTINENTS else 0,
                            format_func=formatter(CONTINENTS), key="preferences_continent")
    elif mode == "One country":
        ids = [c["id"] for c in get_countries(collection=collection)]
        current = st.session_state.scope_country
        country_id = st.selectbox(t("Country"), ids, index=ids.index(current) if current in ids else 0,
                                  format_func=country_formatter(), key="preferences_country")
        area = get_country(country_id)["continent"]
    st.caption(t("Area changes update Explore and Learn and the next quiz setup. Your current round is kept."))
    st.divider()
    sound_on, volume = _sound_controls()
    st.divider()
    _privacy_controls()
    if st.button(t("Apply settings"), key="apply_preferences", type="primary", width="stretch"):
        st.session_state.pending_preferences = {
            "profile_name": name.strip(), "app_language": lang, "scope_mode": mode, "scope_continent": area,
            "scope_country": country_id, "scope_collection": collection,
            "sound_enabled": bool(sound_on), "sound_volume": int(volume)}
        st.rerun()
    st.caption(t("Signed-in profiles save online when the account connection is ready. Guest profiles last for this session."))
    data_sources()


def _settings_dialog() -> None:
    st.dialog(t("Settings"), width="small")(_settings_body)()


# --------------------------------------------------------------------------- credits

def data_sources() -> None:
    with st.expander(t("Data sources and coverage")):
        st.markdown("Country data adapted from [mledoze/countries](https://github.com/mledoze/countries) "
                    "(commit c2ac004, 29 September 2026), licensed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). "
                    "The adapted database in `data/` is distributed under the same licence. Coverage is checked against the "
                    "[UN member state list](https://www.un.org/en/about-us/member-states) and the two "
                    "[UN observer states](https://www.un.org/en/about-us/non-member-states) (checked 8 October 2026).")
        st.markdown("Corrections and editorial decisions are documented in `data/reference/curation.json` and `COVERAGE.md`. "
                    "Missing or disputed facts skip only the question types that need them.")
        st.markdown("Flags are SVG files from the same repository, resized for the app. Flags are not covered by the ODbL; "
                    "see [Wikipedia: copyright on emblems](https://en.wikipedia.org/wiki/Wikipedia:Copyright_on_emblems).")
        st.markdown("Map outlines: [Natural Earth](https://www.naturalearthdata.com/) 1:50m Admin 0 – Countries (public domain), "
                    "simplified and coloured by the continents in the country data (`assets/world_map.json`, built by "
                    "`tools/build_world_map.py`).")
        st.markdown("Landmarks: [UNESCO World Heritage List](https://whc.unesco.org/en/list/) (single-country sites only). "
                    "Head-of-state questions use dated, sourced records only; records older than 30 days are excluded "
                    "until verified again.")


def photo_credits() -> None:
    with st.expander(t("Photography credits")):
        st.caption(t("Photography loads online."))
        for p in PHOTOS.values():
            st.markdown(f"[{p['caption']}]({p['page']}) — {p['author']} · [{p['license']}]({p['license_url']}). "
                        "Cropped for layout; the original is unchanged.")
