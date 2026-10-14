"""💳 Withdrawal Management — part of 💰 Rewards & Referral Management in the Owner dashboard (English only).

Access: rendered only after analytics.is_owner() on the server; every decision is checked again by the database
(reward_cashout_settings.owner_emails). Approving NEVER moves money: the owner transfers the money from their own bank,
then records it with "Mark as paid" (one ledger row, exactly the approved amount). Real requests can be approved or
paid only while [rewards] payouts_active is on; test requests can always be simulated and are never payable.
"""
from __future__ import annotations

import time
from datetime import date
from html import escape

import streamlit as st

from core import analytics, rewards, withdrawals
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .owner_rewards import _actor, _download, _naira, _short, _table, _tiles

DATA_TTL = 30
NOTIFY_SECONDS = 30   # the notification panel (and only it) checks for new requests this often
ERRORS = {
    "not_owner": "Your email is not listed in reward_cashout_settings.owner_emails in the database. Add it with the "
                 "SQL in WITHDRAWALS_SETUP.md (step 3).",
    "request_closed": "This request is already closed (paid or rejected).",
    "invalid_transition": "That status change is not possible from the current status.",
    "reason_required": "Please give a reason (at least 3 characters).",
    "verification_required": "Confirm both checks (eligibility and bank beneficiary name) before approving.",
    "reservation_mismatch": "The reserved earning months no longer add up to the requested amount. Reject this request.",
    "already_paid": "This request has already been marked as paid. No second payment was recorded.",
    "not_approved": "Only an approved request can be marked as paid.",
    "amount_mismatch": "The amount must equal the approved amount exactly.",
    "payment_date_in_future": "The payment date cannot be in the future.",
    "payment_before_approval": "The payment date cannot be before the approval date.",
    "duplicate_reference": "This bank transaction reference is already recorded for another payment.",
    "invalid_fingerprint": "The bank account fingerprint is not valid.",
    "payouts_disabled": "Real payouts are switched off in the database (reward_cashout_settings.real_payouts = false). "
                        "Real requests cannot be approved or paid until you switch it on after legal review.",
    "account_not_verified": "Verify this player's eligibility first in Participants (Eligibility verification = "
                            "verified). Approving a withdrawal never changes that status by itself; the existing "
                            "payment rules require it before a month is approved or paid.",
    "earnings_changed": "The earnings covered by this request changed after it was submitted (for example a referral "
                        "was rejected, or one is awaiting review). Reject this request — the earnings are released — "
                        "and the player can request the correct net amount again.",
    "verify the participant": "The player's eligibility is not verified in Participants (status 'failed'?). Check the "
                              "account before recording the payment.",
}


EMAIL_STATUS = {"pending": "not sent", "not_configured": "not configured (optional)", "sent": "sent",
                "failed": "failed — the request is saved"}


def _error(error: Exception) -> str:
    text = str(error)
    return next((message for key, message in ERRORS.items() if key in text), text)


def _invalidate() -> None:
    st.session_state.pop("rw_cash_data", None)
    st.session_state.pop("rw_owner_data", None)


def _load(s) -> dict:
    cached = st.session_state.get("rw_cash_data")
    if cached and time.time() - cached["at"] < DATA_TTL:
        return cached
    data = {"at": time.time(), "settings": s.settings(), "cashout": s.cashout_settings(),
            "requests": s.cashout_requests(), "months": s.cashout_months(), "payments": s.cashout_payments(),
            "notifications": s.notifications(), "accounts": s.accounts(), "events": s.events(),
            "reviews": s.payments(), "enrolments": s.enrolments(), "referrals": s.referrals(), "visits": s.visits()}
    st.session_state.rw_cash_data = data
    return data


def unread_count() -> int:
    """New withdrawal requests the owner has not opened yet (for the alert at the top of the Owner dashboard)."""
    try:
        s = hooks.cashout_store(for_tester=True)
        return len(s.notifications(unread=True)) if s else 0
    except Exception:
        return 0


def _names(d: dict) -> dict:
    return {a["profile_id"]: a.get("display_name") or a.get("email") or _short(a["profile_id"]) for a in d["accounts"]}


