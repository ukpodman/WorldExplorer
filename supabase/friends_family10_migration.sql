-- World Explorer — FRIENDS & FAMILY 10: provisional rewards for the private pilot — PROPOSED additive migration
--
-- STATUS: proposed for review. Do NOT run it until it has been reviewed and the owner approves. It switches nothing
-- on, pays nothing and changes no existing record.
-- Run AFTER rewards_schema.sql, withdrawals_migration.sql, public_programme_migration.sql, founding50_migration.sql
-- and pilot_invitations_migration.sql (already installed), in Supabase → SQL Editor. Safe to run again.
--
-- What it adds (a separate ledger: the existing rewards tables, the ₦1,000 public cap, the ₦0-while-public-OFF rule,
-- withdrawals and payments are untouched)
--   * pilot_reward_settings: one row with the approved values, fixed by CHECK constraints (10 participants, ₦50,000
--     monthly budget, ₦500 per day, ₦7,000 per month, 15–60 verified minutes, payments_enabled = FALSE). Changing any
--     of them needs another reviewed migration; there is no function that changes them.
--   * At most 10 approved participants while Public Rewards is OFF (trigger on the applications table).
--   * pilot_activity: meaningful learning interactions, time-stamped by the DATABASE clock (the app cannot send a
--     time). Repeats of the same interaction within 10 minutes are ignored. Rows are never edited or deleted (test
--     rows excepted). Real rows only for approved participants while the pilot switch is ON; test accounts' rows are
--     marked test and never settled.
--   * pilot_month_ledger / pilot_settlement_preview: verified minutes, daily tiers and the monthly maximum, then the
--     shared ₦50,000 budget (largest-remainder, whole naira, never above the budget or anyone's provisional amount).
--   * pilot_day_reviews: the owner may exclude a participant's day (with a reason) before the month is settled.
--   * pilot_settlements + pilot_settlement_lines: an immutable monthly settlement, finalised once by the owner after
--     the month ends and only if the complete allocation is exactly the one the owner previewed: the preview carries a
--     SHA-256 fingerprint of every participant's provisional and final amount (plus month, budget and totals), and
--     finalising recomputes it under a lock that also blocks day reviews and late activity for that month. Amounts
--     can never change afterwards; each line then needs the owner's approval (or is withheld with a reason).
--   * Invitation-only, independently of Public Rewards: a real participant's learning is recorded only while the pilot
--     switch is ON, the person's application is approved AND their Google email is on the active invitation list
--     (reward_pilot_invited). Public Rewards being ON never admits anyone to the pilot; the public programme keeps its
--     own rules and ledger.
--   * pilot_mark_paid always refuses while payments_enabled is FALSE (fixed by the CHECK constraint).
--
-- Security: Row Level Security ON; anon and authenticated get nothing; only service_role (the app's server key) is
-- granted, explicitly (Supabase Data API change of 30 October 2026), and only to READ the tables. Every write goes
-- through a function (SECURITY DEFINER, fixed search_path) that checks its own rules; owner functions check
-- reward_cashout_settings.owner_emails and write reward_audit_log.

do $$
begin
  if to_regclass('public.reward_pilot_invitations') is null
     or to_regprocedure('public.reward_pilot_on()') is null then
    raise exception 'Run supabase/pilot_invitations_migration.sql first (the invitation-only pilot).';
  end if;
end $$;

-- ============================================================================ settings (fixed values)

create table if not exists public.pilot_reward_settings (
  id                  int primary key default 1 check (id = 1),
  max_participants    int not null default 10    check (max_participants = 10),
  monthly_budget      int not null default 50000 check (monthly_budget = 50000),
  daily_max           int not null default 500   check (daily_max = 500),
  monthly_max         int not null default 7000  check (monthly_max = 7000),
  min_minutes         int not null default 15    check (min_minutes = 15),
  max_minutes         int not null default 60    check (max_minutes = 60),
  inactivity_seconds  int not null default 180   check (inactivity_seconds = 180),
  repeat_seconds      int not null default 600   check (repeat_seconds = 600),
  payments_enabled    boolean not null default false check (payments_enabled = false),
  created_at          timestamptz not null default now()
);
insert into public.pilot_reward_settings (id) values (1) on conflict (id) do nothing;

-- ============================================================================ at most 10 pilot participants

-- While Public Rewards is OFF every approval is a pilot approval: at most 10 approved. If Public Rewards is ever ON,
-- public applicants follow the public programme's own place limit, and approving an INVITED person (a pilot member)
-- still needs a free pilot place: at most 10 approved people who are on the active invitation list.
create or replace function public.pilot_places_guard() returns trigger
language plpgsql set search_path = public as $$
declare taken int; v_max int; v_public boolean;
begin
  if new.status = 'approved' and old.status is distinct from 'approved' and not new.test then
    v_public := public.reward_public_on();
    if not v_public or public.reward_pilot_invited((select email from public.reward_accounts
                                                     where profile_id = new.profile_id)) then
      perform pg_advisory_xact_lock(hashtext('founding'));
      select max_participants into v_max from public.pilot_reward_settings where id = 1;
      select count(*) into taken
        from public.reward_founding_applications a join public.reward_accounts r on r.profile_id = a.profile_id
       where a.status = 'approved' and not a.test and a.id <> new.id
         and (not v_public or public.reward_pilot_invited(r.email));
      if taken >= coalesce(v_max, 10) then raise exception 'places_full'; end if;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists pilot_places_guard on public.reward_founding_applications;
create trigger pilot_places_guard before update of status on public.reward_founding_applications
  for each row execute function public.pilot_places_guard();

-- ============================================================================ activity

create table if not exists public.pilot_activity (
  id          bigint generated always as identity primary key,
  profile_id  text not null references public.reward_accounts (profile_id),
  day         date not null,                                         -- Lagos calendar day of "at"
  kind        text not null check (kind in ('answer', 'quiz', 'challenge', 'country', 'view')),
  subject     text not null check (length(subject) between 1 and 120),
  detail      jsonb check (detail is null or pg_column_size(detail) <= 300),
  test        boolean not null default false,
  at          timestamptz not null default now()
);
create index if not exists pilot_activity_profile_day on public.pilot_activity (profile_id, day);
create index if not exists pilot_activity_repeat on public.pilot_activity (profile_id, kind, subject, at);

create or replace function public.pilot_activity_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' and old.test then return old; end if;
  raise exception 'pilot activity records are kept unchanged for the audit trail';
end $$;
drop trigger if exists pilot_activity_guard on public.pilot_activity;
create trigger pilot_activity_guard before update or delete on public.pilot_activity
  for each row execute function public.pilot_activity_guard();

create table if not exists public.pilot_day_reviews (
  profile_id   text not null references public.reward_accounts (profile_id),
  day          date not null,
  excluded     boolean not null,
  reason       text check (reason is null or length(reason) <= 500),
  reviewed_by  text not null,
  reviewed_at  timestamptz not null default now(),
  primary key (profile_id, day),
  check (not excluded or reason is not null)
);

-- A pilot participant: an approved real application AND an active invitation for the account's Google email
-- (whatever the Public Rewards switch says). Revoking the invitation stops recording at once.
create or replace function public.pilot_is_participant(p_profile text) returns boolean
language sql stable set search_path = public as $$
  select exists (select 1
                   from public.reward_founding_applications a
                   join public.reward_accounts r on r.profile_id = a.profile_id
                  where a.profile_id = p_profile and a.status = 'approved' and not a.test and not r.test
                    and public.reward_pilot_invited(r.email))
$$;

-- p_at is the database clock in normal use (pilot_record_activity); this variant exists for the local tests only and
-- is NOT granted to the app's key.
create or replace function public.pilot_record_activity_at(p_profile text, p_kind text, p_subject text,
                                                           p_detail jsonb, p_at timestamptz)
returns public.pilot_activity
language plpgsql set search_path = public as $$
declare
  acc       public.reward_accounts;
  s         public.pilot_reward_settings;
  v_subject text := left(btrim(coalesce(p_subject, '')), 120);
  v_day     date := (p_at at time zone 'Africa/Lagos')::date;
  v_detail  jsonb;
  row       public.pilot_activity;
begin
  if p_kind is null or p_kind not in ('answer', 'quiz', 'challenge', 'country', 'view') or v_subject = '' then
    raise exception 'invalid_activity';
  end if;
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if not found then raise exception 'unknown_account'; end if;
  if not acc.test then
    if not public.reward_pilot_on() then raise exception 'pilot_closed'; end if;
    if not public.pilot_is_participant(p_profile) then raise exception 'not_participant'; end if;
    -- shared month lock: a settlement of this month (exclusive lock) waits for this record, or this record waits for
    -- the settlement and is then refused
    perform pg_advisory_xact_lock_shared(hashtext('ff10:month:' || to_char(v_day, 'YYYY-MM')));
    if exists (select 1 from public.pilot_settlements where month = to_char(v_day, 'YYYY-MM')) then
      raise exception 'month_settled';
    end if;
  end if;
  select * into s from public.pilot_reward_settings where id = 1;
  perform pg_advisory_xact_lock(hashtext('ff10:' || p_profile));          -- one interaction at a time per person
  if exists (select 1 from public.pilot_activity
              where profile_id = p_profile and kind = p_kind and subject = v_subject
                and at <= p_at and at > p_at - make_interval(secs => s.repeat_seconds)) then
    return null;                                                           -- a repeat: ignored, adds no time
  end if;
  if p_kind in ('quiz', 'challenge') and p_detail is not null then
    v_detail := jsonb_strip_nulls(jsonb_build_object(
      'questions', case when jsonb_typeof(p_detail -> 'questions') = 'number' then p_detail -> 'questions' end,
      'avg_seconds', case when jsonb_typeof(p_detail -> 'avg_seconds') = 'number' then p_detail -> 'avg_seconds' end));
  end if;
  insert into public.pilot_activity (profile_id, day, kind, subject, detail, test, at)
  values (p_profile, v_day, p_kind, v_subject, v_detail, acc.test, p_at)
  returning * into row;
  return row;
end $$;

create or replace function public.pilot_record_activity(p_profile text, p_kind text, p_subject text,
                                                        p_detail jsonb default null)
returns public.pilot_activity
language sql security definer set search_path = public as $$       -- the time is always the database clock
  select public.pilot_record_activity_at(p_profile, p_kind, p_subject, p_detail, clock_timestamp())
$$;

-- ============================================================================ ledger

create or replace function public.pilot_tier(p_minutes int, p_quizzes int, p_new int, p_challenge boolean)
returns int language sql immutable as $$
  select case
    when p_minutes < 15 or p_quizzes < 1 then 0
    when p_minutes < 30 or p_quizzes < 2 then 1
    when p_minutes < 45 or p_new < 1 then 2
    when p_minutes < 60 or not p_challenge then 3
    else 4 end
$$;

create or replace function public.pilot_tier_amount(p_tier int) returns int
language sql immutable as $$
  select case p_tier when 1 then 100 when 2 then 250 when 3 then 350 when 4 then 500 else 0 end
$$;

-- One participant's days in a month: verified minutes (one timeline per day: gaps between consecutive interactions
-- count up to inactivity_seconds), milestones, tier, and the amount after the monthly maximum (owner-excluded days ₦0).
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
    gaps as (
      select a.day, lead(a.at) over (partition by a.day order by a.at, a.id) as next_at, a.at
        from a),
    gaps2 as (                                    -- the day's last interaction has no following gap (least() would
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

create or replace function public.pilot_month_total(p_profile text, p_month text) returns int
language sql stable set search_path = public as $$
  select coalesce(sum(amount), 0)::int from public.pilot_month_ledger(p_profile, p_month)
$$;

create or replace function public.pilot_month_days(p_profile text, p_month text) returns jsonb
language sql stable set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(l) order by l.day), '[]'::jsonb) from public.pilot_month_ledger(p_profile, p_month) l
$$;

