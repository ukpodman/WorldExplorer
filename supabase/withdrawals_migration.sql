-- World Explorer V21 — Manual cash withdrawal requests — additive database migration
--
-- Run AFTER supabase/rewards_schema.sql, in Supabase → SQL Editor (see WITHDRAWALS_SETUP.md). It only ADDS new
-- objects whose names start with reward_cashout_ / reward_owner_notifications, plus one extra safety trigger on
-- reward_payments. Existing tables, rows and functions are not changed. Safe to run again.
--
-- What it does
--   * A player with verified (server-recorded) earnings from COMPLETED calendar months can request the whole
--     available balance, after the waiting period (30 calendar days from their first enrolment, Nigeria time).
--   * The request reserves those earning months, so the same earnings can never be requested or paid twice
--     (unique index), and notifies the owner (reward_owner_notifications).
--   * The owner reviews, approves, holds or rejects. Approving NEVER moves money. After the owner has transferred
--     the money from their own bank, "Mark as paid" writes ONE ledger row (reward_cashout_payments) for exactly the
--     approved amount. A rejected request releases its months for a future request unless the owner records an
--     auditable disqualification.
--   * Real (non-test) requests are refused until the owner deliberately switches on live_requests below (and the
--     app's own [rewards] withdrawals_active secret). Real approvals and payments are refused until real_payouts is
--     switched on (and the app's [rewards] payouts_active). Test accounts can simulate everything; their rows are
--     marked test = true and are never real liabilities.
--   * Balances use NET VERIFIED earnings per completed month: rewards of referrals the owner rejected are deducted,
--     a month with a referral reward still awaiting review waits, and nothing is ever negative. The amounts are
--     checked again when the owner approves and when a payment is recorded.
--   * Withdrawal approval never changes the player's general eligibility verification (reward_accounts); its own
--     checks are stored on the request. Real requests need the account to be verified already in Participants,
--     because the existing payment rules require it.
--   * One record of what was paid per earning month: when a real request is marked as paid, each covered month is
--     also settled in the EXISTING reward_payments table (status paid, reference = the WD- reference), so the
--     existing Payments tab and budget figures include it. reward_cashout_payments keeps the bank transfer itself
--     (one transfer can cover several months). Such a month is recognised by its paid reservation, never by the
--     reference text, and its reference is protected (remarks can still be added).
--
-- Security model (same as the rewards tables): Row Level Security on, no access at all for the browser roles
-- (anon, authenticated); only the server key (service_role) used by the app on the server. The app reads and
-- writes only the signed-in player's own rows; owner actions are checked by the app AND here (owner_emails).
-- Bank account numbers are never stored: only a keyed fingerprint computed by the app (HMAC-SHA256).
--
-- Money is whole naira. Days and months follow Nigeria time (Africa/Lagos, UTC+1).

do $$
begin
  if to_regclass('public.reward_accounts') is null then
    raise exception 'Run supabase/rewards_schema.sql first (the rewards tables are missing).';
  end if;
end $$;

-- ============================================================================ tables

create table if not exists public.reward_cashout_settings (
  id             int primary key default 1 check (id = 1),         -- exactly one row
  live_requests  boolean not null default false,                   -- real requests allowed (keep OFF until cleared)
  real_payouts   boolean not null default false,                   -- real approvals and payments allowed (keep OFF)
  min_days       int not null default 30 check (min_days between 1 and 365),
  owner_emails   text[] not null default '{}',                     -- who may review, approve and record payments
  updated_at     timestamptz not null default now(),
  updated_by     text
);
insert into public.reward_cashout_settings (id) values (1) on conflict (id) do nothing;
alter table public.reward_cashout_settings add column if not exists real_payouts boolean not null default false;

create table if not exists public.reward_cashout_requests (
  id                    bigint generated always as identity primary key,
  reference             text not null unique check (reference ~ '^WD-[0-9]{6}-[2-9A-HJ-NP-Z]{4}$'),
  profile_id            text not null references public.reward_accounts (profile_id),
  amount                int not null check (amount > 0),
  months                text[] not null check (cardinality(months) > 0),
  legal_name            text not null check (length(btrim(legal_name)) between 2 and 120),
  declarations          jsonb not null,
  status                text not null default 'pending_review'
                          check (status in ('pending_review','under_review','approved','on_hold','rejected','paid')),
  request_month         text not null check (request_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  requested_at          timestamptz not null default now(),
  simulated_as_of       date,                                       -- test simulations only
  flags                 jsonb not null default '[]'::jsonb,         -- review prompts captured at request time
  beneficiary_verified  boolean not null default false,             -- set by the owner on approval
  eligibility_confirmed boolean not null default false,             -- set by the owner on approval
  bank_fingerprint      text check (bank_fingerprint is null or bank_fingerprint ~ '^[0-9a-f]{64}$'),
  decision_note         text check (decision_note is null or length(decision_note) <= 1000),
  approved_by           text,
  approved_at           timestamptz,
  decided_by            text,
  decided_at            timestamptz,
  paid_at               timestamptz,
  test                  boolean not null default false,
  updated_at            timestamptz not null default now(),
  updated_by            text,
  constraint reward_cashout_simulation_is_test check (simulated_as_of is null or test),
  constraint reward_cashout_approval_checked check (
    status not in ('approved','paid') or (beneficiary_verified and eligibility_confirmed and approved_by is not null)),
  constraint reward_cashout_paid_has_time check (status <> 'paid' or paid_at is not null)
);
-- one open request per person (a request always covers the whole available balance)
create unique index if not exists reward_cashout_one_open on public.reward_cashout_requests (profile_id)
  where status in ('pending_review','under_review','approved','on_hold');
create index if not exists reward_cashout_requests_status on public.reward_cashout_requests (status, requested_at);
create index if not exists reward_cashout_requests_profile on public.reward_cashout_requests (profile_id);

-- which earning months a request covers; a month can be held by at most one request that is not released
create table if not exists public.reward_cashout_months (
  request_id  bigint not null references public.reward_cashout_requests (id),
  profile_id  text not null references public.reward_accounts (profile_id),
  month       text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  amount      int not null check (amount > 0),
  status      text not null default 'reserved' check (status in ('reserved','paid','released','disqualified')),
  test        boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (request_id, month)
);
create unique index if not exists reward_cashout_month_once on public.reward_cashout_months (profile_id, month)
  where status <> 'released';

-- the payment ledger: one row per paid request, never changed afterwards
create table if not exists public.reward_cashout_payments (
  id             bigint generated always as identity primary key,
  request_id     bigint not null unique references public.reward_cashout_requests (id),
  profile_id     text not null references public.reward_accounts (profile_id),
  amount         int not null check (amount > 0),
  payment_date   date not null,
  payment_month  text not null check (payment_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  bank_reference text check (bank_reference is null or length(bank_reference) between 1 and 120),
  recorded_by    text not null,
  recorded_at    timestamptz not null default now(),
  test           boolean not null default false,
  constraint reward_cashout_payment_month check (payment_month = to_char(payment_date, 'YYYY-MM'))
);
create unique index if not exists reward_cashout_bank_reference on public.reward_cashout_payments (lower(bank_reference))
  where bank_reference is not null and not test;

create table if not exists public.reward_owner_notifications (
  id           bigint generated always as identity primary key,
  kind         text not null check (kind in ('cashout_request')),
  request_id   bigint references public.reward_cashout_requests (id),
  title        text not null,
  details      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  read_at      timestamptz,
  read_by      text,
  email_status text not null default 'pending' check (email_status in ('pending','not_configured','sent','failed')),
  test         boolean not null default false
);
create index if not exists reward_owner_notifications_unread on public.reward_owner_notifications (read_at, created_at);

-- ============================================================================ helpers

create or replace function public.reward_cashout_today(p_as_of date default null) returns date
language sql stable as $$
  select coalesce(p_as_of, (now() at time zone 'Africa/Lagos')::date)
$$;

create or replace function public.reward_cashout_is_owner(p_actor text) returns boolean
language sql stable set search_path = public as $$
  select coalesce((select lower(btrim(p_actor)) = any (select lower(btrim(x)) from unnest(s.owner_emails) x)
                     from public.reward_cashout_settings s where s.id = 1), false)
$$;

-- ============================================================================ eligibility and balance

-- Net verified earnings per month for one person. Earned rewards are never negative or edited (rewards_schema.sql);
-- the existing reduction is a REJECTED referral, whose reward stays recorded but is not payable. So per month:
--   gross    = all rewards earned
--   refused  = rewards of referrals the owner rejected (the negative adjustment)
--   net      = gross - refused, never below zero
--   awaiting = referral rewards whose referral the owner has not approved or rejected yet; a month with any of
--              these is not verified yet and cannot be requested until the owner decides
create or replace function public.reward_cashout_month_earnings(p_profile text, p_test boolean)
returns table (month text, gross int, refused int, net int, awaiting int)
language sql stable set search_path = public as $$
  select e.month,
         sum(e.amount)::int,
         coalesce(sum(e.amount) filter (where e.kind = 'referral' and r.status = 'rejected'), 0)::int,
         greatest(coalesce(sum(e.amount) filter (where not (e.kind = 'referral' and coalesce(r.status, '') = 'rejected')),
                           0), 0)::int,
         coalesce(sum(e.amount) filter (where e.kind = 'referral' and coalesce(r.status, 'pending') in ('pending','qualified')),
                  0)::int
    from public.reward_activity_events e
    left join public.user_referrals r on e.kind = 'referral' and r.referred_id = e.subject
   where e.profile_id = p_profile and e.test = p_test and e.amount > 0
   group by e.month
$$;

-- True when this person's month was settled by a paid withdrawal. Decided by the withdrawal's own reservation
-- (reward_cashout_months, changed only by the withdrawal functions; a paid reservation can never be reopened),
-- not by the payment reference, so later edits to reward_payments can never cause a month to be counted twice.
create or replace function public.reward_cashout_settled(p_profile text, p_month text) returns boolean
language sql stable set search_path = public as $$
  select exists (select 1 from public.reward_cashout_months m
                  where m.profile_id = p_profile and m.month = p_month and m.status = 'paid')
$$;

-- Everything the app shows on the player's withdrawal card, computed here so the database is the authority.
-- p_as_of (a simulated Nigeria date) is accepted for test accounts only.
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

  -- original enrolment: the first month this person actually took part in (never the latest login)
  select min(created_at) into joined from public.reward_enrolments
   where profile_id = p_profile and test = acc.test
     and (status = 'enrolled' or (status = 'withdrawn' and reserved_amount > 0));
  joined_on := (joined at time zone 'Africa/Lagos')::date;
  eligible_on := joined_on + cs.min_days;

  if acc.membership = 'none' or acc.terms_version is null then reasons := reasons || 'not_joined'::text; end if;
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

-- ============================================================================ player request

-- Submit a request for the whole available balance. p_expected_amount is the amount the player saw: if anything
-- changed meanwhile the request is refused ('amount_changed') so the player always confirms the real figure.
create or replace function public.reward_cashout_request(p_profile text, p_legal_name text, p_declarations jsonb,
                                                         p_expected_amount int, p_as_of date default null,
                                                         p_flags jsonb default '[]'::jsonb)
returns public.reward_cashout_requests
language plpgsql set search_path = public as $$
declare
  st     jsonb;
  acc    public.reward_accounts%rowtype;
  req    public.reward_cashout_requests%rowtype;
  today  date;
  ref    text;
  alpha  constant text := '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
begin
  perform pg_advisory_xact_lock(hashtext('cashout:' || p_profile));      -- one decision per person at a time
  st := public.reward_cashout_status(p_profile, p_as_of);
  if not coalesce((st ->> 'eligible')::boolean, false) then
    raise exception 'not_eligible: %', coalesce(st -> 'reasons' ->> 0, 'unknown');
  end if;
  if p_expected_amount is distinct from (st ->> 'amount')::int then raise exception 'amount_changed'; end if;
  if length(btrim(coalesce(p_legal_name, ''))) not between 2 and 120 then raise exception 'legal_name_required'; end if;
  if not (coalesce((p_declarations ->> 'legal_name')::boolean, false)
          and coalesce((p_declarations ->> 'own_account')::boolean, false)
          and coalesce((p_declarations ->> 'name_match')::boolean, false)
          and coalesce((p_declarations ->> 'false_information')::boolean, false)) then
    raise exception 'declarations_required';
  end if;
  select * into acc from public.reward_accounts where profile_id = p_profile;
  today := public.reward_cashout_today(p_as_of);
  for attempt in 1 .. 50 loop
    ref := 'WD-' || to_char(today, 'YYYYMM') || '-';
    for i in 1 .. 4 loop
      ref := ref || substr(alpha, 1 + floor(random() * length(alpha))::int, 1);
    end loop;
    exit when not exists (select 1 from public.reward_cashout_requests where reference = ref);
  end loop;

  perform set_config('we.cashout', 'on', true);
  insert into public.reward_cashout_requests (reference, profile_id, amount, months, legal_name, declarations,
                                              request_month, simulated_as_of, flags, test, updated_by)
  values (ref, p_profile, (st ->> 'amount')::int,
          array(select x ->> 'month' from jsonb_array_elements(st -> 'months') x order by 1),
          btrim(p_legal_name), p_declarations || jsonb_build_object('declared_at', now()),
          to_char(today, 'YYYY-MM'), p_as_of, coalesce(p_flags, '[]'::jsonb), acc.test, p_profile)
  returning * into req;
  insert into public.reward_cashout_months (request_id, profile_id, month, amount, test)
  select req.id, p_profile, x ->> 'month', (x ->> 'amount')::int, acc.test
    from jsonb_array_elements(st -> 'months') x;
  insert into public.reward_owner_notifications (kind, request_id, title, details, test)
  values ('cashout_request', req.id, 'New withdrawal request',
          jsonb_build_object('reference', req.reference, 'player', coalesce(acc.display_name, acc.email, left(p_profile, 10)),
                             'amount', req.amount, 'requested_at', req.requested_at, 'months', to_jsonb(req.months)),
          acc.test);
  perform set_config('we.cashout', 'off', true);
  return req;
end $$;

-- ============================================================================ owner decisions

-- True when a reserved month's net verified earnings no longer equal the reserved amount (for example the owner
-- rejected a referral after the request) or a referral reward in it is awaiting review again. Such a request must
-- be rejected and requested again, so nothing that is no longer payable is ever approved or paid.
create or replace function public.reward_cashout_earnings_changed(p_id bigint) returns boolean
language sql stable set search_path = public as $$
  select exists (
    select 1
      from public.reward_cashout_months rm
      join public.reward_cashout_requests rq on rq.id = rm.request_id
      left join public.reward_cashout_month_earnings(rq.profile_id, rq.test) me on me.month = rm.month
     where rm.request_id = p_id and rm.status = 'reserved'
       and (me.month is null or me.net <> rm.amount or me.awaiting > 0))
$$;

-- p_action: 'review' (Under review) | 'approve' | 'hold' | 'reject'. Approving never moves money; it needs the
-- owner's confirmation of eligibility and of the bank beneficiary name. Hold and reject need a reason.
-- p_disqualify (reject only): the covered earnings stay blocked (an auditable disqualification) instead of being
-- released for a future request.
create or replace function public.reward_cashout_decide(p_id bigint, p_action text, p_actor text,
                                                        p_note text default null,
                                                        p_beneficiary_verified boolean default false,
                                                        p_eligibility_confirmed boolean default false,
                                                        p_disqualify boolean default false)
returns public.reward_cashout_requests
language plpgsql set search_path = public as $$
declare
  req        public.reward_cashout_requests%rowtype;
  new_status text;
  reserved   int;
  note       text := nullif(btrim(coalesce(p_note, '')), '');
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  select * into req from public.reward_cashout_requests where id = p_id;
  if not found then raise exception 'unknown_request'; end if;
  perform pg_advisory_xact_lock(hashtext('cashout:' || req.profile_id));
  select * into req from public.reward_cashout_requests where id = p_id for update;
  if req.status in ('paid','rejected') then raise exception 'request_closed'; end if;
  new_status := case p_action when 'review' then 'under_review' when 'approve' then 'approved'
                              when 'hold' then 'on_hold' when 'reject' then 'rejected' end;
  if new_status is null then raise exception 'unknown_action'; end if;
  if new_status = req.status then raise exception 'invalid_transition'; end if;
  if new_status = 'under_review' and req.status not in ('pending_review','on_hold') then
    raise exception 'invalid_transition';
  end if;
  if new_status in ('on_hold','rejected') and (note is null or length(note) < 3) then
    raise exception 'reason_required';
  end if;
  if new_status = 'approved' then
    if not req.test and not coalesce((select real_payouts from public.reward_cashout_settings where id = 1), false) then
      raise exception 'payouts_disabled';
    end if;
    if not (coalesce(p_beneficiary_verified, false) and coalesce(p_eligibility_confirmed, false)) then
      raise exception 'verification_required';
    end if;
    select coalesce(sum(amount), 0) into reserved from public.reward_cashout_months
     where request_id = p_id and status = 'reserved';
    if reserved <> req.amount then raise exception 'reservation_mismatch'; end if;
    -- withdrawal checks are recorded on the request only; the player's general eligibility verification is NOT
    -- changed here. The existing payment rules need it, so a real request needs it to be verified already.
    if not req.test and coalesce((select verification from public.reward_accounts
                                   where profile_id = req.profile_id), '') <> 'verified' then
      raise exception 'account_not_verified';
    end if;
    if public.reward_cashout_earnings_changed(p_id) then raise exception 'earnings_changed'; end if;
  end if;

  perform set_config('we.cashout', 'on', true);
  update public.reward_cashout_requests
     set status = new_status,
         decision_note = coalesce(note, decision_note),
         beneficiary_verified = case when new_status = 'approved' then true else beneficiary_verified end,
         eligibility_confirmed = case when new_status = 'approved' then true else eligibility_confirmed end,
         approved_by = case when new_status = 'approved' then p_actor else approved_by end,
         approved_at = case when new_status = 'approved' then now() else approved_at end,
         decided_by = p_actor, decided_at = now(), updated_by = p_actor
   where id = p_id
  returning * into req;
  if new_status = 'rejected' then
    update public.reward_cashout_months
       set status = case when coalesce(p_disqualify, false) then 'disqualified' else 'released' end
     where request_id = p_id and status = 'reserved';
  end if;
  update public.reward_owner_notifications set read_at = coalesce(read_at, now()), read_by = coalesce(read_by, p_actor)
   where request_id = p_id;
  perform set_config('we.cashout', 'off', true);
  return req;
end $$;

-- Record a payment AFTER the owner has transferred the money outside World Explorer. The amount must equal the
-- approved amount; a request is paid at most once; a bank reference can be used only once.
create or replace function public.reward_cashout_pay(p_id bigint, p_amount int, p_payment_date date,
                                                     p_reference text, p_actor text)
returns public.reward_cashout_payments
language plpgsql set search_path = public as $$
declare
  req   public.reward_cashout_requests%rowtype;
  pay   public.reward_cashout_payments%rowtype;
  m     record;
  today date := (now() at time zone 'Africa/Lagos')::date;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  select * into req from public.reward_cashout_requests where id = p_id;
  if not found then raise exception 'unknown_request'; end if;
  perform pg_advisory_xact_lock(hashtext('cashout:' || req.profile_id));
  select * into req from public.reward_cashout_requests where id = p_id for update;
  if req.status = 'paid' or exists (select 1 from public.reward_cashout_payments where request_id = p_id) then
    raise exception 'already_paid';
  end if;
  if req.status <> 'approved' then raise exception 'not_approved'; end if;
  if not req.test and not coalesce((select real_payouts from public.reward_cashout_settings where id = 1), false) then
    raise exception 'payouts_disabled';
  end if;
  if p_amount is distinct from req.amount then raise exception 'amount_mismatch'; end if;
  if not req.test and coalesce((select verification from public.reward_accounts
                                 where profile_id = req.profile_id), '') <> 'verified' then
    raise exception 'account_not_verified';
  end if;
  if public.reward_cashout_earnings_changed(p_id) then raise exception 'earnings_changed'; end if;
  if p_payment_date is null then raise exception 'payment_date_required'; end if;
  if not req.test and p_payment_date > today then raise exception 'payment_date_in_future'; end if;
  if not req.test and p_payment_date < (req.approved_at at time zone 'Africa/Lagos')::date then
    raise exception 'payment_before_approval';
  end if;

  perform set_config('we.cashout', 'on', true);
  begin
    insert into public.reward_cashout_payments (request_id, profile_id, amount, payment_date, payment_month,
                                                bank_reference, recorded_by, test)
    values (p_id, req.profile_id, req.amount, p_payment_date, to_char(p_payment_date, 'YYYY-MM'),
            nullif(btrim(coalesce(p_reference, '')), ''), p_actor, req.test)
    returning * into pay;
  exception when unique_violation then
    raise exception 'duplicate_reference';
  end;
  update public.reward_cashout_requests
     set status = 'paid', paid_at = now(), decided_by = p_actor, decided_at = now(), updated_by = p_actor
   where id = p_id;
  update public.reward_cashout_months set status = 'paid' where request_id = p_id and status = 'reserved';
  if not req.test then
    -- settle each covered month in the existing reward_payments table (its own rules run as usual: approved first,
    -- then paid, never more than was earned, paid rows frozen)
    for m in select month, amount from public.reward_cashout_months where request_id = p_id order by month loop
      insert into public.reward_payments (profile_id, month, test, updated_by)
      values (req.profile_id, m.month, false, p_actor) on conflict (profile_id, month) do nothing;
      update public.reward_payments
         set status = 'approved', approved_amount = m.amount, updated_by = p_actor,
             remarks = coalesce(remarks || ' · ', '') || 'Paid through withdrawal request ' || req.reference
       where profile_id = req.profile_id and month = m.month;
      update public.reward_payments
         set status = 'paid', paid_amount = m.amount, payment_date = p_payment_date, reference = req.reference,
             updated_by = p_actor
       where profile_id = req.profile_id and month = m.month;
    end loop;
  end if;
  perform set_config('we.cashout', 'off', true);
  return pay;
end $$;

-- Store the keyed fingerprint of the bank account the owner checked (never the number itself). Returns how many
-- OTHER people's requests carry the same fingerprint (a prompt for a manual look, never an automatic block).
create or replace function public.reward_cashout_set_fingerprint(p_id bigint, p_fingerprint text, p_actor text)
returns int
language plpgsql set search_path = public as $$
declare
  req     public.reward_cashout_requests%rowtype;
  matches int;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$' then raise exception 'invalid_fingerprint'; end if;
  select * into req from public.reward_cashout_requests where id = p_id for update;
  if not found then raise exception 'unknown_request'; end if;
  if req.status in ('paid','rejected') then raise exception 'request_closed'; end if;
  perform set_config('we.cashout', 'on', true);
  update public.reward_cashout_requests set bank_fingerprint = p_fingerprint, updated_by = p_actor where id = p_id;
  perform set_config('we.cashout', 'off', true);
  select count(distinct profile_id) into matches from public.reward_cashout_requests
   where bank_fingerprint = p_fingerprint and profile_id <> req.profile_id and test = req.test;
  return matches;
end $$;

-- ============================================================================ guards (no changes outside the functions)

create or replace function public.reward_cashout_requests_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.test then return old; end if;
    raise exception 'withdrawal records are kept for the audit trail and cannot be deleted';
  end if;
  if coalesce(current_setting('we.cashout', true), '') <> 'on' then
    raise exception 'withdrawal requests change only through the withdrawal functions';
  end if;
  if tg_op = 'UPDATE' then
    if new.reference <> old.reference or new.profile_id <> old.profile_id or new.amount <> old.amount
       or new.months <> old.months or new.legal_name <> old.legal_name or new.test <> old.test
       or new.requested_at <> old.requested_at or new.declarations <> old.declarations then
      raise exception 'the requested amount, months and declarations cannot be changed';
    end if;
    new.updated_at := now();
  end if;
  return new;
end $$;

drop trigger if exists reward_cashout_requests_guard on public.reward_cashout_requests;
create trigger reward_cashout_requests_guard before insert or update or delete on public.reward_cashout_requests
  for each row execute function public.reward_cashout_requests_guard();

create or replace function public.reward_cashout_months_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.test then return old; end if;
    raise exception 'withdrawal records are kept for the audit trail and cannot be deleted';
  end if;
  if coalesce(current_setting('we.cashout', true), '') <> 'on' then
    raise exception 'withdrawal reservations change only through the withdrawal functions';
  end if;
  if tg_op = 'UPDATE' then
    if new.request_id <> old.request_id or new.profile_id <> old.profile_id or new.month <> old.month
       or new.amount <> old.amount or new.test <> old.test then
      raise exception 'a reservation cannot be moved or resized';
    end if;
    if old.status in ('paid','disqualified','released') and new.status <> old.status then
      raise exception 'a settled reservation cannot be reopened';
    end if;
    new.updated_at := now();
  end if;
  return new;
end $$;

drop trigger if exists reward_cashout_months_guard on public.reward_cashout_months;
create trigger reward_cashout_months_guard before insert or update or delete on public.reward_cashout_months
  for each row execute function public.reward_cashout_months_guard();

create or replace function public.reward_cashout_payments_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.test then return old; end if;
    raise exception 'payment records are kept for the audit trail and cannot be deleted';
  end if;
  if tg_op = 'UPDATE' then raise exception 'a recorded payment cannot be changed'; end if;
  if coalesce(current_setting('we.cashout', true), '') <> 'on' then
    raise exception 'payments are recorded only with Mark as paid';
  end if;
  return new;
end $$;

drop trigger if exists reward_cashout_payments_guard on public.reward_cashout_payments;
create trigger reward_cashout_payments_guard before insert or update or delete on public.reward_cashout_payments
  for each row execute function public.reward_cashout_payments_guard();

create or replace function public.reward_owner_notifications_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.test then return old; end if;
    raise exception 'notifications are kept for the audit trail and cannot be deleted';
  end if;
  if tg_op = 'INSERT' and coalesce(current_setting('we.cashout', true), '') <> 'on' then
    raise exception 'notifications are created by the withdrawal functions';
  end if;
  if tg_op = 'UPDATE' and (new.kind <> old.kind or new.request_id is distinct from old.request_id
                           or new.title <> old.title or new.details <> old.details or new.test <> old.test
                           or new.created_at <> old.created_at) then
    raise exception 'only the read and email status of a notification can change';
  end if;
  return new;
end $$;

drop trigger if exists reward_owner_notifications_guard on public.reward_owner_notifications;
create trigger reward_owner_notifications_guard before insert or update or delete on public.reward_owner_notifications
  for each row execute function public.reward_owner_notifications_guard();

-- The existing monthly payment review must never approve or pay a month that a withdrawal request holds
-- (the withdrawal's own settlement inside reward_cashout_pay is the only exception).
create or replace function public.reward_payments_cashout_guard() returns trigger
language plpgsql set search_path = public as $$
begin
  -- only a change INTO approved or paid is checked: remarks and reasons on a month already settled stay editable
  -- (its amounts, date and status are frozen by reward_payments_guard, its reference by the settlement guard below)
  if new.status in ('approved','paid') and coalesce(current_setting('we.cashout', true), '') <> 'on'
     and (tg_op = 'INSERT' or old.status not in ('approved','paid')) then
    perform pg_advisory_xact_lock(hashtext('cashout:' || new.profile_id));
    if exists (select 1 from public.reward_cashout_months m
                where m.profile_id = new.profile_id and m.month = new.month and m.status <> 'released') then
      raise exception 'month % of this participant is covered by a withdrawal request; manage it under Withdrawals',
        new.month;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists reward_payments_cashout_guard on public.reward_payments;
create trigger reward_payments_cashout_guard before insert or update on public.reward_payments
  for each row execute function public.reward_payments_cashout_guard();

-- The existing rules let a paid record's reference and remarks change. For a month settled by a withdrawal the
-- reference is the WD- reference that links it to the withdrawal, so it is kept; remarks and reasons can still be
-- added. Other payments cannot take a WD- reference, so no record can pretend to be a withdrawal settlement.
create or replace function public.reward_payments_settlement_guard() returns trigger
language plpgsql set search_path = public as $$
declare
  settled boolean;
begin
  if coalesce(current_setting('we.cashout', true), '') = 'on' then return new; end if;   -- the settlement itself
  settled := public.reward_cashout_settled(new.profile_id, new.month);
  if settled and tg_op = 'UPDATE' and new.reference is distinct from old.reference then
    raise exception 'the reference of a payment settled by withdrawal request % cannot be changed; add a remark instead',
      old.reference;
  end if;
  if not settled and coalesce(new.reference, '') ~* '^WD-[0-9]{6}-[2-9A-HJ-NP-Z]{4}$'
     and (tg_op = 'INSERT' or new.reference is distinct from old.reference) then
    raise exception 'references in the form WD-YYYYMM-XXXX are reserved for payments settled by a withdrawal request';
  end if;
  return new;
end $$;

drop trigger if exists reward_payments_settlement_guard on public.reward_payments;
create trigger reward_payments_settlement_guard before insert or update on public.reward_payments
  for each row execute function public.reward_payments_settlement_guard();

-- ============================================================================ audit trail

create or replace function public.reward_cashout_audit() returns trigger
language plpgsql set search_path = public as $$
declare
  n jsonb := to_jsonb(new);
begin
  insert into public.reward_audit_log (actor, action, target, old_value, new_value)
  values (coalesce(n ->> 'updated_by', n ->> 'recorded_by'), tg_table_name || '_' || lower(tg_op),
          coalesce(n ->> 'reference', 'request ' || (n ->> 'request_id'), 'settings'),
          case when tg_op = 'UPDATE' then to_jsonb(old) end, n);
  return new;
end $$;

drop trigger if exists reward_cashout_requests_audit on public.reward_cashout_requests;
create trigger reward_cashout_requests_audit after insert or update on public.reward_cashout_requests
  for each row execute function public.reward_cashout_audit();
drop trigger if exists reward_cashout_payments_audit on public.reward_cashout_payments;
create trigger reward_cashout_payments_audit after insert on public.reward_cashout_payments
  for each row execute function public.reward_cashout_audit();
drop trigger if exists reward_cashout_settings_audit on public.reward_cashout_settings;
create trigger reward_cashout_settings_audit after update on public.reward_cashout_settings
  for each row execute function public.reward_cashout_audit();

-- ============================================================================ access (server only)

alter table public.reward_cashout_settings    enable row level security;
alter table public.reward_cashout_requests    enable row level security;
alter table public.reward_cashout_months      enable row level security;
alter table public.reward_cashout_payments    enable row level security;
alter table public.reward_owner_notifications enable row level security;

revoke all on public.reward_cashout_settings, public.reward_cashout_requests, public.reward_cashout_months,
              public.reward_cashout_payments, public.reward_owner_notifications
  from public, anon, authenticated;

grant select, update                 on public.reward_cashout_settings    to service_role;
grant select, insert, update, delete on public.reward_cashout_requests    to service_role;   -- guarded by triggers
grant select, insert, update, delete on public.reward_cashout_months      to service_role;   -- guarded by triggers
grant select, insert, delete         on public.reward_cashout_payments    to service_role;   -- delete: test rows only
grant select, insert, update, delete on public.reward_owner_notifications to service_role;   -- read/email status only

revoke execute on function public.reward_cashout_today(date)                                 from public, anon, authenticated;
revoke execute on function public.reward_cashout_is_owner(text)                              from public, anon, authenticated;
revoke execute on function public.reward_cashout_status(text, date)                          from public, anon, authenticated;
revoke execute on function public.reward_cashout_month_earnings(text, boolean)               from public, anon, authenticated;
revoke execute on function public.reward_cashout_settled(text, text)                         from public, anon, authenticated;
revoke execute on function public.reward_cashout_earnings_changed(bigint)                     from public, anon, authenticated;
revoke execute on function public.reward_cashout_request(text, text, jsonb, int, date, jsonb) from public, anon, authenticated;
revoke execute on function public.reward_cashout_decide(bigint, text, text, text, boolean, boolean, boolean)
  from public, anon, authenticated;
revoke execute on function public.reward_cashout_pay(bigint, int, date, text, text)          from public, anon, authenticated;
revoke execute on function public.reward_cashout_set_fingerprint(bigint, text, text)         from public, anon, authenticated;
grant  execute on function public.reward_cashout_today(date)                                 to service_role;
grant  execute on function public.reward_cashout_is_owner(text)                              to service_role;
grant  execute on function public.reward_cashout_status(text, date)                          to service_role;
grant  execute on function public.reward_cashout_month_earnings(text, boolean)               to service_role;
grant  execute on function public.reward_cashout_settled(text, text)                         to service_role;
grant  execute on function public.reward_cashout_earnings_changed(bigint)                     to service_role;
grant  execute on function public.reward_cashout_request(text, text, jsonb, int, date, jsonb) to service_role;
grant  execute on function public.reward_cashout_decide(bigint, text, text, text, boolean, boolean, boolean) to service_role;
grant  execute on function public.reward_cashout_pay(bigint, int, date, text, text)          to service_role;
grant  execute on function public.reward_cashout_set_fingerprint(bigint, text, text)         to service_role;
