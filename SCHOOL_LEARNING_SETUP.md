# School Learning: saving students' progress (PROPOSAL, awaiting the owner's approval)

**Status: NOT applied.** Nothing in V24 changes the production database. Until you approve the migration, run it and switch saving on,
School Learning works fully for everyone, and the page tells students exactly where their progress is kept:

| | Guest | Signed in, saving OFF (today) | Signed in, saving ON (after approval) |
|---|---|---|---|
| Open School Learning, read all 7 lessons, practise, see progress | yes | yes | yes |
| Where progress is kept | this browser tab, or on this device if the student switches on "Keep my progress on this device" (a small cookie, up to 180 days) | this browser tab only; the device cookie is never read or written for a signed-in student | the student's account, available on any device |
| Points, badges, streaks, rewards, Founding 50, referrals, withdrawals | **never** | **never** | **never** |

The app never says progress is saved when it is not. If the tables are missing or unreachable, it says "We could not reach your saved School
Learning progress" and keeps the visit's progress.

**Progress always belongs to one owner (Project Atlas review fix).** School Learning progress in a browser session belongs either to the guest
or to exactly one signed-in account. When the person changes (sign in, sign out, or a different account), the session's School progress is
cleared before the new owner's progress is loaded, so one student's progress can never be added to another student's account.

**Guest progress is offered, never imported silently.** If someone studied as a guest and then signs in, School Learning shows: "You studied N
lessons as a guest on this device … Nothing is added unless you choose." with three buttons:

* **Add to my progress**: copies the guest records into the account (the newer record wins for each lesson) and removes the device copy;
* **Discard guest progress**: deletes the guest copy (for example when someone else used this device as a guest);
* **Not now**: hides the offer for this visit and changes nothing.

## 1. Exact database structure

File: `supabase/school_learning_migration.sql` (one transaction; safe to run twice).

**`public.school_lesson_progress`**: one row per student, subject and lesson. Primary key (`user_id`, `subject`, `lesson_id`).

| Column | Type | Rule / meaning |
|---|---|---|
| `user_id` | text | 64 lowercase hex characters: the same one-way account id the profile table uses (never an e-mail, name, school or date of birth) |
| `subject`, `lesson_id` | text | e.g. `geography`, `ng-climate` |
| `page`, `page_id` | int, text | the current reading position (the index, plus a stable page id that survives corrected lessons) |
| `furthest` | int | furthest page reached; never below `page` |
| `completed`, `completed_at` | boolean, timestamptz | marked complete after reaching the last page |
| `revision` | boolean | on the student's revision list |
| `best`, `last`, `attempts` | int | practice scores and number of finished rounds |
| `answered`, `correct` | int | practice questions answered and answered correctly (`correct ≤ answered`) |
| `recent_questions` | jsonb | ids of the last 20 questions asked, so the next round avoids them (at most 50) |
| `content_version` | int | the lesson version the student last opened |
| `practised_at`, `updated_at` | timestamptz | |

**`public.school_practice_attempts`**: one row per finished practice round. These rows are never edited.

| Column | Type | Rule / meaning |
|---|---|---|
| `id` | bigint identity | |
| `user_id`, `subject`, `lesson_id` | text | as above |
| `score`, `total` | int | `0 ≤ score ≤ total ≤ 100` |
| `answers` | jsonb | a list of `{"q": question id, "ok": true/false}`, under 8 KB; no typed text |
| `content_version` | int | |
| `created_at` | timestamptz | |

Index: `(user_id, subject, lesson_id, created_at desc)`.

## 2. Security policies and their effects

There are now **two files**:

* **`supabase/school_learning_migration.sql`** (the base, needed for server mode):
  * **Row Level Security is ON** for both tables, with **no policies**.
  * **`public`, `anon` and `authenticated`**: every privilege is revoked, so browser keys and Supabase Auth tokens have no access at all.
  * **`service_role`** (the server key the app already uses): select, insert and update on progress; select and insert on attempts. Attempts get no `update`.
* **`supabase/school_learning_user_token_policies.sql`** (OPTIONAL, only for option B below): grants `authenticated` access and adds five policies. A request can select, insert or update progress, and select or insert attempts, **only where `user_id` equals the `we_profile_id` claim in its token**. Do not run this file for server mode.
* There are no foreign keys, triggers or functions that touch `world_explorer_profiles`, `reward_*`, withdrawals, referrals, Founding 50, badges or quiz statistics. Nothing in School Learning can create points or money.
* Supabase Auth's own sign-in tokens never carry the top-level `we_profile_id` claim, so they match no rows, even if Supabase Auth sign-ups were ever enabled.

## 3. One decision for you: how the app connects

