-- World Explorer — Referral & Monthly Rewards (pilot) — database schema
--
-- Run once in Supabase → SQL Editor (see REWARDS_SETUP.md). It only ADDS new objects whose names start with
-- reward_ / user_referrals; the existing tables (world_explorer_profiles, world_explorer_events,
-- world_explorer_feedback) are not touched. Safe to run again: every statement is "if not exists" / "or replace".
--
-- Security model (same as the existing tables): Row Level Security on, no access at all for the browser roles
-- (anon, authenticated), access only for the server key (service_role) that the app uses on the server.
--
-- The money rules live HERE as well as in the app: the app asks for a reward, the database decides how much is
-- stored (trigger reward_events_cap). Earned amounts can never be edited afterwards, enrolment is atomic, and
-- every change to settings and payments is written to reward_audit_log automatically.
--
-- Money is whole naira. Days and months follow Nigeria time (Africa/Lagos, UTC+1).

-- ============================================================================ tables

create table if not exists public.reward_program_settings (
  id                 int primary key default 1 check (id = 1),           -- exactly one row
  monthly_cap        int not null default 1000  check (monthly_cap > 0),
  active_day_amount  int not null default 25    check (active_day_amount >= 0),
  active_day_max     int not null default 20    check (active_day_max >= 0),
  quiz_amount        int not null default 10    check (quiz_amount >= 0),
  quiz_max_month     int not null default 30    check (quiz_max_month >= 0),
  quiz_max_day       int not null default 3     check (quiz_max_day >= 0),
  country_amount     int not null default 5     check (country_amount >= 0),
  country_max_month  int not null default 40    check (country_max_month >= 0),
  country_max_day    int not null default 5     check (country_max_day >= 0),
  referral_amount    int not null default 50    check (referral_amount >= 0),
  referral_max_month int not null default 4     check (referral_max_month >= 0),
  monthly_budget     int not null default 50000 check (monthly_budget >= 0),
  max_places         int not null default 50    check (max_places >= 0),
  start_date         date not null default date '2026-10-01',
  paused             boolean not null default false,
  updated_at         timestamptz not null default now(),
  updated_by         text,
  -- people must be able to reach the monthly maximum without referrals
  constraint reward_settings_reachable check (
    active_day_amount * active_day_max + quiz_amount * quiz_max_month + country_amount * country_max_month
      >= monthly_cap)
);
insert into public.reward_program_settings (id) values (1) on conflict (id) do nothing;

create table if not exists public.reward_accounts (
  profile_id          text primary key check (profile_id ~ '^[0-9a-f]{64}$'),   -- same id as world_explorer_profiles
  referral_code       text not null unique check (referral_code ~ '^WE[2-9A-HJ-NP-Z]{4}$'),
  email               text,                                   -- Google-verified email, for the owner only
  display_name        text,
  created_at          timestamptz not null default now(),
  new_registration    boolean not null default false,         -- profile did not exist before this account
  membership          text not null default 'none'
                        check (membership in ('none','member','withdrawn','suspended')),
  age_confirmed       boolean not null default false,         -- self-declaration (provisional only)
  residence_confirmed boolean not null default false,         -- self-declaration (provisional only)
  terms_version       text,
  declared_at         timestamptz,
  verification        text not null default 'provisional'
                        check (verification in ('provisional','verified','failed')),
  verification_note   text,
  review              text not null default 'ok' check (review in ('ok','review','hold')),
  review_note         text,
  test                boolean not null default false,
  constraint reward_member_declared check (
    membership <> 'member' or (age_confirmed and residence_confirmed and terms_version is not null))
);

create table if not exists public.reward_enrolments (
  profile_id       text not null references public.reward_accounts (profile_id),
  month            text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  status           text not null check (status in ('enrolled','waitlist','withdrawn')),
  reserved_amount  int not null default 0 check (reserved_amount >= 0),
  waitlist_position int,
  test             boolean not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  primary key (profile_id, month)
);
create index if not exists reward_enrolments_month on public.reward_enrolments (month, status);

create table if not exists public.reward_activity_events (
  event_key   text primary key,                               -- deterministic: repeats are ignored
  profile_id  text not null references public.reward_accounts (profile_id),
  kind        text not null check (kind in ('active_day','quiz','country','referral')),
  subject     text not null,                                  -- quiz round id, country id, day, referred profile
  month       text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  day         date not null,
  amount      int not null default 0 check (amount >= 0),     -- set by the trigger, never by the app alone
  reason      text,                                           -- why the amount is what it is (set by the trigger)
  test        boolean not null default false,
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  constraint reward_event_month_matches_day check (month = to_char(day, 'YYYY-MM'))
);
create index if not exists reward_events_profile_month on public.reward_activity_events (profile_id, month);
create index if not exists reward_events_month on public.reward_activity_events (month);

