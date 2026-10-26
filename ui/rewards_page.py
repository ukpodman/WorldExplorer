"""💰 My Rewards — the participant's page: joining (opt-in with self-declarations), this month's earnings, payment
status, history and the personal invitation link. Shown only when the programme is switched on, or to owners and
testers (whose records are test records). Amounts always come from the database."""
from __future__ import annotations

from html import escape

import streamlit as st

from core import accounts, rewards
from core.rewards_store import StoreError

from . import rewards_hooks as hooks
from . import ff10_ui, founding_ui, withdraw_ui
from .components import e, hero, html, sign_in_button
from .state import t

KIND_TEXT = {"active_day": "Active days", "quiz": "Quizzes", "country": "Countries explored", "referral": "Referrals"}
KIND_RULE = {"active_day": "A day with a finished quiz or two countries explored",
             "quiz": "A finished quiz of 5 or more questions (any score)",
             "country": "A new country explored this month",
             "referral": "A friend whose new account completes the learning steps"}
REFERRAL_STATUS = {"pending": "In progress", "qualified": "Completed — awaiting review", "approved": "Approved",
                   "rejected": "Not eligible"}
# Information cards describing the existing earning rules (amounts and limits come from the programme settings).
EARN_CARDS = {
    "active_day": ("📅", "Active days", "Complete a qualifying quiz or explore two countries.",
                   "{amount} per day | Up to {cap} monthly"),
    "quiz": ("📝", "Quizzes", "Complete a qualifying quiz of at least five questions.",
             "{amount} per quiz | Up to {cap} monthly"),
    "country": ("🌍", "Country exploration", "Explore and learn about a new country.",
                "{amount} per country | Up to {cap} monthly"),
    "referral": ("🤝", "Referrals", "Invite a friend who completes the qualifying activities.",
                 "{amount} per successful referral | Up to {cap} monthly"),
}
PAYMENT_TEXT = {"pending_review": "Pending review", "approved": "Approved", "paid": "Paid", "on_hold": "On hold",
                "rejected": "Rejected"}

TERMS = """**World Explorer Rewards — pilot programme rules (version {version})**

1. **Who can join — World Explorer Founding 50.** Signed-in World Explorer users who are at least 18 years old and
   live in Nigeria can apply. Only participants approved by World Explorer (at most 50 at a time) take part and earn
   rewards; applying does not guarantee a place, and an application can be approved, placed on a waiting list or
   declined. Applying and joining are optional; everyone keeps full access to World Explorer without them.
2. **Provisional eligibility.** Your age and residence are self-declared and give provisional eligibility only.
   Before any payment, we will ask you to complete a verification step. If eligibility cannot be confirmed, rewards
   are not paid.
3. **What earns rewards.** Genuine learning only: finished quizzes of at least 5 questions (any score), countries
   explored for the first time in the month, active days (a finished quiz or two countries explored that day) and
   friends invited with your link whose new accounts complete the learning steps. Opening the app or signing in
   does not earn rewards. There is no gambling, no paid entry and no leaderboard.
4. **Limits.** At most {cap} per person per calendar month (Nigeria time). Category and daily limits apply as shown
   in the app. Earned rewards are never reduced by later changes to the programme.
5. **Places and budget.** The pilot has a limited monthly budget and number of places. When all places are taken,
   new participants join a waiting list.
6. **Review and payment.** Every month's rewards are reviewed manually. Payments are made only after approval,
   using payment details collected separately in a secure way (World Explorer does not ask for bank details).
   A withdrawal can be requested at the earliest 30 calendar days after you first take your place following
   approval, and only for verified earnings from completed months; every withdrawal is reviewed and paid manually.
   Rewards from activity that breaks these rules (for example automated play, duplicate accounts or self-referral)
   may be refused.
7. **Pilot status.** Until the programme is officially launched, amounts are shown as a preview and are not
   payable. The programme may be paused or ended; rewards already approved will still be paid.
8. **Leaving.** You can leave at any time. Rewards you earned before leaving remain subject to review and payment.
"""


def _naira(amount) -> str:
    return f"₦{int(amount or 0):,}"


def _flash(message: str, kind: str = "success") -> None:
    st.session_state.rw_flash = (message, kind)


def _show_flash() -> None:
    flash = st.session_state.pop("rw_flash", None)
    if flash:
        getattr(st, flash[1])(flash[0])


def _banner(account: dict | None) -> None:
    if (account and account.get("test")) or (hooks.tester() and not hooks.enabled()):
        # Test mode belongs to owner/tester accounts; it is not the Friends & Family 10, and nothing here is owed.
        st.warning(t("Test mode for owner and tester accounts only. It is separate from Friends & Family 10. "
                     "All amounts are simulated and non-payable, and these records are marked as test records."),
                   icon="🧪")
    elif hooks.enabled() and not hooks.payouts_active():   # public programme only (the private pilot explains itself)
        st.info(t("Pilot preview: amounts are shown for information and are not payable until the programme is "
                  "officially launched."), icon="ℹ️")
    if hooks.preview_store():
        st.caption(t("Preview storage: records last until the app restarts."))


