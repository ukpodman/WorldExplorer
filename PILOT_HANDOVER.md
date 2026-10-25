# World Explorer: Friends & Family 10 handover (updated 25 October 2026)

**Branch:** `atlas-pilot-consolidated` @ `b4fc727`, plus the interface corrections (`d3a7a01`, `d8e121b`, already
installed on your side), plus the Friends & Family 10 package.
**Package:** only the changed files; unzip it over that branch. The proposed SQL migration is also delivered as a
separate file for review.

**Deployment status:** **not deployed**. Nothing has been pushed, merged or deployed, no SQL has been run, and
production `main` is unchanged.

**Database:**
- `pilot_invitations_migration.sql` is **already installed and verified** in Supabase. Do not run it again.
- `friends_family10_migration.sql` is **new, proposed and not run**. Run it only after its review and your approval.

## What Friends & Family 10 is

The private pilot, renamed and resized: **World Explorer — Friends & Family 10**.
- At most 10 invited adults, each approved by you.
- Provisional rewards for verified learning: daily tiers of ₦100, ₦250, ₦350 and ₦500, at most ₦7,000 a month per
  person.
- A shared ₦50,000 monthly budget with proportional settlement.
- Your approval of every final allocation.
- Payments disabled at database level.

**Full description, decisions and limitations: `FRIENDS_FAMILY10.md`.**

## Unchanged

- Public educational access (Explore, Learn, Quiz, Badges, School Learning, points and profiles).
- Google sign-in and Supabase access.
- Invitation-only entry and the legal publication rules (operator verification, checksum approval).
- The existing rewards ledger (₦0 while Public Rewards is OFF), withdrawals and the future public Founding 50
  programme.

## Install (development branch only)

1. Unzip the package over the branch, after the corrections package.
2. Save the separate SQL file as `supabase/friends_family10_migration.sql` (it is also in the ZIP). Storing it does
   not run it.
3. Run `python -m unittest discover tests`. Expect 0 failures.
   - The PostgreSQL rule tests are skipped where PostgreSQL is not installed, or where
     `supabase/pilot_invitations_migration.sql` is missing from the checkout.

## To start Friends & Family 10 (in order)

1. **Lawyer review:** finalise the Privacy Policy, Terms of Use and the rewritten Friends & Family 10 terms, and
   complete `legal/OPERATOR_VERIFICATION.md`, including the new item D.3a.
2. **Streamlit secrets `[legal]`:**
   - `operator_verified`;
   - `contact_email`;
   - `registered_address`;
   - `[legal.approved]` checksums (see `legal/PILOT_ACTIVATION_READINESS.md`).
3. **After review and your approval:** run `supabase/friends_family10_migration.sql` in Supabase.
4. **Owner dashboard → 🤝 Friends & Family 10:**
   1. "Record the published pilot terms";
   2. invite people;
   3. approve up to 10;
   4. tick the confirmation and switch the pilot ON.
5. **Each month, in 📊 F&F 10 rewards:**
   1. review flagged days;
   2. finalise the settlement after the month ends;
   3. approve or withhold each allocation.

   Payments stay disabled.

## Tests

The results are in `TEST_RESULTS.md`.

Database rules are tested on the in-memory store and on a real local PostgreSQL. Live Supabase and Google sign-in were
not tested.

## Continue in a new session

> Continue World Explorer from branch `atlas-pilot-consolidated` (handover: PILOT_HANDOVER.md, FRIENDS_FAMILY10.md).
> The pilot invitations migration is installed; friends_family10_migration.sql is proposed and not run. Do not change
> Explore, Learn, Quiz or Badges. Do not run migrations, deploy or merge.