def _row(r: dict, names: dict, d: dict) -> dict:
    paid = next((p for p in d["payments"] if p["request_id"] == r["id"]), None)
    return {"Reference": r["reference"], "Player": names.get(r["profile_id"], _short(r["profile_id"])),
            "Legal name": r.get("legal_name") or "", "Amount": r["amount"],
            "Earning months": ", ".join(r.get("months") or []), "Requested": str(r.get("requested_at") or "")[:10],
            "Status": withdrawals.STATUS_LABELS[r["status"]], "Decided by": r.get("decided_by") or "",
            "Paid on": (paid or {}).get("payment_date") or "", "Bank reference": (paid or {}).get("bank_reference") or "",
            "Flags": len(r.get("flags") or []), "Test": withdrawals.TEST_LABEL if r.get("test") else ""}


# --------------------------------------------------------------------------- sections

def _switches(d: dict) -> None:
    cfg = d["cashout"]
    owners = {str(x).strip().lower() for x in cfg.get("owner_emails") or []}
    try:
        email_cfg = dict(st.secrets.get("email", {}))
    except Exception:
        email_cfg = {}
    from core import notify
    _tiles([("Live withdrawals (app)", "ON" if hooks.withdrawals_active() else "OFF", "[rewards] withdrawals_active"),
            ("Live withdrawals (database)", "ON" if cfg.get("live_requests") else "OFF", "live_requests"),
            ("Payouts (app)", "ON" if hooks.payouts_active() else "OFF", "[rewards] payouts_active"),
            ("Payouts (database)", "ON" if cfg.get("real_payouts") else "OFF", "real_payouts"),
            ("Owner listed in database", "yes" if _actor().strip().lower() in owners else "NO", "owner_emails"),
            ("E-mail notifications", "configured" if notify.configured(email_cfg) else "off", "[email] SMTP"),
            ("Bank fingerprints", "configured" if len(hooks.fingerprint_key()) >= withdrawals.MIN_KEY_LENGTH
             else "off", "[rewards] bank_fingerprint_key")])
    if not (hooks.withdrawals_active() and cfg.get("live_requests")):
        st.info("Real withdrawal requests are switched off. Players see a grey button; owner and tester (test) "
                "accounts can simulate the whole process. Switching on needs BOTH the app secret and the database "
                "setting (WITHDRAWALS_SETUP.md), after legal and compliance review.")
    if _actor().strip().lower() not in owners:
        st.warning(ERRORS["not_owner"])


@st.fragment(run_every=NOTIFY_SECONDS)
def _live_notifications(s) -> None:
    """New requests appear here while the dashboard is open: only this panel re-runs every NOTIFY_SECONDS (one small
    read of the unread notifications), never the whole page, so forms being filled in are not disturbed. Unread
    notifications are stored in the database and wait until the owner opens the application or marks them read."""
    try:
        unread = s.notifications(unread=True)
        status = {r["id"]: r["status"] for r in s.cashout_requests()}
    except Exception:
        st.caption("🔔 Notifications could not be read just now; they are kept and will show on the next check.")
        return
    seen = st.session_state.get("rw_cash_seen")
    ids = {n["id"] for n in unread}
    if seen is not None and ids - seen:
        st.toast(f"🔔 {len(ids - seen)} new withdrawal request(s)", icon="💳")
        _invalidate()                                   # the table and figures load fresh on the next full run
    st.session_state.rw_cash_seen = ids
    st.markdown(f"#### 🔔 Notifications ({len(unread)} unread)")
    st.caption(f"Checked {time.strftime('%H:%M:%S')} · new requests appear here automatically every "
               f"{NOTIFY_SECONDS} seconds.")
    for n in unread[:10]:
        info = n.get("details") or {}
        with st.container(border=True, key=f"rw_note_{n['id']}"):
            if n.get("test"):
                st.html(f'<div class="rw-test-label">🧪 {escape(withdrawals.TEST_LABEL)}</div>')
            st.markdown("**🔔 NEW WITHDRAWAL REQUEST**")
            st.html('<dl class="rw-cash-dl">' + "".join(
                f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in (
                    ("Player", info.get("player", "")), ("Amount", _naira(info.get("amount"))),
                    ("Reference", info.get("reference", "")), ("Request date", str(info.get("requested_at", ""))[:10]),
                    ("Status", withdrawals.STATUS_LABELS.get(status.get(n.get("request_id")), "")),
                    ("E-mail", EMAIL_STATUS.get(n.get("email_status"), n.get("email_status") or "")))) + "</dl>")
            if st.button("Review Application", key=f"rw_note_open_{n['id']}", type="primary"):
                st.session_state.rw_cash_pick = n.get("request_id")
                s.mark_notification_read(n["id"], _actor())
                _invalidate()
                st.rerun(scope="app")
    if len(unread) > 10:
        st.caption(f"{len(unread) - 10} more unread request(s) are listed in the table below.")
    if len(unread) > 1 and st.button("Mark all as read", key="rw_note_all"):
        for n in unread:
            s.mark_notification_read(n["id"], _actor())
        _invalidate()
        st.rerun(scope="app")


