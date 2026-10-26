"""The participant's application card. Internally the programme is "Funding 50" (tables and code keep the earlier
"founding" names); participants see:
  * while the public rewards programme is OFF (now): "World Explorer — Friends & Family 10", the published pilot terms
    (legal/PILOT_TERMS.md, the exact approved version is recorded with the application) and no money language;
  * once public rewards are separately authorised and ON (later): the earlier Founding 50 rewards texts.
World Explorer and its geography features stay free for everyone; applying is optional.

Only approved participants can earn money. The database enforces that again (supabase/founding50_migration.sql):
one application per person, owner-only decisions, no enrolment and no paid activity without approval, and the 30-day
withdrawal wait counted from the first official enrolment after approval. Nothing here can approve anybody.
"""
from __future__ import annotations

import streamlit as st

from core import founding, legal, rewards
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .components import html
from .state import t

TEST_LABEL = "🧪 Test application — not payable"
APPLY_ERRORS = {
    "already_applied": "You have already applied. Each person can apply once.",
    "programme_off": "Applications are closed at the moment. Please try again later.",
    "not_invited": "Friends & Family 10 is by invitation only. You can keep using all of World Explorer for free.",
    "terms_outdated": "The pilot terms have been updated. Please read the current terms and apply again.",
    "terms_required": "Applications are closed at the moment. Please try again later.",
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


PILOT_STATUS_TEXT = {
    "pending": ("info", "Your application to Friends & Family 10 was received on {date} and is waiting for review."),
    "waitlist": ("info", "You are on the Friends & Family 10 waiting list. This page will show it when a place is "
                         "offered to you."),
    "rejected": ("warning", "Your application was not accepted this time. You can keep using all of World Explorer "
                            "for free."),
    "approved": ("success", "Welcome to Friends & Family 10! Your application was approved."),
}


def pilot_mode() -> bool:
    """Participants see the Friends & Family 10 (not the rewards programme) while public rewards are not ON."""
    return not hooks.enabled()


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


def _pilot_intro(s) -> None:
    total = legal.PILOT_MAX_PLACES
    try:
        left = max(total - sum(1 for a in s.founding_applications("approved") if not a.get("test")), 0)
    except Exception:
        left = total
    st.subheader(t("World Explorer — Friends & Family 10"))
    st.markdown(t("An invitation-only programme for up to {n} adults in Nigeria. You help us test World Explorer "
                  "before a wider launch; the World Explorer team reviews every application.", n=total))
    st.caption(t("Approved participants earn cash rewards for verified learning: up to ₦500 a day and ₦7,000 a month, "
                 "from a shared ₦50,000 monthly budget. Daily amounts are provisional; after each month, approved final "
                 "allocations are paid in naira by bank transfer."))
    st.caption(t("Educational points and badges have no monetary value."))
    html(f'<div class="rw-stats"><div class="rw-stat"><div class="rw-stat-value">{left} / {total}</div>'
         f'<div class="rw-stat-label">{t("Places available")}</div></div></div>')


def _pilot_apply_form(s, who: dict, account: dict) -> None:
    """The application with the published Friends & Family 10 terms; the exact version shown is the version the
    applicant accepts, and the database checks it against the owner's approved version."""
    terms_id = legal.pilot_terms_id()
    from . import ff10_ui
    ff10_ui.documents()          # the approved agreement and privacy notice, with the approval record
    with st.form("rw_founding_apply", border=True):
        st.markdown("**" + t("Apply to Friends & Family 10") + "**")
        state = st.selectbox(t("State of residence"), founding.STATES, index=None,
                             placeholder=t("Choose your state"), key="rw_f_state")
        note = st.text_area(t("Why would you like to take part? (optional)"), max_chars=founding.NOTE_MAX,
                            key="rw_f_note", height=90)
        adult = st.checkbox(t("I am 18 years or older."), key="rw_f_adult")
        resident = st.checkbox(t("I live in Nigeria."), key="rw_f_resident")
        terms = st.checkbox(t("I have read and accept the Friends & Family 10 terms."), key="rw_f_terms")
        st.caption(t("Applying does not guarantee a place. We do not ask for bank details."))
        submitted = st.form_submit_button(t("Apply to Friends & Family 10"), type="primary", width="stretch")
    if submitted:
        _submit(s, who, state, note, adult, resident, terms, terms_id,
                t("Thank you! Your application to Friends & Family 10 was sent. The World Explorer team will "
                  "review it."))


def _submit(s, who: dict, state, note, adult: bool, resident: bool, terms: bool, terms_version: str,
            thanks: str) -> None:
    if not (adult and resident and terms):
        st.error(t(APPLY_ERRORS["declarations_required"]))
        return
    if not state:
        st.error(t(APPLY_ERRORS["state_required"]))
        return
    try:
        s.apply_founding(who["profile_id"], state, note, adult, resident, terms, terms_version=terms_version)
    except StoreError as error:
        key = next((k for k in APPLY_ERRORS if k in str(error)), None)
        st.error(t(APPLY_ERRORS[key]) if key else t("Your application could not be sent. Please try again."))
        return
    except Exception:
        st.error(t("Your application could not be sent. Please try again."))
        return
    st.session_state.rw_flash = (thanks, "success")
    st.rerun()


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
    if submitted:
        _submit(s, who, state, note, adult, resident, terms, rewards.TERMS_VERSION,
                t("Thank you! Your Founding 50 application was sent. The World Explorer team will review it."))


def _status(application: dict, member: bool) -> None:
    kind, text = (PILOT_STATUS_TEXT if pilot_mode() else STATUS_TEXT)[application["status"]]
    getattr(st, kind)(t(text, date=str(application.get("applied_at") or "")[:10]),
                      icon={"success": "✅", "warning": "ℹ️", "info": "⏳"}[kind])
    if application["status"] == "approved" and not member and not pilot_mode():
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
        pilot = pilot_mode()
        if test:
            html(f'<div class="rw-test-label">{t(TEST_LABEL)}</div>')
        _pilot_intro(s) if pilot else _intro(s)
        if application:
            _status(application, member)
        elif not (test or hooks.may_apply()):   # invitation only (the database refuses it as well)
            st.info(t(APPLY_ERRORS["not_invited"]))
        elif pilot and not hooks.pilot_terms_current():
            st.info(t(APPLY_ERRORS["terms_required"]))   # the approved terms are not recorded yet (owner)
        elif pilot:
            _pilot_apply_form(s, who, account)
        else:
            _apply_form(s, who, account)
        if member and not approved and not pilot:
            st.caption(t("Your activity is recorded, but it earns rewards only after your Founding 50 application is "
                         "approved."))
    return approved


def unavailable() -> None:
    """Real players while supabase/founding50_migration.sql is not installed: no joining (fail safe)."""
    with st.container(border=True, key="rw_founding"):
        st.subheader("🌟 " + t("World Explorer Founding 50"))
        st.info(t("Applications for the Founding 50 open soon. You can keep using all of World Explorer for free."))
