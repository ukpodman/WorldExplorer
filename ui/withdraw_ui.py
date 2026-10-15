"""💳 Withdraw — the player's part of the manual withdrawal system, shown inside 💰 My Rewards.

The withdrawal button stays grey until the database says this person is eligible (reward_cashout_status): joined,
30 calendar days since the original enrolment (Nigeria time), earnings from completed months that are not already
requested or paid, no open request, and — for real accounts — live withdrawals switched on by the owner. A request
always covers the whole available balance; the player never enters bank details here. Approval and payment are done
manually by the owner (ui/owner_withdrawals.py); nothing here moves money.
"""
from __future__ import annotations

from datetime import timedelta
from html import escape

import streamlit as st

from core import notify, rewards, withdrawals
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .components import e, html
from .state import language, t

PLAYER_STATUS = {
    "pending_review": ("Pending Review", "Your withdrawal request has been received and is awaiting verification."),
    "under_review": ("Under Review", "The programme owner is verifying your request."),
    "approved": ("Approved — Awaiting Payment",
                 "Your request is approved. The programme owner will send the payment to your bank account."),
    "on_hold": ("On Hold", "Your request is on hold for further checks. The programme owner will contact you."),
    "rejected": ("Rejected", "Your request was not approved."),
    "paid": ("Paid", "The payment has been sent."),
}
BLOCKED = (  # first matching reason decides the grey button's label
    ("suspended", "🔒 Withdraw — Participation on hold"),
    ("account_on_hold", "🔒 Withdraw — Participation on hold"),
    ("not_joined", "🔒 Withdraw — Join the programme first"),
    ("not_enrolled", "🔒 Withdraw — Join the programme first"),
    ("declarations", "🔒 Withdraw — Declarations missing"),
    ("waiting_period", None),                       # "Available in N days"
    ("no_earnings", "🔒 Withdraw — No earnings from completed months yet"),
    ("not_live", "🔒 Withdraw — Opens after the official launch"),
)
DECLARATION_TEXT = {
    "legal_name": "I am providing my correct legal name.",
    "own_account": "The receiving bank account belongs to me.",
    "name_match": "I understand that the bank account beneficiary name must match my verified legal identity.",
    "false_information": "I understand that false or misleading information may result in the withdrawal being "
                         "placed on hold or rejected after review.",
}


def _naira(amount) -> str:
    return f"₦{int(amount or 0):,}"


def _as_of(account: dict) -> str | None:
    """A simulated date (test accounts only; the database refuses it for real accounts)."""
    days = int(st.session_state.get("rw_sim_days") or 0)
    if not account.get("test") or days <= 0:
        return None
    return (withdrawals.today() + timedelta(days=days)).isoformat()


def _button_label(status: dict) -> str:
    reasons = status.get("reasons") or []
    for reason, label in BLOCKED:
        if reason in reasons:
            if reason == "waiting_period":
                days = int(status.get("days_left") or 0)
                return t("🔒 Withdraw — Available in 1 day") if days == 1 else \
                    t("🔒 Withdraw — Available in {n} days", n=days)
            return t(label)
    return t("🔒 Withdraw")


def _tiles(totals: dict) -> None:
    items = (("Total earned", totals.get("earned")), ("Available now", totals.get("available")),
             ("Pending withdrawal", totals.get("pending")), ("Approved, awaiting payment", totals.get("approved")),
             ("Paid", totals.get("paid")), ("Remaining unpaid", totals.get("unpaid")))
    html('<div class="rw-stats rw-cash-stats">' + "".join(
        f'<div class="rw-stat"><div class="rw-stat-value">{escape(_naira(v))}</div>'
        f'<div class="rw-stat-label">{e(k)}</div></div>' for k, v in items) + "</div>")


def _checklist(status: dict) -> None:
    reasons = set(status.get("reasons") or [])
    lines = [
        (not reasons & {"not_joined", "not_enrolled", "suspended", "account_on_hold", "declarations"},
         t("Taking part in the rewards programme")),
        ("waiting_period" not in reasons and status.get("eligible_on") is not None,
         t("{n} calendar days since you first joined", n=status.get("min_days") or withdrawals.MIN_DAYS)
         + (f" ({t('eligible from {day}', day=status['eligible_on'])})" if status.get("eligible_on") else "")),
        ("no_earnings" not in reasons, t("Earnings from completed months that are not yet paid")),
        ("open_request" not in reasons, t("No other withdrawal request in progress")),
    ]
    if not status.get("test"):
        lines.append(("not_live" not in reasons, t("Withdrawals officially opened")))
    st.markdown("**" + t("Eligibility requirements") + "**")
    html('<ul class="rw-checklist">' + "".join(
        f'<li class="{"ok" if done else "todo"}"><span aria-hidden="true">{"✅" if done else "⬜"}</span>'
        f'{escape(text)}</li>' for done, text in lines) + "</ul>")


