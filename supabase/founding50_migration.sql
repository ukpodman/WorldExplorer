-- World Explorer — FOUNDING 50 approval system — additive migration
--
-- Run AFTER supabase/rewards_schema.sql, supabase/withdrawals_migration.sql and
-- supabase/public_programme_migration.sql, in Supabase → SQL Editor (see FOUNDING50_SETUP.md). Safe to run again.
-- It does not change any existing player record, reward, enrolment, payment or withdrawal.
--
-- Option B: anyone can apply, only the Owner approves.
--   * reward_founding_applications: one application per person (duplicates are refused). Status: pending, approved,
--     rejected or waitlist. Applying, approving, rejecting and waiting-listing happen only through the functions
--     below; every change is written to reward_audit_log. A new application stays "unseen" (the Owner dashboard
--     notification) until the Owner opens or decides it.
--   * Only APPROVED participants can earn money. For real (non-test) accounts the database
--       - refuses enrolment and waiting-list moves without an approved application ('not_approved');
--       - records activity of anyone else with ₦0 (reason 'not_approved');
--       - refuses withdrawal requests, withdrawal approvals/payments and monthly payment approvals/payments for
--         people who were never approved or whose approval the Owner later rejected.
--   * At most max_places (50) approved participants at a time ('places_full'); the monthly enrolment limit of 50
--     places, the ₦50,000 monthly budget and the ₦1,000 monthly maximum are unchanged.
--   * The 30-day withdrawal wait starts at the first official enrolment after the Owner first approved the
--     application (reward_enrolments.enrolled_at, set by the database), not at applying or creating the account.
--   * Real applications are accepted only while the public programme switch is ON. Owner and tester (test) accounts
--     can try the whole flow at any time; their records are test records and never payable.
--
-- Nothing here switches the programme on, enables payouts or withdrawals, or approves anybody automatically.
-- If you ever run supabase/withdrawals_migration.sql again, run this file again afterwards (it extends
-- reward_cashout_status with the Founding 50 rules).

do $$
begin
  if to_regclass('public.reward_program_settings') is null then
    raise exception 'Run supabase/rewards_schema.sql first (the rewards tables are missing).';
  end if;
  if to_regprocedure('public.reward_cashout_is_owner(text)') is null then
    raise exception 'Run supabase/withdrawals_migration.sql first (it holds the owner list).';
  end if;
  if to_regprocedure('public.reward_public_on()') is null then
    raise exception 'Run supabase/public_programme_migration.sql first (the public programme switch).';
  end if;
end $$;

-- ============================================================================ tables

create table if not exists public.reward_founding_applications (
  id                  bigint generated always as identity primary key,
  profile_id          text not null unique references public.reward_accounts (profile_id),   -- one per person
  status              text not null default 'pending' check (status in ('pending','approved','rejected','waitlist')),
  state               text not null check (length(state) between 2 and 40),   -- Nigerian state of residence
  note                text check (note is null or length(note) <= 300),
  age_confirmed       boolean not null,
  residence_confirmed boolean not null,
  terms_version       text not null,
  applied_at          timestamptz not null default now(),
  first_approved_at   timestamptz,          -- first approval ever: the withdrawal clock counts enrolments after it
  approved_at         timestamptz,          -- latest approval
  decided_at          timestamptz,
  decided_by          text,
  decision_note       text check (decision_note is null or length(decision_note) <= 500),
  seen_at             timestamptz,          -- null = a new application the Owner has not opened yet
  seen_by             text,
  test                boolean not null default false,
  updated_at          timestamptz not null default now(),
  constraint reward_founding_declared check (age_confirmed and residence_confirmed),
  constraint reward_founding_approval_kept check (status <> 'approved' or first_approved_at is not null)
);
create index if not exists reward_founding_status on public.reward_founding_applications (status, applied_at);
create index if not exists reward_founding_unseen on public.reward_founding_applications (seen_at, applied_at);

-- the moment a place was actually taken (a waiting-list row promoted later gets its own time)
alter table public.reward_enrolments add column if not exists enrolled_at timestamptz;

-- ============================================================================ helpers

