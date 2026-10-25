"""📊 F&F 10 rewards — the Owner's management view for Friends & Family 10 (English only).

Rendered only after analytics.is_owner() on the server. Every amount comes from the database's own calculation
(pilot_month_days per participant, pilot_settlement_preview, pilot_settle_month); raw activity is loaded only for the
participant and month the owner opens (review flags and the CSV download).
Nothing here can pay money: pilot_mark_paid always refuses while payments are disabled.
"""
from __future__ import annotations

import time

import streamlit as st

from core import analytics, rewards
from core import pilot_rewards as pr
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .owner_rewards import _actor, _download, _naira, _short, _table, _tiles

DATA_TTL = 30
ERRORS = {
    "not_owner": "Your email is not listed in reward_cashout_settings.owner_emails in the database.",
    "reason_required": "Please give a reason.",
    "confirmation_required": "Please tick the confirmation first.",
    "month_not_ended": "A month can be settled only after it has ended (Lagos time).",
    "already_settled": "This month is already settled. Settlements are final.",
    "preview_changed": "The figures changed since the preview (for example a day was excluded). Check the new preview "
                       "and confirm again.",
    "month_settled": "This month is settled; its days can no longer change.",
    "payments_disabled": "Payments are disabled. Nothing was paid.",
    "no_change": "It already has that status.",
    "note_too_long": "Please keep the note under 500 characters.",
}


def _error(error: Exception) -> str:
    text = str(error)
    return next((m for k, m in ERRORS.items() if k in text), text)


def _invalidate() -> None:
    st.session_state.pop("ff10_owner", None)


def _load(s) -> dict:
    cached = st.session_state.get("ff10_owner")
    if cached and time.time() - cached["at"] < DATA_TTL:
        return cached
    apps = [a for a in s.founding_applications() if not a.get("test")]
    lines = s.ff10_lines()
    month = rewards.month_key()
    approved = [a for a in apps if a["status"] == "approved"]
    people = sorted({a["profile_id"] for a in approved} | {line["profile_id"] for line in lines})
    data = {"at": time.time(), "month": month, "accounts": {a["profile_id"]: a for a in s.accounts()},
            "approved": approved, "applications": apps, "people": people,
            "invitations": [i for i in s.invitations() if not i.get("revoked_at")],
            "ledgers": {pid: [_summary(r) for r in s.ff10_ledger(pid, month)] for pid in people},
            "settlements": {r["month"]: r for r in s.ff10_settlements()}, "lines": lines}
    st.session_state.ff10_owner = data
    return data


def _who(d: dict, pid: str) -> str:
    a = d["accounts"].get(pid) or {}
    return a.get("display_name") or a.get("email") or _short(pid)


def _summary(row: dict) -> pr.DaySummary:
    from .ff10_ui import _summary as convert
    return convert(row)


def _people(d: dict) -> list[str]:
    return sorted(d["people"], key=lambda pid: _who(d, pid).lower())


def _recent_months(month: str, n: int = 6) -> list[str]:
    out = [month]
    while len(out) < n:
        out.append(rewards.previous_month(out[-1]))
    return out


def render() -> None:
    if not analytics.is_owner():
        st.info("This page is not available.")
        return
    st.markdown("### 📊 Friends & Family 10 — learning and provisional rewards")
    health = hooks.ff10_health()
    if health != "ok":
        st.warning("Friends & Family 10 rewards are not installed in the database yet. After review and your "
                   "approval, run supabase/friends_family10_migration.sql in Supabase. Until then nothing is recorded "
                   "and participants see no rewards; everything else works as before."
                   if health == "missing_tables" else "The Friends & Family 10 records could not be read just now.")
        return
    s = hooks.ff10_store(for_tester=True)
    flash = st.session_state.pop("ff10_flash", None)
    if flash:
        st.success(flash)
    try:
        d = _load(s)
    except Exception:
        st.error("The Friends & Family 10 records could not be read just now. Players are not affected.")
        return
    month, today = rewards.month_key(), rewards.day_key()
    st.caption("Provisional amounts are calculated from verified learning and are not payable. After a month ends you "
               "finalise its settlement (shared ₦50,000 budget), then approve or withhold each participant's final "
               "allocation. Payments stay disabled.")
    _overview(d, month, today)
    st.divider()
    _participant_detail(s, d, month)
    st.divider()
    _settlement(s, d, month)
    st.divider()
    _settled(s, d)


