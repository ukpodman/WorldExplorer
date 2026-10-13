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