-- may this account take part and earn? Test (owner/tester) accounts always may; real accounts need APPROVED.
create or replace function public.reward_founding_approved(p_profile text) returns boolean
language sql stable set search_path = public as $$
  select coalesce((select a.test from public.reward_accounts a where a.profile_id = p_profile), false)
      or exists (select 1 from public.reward_founding_applications f
                  where f.profile_id = p_profile and f.status = 'approved' and not f.test)
$$;

-- is a real account barred from withdrawals and payments? Yes when it was never approved, or when the Owner
-- rejected it after approval. (Moved back to the waiting list: earnings already earned stay payable.)
create or replace function public.reward_founding_blocks(p_profile text) returns boolean
language sql stable set search_path = public as $$
  select not coalesce((select a.test from public.reward_accounts a where a.profile_id = p_profile), false)
     and not exists (select 1 from public.reward_founding_applications f
                      where f.profile_id = p_profile and f.first_approved_at is not null
                        and f.status <> 'rejected' and not f.test)
$$;

-- start of the 30-day withdrawal wait: the first official enrolment (a place actually taken) after the first
-- approval. Test accounts: the first enrolment, as before.
create or replace function public.reward_founding_joined(p_profile text, p_test boolean) returns timestamptz
language sql stable set search_path = public as $$
  select min(coalesce(e.enrolled_at, e.created_at))
    from public.reward_enrolments e
   where e.profile_id = p_profile and e.test = p_test
     and (e.status = 'enrolled' or (e.status = 'withdrawn' and e.reserved_amount > 0))
     and (p_test or coalesce(e.enrolled_at, e.created_at) >=
                    (select f.first_approved_at from public.reward_founding_applications f
                      where f.profile_id = p_profile and not f.test))
$$;

create or replace function public.reward_founding_states() returns text[]
language sql immutable as $$
  select array['Abia','Adamawa','Akwa Ibom','Anambra','Bauchi','Bayelsa','Benue','Borno','Cross River','Delta',
               'Ebonyi','Edo','Ekiti','Enugu','FCT Abuja','Gombe','Imo','Jigawa','Kaduna','Kano','Katsina','Kebbi',
               'Kogi','Kwara','Lagos','Nasarawa','Niger','Ogun','Ondo','Osun','Oyo','Plateau','Rivers','Sokoto',
               'Taraba','Yobe','Zamfara']
$$;

-- ============================================================================ apply (the player)

create or replace function public.reward_founding_apply(p_profile text, p_state text, p_note text,
                                                        p_adult boolean, p_resident boolean, p_terms boolean,
                                                        p_terms_version text)
returns public.reward_founding_applications
language plpgsql set search_path = public as $$
declare
  acc public.reward_accounts%rowtype;
  app public.reward_founding_applications%rowtype;
begin
  perform pg_advisory_xact_lock(hashtext('founding:' || p_profile));
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if not found then raise exception 'no_account'; end if;
  if exists (select 1 from public.reward_founding_applications where profile_id = p_profile) then
    raise exception 'already_applied';
  end if;
  if not (coalesce(p_adult, false) and coalesce(p_resident, false) and coalesce(p_terms, false)) then
    raise exception 'declarations_required';
  end if;
  if p_state is null or not (btrim(p_state) = any (public.reward_founding_states())) then
    raise exception 'state_required';
  end if;
  if length(coalesce(p_note, '')) > 300 then raise exception 'note_too_long'; end if;
  if coalesce(btrim(p_terms_version), '') = '' then raise exception 'declarations_required'; end if;
  if not acc.test and acc.membership = 'suspended' then raise exception 'suspended'; end if;
  if not acc.test and not public.reward_public_on() then raise exception 'programme_off'; end if;
  perform set_config('we.founding', 'on', true);
  insert into public.reward_founding_applications (profile_id, state, note, age_confirmed, residence_confirmed,
                                                   terms_version, test)
  values (p_profile, btrim(p_state), nullif(btrim(coalesce(p_note, '')), ''), true, true, btrim(p_terms_version),
          acc.test)
  returning * into app;
  perform set_config('we.founding', 'off', true);
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_profile, 'founding_applied', p_profile, to_jsonb(app));
  return app;
