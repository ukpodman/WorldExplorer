"""World Explorer — learn about countries and take a reusable geography challenge.

Run with:  streamlit run app.py

Layout:
  core/     pure logic (data, translations, quiz engine) + account storage
  ui/       Streamlit state, components, pages and sound
  data/     country, political, photo and translation data (JSON) + reference lists
  assets/   styles.css and flag images
  tools/    scripts that rebuild the bundled data (not used at runtime)
"""
import streamlit as st

st.set_page_config(page_title="World Explorer", page_icon="🌍", layout="wide")


def _load_fresh_code() -> None:
    """After a deploy, make sure this run uses the new ui/ and core/ code.

    Streamlit keeps imported modules in memory and only drops them when its file watcher notices a change. On a
    hosted app that does not always happen when the new code is pulled, so the server kept running old Python
    while styles.css (read from disk) was already new, producing a broken mix. Here every run compares the
    project's .py files on disk with the ones loaded; if any changed, the project modules are dropped from memory
    so the imports below load the current code."""
    import pathlib
    import sys
    root = pathlib.Path(__file__).resolve().parent
    stamp = tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                         for folder in ("ui", "core") for p in (root / folder).glob("*.py")))
    previous = getattr(sys, "_world_explorer_code_stamp", None)
    if previous is not None and previous != stamp:
        for name, module in list(sys.modules.items()):
            path = getattr(module, "__file__", None) or ""
            if (name in ("ui", "core") or name.startswith(("ui.", "core."))) and path.startswith(str(root)):
                sys.modules.pop(name, None)
    sys._world_explorer_code_stamp = stamp


_load_fresh_code()

from core import accounts, analytics, cookies  # noqa: E402  (set_page_config must run first)
from core.data import COUNTRIES  # noqa: E402
from ui import rewards_hooks, state  # noqa: E402
from ui.components import consent_bar, feedback_button, header, inject_styles  # noqa: E402
from ui.pages import ROUTES  # noqa: E402

FOOTER = {
    "guest": "Progress lasts for this browser session",
    "no_storage": "Signed in · progress lasts for this browser session",
    "loading_failed": "Saved profile not reachable yet · nothing has been overwritten",
    "save_failed": "Latest changes not saved online yet",
    "saved": "Saved to your account",
}


def main() -> None:
    state.init()
    analytics.init_session()
    rewards_hooks.capture_referral()  # keeps a ?ref= invitation through Google sign-in
    accounts.restore_profile()
    rewards_hooks.after_sign_in()  # once per session; does nothing while the programme is off
    analytics.log_visit()  # once per session; only with the visitor's permission
    state.apply_pending_preferences()
    inject_styles()
    header()
    consent_bar()
    notice = st.session_state.pop("handoff_notice", None)
    if notice:  # shown once after "Save your progress with Google"
        st.success(state.t("Your guest progress was added to your account: +{points} points.",
                           points=f"{notice['points']:,}") if notice["existing"]
                   else state.t("Your progress is now saved to your account."), icon="✅")
    page = st.session_state.page if st.session_state.page in ROUTES else "Explore"
    with st.container(key=f"view_{page.lower()}"):
        ROUTES[page]()
    st.divider()
    accounts.save_profile()
    accounts.refresh_handoff()
    with st.container(key="app_footer", horizontal=True, vertical_alignment="center"):
        st.caption(f"{state.t('{n} places', n=len(COUNTRIES))} · {state.t(FOOTER[accounts.connection_state()])}.")
        feedback_button()
    script = cookies.script()
    if script:
        st.html(script, unsafe_allow_javascript=True)


main()