@st.fragment(run_every=NOTIFY_SECONDS)
def alert() -> None:
    """The line at the top of the Owner dashboard; refreshes itself like the notification panel."""
    new = unread_count()
    if new:
        st.warning(f"🔔 {new} new withdrawal request{'s' if new != 1 else ''} — open 💰 Rewards & Referral Management "
                   "→ 💳 Withdrawals to review.", icon="💳")


def _summary(d: dict, include_test: bool) -> None:
    pick = (lambda rows: rows) if include_test else (lambda rows: [r for r in rows if not r.get("test")])
    settings = d["settings"]
    f = withdrawals.summary(pick(d["requests"]), pick(d["payments"]), pick(d["events"]), pick(d["months"]),
                            pick(d["reviews"]), settings.monthly_budget, settings.start_date, rewards.month_key(),
                            referrals=d["referrals"])
    _tiles([("Total withdrawal requests", str(f["total"])), ("Pending review", str(f["pending_review"])),
            ("Under review", str(f["under_review"])), ("Approved", str(f["approved"]), "not paid yet"),
            ("On hold", str(f["on_hold"])), ("Rejected", str(f["rejected"])),
            ("Completed payments", str(f["paid"])), ("Amount awaiting payment", _naira(f["awaiting"])),
            ("Total amount paid", _naira(f["paid_amount"]), "withdrawals + monthly reviews"),
            ("Remaining budget", _naira(f["remaining_budget"]), f"of {_naira(f['allocated'])} allocated so far")])
    if include_test:
        st.caption("Test records are included in these figures — they are simulations, never real liabilities.")


def _filters(d: dict, include_test: bool) -> list[dict]:
    rows = [r for r in d["requests"] if include_test or not r.get("test")]
    names = _names(d)
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("Search player, email, legal name or reference", key="rw_cash_q").strip().lower()
    statuses = c2.multiselect("Status", list(withdrawals.STATUSES), format_func=withdrawals.STATUS_LABELS.get,
                              key="rw_cash_status", placeholder="All")
    c1, c2, c3 = st.columns(3)
    months = sorted({m for r in rows for m in (r.get("months") or [])}, reverse=True)
    month = c1.selectbox("Earning month", ["All"] + months, key="rw_cash_month")
    dates = c2.date_input("Request date (from – to)", value=(), key="rw_cash_dates")
    amounts = c3.number_input("Minimum amount (₦)", min_value=0, step=50, value=0, key="rw_cash_min")
    email = {a["profile_id"]: a.get("email") or "" for a in d["accounts"]}
    out = []
    for r in rows:
        hay = " ".join([r["reference"], r.get("legal_name") or "", names.get(r["profile_id"], ""),
                        email.get(r["profile_id"], ""), r["profile_id"]]).lower()
        day = str(r.get("requested_at") or "")[:10]
        if query and query not in hay:
            continue
        if statuses and r["status"] not in statuses:
            continue
        if month != "All" and month not in (r.get("months") or []):
            continue
        if isinstance(dates, (list, tuple)) and len(dates) == 2 and not (dates[0].isoformat() <= day <= dates[1].isoformat()):
            continue
        if r["amount"] < amounts:
            continue
        out.append(r)
    return out