create table if not exists public.user_referrals (
  referred_id  text primary key references public.reward_accounts (profile_id),   -- one referrer per account
  referrer_id  text not null references public.reward_accounts (profile_id),
  code         text not null,
  status       text not null default 'pending' check (status in ('pending','qualified','approved','rejected')),
  created_at   timestamptz not null default now(),
  qualified_at timestamptz,
  decided_at   timestamptz,
  decided_by   text,
  note         text,
  test         boolean not null default false,
  constraint user_referrals_not_self check (referred_id <> referrer_id)
);
create index if not exists user_referrals_referrer on public.user_referrals (referrer_id);

create table if not exists public.reward_referral_visits (
  visit_key   text primary key,                               -- one row per browser session and code
  code        text not null,
  referrer_id text references public.reward_accounts (profile_id),
  outcome     text not null default 'visit'
                check (outcome in ('visit','attributed','existing_account','self','unknown_code','already_referred',
                                   'circular')),
  referred_id text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  test        boolean not null default false
);
create index if not exists reward_visits_referrer on public.reward_referral_visits (referrer_id);

create table if not exists public.reward_payments (
  profile_id      text not null references public.reward_accounts (profile_id),
  month           text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  earned          int not null default 0 check (earned >= 0),         -- snapshot when the review was opened
  approved_amount int not null default 0 check (approved_amount >= 0),
  paid_amount     int not null default 0 check (paid_amount >= 0),
  status          text not null default 'pending_review'
                    check (status in ('pending_review','approved','paid','on_hold','rejected')),
  payment_date    date,
  reference       text check (reference is null or length(reference) <= 120),
  remarks         text check (remarks is null or length(remarks) <= 1000),
  reason          text check (reason is null or length(reason) <= 500),
  test            boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  updated_by      text,
  primary key (profile_id, month),
  constraint reward_paid_within_approved check (paid_amount <= approved_amount),
  constraint reward_paid_has_date check (status <> 'paid' or (payment_date is not null and paid_amount > 0)),
  constraint reward_test_never_payable check (not test or status in ('pending_review','on_hold','rejected'))
);

create table if not exists public.reward_audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  actor       text,
  action      text not null,
  target      text,
  old_value   jsonb,
  new_value   jsonb
);
create index if not exists reward_audit_at on public.reward_audit_log (at);

-- Monthly totals per person (always up to date, so there is nothing to recalculate at the month change)
create or replace view public.reward_monthly_summary as
  select profile_id, month, test,
         coalesce(sum(amount) filter (where kind = 'active_day'), 0)::int as active_day_amount,
         coalesce(sum(amount) filter (where kind = 'quiz'), 0)::int        as quiz_amount,
         coalesce(sum(amount) filter (where kind = 'country'), 0)::int     as country_amount,
         coalesce(sum(amount) filter (where kind = 'referral'), 0)::int    as referral_amount,
         coalesce(sum(amount), 0)::int                                     as total_amount,
         count(*) filter (where kind = 'active_day')::int                  as active_days,
         count(*) filter (where kind = 'quiz')::int                        as quizzes,
         count(*) filter (where kind = 'country')::int                     as countries,
         count(*) filter (where kind = 'referral')::int                    as referrals
    from public.reward_activity_events
   group by profile_id, month, test;

-- ============================================================================ the reward rules (trigger)

create or replace function public.reward_events_cap() returns trigger
language plpgsql set search_path = public as $$
declare
  s          public.reward_program_settings%rowtype;
  base       int;
  lim_month  int;
  lim_day    int;
  n_day      int;
  n_month    int;
  sum_kind   int;
  sum_total  int;