def _overview(d: dict, month: str, today: str) -> None:
    people = _people(d)
    ledgers = d["ledgers"]
    provisional = {pid: sum(x.amount for x in days) for pid, days in ledgers.items()}
    estimate = pr.allocate(provisional)
    total = sum(provisional.values())
    pending = sum(1 for line in d["lines"] if line["status"] == "pending_review")
    approved_total = sum(line["final"] for line in d["lines"] if line["status"] == "approved")
    paid_total = sum(line["final"] for line in d["lines"] if line["status"] == "paid")
    active = sum(1 for days in ledgers.values() if any(x.minutes > 0 for x in days))
    _tiles([("Invited", str(len(d["invitations"])), "active invitations"),
            ("Approved participants", f"{len(d['approved'])} / {pr.MAX_PARTICIPANTS}"),
            ("Active this month", str(active), "with verified learning time"),
            ("Monthly budget", _naira(pr.MONTHLY_BUDGET), month),
            ("Provisional this month", _naira(total), "before budget adjustment"),
            ("Remaining budget", _naira(max(pr.MONTHLY_BUDGET - total, 0)), "if the month ended now"),
            ("Pending settlement reviews", str(pending)),
            ("Approved, not paid", _naira(approved_total), "all settled months"),
            ("Paid", _naira(paid_total), "payments are disabled")])
    if pr.scaled(provisional):
        st.info(f"This month's provisional total ({_naira(total)}) is above the budget: final allocations would be "
                "reduced in proportion (estimate below).")
    table = []
    for pid in people:
        days = ledgers[pid]
        day = next((x for x in days if x.day == today), None)
        table.append({"Participant": _who(d, pid), "E-mail": (d["accounts"].get(pid) or {}).get("email") or "",
                      "Today (min)": day.minutes if day else 0,
                      "Today's activities": (f"{day.quizzes} quiz · {'challenge ✓' if day.challenge else 'no challenge'}"
                                             f" · {day.new_countries} new country") if day else "—",
                      "Today provisional": _naira(day.amount if day else 0),
                      "Month minutes": sum(min(x.minutes, pr.MAX_MINUTES) for x in days),
                      "Month provisional": _naira(provisional[pid]),
                      "Estimated final": _naira(estimate[pid]),
                      "Excluded days": sum(1 for x in days if x.excluded) or ""})
    st.markdown(f"#### Participants — {month}")
    _table(table, "No approved participants or activity yet.")


def _participant_detail(s, d: dict, month: str) -> None:
    st.markdown("#### Activity and reward history")
    people = _people(d)
    if not people:
        st.caption("Nothing to show yet.")
        return
    pid = st.selectbox("Participant", people, format_func=lambda p: _who(d, p), key="ff10_pick")
    chosen = st.selectbox("Month", _recent_months(month), key="ff10_pick_month")
    try:
        ledger = [_summary(r) for r in s.ff10_ledger(pid, chosen)]
        rows = [r for r in s.ff10_activity(pid, chosen) if not r.get("test")]
    except Exception:
        st.error("This participant's history could not be loaded just now.")
        return
    flags = {x.day: x.flags for x in pr.day_summaries(rows)}          # signals for review only (never automatic)
    _table([{"Day": x.day, "Verified min": x.minutes, "Quizzes": x.quizzes, "Daily Challenge": "✓" if x.challenge else "",
             "New countries": x.new_countries, "Interactions": x.interactions, "Tier": x.tier or "",
             "Provisional": _naira(x.amount), "Excluded": "yes" if x.excluded else "",
             "Review flags": "; ".join(flags.get(x.day, ()))} for x in reversed(ledger)], "No activity in this month.")
    _download("Download activity (CSV)", [{"at": r["at"], "day": r["day"], "kind": r["kind"], "subject": r["subject"]}
                                          for r in rows], f"ff10-activity-{_short(pid)}-{chosen}", "ff10_csv")
    if chosen in d["settlements"] or not ledger:
        if chosen in d["settlements"]:
            st.caption("This month is settled: its days can no longer change.")
        return
    with st.form("ff10_review", border=True, clear_on_submit=True):
        st.markdown("**Review a day** (excluded days earn ₦0 and do not use up the monthly maximum)")
        day = st.selectbox("Day", [x.day for x in reversed(ledger)], key="ff10_review_day")
        reason = st.text_input("Reason (required to exclude)", max_chars=500, key="ff10_review_reason")
        one, two = st.columns(2)
        exclude = one.form_submit_button("Exclude this day")
        restore = two.form_submit_button("Restore this day")
    if exclude or restore:
        _act(lambda: s.ff10_review_day(pid, day, bool(exclude), _actor(), reason or None),
             f"{day} was {'excluded' if exclude else 'restored'} for {_who(d, pid)}.")