def _review(s, d: dict, req: dict) -> None:
    names = _names(d)
    pid = req["profile_id"]
    account = next((a for a in d["accounts"] if a["profile_id"] == pid), {})
    events = [e for e in d["events"] if e["profile_id"] == pid and bool(e.get("test")) == bool(req.get("test"))]
    joined = withdrawals.first_enrolment([e for e in d["enrolments"] if e["profile_id"] == pid], bool(req.get("test")))
    months = [m for m in d["months"] if m["request_id"] == req["id"]]
    history = [r for r in d["requests"] if r["profile_id"] == pid and r["id"] != req["id"]]
    made = [r for r in d["referrals"] if r["referrer_id"] == pid]
    referred_by = next((r for r in d["referrals"] if r["referred_id"] == pid), None)
    flags = list(dict.fromkeys(list(req.get("flags") or [])
                               + withdrawals.identity_flags(req, d["requests"], d["accounts"])
                               + rewards.fraud_signals(account, events, made,
                                                       [v for v in d["visits"] if v.get("referrer_id") == pid])))
    with st.container(border=True, key="rw_cash_review"):
        if req.get("test"):
            st.html(f'<div class="rw-test-label">🧪 {escape(withdrawals.TEST_LABEL)}</div>')
        st.markdown(f"**{escape(req['reference'])}** · {withdrawals.STATUS_LABELS[req['status']]} · "
                    f"{_naira(req['amount'])}")
        st.html('<dl class="rw-cash-dl rw-cash-dl-wide">' + "".join(
            f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in (
                ("Legal name (as entered by the player)", req.get("legal_name") or ""),
                ("Registered profile", f"{names.get(pid, '')} · code {account.get('referral_code', '')} · "
                                       f"{_short(pid)} · membership {account.get('membership', '')}"),
                ("Google account", f"{account.get('email') or '—'} (Google name: {account.get('display_name') or '—'})"),
                ("Declarations", f"18+ {'yes' if account.get('age_confirmed') else 'no'} · Nigeria "
                                 f"{'yes' if account.get('residence_confirmed') else 'no'} · eligibility "
                                 f"{account.get('verification', '')} (self-declared until you verify)"),
                ("Rewards enrolment date", joined.astimezone(rewards.LAGOS).date().isoformat() if joined else "—"),
                ("Total earned / net verified", _net_line(pid, req, d)),
                ("Withdrawal amount", _naira(req["amount"])),
                ("Earning months covered", ", ".join(f"{m['month']} {_naira(m['amount'])} ({m['status']})" for m in months)),
                ("Requested", str(req.get("requested_at") or "")[:16].replace("T", " ") + " UTC"
                              + (f" · simulated date {req['simulated_as_of']}" if req.get("simulated_as_of") else "")),
                ("Referral activity", f"{len(made)} referred · {sum(1 for r in made if r['status'] == 'approved')} approved"
                                      + (f" · referred by {_short(referred_by['referrer_id'])} ({referred_by['status']})"
                                         if referred_by else "")),
                ("Bank fingerprint", "recorded" if req.get("bank_fingerprint") else "not recorded"),
                ("Decision", f"{req.get('decided_by') or '—'} {str(req.get('decided_at') or '')[:10]}"
                             + (f" · {req['decision_note']}" if req.get("decision_note") else "")))) + "</dl>")
        if req["status"] not in ("paid", "rejected"):
            if not req.get("test") and account.get("verification") != "verified":
                st.warning("Eligibility is not verified for this player yet (" + str(account.get("verification"))
                           + "). Verify it in Participants before approving; this withdrawal does not change it.")
            if withdrawals.earnings_changed(req, d["months"], d["events"], d["referrals"]):
                st.error(ERRORS["earnings_changed"])
        for flag in flags:
            st.warning(flag)
        if not flags:
            st.caption("No fraud or duplicate-account prompts. (Prompts are never automatic blocks.)")
        if history:
            st.markdown("**Previous withdrawals**")
            _table([_row(r, names, d) for r in history])
        if req["status"] in ("paid", "rejected"):
            paid = next((p for p in d["payments"] if p["request_id"] == req["id"]), None)
            if paid:
                st.success(f"Paid {_naira(paid['amount'])} on {paid['payment_date']} · recorded by {paid['recorded_by']}"
                           + (f" · bank reference {paid['bank_reference']}" if paid.get("bank_reference") else ""))
            return
        _fingerprint(s, req)
        _actions(s, req)