end $$;

-- ============================================================================ decide (the Owner)

-- p_action: approve | reject | waitlist. A reason is required to reject, and to take a place away from an
-- approved participant. Taking an approved participant off (reject or waiting list) ends their enrolment for this
-- month (and any later month) so the place and budget are freed; what they already earned is kept. Moved to the
-- waiting list, earned rewards stay payable; rejected, they are no longer payable (reward_founding_blocks).
create or replace function public.reward_founding_decide(p_id bigint, p_action text, p_actor text,
                                                         p_note text default null)
returns public.reward_founding_applications
language plpgsql set search_path = public as $$
declare
  app      public.reward_founding_applications%rowtype;
  old_app  public.reward_founding_applications%rowtype;
  s        public.reward_program_settings%rowtype;
  v_new    text;
  v_note   text := nullif(btrim(coalesce(p_note, '')), '');
  taken    int;
  e        record;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  v_new := case p_action when 'approve' then 'approved' when 'reject' then 'rejected'
                         when 'waitlist' then 'waitlist' end;
  if v_new is null then raise exception 'invalid_action'; end if;
  perform pg_advisory_xact_lock(hashtext('founding'));                    -- approvals one at a time (place limit)
  select * into old_app from public.reward_founding_applications where id = p_id;
  if not found then raise exception 'unknown_application'; end if;
  perform pg_advisory_xact_lock(hashtext('founding:' || old_app.profile_id));
  select * into old_app from public.reward_founding_applications where id = p_id for update;
  if old_app.status = v_new then raise exception 'no_change'; end if;
  if v_note is not null and length(v_note) > 500 then raise exception 'note_too_long'; end if;
  if (v_new = 'rejected' or old_app.status = 'approved') and v_note is null then raise exception 'reason_required'; end if;
  if v_new = 'approved' and not old_app.test then
    select * into s from public.reward_program_settings where id = 1;
    select count(*) into taken from public.reward_founding_applications where status = 'approved' and not test;
    if taken >= s.max_places then raise exception 'places_full'; end if;
  end if;
  perform set_config('we.founding', 'on', true);
  update public.reward_founding_applications
     set status = v_new, decided_at = now(), decided_by = p_actor, decision_note = coalesce(v_note, decision_note),
         approved_at = case when v_new = 'approved' then now() else approved_at end,
         first_approved_at = case when v_new = 'approved' then coalesce(first_approved_at, now())
                                  else first_approved_at end,
         seen_at = coalesce(seen_at, now()), seen_by = coalesce(seen_by, p_actor), updated_at = now()
   where id = p_id
  returning * into app;
  perform set_config('we.founding', 'off', true);
  if old_app.status = 'approved' then
    for e in select month from public.reward_enrolments                  -- this month and later only: past
              where profile_id = app.profile_id and status <> 'withdrawn'    -- months' records stay untouched
                and month >= to_char(now() at time zone 'Africa/Lagos', 'YYYY-MM') order by month loop
      perform public.reward_withdraw(app.profile_id, e.month, p_actor);
    end loop;
  end if;
  insert into public.reward_audit_log (actor, action, target, old_value, new_value)
  values (p_actor, 'founding_' || v_new, app.profile_id,
          jsonb_build_object('status', old_app.status), jsonb_build_object('status', v_new, 'note', v_note,
                                                                           'test', app.test));
  return app;
end $$;

-- the Owner dashboard notification: mark one (p_id) or all new applications as seen
create or replace function public.reward_founding_mark_seen(p_actor text, p_id bigint default null)
returns int
language plpgsql set search_path = public as $$
declare
  n int;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  perform set_config('we.founding', 'on', true);
  update public.reward_founding_applications set seen_at = now(), seen_by = p_actor
   where seen_at is null and (p_id is null or id = p_id);
  get diagnostics n = row_count;
  perform set_config('we.founding', 'off', true);
  return n;
end $$;

-- ============================================================================ guards and enforcement

