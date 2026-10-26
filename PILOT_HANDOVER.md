# World Explorer: Friends & Family 10 handover (updated 25 October 2026, real cash)

**Branch:** `atlas-pilot-consolidated`, with the corrections, Friends & Family 10 and review-correction packages,
plus this real-cash patch.

**Status:**
- Not deployed by Claude: nothing was pushed or merged, and production `main` is unchanged.
- No SQL was run and no payment was made.

**Database:**
- `pilot_invitations_migration.sql` is **installed**.
- `friends_family10_migration.sql` is **installed**, as you confirmed. Do not run either again.
- `friends_family10_payments_migration.sql` is **installed**, as you confirmed.
- `friends_family10_acceptance_migration.sql` is **new, proposed and not run**. It makes participants accept the
  current private terms before earning. Run it only after review and your approval.

## What Friends & Family 10 is

A **real-cash** private pilot:
- 10 invited, individually approved adults;
- cash rewards for verified learning, at most ₦500 per day and ₦7,000 per month per person;
- a shared ₦50,000 monthly budget, with proportional adjustment when it is exceeded;
- approved final allocations paid in naira by manual bank transfer from the company account and recorded in an
  append-only payment ledger.

Public Rewards, public payouts and withdrawals stay OFF.

**Details: `FRIENDS_FAMILY10.md` (section 4a covers payments).**

## Install (development branch only)

1. Unzip the patch over the branch.
2. Save the separate SQL file as `supabase/friends_family10_acceptance_migration.sql` (it is also in the ZIP). Storing
   it does not run it.
3. Run `python -m unittest discover tests`. Expect 0 failures.

## To start paying (in order)

1. Finalise the pilot's own documents (`legal/PILOT_TERMS.md` and `legal/PILOT_PRIVACY_NOTICE.md`): remove the
   DRAFT notice and the open items, and set a final version line.
2. Set the `[legal]` operator details and the `[legal.pilot_approval]` record (decision-maker, date, versions,
   checksums). See `FRIENDS_FAMILY10.md` section 4b and `legal/PILOT_ACTIVATION_READINESS.md`.
3. After review and your approval, run `supabase/friends_family10_acceptance_migration.sql` in Supabase.
4. In 🤝 Friends & Family 10, record the pilot terms, invite people, approve up to 10, and switch the pilot ON.
5. In 📊 F&F 10 rewards → 💵 Cash payments:
   1. check that every readiness check passes;
   2. authorise pilot payments;
   3. verify each beneficiary.
6. Each month:
   1. review flagged days;
   2. finalise the settlement;
   3. approve or withhold each allocation;
   4. pay approved allocations by bank transfer;
   5. record each transfer (amount, date, reference).

## Tests

The results are in `TEST_RESULTS.md`. Database rules are tested on the in-memory store and on a real local PostgreSQL.
Live Supabase and Google sign-in were not tested.

## Continue in a new session

> Continue World Explorer from branch `atlas-pilot-consolidated` (handover: PILOT_HANDOVER.md, FRIENDS_FAMILY10.md).
> The pilot invitations, friends_family10 and friends_family10_payments migrations are installed;
> friends_family10_acceptance_migration.sql is proposed and not run. Do not change Explore, Learn, Quiz or Badges. Do not run migrations, deploy or merge.