-- The exact allocation the owner would finalise (real participants with activity in the month).
create or replace function public.pilot_settlement_preview(p_month text) returns jsonb
language plpgsql stable set search_path = public as $$
declare
  s      public.pilot_reward_settings;
  result jsonb;
begin
  if p_month is null or p_month !~ '^\d{4}-(0[1-9]|1[0-2])$' then raise exception 'invalid_month'; end if;
  select * into s from public.pilot_reward_settings where id = 1;
  with people as (
    select distinct profile_id from public.pilot_activity where not test and to_char(day, 'YYYY-MM') = p_month),
  p as (select profile_id, least(public.pilot_month_total(profile_id, p_month), s.monthly_max) as prov from people),
  t as (select coalesce(sum(prov), 0)::bigint as total from p),
  b as (
    select p.profile_id, p.prov,
           case when t.total <= s.monthly_budget then p.prov else (p.prov::bigint * s.monthly_budget / t.total)::int end as base,
           case when t.total <= s.monthly_budget then 0 else (p.prov::bigint * s.monthly_budget % t.total) end as rem,
           t.total
      from p, t),
  extra as (select case when max(b.total) > s.monthly_budget then s.monthly_budget - sum(b.base) else 0 end as n from b),
  r as (select b.*, row_number() over (order by b.rem desc, b.profile_id collate "C") as rn from b),
  lines as (
    select r.profile_id, r.prov as provisional, r.base + case when r.rn <= extra.n then 1 else 0 end as final
      from r, extra)
  select jsonb_build_object(
           'month', p_month, 'budget', s.monthly_budget,
           'total_provisional', (select total from t),
           'total_final', coalesce((select sum(final) from lines), 0),
           'scaled', (select total from t) > s.monthly_budget,
           'unspent', s.monthly_budget - coalesce((select sum(final) from lines), 0),
           'lines', coalesce((select jsonb_agg(jsonb_build_object('profile_id', profile_id, 'provisional', provisional,
                                                                  'final', final) order by profile_id collate "C")
                                from lines), '[]'::jsonb),
           -- the complete allocation in one deterministic SHA-256 value (core.pilot_rewards.fingerprint, same text)
           'fingerprint', encode(sha256(convert_to(
               'ff10-settlement-v1|' || p_month || '|' || s.monthly_budget || '|' || (select total from t) || '|'
               || coalesce((select sum(final) from lines), 0) || '|'
               || coalesce((select string_agg(profile_id || ':' || provisional || ':' || final, ';'
                                              order by profile_id collate "C") from lines), ''),
               'UTF8')), 'hex'))
    into result;
  return result;
