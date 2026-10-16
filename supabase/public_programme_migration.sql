-- World Explorer — Public Rewards Programme ON/OFF (owner switch) — additive migration
--
-- Run AFTER supabase/rewards_schema.sql and supabase/withdrawals_migration.sql, in Supabase → SQL Editor (see
-- REWARDS_SETUP.md, "Public Rewards Programme switch"). Safe to run again. It does not change any player record.
--
-- What it adds
--   * reward_program_settings.public_enabled (default FALSE — the programme is NOT switched on by this migration),
--     with who changed it and when.
--   * reward_set_public_programme(enabled, actor, confirmed): the only way to change it. Only the owners listed in
--     reward_cashout_settings.owner_emails may call it; switching ON needs an explicit confirmation. Every change is
--     written to reward_audit_log.
--   * While the switch is OFF, for real (non-test) accounts only:
--       - new enrolments and waiting-list promotions are refused ('programme_off');
--       - new activity is still recorded, but earns ₦0 (reason 'programme_off').
--     Existing enrolments, earned rewards, balances, payments, withdrawals and history are never changed. Leaving
--     the programme stays possible. Owner and tester (test) records are not affected.
--
-- Public participation needs BOTH this switch and the app's deployment safety switch [rewards] enabled = true.
-- The separate pause setting, the budget (₦50,000), places (50), the monthly maximum (₦1,000) and all payment
-- switches ([rewards] payouts_active, withdrawals_active, live_requests, real_payouts) are not changed by it.

do $$
begin
  if to_regclass('public.reward_program_settings') is null then
    raise exception 'Run supabase/rewards_schema.sql first (the rewards tables are missing).';
  end if;
  if to_regprocedure('public.reward_cashout_is_owner(text)') is null then
    raise exception 'Run supabase/withdrawals_migration.sql first (it holds the owner list).';
  end if;
end $$;

alter table public.reward_program_settings add column if not exists public_enabled boolean not null default false;
alter table public.reward_program_settings add column if not exists public_changed_at timestamptz;
alter table public.reward_program_settings add column if not exists public_changed_by text;

-- ============================================================================ the owner switch

create or replace function public.reward_set_public_programme(p_enabled boolean, p_actor text,
                                                              p_confirmed boolean default false)
returns public.reward_program_settings
language plpgsql set search_path = public as $$
declare
  s public.reward_program_settings%rowtype;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if p_enabled is null then raise exception 'invalid_value'; end if;
  if p_enabled and not coalesce(p_confirmed, false) then raise exception 'confirmation_required'; end if;
  perform set_config('we.public', 'on', true);
  update public.reward_program_settings
     set public_enabled = p_enabled, public_changed_at = now(), public_changed_by = p_actor,
         updated_at = now(), updated_by = p_actor
   where id = 1
  returning * into s;
  perform set_config('we.public', 'off', true);
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, case when p_enabled then 'public_programme_on' else 'public_programme_off' end, 'settings',
          jsonb_build_object('public_enabled', p_enabled, 'confirmed', coalesce(p_confirmed, false)));
  return s;
end $$;

-- the switch changes only through the function above (the ordinary settings form cannot change it)
create or replace function public.reward_public_switch_guard() returns trigger
language plpgsql as $$
begin
  if (new.public_enabled is distinct from old.public_enabled or new.public_changed_at is distinct from old.public_changed_at
      or new.public_changed_by is distinct from old.public_changed_by)
     and coalesce(current_setting('we.public', true), '') <> 'on' then
    raise exception 'the public programme switch changes only through reward_set_public_programme (Owner dashboard)';
  end if;
  return new;
end $$;

drop trigger if exists reward_public_switch_guard on public.reward_program_settings;
create trigger reward_public_switch_guard before update on public.reward_program_settings
  for each row execute function public.reward_public_switch_guard();

-- ============================================================================ enforcement while OFF

create or replace function public.reward_public_on() returns boolean
language sql stable set search_path = public as $$
  select coalesce((select public_enabled from public.reward_program_settings where id = 1), false)
$$;

-- runs after reward_events_cap (triggers fire in name order): real activity earns nothing while OFF
create or replace function public.reward_events_public() returns trigger
language plpgsql set search_path = public as $$
begin
  if not new.test and new.amount > 0 and not public.reward_public_on() then
    new.amount := 0;
    new.reason := 'programme_off';
  end if;
  return new;
end $$;

drop trigger if exists reward_events_public on public.reward_activity_events;
create trigger reward_events_public before insert on public.reward_activity_events
  for each row execute function public.reward_events_public();

-- no new real enrolments or waiting-list moves while OFF (leaving the programme stays possible)
create or replace function public.reward_enrolments_public() returns trigger
language plpgsql set search_path = public as $$
begin
  if not new.test and new.status in ('enrolled','waitlist')
     and (tg_op = 'INSERT' or new.status is distinct from old.status)
     and not public.reward_public_on() then
    raise exception 'programme_off';
  end if;
  return new;
end $$;

drop trigger if exists reward_enrolments_public on public.reward_enrolments;
create trigger reward_enrolments_public before insert or update on public.reward_enrolments
  for each row execute function public.reward_enrolments_public();

-- ============================================================================ access (server only)

revoke execute on function public.reward_set_public_programme(boolean, text, boolean) from public, anon, authenticated;
revoke execute on function public.reward_public_on()                                  from public, anon, authenticated;
grant  execute on function public.reward_set_public_programme(boolean, text, boolean) to service_role;
grant  execute on function public.reward_public_on()                                  to service_role;
