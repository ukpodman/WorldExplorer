# School Learning expansion: Nigerian History and Citizenship and Heritage Studies

Branch `school-learning` (local only; not pushed or deployed). Base: `atlas-explore-dev` @ fa4fa08.

## What changed for students

* **Landing page.** The three subject cards stay. Nigerian History and Citizenship and Heritage Studies are no longer
  "Coming soon", because they now have working lessons. Every card (Geography included) shows:
  * the classes that have lessons;
  * the number of lessons, split honestly into reviewed and draft;
  * the number of curriculum topics listed;
  * a progress bar with completed and started counts;
  * **Continue learning** (**Start learning** before the first lesson) and **Explore subject** buttons.
* **Navigation.** Explore subject → choose a class (Primary 1–6 and JSS 1–3, or SSS 1–3) → choose a term (First, Second, Third, or
  "Term not confirmed" where the schemes do not agree) → topics → lessons.
  * Classes with lessons are marked ●.
  * Topics without a lesson say "Lesson not written yet". Nothing is shown as ready when it is not.
* **Interactive lessons** have parts A–K:
  * A–F: introduction and why it matters, objectives, background, main sections, key people, places and events, cause and effect;
  * G: at least two activities;
  * H–K: key terms, summary, knowledge check, further learning with numbered sources.
  * Labels mark documented facts, oral traditions, interpretations, approximate dates and disputed points.
* **Optional read-aloud.** "🔊 Listen to this page" has Listen, Pause, Resume, Restart and Stop buttons. It uses the
  browser's own voice, never starts by itself and is keyboard accessible.
* **Progress** includes:
  * started and completed lessons;
  * knowledge-check scores (best out of 10; written answers self-checked and not counted);
  * the revision list;
  * recently studied lessons;
  * a table by class and term;
  * a suggested next lesson.
  * Guests can learn without an account. Progress lasts for the visit, or longer on the device if they switch it on. The page says exactly where progress is kept.

## Architecture

```
data/school/subjects.json                   "engine": "interactive" for the two new subjects
data/school/<subject>/curriculum.json      classes → terms → topics (verification + sources) → lesson ids
data/school/<subject>/lessons/<id>.json    one interactive lesson per file (validated JSON, stable ids)
data/school/nigerian-history/figures/      map of modern Nigeria with six sites (labelled and numbered); evidence drawings
core/assess.py        NEW  question engine: mcq, true/false, fill-in, matching, ordering, map, image, scenario, short written
core/lessons.py       NEW  curriculum + lesson loading, validation, pages, read-aloud text, progress by class/term, suggested next
core/school.py        EDITED  dispatches to core/lessons.py for interactive subjects; Geography code paths unchanged
ui/school_interactive.py  NEW  subject card, class/term/topic screens, lesson reader, activities, knowledge check, progress
ui/school.py          EDITED  routes interactive subjects; new card buttons; multi-subject device cookie (v2, still reads v1)
assets/styles.css     EDITED  appended .sx-* styles (navy/teal/ivory, light and dark, phone rules)
tools/build_history_figures.py  NEW  builds the history figures from the Geography base map (Natural Earth, public domain)
```

Reusable components:

| Component | Where | Activity or question type |
|---|---|---|
| Timeline Explorer (exact vs approximate dates) | `_timeline` | `timeline` |
| Kingdom / Site Explorer (modern map for reference only) | `_explorer` | `explorer` |
| Historical Investigation | `_investigation` | `investigation` |
| Arrange the Timeline (Move up / Move down, no drag) | `question` | `order` |
| Interactive Stories (no invented dialogue) | `_story` | `story` |
| Civic Scenarios (non-partisan) | `question` | `scenario` |
| Government Institution Explorer | `_diagram` | `diagram` |
| Rights & Responsibilities Challenge | `question` | `match` + `truefalse` |
| Cultural Heritage Explorer | `_explorer` | `explorer` |
| Assessment engine with explanations | `core/assess.py` + `question`/`feedback` | all nine types |
| Read-aloud | `read_aloud` | — |

The Cultural Heritage Explorer is the same `explorer` component as the Kingdom and Site Explorer, given heritage items.

## What stays protected

* No database migration. Interactive progress uses the existing `school_lesson_progress` columns:
  * page, page_id, furthest, completed, revision, best, last, attempts, answered, correct, version and timestamps;
  * knowledge-check attempts use `school_practice_attempts`, storing question ids and right/wrong only.