end $$;

-- ============================================================================ owner review of days

create or replace function public.pilot_review_day(p_profile text, p_day date, p_excluded boolean, p_actor text,
                                                   p_reason text default null)
returns public.pilot_day_reviews
language plpgsql security definer set search_path = public as $$
declare
  v_reason text := nullif(btrim(coalesce(p_reason, '')), '');
  row      public.pilot_day_reviews;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if p_excluded and v_reason is null then raise exception 'reason_required'; end if;
  if v_reason is not null and length(v_reason) > 500 then raise exception 'note_too_long'; end if;
  -- shared month lock (see pilot_settle_month): a review cannot slip in while a settlement is being finalised
  perform pg_advisory_xact_lock_shared(hashtext('ff10:month:' || to_char(p_day, 'YYYY-MM')));
  if exists (select 1 from public.pilot_settlements where month = to_char(p_day, 'YYYY-MM')) then
    raise exception 'month_settled';
  end if;
  insert into public.pilot_day_reviews (profile_id, day, excluded, reason, reviewed_by, reviewed_at)
  values (p_profile, p_day, p_excluded, v_reason, p_actor, now())
  on conflict (profile_id, day) do update
    set excluded = excluded.excluded, reason = excluded.reason, reviewed_by = excluded.reviewed_by,
        reviewed_at = excluded.reviewed_at
  returning * into row;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, case when p_excluded then 'pilot_day_excluded' else 'pilot_day_restored' end,
          p_profile || ' ' || p_day, to_jsonb(row));
  return row;
