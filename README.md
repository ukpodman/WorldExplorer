# World Explorer

Learn about every country and take a geography quiz in English, German, Spanish, Chinese or Russian. The
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
  daily.py                 Daily Challenge, day streak and "Practise mistakes" (pure Python)
  analytics.py             pilot measurement: consent, pseudonymous ids, deduplicated events, feedback storage
  metrics.py               pilot metric definitions and calculations for the owner dashboard (pure Python)
  cookies.py               the small first-party cookies (read on the server, written by a tiny script)
  rewards.py               rewards pilot rules: amounts, caps, Nigeria days, referrals, budget, fraud signals
  rewards_store.py         rewards storage: Supabase REST (server only) and an in-memory preview store
  facts.py                 the sourced "Did you know?" fact after each answer
  learn.py                 Learn helpers: country stepping, neighbours by collection, size comparison
ui/
  state.py                 session state and round callbacks
  components.py            header, hero, settings drawer (profile, sign-in help, places, sound)
  pages.py                 Explore, Learn, Quiz, Badges
  world_map.py             interactive continent map on Explore (custom component, bundled outlines)
  owner.py                 private owner dashboard (server-side owner check)
  owner_rewards.py         owner "💰 Rewards & Referral Management" tab
  rewards_page.py          💰 My Rewards page (join, month, payments, invitation link)
  rewards_hooks.py         rewards switches, referral capture and the small activity hooks
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
  world_map.json           continent outlines for the Explore map (Natural Earth, public domain; generated)
supabase/rewards_schema.sql  rewards tables, rules, functions and access (run once in Supabase; see REWARDS_SETUP.md)
tests/                     test_core.py (logic), test_app.py (real Streamlit AppTest), test_rewards*.py
tools/                     rebuild data/countries.json, flags.json, world_map.json and COVERAGE.md
```

## Tests

```bash
python -m unittest discover tests
```
`test_core.py` needs only Python. `test_app.py`, `test_analytics.py` (measurement, owner access, guest → account)
and `test_reliability.py` (answer timing, signed-in profiles, save/load failures) run the real app with Streamlit's
AppTest against simulated Google and Supabase stand-ins; they are skipped if Streamlit is not installed.
`test_rewards.py` also runs the rewards SQL on a throwaway local PostgreSQL when one is installed (skipped otherwise);
`test_rewards_app.py` drives the rewards pages with simulated Google identities.

## Updating data

1. `git clone https://github.com/mledoze/countries` (any location).
2. Edit corrections in `data/reference/curation.json` if needed (each entry records its reason).
3. `python tools/build_countries.py <clone>`, then `python tools/render_flags.py <clone>`
   (needs Playwright + Chromium), then `python tools/write_coverage_md.py`.
4. Run the tests.

**Explore map:** `assets/world_map.json` is built from Natural Earth's 1:50m *Admin 0 – Countries* file
(public domain): `python tools/build_world_map.py <path to ne_50m_admin_0_countries.geojson>` (from
`github.com/nvkelso/natural-earth-vector`, folder `geojson/`). Every outline is coloured by the continent in
`data/countries.json`, so rebuild the map after rebuilding the countries.

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

The pilot measurement and feedback tables are separate from player progress; their SQL and the secrets section
that switches them on are in `SETUP_ANALYTICS.md`.

## Sounds

Sound effects are off by default (☰ Settings → Sound effects, with volume and preview). The tones
are generated in Python (`ui/sound.py`), so no third-party audio files or licences are involved.
Each sound plays once, never on reruns. If the browser blocks sound, nothing breaks, and every
sound has an on-screen message too.

## Licences

