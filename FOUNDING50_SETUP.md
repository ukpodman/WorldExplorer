# World Explorer Founding 50 — setup and operation

**Option B: anyone can apply, only the Owner approves.** World Explorer and all its free geography features (maps,
countries, quizzes, badges) stay open to everyone. Signed-in players in Nigeria can apply to the Founding 50 rewards
programme. Only the participants you approve can join and earn money.

Nothing here switches the programme on, enables payouts or withdrawals, or approves anybody automatically.

## What the database enforces (`supabase/founding50_migration.sql`)

The rules live in Supabase, so they hold even if somebody bypasses the Streamlit screens.

| Rule | How |
| --- | --- |
| One application per person | `reward_founding_applications.profile_id` is unique; a second application is refused (`already_applied`). |
| Only the Owner decides | `reward_founding_decide` checks your e-mail against `reward_cashout_settings.owner_emails`. Players, browser keys (anon/authenticated) and direct table writes are refused. |
| Statuses | Pending → Approved, Waiting List or Rejected (and back). A reason is required to reject, and to take a place away from an approved participant. |
| At most 50 approved participants | Approving is refused when `max_places` (50) real participants are approved (`places_full`). Test applications never take a place. |
| Only approved participants earn | Real accounts without an approved application cannot enrol or join the monthly waiting list (`not_approved`). Their activity is recorded with ₦0. |
| No money for non-approved accounts | Withdrawal requests, withdrawal approvals and payments, and monthly payment approvals and payments are refused for people never approved or rejected after approval (`founding_not_approved`). |
| 30-day withdrawal wait | Counted from the participant's **first official enrolment after your first approval** (the moment they take their place, `reward_enrolments.enrolled_at`). Applying, creating an account or being approved does not start it. |
| Withdrawal eligibility | 30 calendar days **and** verified earnings from a completed month (unchanged from V21). You review and approve every withdrawal manually; nothing is transferred automatically. |
| Audit | Every application and decision is written to `reward_audit_log` (`founding_applied`, `founding_approved`, `founding_waitlist`, `founding_rejected`). |

The existing limits are unchanged: ₦50,000 monthly budget, 50 places per month, ₦1,000 monthly maximum per
participant. Real applications are accepted only while the Public Rewards Programme is ON. Owner and tester accounts
can try the whole flow at any time; their records are test records and are never payable.

**Taking a place away.** Moving an approved participant to the waiting list or rejecting them ends their enrolment
for the current month (and later months), which frees the place and the unused budget. Past months and everything
they earned stay recorded. On the **waiting list**, earned rewards stay payable. **Rejected**, they are no longer
payable.

## Install (only after your approval)

1. Supabase → **SQL Editor** → paste `supabase/founding50_migration.sql` → **Run**. It needs
   `rewards_schema.sql`, `withdrawals_migration.sql` and `public_programme_migration.sql` first, and stops with a
   clear message if one is missing. It can be run again safely. If you ever run `withdrawals_migration.sql` again,
   run this file again afterwards.
2. Deploy the branch and **Reboot** the app. Until the migration is installed, real players see "Applications for
   the Founding 50 open soon" and cannot join (fail-safe); the Owner dashboard shows what to run.

Existing players and records are not changed. If anyone was already taking part before the migration, they keep
everything they earned, but they need to apply and be approved before they can earn again or be paid.

## Daily operation

**Player.** 💰 My Rewards → **🌟 World Explorer Founding 50** → choose their Nigerian state, an optional message,
confirm they are 18+, live in Nigeria and accept the rules → **Apply for the Founding 50**. They then see Pending,
Waiting List, Rejected or Approved. Once approved, they confirm their declarations and press **Join**; their 30-day
withdrawal wait starts then. The player screens are available in all five languages.

**Owner.** A notice at the top of the Owner dashboard shows new applications (it refreshes every 30 seconds).
💰 Rewards & Referral Management → **🌟 Founding 50**:

* **Dashboard:**
  * places available;
  * approved participants;
  * pending applications (and how many are new);
  * waiting list and rejected;
  * total applications;
  * participants taking part this month;
  * active participants;
  * earned this month;
  * net verified earnings from completed months.
* **New applications:** open one to review it (this clears its notification), or mark all as seen.
* **Lists:** Pending, Approved, Waiting List, Rejected or All. The waiting list is shown in order, and there is a
  CSV download.
* **Review:**
  * the applicant's details, declarations, state and message;
  * account age, activity so far, whether a friend invited them, and verified earnings.
  * Then choose **Approve**, **Waiting list** or **Reject**, with a note. Approve is unavailable when all 50 places
    are taken.

Your decision notes are internal: players never see them.

## What was tested, and what needs live checking

Tested here:
* The same scenarios on the in-memory store and on the real SQL in a local PostgreSQL 16, with all four migration
  files.
* The player and Owner screens in Streamlit's app tester.
* Mutation checks: removing any of the database rules makes a test fail.

Not tested:
* The live Supabase project.
* Google sign-in.
* Real phones.

Check on a phone and in Supabase after deploying.