-- applications change only through the functions above (test rows may be deleted to clear owner testing)
create or replace function public.reward_founding_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.test then return old; end if;
    raise exception 'Founding 50 applications are kept for the audit trail and cannot be deleted';
  end if;
  if coalesce(current_setting('we.founding', true), '') <> 'on' then
    raise exception 'Founding 50 applications change only through the Founding 50 functions';
  end if;
  if tg_op = 'UPDATE' and (new.profile_id <> old.profile_id or new.test <> old.test or new.applied_at <> old.applied_at
                           or new.state <> old.state or new.note is distinct from old.note) then
    raise exception 'an application''s details cannot be changed';
  end if;
  return new;
end $$;

drop trigger if exists reward_founding_guard on public.reward_founding_applications;
create trigger reward_founding_guard before insert or update or delete on public.reward_founding_applications
  for each row execute function public.reward_founding_guard();

-- enrolment: real accounts need an approved application; record when a place was actually taken
create or replace function public.reward_enrolments_founding() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.status = 'enrolled' and (tg_op = 'INSERT' or old.status is distinct from 'enrolled') then
    new.enrolled_at := now();
  end if;
  if not new.test and new.status in ('enrolled','waitlist')
     and (tg_op = 'INSERT' or new.status is distinct from old.status) then
    perform pg_advisory_xact_lock(hashtext('founding:' || new.profile_id));
    if not public.reward_founding_approved(new.profile_id) then raise exception 'not_approved'; end if;
  end if;
  return new;
end $$;

drop trigger if exists reward_enrolments_founding on public.reward_enrolments;
create trigger reward_enrolments_founding before insert or update on public.reward_enrolments
  for each row execute function public.reward_enrolments_founding();

-- earning: runs after reward_events_cap (triggers fire in name order) — only approved participants earn money
create or replace function public.reward_events_founding() returns trigger
language plpgsql set search_path = public as $$
begin
  if not new.test and new.amount > 0 and not public.reward_founding_approved(new.profile_id) then
    new.amount := 0;
    new.reason := 'not_approved';
  end if;
  return new;
end $$;

drop trigger if exists reward_events_founding on public.reward_activity_events;
create trigger reward_events_founding before insert on public.reward_activity_events
  for each row execute function public.reward_events_founding();

-- money: no withdrawal approval/payment and no monthly payment approval/payment for people never approved or
-- rejected by the Owner (test records were never payable anyway)
create or replace function public.reward_cashout_founding() returns trigger
language plpgsql set search_path = public as $$
begin
  if not new.test and new.status in ('approved','paid') and new.status is distinct from old.status
     and public.reward_founding_blocks(new.profile_id) then
    raise exception 'founding_not_approved';
  end if;
  return new;
end $$;

drop trigger if exists reward_cashout_founding on public.reward_cashout_requests;
create trigger reward_cashout_founding before update on public.reward_cashout_requests
  for each row execute function public.reward_cashout_founding();

create or replace function public.reward_payments_founding() returns trigger
language plpgsql set search_path = public as $$
begin
  if not new.test and new.status in ('approved','paid')
     and (tg_op = 'INSERT' or new.status is distinct from old.status)
     and public.reward_founding_blocks(new.profile_id) then
    raise exception 'founding_not_approved';
  end if;
  return new;
end $$;

drop trigger if exists reward_payments_founding on public.reward_payments;
create trigger reward_payments_founding before insert or update on public.reward_payments
  for each row execute function public.reward_payments_founding();

-- ============================================================================ waiting list (extended)

-- Move people from the waiting list into free places (first come, first served). Returns how many moved.
-- The same as in rewards_schema.sql, plus: only people with an approved Founding 50 application are moved.
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
              and public.reward_founding_approved(e.profile_id)          -- Founding 50: approved people only
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

-- ============================================================================ withdrawal eligibility (extended)

-- the same as in withdrawals_migration.sql, plus: real accounts need a Founding 50 approval ('not_approved'),
-- and the 30-day wait counts from the first official enrolment after the first approval (reward_founding_joined)
create or replace function public.reward_cashout_status(p_profile text, p_as_of date default null)
returns jsonb
language plpgsql stable set search_path = public as $$
declare
  acc          public.reward_accounts%rowtype;
  cs           public.reward_cashout_settings%rowtype;
  today        date;
  cur_month    text;
  joined       timestamptz;
  joined_on    date;
  eligible_on  date;
  reasons      text[] := '{}';
  v_months     jsonb := '[]'::jsonb;
  v_amount     int := 0;
  v_waiting    jsonb := '[]'::jsonb;
  open_req     jsonb;
  earned_all   int;
  earned_now   int;
  pending      int;
  approved     int;
  paid         int;
  refused      int;
