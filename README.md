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

Extract the ZIP and open the `WorldExplorer` folder.

**1. Upload the visible files (one browser upload).**
1. Open https://github.com/ukpodman/WorldExplorer on the `main` branch → **Add file → Upload files**.
2. Select everything inside the extracted folder (not the folder itself, not the ZIP) and drag it in.
   Folders keep their structure and same-named files are replaced.
3. Check the list shows `app.py` at the top level and paths such as `core/badges.py` and `assets/styles.css`.
4. Commit directly to `main`.

**2. Add or replace the hidden theme file `.streamlit/config.toml` (required for automatic light/dark).**
The browser upload usually skips files in hidden folders, so do this step by hand:
1. In the repository, check whether `.streamlit/config.toml` exists (open the `.streamlit` folder if it is listed).
   - **It exists:** open it, click the pencil (Edit) icon, select all and delete the old text.
   - **It does not exist:** choose **Add file → Create new file** and type the name exactly: `.streamlit/config.toml`
     (typing the `/` creates the folder).
2. Open `.streamlit/config.toml` from the extracted folder in a text editor (Notepad/TextEdit; on Windows enable
   *View → Show → Hidden items*, on a Mac press Cmd+Shift+. in Finder), copy everything and paste it into GitHub.
3. Commit to `main`. Optionally repeat for `.gitignore` the same way.

Without this file Streamlit uses its own default colours; the app stays readable (it follows whichever theme
Streamlit shows) but the ivory/navy palette is only exact with the file in place.

Never upload `.streamlit/secrets.toml`. Keep the existing Streamlit Cloud secrets and the main file
path `app.py`; the app redeploys automatically after each commit.

**Or with GitHub Desktop / git:** copy everything (including hidden files) into your clone,
commit and push to `main`. Hidden files are included automatically.

## Project layout

