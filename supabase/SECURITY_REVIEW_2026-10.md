# Supabase security review (24 October 2026)

**Scope:**
- every SQL file in `supabase/`;
- the setup SQL in `README.md` (profiles) and `SETUP_ANALYTICS.md` (events, feedback);
- the proposed `pilot_invitations_migration.sql`.

**Method:** all rewards migrations were run in order in a throwaway local PostgreSQL 16, with Supabase-like roles
(`anon`, `authenticated`, and `service_role` with BYPASSRLS). The access checks below were run there, and the
existing Postgres test suite (`tests/pg_harness.py`) passes against it. Your Supabase project was not touched.

## 1. The Data API change on 30 October 2026

From 30 October 2026, **new** tables in `public` are no longer exposed to the Data API automatically. Each role,
including `service_role`, needs an explicit `GRANT`. **Existing tables keep their grants.**
([Supabase changelog](https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically))

What this means for World Explorer:

| Area | Finding |
|---|---|
| Tables already created in your project | Not affected. |
| Scripts not run yet (`founding50`, `withdrawals`, `public_programme`, `school_learning`, the proposed `pilot_invitations`) | **Ready.** Each one grants the needed privileges to `service_role` explicitly and revokes everything from `anon` and `authenticated`. They work the same before and after 30 October. |
| A new Supabase project (e.g. staging) set up from `README.md` / `SETUP_ANALYTICS.md` | **Ready.** That SQL also grants `service_role` explicitly. |
| `school_learning_user_token_policies.sql` (optional) | Grants `authenticated` on purpose, protected by row policies limited to the student's own rows. Run it only if you choose that mode; server mode needs none of it. |

## 2. Access checks (local test database, after all migrations)

| Check | Result |
|---|---|
| Tables or views in `public` reachable by `anon` or `authenticated` | **0** |
| Tables without Row Level Security | **0** |
| Tables the server key (`service_role`) cannot read | **0** |
| Callable functions (RPC) executable by `anon` or `authenticated` | **0** |
| Trigger functions executable by the browser roles | 22. **Not a risk:** Postgres refuses to run a trigger function outside a trigger ("trigger functions can only be called as triggers"). Optional tidy-up below. |
| The new `reward_pilot_invitations` table and its 10 functions | `service_role` only. No delete privilege: invitations are revoked, never deleted. |

## 3. Owner-only actions

- Every owner action is a database function that checks the owner list in `reward_cashout_settings.owner_emails`
  and writes to `reward_audit_log`. This covers: decisions, payments, the public switch, and the new pilot switch,
  invitation-only setting, invitations and revocations.
- The app checks the owner again on the server (`[analytics] owner_emails`, with a verified Google email).
- The browser never talks to Supabase. The server key stays on the server.
- The pilot switches cannot be changed through the ordinary settings update: a database trigger refuses it (tested).

## 4. Proposed migration (not run)

`supabase/pilot_invitations_migration.sql` adds the invitation-only Friends & Family Pilot:
- **New table:** `reward_pilot_invitations`. It stores only the invited Google email, an optional owner note, and
  who invited or revoked it and when.
- **New settings columns** (both default safe): `pilot_enabled` (OFF) and `invitation_only` (ON).
- **New functions** for the pilot switch, the invitation-only setting, inviting and revoking.
- **Two separately approved participation terms**: `pilot_terms_version` (the published pilot terms) and
  `public_terms_version` (the public programme rules). Both are set only by the owner function
  `reward_set_participation_terms(mode, version, actor)`, which is audited.
  - Each way in accepts only its own terms (`terms_outdated` otherwise), and the accepted version stays on the
    application.
  - The pilot cannot be switched on before pilot terms are recorded. Public applications cannot be allowed before
    public terms are recorded.
  - Comparisons with terms that aren't recorded yet are NULL-safe: they count as refused. A test caught this on real
    Postgres.
- **One updated rule** in `reward_founding_apply`: applications need the pilot or the public switch ON, plus an
  invitation. The invitation is always required in the pilot, and also in public mode unless `invitation_only` is
  switched off (confirmed and audited).

It changes no payment, withdrawal or enrolment rule and approves nobody. Tested locally for:
- rerunning it safely;
- strangers refused while the public switch is ON;
- invited people accepted;
- owner-only and confirmed changes;
- revocation;
- approved pilot participants earning ₦0 and unable to enrol while the public programme is OFF;
- no browser-role access.

**Order:** run it after `founding50_migration.sql`, and again if that file is ever re-run.

## 5. Optional tidy-up (not needed for security)

To remove the default `EXECUTE` on trigger functions for the browser roles, generate the statements:

```sql
select format('revoke execute on function %s from public, anon, authenticated;', p.oid::regprocedure)
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public' and p.prorettype = 'trigger'::regtype and p.proname like 'reward%';
```

Review the statements it prints, then run them. Triggers keep working: Postgres does not check `EXECUTE` when a
trigger fires. This was tested locally: with the right revoked from every role, the audit trigger still wrote its row.
