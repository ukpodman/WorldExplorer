"""Applications tab of 💰 Rewards & Referral Management in the Owner dashboard (English only).

While Public Rewards is OFF it is the private 🤝 Friends & Family 10: invitation only, so only people the Owner has
invited can apply, and only participants the Owner approves take part (at most 50). When Public Rewards is ON it is the
🌟 Founding 50 programme (still invitation only unless the Owner separately allows public applications). The database
tables and functions keep their founding50 names. Access: rendered only after analytics.is_owner() on the server;
every decision is checked again by the database (reward_founding_decide: owner list, place limit, reason rules, audit
log). Approving never enrols anybody and never moves money; the participant takes their place themselves, and the
30-day withdrawal wait starts then.
"""
from __future__ import annotations

import time
from html import escape

import streamlit as st

from core import analytics, founding, rewards, withdrawals
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .owner_rewards import _actor, _download, _naira, _short, _table, _tiles

DATA_TTL = 30
NOTIFY_SECONDS = 30
FILTERS = ("pending", "approved", "waitlist", "rejected", "all")
ERRORS = {
    "not_owner": "Your email is not listed in reward_cashout_settings.owner_emails in the database. Add it with the "
                 "SQL in WITHDRAWALS_SETUP.md (step 3).",
    "places_full": "All places are taken. Place the application on the waiting list, or first move an "
                   "approved participant off.",
    "reason_required": "Please give a reason. A reason is needed to reject, and to take a place away from an approved "
                       "participant.",
    "no_change": "The application already has that status.",
    "note_too_long": "Please keep the note under 500 characters.",
    "unknown_application": "This application no longer exists. Press Refresh.",
    "invalid_action": "That action is not possible.",
    "invalid_email": "Please enter a valid email address (the Google address the person signs in with).",
    "not_invited": "That address is not on the invitation list.",
    "confirmation_required": "Please tick the confirmation first.",
    "terms_required": "Record the approved terms first: the pilot terms before switching the pilot on, the public "
                      "programme rules before allowing public applications.",
}
ACTION_LABEL = {"approve": "✅ Approve", "waitlist": "⏳ Waiting list", "reject": "✖ Reject"}


def pilot_mode() -> bool:
    """Public Rewards is OFF: the private Friends & Family 10 is the only programme people can join."""
    return not hooks.enabled()


def places(settings) -> int:
    """Approved places: 10 in the private Friends & Family 10, the max_places setting for the public programme."""
    from core import legal
    return legal.PILOT_MAX_PLACES if pilot_mode() else int(settings.max_places)


def programme_name() -> str:
    return "Friends & Family 10" if pilot_mode() else "Founding 50"


def activation_blockers(status: dict) -> list[str]:
    """Exactly why the pilot cannot be switched on yet (empty list = it may be switched on). The legal requirements
    come from core/legal.py and are never filled in or skipped here; the recorded terms come from the database."""
    from core import legal
    out = legal.pilot_activation_problems()
    current, recorded = legal.pilot_terms_id(), status.get("terms_version")
    if recorded != current:
        if not recorded:
            out.append("The pilot terms applicants must accept are not recorded yet (press \"Record the published pilot "
                       "terms\" once they are published).")
        else:
            out.append(f"The recorded pilot terms ({recorded}) are not the published pilot terms ({current}); record "
                       "them again once the published version is approved.")
    return out


def _error(error: Exception) -> str:
    text = str(error)
    return next((message for key, message in ERRORS.items() if key in text), text)


def _invalidate() -> None:
    st.session_state.pop("rw_f_data", None)
    st.session_state.pop("rw_owner_data", None)


def _load(s) -> dict:
    cached = st.session_state.get("rw_f_data")
    if cached and time.time() - cached["at"] < DATA_TTL:
        return cached
    data = {"at": time.time(), "settings": s.settings(), "applications": s.founding_applications(),
            "accounts": s.accounts(), "enrolments": s.enrolments(), "events": s.events(), "referrals": s.referrals()}
    st.session_state.rw_f_data = data
    return data