def _earning_table(settings: rewards.Settings) -> None:
    """Four separate reward cards (native Streamlit containers: title, description and amount on their own lines),
    two per row where there is room and one per row on phones."""
    for pair in (("active_day", "quiz"), ("country", "referral")):
        for column, kind in zip(st.columns(2, gap="small"), pair):
            icon, title, description, amounts = EARN_CARDS[kind]
            with column, st.container(border=True, key=f"rw_card_{kind}"):
                st.markdown(f"{icon} **{t(title)}**")
                st.caption(t(description))
                st.markdown("**" + t(amounts, amount=_naira(settings.amount(kind)),
                                     cap=_naira(settings.category_cap(kind))) + "**")
    with st.container(key="rw_limit"):
        st.markdown("**" + t("Monthly earning limit: {cap}", cap=_naira(settings.monthly_cap)) + "**")
        st.caption(t("You can reach the monthly maximum without referrals. Opening the app or signing in never earns "
                     "rewards."))


def _join_form(s, who: dict, ctx: dict) -> None:
    settings = ctx["settings"]
    st.subheader("🎯 " + t("Join the rewards pilot"))
    _earning_table(settings)
    with st.expander("📜 " + t("Programme rules")):
        st.caption(t("The programme rules are available in English."))
        st.markdown(TERMS.format(version=rewards.TERMS_VERSION, cap=_naira(settings.monthly_cap)))
    if settings.paused:
        st.warning(t("The rewards programme is paused. Your earned rewards are kept."))
        return
    with st.form("rewards_join", border=True):
        st.markdown("**" + t("Your declarations") + "**")
        adult = st.checkbox(t("I am 18 years or older."), key="rw_adult")
        resident = st.checkbox(t("I live in Nigeria."), key="rw_resident")
        terms = st.checkbox(t("I have read and accept the programme rules."), key="rw_terms")
        st.caption(t("Your answers give provisional eligibility. Before any payment we will ask you to verify them. "
                     "We do not ask for bank details here."))
        submitted = st.form_submit_button(t("Join"), type="primary", width="stretch")
    if submitted:
        if not (adult and resident and terms):
            st.error(t("Please confirm all three statements to join."))
            return
        try:
            row = s.join(who["profile_id"], ctx["month"])
        except StoreError as error:
            st.error(t("The rewards programme is paused. Your earned rewards are kept.") if "paused" in str(error)
                     else t("Joining did not work. Please try again."))
            return
        except Exception:
            st.error(t("Joining did not work. Please try again."))
            return
        if row and row.get("status") == "waitlist":
            _flash(t("All places are taken this month. You are on the waiting list (position {n}).",
                     n=row.get("waitlist_position")), "info")
        else:
            _flash(t("Welcome to the rewards pilot! Your activity now counts."))
        hooks.context(refresh=True)
        st.rerun()


def _status_line(enrolment: dict | None, settings) -> None:
    status = (enrolment or {}).get("status")
    if settings.paused:
        st.warning(t("The rewards programme is paused. Your earned rewards are kept."))
    elif status == "enrolled":
        st.success(t("You are taking part this month."), icon="✅")
    elif status == "waitlist":
        st.info(t("You are on the waiting list (position {n}). You will be added when a place becomes free.",
                  n=enrolment.get("waitlist_position")))
    elif status == "withdrawn":
        st.info(t("You left the programme this month. Rewards you earned are kept."))
    else:
        st.info(t("Your place for this month is confirmed with your first quiz or country."))


