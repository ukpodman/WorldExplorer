# World Explorer — Friends & Family 10: how it works (25 October 2026)

**Branch:** `atlas-pilot-consolidated` @ `b4fc727`, plus the interface corrections `d3a7a01` and `d8e121b`, plus this
package.
**Status:** not deployed. Nothing has been pushed or merged, no SQL has been run, and production `main` is unchanged.
Public Rewards, withdrawals and payments stay OFF.

## 1. The programme

| Setting | Value | Enforced by |
|---|---|---|
| Name | World Explorer — Friends & Family 10 | the app (participant and owner screens) |
| Approved participants | at most **10** adults | database trigger `pilot_places_guard`: all approvals while Public Rewards is OFF; if it is ever ON, all approved people on the invitation list (public applicants follow the public limit) |
| Entry | invitation only, owner approval for everyone | the installed pilot migration (applications), and `pilot_is_participant` for every learning record: approved **and** an active invitation, whatever the Public Rewards switch says. Revoking an invitation stops recording at once. |
| Monthly budget (all participants) | **₦50,000** | `pilot_reward_settings` (CHECK constraint) and the settlement |
| Per participant | **₦500/day**, **₦7,000/month** | the ledger (`pilot_month_ledger`) |
| Rewarded learning per day | 15–60 verified minutes | the daily tiers |
| Payments | **disabled** | `payments_enabled = false` fixed by a CHECK constraint; `pilot_mark_paid` always refuses |

The internal database names keep "founding50" and "pilot"; only the displayed name changed. The future public
programme keeps the name Founding 50 and its own `max_places` setting (50).

## 2. Verified active learning time

- **What counts.** Each of these sends one interaction to the database, which time-stamps it with its own clock:
  - answering a quiz question;
  - finishing a qualifying quiz (five or more questions);
  - finishing the Daily Challenge;
  - opening a country's details (neighbours, landmarks, size comparison, more details);
  - moving to a country in Learn (Next, Previous, Surprise me, or from a country card) or picking one in Explore.
- **What never counts:**
  - opening the app, signing in or refreshing;
  - leaving a page open;
  - School Learning;
  - repeating the same action. The same interaction (same kind and subject) within 10 minutes is ignored.
- **The timeline rule.** All of a day's interactions form one timeline, whatever the number of tabs or devices. The
  gap between two consecutive interactions counts up to 3 minutes, so reading a country page counts, while a long
  pause adds at most 3 minutes. Overlapping sessions cannot count twice, and the total can never exceed real time.
- **Days follow Lagos time** (West Africa Time).
- **Privacy.** No device fingerprinting, location, screen recording or new personal data. Each record holds the
  profile id, the kind of interaction, its subject (country, quiz round or question id) and the time. For quizzes it
  also holds the number of questions and the average answer time, which is used for the review flags.
- **Owner review.** Days are flagged for the owner, never penalised automatically:
  - "low variety": few different activities for the time recorded;
  - "very fast answers": under 2 seconds on average.

  The owner may exclude a day, with a reason, before the month is settled.

## 3. Daily tiers (cumulative daily totals)

| Verified learning that day | Daily provisional reward |
|---|---|
| Under 15 minutes | ₦0 |
| 15 min + 1 qualifying quiz | ₦100 |
| 30 min + 2 qualifying quizzes | ₦250 |
| 45 min + the above + 1 country explored for the first time | ₦350 |
| 60 min + the above + the Daily Challenge | ₦500 |

- Each tier needs the tiers below it.
- **Decision taken:** the Daily Challenge is its own milestone. It is not counted as one of the two quizzes.
- **Decision taken:** a "new country" is one the participant has never explored before in the programme. Opening a
  country's details counts as exploring it.
- Each day's amount is cut so that the month never exceeds ₦7,000. A day the owner excluded earns ₦0 and does not
  use up the monthly maximum.
- Learning beyond the limits still earns educational points and badges, as before.

## 4. The shared ₦50,000 pool and monthly settlement

1. After a month ends (Lagos time), the owner opens 📊 F&F 10 rewards → Monthly settlement. The page shows the exact
   preview, calculated by the database.
2. **Within budget:** everyone keeps their provisional amount, and the rest stays unspent.
3. **Over budget:** the budget is shared in proportion: provisional × 50,000 ÷ total. Amounts are in whole naira,
   using the largest-remainder method with ties broken by profile id. The result is deterministic, sums to exactly
   ₦50,000, and no one receives more than their provisional amount. Ten participants at ₦7,000 each receive ₦5,000.
