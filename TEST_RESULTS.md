# Automated test results: School Learning expansion, Nigerian History and Citizenship and Heritage Studies (26 October 2026)

**Command:** `python -m unittest discover tests` (the complete suite), branch `school-learning` (base `fa4fa08`). Local only:
no Supabase project, GitHub or Streamlit deployment was used, and no SQL migration was run.

| Run | Tests | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| A. With `supabase/pilot_invitations_migration.sql` in the checkout | 803 | 803 | 0 | 0 | 0 |
| B. The GitHub branch as it is (that file missing) | 803 | 716 | 0 | 0 | 87 |

**Raw results:**
- Run A: `Ran 803 tests in 627.498s — OK`
- Run B: `Ran 803 tests in 478.762s — OK (skipped=87)`

The 87 skipped tests in run B are the PostgreSQL rule tests for Founding 50 and Friends & Family 10, as before.

**Two problems found and fixed during testing:**
- One new assertion depended on an exception class that another test module reloads. It now checks for `ValueError`, the
  parent class.
- One existing quiz test (`test_app.RefinementTests.test_practise_mistakes_round_clears_correct_answers`) failed once in an
  earlier full run of B. It passed 10 times out of 10 on its own, both with and without this patch, and passed in both final full
  runs. It is a random-order quiz test that School Learning does not touch.

## New: `tests/test_school_interactive.py` (38 tests)

| Area | What is checked |
|---|---|
| Curriculum metadata | Both subjects are available and interactive. Primary 1–6, JSS 1–3 and SSS 1–3 are listed with valid term ids. Every topic is labelled `scheme`, never `official`. SSS 2 and SSS 3 have no invented topics and keep an honest note. No WASSCE, WAEC or examination-preparation wording appears for Citizenship and Heritage Studies. No "approved/endorsed by NERDC" claims appear anywhere. |
| Content validation | The three lessons validate; they have parts A–K, at least two activities and varied assessments; together they use all 9 question types and all 6 activity types. Stories contain no dialogue or quotation marks. Approximate dates are worded as estimates. The map says it shows modern Nigeria only. Nine kinds of broken lesson are rejected. Unknown lessons and empty classes are handled safely. |
| Assessment scoring | Right and wrong explanations for every type. Fill-in answers are normalised. Matching and ordering give per-item feedback. Scenario verdicts are checked. Written answers are never auto-marked. An answer cannot be recorded twice. Tallies count marked questions only, and scores are scaled to 10. |
| Progress | Knowledge-check results use the existing record fields only (no new database columns). Progress is reported by class and term, with a suggested next lesson. Read-aloud text contains no markup. |
| Device storage | One cookie now holds several subjects (v2), and old v1 cookies are still read. When space runs short, the newest progress is kept. |
| Geography compatibility | Geography's 7 lessons, page structure, 34 topics and WAEC label are unchanged, and the Geography lesson and practice flow still works. |
| Separation from rewards | No school module imports or calls rewards, Friends & Family 10, quiz, badge or points code. In the running app, the reward hooks are replaced with stand-ins and never called during study. Points, badges, quiz and streak state are unchanged. |
| Accessibility and mobile | Read-aloud never autoplays: it starts only from a button, has Listen, Pause, Resume, Restart and Stop, and announces its state. Nothing uses drag and drop; ordering uses Move up and Move down buttons. Phone layout rules are present. |
| App (Streamlit AppTest) | The home page shows three cards with Continue and Explore buttons and no "Coming soon". Class and term navigation works, including empty classes, "Term not confirmed" and incomplete topics. A full Primary 4 lesson and knowledge check runs end to end and is recorded. The JSS timeline, matching, story and investigation activities work. Ordering works with buttons only. The SSS scenarios and institution explorer work, and "Knowledge check" opens that page. Continue learning and device storage work for guests. |

Updated: `tests/test_school.py`. Its two assertions that the new subjects were "planned" now expect them to be available, and
the subject search now finds Citizenship and Heritage Studies.

---

# Automated test results: Friends & Family 10 private documents, approval record and acceptance (25 October 2026)

**Command:** `python -m unittest discover tests` (the complete suite)
**Code tested:** the real-cash patch (`932e362`) plus this update. These are local databases with every migration
loaded, including the proposed acceptance migration; your Supabase project was not used.

| Run | Tests | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| A. With `supabase/pilot_invitations_migration.sql` in the checkout (every database rule on real PostgreSQL) | 765 | 765 | 0 | 0 | 0 |
| B. Your GitHub branch as it is (that file missing) | 765 | 678 | 0 | 0 | 87 |

**Raw results:**
- Run A: `Ran 765 tests in 823.812s — OK`
- Run B: `Ran 765 tests in 623.808s — OK (skipped=87)`