def _names(d: dict) -> dict:
    return {a["profile_id"]: a for a in d["accounts"]}


def _who(account: dict | None, pid: str) -> str:
    account = account or {}
    return account.get("display_name") or account.get("email") or _short(pid)


def _verified(d: dict, rows: list[dict], month: str) -> dict[str, int]:
    """Net verified earnings from completed months (no referral awaiting review), per person."""
    out = {}
    for a in rows:
        months = withdrawals.month_earnings(a["profile_id"], bool(a.get("test")), d["events"], d["referrals"])
        out[a["profile_id"]] = sum(m["net"] for k, m in months.items() if k < month and m["awaiting"] == 0)
    return out


def unseen_count() -> int:
    return hooks.founding_unseen()


@st.fragment(run_every=NOTIFY_SECONDS)
def alert() -> None:
    """The line at the top of the Owner dashboard (in-app notification); refreshes itself every NOTIFY_SECONDS."""
    new = unseen_count()
    seen = st.session_state.get("rw_f_alert_seen")
    if seen is not None and new > seen:
        st.toast(f"{new - seen} new {programme_name()} application(s)", icon="🔔")
        _invalidate()
    st.session_state.rw_f_alert_seen = new
    if new:
        st.info(f"{new} new {programme_name()} application{'s' if new != 1 else ''} — open 💰 Rewards & Referral "
                f"Management → {programme_name()} to review.", icon="🔔")


def _dashboard(d: dict, include_test: bool, month: str) -> list[dict]:
    rows = [a for a in d["applications"] if include_test or not a.get("test")]
    pick = (lambda xs: xs) if include_test else (lambda xs: [x for x in xs if not x.get("test")])
    f = founding.dashboard(rows, pick(d["enrolments"]), pick(d["events"]), places(d["settings"]), month,
                           _verified(d, rows, month))
    if pilot_mode():   # Friends & Family 10: the old rewards ledger is not used (provisional rewards: own tab)
        _tiles([("Places available", f"{f['available']} / {f['places']}", "approved participants at a time"),
                ("Approved participants", str(f["approved"])), ("Pending", str(f["pending"]), f"{f['unseen']} new"),
                ("Waiting list", str(f["waitlist"])), ("Rejected", str(f["rejected"])),
                ("Applications", str(f["total"]))])
        st.caption("Learning time, provisional rewards, the ₦50,000 budget and the monthly settlement are in the "
                   "📊 F&F 10 rewards tab.")
        if include_test:
            st.caption("Test applications are included — they are simulations and never payable.")
        return rows
    _tiles([("Places available", f"{f['available']} / {f['places']}", "approved participants at a time"),
            ("Approved participants", str(f["approved"])), ("Pending", str(f["pending"]), f"{f['unseen']} new"),
            ("Waiting list", str(f["waitlist"])), ("Rejected", str(f["rejected"])),
            ("Applications", str(f["total"])),
            ("Taking part this month", str(f["enrolled"]), "approved and enrolled"),
            ("Active this month", str(f["active"]), "approved, with activity"),
            ("Earned this month", _naira(f["earned_month"]), "approved participants"),
            ("Verified earnings", _naira(f["verified"]), "net, completed months")])
    st.caption(f"Budget and limits are unchanged: {_naira(d['settings'].monthly_budget)} per month, "
               f"{d['settings'].max_places} places, at most {_naira(d['settings'].monthly_cap)} per participant per "
               "month. Only approved participants can earn; real payouts and withdrawals keep their own switches.")
    if include_test:
        st.caption("Test applications are included — they are simulations and never payable.")
    return rows


