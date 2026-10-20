-- World Explorer V24 — School Learning — OPTIONAL per-student policies for access = "user_token" (NOT APPLIED)
--
-- Run ONLY if the owner approves the "user_token" access mode, AFTER supabase/school_learning_migration.sql.
-- Requirements: the project can verify HS256 tokens signed with its legacy JWT secret. Projects that have moved to the
-- newer asymmetric JWT signing keys cannot verify tokens the app signs itself, so this mode does not work there.
-- Effect: the "authenticated" role may read/insert/update ONLY rows whose user_id equals the token's top-level
-- "we_profile_id" claim; attempts can be added and read, never edited. anon stays without access.
-- Undo: drop the five policies below and revoke the two grants.

begin;

grant select, insert, update          on public.school_lesson_progress   to authenticated;
grant select, insert                  on public.school_practice_attempts to authenticated;

drop policy if exists school_progress_own_select on public.school_lesson_progress;
drop policy if exists school_progress_own_insert on public.school_lesson_progress;
drop policy if exists school_progress_own_update on public.school_lesson_progress;
drop policy if exists school_attempts_own_select on public.school_practice_attempts;
drop policy if exists school_attempts_own_insert on public.school_practice_attempts;

create policy school_progress_own_select on public.school_lesson_progress for select to authenticated
  using (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''));
create policy school_progress_own_insert on public.school_lesson_progress for insert to authenticated
  with check (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''));
create policy school_progress_own_update on public.school_lesson_progress for update to authenticated
  using (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''))
  with check (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''));
create policy school_attempts_own_select on public.school_practice_attempts for select to authenticated
  using (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''));
create policy school_attempts_own_insert on public.school_practice_attempts for insert to authenticated
  with check (user_id = coalesce(auth.jwt() ->> 'we_profile_id', ''));

commit;

-- Verification: expect five policies, all for the authenticated role:
--   select tablename, policyname, roles, cmd from pg_policies where tablename like 'school_%' order by 1, 2;
-- Isolation check (transaction, rolled back):
--   begin; set local role authenticated;
--   select set_config('request.jwt.claims', '{"role":"authenticated","we_profile_id":"' || repeat('a', 64) || '"}', true);
--   insert into public.school_lesson_progress (user_id, subject, lesson_id) values (repeat('a', 64), 'geography', 'ng-climate');
--   select set_config('request.jwt.claims', '{"role":"authenticated","we_profile_id":"' || repeat('b', 64) || '"}', true);
--   select count(*) from public.school_lesson_progress;   -- expect 0
--   rollback;