begin
  -- one person's events for one month are decided one at a time
  perform pg_advisory_xact_lock(hashtext('reward:' || new.profile_id || ':' || new.month));
  new.created_at := now();
  -- test (preview) records follow the account, so a tester can never create a real, payable record
  select a.test into new.test from public.reward_accounts a where a.profile_id = new.profile_id;
  new.test := coalesce(new.test, false);
  if new.amount is null or new.amount <= 0 then
    new.amount := 0; new.reason := coalesce(new.reason, 'activity_only'); return new;
  end if;
  select * into s from public.reward_program_settings where id = 1;
  if not exists (select 1 from public.reward_accounts a
                  where a.profile_id = new.profile_id and a.membership = 'member' and a.test = new.test)
     or not exists (select 1 from public.reward_enrolments e
                     where e.profile_id = new.profile_id and e.month = new.month and e.status = 'enrolled'
                       and e.test = new.test) then
    new.amount := 0; new.reason := 'not_enrolled'; return new;
  end if;
  if s.paused then new.amount := 0; new.reason := 'paused'; return new; end if;
  if new.day < s.start_date then new.amount := 0; new.reason := 'not_started'; return new; end if;

  base := case new.kind when 'active_day' then s.active_day_amount when 'quiz' then s.quiz_amount
                        when 'country' then s.country_amount else s.referral_amount end;
  lim_month := case new.kind when 'active_day' then s.active_day_max when 'quiz' then s.quiz_max_month
                             when 'country' then s.country_max_month else s.referral_max_month end;
  lim_day := case new.kind when 'active_day' then 1 when 'quiz' then s.quiz_max_day
                           when 'country' then s.country_max_day else null end;

  select count(*) filter (where kind = new.kind and day = new.day),
         count(*) filter (where kind = new.kind),
         coalesce(sum(amount) filter (where kind = new.kind), 0),
         coalesce(sum(amount), 0)
    into n_day, n_month, sum_kind, sum_total
    from public.reward_activity_events
   where profile_id = new.profile_id and month = new.month and test = new.test and amount > 0;

  if lim_day is not null and n_day >= lim_day then new.amount := 0; new.reason := 'day_limit'; return new; end if;
  if n_month >= lim_month then new.amount := 0; new.reason := 'month_limit'; return new; end if;
  new.amount := least(base, base * lim_month - sum_kind, s.monthly_cap - sum_total);
  if new.amount <= 0 then new.amount := 0; new.reason := 'monthly_cap'; return new; end if;
  new.reason := case when new.amount = base then 'awarded' else 'partial_cap' end;
  return new;
end $$;

drop trigger if exists reward_events_cap on public.reward_activity_events;
create trigger reward_events_cap before insert on public.reward_activity_events
  for each row execute function public.reward_events_cap();

-- earned rewards are never edited; only test records may be removed (to clear owner testing)
create or replace function public.reward_events_frozen() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'DELETE' and old.test then return old; end if;
  raise exception 'reward events cannot be changed or deleted (event %)', old.event_key;
end $$;

drop trigger if exists reward_events_frozen on public.reward_activity_events;
create trigger reward_events_frozen before update or delete on public.reward_activity_events
  for each row execute function public.reward_events_frozen();

-- ============================================================================ accounts and referrals

-- Create (or return) a person's reward account with a permanent, unique referral code.
create or replace function public.reward_ensure_account(p_profile text, p_email text, p_name text,
                                                        p_new boolean, p_test boolean default false)
returns public.reward_accounts
language plpgsql set search_path = public as $$
declare
  acc   public.reward_accounts%rowtype;
  alpha constant text := '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
  code  text;
begin
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if found then
    if p_email is not null and acc.email is distinct from p_email then
      update public.reward_accounts set email = p_email where profile_id = p_profile returning * into acc;
    end if;
    return acc;
  end if;
  for attempt in 1 .. 50 loop
    code := 'WE';
    for i in 1 .. 4 loop
      code := code || substr(alpha, 1 + floor(random() * length(alpha))::int, 1);
    end loop;
    begin
      insert into public.reward_accounts (profile_id, referral_code, email, display_name, new_registration, test)
      values (p_profile, code, p_email, left(p_name, 80), coalesce(p_new, false), coalesce(p_test, false))
      returning * into acc;
      return acc;
    exception when unique_violation then
      select * into acc from public.reward_accounts where profile_id = p_profile;   -- created meanwhile
      if found then return acc; end if;                                              -- else: code taken, retry
    end;
  end loop;
  raise exception 'could not allocate a referral code';
end $$;

-- Attribute a newly registered account to the owner of a referral code. Returns the outcome:
-- attributed | existing_account | self | unknown_code | already_referred | circular
create or replace function public.reward_attribute(p_referred text, p_code text, p_visit text default null)
returns text
language plpgsql set search_path = public as $$
declare
  ref_acc public.reward_accounts%rowtype;
  me      public.reward_accounts%rowtype;
  v_outcome text;
