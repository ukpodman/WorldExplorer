"""📊 F&F 10 rewards — the Owner's management view for Friends & Family 10 (English only).

Rendered only after analytics.is_owner() on the server. Every amount comes from the database's own calculation
(pilot_month_days per participant, pilot_settlement_preview, pilot_settle_month); raw activity is loaded only for the
participant and month the owner opens (review flags and the CSV download).
Real cash: approved final allocations are paid by the owner as manual Nigerian bank transfers OUTSIDE the app; the
owner then records each transfer here (pilot_record_payment), after the monthly settlement, the beneficiary check and
approval, and only while the owner has authorised pilot payments. The app never moves money itself, and Public
Rewards, public payouts and withdrawals are not involved.
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
    "payments_disabled": "Pilot payments are not authorised. Authorise them in “Cash payments” first.",
    "terms_required": "Record the approved pilot terms first (🤝 Friends & Family 10 tab).",
    "not_settled": "This month is not settled yet.",
    "not_approved": "Approve this participant's final allocation first.",
    "already_paid": "A payment is already recorded for this participant and month.",
    "beneficiary_not_verified": "Verify this participant's identity and bank account name first.",
    "amount_mismatch": "The amount must equal the approved final allocation exactly.",
    "budget_exceeded": "This payment would exceed the month's settled total or the ₦50,000 budget.",
    "reference_required": "Enter the bank transfer reference.",
    "duplicate_reference": "This bank transfer reference is already recorded.",
    "invalid_date": "The transfer date cannot be in the future or before the settlement.",
    "invalid_account_last4": "Enter only the last 4 digits of the account number.",
    "details_required": "Enter the account holder's legal name and the bank.",
    "not_participant": "This person is not an approved, invited participant.",
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
    data["cash"] = s.ff10_payments_health() == "ok"
    data["payments"] = s.ff10_payments() if data["cash"] else []
    data["beneficiaries"] = {b["profile_id"]: b for b in s.ff10_beneficiaries()} if data["cash"] else {}
    data["payments_enabled"] = s.ff10_payments_enabled() if data["cash"] else False
    data["accepted"] = {a["profile_id"]: s.ff10_terms_accepted(a["profile_id"]) for a in approved}
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
    st.caption("Provisional amounts are calculated from verified learning. After a month ends you finalise its "
               "settlement (shared ₦50,000 budget), approve or withhold each final allocation, pay approved allocations "
               "by bank transfer from the company account, and record each transfer here.")
    _overview(d, month, today)
    st.divider()
    _cash(s, d)
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
    paid_total = sum(int(r["amount"]) for r in d["payments"])
    active = sum(1 for days in ledgers.values() if any(x.minutes > 0 for x in days))
    _tiles([("Invited", str(len(d["invitations"])), "active invitations"),
            ("Approved participants", f"{len(d['approved'])} / {pr.MAX_PARTICIPANTS}"),
            ("Active this month", str(active), "with verified learning time"),
            ("Monthly budget", _naira(pr.MONTHLY_BUDGET), month),
            ("Provisional this month", _naira(total), "before budget adjustment"),
            ("Remaining budget", _naira(max(pr.MONTHLY_BUDGET - total, 0)), "if the month ended now"),
            ("Pending settlement reviews", str(pending)),
            ("Approved, payment pending", _naira(approved_total), "all settled months"),
            ("Paid", _naira(paid_total), "recorded bank transfers")])
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
    _time_audit(s, d, pid, rows, chosen)
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


AUDIT_DAYS = ("2026-10-26", "2026-10-27")     # the reported days (owner may choose any other days of the month)


def _lagos_time(value) -> str:
    return rewards.lagos_now(value).strftime("%H:%M:%S") if value else "—"


def _time_audit(s, d: dict, pid: str, rows: list[dict], month: str) -> None:
    """READ-ONLY learning-time audit: why verified minutes differ from the time between first and last activity.
    Nothing here changes a record, a day review or an amount."""
    with st.expander("🔎 Learning-time audit (read-only)", key="ff10_audit"):
        st.caption("Shows each day's recorded interactions and activity checks, the time between the first and last of "
                   "them, the verified minutes, and every pause longer than 3 minutes (only 3 minutes of a longer pause "
                   "count). Elapsed time alone does not prove learning — a pause can be reading or an app left open. "
                   "This audit never changes records or amounts; any adjustment needs separate evidence and your own "
                   "decision, outside this tool.")
        days_with_activity = sorted({str(r["day"])[:10] for r in rows})
        options = sorted(set(days_with_activity) | {x for x in AUDIT_DAYS if x[:7] == month})
        if not options:
            st.caption("No activity in this month.")
            return
        default = [x for x in AUDIT_DAYS if x in options] or options[-2:]
        chosen = st.multiselect("Days", options, default=default, key="ff10_audit_days")
        try:
            beats = [b for b in s.ff10_heartbeats(pid, month) if not b.get("test")]
        except Exception:
            beats = []
        report = pr.audit_days(rows, beats, sorted(chosen))
        _table([{"Day": x["day"], "Interactions": x["interactions"], "Activity checks": x["heartbeats"],
                 "Qualifying quizzes": x["quizzes"], "Daily Challenge": "✓" if x["challenge"] else "",
                 "First": _lagos_time(x["first"]), "Last": _lagos_time(x["last"]),
                 "Elapsed min": round(x["elapsed"] / 60, 1), "Verified min": round(x["credited"] / 60, 1),
                 "Not counted min": round(x["uncredited"] / 60, 1), "Pauses > 3 min": len(x["gaps"])}
                for x in report], "No activity on the chosen days.")
        gaps = [{"Day": x["day"], "From": _lagos_time(g["start"]), "To": _lagos_time(g["end"]),
                 "Pause min": round(g["seconds"] / 60, 1), "Not counted min": round(g["uncredited"] / 60, 1),
                 "Before": f"{g['before'][0]}: {g['before'][1]}", "After": f"{g['after'][0]}: {g['after'][1]}"}
                for x in report for g in x["gaps"]]
        if gaps:
            st.markdown("**Pauses longer than 3 minutes** (Lagos time)")
            _table(gaps, "")
        if not beats:
            st.caption("No activity checks are recorded for these days: reading and exploring without clicking was not "
                       "measured before the active-time update, so a long pause cannot show whether the participant "
                       "was reading.")
        _download("Download audit (CSV)", gaps or [{"Day": x["day"], "Elapsed min": round(x["elapsed"] / 60, 1),
                                                     "Verified min": round(x["credited"] / 60, 1)} for x in report],
                  f"ff10-time-audit-{_short(pid)}-{month}", "ff10_audit_csv")


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
        one, two = st.columns(2)
        approve = one.form_submit_button("✅ Approve allocation")
        withhold = two.form_submit_button("✖ Withhold")
    if approve or withhold:
        action = "approve" if approve else "withhold"
        _act(lambda: s.ff10_decide(chosen, pid, action, _actor(), note or None),
             f"{_who(d, pid)}: {chosen} allocation {'approved — payment pending' if approve else 'withheld'}.")
    _record_payment(s, d, chosen, lines)


def _record_payment(s, d: dict, month: str, lines: list[dict]) -> None:
    """Record a manual bank transfer that has already been made from the company account."""
    st.markdown("**Record a bank transfer**")
    if not d["cash"]:
        return
    payable = [line for line in lines if line["status"] == "approved"]
    if not d["payments_enabled"]:
        st.caption("Pilot payments are not authorised yet (see “Cash payments” above).")
        return
    if not payable:
        st.caption("No approved allocation is waiting for payment in this month.")
        return
    with st.form("ff10_pay", border=True, clear_on_submit=True):
        pid = st.selectbox("Participant", [line["profile_id"] for line in payable], format_func=lambda p: (
            f"{_who(d, p)} · {_naira(next(x['final'] for x in payable if x['profile_id'] == p))}"), key="ff10_pay_pick")
        amount = st.number_input("Amount transferred (₦)", min_value=1, max_value=pr.MONTHLY_MAX, step=1,
                                 key="ff10_pay_amount")
        paid_on = st.date_input("Transfer date", value=rewards.lagos_now().date(), key="ff10_pay_date")
        reference = st.text_input("Bank transfer reference", max_chars=100, key="ff10_pay_ref")
        sure = st.checkbox("I confirm this transfer was made from the company account to the verified beneficiary, "
                           "for exactly this amount.", key="ff10_pay_confirm")
        submitted = st.form_submit_button("Record payment", type="primary")
    if submitted:
        _act(lambda: s.ff10_record_payment(month, pid, int(amount), paid_on.isoformat(), reference, _actor(),
                                           confirmed=sure),
             f"Payment recorded for {_who(d, pid)} ({month}).")


def readiness(d: dict) -> list[tuple[str, bool, str]]:
    """The private cash pilot's readiness checks: (requirement, met, detail). Nothing is filled in or assumed; each
    check reads the owner's own settings, the documents in legal/ and the database."""
    from core import legal
    cfg = legal.config()
    status = hooks.pilot_switch()
    terms_ok = status.get("terms_version") == legal.pilot_terms_id()
    record_issues = legal.approval_record_problems(cfg)
    record = legal.pilot_approval(cfg)
    rows = [
        ("Operator verified ([legal] operator_verified)", legal.operator_verified(cfg),
         "Your own confirmation that the company is the operator (legal/OPERATOR_VERIFICATION.md section A)."),
        ("Contact email and registered address", bool(legal.contact_email(cfg)) and bool(legal.registered_address(cfg)),
         "[legal] contact_email and registered_address."),
        ("Private-pilot approval record", not record_issues, "; ".join(record_issues) if record_issues else
         f"Approved by {record.get('approved_by')} on {str(record.get('approved_on'))[:10]}."),
    ]
    for key in legal.PILOT:
        issues = [i for i in legal.problems(key, cfg) if not i.startswith(legal.SHARED_PREFIXES)]
        rows.append((f"{legal.DOCUMENTS[key][0]} published", not issues,
                     "; ".join(issues[:3]) + (" …" if len(issues) > 3 else "") if issues else
                     f"Version {legal.version(key)} · SHA-256 {legal.checksum(key)}"))
    rows += [
        ("Approved private terms recorded", terms_ok, "🤝 Friends & Family 10 tab → Record the published pilot terms."),
        ("Invitation-only, at most 10 participants", len(d["approved"]) <= pr.MAX_PARTICIPANTS,
         f"{len(d['approved'])} approved."),
        ("Public Rewards OFF", not hooks.enabled(), "Must stay OFF for the private pilot."),
    ]
    return rows