end $$;

-- ============================================================================ immutable monthly settlement

create table if not exists public.pilot_settlements (
  month              text primary key check (month ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  budget             int not null check (budget >= 0),
  total_provisional  int not null check (total_provisional >= 0),
  total_final        int not null check (total_final >= 0 and total_final <= budget),
  participants       int not null check (participants >= 0),
  scaled             boolean not null,
  fingerprint        text not null check (fingerprint ~ '^[0-9a-f]{64}$'),   -- the preview the owner confirmed
  finalised_by       text not null,
  finalised_at       timestamptz not null default now()
);

create table if not exists public.pilot_settlement_lines (
  month              text not null references public.pilot_settlements (month),
  profile_id         text not null references public.reward_accounts (profile_id),
  provisional        int not null check (provisional between 0 and 7000),
  final              int not null check (final >= 0 and final <= provisional),
  status             text not null default 'pending_review'
                       check (status in ('pending_review', 'approved', 'withheld', 'paid')),
  decided_by         text,
  decided_at         timestamptz,
  note               text check (note is null or length(note) <= 500),
  paid_at            timestamptz,
  payment_reference  text,
  primary key (month, profile_id)
);

create or replace function public.pilot_settlement_guard() returns trigger
language plpgsql as $$
begin
  if tg_table_name = 'pilot_settlements' or tg_op = 'DELETE' then
    raise exception 'pilot settlements are final and kept unchanged';
  end if;
  if new.month <> old.month or new.profile_id <> old.profile_id or new.provisional <> old.provisional
     or new.final <> old.final then
    raise exception 'settled amounts cannot be changed';
  end if;
  if coalesce(current_setting('we.ff10', true), '') <> 'on' then
    raise exception 'settlement lines change only through the owner functions';
  end if;
  if old.status = 'paid' then raise exception 'already_paid'; end if;
  return new;
end $$;
drop trigger if exists pilot_settlement_guard on public.pilot_settlements;
create trigger pilot_settlement_guard before update or delete on public.pilot_settlements
  for each row execute function public.pilot_settlement_guard();
drop trigger if exists pilot_settlement_lines_guard on public.pilot_settlement_lines;
create trigger pilot_settlement_lines_guard before update or delete on public.pilot_settlement_lines
  for each row execute function public.pilot_settlement_guard();

drop function if exists public.pilot_settle_month(text, text, boolean, int);    -- an earlier draft of this file
create or replace function public.pilot_settle_month(p_month text, p_actor text, p_confirmed boolean,
                                                     p_expected_fingerprint text)
returns public.pilot_settlements
language plpgsql security definer set search_path = public as $$
declare
  preview jsonb;
  line    jsonb;
  row     public.pilot_settlements;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if not coalesce(p_confirmed, false) then raise exception 'confirmation_required'; end if;
  if p_month is null or p_month !~ '^\d{4}-(0[1-9]|1[0-2])$' then raise exception 'invalid_month'; end if;
  if p_month >= to_char(now() at time zone 'Africa/Lagos', 'YYYY-MM') then raise exception 'month_not_ended'; end if;
  perform pg_advisory_xact_lock(hashtext('ff10:settle'));                  -- one settlement at a time
  -- exclusive month lock: day reviews and late activity for this month (shared lock) finish first or wait, and are
  -- refused once the settlement exists
  perform pg_advisory_xact_lock(hashtext('ff10:month:' || p_month));
  if exists (select 1 from public.pilot_settlements where month = p_month) then raise exception 'already_settled'; end if;
  preview := public.pilot_settlement_preview(p_month);                    -- recomputed under the lock
  if p_expected_fingerprint is null or (preview ->> 'fingerprint') <> p_expected_fingerprint then
    raise exception 'preview_changed';                                     -- any participant's amount differs
  end if;
  insert into public.pilot_settlements (month, budget, total_provisional, total_final, participants, scaled,
                                        fingerprint, finalised_by)
  values (p_month, (preview ->> 'budget')::int, (preview ->> 'total_provisional')::int,
          (preview ->> 'total_final')::int, jsonb_array_length(preview -> 'lines'), (preview ->> 'scaled')::boolean,
          preview ->> 'fingerprint', p_actor)
  returning * into row;
  for line in select * from jsonb_array_elements(preview -> 'lines') loop
    insert into public.pilot_settlement_lines (month, profile_id, provisional, final)
    values (p_month, line ->> 'profile_id', (line ->> 'provisional')::int, (line ->> 'final')::int);
  end loop;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, 'pilot_settled', p_month, preview);
  return row;