begin
  perform pg_advisory_xact_lock(hashtext('referral:' || p_referred));
  select * into ref_acc from public.reward_accounts where referral_code = upper(trim(p_code));
  select * into me from public.reward_accounts where profile_id = p_referred;
  if not found or ref_acc.profile_id is null then
    v_outcome := 'unknown_code';
  elsif ref_acc.profile_id = p_referred then
    v_outcome := 'self';
  elsif exists (select 1 from public.user_referrals where referred_id = p_referred) then
    v_outcome := 'already_referred';
  elsif not me.new_registration then
    v_outcome := 'existing_account';
  elsif exists (select 1 from public.user_referrals where referred_id = ref_acc.profile_id
                                                     and referrer_id = p_referred) then
    v_outcome := 'circular';
  elsif ref_acc.test <> me.test then
    v_outcome := 'unknown_code';                                   -- test and real accounts never mix
  else
    insert into public.user_referrals (referred_id, referrer_id, code, test)
    values (p_referred, ref_acc.profile_id, ref_acc.referral_code, me.test);
    v_outcome := 'attributed';
  end if;
  if p_visit is not null then
    update public.reward_referral_visits
       set outcome = v_outcome, referred_id = p_referred, updated_at = now(),
           referrer_id = coalesce(referrer_id, ref_acc.profile_id)
     where visit_key = p_visit;
  end if;
  return v_outcome;
end $$;

-- ============================================================================ enrolment (atomic)

-- Enrol a member for a month. Real enrolments reserve the monthly maximum from the budget; when places or budget
-- run out the person joins the waiting list. Returns the enrolment row (status enrolled | waitlist | withdrawn).
-- Raises 'paused' or 'not_member' when enrolment is not possible.
create or replace function public.reward_enrol(p_profile text, p_month text)
returns public.reward_enrolments
language plpgsql set search_path = public as $$
declare
  s      public.reward_program_settings%rowtype;
  acc    public.reward_accounts%rowtype;
  row_   public.reward_enrolments%rowtype;
  places int;
  used   int;
  pos    int;
begin
  perform pg_advisory_xact_lock(hashtext('enrol:' || p_month));
  select * into row_ from public.reward_enrolments where profile_id = p_profile and month = p_month;
  if found then return row_; end if;
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if not found or acc.membership <> 'member' then raise exception 'not_member'; end if;
  select * into s from public.reward_program_settings where id = 1;
  if s.paused then raise exception 'paused'; end if;

  if acc.test then   -- owner/tester previews never use real places or budget
    insert into public.reward_enrolments (profile_id, month, status, reserved_amount, test)
    values (p_profile, p_month, 'enrolled', s.monthly_cap, true) returning * into row_;
    return row_;
  end if;

  select count(*) filter (where status = 'enrolled'),
         coalesce(sum(reserved_amount) filter (where status in ('enrolled','withdrawn')), 0)
    into places, used
    from public.reward_enrolments where month = p_month and not test;
  if places < s.max_places and used + s.monthly_cap <= s.monthly_budget
     and not exists (select 1 from public.reward_enrolments
                      where month = p_month and not test and status = 'waitlist') then
    insert into public.reward_enrolments (profile_id, month, status, reserved_amount)
    values (p_profile, p_month, 'enrolled', s.monthly_cap) returning * into row_;
  else
    select coalesce(max(waitlist_position), 0) + 1 into pos
      from public.reward_enrolments where month = p_month and not test;
    insert into public.reward_enrolments (profile_id, month, status, waitlist_position)
    values (p_profile, p_month, 'waitlist', pos) returning * into row_;
  end if;
  return row_;
end $$;

-- Move people from the waiting list into free places (first come, first served). Returns how many moved.
create or replace function public.reward_promote_waitlist(p_month text, p_actor text default null)
returns int
language plpgsql set search_path = public as $$
declare
  s      public.reward_program_settings%rowtype;
  places int;
  used   int;
  moved  int := 0;
  w      record;
begin
  perform pg_advisory_xact_lock(hashtext('enrol:' || p_month));
  select * into s from public.reward_program_settings where id = 1;
  if s.paused then return 0; end if;
  for w in select e.profile_id from public.reward_enrolments e
             join public.reward_accounts a on a.profile_id = e.profile_id
            where e.month = p_month and not e.test and e.status = 'waitlist' and a.membership = 'member'
            order by e.waitlist_position, e.created_at loop
    select count(*) filter (where status = 'enrolled'),
           coalesce(sum(reserved_amount) filter (where status in ('enrolled','withdrawn')), 0)
      into places, used
      from public.reward_enrolments where month = p_month and not test;
    exit when places >= s.max_places or used + s.monthly_cap > s.monthly_budget;
    update public.reward_enrolments
       set status = 'enrolled', reserved_amount = s.monthly_cap, waitlist_position = null, updated_at = now()
     where profile_id = w.profile_id and month = p_month;
    moved := moved + 1;
  end loop;
  if moved > 0 then
    insert into public.reward_audit_log (actor, action, target, new_value)
    values (p_actor, 'waitlist_promoted', p_month, jsonb_build_object('moved', moved));
  end if;
  return moved;