begin
  select * into cs from public.reward_cashout_settings where id = 1;
  select * into acc from public.reward_accounts where profile_id = p_profile;
  if not found then
    return jsonb_build_object('eligible', false, 'reasons', jsonb_build_array('not_joined'), 'amount', 0,
                              'months', '[]'::jsonb, 'live', cs.live_requests, 'test', false, 'min_days', cs.min_days);
  end if;
  if p_as_of is not null and not acc.test then
    raise exception 'simulation_for_test_accounts_only';
  end if;
  today := public.reward_cashout_today(p_as_of);
  cur_month := to_char(today, 'YYYY-MM');

  -- Founding 50: the 30-day wait starts at the participant's first official enrolment AFTER the owner first
  -- approved their application (never at applying, creating the account or the latest login)
  joined := public.reward_founding_joined(p_profile, acc.test);
  joined_on := (joined at time zone 'Africa/Lagos')::date;
  eligible_on := joined_on + cs.min_days;

  if acc.membership = 'none' or acc.terms_version is null then reasons := reasons || 'not_joined'::text; end if;
  if not acc.test and public.reward_founding_blocks(p_profile) then reasons := reasons || 'not_approved'::text; end if;
  if acc.membership = 'suspended' then reasons := reasons || 'suspended'::text; end if;
  if not acc.test and not (acc.age_confirmed and acc.residence_confirmed) then
    reasons := reasons || 'declarations'::text;
  end if;
  if acc.review = 'hold' then reasons := reasons || 'account_on_hold'::text; end if;
  if joined is null then
    reasons := reasons || 'not_enrolled'::text;
  elsif today < eligible_on then
    reasons := reasons || 'waiting_period'::text;
  end if;

  -- available: NET VERIFIED earnings (see reward_cashout_month_earnings) from completed months that no request
  -- holds and no monthly review approved, paid, held or refused; the current, incomplete month is never included,
  -- months with a referral reward still awaiting the owner's review wait, and a month is never below zero
  select coalesce(jsonb_agg(jsonb_build_object('month', m.month, 'amount', m.net) order by m.month)
                    filter (where m.awaiting = 0 and m.net > 0), '[]'::jsonb),
         coalesce(sum(m.net) filter (where m.awaiting = 0 and m.net > 0), 0)::int,
         coalesce(jsonb_agg(m.month order by m.month) filter (where m.awaiting > 0), '[]'::jsonb)
    into v_months, v_amount, v_waiting
    from public.reward_cashout_month_earnings(p_profile, acc.test) m
   where m.month < cur_month
     and not exists (select 1 from public.reward_cashout_months r
                      where r.profile_id = p_profile and r.month = m.month and r.status <> 'released')
     and not exists (select 1 from public.reward_payments p
                      where p.profile_id = p_profile and p.month = m.month
                        and p.status in ('approved','paid','on_hold','rejected'));
  if v_amount <= 0 then reasons := reasons || 'no_earnings'::text; end if;

  select to_jsonb(r) - 'legal_name' - 'declarations' - 'bank_fingerprint' - 'flags' into open_req
    from public.reward_cashout_requests r
   where r.profile_id = p_profile and r.status in ('pending_review','under_review','approved','on_hold')
   limit 1;
  if open_req is not null then reasons := reasons || 'open_request'::text; end if;
  if not acc.test and not cs.live_requests then reasons := reasons || 'not_live'::text; end if;

  select coalesce(sum(amount) filter (where amount > 0), 0)::int,
         coalesce(sum(amount) filter (where amount > 0 and month >= cur_month), 0)::int
    into earned_all, earned_now
    from public.reward_activity_events where profile_id = p_profile and test = acc.test;
  select coalesce(sum(amount) filter (where status in ('pending_review','under_review','on_hold')), 0)::int,
         coalesce(sum(amount) filter (where status = 'approved'), 0)::int
    into pending, approved
    from public.reward_cashout_requests where profile_id = p_profile and test = acc.test;
  select coalesce((select sum(amount) from public.reward_cashout_payments
                    where profile_id = p_profile and test = acc.test), 0)::int
       + coalesce((select sum(p.paid_amount) from public.reward_payments p
                    where p.profile_id = p_profile and p.test = acc.test and p.status = 'paid'
                      -- a month settled by a withdrawal is already counted in reward_cashout_payments; recognised by
                      -- its paid reservation (never by the reference text, which the existing rules let you edit)
                      and not public.reward_cashout_settled(p.profile_id, p.month)), 0)::int
    into paid;
  -- refused per month, one figure each: a month refused in a monthly review or disqualified with a withdrawal
  -- counts in full; a month settled by a monthly review for less than was earned counts the difference; otherwise
  -- the rewards of rejected referrals
  select coalesce(sum(case
           when rv.status = 'rejected' and not rv.settled then me.gross
           when rv.status in ('approved','paid') and not rv.settled then greatest(me.gross - rv.approved_amount, 0)
           when exists (select 1 from public.reward_cashout_months d
                         where d.profile_id = p_profile and d.month = me.month and d.status = 'disqualified') then me.gross
           else me.refused end), 0)::int
    into refused
    from public.reward_cashout_month_earnings(p_profile, acc.test) me
    left join lateral (select p.status, p.approved_amount,
                              public.reward_cashout_settled(p.profile_id, p.month) as settled
                         from public.reward_payments p
                        where p.profile_id = p_profile and p.month = me.month) rv on true;

  return jsonb_build_object(
    'eligible', cardinality(reasons) = 0, 'reasons', to_jsonb(reasons), 'today', today, 'month', cur_month,
    'joined_on', joined_on, 'eligible_on', eligible_on,
    'days_left', case when eligible_on is null then null else greatest(eligible_on - today, 0) end,
    'months', v_months, 'amount', v_amount, 'waiting_months', v_waiting, 'open_request', open_req, 'live', cs.live_requests, 'test', acc.test,
    'min_days', cs.min_days,
    'totals', jsonb_build_object('earned', earned_all, 'current_month', earned_now, 'available', v_amount,
                                 'pending', pending, 'approved', approved, 'paid', paid, 'refused', refused,
                                 'unpaid', greatest(earned_all - paid - refused, 0)));
