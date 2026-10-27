# Friends & Family 10 — verified active learning time (branch: ff10-active-time)

NOT deployed. No SQL executed. Payments, Public Rewards, approvals, balances and existing records untouched.

## Cause (confirmed in the code)
* Verified time = the gaps between consecutive recorded interactions, each counted up to 180 s
  (`core/pilot_rewards.active_seconds`, SQL `pilot_month_ledger`). A longer pause counts 3 minutes, never more.
* Only five clicks are recorded (`ui/rewards_hooks.ping`): quiz answer, finished quiz, Daily Challenge, country opened,
  country details/expander opened. Reading a Learn page, studying the map or photos, reading quiz explanations and
  scrolling record NOTHING. Opening the same country again within 10 minutes is ignored (repeat rule).
* 27 Oct: 38 short gaps = 5.2 min, plus one 36.6-min pause counted as 3 min → 8.2 min (8 whole minutes) → ₦0.
  26 Oct: 3.4 min of short gaps + 2 × 3 min → 9.4 min. Nothing was lost or miscounted: the pauses had no events.
* Recording is fire-and-forget (errors swallowed), so a network failure also shows up as a longer pause.
* Duplicate events and Streamlit reruns are already safe (repeat rule; one per-day timeline; database clock).

## Fix
* `ui/ff10_heartbeat.py` (new): for participants only, on Explore, World Geography Learn and World Geography quizzes
  (≥5 questions; never School Learning). The page sends one activity check per minute only while the page is visible
  and focused AND a real scroll/touch/key/click happened in the last 75 s (synthetic events and mouse movement ignored).
  Runs in a fragment: no full-page reruns.
* Database (`pilot_record_heartbeat`) decides: own clock; ≤1 accepted check per 50 s per person (tabs/devices/reruns);
  only within 15 minutes after a meaningful interaction the same day; ≤150 per day; same participant/pilot/settled-month
  checks as interactions. Lost checks are never replayed.
* Accepted checks join the same day timeline; the 180 s rule, tiers and all caps are unchanged. Days without checks
  (every historical day) give exactly the same result. Checks alone never earn: quizzes are still required.
* Participant card: verified minutes, qualifying quizzes x/2, reading minutes verified by checks, next milestone, and
  the minutes not counted with the reason.
* Owner → Friends & Family 10 → participant → "Learning-time audit (read-only)": 26–27 Oct by default; elapsed vs verified,
  every pause > 3 min with what came before/after, CSV. It changes nothing; no automatic conversion to rewards.

## Migration (proposed, run only after approval)
`supabase/friends_family10_active_time_migration.sql` — new table `pilot_heartbeats`, two functions, `pilot_month_ledger`
replaced with the same signature. Rollback: `supabase/friends_family10_active_time_rollback.sql`.
Until it is installed the app sends no checks and behaves exactly as now.
Order: install migration → deploy code to the Atlas preview → test on iPhone (Safari) → production.
