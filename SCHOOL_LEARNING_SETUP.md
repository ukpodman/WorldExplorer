# School Learning: saving student progress (PROPOSAL, awaiting the owner's approval)

**Status: not applied.** Nothing in this branch changes the live database. Until you approve and switch it on, School
Learning works fully for everyone, and progress is kept for the current visit only. The page tells students this.

## What students get

| | Guest (not signed in) | Signed in, saving OFF (today) | Signed in, saving ON (after approval) |
|---|---|---|---|
| Read all 7 lessons, diagrams, checks, exam questions | yes | yes | yes |
| Practise 10 questions per lesson | yes | yes | yes |
| Reading position, Completed, Revision list, scores | this browser tab only | this visit only | saved to their account |
| Points, badges, streaks, rewards, withdrawals | **never** | **never** | **never** |

## 1. Proposed database structure

Two new tables, used only by School Learning. File: `supabase/school_learning_migration.sql`.

**`public.school_lesson_progress`**: one row per student, subject and lesson

| Column | Type | Rule |
|---|---|---|
| `user_id` | text | 64 lowercase hex characters: the same one-way account id as the profile table (never an e-mail or name) |
| `subject` | text | e.g. `geography` (lowercase letters, digits, hyphens) |
| `lesson_id` | text | e.g. `ng-climate` |
| `page` | int | reading position, 0–99 |
| `furthest` | int | furthest page reached, 0–99, never below `page` |
| `completed` | boolean | the student marked the lesson complete (only allowed after reaching the last page) |
| `completed_at` | timestamptz | |
| `revision` | boolean | on the student's revision list (separate from completion) |
| `best`, `last` | int | best and latest practice score, 0–100 |
| `attempts` | int | finished practice sessions, ≥ 0 |
| `practised_at`, `updated_at` | timestamptz | |
| **primary key** | | (`user_id`, `subject`, `lesson_id`) |

**`public.school_practice_attempts`**: one row per finished practice (a history, never edited)

| Column | Type | Rule |
|---|---|---|
| `id` | bigint identity | |
| `user_id`, `subject`, `lesson_id` | text | as above |
| `score`, `total` | int | `0 ≤ score ≤ total ≤ 100` |
| `answers` | jsonb | a list of `{"q": question id, "ok": true/false}`, under 8 KB. No typed text, nothing personal |
| `created_at` | timestamptz | |

Index: `(user_id, subject, lesson_id, created_at desc)`.

## 2. Security policies

The same model as the existing World Explorer tables:

* **Row Level Security ON** for both tables, with **no policies**, so the browser roles can do nothing.
* `revoke all … from public, anon, authenticated`: students' browsers can never read or write these tables.
* `service_role` only (the server key the app already uses, on the server): progress gets `select, insert, update, delete`. Attempts get `select, insert, delete` and **no update**, so a score is never changed after it is recorded.
* There are no foreign keys or triggers into `world_explorer_profiles`, `reward_*`, withdrawals, referrals, badges or quiz tables. Nothing in School Learning can create points or money.
* Children's privacy: the tables hold only the hashed account id, lesson ids, page numbers, dates and scores.

## 3. Migration plan (each step only after your approval)

1. **Back up.** In Supabase, go to Database → Backups and confirm a recent backup exists, or export the project.
2. **Review** `supabase/school_learning_migration.sql`. It contains only `create table if not exists`, an index, RLS, revoke and grant statements, all in one transaction.
3. **Run** it once in Supabase → SQL Editor. It is safe to run again.
4. **Check** in the Table Editor that both tables exist, show "RLS enabled" and have no policies.
5. **Switch on** saving by adding this to Streamlit Cloud → App settings → Secrets (next to the existing `[profiles]` section, which must already be set up):
   ```toml
   [school]
   progress_storage = "supabase"
   ```
   Without this line the app never calls the new tables, even if they exist.
6. **Test** with your own Google account: read two pages, mark a lesson complete, finish one practice, then reload. Your position, status and score should come back. Then check one row in each table.
7. **Roll back** (removes only School Learning data): remove the `[school]` secret, then
   `drop table if exists public.school_practice_attempts; drop table if exists public.school_lesson_progress;`

To delete one student's data on request: `delete from public.school_practice_attempts where user_id = '<id>'; delete from public.school_lesson_progress where user_id = '<id>';`

## How it was tested here (not on your database)

* The migration ran twice on a throwaway local PostgreSQL 16 with the Supabase roles (`tests/test_school.py`, MigrationTests). Those tests check that the server role can save and upsert, that bad ids, out-of-range pages and scores and non-list answers are rejected, that attempts cannot be updated, that `anon` and `authenticated` cannot select or insert, and that RLS is on.
* The app code was tested with the storage switched off (the default) and with a stand-in for the REST calls. **Live Supabase and Google sign-in were not tested**, because this session has no access to them.
