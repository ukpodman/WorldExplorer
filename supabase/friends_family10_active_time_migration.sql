-- WORLD EXPLORER — FRIENDS & FAMILY 10: verified reading and exploring time ("activity checks")
--
-- PROPOSED — NOT APPLIED. Run only after the Owner has approved it, in Supabase → SQL Editor, AFTER
-- friends_family10_migration.sql, friends_family10_payments_migration.sql and friends_family10_acceptance_migration.sql
-- (all already installed). Safe to run again. Rollback: friends_family10_active_time_rollback.sql.
--
-- What it changes
--   * NEW table pilot_heartbeats: one row per accepted activity check (reading or exploring without clicking).
--   * NEW functions pilot_record_heartbeat / pilot_record_heartbeat_at (the database decides what is accepted).
--   * REPLACES pilot_month_ledger (same name, arguments and result columns) so that accepted checks join each day's
--     one timeline as points in time. The gap rule (at most 180 seconds between two consecutive points) is unchanged.
--
-- What it does NOT change
--   * No existing row of any table is changed or deleted (pilot_activity, approvals, acceptances, reviews,
--     settlements, settlement lines, beneficiaries, payments, audit log).
--   * Every day without checks — all days before this migration — is calculated exactly as before.
--   * Tiers, ₦500 daily maximum, ₦7,000 monthly maximum, ₦50,000 shared budget, 10 participants, payments switch,
--     Public Rewards: unchanged (pilot_reward_settings is not touched).
--
-- Rules for an activity check (the same values are in core/pilot_rewards.py)
--   * time = the database clock; area must be explore, learn or quiz (School Learning never sends checks)
--   * only approved, invited participants with the current terms accepted, while the pilot is ON, in a month that is
--     not settled (test accounts are recorded as test, never settled)
--   * ignored when the person's previous accepted check was less than 50 seconds ago (one stream per person, whatever
--     the number of tabs, devices or page reruns)
--   * ignored unless the person recorded a meaningful interaction (quiz answer, quiz, Daily Challenge, country opened
--     or explored) the same Lagos day within the last 15 minutes: leaving the app open stops earning
--   * at most 150 accepted checks per person per day

do $$
begin
  if to_regclass('public.pilot_activity') is null
     or to_regprocedure('public.pilot_is_participant(text)') is null
     or to_regclass('public.pilot_terms_acceptances') is null then
    raise exception 'Run the Friends & Family 10 migrations (main, payments, acceptance) first.';
  end if;
end $$;

-- ============================================================================ table

create table if not exists public.pilot_heartbeats (
  id          bigint generated always as identity primary key,
  profile_id  text not null references public.reward_accounts (profile_id),
  day         date not null,                                         -- Lagos calendar day of "at"
  area        text not null check (area in ('explore', 'learn', 'quiz')),
  test        boolean not null default false,
  at          timestamptz not null default now()
);
create index if not exists pilot_heartbeats_profile_day on public.pilot_heartbeats (profile_id, day, at);

create or replace function public.pilot_heartbeats_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' and old.test then return old; end if;
  raise exception 'pilot activity checks are kept unchanged for the audit trail';
end $$;
drop trigger if exists pilot_heartbeats_guard on public.pilot_heartbeats;
create trigger pilot_heartbeats_guard before update or delete on public.pilot_heartbeats
  for each row execute function public.pilot_heartbeats_guard();

-- ============================================================================ recording

-- p_at is the database clock in normal use (pilot_record_heartbeat); this variant exists for the local tests only and
-- is NOT granted to the app's key.
create or replace function public.pilot_record_heartbeat_at(p_profile text, p_area text, p_at timestamptz)
returns public.pilot_heartbeats
language plpgsql set search_path = public as $$
declare
  acc   public.reward_accounts;
  v_day date := (p_at at time zone 'Africa/Lagos')::date;
  row   public.pilot_heartbeats;
begin
  if p_area is null or p_area not in ('explore', 'learn', 'quiz') then raise exception 'invalid_activity'; end if;
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if not found then raise exception 'unknown_account'; end if;
  if not acc.test then
    if not public.reward_pilot_on() then raise exception 'pilot_closed'; end if;
    if not public.pilot_is_participant(p_profile) then raise exception 'not_participant'; end if;
    perform pg_advisory_xact_lock_shared(hashtext('ff10:month:' || to_char(v_day, 'YYYY-MM')));
    if exists (select 1 from public.pilot_settlements where month = to_char(v_day, 'YYYY-MM')) then
      raise exception 'month_settled';
    end if;
  end if;
  perform pg_advisory_xact_lock(hashtext('ff10:' || p_profile));          -- one record at a time per person
  if exists (select 1 from public.pilot_heartbeats
              where profile_id = p_profile and day = v_day
                and at <= p_at and at > p_at - make_interval(secs => 50)) then
    return null;                                                           -- too soon: another tab, device or rerun
  end if;
  if not exists (select 1 from public.pilot_activity
                  where profile_id = p_profile and test = acc.test and day = v_day
                    and at <= p_at and at >= p_at - make_interval(secs => 900)) then
    return null;                                                           -- nothing meaningful in the last 15 minutes
  end if;
  if (select count(*) from public.pilot_heartbeats where profile_id = p_profile and day = v_day) >= 150 then
    return null;                                                           -- daily limit of checks
  end if;
  insert into public.pilot_heartbeats (profile_id, day, area, test, at)
  values (p_profile, v_day, p_area, acc.test, p_at)
  returning * into row;
  return row;
