"""💰 Rewards & Referral Management — the owner's part of the Owner dashboard (English only).

Access: ui/owner.render checks analytics.is_owner() on the server before calling render(); this module checks again,
so knowing a page or widget name is never enough. All reads and writes go through the server-side store; the money
rules are enforced again by the database (amount caps, frozen earnings, payment checks, audit log).
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date
from html import escape

import streamlit as st

from core import accounts, analytics, metrics, rewards
from core.rewards import Settings
from core.rewards_store import StoreError

from . import rewards_hooks as hooks

DATA_TTL = 30


def _naira(amount) -> str:
    return "—" if amount is None else f"₦{int(amount):,}"


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _tile(label: str, value: str, note: str = "") -> str:
    return (f'<div class="owner-tile"><span>{escape(label)}</span><b>{escape(str(value))}</b>'
            f'{f"<small>{escape(note)}</small>" if note else ""}</div>')


def _tiles(items: list[tuple]) -> None:
    st.html('<div class="owner-grid">' + "".join(_tile(*item) for item in items) + "</div>")


def _table(rows: list[dict], empty: str = "No records yet.") -> None:
    if not rows:
        st.caption(empty)
        return
    head = "".join(f"<th>{escape(str(k))}</th>" for k in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{escape(str(v if v is not None else ''))}</td>" for v in r.values()) + "</tr>"
                   for r in rows)
    st.html(f'<div class="owner-table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def _csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    out = io.StringIO()
    columns = list(dict.fromkeys(k for r in rows for k in r))
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return ("﻿" + out.getvalue()).encode("utf-8")   # BOM: Excel opens UTF-8 (₦, names) correctly


def _download(label: str, rows: list[dict], name: str, key: str) -> None:
    st.download_button(label, _csv(rows), file_name=f"{name}-{date.today().isoformat()}.csv", mime="text/csv",
                       key=key, disabled=not rows, icon=":material/download:")


def _short(pid: str | None) -> str:
    return (pid or "")[:10]


def _actor() -> str:
    who = accounts.identity() or {}
    return str(who.get("email") or "owner")


# --------------------------------------------------------------------------- data

def _invalidate() -> None:
    st.session_state.pop("rw_owner_data", None)


def _load(s) -> dict:
    cached = st.session_state.get("rw_owner_data")
    if cached and time.time() - cached["at"] < DATA_TTL:
        return cached
    data = {"at": time.time(), "settings": s.settings(), "accounts": s.accounts(), "enrolments": s.enrolments(),
            "events": s.events(), "referrals": s.referrals(), "visits": s.visits(), "payments": s.payments(),
            "audit": s.audit(500)}
    st.session_state.rw_owner_data = data
    return data


def _real(rows: list[dict], include_test: bool) -> list[dict]:
    return rows if include_test else [r for r in rows if not r.get("test")]


@st.cache_data(ttl=120, show_spinner=False)
def _analytics_events() -> list[dict]:
    return analytics.fetch(analytics.EVENTS_TABLE, "occurred_at,event,anon_id,linked_id,test",
                           "occurred_at.asc,event_key.asc")


# --------------------------------------------------------------------------- sections

def _status_panel(s) -> None:
    flags = [("Programme (enabled)", "ON" if hooks.enabled() else "OFF"),
             ("Payouts (payouts_active)", "ON" if hooks.payouts_active() else "OFF"),
             ("Storage", {"ok": "Supabase tables ready", "missing_tables": "Run supabase/rewards_schema.sql",
                          "no_storage": "No Supabase storage", "error": "Not reachable"}[hooks.store_health()])]
    _tiles([(k, v) for k, v in flags])
    if hooks.preview_store():
        st.warning("Preview mode: the rewards tables are not set up, so records are kept in this server's memory "
                   "and disappear when the app restarts. Follow REWARDS_SETUP.md to create the tables.")
    if not hooks.enabled():
        st.info("The public programme is switched off. Only owners and listed testers see 💰 Rewards; all their "
                "records are test records and are never payable.")
    if not hooks.payouts_active():
        st.caption("Payouts are switched off: payments cannot be approved or marked as paid until you set "
                   "[rewards] payouts_active = true after legal and compliance review.")


def _overview(d: dict, month: str, include_test: bool) -> None:
    settings: Settings = d["settings"]
    accounts_ = _real(d["accounts"], include_test)
    enrol = [e for e in _real(d["enrolments"], include_test) if e["month"] == month]
    events = _real(d["events"], include_test)
    month_events = [e for e in events if e["month"] == month]
    payments = [p for p in _real(d["payments"], include_test) if p["month"] == month]
    referrals = _real(d["referrals"], include_test)
    visits = _real(d["visits"], include_test)

    st.markdown("#### User analytics")
    registered = hooks.registered_users()
    new_this_month = sum(1 for a in accounts_ if a.get("new_registration") and str(a.get("created_at", ""))[:7] == month)
    active_people = len({e["profile_id"] for e in month_events})
    activity = None
    if analytics.enabled():
        try:
            prepared, _ = metrics.prepare(_analytics_events(), include_test)
            activity = rewards.activity_overview(prepared)
        except Exception:
            activity = None
    participants = [e["profile_id"] for e in enrol if e["status"] == "enrolled"]
    items = [("Total registered users", "—" if registered is None else f"{registered:,}", "saved profiles"),
             ("New registrations", str(new_this_month), month),
             ("Rewards participants", str(len(participants)), f"of {settings.max_places} places"),
             ("Waiting list", str(sum(1 for e in enrol if e["status"] == "waitlist")), month),
             ("Active in programme", str(active_people), "people with rewards activity this month")]
    if activity:
        items += [("Daily active users", str(activity["dau"]), "today (Nigeria time)"),
                  ("Weekly active users", str(activity["wau"]), "last 7 days"),
                  ("Monthly active users", str(activity["mau"]), "last 30 days"),
                  ("7-day retention", _pct(activity["retention7"]["pct"]),
                   f"{activity['retention7']['n']} of {activity['retention7']['d']}"),
                  ("30-day retention", _pct(activity["retention30"]["pct"]),
                   f"{activity['retention30']['n']} of {activity['retention30']['d']}")]
    _tiles(items)
    if not activity:
        st.caption("Daily, weekly and monthly active users and retention come from pilot measurement — switch on "
                   "[analytics] (SETUP_ANALYTICS.md) to see them.")

    st.markdown("#### Referral analytics")
    r = rewards.referral_overview(accounts_, visits, referrals, events)
    _tiles([("Referral links generated", str(r["links"])), ("Referral link visits", str(r["visits"])),
            ("Registrations from referrals", str(r["registrations"])),
            ("Successful verified referrals", str(r["approved"]), f"{r['qualified']} completed, awaiting review"),
            ("Pending referrals", str(r["pending"])),
            ("Referral conversion rate", _pct(r["conversion"]), f"success rate {_pct(r['success_rate'])}"),
            ("Referral earnings", _naira(r["earnings"]), "all months")])

    st.markdown("#### Financial analytics")
    f = rewards.budget_figures(settings, enrol, month_events, payments)
    cost = rewards.cost_per_retained(month_events, participants)
    _tiles([("Allocated monthly budget", _naira(f["allocated"])), ("Reserved budget", _naira(f["reserved"])),
            ("Rewards earned", _naira(f["earned"])), ("Pending payment amounts", _naira(f["pending"])),
            ("Approved payments", _naira(f["approved"])), ("Completed payments", _naira(f["paid"])),
            ("Remaining unreserved budget", _naira(f["unreserved"])),
            ("Average reward per participant", _naira(f["average"])),
            ("Cost per retained active user", _naira(cost["cost"]), f"{cost['retained']} with 3+ active days")])
    if f["reserved"] > settings.monthly_budget:
        st.warning("Reserved budget is above the current monthly budget (the budget was lowered after people "
                   "joined). Existing places and earnings are kept; nobody new is enrolled until it fits again.")
    with st.expander("Definitions"):
        for text in rewards.ANALYTICS_DEFINITIONS.values():
            st.markdown(f"- {text}")


def _budget(s, d: dict, month: str) -> None:
    settings: Settings = d["settings"]
    enrol = [e for e in d["enrolments"] if e["month"] == month and not e.get("test")]
    f = rewards.budget_figures(settings, enrol, [e for e in d["events"] if e["month"] == month and not e.get("test")],
                               [p for p in d["payments"] if p["month"] == month and not p.get("test")])
    _tiles([("Monthly budget", _naira(settings.monthly_budget)), ("Places", str(settings.max_places),
             f"budget funds {settings.places_by_budget()}"),
            ("Places taken", str(f["participants"])), ("Waiting list", str(f["waitlist"])),
            ("Reserved", _naira(f["reserved"])), ("Unreserved", _naira(f["unreserved"]))])
    st.progress(min(f["reserved"] / settings.monthly_budget, 1.0) if settings.monthly_budget else 0.0,
                text=f"Reserved {_naira(f['reserved'])} of {_naira(settings.monthly_budget)}")
    waiting = sorted((e for e in enrol if e["status"] == "waitlist"), key=lambda e: e.get("waitlist_position") or 0)
    if waiting:
        st.caption("Waiting list (first come, first served): " + ", ".join(
            f"#{e['waitlist_position']} {_short(e['profile_id'])}" for e in waiting[:20]))
    if st.button("Move people from the waiting list into free places", key="rw_promote", disabled=not waiting):
        moved = s.promote(month, _actor())
        _invalidate()
        st.success(f"{moved} participant(s) moved from the waiting list.")


def _participants(s, d: dict, include_test: bool) -> None:
    accounts_ = _real(d["accounts"], include_test)
    query = st.text_input("Search by email, name, referral code or profile id", key="rw_owner_search").strip().lower()
    month = rewards.month_key()
    rows = []
    for a in accounts_:
        hay = " ".join(str(a.get(k) or "") for k in ("email", "display_name", "referral_code", "profile_id")).lower()
        if query and query not in hay:
            continue
        enrol = next((e for e in d["enrolments"] if e["profile_id"] == a["profile_id"] and e["month"] == month), None)
        earned = sum(int(e.get("amount") or 0) for e in d["events"] if e["profile_id"] == a["profile_id"] and e["month"] == month)
        rows.append({"Profile": _short(a["profile_id"]), "Email": a.get("email") or "", "Name": a.get("display_name") or "",
                     "Code": a["referral_code"], "Membership": a["membership"], "This month": (enrol or {}).get("status", ""),
                     "Earned (month)": earned, "Verification": a["verification"], "Review": a["review"],
                     "New account": "yes" if a.get("new_registration") else "", "Test": "test" if a.get("test") else ""})
    _table(rows[:200], "No matching accounts.")
    if len(rows) > 200:
        st.caption(f"Showing 200 of {len(rows)} — refine the search.")
    _download("Export participants (CSV)", rows, "rewards-participants", "rw_csv_participants")
    if not rows:
        return
    options = [a["profile_id"] for a in accounts_ if _short(a["profile_id"]) in {r["Profile"] for r in rows}]
    labels = {a["profile_id"]: f"{a.get('email') or a.get('display_name') or 'account'} · {a['referral_code']} · "
              f"{_short(a['profile_id'])}" for a in accounts_}
    pid = st.selectbox("Open an account", options, format_func=lambda p: labels.get(p, p), index=None,
                       placeholder="Choose an account", key="rw_owner_pick")
    if pid:
        _participant_detail(s, d, pid)


def _participant_detail(s, d: dict, pid: str) -> None:
    account = next(a for a in d["accounts"] if a["profile_id"] == pid)
    events = [e for e in d["events"] if e["profile_id"] == pid]
    made = [r for r in d["referrals"] if r["referrer_id"] == pid]
    visits = [v for v in d["visits"] if v.get("referrer_id") == pid]
    flags = rewards.fraud_signals(account, events, made, visits)
    with st.container(border=True):
        st.markdown(f"**{escape(account.get('email') or account.get('display_name') or 'Account')}** · "
                    f"code {account['referral_code']} · joined {str(account.get('created_at'))[:10]}"
                    + (" · TEST" if account.get("test") else ""))
        st.caption(f"Declarations: 18+ {'yes' if account.get('age_confirmed') else 'no'}, Nigeria "
                   f"{'yes' if account.get('residence_confirmed') else 'no'}, terms {account.get('terms_version') or '—'} "
                   f"({str(account.get('declared_at') or '')[:10]}). Self-declared = provisional until verified.")
        for flag in flags:
            st.warning(flag)
        with st.form(f"rw_account_{pid}", border=False):
            c1, c2, c3 = st.columns(3)
            verification = c1.selectbox("Eligibility verification", ["provisional", "verified", "failed"],
                                        index=["provisional", "verified", "failed"].index(account["verification"]))
            review = c2.selectbox("Review", ["ok", "review", "hold"], index=["ok", "review", "hold"].index(account["review"]))
            membership = c3.selectbox("Membership", ["none", "member", "withdrawn", "suspended"],
                                      index=["none", "member", "withdrawn", "suspended"].index(account["membership"]))
            note = st.text_input("Note (verification method, reason for review)", value=account.get("review_note") or "",
                                 max_chars=300)
            if st.form_submit_button("Save account status"):
                changes = {"verification": verification, "review": review, "review_note": note or None,
                           "verification_note": note or None}
                if membership != account["membership"]:
                    if membership == "member" and not account.get("terms_version"):
                        st.error("This person has not made the declarations; they must join from 💰 Rewards.")
                        return
                    changes["membership"] = membership
                try:
                    s.update_account(pid, changes)
                    s.log(_actor(), "account_status", pid, changes)
                    _invalidate()
                    st.success("Saved (recorded in the audit log).")
                except StoreError as error:
                    st.error(str(error))
        st.markdown("**Activity history**")
        history = [{"When": str(e.get("created_at"))[:16].replace("T", " "), "Day": e["day"], "Kind": e["kind"],
                    "Subject": e["subject"] if e["kind"] != "referral" else _short(e["subject"]),
                    "Amount": e["amount"], "Reason": e.get("reason") or "",
                    "Detail": ", ".join(f"{k}={v}" for k, v in (e.get("detail") or {}).items())}
                   for e in reversed(events)]
        _table(history[:300], "No activity recorded.")
        _download("Export this person's activity (CSV)", history, f"rewards-activity-{_short(pid)}", f"rw_csv_hist_{pid}")
        by_month = {}
        for e in events:
            by_month.setdefault(e["month"], []).append(e)
        _table([{"Month": m, **{rewards.KIND_LABELS[k]: v["amount"] for k, v in rewards.summarize(evs).items() if k != "total"},
                 "Total": rewards.summarize(evs)["total"]} for m, evs in sorted(by_month.items(), reverse=True)])
        referred_by = next((r for r in d["referrals"] if r["referred_id"] == pid), None)
        if referred_by:
            st.caption(f"Referred by {_short(referred_by['referrer_id'])} ({referred_by['status']}).")
        if made:
            st.markdown("**Referrals made**")
            _table([{"Friend": _short(r["referred_id"]), "Joined": str(r.get("created_at"))[:10], "Status": r["status"],
                     "Qualified": str(r.get("qualified_at") or "")[:10]} for r in made])
        pays = [p for p in d["payments"] if p["profile_id"] == pid]
        if pays:
            st.markdown("**Payments**")
            _table([_payment_row(p) for p in pays])


def _payment_row(p: dict) -> dict:
    return {"Profile": _short(p["profile_id"]), "Month": p["month"], "Earned": p["earned"],
            "Approved": p["approved_amount"], "Paid": p["paid_amount"], "Status": rewards.PAYMENT_LABELS[p["status"]],
            "Payment date": p.get("payment_date") or "", "Reference": p.get("reference") or "",
            "Remarks": p.get("remarks") or "", "Updated by": p.get("updated_by") or "",
            "Updated": str(p.get("updated_at") or "")[:16].replace("T", " "), "Test": "test" if p.get("test") else ""}


def _payments(s, d: dict, include_test: bool) -> None:
    months = sorted({e["month"] for e in d["events"]} | {rewards.month_key()}, reverse=True)
    month = st.selectbox("Month", months, key="rw_pay_month")
    earned_by = {}
    for e in d["events"]:
        if e["month"] == month and int(e.get("amount") or 0) > 0:
            earned_by[(e["profile_id"], bool(e.get("test")))] = earned_by.get((e["profile_id"], bool(e.get("test"))), 0) + int(e["amount"])
    existing = {(p["profile_id"], p["month"]) for p in d["payments"]}
    missing = [(pid, test) for (pid, test) in earned_by if (pid, month) not in existing and (include_test or not test)]
    st.caption("A payment review records what each participant earned in the month. Approving needs verified "
               "eligibility and active payouts; marking as paid is always a separate, manual step.")
    if st.button(f"Open payment reviews for {len(missing)} participant(s) with earnings", key="rw_open_reviews",
                 disabled=not missing):
        for pid, test in missing:
            s.open_payment(pid, month, test, _actor())
        _invalidate()
        st.rerun()
    pays = [p for p in _real(d["payments"], include_test) if p["month"] == month]
    _table([_payment_row(p) for p in pays], "No payment reviews for this month yet.")
    _download("Export payments (CSV)", [_payment_row(p) for p in _real(d["payments"], include_test)],
              "rewards-payments", "rw_csv_payments")
    if not pays:
        return
    labels = {p["profile_id"]: f"{_short(p['profile_id'])} · earned {_naira(p['earned'])} · "
              f"{rewards.PAYMENT_LABELS[p['status']]}" for p in pays}
    pid = st.selectbox("Update a payment", list(labels), format_func=labels.get, index=None,
                       placeholder="Choose a participant", key="rw_pay_pick")
    if not pid:
        return
    current = next(p for p in pays if p["profile_id"] == pid)
    earned_now = sum(int(e.get("amount") or 0) for e in d["events"] if e["profile_id"] == pid and e["month"] == month)
    account = next((a for a in d["accounts"] if a["profile_id"] == pid), {})
    referral_events = [e for e in d["events"] if e["profile_id"] == pid and e["month"] == month and e["kind"] == "referral"
                       and int(e.get("amount") or 0) > 0]
    unapproved = [e for e in referral_events
                  if next((r for r in d["referrals"] if r["referred_id"] == e["subject"]), {}).get("status") != "approved"]
    if unapproved:
        st.warning(f"{len(unapproved)} referral reward(s) this month belong to referrals not yet approved. Validate the "
                   "referred accounts in the Referrals tab, or approve a lower amount.")
    if account.get("verification") != "verified":
        st.warning("Eligibility is not verified yet (self-declared only). Verify it in Participants before approving.")
    with st.form(f"rw_pay_{pid}_{month}", border=True):
        status = st.selectbox("Status", list(rewards.PAYMENT_LABELS), format_func=rewards.PAYMENT_LABELS.get,
                              index=list(rewards.PAYMENT_LABELS).index(current["status"]))
        c1, c2 = st.columns(2)
        approved = c1.number_input("Approved amount (₦)", min_value=0, max_value=max(earned_now, 0), step=5,
                                   value=int(current["approved_amount"] or earned_now))
        paid = c2.number_input("Paid amount (₦)", min_value=0, max_value=max(earned_now, 0), step=5,
                               value=int(current["paid_amount"] or current["approved_amount"] or 0))
        pay_date = st.date_input("Payment date", value=date.fromisoformat(str(current["payment_date"])[:10])
                                 if current.get("payment_date") else None)
        reference = st.text_input("Transaction reference (optional)", value=current.get("reference") or "", max_chars=120)
        remarks = st.text_area("Payment remarks", value=current.get("remarks") or "", max_chars=1000)
        reason = st.text_input("Reason (required for On hold or Rejected)", value=current.get("reason") or "", max_chars=500)
        confirm = st.checkbox("I confirm this update (for Paid: the money was sent outside World Explorer)")
        if st.form_submit_button("Save payment update", type="primary"):
            if status in ("approved", "paid") and not hooks.payouts_active():
                st.error("Payouts are switched off ([rewards] payouts_active = false). Payments cannot be approved or "
                         "marked as paid yet.")
                return
            if not confirm:
                st.error("Please tick the confirmation box.")
                return
            if status in ("on_hold", "rejected") and not reason.strip():
                st.error("Please give a reason.")
                return
            amount = approved if status == "approved" else (paid if status == "paid" else None)
            changes, error = rewards.payment_transition(current, status, amount, earned_now)
            if error:
                st.error(error)
                return
            changes.update(reference=reference.strip() or None, remarks=remarks.strip() or None,
                           reason=reason.strip() or None)
            if status == "paid":
                if not pay_date:
                    st.error("Enter the payment date.")
                    return
                changes["payment_date"] = pay_date.isoformat()
            try:
                s.update_payment(pid, month, changes, _actor())
                _invalidate()
                st.success("Payment updated (recorded in the audit log).")
            except StoreError as err:
                st.error(str(err))


def _referrals_tab(s, d: dict, include_test: bool) -> None:
    referrals = _real(d["referrals"], include_test)
    email = {a["profile_id"]: a.get("email") or a.get("display_name") or "" for a in d["accounts"]}
    rows = []
    for r in reversed(referrals):
        progress = rewards.referral_progress(rewards.activity_totals([e for e in d["events"] if e["profile_id"] == r["referred_id"]]))
        rows.append({"Referrer": f"{_short(r['referrer_id'])} {email.get(r['referrer_id'], '')}".strip(),
                     "Referred": f"{_short(r['referred_id'])} {email.get(r['referred_id'], '')}".strip(),
                     "Code": r["code"], "Joined": str(r.get("created_at"))[:10], "Status": r["status"],
                     "Progress": " · ".join(f"{k} {a}/{b}" for k, (a, b) in progress.items()),
                     "Qualified": str(r.get("qualified_at") or "")[:10], "Decided by": r.get("decided_by") or "",
                     "Test": "test" if r.get("test") else ""})
    _table(rows, "No referrals yet.")
    _download("Export referrals (CSV)", rows, "rewards-referrals", "rw_csv_referrals")
    visits = _real(d["visits"], include_test)
    if visits:
        outcomes = {}
        for v in visits:
            outcomes[v["outcome"]] = outcomes.get(v["outcome"], 0) + 1
        st.caption("Link visits by outcome: " + ", ".join(f"{k} {n}" for k, n in sorted(outcomes.items())))
    pending = [r for r in referrals if r["status"] == "qualified"]
    if not pending:
        return
    st.markdown("**Validate completed referrals** — check both accounts (Participants tab) before approving.")
    labels = {r["referred_id"]: f"{_short(r['referrer_id'])} → {_short(r['referred_id'])} (qualified "
              f"{str(r.get('qualified_at') or '')[:10]})" for r in pending}
    pick = st.selectbox("Referral", list(labels), format_func=labels.get, index=None, key="rw_ref_pick",
                        placeholder="Choose a completed referral")
    if pick:
        note = st.text_input("Note", key="rw_ref_note", max_chars=300)
        c1, c2 = st.columns(2)
        decision = None
        if c1.button("Approve referral", key="rw_ref_ok", type="primary"):
            decision = "approved"
        if c2.button("Reject referral", key="rw_ref_no"):
            decision = "rejected"
        if decision:
            from datetime import datetime, timezone
            s.update_referral(pick, {"status": decision, "decided_at": datetime.now(timezone.utc).isoformat(),
                                     "decided_by": _actor(), "note": note or None})
            _invalidate()
            st.success(f"Referral {decision}. Earned rewards are never changed automatically; approve the right "
                       "amount in Payments.")


def _fraud(d: dict, include_test: bool) -> None:
    flags = {}
    for a in _real(d["accounts"], include_test):
        pid = a["profile_id"]
        flags[pid] = rewards.fraud_signals(a, [e for e in d["events"] if e["profile_id"] == pid],
                                           [r for r in d["referrals"] if r["referrer_id"] == pid],
                                           [v for v in d["visits"] if v.get("referrer_id") == pid])
    o = rewards.fraud_overview(flags)
    _tiles([("Suspicious registrations", str(o["registrations"])), ("Duplicate referral attempts", str(o["duplicates"])),
            ("Unusual quiz activity", str(o["quiz"])), ("Suspicious earning patterns", str(o["earning"])),
            ("Accounts requiring manual review", str(o["review"])), ("Accounts with any signal", str(o["flagged"]))])
    st.caption("Signals are prompts for a manual look, never automatic blocks. Several people sharing a home or a "
               "device are not treated as fraud. No device fingerprinting is used.")
    rows = [{"Profile": _short(pid), "Email": next((a.get("email") or "" for a in d["accounts"] if a["profile_id"] == pid), ""),
             "Signals": " | ".join(f)} for pid, f in flags.items() if f]
    _table(rows, "No signals.")
    _download("Export fraud signals (CSV)", rows, "rewards-fraud", "rw_csv_fraud")


def _settings_tab(s, d: dict) -> None:
    settings: Settings = d["settings"]
    st.caption("Changes apply from now on. Rewards already earned and places already taken are never reduced. "
               "Every change is recorded in the audit log.")
    paused = st.toggle("Pause the programme (no new rewards or enrolments; earnings are kept)", value=settings.paused,
                       key="rw_set_paused")
    if paused != settings.paused:
        new = Settings(**{**settings.as_row(), "paused": paused})
        problems = s.save_settings(new, _actor())
        _invalidate()
        st.success("Programme paused." if paused else "Programme resumed.") if not problems else st.error(problems[0])
    with st.form("rw_settings", border=True):
        st.markdown("**Budget and places (future enrolments)**")
        c1, c2 = st.columns(2)
        budget = c1.number_input("Monthly budget (₦)", min_value=0, step=1000, value=settings.monthly_budget)
        places = c2.number_input("Places", min_value=0, step=1, value=settings.max_places)
        st.markdown("**Rewards per activity and limits**")
        c1, c2, c3 = st.columns(3)
        cap = c1.number_input("Monthly maximum per person (₦)", min_value=1, step=50, value=settings.monthly_cap)
        start = c2.date_input("Programme start date", value=date.fromisoformat(settings.start_date))
        c3.caption("Keep the per-person maximum reachable without referrals.")
        values = {}
        for kind, fields_ in (("Active day", ("active_day_amount", "active_day_max")),
                              ("Quiz", ("quiz_amount", "quiz_max_month", "quiz_max_day")),
                              ("Country", ("country_amount", "country_max_month", "country_max_day")),
                              ("Referral", ("referral_amount", "referral_max_month"))):
            cols = st.columns(3)
            for col, name in zip(cols, fields_):
                label = {"amount": f"{kind}: ₦ each", "max": f"{kind}: per month", "month": f"{kind}: per month",
                         "day": f"{kind}: per day"}[name.rsplit("_", 1)[1]]
                values[name] = col.number_input(label, min_value=0, step=1, value=int(getattr(settings, name)), key=f"rw_{name}")
        if st.form_submit_button("Save settings", type="primary"):
            new = Settings(**{**settings.as_row(), **values, "monthly_budget": int(budget), "max_places": int(places),
                              "monthly_cap": int(cap), "start_date": start.isoformat()})
            problems = s.save_settings(new, _actor())
            if problems:
                for p in problems:
                    st.error(p)
            else:
                _invalidate()
                st.success("Settings saved.")
                if new.places_by_budget() < new.max_places:
                    st.info(f"The budget funds {new.places_by_budget()} full places; enrolment stops at whichever "
                            "limit is reached first.")


def _audit_tab(d: dict) -> None:
    rows = [{"When (UTC)": str(a.get("at"))[:19].replace("T", " "), "Actor": a.get("actor") or "", "Action": a["action"],
             "Target": _short(a.get("target")) if a.get("target") and len(str(a.get("target"))) > 40 else (a.get("target") or ""),
             "Change": _change(a)} for a in d["audit"]]
    _table(rows[:300], "No changes recorded yet.")
    _download("Export audit log (CSV)", rows, "rewards-audit", "rw_csv_audit")


def _change(entry: dict) -> str:
    old, new = entry.get("old_value") or {}, entry.get("new_value") or {}
    if not isinstance(new, dict):
        return str(new)
    if old:
        keys = [k for k in new if k not in ("updated_at", "updated_by") and old.get(k) != new.get(k)]
        return ", ".join(f"{k}: {old.get(k)} → {new.get(k)}" for k in keys)[:300]
    return ", ".join(f"{k}={v}" for k, v in new.items() if k not in ("updated_at",))[:300]


def _test_tools(s) -> None:
    with st.expander("Test records"):
        st.caption("Owner and tester activity is stored with test = true: excluded from all figures above unless "
                   "'Include test records' is on, and never payable.")
        sure = st.checkbox("Delete all test records (real records cannot be deleted)", key="rw_clear_sure")
        if st.button("Clear test records", key="rw_clear", disabled=not sure):
            s.clear_test_data(_actor())
            _invalidate()
            st.success("Test records cleared.")


# --------------------------------------------------------------------------- entry point

def render() -> None:
    if not analytics.is_owner():
        st.info("This page is not available.")
        return
    st.subheader("💰 Rewards & Referral Management")
    s = hooks.store(for_tester=True)
    if not s:
        st.warning("Rewards storage is not available.")
        return
    _status_panel(s)
    top1, top2 = st.columns([1, 1], vertical_alignment="bottom")
    include_test = top1.toggle("Include test records", key="rw_include_test")
    if top2.button("Refresh", key="rw_refresh"):
        _invalidate()
    try:
        d = _load(s)
    except Exception:
        st.error("The rewards tables could not be read. Check that supabase/rewards_schema.sql was run. Players are "
                 "not affected.")
        return
    month = rewards.month_key()
    from . import owner_withdrawals   # 💳 Withdrawal Management (V21)
    cash = hooks.cashout_store(for_tester=True)
    waiting = owner_withdrawals.unread_count() if cash else 0     # the same unread number as the 🔔 alert
    tabs = st.tabs([f"💳 Withdrawals ({waiting})", "Overview", "Budget", "Participants", "Payments", "Referrals",
                    "Fraud", "Settings", "Audit log"])
    with tabs[0]:
        owner_withdrawals.render(include_test)
    with tabs[1]:
        _overview(d, month, include_test)
    with tabs[2]:
        _budget(s, d, month)
    with tabs[3]:
        _participants(s, d, include_test)
    with tabs[4]:
        _payments(s, d, include_test)
    with tabs[5]:
        _referrals_tab(s, d, include_test)
    with tabs[6]:
        _fraud(d, include_test)
    with tabs[7]:
        _settings_tab(s, d)
    with tabs[8]:
        _audit_tab(d)
    _test_tools(s)