def _request_card(req: dict, submitted: bool = False) -> None:
    label, message = PLAYER_STATUS.get(req["status"], (req["status"], ""))
    title = "✅ " + t("Withdrawal Request Submitted") if submitted else "💳 " + t("Your withdrawal request")
    rows = [(t("Reference"), req["reference"]), (t("Amount"), _naira(req["amount"])),
            (t("Earning period"), withdrawals.period_label(list(req.get("months") or []), language())),
            (t("Requested on"), str(req.get("requested_at") or "")[:10]), (t("Request status"), t(label))]
    with st.container(border=True, key="rw_cash_request"):
        if req.get("test"):
            html(f'<div class="rw-test-label">🧪 {e(withdrawals.TEST_LABEL)}</div>')
        st.markdown(f"**{title}**")
        html('<dl class="rw-cash-dl">' + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in rows)
             + "</dl>")
        st.caption(t(message))
        if req["status"] in ("on_hold", "rejected") and req.get("decision_note"):
            st.caption(t("Note from the programme owner: {note}", note=req["decision_note"]))


def _form(s, who: dict, account: dict, status: dict) -> None:
    with st.form("rw_cash_form", border=True):
        if account.get("test"):
            html(f'<div class="rw-test-label">🧪 {e(withdrawals.TEST_LABEL)}</div>')
        st.markdown("**💰 " + t("WORLD EXPLORER — WITHDRAWAL REQUEST") + "**")
        rows = [(t("Player"), who.get("name") or account.get("display_name") or ""),
                (t("Verified available balance"), _naira(status["amount"])),
                (t("Eligible earning period"),
                 withdrawals.period_label([m["month"] for m in status.get("months", [])], language()))]
        html('<dl class="rw-cash-dl">' + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in rows)
             + "</dl>")
        legal = st.text_input(t("Legal name"), max_chars=120, key="rw_cash_legal",
                              help=t("Your full name exactly as it appears on your bank account and official ID."))
        ticks = {k: st.checkbox(t(text), key=f"rw_cash_decl_{k}") for k, text in DECLARATION_TEXT.items()}
        st.caption(t("Do not enter bank details here. World Explorer never asks for your bank account number, PIN or "
                     "passwords in the app. The programme owner will contact you by email to verify your details "
                     "and arrange the transfer."))
        st.caption(t("Submitting this request does not verify your identity or bank account. Every request is "
                     "checked manually before any payment."))
        submitted = st.form_submit_button(t("Submit Withdrawal Request"), type="primary", width="stretch")
    if st.button(t("Cancel"), key="rw_cash_cancel"):
        st.session_state.rw_cash_open = False
        st.rerun()
    if not submitted:
        return
    if not withdrawals.legal_name_ok(legal):
        st.error(t("Please enter your legal name."))
        return
    if not all(ticks.values()):
        st.error(t("Please confirm all four statements."))
        return
    pid = account["profile_id"]
    try:
        flags = withdrawals.identity_flags({"profile_id": pid, "legal_name": legal, "test": account.get("test")},
                                           s.cashout_requests(), [account])
        flags += rewards.fraud_signals(account, s.events(pid), s.referrals(pid), s.visits(pid))
    except Exception:
        flags = []
    try:
        req = s.request_cashout(pid, legal.strip(), dict(ticks), status["amount"], _as_of(account), flags)
    except StoreError as error:
        message = str(error)
        if "amount_changed" in message:
            st.error(t("Your available balance has changed. Please check the new amount and submit again."))
        elif "not_eligible" in message:
            st.error(t("A withdrawal request is not possible right now."))
        else:
            st.error(t("The request could not be sent. Please try again."))
        return
    except Exception:
        st.error(t("The request could not be sent. Please try again."))
        return
    _email_owner(s, req)
    st.session_state.rw_cash_open = False
    st.session_state.rw_cash_done = req["id"]
    for k in ["rw_cash_legal"] + [f"rw_cash_decl_{k}" for k in DECLARATION_TEXT]:
        st.session_state.pop(k, None)
    st.rerun()


def _email_owner(s, req: dict) -> None:
    """Optional e-mail to the owner. Never blocks or undoes the recorded request."""
    try:
        note = next((n for n in s.notifications() if n.get("request_id") == req["id"]), None)
        if not note:
            return
        try:
            cfg = dict(st.secrets.get("email", {}))
        except Exception:
            cfg = {}
        result = notify.send(cfg, *notify.withdrawal_message(note.get("details") or {}, bool(req.get("test"))))
        s.set_email_status(note["id"], result)
    except Exception:
        pass