end $$;

create or replace function public.pilot_settlement_decide(p_month text, p_profile text, p_action text, p_actor text,
                                                          p_note text default null)
returns public.pilot_settlement_lines
language plpgsql security definer set search_path = public as $$
declare
  old_line public.pilot_settlement_lines;
  line     public.pilot_settlement_lines;
  v_note   text := nullif(btrim(coalesce(p_note, '')), '');
  v_new    text;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  v_new := case p_action when 'approve' then 'approved' when 'withhold' then 'withheld' end;
  if v_new is null then raise exception 'invalid_action'; end if;
  select * into old_line from public.pilot_settlement_lines where month = p_month and profile_id = p_profile for update;
  if not found then raise exception 'unknown_line'; end if;
  if old_line.status = 'paid' then raise exception 'already_paid'; end if;
  if old_line.status = v_new then raise exception 'no_change'; end if;
  if v_note is not null and length(v_note) > 500 then raise exception 'note_too_long'; end if;
  if (v_new = 'withheld' or old_line.status <> 'pending_review') and v_note is null then
    raise exception 'reason_required';
  end if;
  perform set_config('we.ff10', 'on', true);
  update public.pilot_settlement_lines
     set status = v_new, decided_by = p_actor, decided_at = now(), note = coalesce(v_note, note)
   where month = p_month and profile_id = p_profile
  returning * into line;
  perform set_config('we.ff10', 'off', true);
  insert into public.reward_audit_log (actor, action, target, old_value, new_value)
  values (p_actor, 'pilot_line_' || v_new, p_profile || ' ' || p_month, to_jsonb(old_line), to_jsonb(line));
  return line;
