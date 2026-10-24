# World Explorer: Friends & Family Pilot handover (24 October 2026)

**Base:** your published `atlas-explore-dev` @ `582cbe9` (Premium Badges).
**Package:** one consolidated ZIP containing the legal-operator, pilot-safeguard and correction work, rebuilt on top of
`582cbe9`. The proposed SQL migration is delivered separately and is **not** run.
Nothing is pushed, merged or deployed.

## What it adds

1. **Legal operator (proposed):**
   - World Explorer — Operated by OKETORIAH KÖNIGREICH LTD (CAC RC 7160552).
   - Drafts in `legal/`: Privacy Policy, Terms of Use and Friends & Family Pilot terms, plus the checklist
     `OPERATOR_VERIFICATION.md`.
   - A document is shown in Settings → Legal information only when it is complete (no DRAFT notice, no [open
     items]), the operator is verified, a contact email and registered address are set, and the owner has approved
     its exact **content checksum**. Any edit unpublishes it until it is approved again.
2. **Three independent modes:**
   - **Public educational access:** unchanged and never restricted.
   - **Friends & Family Pilot:**
     - invitation-only, with the owner's invitation list and pilot switch;
     - owner approval, at most 50 participants;
     - participants accept the approved pilot terms;
     - no money language, and ₦0 is recorded for activity.
   - **Public rewards enrolment (future):** needs the public switches, approved public programme rules, and "Allow
     public applications" (invitation-only OFF), each a separate owner decision. It stays disabled.
3. **Two separately approved terms versions:** pilot terms (`<version>#<checksum>`) and public programme rules
   (`rewards.TERMS_VERSION`). Each way in accepts only its own approved version, and the accepted version is kept with
   the application and in the audit log.
4. **Money stays off:**
   - payouts and withdrawals also require the published legal documents, on top of their existing switches, which
     are all off;
   - the database records ₦0 while the public programme is off.

## Install (development branch only)

1. Copy the ZIP contents over the project (on top of `582cbe9`).
2. Save `PROPOSED_pilot_invitations_migration_NOT_RUN.sql` as `supabase/pilot_invitations_migration.sql`. Storing
   it there does not run it; the tests read it.
3. Run `python -m unittest discover tests`. Expect 0 failures (on your machine the PostgreSQL tests are skipped if
   PostgreSQL is not installed).

Nothing changes for players until you act: the documents are drafts, the pilot switch does not exist until the
migration runs, and all money switches are off.

## To start the pilot (in order)

1. Lawyer review: finalise the three documents and complete `legal/OPERATOR_VERIFICATION.md`.
2. Streamlit secrets `[legal]`:
   - `operator_verified = true`;
   - `contact_email`;
   - `registered_address`;
   - `[legal.approved]` privacy / terms / pilot = the checksums shown in Owner dashboard → ⚖️ Legal & switches.
3. After your approval, run the migration in Supabase.
4. In Owner dashboard → Founding 50:
   1. "Record the published pilot terms";
   2. invite people;
   3. tick the confirmation and switch the pilot ON.

## Tests

The full suite passes; the count is in the chat summary. New since the last package:
- regression tests 1–6 (pilot terms, uninvited refused, public terms only after authorisation, outdated terms
  refused, educational access unrestricted, payouts disabled);
- a NULL-safety test that caught a real SQL bug, now fixed.

Database rules run on both the in-memory store and a real local PostgreSQL. Live Supabase and Google sign-in were
not tested.

## Continue in a new session

> Continue World Explorer from branch `atlas-pilot-consolidated` (handover: PILOT_HANDOVER.md). Do not change
> Explore, Learn, Quiz or Badges. Do not run migrations, deploy or merge.
