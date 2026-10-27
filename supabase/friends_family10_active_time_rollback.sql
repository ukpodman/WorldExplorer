-- WORLD EXPLORER — FRIENDS & FAMILY 10: rollback of friends_family10_active_time_migration.sql
-- PROPOSED — run only on the Owner's decision. Restores the original pilot_month_ledger (verbatim from
-- friends_family10_migration.sql) and stops recording activity checks. The pilot_heartbeats table and its rows are
-- KEPT for the audit trail (they no longer affect any amount); drop it separately only if the Owner decides so.

revoke execute on function public.pilot_record_heartbeat(text, text) from service_role;
drop function if exists public.pilot_record_heartbeat(text, text);
drop function if exists public.pilot_record_heartbeat_at(text, text, timestamptz);

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

revoke execute on function public.pilot_month_ledger(text, text) from public, anon, authenticated;
grant  execute on function public.pilot_month_ledger(text, text) to service_role;