def _month_card(events: list[dict], settings, ctx: dict) -> None:
    summary = rewards.summarize(events)
    total, cap = summary["total"], settings.monthly_cap
    html(f'<div class="rw-month"><div class="rw-label">{e("This month")}</div>'
         f'<div class="rw-total">{escape(_naira(total))} <small>/ {escape(_naira(cap))}</small></div></div>')
    st.progress(min(total / cap, 1.0) if cap else 0.0)
    rows = []
    for kind in rewards.KINDS:
        item = summary[kind]
        rows.append(f'<div class="rw-cat"><div class="rw-cat-name">{e(KIND_TEXT[kind])}</div>'
                    f'<div class="rw-cat-count">{item["count"]} / {settings.month_limit(kind)}</div>'
                    f'<div class="rw-cat-amount">{escape(_naira(item["amount"]))} '
                    f'<small>/ {escape(_naira(settings.category_cap(kind)))}</small></div></div>')
    html(f'<div class="rw-cats">{"".join(rows)}</div>')
    left = max(cap - total, 0)
    today = [x for x in events if str(x.get("day"))[:10] == ctx["day"] and int(x.get("amount") or 0) > 0]
    quizzes = sum(1 for x in today if x.get("kind") == "quiz")
    countries = sum(1 for x in today if x.get("kind") == "country")
    st.caption(t("{amount} left to earn this month · Today: {q}/{qmax} quizzes, {c}/{cmax} countries.",
                 amount=_naira(left), q=quizzes, qmax=settings.quiz_max_day, c=countries,
                 cmax=settings.country_max_day))
    if left:
        tips = []
        if quizzes < settings.quiz_max_day:
            tips.append(t("Finish a quiz of 5 or more questions."))
        if countries < settings.country_max_day:
            tips.append(t("Explore a new country: open its neighbours, landmarks or details, or start its quiz."))
        if not any(x.get("kind") == "active_day" for x in today):
            tips.append(t("Make today an active day with one finished quiz or two countries."))
        tips.append(t("Invite a friend with your link."))
        with st.expander(t("How to earn more")):
            for tip in tips:
                st.markdown(f"- {tip}")


def _history(s, pid: str, month: str) -> None:
    events = s.events(pid)
    payments = {p["month"]: p for p in s.payments(profile_id=pid)}
    months = sorted({str(x["month"]) for x in events if int(x.get("amount") or 0) > 0} | set(payments), reverse=True)
    if not months:
        return
    with st.expander(t("Earnings and payments by month")):
        for m in months:
            earned = sum(int(x.get("amount") or 0) for x in events if x["month"] == m)
            pay = payments.get(m)
            status = t(PAYMENT_TEXT[pay["status"]]) if pay else (t("This month") if m == month else t("Pending review"))
            line = f"**{m}** · {_naira(earned)} · {status}"
            if pay and pay.get("status") == "paid":
                line += f" · {t('Paid')} {_naira(pay.get('paid_amount'))} ({pay.get('payment_date')})"
            st.markdown(line)


def _leave(s, pid: str, month: str) -> None:
    with st.expander(t("Leave the programme")):
        st.caption(t("You can leave at any time. Rewards you earned before leaving are kept for review."))
        sure = st.checkbox(t("Yes, I want to leave the rewards programme."), key="rw_leave_sure")
        if st.button(t("Leave the programme"), key="rw_leave", disabled=not sure):
            try:
                s.leave(pid, month)
                _flash(t("You left the rewards programme. You can keep using World Explorer as before."), "info")
            except Exception:
                _flash(t("That did not work. Please try again."), "error")
            hooks.context(refresh=True)
            st.rerun()


def _referrals(s, account: dict, ctx: dict) -> None:
    with st.container(border=True, key="rw_invite"):
        _referrals_body(s, account)


def _referrals_body(s, account: dict) -> None:
    st.subheader("🤝 " + t("Invite friends"))
    code = account["referral_code"]
    link = hooks.referral_link(code)
    st.caption(t("Your personal invitation link (code {code}):", code=code))
    st.code(link, language=None, wrap_lines=True)
    st.link_button(t("Share on WhatsApp"), hooks.whatsapp_link(code, t("Join me on World Explorer and learn about every country:")),
                   icon=":material/share:", width="stretch")
    needs = rewards.REFERRAL_NEEDS
    st.caption(t("A friend counts when their new account has {d} active days, {q} quizzes and {c} countries explored. "
                 "Existing accounts and your own account do not count.", d=needs["active_days"], q=needs["quizzes"],
                 c=needs["countries"]))
    mine = s.referrals(account["profile_id"])
    visits = s.visits(account["profile_id"])
    earned = sum(int(x.get("amount") or 0) for x in s.events(account["profile_id"], kind="referral"))
    done = sum(1 for r in mine if r["status"] in ("qualified", "approved"))
    pending = sum(1 for r in mine if r["status"] == "pending")
    html('<div class="rw-stats">'
         + "".join(f'<div class="rw-stat"><div class="rw-stat-value">{escape(str(v))}</div>'
                   f'<div class="rw-stat-label">{e(k)}</div></div>' for k, v in (
             ("Link visits", len(visits)), ("Friends joined", len(mine)), ("Completed", done), ("In progress", pending),
             ("Earned from invitations", _naira(earned))))
         + "</div>")
    if mine:
        with st.expander(t("Invitation history")):
            for i, r in enumerate(reversed(mine[-20:]), 1):
                joined = str(r.get("created_at") or "")[:10]
                line = f"{t('Friend {n}', n=len(mine) - i + 1)} · {joined} · {t(REFERRAL_STATUS[r['status']])}"
                if r["status"] == "pending":
                    progress = rewards.referral_progress(rewards.activity_totals(s.events(r["referred_id"])))
                    line += " · " + t("{d}/{dn} days, {q}/{qn} quizzes, {c}/{cn} countries",
                                      d=progress["active_days"][0], dn=progress["active_days"][1],
                                      q=progress["quizzes"][0], qn=progress["quizzes"][1],
                                      c=progress["countries"][0], cn=progress["countries"][1])
                st.markdown(line)


