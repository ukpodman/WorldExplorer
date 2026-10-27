"""🤝 Friends & Family 10 — the participant's learning progress and provisional rewards.

Shown on the participant page to approved participants (and, with test records, to owners and testers). Real
participants' figures come from the database's own calculation (pilot_month_days); test accounts' figures are
calculated here with the same rules (core/pilot_rewards.py). Provisional amounts are estimates until the monthly
settlement (the shared budget may reduce them); approved final allocations are paid in real naira by bank transfer.
"""
from __future__ import annotations

import time

import streamlit as st

from core import legal
from core import pilot_rewards as pr
from core import rewards
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from .state import t

TIER_TEXT = (
    "15 minutes and 1 qualifying quiz",
    "30 minutes and 2 qualifying quizzes",
    "45 minutes and a country you have not explored before",
    "60 minutes and today's Daily Challenge",
)
LINE_TEXT = {"pending_review": "Waiting for the Owner's review", "approved": "Approved — bank transfer pending",
             "withheld": "Withheld after review", "paid": "Paid by bank transfer"}
CACHE_SECONDS = 60


def _naira(amount: int) -> str:
    return f"₦{int(amount):,}"


def _summary(row: dict) -> pr.DaySummary:
    return pr.DaySummary(day=str(row["day"])[:10], seconds=int(row["seconds"]), minutes=int(row["minutes"]),
                         quizzes=int(row["quizzes"]), challenge=bool(row["challenge"]),
                         new_countries=int(row["new_countries"]), interactions=int(row["interactions"]), subjects=0,
                         tier=int(row["tier"]), tier_amount=int(row["tier_amount"]), amount=int(row["amount"]),
                         excluded=bool(row["excluded"]))


def month_days(s, member: dict, month: str) -> list[pr.DaySummary]:
    """The participant's days this month, after the monthly maximum."""
    if not member["test"]:
        return [_summary(r) for r in s.ff10_ledger(member["profile_id"], month)]
    rows = [r for r in s.ff10_activity(member["profile_id"]) if r.get("test")]
    beats = [b for b in s.ff10_heartbeats(member["profile_id"]) if b.get("test")]
    return pr.month_ledger(pr.day_summaries(rows, beats=beats), month)