```
app.py                     entry point and page routing
requirements.txt           streamlit[auth]==1.65.0, Pillow
core/
  data.py                  loads/validates places, statuses, flags; political-record freshness
  i18n.py                  interface translations + localised country names
  quiz.py                  question generation, deduplication, scoring, round state (pure Python)
  accounts.py              optional sign-in diagnostics and Supabase profile storage
  badges.py                badge rules and the quiz statistics they are earned from
  records.py               medals and personal records (per round settings)
  facts.py                 the sourced "Did you know?" fact after each answer
  learn.py                 Learn helpers: country stepping, neighbours by collection, size comparison
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

## Scoring rules

| Part | Rule |
|---|---|
| Base points | 100 × difficulty (Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2), for a correct answer |
| Streak multiplier | Consecutive correct answers in the current round: 1st–2nd ×1, 3rd–4th ×2, 5th onward ×3. Only the base points are multiplied |
| Streak reset | A wrong answer or a timeout resets the streak to 0. Every new round starts at 0. (There is no skip button; leaving the page keeps the round and the streak.) |
| Speed bonus | +25 (flat, not multiplied) for answering within 7 s, or within a third of the time limit in timed rounds |
| Hint | −25 (flat) from that answer, applied after multiplying. A hinted correct answer still continues the streak |
| Question total | `max(0, base × multiplier + speed − hint)`; wrong and timed-out answers score 0 |
| Perfect round | +250 × difficulty when every answer is correct and no hint was used. Never multiplied by the streak |
| Medals | Accuracy only: gold ≥ 90 %, silver ≥ 70 %, bronze ≥ 50 %, otherwise "Keep practising" |
| Score records | Compared only with rounds of identical settings: places, area, category, difficulty, question count, timed or not, and (for Mixed) flag questions on/off |
| Streak record | Best answer streak in any round |

Each answer, timeout and finished round is recorded once: answer, Next and timer callbacks check the round
serial and question number, and a finished round is marked so totals, badge statistics and records never
change twice (double clicks, reruns, navigation). A browser refresh starts a new session: guests start
fresh, signed-in players reload their saved profile.

## Checking sign-in and saved records yourself

Google sign-in and Supabase saving cannot be tested from the development environment (no access to your
accounts). After uploading:
1. Open the app, sign in with Google (☰ → Continue with Google). The footer should say "Saved to your account".
2. Play one 5-question round. Note the score, the streak record and the "First score for these settings" line.
3. Reload the page (or open it on another device) and sign in again. Play a round with the same settings:
   the results should now say "Your best for these settings" (or "New best…") with your earlier score, and
   Badges should show the same points and rounds as before.
4. In Supabase (Table editor → `world_explorer_profiles`) your row's `profile` JSON should now contain a
   `records` entry next to `points`, `rounds_finished` and `stats`. Older rows without it keep working.
5. If the footer says "Saved profile not reachable yet", nothing is written until the profile has loaded.

## Changes in this update (clearer Explore controls)

- **Explore:** "Change" is now **Exploration area**, beside the area summary. It opens a compact inline section
  (closed by default) with only *Places to include*, *Exploration area* and, when needed, *Continent* or *Country*.
  Changes apply immediately to the same shared preferences Settings uses, so Explore, Learn, quiz setup and Settings
  always agree. After a change Explore returns to page 1 with its search/continent/status filters cleared, and Learn
  moves to a country inside the new area if needed. Search, Continent and Status stay visible.
- **☰ Settings** keeps profile, sign-in, language, sound and the same exploration choices. Its accessible name is
  "Settings" (translated). Opening it closes the inline section, so the controls never appear twice.
- **Quiz:** "Change" is now **Quiz settings**. It opens quiz setup and keeps an unfinished round (unchanged protection).

## Earlier: automatic light/dark appearance

- **Cause of the tester's issue:** without `.streamlit/config.toml` on the server, Streamlit followed the phone's
  dark mode for its own widgets (segmented buttons, expander headers) while our stylesheet kept a light page with
  navy text — dark text on dark controls.
- **Now:** `config.toml` defines a light and a dark theme, so Streamlit follows the device setting ("System"),
  reacts to changes while the app is open, and lets visitors choose Light or Dark in the ⋮ menu (toolbar mode
  `viewer`: appearance and print only, no developer tools). A small script mirrors Streamlit's *active* theme onto
  the page (`<html data-we-theme>`), and `assets/styles.css` switches its colour tokens with it, so custom cards
  and native widgets always match, including an explicit Light/Dark choice.
- **Dark palette:** deep navy page, lighter navy cards and inputs, off-white text, lighter muted captions, teal
  accents, restrained gold highlights, stronger borders and gold focus rings. Flags, photos, medals and illustrations
  keep their colours (no inversion). Correct/wrong answers keep their ✓/✕ symbols and words.
- **Contrast:** every visible text element measured ≥ 4.9:1 in both modes; input borders, focus rings, switches and
  progress bars ≥ 3:1. Light-mode input borders and focus rings were darkened to reach 3:1.

## Earlier: shorter Learn page

- **Removed** the three "Test yourself" cards (they repeated the facts below). "Quiz me on this country" is unchanged.
- **Phones and tablets (up to 1024 px):** a small flag beside the country name and one continent/region line; the
  large flag/photo panel and the top Previous/Next row are hidden. Four fact tiles (capital roles, currencies,
  languages with official status or wide use, total area) in as many columns as fit, one column on very narrow
  screens. Neighbours, Landmarks, Compare country size and **More details** (official name, country code, calling
  codes and domains, head of state, sources) start collapsed. Surprise me sits beside the country menu; Previous and
  Next stay at the bottom, in the normal page flow.
- **Desktop:** heading, photo/flag panel, six tiles, neighbours, landmarks and source lines look as before; only
  Surprise me moved beside the menu. A small script opens the Neighbours and Landmarks sections on screens wider than
  1024 px so they read as plain sections; without JavaScript they stay collapsible.
- Default Learn page at 390 px: 2,146 px → 1,158 px tall (−46 %); at 768 px it now fits one screen.

## Earlier: interactive Learn

- **Navigation:** Previous, Next and Surprise me under the country menu (Previous and Next also at the bottom). They
  follow the dropdown order (alphabetical) within your exploration area and wrap round at the ends; a country opened
  from outside the area returns to it. Surprise me always picks a different country. With only one country in the
  area the buttons are disabled and a note says why. Changing country never touches an unfinished quiz round.
- **Neighbours:** flag buttons with translated names replace the sentence; tapping one opens it and the menu follows.
  Neighbours left out by your *Places to include* setting (for example Gibraltar for Spain) are named with a note on
  how to include them — the setting is never changed for you. Places without land borders say so.
- **Test yourself** cards (later removed again, see above).
- **Compare country size** (collapsed): choose a reference country to see both total areas, two proportional bars
  and the ratio in words. Same country, a missing area and very small areas are handled explicitly. The choice is
  remembered for the session and saved with signed-in profiles (new `size_reference` field; older profiles start
  with none).
- On phones the Learn banner is hidden and the flag sits above the name; on tablets the fact tiles stay in two columns.

## Earlier: quiz experience

- **Category colours:** each question category has a restrained accent (chip, card edge, progress bar) with an icon
  and its name; text contrast is at least 4.5:1.
- **Answer feedback:** a short pop for the correct answer and a small nudge for a wrong one, shown once per answer
  (never on reruns) and switched off when the device asks for reduced motion. The correct answer is only shown
  after submitting. Flags are larger (up to 220 px tall on desktop, 150 px on phones) without cropping.
- **Streaks:** see *Scoring rules*. The points, multiplier and breakdown appear after each answer.
- **Did you know?** One extra sourced fact from the bundled data after each answer. It never repeats the fact just
  tested or any fact a later question in the round asks about.
- **Results:** accuracy with a medal, best streak, score record for the same settings, streak record, a short
  perfect-round celebration (and tone, if sound is on), and the closest unearned badge with a practice button.
- **Phones:** short answers sit two per row, the quiz banner is hidden during rounds, and the round bar and score
  strip are slimmer, so an answered question is shorter than before even with the new feedback.
- Records are saved with signed-in profiles (new `records` field, older profiles load with empty records).

## Earlier: compact layout

- **Explore, desktop:** 7 countries per page. Row 1 shows three countries and the "Your next challenge" card;
  row 2 shows countries four to seven, so the seventh sits directly under the challenge card. All cards share one
  width and each row shares one height. Search and filters span the full width above, and pagination sits beneath
  the whole layout. Every country is reachable exactly once through the pages, with or without filters.
- **Explore, phones:** a one-line featured banner, so search sits near the top. Each country is a compact row
  (small flag, name, capital, Discover), and the quiz card comes after the list and pagination. The same cards are
  re-arranged with CSS; nothing is rendered twice.
- **Badges:** a short heading and one row of points, rounds and badges. Earned badges come first, then the three
  goals closest to completion; the rest are under "See all badges". Each badge appears once. Opening the list
  changes no progress. Progress bars are teal even without the theme file. Compact rows on phones.
- **Learn, quiz setup, Settings on phones:** slimmer banners, a smaller flag panel, two-column fact tiles, side-by-side
  quiz dropdowns from 360 px wide, and tighter Settings spacing. Header clearance and Settings scrolling are unchanged.

## Earlier changes

- **Look:** switches, sliders, progress bars and the review toggle use the teal palette even when
  `.streamlit/config.toml` is missing; inputs and dropdowns have a white fill and warm border;
  "Flag questions" replaces the truncated label (all four languages); the tagline hides below 900 px;
  navigation labels never truncate (German/Spanish checked down to 300 px wide).
- **Phones:** compact country rows on Explore with search and filters side by side; slimmer banners on
  Explore, Quiz, Learn and Badges; the "next challenge" card stays below the country list; the Next
  button sits above Streamlit Cloud's corner badges; result numbers stay in one row.
- **Quiz setup:** grouped into "What to practise" and "Where" (with a summary of the selected area);
  choices are remembered when you leave the Quiz page and come back.
- **Learn:** "Quiz me on this country" opens quiz setup with that country (an unfinished round is kept,
  with a clear note); photo or a continent-tinted flag panel on the right; facts and sources unchanged.
- **Badges:** 14 badges (the original 3 unchanged) with requirements and progress bars, earned only from
  recorded answers and finished rounds; new statistics are saved with signed-in profiles
  (older profiles load with empty statistics and keep their points and rounds).