def _net_line(pid: str, req: dict, d: dict) -> str:
    earnings = withdrawals.month_earnings(pid, bool(req.get("test")), d["events"], d["referrals"])
    gross = sum(m["gross"] for m in earnings.values())
    refused = sum(m["refused"] for m in earnings.values())
    waiting = sum(m["awaiting"] for m in earnings.values())
    return (f"{_naira(gross)} earned · {_naira(gross - refused)} net verified"
            + (f" · {_naira(refused)} from rejected referrals deducted" if refused else "")
            + (f" · {_naira(waiting)} of referral rewards awaiting your review" if waiting else ""))


def _fingerprint(s, req: dict) -> None:
    key = hooks.fingerprint_key()
    with st.expander("Bank account check (keyed fingerprint)"):
        st.caption("Enter the bank and the 10-digit account number the player gave you outside the app. Only a keyed "
                   "fingerprint is stored, never the number, to spot the same account on two different profiles.")
        if len(key) < withdrawals.MIN_KEY_LENGTH:
            st.info("Set [rewards] bank_fingerprint_key (32+ random characters) in secrets to use this check.")
            return
        with st.form(f"rw_fp_{req['id']}", clear_on_submit=True, border=False):
            c1, c2 = st.columns(2)
            bank = c1.text_input("Bank (name or code)", max_chars=40)
            number = c2.text_input("Account number", type="password", max_chars=20)
            if st.form_submit_button("Record fingerprint"):
                try:
                    fp = withdrawals.fingerprint(key, bank, number)
                    matches = s.fingerprint_cashout(req["id"], fp, _actor())
                    _invalidate()
                    if matches:
                        st.warning(f"The same bank account is on {matches} other account(s). Review before approving.")
                    else:
                        st.success("Fingerprint recorded. No other account uses this bank account.")
                except ValueError as error:
                    st.error({"account_number_invalid": "Enter a 10-digit account number.",
                              "bank_required": "Enter the bank."}.get(str(error), str(error)))
                except StoreError as error:
                    st.error(_error(error))


def _real_locked(req: dict) -> bool:
    """Real requests can be approved and paid only while [rewards] payouts_active is on (checked here on the server,
    not only by greying out buttons; the database checks its own real_payouts switch as well)."""
    return not req.get("test") and not hooks.payouts_active()


def _decide(s, req: dict, action: str, note: str | None = None, **kwargs) -> None:
    if action == "approve" and _real_locked(req):
        st.error("Payouts are switched off ([rewards] payouts_active = false). Real requests cannot be approved yet.")
        return
    try:
        s.decide_cashout(req["id"], action, _actor(), note=note, **kwargs)
        _invalidate()
        st.session_state.rw_cash_flash = f"{req['reference']}: {withdrawals.STATUS_LABELS[withdrawals.ACTIONS[action]]}."
        st.rerun()
    except StoreError as error:
        st.error(_error(error))