def _new_list(s, rows: list[dict], names: dict) -> None:
    new = [a for a in rows if not a.get("seen_at")]
    st.markdown(f"#### 🔔 New applications ({len(new)})")
    if not new:
        st.caption("No new applications. New ones appear here and at the top of the dashboard.")
        return
    for a in new[:10]:
        with st.container(border=True, key=f"rw_f_new_{a['id']}"):
            if a.get("test"):
                st.html(f'<div class="rw-test-label">🧪 TEST APPLICATION — NOT PAYABLE</div>')
            st.markdown(f"**🔔 NEW {programme_name().upper()} APPLICATION** · {escape(_who(names.get(a['profile_id']), a['profile_id']))}"
                        f" · {escape(a.get('state') or '')} · {str(a.get('applied_at') or '')[:10]}")
            if st.button("Review application", key=f"rw_f_open_{a['id']}", type="primary"):
                st.session_state.rw_f_pick = a["id"]
                st.session_state.rw_f_filter = "all"
                s.mark_founding_seen(_actor(), a["id"])
                _invalidate()
                st.rerun()
    if len(new) > 1 and st.button("Mark all as seen", key="rw_f_seen_all"):
        s.mark_founding_seen(_actor())
        _invalidate()
        st.rerun()


def _row(a: dict, names: dict) -> dict:
    account = names.get(a["profile_id"]) or {}
    return {"ID": a["id"], "Applicant": _who(account, a["profile_id"]), "E-mail": account.get("email") or "",
            "State": a.get("state") or "", "Applied": str(a.get("applied_at") or "")[:10],
            "Status": founding.STATUS_LABELS[a["status"]], "Decided": str(a.get("decided_at") or "")[:10],
            "Decided by": a.get("decided_by") or "", "New": "yes" if not a.get("seen_at") else "",
            "Test": "TEST — not payable" if a.get("test") else ""}


def _table_section(rows: list[dict], names: dict) -> list[dict]:
    c = founding.counts(rows)
    labels = {"pending": f"Pending ({c['pending']})", "approved": f"Approved ({c['approved']})",
              "waitlist": f"Waiting List ({c['waitlist']})", "rejected": f"Rejected ({c['rejected']})",
              "all": f"All ({c['total']})"}
    if st.session_state.get("rw_f_filter") not in FILTERS:
        st.session_state.rw_f_filter = "pending"
    choice = st.segmented_control("Show", FILTERS, format_func=labels.get, key="rw_f_filter") or "pending"
    shown = founding.waitlist_order(rows) if choice == "waitlist" else \
        [a for a in rows if choice == "all" or a["status"] == choice]
    if choice == "waitlist" and shown:
        st.caption("Waiting list in the order applications were placed on it.")
    _table([_row(a, names) for a in shown], "No applications here.")
    _download("Download applications (CSV)", [_row(a, names) for a in rows], "founding50-applications", "rw_f_csv")
    return shown


def _details(a: dict, d: dict, names: dict, month: str) -> None:
    account = names.get(a["profile_id"]) or {}
    totals = rewards.activity_totals([e for e in d["events"] if e["profile_id"] == a["profile_id"]])
    referral = next((r for r in d["referrals"] if r.get("referred_id") == a["profile_id"]), None)
    verified = _verified(d, [a], month)[a["profile_id"]]
    items = (("Applicant", _who(account, a["profile_id"])), ("E-mail", account.get("email") or "—"),
             ("Profile", _short(a["profile_id"])), ("State of residence", a.get("state") or ""),
             ("Applied", str(a.get("applied_at") or "")[:16].replace("T", " ")),
             ("Status", founding.STATUS_LABELS[a["status"]]),
             ("Declarations", "18+ and living in Nigeria confirmed; rules accepted (" + str(a.get("terms_version")) + ")"),
             ("Account created", str(account.get("created_at") or "")[:10] or "—"),
             ("Programme membership", account.get("membership") or "none"),
             ("Activity so far", f"{totals.get('quizzes', 0)} quizzes, {totals.get('countries', 0)} countries, "
                                 f"{totals.get('active_days', 0)} active days"),
             ("Invited by a friend", "yes" if referral else "no"),
             ("Verified earnings", _naira(verified)),
             ("First approved", str(a.get("first_approved_at") or "")[:10] or "—"),
             ("Last decision", (f"{founding.STATUS_LABELS[a['status']]} by {a.get('decided_by')} on "
                                f"{str(a.get('decided_at'))[:10]}") if a.get("decided_at") else "—"),
             ("Decision note", a.get("decision_note") or "—"))
    st.html('<dl class="rw-cash-dl">' + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in items)
            + "</dl>")
    if a.get("note"):
        st.markdown("**Message from the applicant**")
        st.text(a["note"])


