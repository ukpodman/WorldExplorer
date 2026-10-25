-- World Explorer — FRIENDS & FAMILY 10: real cash payments (manual Nigerian bank transfers) — PROPOSED additive migration
--
-- STATUS: proposed for review. Do NOT run it until it has been reviewed and the owner approves. It does not switch
-- payments on and pays nothing by itself.
-- Run AFTER friends_family10_migration.sql (already installed). Safe to run again. It changes no existing record.
--
-- What it adds (the private pilot only; Public Rewards, the public payout switch and public withdrawals are untouched)
--   * Pilot payment authorisation: pilot_reward_settings.payments_enabled can now be switched by the owner ONLY through
--     pilot_set_payments(enabled, actor, confirmed). Switching ON needs the confirmation and the approved pilot terms
--     recorded in the database (the app additionally requires every published legal document and the operator
--     details). Every change is audited. It is independent of reward_cashout_settings.real_payouts (public payouts).
--   * pilot_beneficiaries: the owner's record that a participant's identity and bank account name were checked:
--     legal name, bank name and the LAST FOUR digits of the account only (full account numbers are never stored).
--   * pilot_payments: the payment ledger, one row per participant and settled month: beneficiary (name, bank, last 4
--     digits), amount, transfer date, bank transfer reference, status, who recorded it and when. Rows are never
--     edited or deleted.
--   * pilot_record_payment(month, profile, amount, paid_on, reference, actor, confirmed) — the only way to record a
--     manual bank transfer. It refuses unless: pilot payments are authorised; the month is settled; the participant's
--     final allocation is APPROVED and not yet paid; the beneficiary is verified; the amount equals the approved final
--     allocation exactly; the month's recorded payments stay within the settlement total and the ₦50,000 budget; the
--     reference is new; the date is not in the future and not before the settlement. One payment per participant and
--     month (unique), serialised by a month lock.
--   * pilot_mark_paid (from the previous migration) now always refuses: use pilot_record_payment.
--
-- Security: Row Level Security ON; anon and authenticated get nothing; service_role may only READ the new tables;
-- every write goes through the functions below (SECURITY DEFINER, fixed search_path), which check the owner list.

do $$
begin
  if to_regclass('public.pilot_settlement_lines') is null then
    raise exception 'Run supabase/friends_family10_migration.sql first.';
  end if;
end $$;

-- ============================================================================ payment authorisation (owner switch)

alter table public.pilot_reward_settings drop constraint if exists pilot_reward_settings_payments_enabled_check;
alter table public.pilot_reward_settings add column if not exists payments_changed_at timestamptz;
alter table public.pilot_reward_settings add column if not exists payments_changed_by text;

create or replace function public.pilot_set_payments(p_enabled boolean, p_actor text, p_confirmed boolean default false)
returns public.pilot_reward_settings
language plpgsql security definer set search_path = public as $$
declare
  row public.pilot_reward_settings;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if p_enabled and not coalesce(p_confirmed, false) then raise exception 'confirmation_required'; end if;
  if p_enabled and nullif(btrim(coalesce(public.reward_pilot_terms(), '')), '') is null then
    raise exception 'terms_required';                                      -- the approved pilot terms first
  end if;
  update public.pilot_reward_settings
     set payments_enabled = coalesce(p_enabled, false), payments_changed_at = now(), payments_changed_by = p_actor
   where id = 1
  returning * into row;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, case when p_enabled then 'pilot_payments_on' else 'pilot_payments_off' end, 'pilot_payments',
          jsonb_build_object('payments_enabled', row.payments_enabled, 'pilot_terms', public.reward_pilot_terms()));
  return row;
end $$;

-- ============================================================================ beneficiary verification

create table if not exists public.pilot_beneficiaries (
  profile_id     text primary key references public.reward_accounts (profile_id),
  legal_name     text not null check (length(btrim(legal_name)) between 3 and 120),
  bank_name      text not null check (length(btrim(bank_name)) between 2 and 80),
  account_last4  text not null check (account_last4 ~ '^[0-9]{4}$'),         -- never the full account number
  verified       boolean not null default true,
  note           text check (note is null or length(note) <= 500),
  verified_by    text not null,
  verified_at    timestamptz not null default now()
);