def _act(fn, message: str) -> None:
    try:
        fn()
    except StoreError as error:
        st.error(_error(error))
        return
    except Exception:
        st.error("That did not work just now. Please try again; nothing was changed.")
        return
    _invalidate()
    st.session_state.pop("ff10_progress", None)
    st.session_state.ff10_flash = message
    st.rerun()


def _settlement(s, d: dict, month: str) -> None:
    st.markdown("#### Monthly settlement")
    candidates = [m for m in _recent_months(month, 4)[1:] if m not in d["settlements"] and pr.month_ended(m)]
    if not candidates:
        st.caption("No ended month is waiting for settlement. The current month can be settled after it ends.")
        return
    chosen = st.selectbox("Month to settle", candidates, key="ff10_settle_month")
    try:
        preview = s.ff10_preview(chosen)
    except Exception:
        st.error("The settlement preview could not be calculated just now.")
        return
    if not preview["lines"]:
        st.caption(f"No participant activity in {chosen}: nothing to settle.")
        return
    _tiles([("Budget", _naira(preview["budget"])), ("Provisional total", _naira(preview["total_provisional"])),
            ("Final total", _naira(preview["total_final"])), ("Unspent", _naira(preview["unspent"])),
            ("Participants", str(len(preview["lines"])))])
    if preview["scaled"]:
        st.info("The provisional total is above the budget, so every amount is reduced in proportion (whole naira, "
                "largest-remainder rounding). The final total is exactly the budget.")
    else:
        st.caption("The provisional total is within the budget: everyone keeps their full amount; the rest stays "
                   "unspent.")
    _table([{"Participant": _who(d, line["profile_id"]), "Provisional": _naira(line["provisional"]),
             "Final allocation": _naira(line["final"])} for line in preview["lines"]])
    sure = st.checkbox(f"I have checked this allocation for {chosen}. Finalising is permanent; each amount still needs "
                       "my approval and nothing is paid.", key="ff10_settle_confirm")
    if st.button(f"Finalise the {chosen} settlement", key="ff10_settle", type="primary", disabled=not sure):
        _act(lambda: s.ff10_settle(chosen, _actor(), preview["fingerprint"], confirmed=True),
             f"The {chosen} settlement was finalised. Review each participant's allocation below.")


def _settled(s, d: dict) -> None:
    st.markdown("#### Settled months")
    if not d["settlements"]:
        st.caption("No month has been settled yet.")
        return
    chosen = st.selectbox("Settled month", sorted(d["settlements"], reverse=True), key="ff10_settled_month")
    settlement = d["settlements"][chosen]
    st.caption(f"Finalised by {settlement['finalised_by']} on {str(settlement['finalised_at'])[:10]} · provisional "
               f"{_naira(settlement['total_provisional'])} · final {_naira(settlement['total_final'])}"
               + (" · reduced in proportion" if settlement["scaled"] else ""))
    lines = [line for line in d["lines"] if line["month"] == chosen]
    _table([{"Participant": _who(d, line["profile_id"]), "Provisional": _naira(line["provisional"]),
             "Final": _naira(line["final"]), "Status": pr.LINE_LABELS.get(line["status"], line["status"]),
             "Decided by": line.get("decided_by") or "", "Note": line.get("note") or ""} for line in lines])
    open_lines = [line for line in lines if line["status"] != "paid"]
    if not open_lines:
        return
    with st.form("ff10_decide", border=True, clear_on_submit=True):
        pid = st.selectbox("Participant", [line["profile_id"] for line in open_lines],
                           format_func=lambda p: _who(d, p), key="ff10_decide_pick")
        note = st.text_input("Note (required to withhold, or to change an earlier decision)", max_chars=500,
                             key="ff10_decide_note")
        one, two, three = st.columns(3)
        approve = one.form_submit_button("✅ Approve allocation")
        withhold = two.form_submit_button("✖ Withhold")
        three.form_submit_button("Mark as paid", disabled=True, help="Payments are disabled.")
    if approve or withhold:
        action = "approve" if approve else "withhold"
        _act(lambda: s.ff10_decide(chosen, pid, action, _actor(), note or None),
             f"{_who(d, pid)}: {chosen} allocation {'approved (not paid)' if approve else 'withheld'}.")
    st.caption("Approving records your decision only. Payments are disabled; no money can be paid from here.")