end $$;

-- ============================================================================ access (server only)

alter table public.reward_founding_applications enable row level security;
revoke all on public.reward_founding_applications from public, anon, authenticated;
grant select, insert, update, delete on public.reward_founding_applications to service_role;   -- guarded by triggers

revoke execute on function public.reward_founding_approved(text)                             from public, anon, authenticated;
revoke execute on function public.reward_founding_blocks(text)                               from public, anon, authenticated;
revoke execute on function public.reward_founding_joined(text, boolean)                      from public, anon, authenticated;
revoke execute on function public.reward_founding_states()                                   from public, anon, authenticated;
revoke execute on function public.reward_founding_apply(text, text, text, boolean, boolean, boolean, text)
  from public, anon, authenticated;
revoke execute on function public.reward_founding_decide(bigint, text, text, text)           from public, anon, authenticated;
revoke execute on function public.reward_founding_mark_seen(text, bigint)                    from public, anon, authenticated;
revoke execute on function public.reward_cashout_status(text, date)                          from public, anon, authenticated;
grant  execute on function public.reward_founding_approved(text)                             to service_role;
grant  execute on function public.reward_founding_blocks(text)                               to service_role;
grant  execute on function public.reward_founding_joined(text, boolean)                      to service_role;
grant  execute on function public.reward_founding_states()                                   to service_role;
grant  execute on function public.reward_founding_apply(text, text, text, boolean, boolean, boolean, text) to service_role;
grant  execute on function public.reward_founding_decide(bigint, text, text, text)           to service_role;
grant  execute on function public.reward_founding_mark_seen(text, bigint)                    to service_role;
grant  execute on function public.reward_cashout_status(text, date)                          to service_role;
