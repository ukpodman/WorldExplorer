# Friends & Family 10: legal activation readiness (updated 25 October 2026)

This is a review of the legal configuration on branch `atlas-pilot-consolidated` (`b4fc727`). Nothing has been filled
in, approved or bypassed. Claude is not a lawyer; the legal content needs your lawyer.

**Live status in the app.** I cannot see your Streamlit secrets. The app shows the live list in two places:
- Owner dashboard → 💰 Rewards & Referral Management → 🤝 Friends & Family 10. The "Switch the pilot ON" button
  stays disabled and lists every missing item.
- Owner dashboard → ⚖️ Legal & switches.

**Database.** You reported that the pilot migration is installed and verified. It is not repeated here. The new
`supabase/friends_family10_migration.sql` (provisional rewards and settlement) is proposed and **not run**; run it only
after its review and your approval. Without it the pilot can still open, but nothing is recorded for rewards.

## What the app requires before the pilot can be switched on

All of these must hold. The database separately refuses the switch until the pilot terms are recorded.

| # | Requirement | Who provides it | Status in the repository |
|---|---|---|---|
| 1 | The company is confirmed as operator and data controller: `[legal] operator_verified = true` | You, after `OPERATOR_VERIFICATION.md` section A (CAC status report, board resolution, IP assignment, service accounts) | Not set |
| 2 | Privacy and legal contact: `[legal] contact_email` | You (a real mailbox you monitor) | Not set |
| 3 | Registered address: `[legal] registered_address` (as on the CAC record) | You, from the CAC status report | Not set |
| 4 | Privacy Policy finalised: no DRAFT notice, no open items, a final `*Version:*` line | Your lawyer | Draft `draft-2026-10-24`, 15 open items, e.g. DPO, hosting region, retention periods (now including Friends & Family 10 learning records), transfer mechanism, EU/UK scope |
| 5 | Terms of Use finalised (same rules) | Your lawyer | Draft `draft-2026-10-24`, 2 open items (enforceability review) |
| 6 | Friends & Family 10 cash-pilot terms finalised (same rules) | You and your adviser | Draft `draft-2026-10-25-cash` (real cash by bank transfer, provisional vs final amounts, proportional settlement), open items (cash-rewards approval, tax treatment, payment timing, conflict-of-interest wording, leaving channel) |
| 7 | Each finalised document approved by its exact content checksum: `[legal.approved] privacy / terms / pilot` | You, copying the checksums shown in ⚖️ Legal & switches **after** the final text is in the repository | Not set. The checksums of today's drafts are deliberately not given here: approving a draft can never publish it. |
| 8 | The approved pilot terms recorded in the database ("Record the published pilot terms…") | You, in the pilot tab, once items 1–7 are done | Only possible after items 1–7 |

Then:
1. Invite people (their Google sign-in email).
2. Tick the confirmation.
3. Switch the pilot ON.

## Points still to decide with your lawyer

These block the documents, not the code:
- NDPC registration tier.
- Data Protection Officer (DPO).
- Cross-border transfer basis (Streamlit, US; Supabase region to confirm).
- Retention periods.
- Children and parental consent: School Learning targets secondary students.
- Whether EU/GDPR duties apply.
- Rewards-rules status with the Federal Competition and Consumer Protection Commission (FCCPC). This applies to any
  future paid programme, not the ₦0 pilot.

See `OPERATOR_VERIFICATION.md` sections A–D.

## What stays off regardless

The following stay off, and nothing in this package changes any of them:
- Public Rewards (the deployment switch, the owner's public switch, and published documents are all needed).
- Public applications (invitation-only stays ON).
- Withdrawals and payouts.

## Real cash payments (after the pilot is open)

The owner tab 📊 F&F 10 rewards → 💵 Cash payments shows these checks live. "Authorise pilot payments" stays disabled
until every one passes:

1. Operator verified (`[legal] operator_verified`).
2. Contact email and registered address set.
3. Privacy Policy, Terms of Use and the cash-pilot terms (`legal/PILOT_TERMS.md`, version `draft-2026-10-25-cash`,
   rewritten for real cash) finalised and approved by checksum.
4. Approved pilot terms recorded in the database.
5. The legal requirements for cash rewards reviewed: FCCPC sales-promotion rules, tax treatment and identity checks
   (`OPERATOR_VERIFICATION.md` section D). These are confirmed by finalising and approving the documents.
6. Invitation-only with at most 10 participants.
7. Public Rewards OFF.

The database part is `supabase/friends_family10_payments_migration.sql`: proposed, **not run**. Nothing here is filled
in or approved for you, and the app never pays money itself.
