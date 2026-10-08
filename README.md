# World Explorer

Learn about countries and take a geography quiz — capitals, currencies, languages,
borders, UNESCO landmarks, heads of state and more — in English, German, Spanish or Chinese.

## Upload to the existing GitHub repository

Extract the download and open the WorldExplorer folder. Upload its contents
(app.py, requirements.txt, README.md, core/, ui/, data/, assets/ and tests/)
to the root of ukpodman/WorldExplorer. Do not upload the ZIP file or put these
inside another WorldExplorer folder. Keep Streamlit Cloud’s main file path
as app.py and keep the existing Cloud secrets. Authentication dependencies
are included in requirements.txt.

## Run it

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Guest mode works out of the box. Sign-in and saved profiles are optional (see below).

## Project layout

```
app.py                  entry point and page routing
core/
  data.py               loads and validates country data; political-record freshness
  i18n.py               interface translations (template → translate → fill)
  quiz.py               question generation, scoring, round state — pure Python, no Streamlit
  accounts.py           optional sign-in and Supabase profile storage
ui/
  state.py              session state and the callbacks that drive a round
  components.py         header, hero banners, settings drawer, credits
  pages.py              Explore, Learn, Quiz, Badges
data/
  countries.json        country records (adapted from mledoze/countries, ODbL 1.0)
  heads_of_state.json   dated, sourced political records
  photos.json           curated destination photos with licences
  translations.json     UI strings for every language
assets/styles.css       all styling
tests/test_core.py      unit tests:  python -m unittest discover tests
```

## Updating data

- **Countries** — edit `data/countries.json`. Records are validated on load; malformed ones are skipped.
- **Heads of state** — edit `data/heads_of_state.json`, or drop a `data/heads_of_state.local.json`
  with the same shape to override entries. Records older than 30 days are hidden from the quiz
  and the Learn page until you re-verify them and update `verified_on`.
  *The bundled records were verified 2026-10-05, so they drop out after 2026-11-04.*
- **Translations** — add a key (the English text) to `data/translations.json` with one entry per
  non-English language. `tests/test_core.py` fails if a language or a `{field}` is missing.

## Optional: accounts and saved progress

1. `python -m pip install "streamlit[auth]"`
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in.
3. In the Supabase SQL editor:

```sql
create table public.world_explorer_profiles (
  user_id text primary key,
  profile jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now());
alter table public.world_explorer_profiles enable row level security;
revoke all on public.world_explorer_profiles from anon, authenticated;
grant select, insert, update on public.world_explorer_profiles to service_role;
```

No public policies are needed: only this server, using the server key, reads or writes rows,
and the row id is derived from the verified sign-in identity. Never commit `secrets.toml`.

## Sources

Country data adapted from [mledoze/countries](https://github.com/mledoze/countries)
([ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)); the adapted database in `data/` is
distributed under the same licence. Landmarks from the
[UNESCO World Heritage List](https://data.unesco.org/explore/dataset/whc001/), checked 2026-10-08.
Photo credits are listed in the app and in `data/photos.json`.