end $$;

-- Leave the programme for a month: what was already earned stays reserved (and payable once approved); the rest of
-- the reservation is released and the place goes to the waiting list.
create or replace function public.reward_withdraw(p_profile text, p_month text, p_actor text default null)
returns public.reward_enrolments
language plpgsql set search_path = public as $$
declare
  row_   public.reward_enrolments%rowtype;
  earned int;
begin
  perform pg_advisory_xact_lock(hashtext('enrol:' || p_month));
  perform pg_advisory_xact_lock(hashtext('reward:' || p_profile || ':' || p_month));   -- no award in flight
  select coalesce(sum(amount), 0) into earned from public.reward_activity_events
   where profile_id = p_profile and month = p_month;
  update public.reward_enrolments
     set status = 'withdrawn', reserved_amount = least(reserved_amount, earned), waitlist_position = null,
         updated_at = now()
   where profile_id = p_profile and month = p_month and status <> 'withdrawn'
  returning * into row_;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (coalesce(p_actor, p_profile), 'withdrawn', p_profile || ' ' || p_month,
          jsonb_build_object('earned', earned));
  return row_;
end $$;

-- ============================================================================ payments and audit

create or replace function public.reward_payments_guard() returns trigger
language plpgsql set search_path = public as $$
declare
  earned_now int;
  acc        public.reward_accounts%rowtype;
begin
  new.updated_at := now();
  select coalesce(sum(amount), 0) into earned_now from public.reward_activity_events
   where profile_id = new.profile_id and month = new.month and test = new.test;
  if tg_op = 'INSERT' then
    new.earned := earned_now;
  end if;
  if tg_op = 'UPDATE' and old.status = 'paid' then
    if new.status <> 'paid' or new.paid_amount <> old.paid_amount or new.approved_amount <> old.approved_amount
       or new.payment_date is distinct from old.payment_date then
      raise exception 'a completed payment cannot be changed; add a remark instead';
    end if;
  end if;
  if new.approved_amount > earned_now then
    raise exception 'approved amount (%) is more than was earned (%)', new.approved_amount, earned_now;
  end if;
  if new.status in ('approved','paid') then
    select * into acc from public.reward_accounts where profile_id = new.profile_id;
    if acc.test or new.test then raise exception 'test records are never payable'; end if;
    if acc.verification <> 'verified' then
      raise exception 'verify the participant''s eligibility before approving a payment';
    end if;
    if new.approved_amount <= 0 then raise exception 'set the approved amount first'; end if;
  end if;
  if new.status = 'paid' and tg_op = 'UPDATE' and old.status not in ('approved','paid') then
    raise exception 'only an approved payment can be marked as paid';
  end if;
  if new.status = 'paid' and tg_op = 'INSERT' then
    raise exception 'only an approved payment can be marked as paid';
  end if;
  if new.status = 'rejected' then new.approved_amount := 0; new.paid_amount := 0; end if;
  return new;
end $$;

drop trigger if exists reward_payments_guard on public.reward_payments;
create trigger reward_payments_guard before insert or update on public.reward_payments
  for each row execute function public.reward_payments_guard();

create or replace function public.reward_no_delete() returns trigger
language plpgsql as $$
begin
  if old.test then return old; end if;
  raise exception '% records are kept for the audit trail and cannot be deleted', tg_table_name;
end $$;

drop trigger if exists reward_payments_keep on public.reward_payments;
create trigger reward_payments_keep before delete on public.reward_payments
  for each row execute function public.reward_no_delete();
drop trigger if exists reward_enrolments_keep on public.reward_enrolments;
create trigger reward_enrolments_keep before delete on public.reward_enrolments
  for each row execute function public.reward_no_delete();
drop trigger if exists reward_referrals_keep on public.user_referrals;
create trigger reward_referrals_keep before delete on public.user_referrals
  for each row execute function public.reward_no_delete();