def _actions(s, req: dict) -> None:
    real_locked = _real_locked(req)
    if real_locked:
        st.info("Payouts are switched off ([rewards] payouts_active = false): real requests can be reviewed, held or "
                "rejected, but not approved or marked as paid yet.")
    if req["status"] in ("pending_review", "on_hold"):
        if st.button("Mark as under review", key=f"rw_cash_rv_{req['id']}"):
            _decide(s, req, "review")
    if req["status"] != "approved":
        with st.form(f"rw_cash_ok_{req['id']}", border=True):
            st.markdown("**Approve** — confirms the request. It does NOT transfer money.")
            eligible = st.checkbox("I confirmed the player's eligibility (18+, lives in Nigeria, followed the rules).")
            beneficiary = st.checkbox("I verified that the bank account beneficiary name matches the player's legal "
                                      "identity.")
            note = st.text_input("Note (optional)", max_chars=500)
            if st.form_submit_button("Approve", type="primary", disabled=real_locked):
                _decide(s, req, "approve", note, beneficiary=beneficiary, eligibility=eligible)
    else:
        _pay(s, req, real_locked)
    c1, c2 = st.columns(2)
    with c1, st.form(f"rw_cash_hold_{req['id']}", border=True):
        st.markdown("**Place on hold**")
        reason = st.text_area("Reason (shown to the player)", max_chars=1000, key=f"rw_cash_hold_r_{req['id']}")
        if st.form_submit_button("Place on hold", disabled=req["status"] == "on_hold"):
            _decide(s, req, "hold", reason)
    with c2, st.form(f"rw_cash_no_{req['id']}", border=True):
        st.markdown("**Reject**")
        reason = st.text_area("Explanation (required, shown to the player)", max_chars=1000,
                              key=f"rw_cash_no_r_{req['id']}")
        disqualify = st.checkbox("Disqualify these earnings (they will not become available again)",
                                 help="Leave unticked to release the earnings for a future legitimate request.")
        if st.form_submit_button("Reject"):
            _decide(s, req, "reject", reason, disqualify=disqualify)


def _pay(s, req: dict, real_locked: bool) -> None:
    pending = st.session_state.get("rw_cash_confirm")
    if pending and pending.get("id") == req["id"]:
        with st.container(border=True, key="rw_cash_confirm_box"):
            st.warning(f"Final confirmation: record that you transferred {_naira(pending['amount'])} to "
                       f"{req.get('legal_name')} on {pending['date']}"
                       + (f" (bank reference {pending['reference']})" if pending.get("reference") else "")
                       + ". This cannot be undone.")
            c1, c2 = st.columns(2)
            if c1.button("Confirm and record payment", key=f"rw_cash_pay_go_{req['id']}", type="primary"):
                if _real_locked(req):
                    st.session_state.pop("rw_cash_confirm", None)
                    st.error("Payouts are switched off ([rewards] payouts_active = false). No payment was recorded.")
                    return
                try:
                    s.pay_cashout(req["id"], pending["amount"], pending["date"], pending.get("reference"), _actor())
                    st.session_state.pop("rw_cash_confirm", None)
                    _invalidate()
                    st.session_state.rw_cash_flash = f"{req['reference']}: payment of {_naira(pending['amount'])} recorded."
                    st.rerun()
                except StoreError as error:
                    st.session_state.pop("rw_cash_confirm", None)
                    st.error(_error(error))
            if c2.button("Cancel", key=f"rw_cash_pay_no_{req['id']}"):
                st.session_state.pop("rw_cash_confirm", None)
                st.rerun()
        return
    with st.form(f"rw_cash_pay_{req['id']}", border=True):
        st.markdown(f"**Mark as Paid** — only after you have completed the bank transfer yourself. Approved by "
                    f"{req.get('approved_by')} on {str(req.get('approved_at') or '')[:10]}.")
        c1, c2 = st.columns(2)
        amount = c1.number_input("Amount paid (₦) — must equal the approved amount", min_value=0, step=50,
                                 value=int(req["amount"]))
        paid_on = c2.date_input("Payment date", value=date.fromisoformat(req["simulated_as_of"])
                                if req.get("simulated_as_of") else date.today())
        reference = st.text_input("Bank transaction reference (optional)", max_chars=120)
        sent = st.checkbox(f"I have transferred {_naira(req['amount'])} from my bank to the player.")
        if st.form_submit_button("Mark as paid…", type="primary", disabled=real_locked):
            if real_locked:
                st.error("Payouts are switched off ([rewards] payouts_active = false).")
            elif not sent:
                st.error("Please confirm that you completed the bank transfer.")
            elif int(amount) != int(req["amount"]):
                st.error(ERRORS["amount_mismatch"])
            else:
                st.session_state.rw_cash_confirm = {"id": req["id"], "amount": int(amount),
                                                    "date": paid_on.isoformat(), "reference": reference.strip() or None}
                st.rerun()


