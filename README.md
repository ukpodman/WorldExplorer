# World Explorer

Learn about every country and take a geography quiz in English, German, Spanish or Chinese. The
quiz covers capitals, flags, currencies, languages, neighbours, UNESCO landmarks, area
comparisons, heads of state and more.

- **195 UN member and observer states** by default, plus **49 territories and other places** on request,
  each with a neutral status label. See `COVERAGE.md` for the reference comparison, counts and sources.
- All learning data is bundled. Browsing and quizzes never call an external API.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py --server.port 8502
```

Guest mode works out of the box. Sign-in and saved profiles are optional: see `LOGIN_SETUP.md`.

## Upload to the existing GitHub repository (ukpodman/WorldExplorer, branch main)

Extract the ZIP. Inside the `WorldExplorer` folder you will find `app.py`, `requirements.txt`, the
folders `core/`, `ui/`, `data/`, `assets/`, `tests/` and `tools/`, the `.md` files, and the hidden
`.streamlit/config.toml` and `.gitignore`.

**Browser upload (about 40 files, one upload):**
1. Open https://github.com/ukpodman/WorldExplorer on the `main` branch.
2. **Add file → Upload files**.
3. Open the extracted `WorldExplorer` folder, select **everything inside it** (not the folder itself,
   not the ZIP) and drag it onto the page. Folders keep their structure; same-named files are replaced.
4. Check the list shows `app.py` at the top level and paths such as `core/quiz.py` and `assets/flags.json`.
5. Commit directly to `main`.
6. Hidden files: if `.streamlit/config.toml` (light theme) or `.gitignore` are missing afterwards
   (some systems hide dot files), use **Add file → Create new file**, type the same path and name,
   and paste the contents. The app also works without them.

**Or with GitHub Desktop:** clone the repository, copy everything from the extracted folder into
the clone, replacing files, then commit and push to `main`.

Streamlit Community Cloud redeploys automatically. Keep the main file path as `app.py` and keep
your existing Cloud secrets (never upload `secrets.toml`).

## Project layout

```
app.py                     entry point and page routing
requirements.txt           streamlit[auth]==1.65.0, Pillow
core/
  data.py                  loads/validates places, statuses, flags; political-record freshness
  i18n.py                  interface translations + localised country names
  quiz.py                  question generation, deduplication, scoring, round state (pure Python)
  accounts.py              optional sign-in diagnostics and Supabase profile storage
ui/
  state.py                 session state and round callbacks
  components.py            header, hero, settings drawer (profile, sign-in help, places, sound)
  pages.py                 Explore, Learn, Quiz, Badges
  sound.py                 optional generated sound effects
data/
  countries.json           244 places (generated; do not edit by hand)
  heads_of_state.json      dated, sourced political records
  photos.json              curated destination photos with licences
  translations.json        interface strings for every language
  reference/               UN reference list, corrections, carried-over facts, coverage report
assets/
  styles.css               all styling (palette and accessibility notes at the top)
  flags.json               244 flag images (WebP, base64) in one file
tests/                     test_core.py (logic) and test_app.py (real Streamlit AppTest)
tools/                     rebuild data/countries.json, flags.json and COVERAGE.md
```

## Tests

```bash
python -m unittest discover tests
```
`test_core.py` needs only Python. `test_app.py` runs the real app with Streamlit's AppTest and is
skipped if Streamlit is not installed.

## Updating data

1. `git clone https://github.com/mledoze/countries` (any location).
2. Edit corrections in `data/reference/curation.json` if needed (each entry records its reason).
3. `python tools/build_countries.py <clone>`, then `python tools/render_flags.py <clone>`
   (needs Playwright + Chromium), then `python tools/write_coverage_md.py`.
4. Run the tests.

**Heads of state:** edit `data/heads_of_state.json` only after rechecking each source, and set
`verified_on` to the date you checked. Records older than 30 days are hidden automatically.
The bundled records were verified 2026-10-05, so they disappear after 2026-11-04 unless re-verified.

## Supabase table (optional saved profiles)

```sql
create table public.world_explorer_profiles (
  user_id text primary key,
  profile jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now());
alter table public.world_explorer_profiles enable row level security;
revoke all on public.world_explorer_profiles from anon, authenticated;
grant select, insert, update on public.world_explorer_profiles to service_role;
```

Only the server, using the server key from secrets, reads or writes rows. The row id is derived
from the verified sign-in identity.

## Sounds

Sound effects are off by default (☰ Settings → Sound effects, with volume and preview). The tones
are generated in Python (`ui/sound.py`), so no third-party audio files or licences are involved.
Each sound plays once, never on reruns. If the browser blocks sound, nothing breaks, and every
sound has an on-screen message too.

## Licences

Country data: [mledoze/countries](https://github.com/mledoze/countries), ODbL 1.0. The adapted
database in `data/` is distributed under the same licence. Flags come from the same repository
but are not covered by the ODbL (see `COVERAGE.md`). Photo credits are listed in the app and in
`data/photos.json`. Landmarks link to the UNESCO World Heritage List.