drop trigger if exists reward_visits_keep on public.reward_referral_visits;
create trigger reward_visits_keep before delete on public.reward_referral_visits
  for each row execute function public.reward_no_delete();

-- automatic audit trail for settings, payments, account reviews and referral decisions
create or replace function public.reward_audit() returns trigger
language plpgsql set search_path = public as $$
declare
  actor  text;
  target text;
begin
  actor := coalesce(to_jsonb(new) ->> 'updated_by', to_jsonb(new) ->> 'decided_by');
  target := case tg_table_name
              when 'reward_program_settings' then 'settings'
              when 'reward_payments' then (to_jsonb(new) ->> 'profile_id') || ' ' || (to_jsonb(new) ->> 'month')
              when 'user_referrals' then to_jsonb(new) ->> 'referred_id'
              else to_jsonb(new) ->> 'profile_id' end;
  insert into public.reward_audit_log (actor, action, target, old_value, new_value)
  values (actor, tg_table_name || '_' || lower(tg_op), target,
          case when tg_op = 'UPDATE' then to_jsonb(old) end, to_jsonb(new));
  return new;
end $$;

drop trigger if exists reward_settings_audit on public.reward_program_settings;
create trigger reward_settings_audit after update on public.reward_program_settings
  for each row execute function public.reward_audit();
drop trigger if exists reward_payments_audit on public.reward_payments;
create trigger reward_payments_audit after insert or update on public.reward_payments
  for each row execute function public.reward_audit();
drop trigger if exists reward_accounts_audit on public.reward_accounts;
create trigger reward_accounts_audit after update of membership, verification, review on public.reward_accounts
  for each row execute function public.reward_audit();
drop trigger if exists reward_referrals_audit on public.user_referrals;
create trigger reward_referrals_audit after update of status on public.user_referrals
  for each row execute function public.reward_audit();

create or replace function public.reward_audit_frozen() returns trigger
language plpgsql as $$
begin
  raise exception 'the audit log cannot be changed';
end $$;

drop trigger if exists reward_audit_frozen on public.reward_audit_log;
create trigger reward_audit_frozen before update or delete on public.reward_audit_log
  for each row execute function public.reward_audit_frozen();

-- ============================================================================ access (server only)

alter table public.reward_program_settings enable row level security;
alter table public.reward_accounts         enable row level security;
alter table public.reward_enrolments       enable row level security;
alter table public.reward_activity_events  enable row level security;
alter table public.user_referrals          enable row level security;
alter table public.reward_referral_visits  enable row level security;
alter table public.reward_payments         enable row level security;
alter table public.reward_audit_log        enable row level security;

revoke all on public.reward_program_settings, public.reward_accounts, public.reward_enrolments,
              public.reward_activity_events, public.user_referrals, public.reward_referral_visits,
              public.reward_payments, public.reward_audit_log, public.reward_monthly_summary
  from public, anon, authenticated;

grant select, update                 on public.reward_program_settings to service_role;
grant select, insert, update         on public.reward_accounts         to service_role;
grant select, insert, update, delete on public.reward_enrolments       to service_role;   -- delete: test rows only
grant select, insert, delete         on public.reward_activity_events  to service_role;   -- delete: test rows only
grant select, insert, update, delete on public.user_referrals          to service_role;   -- delete: test rows only
grant select, insert, update, delete on public.reward_referral_visits  to service_role;   -- delete: test rows only
grant select, insert, update, delete on public.reward_payments         to service_role;   -- delete: test rows only
grant select, insert                 on public.reward_audit_log        to service_role;
grant select                         on public.reward_monthly_summary  to service_role;

-- functions are executable by everyone by default in PostgreSQL: limit them to the server key
revoke execute on function public.reward_ensure_account(text, text, text, boolean, boolean) from public, anon, authenticated;
revoke execute on function public.reward_attribute(text, text, text)                     from public, anon, authenticated;
revoke execute on function public.reward_enrol(text, text)                               from public, anon, authenticated;
revoke execute on function public.reward_promote_waitlist(text, text)                    from public, anon, authenticated;
revoke execute on function public.reward_withdraw(text, text, text)                      from public, anon, authenticated;
grant  execute on function public.reward_ensure_account(text, text, text, boolean, boolean) to service_role;
grant  execute on function public.reward_attribute(text, text, text)                     to service_role;
grant  execute on function public.reward_enrol(text, text)                               to service_role;
grant  execute on function public.reward_promote_waitlist(text, text)                    to service_role;
grant  execute on function public.reward_withdraw(text, text, text)                      to service_role;