The 87 skipped tests in run B are the PostgreSQL rule tests: 46 in Founding 50 and 41 in Friends & Family 10.

## New in this update

- **`test_legal`** (the pilot's own documents and approval record):
  - `test_pilot_track_is_independent_of_the_general_documents`;
  - `test_approval_record_must_match_every_document_exactly`: covers a missing or placeholder decision-maker, a
    missing or future date, and a wrong version or checksum for either document;
  - `test_approval_record_is_shown_in_the_status`;
  - `test_missing_pilot_approval_record_is_reported`.

  Updated: the outstanding-requirements checklist now names the pilot's own documents and the approval record.
- **`test_ff10`** (memory and PostgreSQL):
  - `test_new_terms_must_be_accepted_before_earning_again`: after the owner records new terms, learning is refused
    (and beneficiary checks too) until the participant accepts exactly the current version. Old versions are refused,
    and acceptances are audited and kept.
  - `test_only_approved_invited_participants_can_accept`.
- **`test_ff10_app`:**
  - `test_participants_accept_updated_terms_before_earning`: the participant sees both approved documents with
    "Approved by … on …". Quiz answers are not recorded until they accept; after accepting, the progress card returns.
  - `test_owner_sees_the_approval_record_and_the_10_place_counter`: shows the decision-maker, date and both
    checksums, "1 / 10 approved", no "/ 50", and the public tabs marked "Public (OFF)".

## Earlier: the real-cash patch

**`tests/test_ff10.py`** (each on the in-memory store and on PostgreSQL):
- `test_payments_need_the_owners_authorisation_and_public_stays_off`: payments are refused until the owner authorises
  them; only the owner can authorise, with a confirmation. Public Rewards, public payouts and withdrawals stay OFF,
  the public ledger still pays ₦0, and the old `pilot_mark_paid` path is closed. Suspending works, and the change is
  audited.
- `test_authorisation_needs_the_recorded_pilot_terms`, and the switch cannot be changed directly.
- `test_recording_a_manual_bank_transfer`: checks the ledger row (beneficiary, bank, last 4 digits, amount, date,
  reference, status, recorded by) and that the line is marked paid. A second payment is refused, the ledger cannot be
  edited or deleted, and a paid line cannot be withheld.
- `test_payment_safeguards`: refuses payments that are not by the owner, not confirmed, to an unverified
  beneficiary, for an unapproved or withheld allocation, for a wrong amount (±₦1), without a reference, dated in the
  future or before the settlement, for a month that is not settled, or with a duplicate reference.
- `test_beneficiary_verification_keeps_only_the_last_four_digits`: a full account number is refused, and
  non-participants are refused.
- `test_full_month_paid_within_the_budget`: 8 participants, ₦56,000 provisional; ₦50,000 is paid in total and never
  more than the settlement.
- `test_concurrent_payment_attempts_pay_once`

**`tests/test_ff10_app.py`:**
- `test_owner_authorises_verifies_and_records_a_bank_transfer`: the full owner flow in the app, through the ledger and
  the participant's "Paid by bank transfer" status.
- `test_payments_cannot_be_authorised_without_the_legal_requirements`: the readiness checks fail and the authorise
  button stays disabled.

**Updated** for the new real-cash wording (no "not payable" or "payments disabled" statements for the pilot):
`test_ff10_app`, `test_pilot_app`, `test_legal`.

**Unchanged and still passing:** invitation-only access (16-combination matrix), the 10-person limit, settlement
fingerprints, and all educational features.

## Earlier: review corrections (settlement integrity and invitation-only)

**1. Settlement integrity**
- `test_fingerprint_is_the_same_in_the_database_and_in_python`
- `test_regression_changed_individual_allocations_with_the_same_total_over_budget`: one participant's day is
  excluded, the total stays ₦50,000 and every share changes. The old preview is refused (`preview_changed`) and the
  new one settles exactly as previewed.
- `test_regression_amounts_moved_between_participants_within_budget`: ₦250 moves from one participant to another,
  and both totals stay ₦350. The old preview is refused.
- `test_settlement_needs_the_owner_confirmation_an_ended_month_and_the_previewed_allocation` (updated): forged and
  missing fingerprints are refused, and the confirmed fingerprint is stored with the settlement.
- `test_day_review_racing_a_settlement_never_both_succeed`: a settlement and a day review run at the same time.
  Either the settlement wins and the review is refused (`month_settled`), or the review wins and the settlement is
  refused (`preview_changed`).
- `test_day_reviews_wait_for_a_settlement_in_progress` (PostgreSQL only): while the month lock is held, a day review
  waits.

**2. Invitation-only enforcement**
- `test_invitation_matrix_pilot_public_invited_approved`: all 16 combinations of pilot ON/OFF × Public Rewards
  ON/OFF × invited/not invited × approved/not approved. Learning is recorded only for pilot ON + invited + approved.
- `test_public_programme_stays_separate_from_the_pilot`: with Public Rewards ON and public applications allowed, an
  uninvited public applicant is approved under the public programme, beyond the 10 pilot places, but cannot enter
  the pilot. An 11th invited person is refused (`places_full`).
- `test_revoking_an_invitation_stops_recording_at_once`

## Coverage of the 17 required areas

| # | Area | Tests |
|---|---|---|
| 1 | At most 10 approved participants | `test_at_most_ten_approved_participants`, `test_public_programme_stays_separate_from_the_pilot` |
| 2 | Invitation-only access | `test_invitation_matrix_pilot_public_invited_approved`, `test_revoking_an_invitation_stops_recording_at_once`, `test_only_invited_and_approved_participants_are_recorded`, `test_people_who_are_not_approved_see_no_progress`, plus the existing pilot tests |
| 3 | Daily earning calculations | `test_daily_tiers`, `test_new_country_means_never_explored_before`, `TierTests` |
| 4 | Active-learning verification | `ActiveTimeTests`, `test_idle_time_refreshes_and_repeats_add_nothing`, `test_two_tabs_at_once_count_once`, `test_activity_time_comes_from_the_database_clock`, `test_the_app_key_cannot_choose_the_time_or_write_tables` (SQL), `test_quiz_answers_and_learn_navigation_are_recorded_for_participants_only` |
| 5 | ₦500 daily maximum | `test_daily_maximum_and_monthly_maximum`, `test_daily_maximum_message_discourages_more_screen_time` |
| 6 | ₦7,000 monthly maximum | `test_daily_maximum_and_monthly_maximum`, `test_monthly_maximum_cuts_the_last_day_partially`, `test_no_one_receives_more_than_7000` |
| 7 | ₦50,000 shared budget | `test_ten_full_participants_share_50000`, `test_unequal_engagement_rounding_and_zero_activity` |
| 8 | Proportional allocation | `test_ten_participants_at_7000_get_5000_each`, `test_over_budget_allocation_matches_the_python_rule_exactly` |
| 9 | Exact whole-naira rounding | `test_proportional_shares_with_exact_whole_naira_rounding`, `test_ties_are_broken_by_profile_id` |
| 10 | Duplicate reward prevention | `test_regression_changed_individual_allocations_with_the_same_total_over_budget`, `test_regression_amounts_moved_between_participants_within_budget`, `test_idle_time_refreshes_and_repeats_add_nothing`, `test_settlement_needs_the_owner_confirmation_an_ended_month_and_the_previewed_allocation` (already settled), `test_settled_amounts_never_change` |
| 11 | Concurrent activity and settlement | `test_day_review_racing_a_settlement_never_both_succeed`, `test_day_reviews_wait_for_a_settlement_in_progress`, `test_concurrent_identical_interactions_are_recorded_once`, `test_concurrent_settlements_finalise_once` (memory threads; SQL parallel database sessions) |
| 12 | Zero-activity participants | `test_unequal_engagement_rounding_and_zero_activity`, `test_a_single_interaction_or_an_open_page_counts_nothing` |
| 13 | Unused budget | `test_within_budget_everybody_keeps_their_amount_and_the_rest_is_unspent`, `test_unequal_engagement_rounding_and_zero_activity` |
| 14 | Owner approval requirements | `test_owner_approval_of_each_line`, `test_excluded_days_earn_nothing_and_free_the_monthly_maximum`, `test_owner_tab_figures_and_settlement`, `test_owner_excludes_a_suspicious_day` |
| 15 | Public Rewards remain OFF | `test_public_rewards_withdrawals_and_payments_stay_off`, `test_no_ff10_tab_once_public_rewards_are_on` |
| 16 | Payments remain disabled | `test_public_rewards_withdrawals_and_payments_stay_off`, `test_payments_enabled_cannot_be_switched_on`, the "Mark as paid" button disabled in `test_owner_tab_figures_and_settlement` |
| 17 | Existing data and educational features | `test_existing_records_are_untouched`, the educational-points check in `test_quiz_answers_…`, `test_owner_test_records_are_marked_test`, and the complete existing suite (Explore, Learn, Quiz, Badges, photos, School Learning, Google sign-in flows, profiles, Founding 50, withdrawals) |

Security checks on PostgreSQL:
- browser roles have no access;
- the app key cannot choose the activity time or write any Friends & Family 10 table directly;
- the migration can be run again and keeps every record.
