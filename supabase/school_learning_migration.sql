-- World Explorer V24 — School Learning progress — PROPOSED migration (NOT APPLIED; awaiting the owner's approval)
--
-- Run once in Supabase → SQL Editor only after approval (see SCHOOL_LEARNING_SETUP.md). It only ADDS two new tables
-- whose names start with school_, their indexes and their security policies. It does not read, change or reference
-- world_explorer_profiles, any reward_* / withdrawal / referral / Founding 50 table, points, badges or quiz statistics.
-- Non-destructive and safe to run again: "if not exists" everywhere, policies are dropped and re-created by name.
--
-- Data kept (privacy by design — students may be under 18): the one-way account id (the same SHA-256 id the profile
-- table uses; never an e-mail, name, school or date of birth), lesson ids, reading position, completion, revision
-- choice, practice scores, and for each finished practice the question ids with right/wrong. No free text.
--
-- Security:
--   * Row Level Security ON for both tables.
--   * anon (the public browser key): NO access at all.
--   * authenticated: NO access in this base migration (recommended "server" mode). An OPTIONAL, separate file,
--     supabase/school_learning_user_token_policies.sql, adds per-student policies for the "user_token" mode; do not run
--     it unless that mode is approved (see SCHOOL_LEARNING_SETUP.md).
--   * service_role (the existing server key): full access, as for the existing tables (access = "server" mode).
--   * Practice attempts can be added and read, never edited.

begin;

-- ============================================================================ tables

create table if not exists public.school_lesson_progress (
  user_id           text        not null check (user_id ~ '^[0-9a-f]{64}$'),
  subject           text        not null check (subject ~ '^[a-z0-9-]{1,64}$'),
  lesson_id         text        not null check (lesson_id ~ '^[a-z0-9-]{1,64}$'),
  page              int         not null default 0 check (page between 0 and 99),
  page_id           text        check (page_id ~ '^[a-z0-9-]{1,64}$'),                 -- stable reading position
  furthest          int         not null default 0 check (furthest between 0 and 99 and furthest >= page),
  completed         boolean     not null default false,
  completed_at      timestamptz,
  revision          boolean     not null default false,
  best              int         check (best between 0 and 100),
  last              int         check (last between 0 and 100),
  attempts          int         not null default 0 check (attempts >= 0),
  answered          int         not null default 0 check (answered >= 0),
  correct           int         not null default 0 check (correct >= 0 and correct <= answered),
  recent_questions  jsonb       not null default '[]'::jsonb
                    check (jsonb_typeof(recent_questions) = 'array' and jsonb_array_length(recent_questions) <= 50),
  content_version   int         not null default 1 check (content_version >= 1),
  practised_at      timestamptz,
  updated_at        timestamptz not null default now(),
  primary key (user_id, subject, lesson_id)
);

create table if not exists public.school_practice_attempts (
  id               bigint generated always as identity primary key,
  user_id          text        not null check (user_id ~ '^[0-9a-f]{64}$'),
  subject          text        not null check (subject ~ '^[a-z0-9-]{1,64}$'),
  lesson_id        text        not null check (lesson_id ~ '^[a-z0-9-]{1,64}$'),
  score            int         not null check (score >= 0),
  total            int         not null check (total between 1 and 100 and score <= total),
  answers          jsonb       not null default '[]'::jsonb
                   check (jsonb_typeof(answers) = 'array' and pg_column_size(answers) < 8192),
  content_version  int         not null default 1 check (content_version >= 1),
  created_at       timestamptz not null default now()
);

create index if not exists school_practice_attempts_user
  on public.school_practice_attempts (user_id, subject, lesson_id, created_at desc);

-- ============================================================================ security

alter table public.school_lesson_progress   enable row level security;
alter table public.school_practice_attempts enable row level security;

revoke all on public.school_lesson_progress   from public, anon, authenticated;
revoke all on public.school_practice_attempts from public, anon, authenticated;

grant select, insert, update, delete  on public.school_lesson_progress   to service_role;
grant select, insert, delete          on public.school_practice_attempts to service_role;   -- attempts are never edited

commit;

-- ============================================================================ verification (run after the migration)
-- 1. Both tables exist with RLS on (expect two rows, both true):
--      select relname, relrowsecurity from pg_class where relname in ('school_lesson_progress', 'school_practice_attempts');
-- 2. No policies and no browser-role privileges in server mode (expect zero rows for both):
--      select tablename, policyname from pg_policies where tablename like 'school_%';
--      select grantee, table_name, privilege_type from information_schema.role_table_grants
--      where table_name like 'school_%' and grantee in ('anon', 'authenticated', 'PUBLIC');
-- 3. The server role can write and read (run in a transaction and roll back):
--      begin; set local role service_role;
--      insert into public.school_lesson_progress (user_id, subject, lesson_id) values (repeat('a', 64), 'geography', 'ng-climate');
--      select count(*) from public.school_lesson_progress;   -- expect 1
--      rollback;
-- 4. Nothing else was changed (expect the same row counts as before the migration, e.g.):
--      select count(*) from public.world_explorer_profiles;
-- ============================================================================ rollback (removes ONLY School Learning data)
-- First remove the [school] section from Streamlit secrets (the app then stops using the tables), then:
--   drop table if exists public.school_practice_attempts;
--   drop table if exists public.school_lesson_progress;
-- Delete one student's School Learning data (for example on an account deletion request):
--   delete from public.school_practice_attempts where user_id = '<id>';
--   delete from public.school_lesson_progress   where user_id = '<id>';