def _review(s, d: dict, rows: list[dict], names: dict, month: str) -> None:
    st.markdown("#### Review an application")
    if not rows:
        st.caption("Nothing to review in this list.")
        return
    ids = [a["id"] for a in rows]
    if st.session_state.get("rw_f_pick") not in ids:
        st.session_state.rw_f_pick = ids[0]
    by_id = {a["id"]: a for a in rows}
    pick = st.selectbox("Application", ids, key="rw_f_pick", format_func=lambda i: (
        f"#{i} · {_who(names.get(by_id[i]['profile_id']), by_id[i]['profile_id'])} · "
        f"{founding.STATUS_LABELS[by_id[i]['status']]}" + (" · TEST" if by_id[i].get("test") else "")))
    a = by_id[pick]
    if not a.get("seen_at"):                     # opening an application clears its notification
        try:
            s.mark_founding_seen(_actor(), a["id"])
            a["seen_at"] = "now"
        except Exception:
            pass
    with st.container(border=True, key="rw_f_review"):
        if a.get("test"):
            st.html('<div class="rw-test-label">🧪 TEST APPLICATION — NOT PAYABLE</div>')
        _details(a, d, names, month)
        taken = sum(1 for x in d["applications"] if x["status"] == "approved" and not x.get("test"))
        full = taken >= places(d["settings"]) and not a.get("test")
        if a["status"] == "approved":
            st.warning("Taking a place away ends this participant's enrolment for this month (the place and budget are "
                       "freed). Waiting list: rewards already earned stay payable. Reject: they are no longer "
                       "payable. A reason is required.")
        note = st.text_input("Note / reason (required to reject or to remove an approved participant)",
                             key=f"rw_f_note_{a['id']}", max_chars=founding.DECISION_NOTE_MAX)
        columns = st.columns(3)
        for column, action in zip(columns, ("approve", "waitlist", "reject")):
            disabled = founding.ACTIONS[action] == a["status"] or (action == "approve" and full)
            if column.button(ACTION_LABEL[action], key=f"rw_f_{action}_{a['id']}", disabled=disabled,
                             type="primary" if action == "approve" else "secondary", width="stretch"):
                _decide(s, a, action, note)
        if full and a["status"] != "approved":
            st.caption(f"All {places(d['settings'])} places are taken — approve is unavailable. Use the waiting "
                       "list.")
        if pilot_mode():
            st.caption("Approving lets the participant collect provisional Friends & Family 10 rewards for genuine "
                       "learning. They are settled monthly within the ₦50,000 budget, need your approval, and are not "
                       "payable: payments are disabled. No money moves.")
        else:
            st.caption("Approving does not enrol anybody and moves no money: the participant takes their place on "
                       "💰 My Rewards, and their 30-day withdrawal waiting period starts then.")


def _decide(s, a: dict, action: str, note: str | None) -> None:
    if not analytics.is_owner():
        st.error("Only the Owner can decide applications.")
        return
    clean = (note or "").strip()
    if (action == "reject" or a["status"] == "approved") and not clean:
        st.error(ERRORS["reason_required"])
        return
    try:
        row = s.decide_founding(a["id"], action, _actor(), clean or None)
    except StoreError as error:
        st.error(_error(error))
        return
    except Exception:
        st.error("The decision could not be saved. Please try again; nothing was changed.")
        return
    _invalidate()
    st.session_state.rw_f_flash = f"Application #{row['id']} is now {founding.STATUS_LABELS[row['status']]}."
    st.rerun()