def _invited_note(ctx: dict) -> None:
    referral = ctx.get("referral")
    if not referral or referral.get("status") != "pending":
        return
    progress = rewards.referral_progress(ctx.get("totals") or {})
    st.caption(t("You joined through a friend's invitation. Your learning activity helps their invitation count: "
                 "{d}/{dn} days, {q}/{qn} quizzes, {c}/{cn} countries.",
                 d=progress["active_days"][0], dn=progress["active_days"][1], q=progress["quizzes"][0],
                 qn=progress["quizzes"][1], c=progress["countries"][0], cn=progress["countries"][1]))


def render() -> None:
    if not hooks.visible():
        st.info(t("This page is not available."))
        return
    if hooks.enabled():
        hero("Rewards pilot", "My Rewards", "Learn, explore and earn rewards every month.", variant="compact")
    else:   # the Friends & Family 10: no money language
        hero("Invitation only", "Friends & Family 10", "Help us test World Explorer before a wider launch.",
             variant="compact")
    who = accounts.identity()
    if not who:
        _banner(None)
        st.info(t("Sign in with Google to join the rewards pilot and get your invitation link."))
        if accounts.provider_ready("google"):
            sign_in_button("google", "Continue with Google", "rewards_google", primary=True)
        return
    s = hooks.store()
    if not s:
        st.warning(t("Rewards are not available right now. Please try again later."))
        return
    try:
        account = s.ensure_account(who["profile_id"], hooks._verified_email() or None, who.get("name"),
                                   bool(st.session_state.get("profile_was_new")), hooks.tester())
        ctx = hooks.context(refresh=True)
    except Exception:
        st.warning(t("Rewards are not available right now. Please try again later."))
        return
    if not ctx:
        st.warning(t("Rewards are not available right now. Please try again later."))
        return
    _banner(account)
    _show_flash()
    _invited_note(ctx)
    pid, month = who["profile_id"], ctx["month"]
    # 🌟 Founding 50: only participants the Owner approved may join and earn (test accounts may always try)
    fs = hooks.founding_store()
    if fs is None and not account.get("test"):
        may_join = False
        if account.get("membership") != "suspended":
            founding_ui.unavailable()
    elif fs is None or account.get("membership") == "suspended":
        may_join = True
    else:
        may_join = founding_ui.section(fs, who, account)
    member = hooks.ff10_member(refresh=True) if not hooks.enabled() else None
    if member and member.get("needs_acceptance"):   # the current approved private terms must be accepted first
        ff10_ui.acceptance(member)
    elif member:   # Friends & Family 10: learning progress, provisional amounts and paid final allocations
        ff10_ui.progress(member)
    if not hooks.enabled() and not account.get("test"):
        # Friends & Family 10 only (the public rewards programme is closed): the application, its status and, once
        # approved, the provisional rewards above — nothing about joining, invitation links or withdrawals. The
        # existing public ledger pays ₦0 while the public switch is off; the pilot pays approved allocations in cash.
        st.info(t("Educational points and badges have no monetary value. Provisional amounts become final at the "
                  "monthly settlement; approved final allocations are paid in naira by bank transfer to your verified "
                  "account. Thank you for helping us test World Explorer."))
        return
    if not hooks.enabled():   # owner/tester accounts only: the public-programme screens with simulated amounts
        st.caption("🧪 " + t("Owner and tester preview: every ₦ amount below is simulated and non-payable."))
    if account.get("membership") == "member":
        _status_line(ctx.get("enrolment"), ctx["settings"])
        with st.container(border=True, key="rw_progress"):
            st.subheader("📊 " + t("Monthly rewards progress"))
            _month_card(s.events(pid, month), ctx["settings"], ctx)
        _history(s, pid, month)
        withdraw_ui.section(s, who, account)
    elif account.get("membership") == "suspended":
        st.warning(t("Your participation is on hold. Please use “Send feedback” if you think this is a mistake."))
    else:
        if may_join:
            _join_form(s, who, ctx)
        if account.get("membership") == "withdrawn":   # earned rewards stay withdrawable after leaving
            withdraw_ui.section(s, who, account)
    st.divider()
    _referrals(s, account, ctx)
    if account.get("membership") == "member":
        st.divider()
        _leave(s, pid, month)
