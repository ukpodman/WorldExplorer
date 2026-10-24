"""Private owner dashboard for the pilot. Access is checked on the server on every run (analytics.is_owner):
a signed-in Google account whose verified email is listed in secrets [analytics] owner_emails. Knowing the page
name is not enough. The dashboard reads the analytics tables with the server key; nothing is sent to the browser
except the aggregated numbers below. Owner-facing text is English only."""
from __future__ import annotations

from html import escape

import streamlit as st

from core import analytics, legal, metrics

PERIODS = {"Last 7 days": 7, "Last 28 days": 28, "All data": None}
MODE_LABELS = {"regular": "Quiz rounds (quiz setup)", "daily": "Daily Challenge — first counted attempt",
               "daily_replay": "Daily Challenge — practice replays", "practice": "Practise mistakes"}


def _pct(rate: dict) -> str:
    return "—" if rate["pct"] is None else f"{rate['pct']:.0f}%"


def _table(rows: list[dict]) -> None:
    """A small HTML table (no extra dependencies; values are escaped)."""
    if not rows:
        st.caption("No data yet.")
        return
    head = "".join(f"<th>{escape(str(k))}</th>" for k in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r.values()) + "</tr>" for r in rows)
    st.html(f'<div class="owner-table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def _tile(label: str, value: str, note: str = "") -> str:
    return (f'<div class="owner-tile"><span>{escape(label)}</span><b>{escape(value)}</b>'
            f'{f"<small>{escape(note)}</small>" if note else ""}</div>')


@st.cache_data(ttl=60, show_spinner=False)
def _load(include_feedback: bool) -> tuple[list, list]:
    events = analytics.fetch(analytics.EVENTS_TABLE,
                             "occurred_at,event,anon_id,signed_in,mode,day,round_id,linked_id,device,test",
                             "occurred_at.asc,event_key.asc")
    feedback = (analytics.fetch(analytics.FEEDBACK_TABLE, "created_at,page,device,description,contact,lang",
                                "created_at.desc,id.asc") if include_feedback else [])
    return events, feedback


REWARDS_TAB = "💰 Rewards & Referral Management"


def render() -> None:
    if not analytics.is_owner():
        # Same message whether the page exists or not; no data is loaded.
        st.info("This page is not available.")
        return
    from . import owner_rewards  # local import: only owners ever load the rewards dashboard
    st.title("Pilot dashboard")
    from . import owner_withdrawals
    owner_withdrawals.alert()   # refreshes itself every 30 s while the dashboard is open
    from . import owner_founding
    owner_founding.alert()      # new Founding 50 applications (in-app notification), refreshes itself as well
    # Only the open tab is drawn: Rewards & Referral Management reads about 30 tables/rows sets from Supabase, which
    # used to run on every visit and every rerun of the dashboard even while Pilot analytics was shown.
    analytics_tab, rewards_tab, legal_tab = st.tabs(["Pilot analytics", REWARDS_TAB, LEGAL_TAB], key="owner_tab",
                                                     on_change="rerun")
    with analytics_tab:
        if analytics_tab.open is not False:
            _pilot_analytics()
    with rewards_tab:
        if rewards_tab.open:
            owner_rewards.render()
    with legal_tab:
        if legal_tab.open:
            _legal_and_switches()


LEGAL_TAB = "⚖️ Legal & switches"


def _legal_and_switches() -> None:
    """Read-only overview: who operates the app, which legal documents are published (and what is missing), and every
    switch that keeps the pilot, public rewards enrolment and money closed. Nothing here changes anything."""
    from . import rewards_hooks as hooks
    cfg = legal.config()
    verified = legal.operator_verified(cfg)
    st.markdown(f"**Operator:** {legal.identification(verified=verified)}")
    st.markdown(f"**Public identification (shown once a document is published):** {legal.operator_line()}")
    general, pilot = legal.live(cfg), legal.pilot_ready(cfg)
    (st.success if general else st.warning)(
        "The Privacy Policy and Terms of Use are PUBLISHED (Settings → Legal information)." if general else
        "The Privacy Policy and Terms of Use are NOT published. Public rewards enrolment, withdrawals and payouts stay "
        "closed. Each document needs: the operator confirmed, a contact email and the registered address, no draft "
        "notice or [open items], a final version, and your approval of that exact version.")
    rows = [{"Requirement": r["switch"], "State": "OK" if r["on"] else "missing", "Details": r["controls"]}
            for r in legal.status(cfg)]
    cfgr = hooks.config()
    public, pilot_sw = hooks.public_state(), hooks.pilot_switch()
    rows += [
        {"Requirement": "Friends & Family Pilot (effective)", "State": "OPEN" if hooks.pilot_open() else "closed",
         "Details": f"Pilot switch {'ON' if pilot_sw.get('enabled') else 'off'} · pilot documents "
                    f"{'published' if pilot else 'not published'} · invited people only · at most "
                    f"{legal.PILOT_MAX_PLACES} approved (Founding 50 tab)."},
        {"Requirement": "[rewards] enabled", "State": "ON" if hooks.deployment_enabled() else "off",
         "Details": "Deployment safety switch for the public rewards programme."},
        {"Requirement": "Public Rewards Programme (dashboard)", "State": "ON" if public.get("owner") else "off",
         "Details": "The owner's switch in 💰 Rewards & Referral Management → Settings."},
        {"Requirement": "Invitation only", "State": "ON" if pilot_sw.get("invitation_only", True) else "OFF",
         "Details": "While ON, even the public programme accepts invited people only (Founding 50 tab)."},
        {"Requirement": "Public rewards enrolment (effective)", "State": "OPEN" if hooks.enabled() else "closed",
         "Details": public.get("reason", "")},
        {"Requirement": "[rewards] withdrawals_active", "State": "ON" if cfgr.get("withdrawals_active") else "off",
         "Details": "Real withdrawal requests (effective: " + ("open" if hooks.withdrawals_active() else "closed") + ")."},
        {"Requirement": "[rewards] payouts_active", "State": "ON" if cfgr.get("payouts_active") else "off",
         "Details": "Approving and paying real money (effective: " + ("open" if hooks.payouts_active() else "closed") + ")."},
    ]
    _table(rows)
    st.caption("Preview the documents in Settings → Legal information (owners see the drafts). Checklist: "
               "legal/OPERATOR_VERIFICATION.md.")


def _pilot_analytics() -> None:
    st.caption("Private to the accounts listed in secrets [analytics] owner_emails. All days are UTC calendar days "
               "(the Daily Challenge day). Only visitors who allowed usage statistics are measured.")
    if not analytics.enabled():
        st.warning("Analytics is switched off or storage is not configured. Follow SETUP_ANALYTICS.md, then set "
                   "[analytics] enabled = true in the app's secrets.")
        return
    left, mid, right = st.columns([1.2, 1, 1], vertical_alignment="bottom")
    period_label = left.selectbox("Period for visitor and round counts", list(PERIODS), key="owner_period")
    include_test = mid.toggle("Include owner/test traffic", key="owner_include_test")
    marked = right.toggle("Mark this browser as test traffic", value=bool(st.session_state.get("an_test")),
                          key="owner_test_browser",
                          help="Sets a cookie in this browser; its events are flagged as test traffic and left out.")
    if marked != bool(st.session_state.get("an_test")):
        analytics.set_test_browser(marked)
    if st.button("Refresh data", key="owner_refresh"):
        _load.clear()
    try:
        events, feedback = _load(True)
    except Exception:
        st.error("The analytics tables could not be read. Check that SETUP_ANALYTICS.md was run in Supabase. "
                 "Players are not affected.")
        return
    m = metrics.compute(events, analytics.utc_now(), PERIODS[period_label], include_test)
    D = metrics.DEFINITIONS
    st.html('<div class="owner-grid">'
            + _tile("Measured people (all data)", str(m["people"]), "guest ids merged after sign-in")
            + _tile("New visitors", str(m["new"]), period_label)
            + _tile("Returning visitors", str(m["returning"]), period_label)
            + _tile("First-round completion", _pct(m["first_round"]), f"{m['first_round']['n']} of {m['first_round']['d']}")
            + _tile("Return within 7 days", _pct(m["return7"]),
                    f"{m['return7']['n']} of {m['return7']['d']} · {m['return7']['pending']} still in window")
            + _tile("Active on 3+ days", _pct(m["active3"]), f"{m['active3']['n']} of {m['active3']['d']}")
            + _tile("Signed-in / guest", f"{m['signed_in']['signed_in']} / {m['signed_in']['guest']}",
                    f"{m['signed_in']['linked']} guests later signed in")
            + _tile("“No thanks” answers", str(m["declined"]), period_label)
            + '</div>')
    st.subheader("Rounds by mode")
    st.caption(period_label + " · starts and completions are events; people are distinct persons.")
    _table([{"Mode": MODE_LABELS[k], "Starts": v["starts"], "Completions": v["completions"],
             "People who started": v["people_started"], "People who completed": v["people_completed"]}
            for k, v in m["rounds"].items()])
    st.caption(f"Daily Challenge: {m['rounds']['daily']['completions']} first counted completions on "
               f"{m['daily_person_days']} daily person-days ({period_label}).")
    st.subheader("Daily participation (UTC days)")
    _table([{"Day": r["day"], "Active people": r["active"], "People with a daily first completion": r["daily_first"],
             "Rounds completed": r["rounds_completed"]} for r in reversed(m["daily_table"])])
    st.caption("Devices (people, last seen): " + ", ".join(f"{k} {v}" for k, v in sorted(m["devices"].items()))
               + f" · Excluded test/owner events: {m['excluded_events']}")
    with st.expander("Metric definitions"):
        for key in ("people", "new", "returning", "rounds", "first_round", "return7", "active3", "signed_in", "declined"):
            st.markdown(f"- {D[key]}")
    st.subheader("Feedback")
    if not feedback:
        st.caption("No feedback yet.")
    for item in feedback[:50]:
        with st.container(border=True):
            st.text(f"{str(item.get('created_at', ''))[:16].replace('T', ' ')} UTC · {item.get('page')} · "
                       f"{item.get('device')} · {item.get('lang')}")
            st.text(item.get("description") or "")
            if item.get("contact"):
                st.text("Contact: " + str(item["contact"]))
