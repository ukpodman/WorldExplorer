"""🤝 Friends & Family 10 — the participant's learning progress and provisional rewards.

Shown on the participant page to approved participants (and, with test records, to owners and testers). Real
participants' figures come from the database's own calculation (pilot_month_days); test accounts' figures are
calculated here with the same rules (core/pilot_rewards.py). Provisional amounts are estimates until the monthly
settlement (the shared budget may reduce them); approved final allocations are paid in real naira by bank transfer.
"""
from __future__ import annotations

import time

import streamlit as st

from core import pilot_rewards as pr
from core import rewards

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
    return pr.month_ledger(pr.day_summaries(rows), month)


def _data(s, member: dict) -> dict:
    cached = st.session_state.get("ff10_progress")
    if cached and cached["profile_id"] == member["profile_id"] and time.time() - cached["at"] < CACHE_SECONDS:
        return cached
    month, today = rewards.month_key(), rewards.day_key()
    days = month_days(s, member, month)
    lines = [] if member["test"] else s.ff10_lines(profile_id=member["profile_id"])
    data = {"profile_id": member["profile_id"], "at": time.time(), "month": month,
            "today": next((d for d in days if d.day == today), None), "month_total": sum(d.amount for d in days),
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
        st.caption(t("Only active learning counts: answering quizzes, exploring countries and reading their details. "
                     "Leaving the app open does not."))
    _settlement(d)


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
