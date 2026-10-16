"""🌟 Founding 50 Applications — part of 💰 Rewards & Referral Management in the Owner dashboard (English only).

Option B: anyone can apply, only the Owner approves. Access: rendered only after analytics.is_owner() on the server;
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
    "places_full": "All Founding 50 places are taken. Place the application on the waiting list, or first move an "
                   "approved participant off.",
    "reason_required": "Please give a reason. A reason is needed to reject, and to take a place away from an approved "
                       "participant.",
    "no_change": "The application already has that status.",
    "note_too_long": "Please keep the note under 500 characters.",
    "unknown_application": "This application no longer exists. Press Refresh.",
    "invalid_action": "That action is not possible.",
}
ACTION_LABEL = {"approve": "✅ Approve", "waitlist": "⏳ Waiting list", "reject": "✖ Reject"}


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
        st.toast(f"🌟 {new - seen} new Founding 50 application(s)", icon="🌟")
        _invalidate()
    st.session_state.rw_f_alert_seen = new
    if new:
        st.info(f"{new} new Founding 50 application{'s' if new != 1 else ''} — open 💰 Rewards & Referral "
                "Management → 🌟 Founding 50 to review.", icon="🌟")


def _dashboard(d: dict, include_test: bool, month: str) -> list[dict]:
    rows = [a for a in d["applications"] if include_test or not a.get("test")]
    pick = (lambda xs: xs) if include_test else (lambda xs: [x for x in xs if not x.get("test")])
    f = founding.dashboard(rows, pick(d["enrolments"]), pick(d["events"]), d["settings"].max_places, month,
                           _verified(d, rows, month))
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
            st.markdown(f"**🌟 NEW FOUNDING 50 APPLICATION** · {escape(_who(names.get(a['profile_id']), a['profile_id']))}"
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
        full = taken >= d["settings"].max_places and not a.get("test")
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
            st.caption(f"All {d['settings'].max_places} places are taken — approve is unavailable. Use the waiting "
                       "list.")
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
    st.markdown("### 🌟 Founding 50 Applications")
    st.caption("Anyone can apply; only you approve. Only approved participants can earn money — the database refuses "
               "enrolment and pays ₦0 for everyone else.")
    names = _names(d)
    rows = _dashboard(d, include_test, month)
    _new_list(s, rows, names)
    st.divider()
    shown = _table_section(rows, names)
    _review(s, d, shown, names, month)