def _approval_record() -> None:
    """The private-pilot approval record exactly as configured ([legal.pilot_approval]) next to the live files."""
    from core import legal
    record = legal.pilot_approval()
    st.markdown("**Private-pilot approval record**")
    rows = [{"Item": "Authorised decision-maker", "Recorded": str(record.get("approved_by") or "—"), "Current file": ""},
            {"Item": "Approval date", "Recorded": str(record.get("approved_on") or "—")[:10], "Current file": ""}]
    for key in legal.PILOT:
        title = legal.DOCUMENTS[key][0]
        rows.append({"Item": f"{title}: version", "Recorded": str(record.get(f"{key}_version") or "—"),
                     "Current file": legal.version(key)})
        rows.append({"Item": f"{title}: SHA-256", "Recorded": str(record.get(f"{key}_sha256") or "—"),
                     "Current file": legal.checksum(key)})
    _table(rows)
    st.caption("Set these in Streamlit secrets under [legal.pilot_approval] (approved_by, approved_on, pilot_version, "
               "pilot_sha256, pilot_privacy_version, pilot_privacy_sha256) after approving the exact files. Any later "
               "change to a document unpublishes it until the record matches again.")


def _cash(s, d: dict) -> None:
    st.markdown("#### 💵 Cash payments (private pilot)")
    if not d["cash"]:
        st.warning("Real cash payments are not installed in the database yet. After review and your approval, run "
                   "supabase/friends_family10_payments_migration.sql in Supabase.")
        return
    checks = readiness(d)
    _table([{"Requirement": name, "Status": "✅" if ok else "❌", "Detail": detail} for name, ok, detail in checks])
    _approval_record()
    accepted = sum(1 for a in d["approved"] if d["accepted"].get(a["profile_id"]))
    st.caption(f"Participants who accepted the current private terms: {accepted} / {len(d['approved'])}. Others "
               "earn nothing until they accept them on their participant page.")
    missing = [name for name, ok, _ in checks if not ok]
    if d["payments_enabled"]:
        st.success("Pilot payments are authorised. Pay approved allocations by bank transfer, then record them.")
        if missing:
            st.warning("Some readiness checks no longer pass: " + "; ".join(missing) + ". Consider suspending payments.")
        if st.button("Suspend pilot payments", key="ff10_payments_off"):
            _act(lambda: s.ff10_set_payments(False, _actor()), "Pilot payments were suspended.")
    else:
        if missing:
            st.info("Pilot payments can be authorised once every check above passes.")
        sure = st.checkbox("I authorise real cash payments for approved Friends & Family 10 allocations. The legal "
                           "requirements above have genuinely been met.", key="ff10_payments_confirm",
                           disabled=bool(missing))
        if st.button("Authorise pilot payments", key="ff10_payments_on", type="primary",
                     disabled=bool(missing) or not sure):
            _act(lambda: s.ff10_set_payments(True, _actor(), confirmed=True), "Pilot payments were authorised.")
    _beneficiaries(s, d)
    if d["payments"]:
        rows = [{"Month": r["month"], "Participant": _who(d, r["profile_id"]), "Beneficiary": r["beneficiary_name"],
                 "Bank": r["bank_name"], "Account": "••••" + r["account_last4"], "Amount": _naira(r["amount"]),
                 "Date": str(r["paid_on"])[:10], "Reference": r["bank_reference"], "Status": r["status"],
                 "Recorded by": r["recorded_by"]} for r in reversed(d["payments"])]
        st.markdown("**Payment ledger**")
        _table(rows)
        _download("Download payment ledger (CSV)", rows, "ff10-payments", "ff10_pay_csv")