4. The owner ticks the confirmation and finalises. The database refuses if:
   - the month has not ended;
   - it is already settled;
   - the allocation changed since the preview (`preview_changed`).

   The preview carries a **fingerprint**: a SHA-256 of the month, the budget, both totals and every participant's
   provisional and final amount. When the owner finalises, the database takes an exclusive lock for that month,
   recomputes the preview and compares the fingerprints. A change to any single participant's amount is refused,
   even if the total stays the same. Day reviews and late activity for that month take the same lock (shared), so
   they cannot slip in during finalisation; after it they are refused. The confirmed fingerprint is stored with the
   settlement.

   Finalising writes `pilot_settlements` and `pilot_settlement_lines`. Their amounts can never change (trigger), and
   activity and day reviews for that month are then refused.
5. Each line then needs the owner's decision: **Approve** (not paid) or **Withhold** (a reason is required, and
   changing an earlier decision also needs a reason).
6. **Mark as paid** is disabled in the app, and the database refuses it (`payments_disabled`).

Provisional amounts are never called earnings. Participants see them as estimates that are not payable.

## 5. Screens

- **Participant** (Rewards page, approved participants only):
  - "Today's learning progress": verified minutes out of 60, the daily provisional reward out of ₦500, and the
    monthly provisional reward out of ₦7,000;
  - the milestone checklist and what is still needed;
  - "Rewards stop increasing for today" once the daily maximum is reached;
  - the monthly settlement status (provisional → final, review status, and whether the amount was reduced to fit the
    budget).

  It is mobile-first and uses native Streamlit containers in the existing Premium Atlas styling, in all five app
  languages.
- **Owner** (💰 Rewards & Referral Management):
  - the applications tab is now "🤝 Friends & Family 10 (n)";
  - the new tab "📊 F&F 10 rewards" shows:
    - figures: invited, approved X/10, active this month, budget, provisional total, remaining budget, pending
      reviews, and approved and paid totals;
    - a participants table: today's minutes, activities and provisional amount, the month's provisional amount, the
      estimated final allocation, and excluded days;
    - each participant's day-by-day history with review flags, exclude and restore, and a CSV download;
    - the settlement preview and finalisation;
    - approve or withhold per settled line.

## 6. Install (development branch only, after review)

1. Unzip the package over `atlas-pilot-consolidated`, on top of the corrections package.
2. Review `supabase/friends_family10_migration.sql`. **Do not run it** until it has been reviewed and you approve.
   Saving it in `supabase/` does not run it; the tests read it.
3. Run `python -m unittest discover tests`.
   - The PostgreSQL tests run only where PostgreSQL is installed, and only if both
     `supabase/pilot_invitations_migration.sql` (already installed in Supabase) and the new file are in the checkout.
4. **Until the new migration runs, the live app is unaffected:**
   - nothing is recorded;
   - participants see no progress card;
   - the owner tab says the migration is not installed.

## 7. Remaining limitations and decisions

1. **Lawyer.** The cash-rewards rules (for example FCCPC sales promotions), tax treatment and identity checks must
   be confirmed before any payment. The pilot terms and Privacy Policy are rewritten as drafts and remain unpublished.
2. **Learning-time heuristics.** The time rules are honest and conservative, but no web app can prove attention. A
   determined person could keep clicking different countries. That is why the review flags, day exclusion and the
   per-line approval exist.
3. **Quiz timeouts.** An expired timed question counts as an answer interaction, as it does for points today.
4. **Owner figures** come from the database's own calculation for each participant. Raw activity is loaded only for
   the participant and month you open. The estimate for the current month includes approved participants and anyone
   already in a settlement; the settlement itself always uses the database calculation over everyone with activity.
5. **Not verified here:**
   - live Supabase;
   - Google sign-in;
   - a visual check in a browser (this environment could not start the Streamlit server).

   The screens are covered by automated app tests.
6. **More than 10 already approved.** If more than 10 participants were already approved before the migration,
   existing approvals stay, and new approvals are refused until the count is below 10.
7. **Payments.** Turning payments on in future needs another reviewed migration that changes the fixed
   `payments_enabled` constraint, plus the legal and identity steps.