| Option | How it works | What you add to Streamlit secrets | Recommendation |
|---|---|---|---|
| **A. Server key (recommended)** | Exactly like the existing profile and rewards tables. The server uses the existing `[profiles] server_key` (including `sb_secret_` keys) and always filters to the signed-in student's id. The browser never sees a key, and browser roles have no access to the tables. Isolation between students is enforced by the app and covered by tests (`tests/test_school_identity.py`). | `[school]`<br>`progress_storage = "supabase"` | **Recommended.** It matches the existing architecture, needs no new secret, and works whatever JWT signing method the project uses. Run only the base migration file. |
| **B. Per-student token (deferred)** | For each request the server signs a 5-minute token that carries only the student's one-way id. The database policies then enforce "own rows only". | `[school]`<br>`progress_storage = "supabase"`<br>`access = "user_token"`<br>`anon_key = "<the project's anon / publishable key>"`<br>`jwt_secret = "<the project's JWT secret>"` | **Deferred.** It needs the legacy HS256 JWT secret, which projects that use only the newer asymmetric signing keys do not have, and that secret is as powerful as the server key. Needs the base file **and** the optional policies file. |

Both options were tested here against a local copy of the database rules (section 6). Neither has been tested against your live Supabase.
Keep `jwt_secret` and the server key only in Streamlit secrets. Never commit them or share them.

## 4. Migration plan (each step only after your approval)

1. **Back up.** In Supabase → Database → Backups, confirm that a recent backup exists, or export the project.
2. **Review** `supabase/school_learning_migration.sql`. It contains only `create table if not exists`, an index, `enable row level security`, `revoke` and `grant` statements, all inside `begin … commit`. (Option B only: also review `supabase/school_learning_user_token_policies.sql`.)
3. **Run** the base file once in Supabase → SQL Editor. Run the optional policies file only if you chose option B.
4. **Verify** with the queries at the end of the file:
   * RLS is on for both tables.
   * Server mode: zero policies are listed, and `anon` / `authenticated` have no grants. (Option B: the five policies are listed.)
   * A server-role test write succeeds inside a transaction that rolls back.
   * The existing tables still have the same row counts.
   * A test row written as one student cannot be read as another (that query runs in a transaction and rolls back).
5. **Switch on** saving with option A or B (section 3) in Streamlit Cloud → App settings → Secrets. Without `progress_storage = "supabase"` the app never calls the new tables.
6. **Test with your own Google account:**
   * Read two pages, add a lesson to revision and finish one practice round.
   * Reload the page, or open it on your phone. You should come back to the same page, with the same status and score.
   * In the Table Editor, check that you see one progress row and one attempt row, holding only the fields listed above.
7. **Roll back if needed.** Remove the `[school]` secret first, then run `drop table if exists public.school_practice_attempts; drop table if exists public.school_lesson_progress;`. This removes only School Learning data.

To delete one student's School Learning data on request: `delete from public.school_practice_attempts where user_id = '<id>'; delete from public.school_lesson_progress where user_id = '<id>';`

## 5. Privacy and child safety

* Students are never asked for a school, class, date of birth, phone number or any other personal detail. Guests need no account at all.
* Stored data is limited to the one-way account id, lesson ids, page positions, completion and revision flags, scores, question ids and right/wrong. School Learning keeps no names or e-mails.
* "Keep my progress on this device" is off until the student switches it on. It stores lesson positions and scores in a first-party cookie (`we_school`), and switching it off deletes the cookie.
* School Learning has no leaderboards, competitions or prizes.

## 6. How this was tested (on a throwaway local database, not yours)

The tests are in `tests/test_school.py`, class `MigrationTests`. They used a local PostgreSQL 16 with the Supabase roles and `auth.jwt()` defined as Supabase defines it. They confirmed that:

* the base migration alone runs twice, adds exactly two tables, and gives `anon` and `authenticated` nothing;
* base + optional policies file runs twice;
* the server role can save and upsert;
* bad ids, `page > furthest`, `correct > answered`, `score > total` and non-list answers are rejected;
* attempts cannot be updated;
* a student's token can insert and read their own rows but sees 0 rows of another student, and cannot insert or update rows for another student;
* a token without the claim sees nothing;
* `anon` cannot select or insert.

App behaviour was tested with a stand-in for the REST calls: saving, then restoring in a new session, and a failing database being reported.

Account boundaries are tested in `tests/test_school_identity.py` (7 tests, written to fail on the original V24 code and pass after the fix):
A then B in one session never mix; a shared browser's device cookie never reaches another account; guest progress is offered, can be added
or discarded; signed-in students get no device copy; signing out and studying as a guest shows none of A's progress; a second subject is
restored too. Full suite on branch `atlas-review`: 516 tests, all passed (20 Oct 2026).

**Live Supabase and real Google sign-in were not tested from here.**