end $$;

-- Payments stay disabled: payments_enabled is fixed to FALSE by a CHECK constraint, so this always refuses.
create or replace function public.pilot_mark_paid(p_month text, p_profile text, p_actor text, p_reference text)
returns public.pilot_settlement_lines
language plpgsql security definer set search_path = public as $$
declare
  line public.pilot_settlement_lines;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if not coalesce((select payments_enabled from public.pilot_reward_settings where id = 1), false)
     or not coalesce((select real_payouts from public.reward_cashout_settings where id = 1), false) then
    raise exception 'payments_disabled';
  end if;
  select * into line from public.pilot_settlement_lines where month = p_month and profile_id = p_profile for update;
  if not found then raise exception 'unknown_line'; end if;
  if line.status <> 'approved' then raise exception 'not_approved'; end if;
  perform set_config('we.ff10', 'on', true);
  update public.pilot_settlement_lines set status = 'paid', paid_at = now(), payment_reference = p_reference,
         decided_by = p_actor, decided_at = now()
   where month = p_month and profile_id = p_profile returning * into line;
  perform set_config('we.ff10', 'off', true);
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, 'pilot_line_paid', p_profile || ' ' || p_month, to_jsonb(line));
  return line;
end $$;

-- ============================================================================ security

alter table public.pilot_reward_settings  enable row level security;
alter table public.pilot_activity         enable row level security;
alter table public.pilot_day_reviews      enable row level security;
alter table public.pilot_settlements      enable row level security;
alter table public.pilot_settlement_lines enable row level security;
revoke all on public.pilot_reward_settings, public.pilot_activity, public.pilot_day_reviews,
              public.pilot_settlements, public.pilot_settlement_lines from public, anon, authenticated;