def today_timeline(s, member: dict, month: str, today: str) -> dict:
    """Why today's verified time is what it is: the same records the calculation uses (read-only)."""
    test = bool(member["test"])
    rows = [r for r in s.ff10_activity(member["profile_id"], month)
            if bool(r.get("test")) == test and str(r["day"])[:10] == today]
    beats = [b for b in s.ff10_heartbeats(member["profile_id"], month)
             if bool(b.get("test")) == test and str(b["day"])[:10] == today]
    tl = pr.timeline(rows, beats)
    tl["check_minutes"] = max(0, (tl["credited"] - pr.active_seconds(rows)) // 60) if beats else 0
    return tl


def _data(s, member: dict) -> dict:
    cached = st.session_state.get("ff10_progress")
    if cached and cached["profile_id"] == member["profile_id"] and time.time() - cached["at"] < CACHE_SECONDS:
        return cached
    month, today = rewards.month_key(), rewards.day_key()
    days = month_days(s, member, month)
    lines = [] if member["test"] else s.ff10_lines(profile_id=member["profile_id"])
    data = {"profile_id": member["profile_id"], "at": time.time(), "month": month,
            "today": next((d for d in days if d.day == today), None), "month_total": sum(d.amount for d in days),
            "timeline": today_timeline(s, member, month, today),
            "lines": lines, "settlements": {r["month"]: r for r in s.ff10_settlements()} if lines else {}}
    st.session_state.ff10_progress = data
    return data


def _bar(label: str, value: int, top: int, text: str) -> None:
    st.markdown(f"**{label}:** {text}")
    st.progress(min(1.0, value / top) if top else 0.0)


def progress(member: dict) -> None:
    s = hooks.ff10_store()
    if s is None:
        return
    try:
        d = _data(s, member)
    except Exception:
        st.caption(t("Your learning progress could not be loaded just now. Your activity is still recorded."))
        return
    day = d["today"]
    minutes = day.minutes if day else 0
    daily = day.amount if day else 0
    with st.container(border=True, key="ff10_progress_card"):
        st.subheader("📊 " + t("Today's learning progress"))
        if member["test"]:
            st.caption("🧪 " + t("Test records: these figures are a preview for owner and tester accounts and are "
                                 "never settled."))
        _bar(t("Verified learning"), min(minutes, pr.MAX_MINUTES), pr.MAX_MINUTES,
             t("{n} / {max} minutes", n=min(minutes, pr.MAX_MINUTES), max=pr.MAX_MINUTES))
        _bar(t("Daily provisional reward"), daily, pr.DAILY_MAX,
             f"{_naira(daily)} / {_naira(pr.DAILY_MAX)}")
        _bar(t("Monthly provisional reward"), d["month_total"], pr.MONTHLY_MAX,
             f"{_naira(d['month_total'])} / {_naira(pr.MONTHLY_MAX)}")
        quizzes = day.quizzes if day else 0
        st.markdown(t("Qualifying quizzes today: {n} / {need}", n=quizzes, need=pr.TIERS[1][2]))
        _time_explained(d.get("timeline"))
        reached = day.tier if day else 0
        st.markdown("**" + t("Today's milestones") + "**")
        st.markdown("\n".join(f"- {'✅' if i < reached else '⬜'} {t(text)} — {_naira(pr.TIERS[i][0])}"
                              for i, text in enumerate(TIER_TEXT)))
        st.caption(t("Each amount is today's total, not an extra reward. Higher milestones need the ones before them."))
        remaining = pr.next_milestones(day)
        if d["month_total"] >= pr.MONTHLY_MAX:
            st.success(t("You have reached this month's provisional maximum. Keep learning for points and badges."))
        elif not remaining:
            st.success(t("Today's maximum is reached. Rewards stop increasing for today; points and badges still "
                         "count. See you tomorrow!"))
        else:
            st.info(t("Next milestone: {steps}.", steps="; ".join(_milestone(m) for m in remaining)))
        st.caption(t("Active learning counts: answering quizzes, exploring countries, and reading while you scroll or "
                     "tap on Explore, Learn or a quiz. Time with the app hidden, in the background or left untouched "
                     "does not count. School Learning is never part of the rewards."))
    _settlement(d)


def _time_explained(tl: dict | None) -> None:
    """Verified minutes from reading, and any time between today's first and last activity that was not counted."""
    if not tl:
        return
    if tl.get("check_minutes"):
        st.caption("📖 " + t("Includes {n} minutes of reading and exploring, verified by activity checks.",
                             n=tl["check_minutes"]))
    if tl["gaps"] and tl["uncredited"] >= 60:
        st.caption("⏸️ " + t("Not counted today: {minutes} minutes in {count} pause(s) longer than 3 minutes without "
                             "any recorded activity.", minutes=tl["uncredited"] // 60, count=len(tl["gaps"])))


def _milestone(text: str) -> str:
    """Translate one generated milestone ("12 more minutes of active learning" and the like)."""
    head, _, rest = text.partition(" ")
    if head.isdigit():
        if rest.startswith("more minutes"):
            return t("{n} more minutes of active learning", n=int(head))
        return t("{n} more qualifying quiz" if head == "1" else "{n} more qualifying quizzes", n=int(head))
    return t(text)


def _settlement(d: dict) -> None:
    with st.container(border=True, key="ff10_settlement_card"):
        st.markdown("**" + t("Monthly settlement") + "**")
        st.caption(t("Provisional rewards are estimates until the month is settled. After each month, all "
                     "participants' provisional rewards are added up. If the total is above the shared ₦50,000 monthly "
                     "budget, every amount is reduced in the same proportion. Your final allocation is paid in naira by "
                     "bank transfer after the Owner has approved it and verified your bank account."))
        st.markdown("- " + t("This month ({month}): in progress — {amount} provisional", month=d["month"],
                             amount=_naira(d["month_total"])))
        for line in sorted(d["lines"], key=lambda r: r["month"], reverse=True):
            settlement = d["settlements"].get(line["month"]) or {}
            text = t("{month}: {provisional} provisional → {final} final allocation · {status}",
                     month=line["month"], provisional=_naira(line["provisional"]), final=_naira(line["final"]),
                     status=t(LINE_TEXT.get(line["status"], line["status"])))
            if settlement.get("scaled"):
                text += " · " + t("reduced in proportion to fit the shared budget")
            st.markdown("- " + text)


# --------------------------------------------------------------------------- the private terms and their acceptance

def approval_caption() -> str:
    """The private-pilot approval record, as configured by the owner (shown with the documents)."""
    record = legal.pilot_approval()
    return t("Approved by {who} on {date}.", who=str(record.get("approved_by") or "—"),
             date=str(record.get("approved_on") or "—")[:10])


def documents() -> None:
    """The approved participation agreement and privacy notice, each with its version (English only)."""
    for key in legal.PILOT:
        title = legal.DOCUMENTS[key][0]
        with st.expander("📜 " + t(title) + f" ({legal.version(key)})", expanded=False):
            st.caption(t("Available in English.") + " " + approval_caption() + f" SHA-256 {legal.checksum(key)[:16]}…")
            st.markdown(legal.document(key))


def acceptance(member: dict) -> None:
    """An approved participant accepts the current approved private terms before earning cash rewards."""
    s = hooks.ff10_store()
    if s is None:
        return
    with st.container(border=True, key="ff10_accept_card"):
        st.subheader("📜 " + t("Please accept the current Friends & Family 10 terms"))
        st.markdown(t("The participation terms have been updated. Cash rewards for your learning are recorded again "
                      "once you have read and accepted them."))
        if not legal.pilot_ready():
            st.info(t("The current terms are not published yet. Please check back soon."))
            return
        documents()
        sure = st.checkbox(t("I have read and accept the Friends & Family 10 terms, and I have read the privacy notice."),
                           key="ff10_accept_confirm")
        if st.button(t("Accept and continue"), key="ff10_accept", type="primary", disabled=not sure):
            try:
                s.ff10_accept_terms(member["profile_id"], legal.pilot_terms_id())
            except StoreError as error:
                st.error(t("Earning is paused until the World Explorer team records the current terms. Please check "
                           "back soon.") if "terms_outdated" in str(error) or "terms_required" in str(error)
                         else t("Your acceptance could not be saved. Please try again."))
                return
            except Exception:
                st.error(t("Your acceptance could not be saved. Please try again."))
                return
            st.session_state.pop("ff10_member", None)
            st.session_state.pop("ff10_progress", None)
            st.rerun()