def _history(requests: list[dict]) -> None:
    if not requests:
        return
    with st.expander(t("Withdrawal history")):
        for r in requests:
            label = t(PLAYER_STATUS.get(r["status"], (r["status"],))[0])
            line = (f"**{r['reference']}** · {str(r.get('requested_at') or '')[:10]} · {_naira(r['amount'])} · "
                    f"{withdrawals.period_label(list(r.get('months') or []), language())} · {label}")
            if r["status"] == "paid" and r.get("paid_at"):
                line += f" · {t('paid on {day}', day=str(r['paid_at'])[:10])}"
            if r.get("test"):
                line += " · 🧪 " + t(withdrawals.TEST_LABEL)
            st.markdown(line)
            if r["status"] in ("rejected", "on_hold") and r.get("decision_note"):
                st.caption(t("Note from the programme owner: {note}", note=r["decision_note"]))


def _simulation(s, account: dict, status: dict) -> None:
    """Owner/tester tools: jump ahead in time and add simulated activity (test records only, never payable)."""
    with st.expander("🧪 " + t("Simulation (test account only)")):
        st.caption(t("These tools exist only for test accounts. Everything they create is a test record and is never "
                     "payable."))
        st.number_input(t("Simulate a later date: days from today"), min_value=0, max_value=120, step=1,
                        key="rw_sim_days",
                        help=t("For example 31 to pass the waiting period and close the current month."))
        if st.session_state.get("rw_sim_days"):
            st.caption(t("Simulated date: {day}", day=status.get("today")))
        if st.button(t("Add simulated activity for this month"), key="rw_sim_earn"):
            added = _simulate_month(s, account)
            hooks.context(refresh=True)
            st.success(t("{n} simulated activities recorded.", n=added))


def _simulate_month(s, account: dict) -> int:
    if not account.get("test"):
        return 0
    pid, now = account["profile_id"], withdrawals.today()
    month = withdrawals.month_of(now)
    if account.get("membership") == "member" and not s.enrolment(pid, month):
        try:
            s.enrol(pid, month)
        except StoreError:
            return 0
    added = 0
    for d in range(1, now.day + 1):
        day = f"{month}-{d:02d}"
        rows = [s.add_event(pid, "active_day", day, day, reward=True, test=True)]
        rows += [s.add_event(pid, "quiz", f"sim-{day}-{i}", day, reward=True, test=True) for i in range(3)]
        rows += [s.add_event(pid, "country", f"SIM{d}{i}", day, reward=True, test=True) for i in range(2)]
        added += sum(1 for r in rows if r)
    return added


def section(s, who: dict, account: dict) -> None:
    """The 💳 Withdraw card on 💰 My Rewards (members and people who left with earnings)."""
    cs = hooks.cashout_store()
    if cs is None:
        return
    try:
        status = cs.cashout_status(account["profile_id"], _as_of(account))
        requests = cs.cashout_requests(account["profile_id"])
    except Exception:
        return
    with st.container(border=True, key="rw_cashout"):
        st.subheader("💳 " + t("Withdraw your rewards"))
        if account.get("test"):
            st.warning(t("Test mode — withdrawal requests are simulations: {label}.", label=t(withdrawals.TEST_LABEL)),
                       icon="🧪")
        _tiles(status.get("totals") or {})
        done = st.session_state.get("rw_cash_done")
        open_req = next((r for r in requests if r["status"] in withdrawals.OPEN), None)
        if open_req:
            _request_card(open_req, submitted=done == open_req["id"])
        elif status.get("eligible"):
            if st.session_state.get("rw_cash_open"):
                _form(cs, who, account, status)
            else:
                if st.button(t("💰 Request Withdrawal — {amount}", amount=_naira(status["amount"])),
                             key="rw_withdraw_go", type="primary", width="stretch"):
                    st.session_state.rw_cash_open = True
                    st.session_state.pop("rw_cash_done", None)
                    st.rerun()
        else:
            with st.container(key="rw_withdraw_locked"):
                st.button(_button_label(status), key="rw_withdraw_grey", disabled=True, width="stretch")
            _checklist(status)
        months = status.get("months") or []
        current = (status.get("totals") or {}).get("current_month") or 0
        if months and not open_req:
            st.caption(t("A withdrawal covers your whole available balance from completed months: {period}.",
                         period=withdrawals.period_label([m["month"] for m in months], language())))
        waiting = status.get("waiting_months") or []
        if waiting:
            st.caption(t("Earnings from {period} are still being checked (a friend's invitation is awaiting review) "
                         "and become available afterwards.",
                         period=withdrawals.period_label(list(waiting), language())))
        if current:
            st.caption(t("This month's {amount} becomes available after the month ends (Nigeria time).",
                         amount=_naira(current)))
        _history([r for r in requests if r is not open_req])
        if account.get("test"):
            _simulation(cs, account, status)