def _beneficiaries(s, d: dict) -> None:
    people = [a["profile_id"] for a in d["approved"]]
    st.markdown("**Beneficiary verification** (identity and bank account name checked by you; only the last 4 digits "
                "of the account are kept)")
    _table([{"Participant": _who(d, pid), "Verified": "✅" if d["beneficiaries"].get(pid) else "—",
             "Name": (d["beneficiaries"].get(pid) or {}).get("legal_name", ""),
             "Bank": (d["beneficiaries"].get(pid) or {}).get("bank_name", ""),
             "Account": ("••••" + d["beneficiaries"][pid]["account_last4"]) if d["beneficiaries"].get(pid) else ""}
            for pid in people], "No approved participants yet.")
    if not people:
        return
    with st.form("ff10_beneficiary", border=True, clear_on_submit=True):
        pid = st.selectbox("Participant", people, format_func=lambda p: _who(d, p), key="ff10_ben_pick")
        name = st.text_input("Account holder's legal name (as on the bank account and ID)", max_chars=120,
                             key="ff10_ben_name")
        bank = st.text_input("Bank", max_chars=80, key="ff10_ben_bank")
        last4 = st.text_input("Last 4 digits of the account number", max_chars=4, key="ff10_ben_last4")
        note = st.text_input("How you verified (optional)", max_chars=500, key="ff10_ben_note")
        sure = st.checkbox("I have checked this person's identity and that the account name matches.",
                           key="ff10_ben_confirm")
        submitted = st.form_submit_button("Save verification")
    if submitted:
        _act(lambda: s.ff10_verify_beneficiary(pid, name, bank, last4, _actor(), confirmed=sure, note=note or None),
             f"Beneficiary verified for {_who(d, pid)}.")