create or replace function public.pilot_verify_beneficiary(p_profile text, p_legal_name text, p_bank_name text,
                                                           p_account_last4 text, p_actor text, p_confirmed boolean,
                                                           p_note text default null)
returns public.pilot_beneficiaries
language plpgsql security definer set search_path = public as $$
declare
  row public.pilot_beneficiaries;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if not coalesce(p_confirmed, false) then raise exception 'confirmation_required'; end if;
  if not public.pilot_is_participant(p_profile) then raise exception 'not_participant'; end if;
  if coalesce(btrim(p_account_last4), '') !~ '^[0-9]{4}$' then raise exception 'invalid_account_last4'; end if;
  if length(btrim(coalesce(p_legal_name, ''))) < 3 or length(btrim(coalesce(p_bank_name, ''))) < 2 then
    raise exception 'details_required';
  end if;
  insert into public.pilot_beneficiaries (profile_id, legal_name, bank_name, account_last4, verified, note,
                                          verified_by, verified_at)
  values (p_profile, btrim(p_legal_name), btrim(p_bank_name), btrim(p_account_last4), true,
          nullif(btrim(coalesce(p_note, '')), ''), p_actor, now())
  on conflict (profile_id) do update
    set legal_name = excluded.legal_name, bank_name = excluded.bank_name, account_last4 = excluded.account_last4,
        verified = true, note = excluded.note, verified_by = excluded.verified_by, verified_at = excluded.verified_at
  returning * into row;
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, 'pilot_beneficiary_verified', p_profile, to_jsonb(row));
  return row;
end $$;

-- ============================================================================ payment ledger

create table if not exists public.pilot_payments (
  id                bigint generated always as identity primary key,
  month             text not null,
  profile_id        text not null references public.reward_accounts (profile_id),
  amount            int not null check (amount > 0 and amount <= 7000),
  paid_on           date not null,
  bank_reference    text not null unique check (length(btrim(bank_reference)) between 4 and 100),
  beneficiary_name  text not null,
  bank_name         text not null,
  account_last4     text not null check (account_last4 ~ '^[0-9]{4}$'),
  status            text not null default 'paid' check (status in ('paid')),
  recorded_by       text not null,
  recorded_at       timestamptz not null default now(),
  unique (month, profile_id),                                              -- one payment per person and month
  foreign key (month, profile_id) references public.pilot_settlement_lines (month, profile_id)
);

create or replace function public.pilot_payments_guard() returns trigger
language plpgsql as $$
begin
  raise exception 'pilot payments are kept unchanged for the audit trail';
end $$;
drop trigger if exists pilot_payments_guard on public.pilot_payments;
create trigger pilot_payments_guard before update or delete on public.pilot_payments
  for each row execute function public.pilot_payments_guard();

create or replace function public.pilot_record_payment(p_month text, p_profile text, p_amount int, p_paid_on date,
                                                       p_reference text, p_actor text, p_confirmed boolean)
returns public.pilot_payments
language plpgsql security definer set search_path = public as $$
declare
  s     public.pilot_reward_settings;
  st    public.pilot_settlements;
  line  public.pilot_settlement_lines;
  ben   public.pilot_beneficiaries;
  paid  int;
  ref   text := btrim(coalesce(p_reference, ''));
  row   public.pilot_payments;
