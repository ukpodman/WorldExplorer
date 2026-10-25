# Automated test results: Friends & Family 10, review corrections (25 October 2026)

**Command:** `python -m unittest discover tests` (the complete suite)
**Code tested:** `atlas-pilot-consolidated` @ `b4fc727`, plus the corrections package (`d8e121b`), plus the
Friends & Family 10 package (`35e966d`), plus these review corrections.
**Environment:** Python 3.13, Streamlit 1.65, and a local PostgreSQL 16 for the database-rule tests. These are
throwaway local databases; your Supabase project was not used and no migration was run on it.

| Run | Tests | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| A. With `supabase/pilot_invitations_migration.sql` (installed in your Supabase) in the checkout, so every database rule runs on real PostgreSQL | 744 | 744 | 0 | 0 | 0 |
| B. Your GitHub branch as it is (that file missing) | 744 | 664 | 0 | 0 | 80 |

**Raw results:**
- Run A: `Ran 744 tests in 641.221s — OK`
- Run B: `Ran 744 tests in 504.441s — OK (skipped=80)`

**The 80 skipped tests in run B** are the PostgreSQL rule tests:
- 46 in `test_founding50.SqlFoundingTests`;
- 34 in `test_ff10.SqlFF10Tests`.

They need the installed pilot migration file in the checkout. The same scenarios run against the in-memory store in
both runs and pass. On a machine without PostgreSQL every PostgreSQL test is skipped.

## New in these review corrections (15 tests; each runs on the in-memory store and on PostgreSQL unless noted)

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
