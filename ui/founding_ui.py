"""🌟 World Explorer Founding 50 — the player's part of 💰 My Rewards (Option B: anyone can apply, only the Owner
approves). World Explorer and its geography features stay free for everyone; applying is optional.

Only approved participants can earn money. The database enforces that again (supabase/founding50_migration.sql):
one application per person, owner-only decisions, no enrolment and no paid activity without approval, and the 30-day
withdrawal wait counted from the first official enrolment after approval. Nothing here can approve anybody.
"""
from __future__ import annotations

import streamlit as st

from core import founding
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .components import html
from .state import t

TEST_LABEL = "🧪 Test application — not payable"
APPLY_ERRORS = {
    "already_applied": "You have already applied. Each person can apply once.",
    "programme_off": "Applications are closed at the moment. Please try again later.",
    "declarations_required": "Please confirm all three statements to apply.",
    "state_required": "Please choose your state of residence.",
    "note_too_long": "Please keep your message under 300 characters.",
    "suspended": "Your participation is on hold. Please use “Send feedback” if you think this is a mistake.",
}
STATUS_TEXT = {
    "pending": ("info", "Your application was received on {date} and is waiting for review."),
    "waitlist": ("info", "You are on the Founding 50 waiting list. This page will show it when a place is offered "
                         "to you."),
    "rejected": ("warning", "Your application was not accepted this time. You can keep using all of World Explorer "
                            "for free."),
    "approved": ("success", "Your Founding 50 application was approved!"),
}


def _places(s) -> tuple[int, int]:
    """(places available, places in total) — real approvals only."""
    total = int(s.settings().max_places)
    try:
        taken = sum(1 for a in s.founding_applications("approved") if not a.get("test"))
    except Exception:
        taken = 0
    return max(total - taken, 0), total


def _intro(s) -> None:
    left, total = _places(s)
    st.subheader("🌟 " + t("World Explorer Founding 50"))
    st.markdown(t("We are welcoming {n} founding participants in Nigeria who explore countries, complete quizzes and "
                  "earn rewards. Anyone can apply; the World Explorer team reviews every application.", n=total))
    st.caption(t("World Explorer stays free for everyone. Maps, countries, quizzes and badges never need an "
                 "application."))
    html(f'<div class="rw-stats"><div class="rw-stat"><div class="rw-stat-value">{left} / {total}</div>'
         f'<div class="rw-stat-label">{t("Places available")}</div></div></div>')


def _apply_form(s, who: dict, account: dict) -> None:
    from .rewards_page import TERMS, _naira   # the programme rules shown when joining (one text)
    settings = s.settings()
    with st.expander("📜 " + t("Programme rules")):
        st.caption(t("The programme rules are available in English."))
        from core import rewards
        st.markdown(TERMS.format(version=rewards.TERMS_VERSION, cap=_naira(settings.monthly_cap)))
    with st.form("rw_founding_apply", border=True):
        st.markdown("**" + t("Apply for the Founding 50") + "**")
        state = st.selectbox(t("State of residence"), founding.STATES, index=None,
                             placeholder=t("Choose your state"), key="rw_f_state")
        note = st.text_area(t("Why would you like to join? (optional)"), max_chars=founding.NOTE_MAX,
                            key="rw_f_note", height=90)
        adult = st.checkbox(t("I am 18 years or older."), key="rw_f_adult")
        resident = st.checkbox(t("I live in Nigeria."), key="rw_f_resident")
        terms = st.checkbox(t("I have read and accept the programme rules."), key="rw_f_terms")
        st.caption(t("Applying does not guarantee a place. Only approved participants earn rewards. We do not ask for "
                     "bank details here."))
        submitted = st.form_submit_button(t("Apply for the Founding 50"), type="primary", width="stretch")
    if not submitted:
        return
    if not (adult and resident and terms):
        st.error(t(APPLY_ERRORS["declarations_required"]))
        return
    if not state:
        st.error(t(APPLY_ERRORS["state_required"]))
        return
    try:
        s.apply_founding(who["profile_id"], state, note, adult, resident, terms)
    except StoreError as error:
        key = next((k for k in APPLY_ERRORS if k in str(error)), None)
        st.error(t(APPLY_ERRORS[key]) if key else t("Your application could not be sent. Please try again."))
        return
    except Exception:
        st.error(t("Your application could not be sent. Please try again."))
        return
    st.session_state.rw_flash = (t("Thank you! Your Founding 50 application was sent. The World Explorer team will review it."),
                                 "success")
    st.rerun()


def _status(application: dict, member: bool) -> None:
    kind, text = STATUS_TEXT[application["status"]]
    getattr(st, kind)(t(text, date=str(application.get("applied_at") or "")[:10]),
                      icon={"success": "✅", "warning": "ℹ️", "info": "⏳"}[kind])
    if application["status"] == "approved" and not member:
        st.caption(t("Confirm your declarations below to take your place. Your 30-day withdrawal waiting period "
                     "starts when you take your place."))


def section(s, who: dict, account: dict) -> bool:
    """Render the Founding 50 card. Returns True when this person may join / take part (approved, or a test
    account), False when the join form must stay hidden."""
    test = bool(account.get("test"))
    member = account.get("membership") == "member"
    application = s.founding_application(who["profile_id"])
    approved = founding.approved(application, account)
    if approved and not test and member:
        return True                         # an approved participant: the normal rewards page, nothing extra
    with st.container(border=True, key="rw_founding"):
        if test:
            html(f'<div class="rw-test-label">{t(TEST_LABEL)}</div>')
        _intro(s)
        if application:
            _status(application, member)
        else:
            _apply_form(s, who, account)
        if member and not approved:
            st.caption(t("Your activity is recorded, but it earns rewards only after your Founding 50 application is "
                         "approved."))
    return approved


def unavailable() -> None:
    """Real players while supabase/founding50_migration.sql is not installed: no joining (fail safe)."""
    with st.container(border=True, key="rw_founding"):
        st.subheader("🌟 " + t("World Explorer Founding 50"))
        st.info(t("Applications for the Founding 50 open soon. You can keep using all of World Explorer for free."))