begin
  if not public.reward_cashout_is_owner(p_actor) then raise exception 'not_owner'; end if;
  if not coalesce(p_confirmed, false) then raise exception 'confirmation_required'; end if;
  select * into s from public.pilot_reward_settings where id = 1;
  if not s.payments_enabled then raise exception 'payments_disabled'; end if;
  perform pg_advisory_xact_lock(hashtext('ff10:pay:' || coalesce(p_month, '')));   -- one payment at a time per month
  select * into st from public.pilot_settlements where month = p_month;
  if not found then raise exception 'not_settled'; end if;
  select * into line from public.pilot_settlement_lines where month = p_month and profile_id = p_profile for update;
  if not found then raise exception 'unknown_line'; end if;
  if line.status = 'paid' or exists (select 1 from public.pilot_payments where month = p_month and profile_id = p_profile)
    then raise exception 'already_paid'; end if;
  if line.status <> 'approved' then raise exception 'not_approved'; end if;
  select * into ben from public.pilot_beneficiaries where profile_id = p_profile and verified;
  if not found then raise exception 'beneficiary_not_verified'; end if;
  if p_amount is distinct from line.final or line.final <= 0 then raise exception 'amount_mismatch'; end if;
  select coalesce(sum(amount), 0) into paid from public.pilot_payments where month = p_month;
  if paid + p_amount > st.total_final or paid + p_amount > s.monthly_budget then raise exception 'budget_exceeded'; end if;
  if length(ref) < 4 then raise exception 'reference_required'; end if;
  if exists (select 1 from public.pilot_payments where bank_reference = ref) then raise exception 'duplicate_reference'; end if;
  if p_paid_on is null or p_paid_on > (now() at time zone 'Africa/Lagos')::date
     or p_paid_on < (st.finalised_at at time zone 'Africa/Lagos')::date then
    raise exception 'invalid_date';
  end if;
  insert into public.pilot_payments (month, profile_id, amount, paid_on, bank_reference, beneficiary_name, bank_name,
                                     account_last4, recorded_by)
  values (p_month, p_profile, p_amount, p_paid_on, ref, ben.legal_name, ben.bank_name, ben.account_last4, p_actor)
  returning * into row;
  perform set_config('we.ff10', 'on', true);
  update public.pilot_settlement_lines
     set status = 'paid', paid_at = now(), payment_reference = ref, decided_by = p_actor, decided_at = now()
   where month = p_month and profile_id = p_profile;
  perform set_config('we.ff10', 'off', true);
  insert into public.reward_audit_log (actor, action, target, new_value)
  values (p_actor, 'pilot_payment_recorded', p_profile || ' ' || p_month, to_jsonb(row));
  return row;
end $$;

-- the earlier placeholder: payments are recorded only through pilot_record_payment
create or replace function public.pilot_mark_paid(p_month text, p_profile text, p_actor text, p_reference text)
returns public.pilot_settlement_lines
language plpgsql security definer set search_path = public as $$
begin
  raise exception 'use_pilot_record_payment';
end $$;

-- ============================================================================ security

alter table public.pilot_beneficiaries enable row level security;
alter table public.pilot_payments      enable row level security;
revoke all on public.pilot_beneficiaries, public.pilot_payments from public, anon, authenticated;
grant select on public.pilot_beneficiaries, public.pilot_payments to service_role;

revoke execute on function public.pilot_set_payments(boolean, text, boolean)                  from public, anon, authenticated;
revoke execute on function public.pilot_verify_beneficiary(text, text, text, text, text, boolean, text)
                                                                                                from public, anon, authenticated;
revoke execute on function public.pilot_record_payment(text, text, int, date, text, text, boolean)
                                                                                                from public, anon, authenticated;
revoke execute on function public.pilot_payments_guard()                                      from public, anon, authenticated;
grant  execute on function public.pilot_set_payments(boolean, text, boolean)                  to service_role;
grant  execute on function public.pilot_verify_beneficiary(text, text, text, text, text, boolean, text)
                                                                                                to service_role;
grant  execute on function public.pilot_record_payment(text, text, int, date, text, text, boolean)
                                                                                                to service_role;

-- Check after running (expected: 0 rows):
--   select table_name, grantee from information_schema.role_table_grants
--    where table_name in ('pilot_beneficiaries', 'pilot_payments') and grantee in ('anon', 'authenticated');