def render(include_test: bool) -> None:
    if not analytics.is_owner():
        st.info("This page is not available.")
        return
    health = hooks.founding_health()
    if health != "ok":
        st.warning("Founding 50 is not installed in the database yet. Run supabase/founding50_migration.sql in "
                   "Supabase (FOUNDING50_SETUP.md) after your approval. Until then real players cannot apply or join; "
                   "everybody can still use World Explorer for free." if health == "missing_tables" else
                   "The Founding 50 applications could not be read just now. Players are not affected.")
        return
    s = hooks.founding_store(for_tester=True)
    flash = st.session_state.pop("rw_f_flash", None)
    if flash:
        st.success(flash)
    try:
        d = _load(s)
    except Exception:
        st.error("The Founding 50 applications could not be read just now. Players are not affected.")
        return
    month = rewards.month_key()
    status = s.pilot_status()
    if pilot_mode():
        st.markdown("### 🤝 Friends & Family 10 — Applications")
        st.caption("Private programme, by invitation only. Only people you have invited can apply, and only "
                   f"participants you approve take part (at most {places(d['settings'])}). Everyone else keeps full, "
                   "free educational access. No payments are available during the pilot.")
    else:
        st.markdown("### 🌟 Founding 50 Applications")
        if not status.get("installed") or not status.get("invitation_only", True):
            st.caption("Anyone signed in can apply; only you approve. Only approved participants can earn money — the "
                       "database refuses enrolment and pays ₦0 for everyone else.")
        else:
            st.caption("Invitation only: only people you have invited can apply, and only you approve. Only approved "
                       "participants can earn money — the database refuses enrolment and pays ₦0 for everyone else.")
    _pilot_controls(s, d)
    st.divider()
    names = _names(d)
    rows = _dashboard(d, include_test, month)
    _new_list(s, rows, names)
    st.divider()
    shown = _table_section(rows, names)
    _review(s, d, shown, names, month)


# --------------------------------------------------------------------------- Friends & Family 10 (invitations)

def _pilot_action(fn, message: str) -> None:
    try:
        fn()
    except StoreError as error:
        st.error(_error(error))
        return
    except Exception:
        st.error("That did not work just now. Please try again.")
        return
    hooks.pilot_switch(refresh=True)
    st.session_state.pop("rw_invited", None)
    _invalidate()
    st.session_state.rw_f_flash = message
    st.rerun()