def _accounting(d: dict, include_test: bool) -> None:
    pick = (lambda rows: rows) if include_test else (lambda rows: [r for r in rows if not r.get("test")])
    st.markdown("**By earning month** — liabilities stay in the month they were earned")
    earning = withdrawals.by_earning_month(pick(d["events"]), pick(d["months"]), pick(d["requests"]), pick(d["reviews"]),
                                           referrals=d["referrals"])
    _table(earning, "No earnings yet.")
    st.markdown("**By payment month** — cash actually transferred")
    cash = withdrawals.by_payment_month(pick(d["payments"]), pick(d["reviews"]))
    _table(cash, "No payments recorded yet.")
    c1, c2 = st.columns(2)
    with c1:
        _download("Export by earning month (CSV)", earning, "withdrawals-by-earning-month", "rw_csv_cash_earning")
    with c2:
        _download("Export by payment month (CSV)", cash, "withdrawals-by-payment-month", "rw_csv_cash_payment")
    with st.expander("Definitions"):
        st.markdown("- **Earning month**: when the player earned the reward. **Withdrawal month**: when they requested "
                    "payment. **Payment month**: when you transferred the money.\n"
                    "- **Net verified earnings**: rewards earned minus rewards of referrals you rejected. A month with "
                    "a referral reward awaiting your review is not withdrawable until you approve or reject it.\n"
                    "- **Requested**: held by a request awaiting review or on hold. **Approved, awaiting payment**: "
                    "approved but not marked as paid. **Refused**: rewards of rejected referrals, a month disqualified "
                    "with a rejected request or rejected in a monthly review, or the part a monthly review did not "
                    "approve.\n"
                    "- **Remaining budget**: monthly budget × programme months so far − rewards earned + refused "
                    "rewards. An earned reward is a liability until it is paid or refused, so it is counted once.\n"
                    "- A rejected request without disqualification releases its months: the earnings become available "
                    "for a future legitimate request.\n"
                    "- Test records (owner/tester simulations) are excluded unless 'Include test records' is on.")


# --------------------------------------------------------------------------- entry point

def render(include_test: bool) -> None:
    if not analytics.is_owner():          # checked again here: knowing the page is never enough
        st.info("This page is not available.")
        return
    s = hooks.cashout_store(for_tester=True)
    st.markdown("### 💳 Withdrawal Management")
    if s is None:
        st.warning("The withdrawal tables are not set up yet. Run supabase/withdrawals_migration.sql "
                   "(WITHDRAWALS_SETUP.md). Players are not affected: the withdrawal card stays hidden.")
        return
    try:
        d = _load(s)
    except Exception:
        st.error("The withdrawal tables could not be read. Players are not affected.")
        return
    flash = st.session_state.pop("rw_cash_flash", None)
    if flash:
        st.success(flash)
    _switches(d)
    _live_notifications(s)
    _summary(d, include_test)
    st.markdown("#### Withdrawal requests")
    rows = _filters(d, include_test)
    names = _names(d)
    table = [_row(r, names, d) for r in rows]
    _table(table[:200], "No withdrawal requests match.")
    _download("Export withdrawals (CSV)", table, "withdrawals", "rw_csv_withdrawals")
    labels = {r["id"]: f"{r['reference']} · {names.get(r['profile_id'], '')} · {_naira(r['amount'])} · "
              f"{withdrawals.STATUS_LABELS[r['status']]}" + (" · TEST" if r.get("test") else "")
              for r in d["requests"]}
    options = [r["id"] for r in rows]
    # The open application is kept in our own session value (not the widget's), so it stays open when its status,
    # and therefore its label, changes after an action.
    pick = st.session_state.get("rw_cash_pick")
    if pick in labels and pick not in options:
        options = [pick] + options          # an application opened from a notification stays visible
    elif pick is not None and pick not in labels:
        pick = st.session_state.rw_cash_pick = None
    if options:
        chosen = st.selectbox("Open an application", options, format_func=labels.get,
                              index=options.index(pick) if pick in options else None,
                              placeholder="Choose a withdrawal request")
        if chosen != pick:
            st.session_state.rw_cash_pick = chosen
        req = next((r for r in d["requests"] if r["id"] == chosen), None)
        if req:
            _review(s, d, req)
    st.markdown("#### Financial accounting")
    _accounting(d, include_test)