-- the app reads with the server key; every change goes through the functions below (test rows may be deleted)
grant select on public.pilot_reward_settings, public.pilot_day_reviews, public.pilot_settlements,
                public.pilot_settlement_lines to service_role;
grant select, delete on public.pilot_activity to service_role;

revoke execute on function public.pilot_places_guard()                                   from public, anon, authenticated;
revoke execute on function public.pilot_activity_guard()                                 from public, anon, authenticated;
revoke execute on function public.pilot_settlement_guard()                               from public, anon, authenticated;
revoke execute on function public.pilot_is_participant(text)                             from public, anon, authenticated;
revoke execute on function public.pilot_record_activity_at(text, text, text, jsonb, timestamptz)
                                                                                          from public, anon, authenticated, service_role;
revoke execute on function public.pilot_record_activity(text, text, text, jsonb)         from public, anon, authenticated;
revoke execute on function public.pilot_tier(int, int, int, boolean)                     from public, anon, authenticated;
revoke execute on function public.pilot_tier_amount(int)                                 from public, anon, authenticated;
revoke execute on function public.pilot_month_ledger(text, text)                         from public, anon, authenticated;
revoke execute on function public.pilot_month_total(text, text)                          from public, anon, authenticated;
revoke execute on function public.pilot_month_days(text, text)                           from public, anon, authenticated;
revoke execute on function public.pilot_settlement_preview(text)                         from public, anon, authenticated;
revoke execute on function public.pilot_review_day(text, date, boolean, text, text)      from public, anon, authenticated;
revoke execute on function public.pilot_settle_month(text, text, boolean, text)          from public, anon, authenticated;
revoke execute on function public.pilot_settlement_decide(text, text, text, text, text)  from public, anon, authenticated;
revoke execute on function public.pilot_mark_paid(text, text, text, text)                from public, anon, authenticated;
grant  execute on function public.pilot_is_participant(text)                             to service_role;
grant  execute on function public.pilot_record_activity(text, text, text, jsonb)         to service_role;
grant  execute on function public.pilot_tier(int, int, int, boolean)                     to service_role;
grant  execute on function public.pilot_tier_amount(int)                                 to service_role;
grant  execute on function public.pilot_month_ledger(text, text)                         to service_role;
grant  execute on function public.pilot_month_total(text, text)                          to service_role;
grant  execute on function public.pilot_month_days(text, text)                           to service_role;
grant  execute on function public.pilot_settlement_preview(text)                         to service_role;
grant  execute on function public.pilot_review_day(text, date, boolean, text, text)      to service_role;
grant  execute on function public.pilot_settle_month(text, text, boolean, text)          to service_role;
grant  execute on function public.pilot_settlement_decide(text, text, text, text, text)  to service_role;
grant  execute on function public.pilot_mark_paid(text, text, text, text)                to service_role;

-- Check after running (expected: 0 rows):
--   select table_name, grantee from information_schema.role_table_grants
--    where table_name like 'pilot\_%' and grantee in ('anon', 'authenticated');