def _pilot_controls(s, d: dict) -> None:
    """Three independent modes: public educational access (always), the invitation-only Friends & Family 10 (this
    switch and list), and public rewards enrolment (the Public Rewards Programme switch AND invitation-only OFF).
    Every change is made by a database function that checks the owner list and writes the audit log."""
    from core import legal
    st.markdown("#### Pilot switch and invitations")
    status = s.pilot_status()
    if not status.get("installed"):
        st.warning("The invitation-only pilot is not installed in the database yet. After your approval, run "
                   "supabase/pilot_invitations_migration.sql in Supabase. Until then nobody can enter the pilot, and "
                   "real applications stay closed unless the public programme is ON (the earlier rule).")
        return
    actor = _actor()
    invites = s.invitations()
    active = [i for i in invites if not i.get("revoked_at")]
    approved = sum(1 for a in d["applications"] if a["status"] == "approved" and not a.get("test"))
    docs = legal.pilot_ready()
    _tiles([("Pilot switch", "ON" if status["enabled"] else "OFF"),
            ("Pilot open to invited people", "YES" if hooks.pilot_open() else "no"),
            ("Invitations", str(len(active))),
            ("Approved participants", f"{approved} / {legal.PILOT_MAX_PLACES}")])
    blockers = activation_blockers(status)
    if status["enabled"] and not docs:
        st.info("The pilot switch is ON, but the pilot stays closed until the Privacy Policy, Terms of Use and pilot "
                "terms are published (⚖️ Legal & switches).")
    st.caption("Invited people can apply; you still approve every application (at most 50). Activity earns ₦0 while "
               "the public programme is OFF, and no payment switch is changed here.")
    current, recorded = legal.pilot_terms_id(), status.get("terms_version")
    st.markdown(f"**Participation terms applicants accept:** recorded `{recorded or 'none'}` · published pilot terms "
                f"`{current}`" + (" ✅" if recorded == current else ""))
    if recorded != current:
        if legal.doc_live("pilot"):
            st.info("Applications are paused until you record the published pilot terms (after any change to them, "
                    "record them again).")
            if st.button("Record the published pilot terms as the approved version", key="pilot_terms_record"):
                _pilot_action(lambda: s.set_participation_terms("pilot", current, actor),
                              f"Applicants must now accept the pilot terms {current}.")
        else:
            st.caption("The pilot terms are not published yet (⚖️ Legal & switches), so they cannot be recorded.")
    if status["enabled"]:
        if st.button("Switch the pilot OFF", key="pilot_off"):
            _pilot_action(lambda: s.set_pilot(False, actor), "The Friends & Family 10 was switched off.")
    else:
        if blockers:
            st.warning("**The pilot cannot be switched on yet.** Still required:\n\n"
                     + "\n".join(f"- {b}" for b in blockers), icon="⛔")
        sure = st.checkbox("I confirm the pilot may accept applications from invited people.", key="pilot_on_confirm",
                           disabled=bool(blockers))
        if st.button("Switch the pilot ON", key="pilot_on", type="primary", disabled=bool(blockers) or not sure,
                     help="Available once every legal requirement above is complete." if blockers else None):
            _pilot_action(lambda: s.set_pilot(True, actor, confirmed=True), "The Friends & Family 10 was switched on.")

    with st.form("pilot_invite", border=True, clear_on_submit=True):
        st.markdown("**Invite a person** (the Google address they sign in with)")
        email = st.text_input("Email", max_chars=254, key="pilot_invite_email")
        note = st.text_input("Note (optional, for you)", max_chars=founding.INVITE_NOTE_MAX, key="pilot_invite_note")
        if st.form_submit_button("Add invitation"):
            if not founding.email_ok(email):
                st.error(ERRORS["invalid_email"])
            else:
                _pilot_action(lambda: s.invite(email, actor, note or None),
                              f"{founding.normalize_email(email)} was invited.")
    if invites:
        _table([{"Email": i["email"], "Note": i.get("note") or "", "Invited": str(i.get("invited_at") or "")[:10],
                 "Status": "revoked" if i.get("revoked_at") else "invited"} for i in invites])
    if active:
        one, two = st.columns([3, 1], vertical_alignment="bottom")
        pick = one.selectbox("Revoke an invitation", [i["email"] for i in active], index=None, key="pilot_revoke_pick",
                             help="Stops new applications from this address. An existing application and your "
                                  "decision on it are not changed.")
        if two.button("Revoke", key="pilot_revoke", disabled=not pick):
            _pilot_action(lambda: s.revoke_invitation(pick, actor), f"The invitation for {pick} was revoked.")

    with st.expander("Public rewards enrolment (separate decision)", key="pilot_public_entry"):
        public_now, public_rec = rewards.TERMS_VERSION, status.get("public_terms_version")
        st.markdown(f"**Public programme rules applicants accept:** recorded `{public_rec or 'none'}` · current rules "
                    f"`{public_now}`" + (" ✅" if public_rec == public_now else ""))
        if public_rec != public_now and st.button("Record the current public programme rules as approved",
                                                  key="public_terms_record"):
            _pilot_action(lambda: s.set_participation_terms("public", public_now, actor),
                          f"Public applicants must now accept the programme rules {public_now}.")
        if status["invitation_only"]:
            st.markdown("**Invitation only: ON** (recommended). Even when the Public Rewards Programme switch is ON, "
                        "only invited people can apply.")
            sure = st.checkbox("I confirm that opening applications to everyone has been separately authorised.",
                               key="pilot_public_confirm")
            if st.button("Allow public applications", key="invitation_only_off", disabled=not sure):
                _pilot_action(lambda: s.set_invitation_only(False, actor, confirmed=True),
                              "Invitation only was switched off: when the public programme is ON, anyone may apply.")
        else:
            st.warning("Invitation only: OFF. When the Public Rewards Programme switch is ON, anyone signed in may apply "
                       "(you still approve each application). The pilot itself always requires an invitation.")
            if st.button("Switch invitation only back ON", key="invitation_only_on"):
                _pilot_action(lambda: s.set_invitation_only(True, actor), "Invitation only was switched back on.")
