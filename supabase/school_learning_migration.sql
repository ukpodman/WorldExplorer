-- World Explorer — School Learning progress — PROPOSED migration (NOT APPLIED; for the owner's approval)
--
-- Run once in Supabase → SQL Editor only after approval (see SCHOOL_LEARNING_SETUP.md). It only ADDS two new tables
-- whose names start with school_. It does not read, change or reference world_explorer_profiles, any reward_* or
-- withdrawal table, points, badges, referrals or quiz statistics. Safe to run again ("if not exists").
--
-- Security model (same as the existing tables): Row Level Security ON with no policies, so the browser roles
-- (anon, authenticated) can do nothing; only the server key (service_role), used by the app on the server, can read
-- and write. Students never talk to the database directly.
--
-- Data kept: a one-way account id (the same SHA-256 id the profile table uses, never an e-mail or name), lesson
-- reading position and status, revision flag, practice scores, and for each finished practice the question ids with
-- right/wrong. No free text, no answers typed by students.

begin;

create table if not exists public.school_lesson_progress (
  user_id       text        not null check (user_id ~ '^[0-9a-f]{64}$'),
  subject       text        not null check (subject ~ '^[a-z0-9-]{1,64}$'),
  lesson_id     text        not null check (lesson_id ~ '^[a-z0-9-]{1,64}$'),
  page          int         not null default 0 check (page between 0 and 99),
  furthest      int         not null default 0 check (furthest between 0 and 99 and furthest >= page),
  completed     boolean     not null default false,
  completed_at  timestamptz,
  revision      boolean     not null default false,
  best          int         check (best between 0 and 100),
  last          int         check (last between 0 and 100),
  attempts      int         not null default 0 check (attempts >= 0),
  practised_at  timestamptz,
  updated_at    timestamptz not null default now(),
  primary key (user_id, subject, lesson_id)
);

create table if not exists public.school_practice_attempts (
  id          bigint generated always as identity primary key,
  user_id     text        not null check (user_id ~ '^[0-9a-f]{64}$'),
  subject     text        not null check (subject ~ '^[a-z0-9-]{1,64}$'),
  lesson_id   text        not null check (lesson_id ~ '^[a-z0-9-]{1,64}$'),
  score       int         not null check (score >= 0),
  total       int         not null check (total between 1 and 100 and score <= total),
  answers     jsonb       not null default '[]'::jsonb check (jsonb_typeof(answers) = 'array' and pg_column_size(answers) < 8192),
  created_at  timestamptz not null default now()
);

create index if not exists school_practice_attempts_user on public.school_practice_attempts (user_id, subject, lesson_id, created_at desc);

-- Security: RLS on, no policies, browser roles have no privileges, server key only.
alter table public.school_lesson_progress   enable row level security;
alter table public.school_practice_attempts enable row level security;
revoke all on public.school_lesson_progress   from public, anon, authenticated;
revoke all on public.school_practice_attempts from public, anon, authenticated;
grant select, insert, update, delete on public.school_lesson_progress   to service_role;
grant select, insert, delete         on public.school_practice_attempts to service_role;   -- attempts are never edited

commit;

-- ----------------------------------------------------------------------------------------------------------------
-- Rollback (removes ONLY School Learning data; nothing else is affected):
--   drop table if exists public.school_practice_attempts;
--   drop table if exists public.school_lesson_progress;
-- Delete one student's School Learning data (e.g. on an account deletion request):
--   delete from public.school_practice_attempts where user_id = '<id>';
--   delete from public.school_lesson_progress   where user_id = '<id>';