end $$;

create or replace function public.pilot_record_heartbeat(p_profile text, p_area text)
returns public.pilot_heartbeats
language sql security definer set search_path = public as $$       -- the time is always the database clock
  select public.pilot_record_heartbeat_at(p_profile, p_area, clock_timestamp())
$$;

-- ============================================================================ ledger (replaced; same signature)

-- One participant's days in a month: verified minutes (one timeline per day made of the day's interactions and its
-- accepted activity checks: gaps between consecutive points count up to inactivity_seconds), milestones, tier, and
-- the amount after the monthly maximum (owner-excluded days ₦0). Checks add time only on days with interactions.
create or replace function public.pilot_month_ledger(p_profile text, p_month text)
returns table (day date, seconds int, minutes int, quizzes int, challenge boolean, new_countries int,
               interactions int, tier int, tier_amount int, excluded boolean, amount int)
language plpgsql stable set search_path = public as $$
#variable_conflict use_column
declare
  s     public.pilot_reward_settings;
  r     record;
  total int := 0;
begin
  select * into s from public.pilot_reward_settings where id = 1;
  for r in
    with a as (
      select x.* from public.pilot_activity x where x.profile_id = p_profile and not x.test),
    pts as (
      select a.day, a.at, 0 as src, a.id from a
      union all
      select h.day, h.at, 1 as src, h.id from public.pilot_heartbeats h
       where h.profile_id = p_profile and not h.test and h.day in (select a.day from a)),
    gaps as (
      select pts.day, lead(pts.at) over (partition by pts.day order by pts.at, pts.src, pts.id) as next_at, pts.at
        from pts),
    gaps2 as (                                    -- the day's last point has no following gap (least() would
      select g1.day,                              -- ignore the NULL, so it is excluded explicitly)
             least(extract(epoch from (g1.next_at - g1.at)), s.inactivity_seconds) as g
        from gaps g1 where g1.next_at is not null),
    secs as (select d0.day, floor(coalesce(sum(g2.g), 0))::int as seconds
               from (select distinct a.day from a) d0 left join gaps2 g2 on g2.day = d0.day group by d0.day),
    firsts as (select a.subject, min(a.day) as day from a where a.kind = 'country' group by a.subject),
    days as (
      select a.day, count(*)::int as interactions,
             count(distinct a.subject) filter (where a.kind = 'quiz')::int as quizzes,
             coalesce(bool_or(a.kind = 'challenge'), false) as challenge
        from a group by a.day)
    select d.day, sc.seconds, d.quizzes, d.challenge, d.interactions,
           (select count(*) from firsts f where f.day = d.day)::int as new_countries,
           coalesce(rv.excluded, false) as excluded
      from days d join secs sc on sc.day = d.day
      left join public.pilot_day_reviews rv on rv.profile_id = p_profile and rv.day = d.day
     where to_char(d.day, 'YYYY-MM') = p_month
     order by d.day
  loop
    day := r.day; seconds := r.seconds; minutes := r.seconds / 60; quizzes := r.quizzes; challenge := r.challenge;
    new_countries := r.new_countries; interactions := r.interactions; excluded := r.excluded;
    tier := public.pilot_tier(minutes, quizzes, new_countries, challenge);
    tier_amount := public.pilot_tier_amount(tier);
    amount := case when excluded then 0 else greatest(0, least(tier_amount, s.daily_max, s.monthly_max - total)) end;
    total := total + amount;
    return next;
  end loop;
end $$;

-- ============================================================================ security

alter table public.pilot_heartbeats enable row level security;
revoke all on public.pilot_heartbeats from public, anon, authenticated;
grant select, delete on public.pilot_heartbeats to service_role;            -- delete: test rows only (guard trigger)

revoke execute on function public.pilot_heartbeats_guard()                                from public, anon, authenticated;
revoke execute on function public.pilot_record_heartbeat_at(text, text, timestamptz)
                                                                       from public, anon, authenticated, service_role;
revoke execute on function public.pilot_record_heartbeat(text, text)                      from public, anon, authenticated;
revoke execute on function public.pilot_month_ledger(text, text)                          from public, anon, authenticated;
grant  execute on function public.pilot_record_heartbeat(text, text)                      to service_role;
grant  execute on function public.pilot_month_ledger(text, text)                          to service_role;

-- Check after running:
--   select count(*) from public.pilot_heartbeats;                                    -- 0 straight after installing
--   select table_name, grantee from information_schema.role_table_grants
--    where table_name = 'pilot_heartbeats' and grantee in ('anon', 'authenticated');   -- 0 rows
--   Compare any participant's October ledger before and after (must be identical until checks are recorded):
--   select * from public.pilot_month_ledger('<profile_id>', '2026-10');
