"""World Explorer — learn about countries and take a reusable geography challenge.

Run with:  streamlit run app.py

Layout:
  core/     pure logic (data, translations, quiz engine) + account storage
  ui/       Streamlit state, components and pages
  data/     country, political, photo and translation data (JSON)
  assets/   styles.css
"""
import streamlit as st

st.set_page_config(page_title="World Explorer", page_icon="🌍", layout="wide")

from core import accounts  # noqa: E402  (set_page_config must run first)
from core.data import COUNTRIES  # noqa: E402
from ui import state  # noqa: E402
from ui.components import header, inject_styles  # noqa: E402
from ui.pages import ROUTES  # noqa: E402


def main() -> None:
    state.init()
    accounts.restore_profile()
    state.apply_pending_preferences()
    inject_styles()
    header()
    page = st.session_state.page if st.session_state.page in ROUTES else "Explore"
    with st.container(key=f"view_{page.lower()}"):
        ROUTES[page]()
    st.divider()
    accounts.save_profile()
    persistence = "Saved to your account" if accounts.is_saved_online() else "Progress lasts for this browser session"
    st.caption(f"{state.t('{n} countries', n=len(COUNTRIES))} · {state.t(persistence)}.")


main()
