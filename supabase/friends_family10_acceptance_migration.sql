-- World Explorer — FRIENDS & FAMILY 10: participants must accept the CURRENT approved private terms — PROPOSED additive
-- migration
--
-- STATUS: proposed for review. Do NOT run it until it has been reviewed and the owner approves. It switches nothing
-- on and changes no existing record.
-- Run AFTER friends_family10_migration.sql and friends_family10_payments_migration.sql (both installed). Safe to run
-- again.
--
-- What it adds
--   * pilot_terms_acceptances: one row per participant and accepted version of the private participation terms
--     (the version the owner recorded with "Record the published pilot terms", i.e. reward_pilot_terms()).
--     Rows are never edited or deleted.
--   * pilot_accept_terms(profile, terms_version): an approved, invited participant accepts exactly the currently
--     recorded version ('terms_outdated' otherwise).
--   * pilot_terms_accepted(profile): TRUE when the participant applied with, or later accepted, the current version.
--   * pilot_is_participant now also requires pilot_terms_accepted, so no learning is recorded for cash rewards (and no
--     beneficiary can be verified) until the participant has accepted the current approved terms. When the owner
--     records new terms, everybody must accept them again before earning again. Invitation-only and approval rules
--     are unchanged; settled months and recorded payments are not affected.

do $$
begin
  if to_regprocedure('public.pilot_is_participant(text)') is null
     or to_regclass('public.pilot_payments') is null then
    raise exception 'Run supabase/friends_family10_migration.sql and friends_family10_payments_migration.sql first.';
  end if;
end $$;

create table if not exists public.pilot_terms_acceptances (
  profile_id     text not null references public.reward_accounts (profile_id),
  terms_version  text not null check (length(btrim(terms_version)) between 3 and 120),
  accepted_at    timestamptz not null default now(),
  primary key (profile_id, terms_version)
);

create or replace function public.pilot_acceptances_guard() returns trigger
language plpgsql as $$
begin
  raise exception 'terms acceptances are kept unchanged for the audit trail';
end $$;
drop trigger if exists pilot_acceptances_guard on public.pilot_terms_acceptances;
create trigger pilot_acceptances_guard before update or delete on public.pilot_terms_acceptances
  for each row execute function public.pilot_acceptances_guard();

create or replace function public.pilot_terms_accepted(p_profile text) returns boolean
language sql stable set search_path = public as $$
  select coalesce(nullif(btrim(coalesce(public.reward_pilot_terms(), '')), '') is not null
         and (exists (select 1 from public.reward_founding_applications
                       where profile_id = p_profile and terms_version = public.reward_pilot_terms())
              or exists (select 1 from public.pilot_terms_acceptances
                          where profile_id = p_profile and terms_version = public.reward_pilot_terms())), false)
$$;

-- unchanged from friends_family10_migration.sql, plus the accepted-terms requirement
create or replace function public.pilot_is_participant(p_profile text) returns boolean
language sql stable set search_path = public as $$
  select exists (select 1
                   from public.reward_founding_applications a
                   join public.reward_accounts r on r.profile_id = a.profile_id
                  where a.profile_id = p_profile and a.status = 'approved' and not a.test and not r.test
                    and public.reward_pilot_invited(r.email))
         and public.pilot_terms_accepted(p_profile)
$$;

create or replace function public.pilot_accept_terms(p_profile text, p_terms_version text)
returns public.pilot_terms_acceptances
language plpgsql security definer set search_path = public as $$
declare
  v_terms text := nullif(btrim(coalesce(public.reward_pilot_terms(), '')), '');
  row     public.pilot_terms_acceptances;
begin
  if not exists (select 1
                   from public.reward_founding_applications a
                   join public.reward_accounts r on r.profile_id = a.profile_id
                  where a.profile_id = p_profile and a.status = 'approved' and not a.test and not r.test
                    and public.reward_pilot_invited(r.email)) then
    raise exception 'not_participant';
  end if;
  if v_terms is null then raise exception 'terms_required'; end if;
  if btrim(coalesce(p_terms_version, '')) is distinct from v_terms then raise exception 'terms_outdated'; end if;
  insert into public.pilot_terms_acceptances (profile_id, terms_version) values (p_profile, v_terms)
  on conflict (profile_id, terms_version) do nothing;
  select * into row from public.pilot_terms_acceptances where profile_id = p_profile and terms_version = v_terms;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_profile, 'pilot_terms_accepted', p_profile, to_jsonb(row));
  return row;
end $$;

alter table public.pilot_terms_acceptances enable row level security;
revoke all on public.pilot_terms_acceptances from public, anon, authenticated;
grant select on public.pilot_terms_acceptances to service_role;

revoke execute on function public.pilot_acceptances_guard()             from public, anon, authenticated;
revoke execute on function public.pilot_terms_accepted(text)            from public, anon, authenticated;
revoke execute on function public.pilot_accept_terms(text, text)        from public, anon, authenticated;
revoke execute on function public.pilot_is_participant(text)            from public, anon, authenticated;
grant  execute on function public.pilot_terms_accepted(text)            to service_role;
grant  execute on function public.pilot_accept_terms(text, text)        to service_role;
grant  execute on function public.pilot_is_participant(text)            to service_role;