Country data: [mledoze/countries](https://github.com/mledoze/countries), ODbL 1.0. The adapted
database in `data/` is distributed under the same licence. Flags come from the same repository
but are not covered by the ODbL (see `COVERAGE.md`). Photo credits are listed in the app and in
`data/photos.json`. Landmarks link to the UNESCO World Heritage List. Map outlines: [Natural Earth](https://www.naturalearthdata.com/)
(public domain; "Made with Natural Earth"), simplified for the Explore map.

## Scoring rules

| Part | Rule |
|---|---|
| Base points | 100 × difficulty (Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2), for a correct answer |
| Streak multiplier | Consecutive correct answers in the current round: 1st–2nd ×1, 3rd–4th ×2, 5th onward ×3. Only the base points are multiplied |
| Streak reset | A wrong answer or a timeout resets the streak to 0. Every new round starts at 0. (There is no skip button; leaving the page keeps the round and the streak.) |
| Speed bonus | Timed rounds only: +25 (flat, not multiplied) for answering within a third of the time limit. Untimed rounds give no speed points (since the 2026-10 pilot update; see below) |
| Hint | −25 (flat) from that answer, applied after multiplying. A hinted correct answer still continues the streak |
| Question total | `max(0, base × multiplier + speed − hint)`; wrong and timed-out answers score 0 |
| Perfect round | +250 × difficulty when every answer is correct and no hint was used. Never multiplied by the streak |
| Medals | Accuracy only: gold ≥ 90 %, silver ≥ 70 %, bronze ≥ 50 %, otherwise "Keep practising" |
| Score records | Compared only with rounds of identical settings: places, area, category, difficulty, question count, timed or not, and (for Mixed) flag questions on/off. Untimed rounds scored after the speed-points change have their own records; earlier untimed records stay saved and are named on the results screen |
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

## Header account bar and Rewards page cards (2026-10-14)

* **Header:** row 1 is the logo and Explore · Learn · Quiz · Badges. Row 2 is a compact account bar on the right:
  **🔑 Sign in with Google** for visitors (the existing Google sign-in; guest progress and invitation links are kept),
  or the signed-in person's photo and name with a small **💰 Rewards** button, then ☰. On phones: logo and ☰, then the
  account bar (full-width Sign in, or photo + name with 💰 Rewards on the right), then the navigation. Long names are
  shortened with "…". "All countries" is no longer shown beside the name (the exploration area setting is unchanged).
* 💰 Rewards keeps the same visibility rules: owners and testers while the programme is off; signed-in people once it is
  on (still also under Settings).
* **My Rewards:** four separate reward cards (title, description, amount on their own lines; two per row on wider
  screens, one per row on phones), the monthly limit below them, and clearer Join, progress and Invite sections. The
  test warning now reads "Test mode — rewards are not payable."
* **Styles after a deploy:** the stylesheet cache is now keyed by the file's version, so new styles appear after an
  update without rebooting the app. (Before, an updated styles.css could stay cached until a reboot, which made new
  pieces such as the reward rows and the 💰 button appear unstyled.)

## Referral & monthly rewards pilot (2026-10-13) — switched off

* Built in but **off**: with the default secrets nobody sees it and nothing is recorded. Setup, launch steps,
  earning rules and what still needs live checking are in **REWARDS_SETUP.md**.
* **People (when switched on):** a compact 💰 button beside ☰ (and Settings → 💰 Rewards) opens My Rewards. Joining
  is optional (18+, lives in Nigeria, accepts the rules; self-declared = provisional until verified). The page shows
  this month's ₦ / ₦1,000 with the four categories, remaining amount, how to earn more, payment status by month, a
  permanent invitation link with copy and WhatsApp share, and invitation history.
* **Owner:** Owner dashboard → "💰 Rewards & Referral Management": user, referral, financial and fraud figures; budget
  and waiting list; participant search with full activity history; manual payments (approve → paid, with date,
  reference, remarks); referral validation; settings and pause; audit log; CSV exports.
* **Small hooks only:** a finished quiz (state.next_question) and meaningful country interactions on Explore and
  Learn call the rewards hooks, which return at once when the programme does not apply. Quiz, exploration, badges,
  sign-in and saved progress behave as before. A `?ref=CODE` link is kept through Google sign-in with the `we_ref`
  cookie.
* Server-side only: amounts are decided by the database; the server key never reaches the browser.

## Explore: one exploration box (2026-10-12)

* **Top bar:** your real day streak, points and badges, and the Daily Challenge (Start / Continue / Replay).
* **World map:** the map fills the box (ocean names, continent emblems), with pills underneath: "All continents" and the
  six continents. Tapping a continent on the map or its pill does the same.
* **A continent:** the map is replaced in the same box. Left: "← World map | Africa" with the count, "Search Africa…",
  a filter icon (status and places to include), the country list (flag, name, capital, ›; the whole row is the button)
  and "‹ Previous 1/6 Next ›". Right: the chosen country with its flag, region, photo (where one is bundled), capital,
  currency, languages, area, Neighbours and Landmarks, and "Quiz Nigeria" (plus "Learn about Nigeria"). Before a
  country is chosen, the right side shows the continent's real badge progress and "Quiz Africa".
* **Phones:** the same journey, one panel at a time in the box: map → list → country; "← Countries of Africa" returns
  to the list with the country still highlighted; "← World map" returns to the map.
* Switching continents clears the search, status filter, page and chosen country; places to include are kept. After
  Learn or a quiz, Explore comes back to the same continent, search, page and country. Places to include is the same
  preference as in Settings; the exploration area stays in Settings and widens (with a notice) if it would hide the
  continent you open. Nothing here starts a quiz or touches an unfinished round.
* **Map data:** Natural Earth 1:50m country outlines (public domain), simplified and bundled in
  `assets/world_map.json`; colours follow the continents in `data/countries.json` (Russia with Europe, Türkiye and
  Kazakhstan with Asia). The outlines (about 100 kB) are sent once per browser session.
* **Russian (Русский)** is the fifth language: every interface string, with Russian plural forms. Country names come
  from the same dataset translations as the other languages; capitals, currencies, languages and regions in facts keep
  the dataset spelling, as in German, Spanish and Chinese. Missing translations fall back to English.
* No new scoring rules, no exploration percentages, no setup changes.

## Pilot update (measurement, timing fix, easier first use)

**Rollback.**
* The working version before this update is commit `82c6293`, tagged `checkpoint-before-pilot-update`.
* The same files are in `WorldExplorer_backup_before_pilot_update.zip`.
* To restore, upload that ZIP's files to GitHub as usual, or run
  `git checkout checkpoint-before-pilot-update -- .` and then commit.
* No database or secrets change is needed to roll back. The two analytics tables can stay; nothing reads them.

### Stage 1 — Measurement (off until you set it up: see SETUP_ANALYTICS.md)

Nothing is recorded until the visitor allows it (consent bar, or Settings → Privacy). Each event is recorded
once per person and round or session, and failures are silent.

**Events recorded**
* `visit` (once per browser session)
* `round_start` and `round_complete`, each with a mode:
  * `regular`: a round started from quiz setup
  * `daily`: the first counted Daily Challenge attempt of that day
  * `daily_replay`: a Daily Challenge replay
  * `practice`: a Practise mistakes round
* `link`: a guest id joined to the account after sign-in
* an anonymous `consent_declined` tally

**Identifiers**
* Guests: a random id in the `we_aid` cookie, kept across refreshes in the same browser.
* Signed-in players: a salted one-way hash of the profile id.
* No fingerprinting.
* The limits of guest identity across devices, cleared storage, private windows and Safari's 7-day cookie cap
  are in SETUP_ANALYTICS.md.

**Owner dashboard**
* Opened from ☰ Settings → Privacy → Owner dashboard.
* Only for signed-in Google accounts whose verified email is in `[analytics] owner_emails`.
* The check runs on the server on every load. Anyone else gets "This page is not available" and no data.
* Owner and test traffic is excluded by default; see SETUP_ANALYTICS.md §4.

**Metric definitions.** All days are UTC calendar days, the same as the Daily Challenge. Every rate is shown as
"n of d" next to the percentage.

| Metric | Numerator | Denominator / scope |
|---|---|---|
| Measured people | distinct pseudonymous ids (a guest id that later signed in is merged into that account) | all data; only visitors who allowed statistics |
| New visitors | people whose first event falls in the selected period (7 days, 28 days or all) | count |
| Returning visitors | people active in the period on a UTC day after the day they were first seen | count |
| Quiz starts / completions | `round_start` / `round_complete` events in the period, by mode, plus distinct people | counts |
| Daily Challenge first counted completions | completed rounds of mode `daily`, plus distinct person-days | counts |
| First-round completion | people whose first started round (any mode except replay) was completed | people who started a first round; first rounds started in the last hour are pending and left out |
| Return within 7 days | people with any event on a later UTC day within 7×24 h after their first completed round | people whose first completed round was at least 7×24 h ago (full window elapsed); the rest are shown as "still in window" |
| Active on 3+ days | people with events on at least three distinct UTC days | all measured people |
| Signed-in vs guest | people with any signed-in event / the rest | all measured people |
| "No thanks" answers | anonymous count of declined statistics prompts | period |

### Stage 2 — Answer timing and speed points (bug fixed)

**The bug.** The answer clock only started the first time code read it.
* In timed rounds the countdown read it when the question appeared, so timing was right.
* Untimed rounds have no countdown, so the first read happened when the answer was submitted. Every untimed
  answer therefore took 0.0 s.
* As a result, every correct untimed answer received the +25 speed bonus, and the "average response time" was
  always 0.0.

**The fix.**
* The clock now starts when the question is shown, in every round (`engine.mark_presented`).
* Untimed rounds pause the clock while the question is off screen (another page, quiz setup, or a round set
  aside).
* Timed rounds keep running as before, so leaving the page cannot buy extra time.

**Decision on speed points.**
* Speed points now apply only in timed rounds. Untimed rounds (including the Daily Challenge) are for reading and
  learning at your own pace, and everyone's Daily Challenge is scored the same way.
* Saved points, badges and earlier records are not recalculated.
* Untimed rounds get new record entries, so a new score is never compared with an older one that included the
  automatic bonus. The results screen shows the earlier best.

### Stage 3 — Interface

* **Explore:** the banner is now one invitation, "Five questions. Discover something new every day.", with
  Start, Continue or Replay for today's challenge, plus "Discover {country}" on tablets and desktops.
  * The grid card is "Take a quiz", so there is no second challenge card.
  * On phones the banner shows one button and the country list follows directly.
* **Active quiz:** no decorative banner during a round. The score, streak and hints sit in a compact one-line
  strip, so the question and answers start higher on the screen. Category colours, explanations, sources and
  the correct/incorrect states are unchanged.
* **Save progress:** after a guest's first completed round, the results show "Save your progress with Google"
  and "Continue as guest".
  * Clicking keeps the guest's progress on the server for 30 minutes (cookie `we_handoff`). It stays there until
    the account save that includes it succeeds, so a failed save can be recovered by a retry or a refresh.
  * The saved profile records a one-way transfer id (`transfers`). Retries, a repeated sign-in and several open
    tabs therefore never add the progress twice. Before writing, a save that includes the progress reads the
    profile again: if another tab already saved the transfer, it uses that result; if the profile changed in the
    meantime, it adds the guest progress to the fresh copy.
  * After Google's page, the progress is added to the account:
    * points, rounds and statistics add up;
    * records keep the higher value;
    * daily days are combined, and a saved day keeps its saved result;
    * the day streak continues;
    * an existing saved profile is never replaced.
  * A one-time message says what was added. The same two-step flow applies to the sign-in button in Settings.
* **Feedback:** "Send feedback" in the footer (shown once SETUP_ANALYTICS.md is done) asks for page, device type,
  a description and optional contact details. It says exactly what is sent, and never sends quiz history or
  account details.

## Fixes before upload (2026-10-11)

The working version before these fixes is the pilot update (commit `d8424e2`). It is tagged
`checkpoint-before-consent-handoff-fix` and saved in `WorldExplorer_backup_before_consent_handoff_fix.zip`.

* **Guest progress transfer:** the hand-off is no longer used up before the account save succeeds. It is
  recoverable after a failed save (retry or refresh), and idempotent through a one-way transfer id saved in the
  profile. A failed save, a refresh, recovery, a repeated sign-in and concurrent tabs each add the progress
  exactly once.
* **Play during a pending transfer:** points, rounds and answer statistics earned while the transfer save is
  still failing are kept when the save is retried. This holds whether another tab saved the transfer first or
  the saved profile changed in the meantime. Retries after repeated failures never count anything twice.
* **Consent:**
  * "No thanks" in one tab now stops measurement in every open tab of the browser without a reload (and in the
    person's other signed-in sessions).
  * Events already waiting in the background queue are checked again and dropped.
  * Global Privacy Control now wins over an earlier "Allow": nothing is recorded, the id cookie is removed and
    the Settings switch is locked off.
  * The privacy wording in Settings and in SETUP_ANALYTICS.md describes exactly this.

## Earlier: daily results after midnight UTC

- The daily results card now looks up the saved result by the round's own date (`quiz["day"]`), not by today's date.
  Reopening yesterday's replay (or counted round) after midnight UTC no longer crashes, and yesterday's score is never
  labelled as today's: replays say "Saved result for {date}", a counted round from an earlier day says "Your result
  for {date} is saved", and the share line uses the round's date. A missing saved result shows a short note and no
  share line. Today's challenge (Start / Continue / Replay, next start time) is still decided separately.
- After midnight the results button offers the new day's challenge (which counts) instead of a practice replay.
  A kept daily round from an earlier day is labelled "Return to the daily challenge of {date}".
- If an earlier day is finished after a later one, its result is saved but the day streak never moves backwards.

## Earlier: Daily Challenge, day streak, Practise mistakes

- **Daily Challenge:** 5 questions a day, the same for everyone: Mixed categories at Medium, all UN member and
  observer states, generated by the normal quiz engine with a seed taken from the date (no random state, no
  recently-asked filtering). Heads-of-state questions are left out, because their records can change during a day.
  The day changes at **midnight UTC**; the app says so and shows when the next challenge starts.
- **Where to start it:** the challenge card on Explore (*Today's challenge* / *Continue* / *Replay*) and a compact box on
  quiz setup (above the setup on phones; above the banner, beside the setup, on tablets and desktops).
- **Only the first completed attempt counts** for points, rounds, badge statistics, records and the day streak.
  Replays are labelled *practice replay* and change nothing (no points, records, badge statistics or mistakes).
  Daily and practice rounds keep their own record entries, so they never overwrite regular-round records.
- **Rounds are never lost:** starting the daily challenge keeps an unfinished regular round (and the other way round);
  quiz setup and the results screen offer *Return to …* buttons for kept rounds.
- **Day streak:** completing today after yesterday adds 1; a missed day starts again at 1. Current streak on Badges,
  best streak and number of completed challenges below it. The results card shows a share line without answers,
  e.g. `World Explorer · Daily 2026-10-10 · 3/5 🟩🟥🟩🟩🟥 · 🔥 4`, with a copy button.
- **Practise mistakes:** wrong or timed-out answers are kept as a deduplicated list of facts (newest 40). *Practise
  mistakes (N)* on the results screen and Badges builds a round of fresh questions (new answer options) for up to 10
  of them; facts that can no longer be asked are skipped; a correct answer to any question about the same fact
  removes it.
- **Saving:** `daily` and `mistakes` are stored with the signed-in profile like the other progress fields. Old profiles
  without them load with empty defaults; invalid values are dropped. The existing rule still applies: a profile is never
  written after a failed read. Guests keep this for the browser session only.
- **Layout:** Explore is no taller than before on phones (the two challenge buttons sit side by side); on narrow tablet
  cards the status line is left out. On phones quiz setup grows by about 50 px (the decorative "Your next adventure"
  line is hidden there); on tablets and desktops quiz setup is unchanged or shorter. Touch targets are at least 44 px
  (also the *Quiz settings* button in the round bar and the card buttons on touch screens). The wrapped switches on
  tablet quiz setup no longer leave a large gap.

## Earlier: clearer Explore controls

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