* School code imports nothing from rewards, Friends & Family 10, quiz, badges, points or withdrawals, and calls no reward hook.
  Tests check this statically and in the running app (the reward hooks are mocked and must never be called).
* Untouched:
  * the F&F10 application and approval logic, reward calculations and the ₦50,000 budget;
  * the Supabase reward and payment functions, Google sign-in and participant accounts;
  * profiles, quizzes, badges and photos;
  * production.
* Geography is unchanged apart from its card. Its card now shows the same facts and buttons as the others; its button key is still `sl_open_geography`.

## Curriculum position (honest labelling)

* **Official facts.** The Federal Ministry of Education (3 September 2025) made Nigerian History compulsory from Primary 1 to JSS 3. It
  made Citizenship and Heritage Studies a new core SSS subject, from 2025/26. NERDC publishes the subject lists.
* **Topic lists.** The official NERDC topic-level documents were not accessible. Topics come from published schemes of work that
  say they follow the new curriculum, and each topic is labelled "Listed in published schemes of work (not yet checked against the
  official NERDC document)".
* **Citizenship and Heritage Studies.** Only SSS 1 First Term topics are listed, because the schemes disagree. SSS 2 and SSS 3 are
  empty with a note. No examination preparation is advertised.
* **Review status.** All three lessons are **Draft** ("Educational review pending") until a qualified teacher reviews them.
  Only `reviewed`/`published` lessons are presented as finished.

Sources: `data/school/nigerian-history/SOURCES.md`, `data/school/citizenship-heritage/SOURCES.md`.

## Sample lessons (vertical slice)

| Lesson | Class / term | Activities | Knowledge check |
|---|---|---|---|
| `p4-historical-sites`: Historical sites in Nigeria | Primary 4, Third Term | site explorer on the map; match the sites; order the sites | 9 questions: mcq, map ×2, true/false ×2, fill-in, scenario, short |
| `jss1-sources-of-history`: History and its sources | JSS 1, First Term | historical investigation (5 sources A–E); timeline explorer (9 dated events); sort the sources; interactive story: the discovery of Igbo-Ukwu (4 chapters) | 10 questions: mcq, true/false, fill-in, image, order, match, scenario, short |
| `sss1-citizenship`: Citizenship in Nigeria | SSS 1, First Term | civic scenarios (3); rights and responsibilities challenge; government institution explorer | 10 questions: mcq, fill-in, true/false, match, order, scenario, short |

## Content expansion plan

Each step adds JSON files only; no interface or database change.

1. **Get the official documents.** Obtain the NERDC curricula for Nigerian History (Primary 1–JSS 3) and Citizenship and Heritage
   Studies (SSS 1–3) from NERDC or a State Ministry/SUBEB. Compare every topic, and change `verification` to `official`
   only where it matches. Correct terms and topic order. Fill SSS 2 and SSS 3.
2. **Teacher review of the three draft lessons.** A qualified teacher reviews them (content, level, language). Fix the lessons, raise
   `version`, then set `review_status` to `reviewed`.
3. **Cycle-1 classes first.** The revised curriculum starts with Primary 1, Primary 4, JSS 1 and SS 1, so these come first.
   * Wave 1 (next): complete JSS 1 First Term (meaning and importance of history as separate lessons) and SSS 1 First Term
     (qualities of a good citizen, national symbols, human rights, rule of law).
   * Wave 2: Primary 4 (all terms) and Primary 1 (simpler primary format).
   * Wave 3: JSS 1 Second and Third Terms: Nok, Ife, Benin, Igbo-Ukwu, Kanem-Borno and Hausa states. Use the kingdom explorer
     with modern-map caveats and the timeline explorer.
   * Wave 4: the remaining classes as their cycles begin.
4. **Per lesson:**
   * Write the lesson from checked sources, labelling facts, traditions, interpretations and approximate dates.
   * Validate it with `python -m unittest tests.test_school_interactive`.
   * Add its sources to SOURCES.md.
   * Keep it Draft until reviewed.
5. **Figures.** Add maps or drawings through `tools/build_history_figures.py`. Kingdom maps must show modern Nigeria for reference
   only. Do not draw historical boundaries unless they come from a cited scholarly map.

Out of scope for now: audio files and translations (read-aloud uses the browser's voice), and teacher accounts.
