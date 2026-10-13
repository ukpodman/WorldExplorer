# Referral & Monthly Rewards pilot — setup and operation

The rewards programme is **built in but switched off**. With the default settings nobody sees 💰 Rewards, nothing is
recorded and nothing is payable. The rest of World Explorer behaves exactly as before. Existing tables
(`world_explorer_profiles`, `world_explorer_events`, `world_explorer_feedback`) are not changed.

There are two separate switches in the app's secrets. Both are `false` by default:

| Switch | What it does |
|---|---|
| `[rewards] enabled` | Everyone sees 💰 Rewards and can join (18+, lives in Nigeria, accepts the rules). |
| `[rewards] payouts_active` | You can approve payments and mark them as paid. Keep this `false` until legal and compliance review is done. |

While `enabled = false`, **owners** (`[analytics] owner_emails`) and the people in `tester_emails` can try everything.
Their records are marked as test records. They are left out of all figures (unless you choose to include them) and the
database never lets them become payable.

## 1. Create the rewards tables in Supabase (one time)

Open Supabase → **SQL Editor** → **New query**. Paste the whole of `supabase/rewards_schema.sql` and press **Run**.

* It only adds new tables (`reward_*`, `user_referrals`), one view, triggers and functions. You can run it again
  safely.
* It uses the same security as your other tables: Row Level Security is on, and the browser roles (`anon`,
  `authenticated`) have no access at all, including to the functions. Only the server key (`service_role`) can use
  them. The app already uses that key on the server, and it is never sent to the browser.
* The money rules are enforced by the database as well as by the app:
  * amounts and daily, monthly, category and ₦1,000 limits (trigger `reward_events_cap`);
  * earned rewards cannot be edited or deleted;
  * enrolment is atomic and cannot exceed places or budget (`reward_enrol`, with a database lock);
  * an approved amount can never exceed what was earned;
  * a payment can be marked paid only after approval, and only for a verified, non-test participant;
  * a paid record cannot be changed;
  * every change to settings, payments, account reviews and referral decisions is written to `reward_audit_log`.

Until this SQL is run, owners and testers get a **preview store** kept in the server's memory. It is labelled in the
app and disappears when the app restarts.

## 2. Secrets (Streamlit Cloud → Settings → Secrets)

Add this section **below** your existing secrets. Do not change `[auth]`, `[profiles]` or `[analytics]`.

```toml
[rewards]
enabled = false
payouts_active = false
tester_emails = ["tester@example.com"]   # optional: Google emails that may test while the programme is off
# app_url = "https://world-explorer-ukpodman.streamlit.app/"   # used in invitation links (this is the default)
```

The owner check stays as it is: a signed-in Google account with a verified email listed in
`[analytics] owner_emails`. It is checked on the server on every run, so hiding a button is not the protection.

## 3. Try it safely before launch

1. Sign in with your owner account. A compact **💰** button appears next to ☰ (Settings → 💰 Rewards also works).
2. Join and play: finish a quiz of 5 or more questions, open a country's Neighbours or Landmarks, and so on. Check
   that your month card fills up. The page shows "Test mode".
3. Open **Settings → Owner dashboard → 💰 Rewards & Referral Management**. Here you can:
   * see your test figures with "Include test records";
   * open a payment review (approving is refused while payouts are off);
   * change settings, pause the programme, and clear test records.
4. A tester can share their invitation link with a second tester who has never signed in before. That shows the whole
   referral journey.

## 4. Launch (only after legal review)

1. Review the programme rules in `ui/rewards_page.py` (`TERMS`, English) with your legal adviser. Update
   `rewards.TERMS_VERSION` in `core/rewards.py` when the wording changes.
2. Check the settings in the dashboard: budget ₦50,000, 50 places, ₦1,000 per person, and the start date.
3. Set `enabled = true`. People can now join. Amounts are shown as a "pilot preview, not payable" until step 4.
4. When you are ready to pay, set `payouts_active = true`.

## How rewards are earned (default settings)

| Activity | Each | Limit | Monthly maximum |
|---|---|---|---|
| Active day: a finished quiz or two countries explored that day | ₦25 | 1 a day, 20 days | ₦500 |
| Quiz: finished, 5 or more questions, any score (Daily Challenge practice replays don't count) | ₦10 | 3 a day, 30 a month | ₦300 |
| Country explored: first meaningful interaction with that country this month | ₦5 | 5 a day, 40 a month | ₦200 |
| Referral: a friend's **new** account reaches 3 active days, 5 quizzes and 10 countries | ₦50 | 4 a month | ₦200 |
| **Total per person per calendar month (Nigeria time, UTC+1)** | | | **₦1,000** |

The first three activities alone add up to ₦1,000, so people can reach the maximum without inviting anyone.

* **What counts as a meaningful interaction with a country:**
  * on Explore: opening the country's Neighbours or Landmarks, choosing a neighbour, or pressing "Quiz …" or
    "Learn about …";
  * on Learn: opening "Compare country size" or "More details", choosing a neighbour, or pressing "Quiz me on this
    country".
* **What never counts:** only viewing a country, time spent on a page, opening the app or signing in. (On desktop,
  Learn opens the Neighbours and Landmarks sections by itself, so those two sections don't count on Learn.)
* **Repeats never pay twice.** Each quiz round, country per month, day and referral has a fixed key, so refreshing a
  page or repeating an action adds nothing.

## Places, budget and the waiting list

* Each participant reserves the monthly maximum (₦1,000) from the budget when they are enrolled for a month. With
  ₦50,000 and 50 places, the 51st person joins the **waiting list**.
* People are enrolled again automatically for each new month on their first activity, while places and budget last.
* If someone leaves, what they earned stays reserved and payable after review, and the rest of their place is freed.
  Then use **Budget → Move people from the waiting list into free places**. The waiting list is first come, first
  served.
* Changing the budget or places affects only new enrolments. Places already given and rewards already earned are
  never reduced.
* The dashboard shows these as separate figures: allocated budget, reserved, earned, pending, approved, completed
  payments, unreserved, average per participant, and cost per retained active user.

## Monthly payments (manual)

1. **Payments → Open payment reviews.** This records each participant's earnings for the month.
2. Check the participant (Participants tab: activity history and fraud signals). Set **Eligibility verification =
   verified** once you have checked their age and residence in a way you are comfortable with. World Explorer never
   asks for or stores bank details. Collect payment details separately and securely.
3. For any referral rewards in the month, approve or reject the referral in the **Referrals** tab after checking both
   accounts.
4. Set the payment to **Approved**, with an amount no higher than what was earned.
5. After you have sent the money outside the app, set it to **Paid**, with the payment date and an optional
   reference and remarks. The app never marks anything as paid by itself.
6. Use **On hold** or **Rejected** (with a reason) when needed.

Every step is recorded in the audit log. All tables can be exported as CSV (it opens in Excel).

## Privacy and fairness

* **What is stored:**
  * the pseudonymous profile id (the same one as player progress);
  * the verified Google email and display name, for the owner only;
  * the declarations (yes/no, terms version, date);
  * activity events (country ids, quiz round ids, number of questions, average answer time).
* **What is not stored:** no date of birth, no address, no ID documents, no bank details, no device fingerprinting.
* **Referred friends:** if a friend joins through a link, their learning activity is recorded only to check whether
  the referral qualifies. They see a note about this on 💰 Rewards.
* **Fraud signals are prompts for a manual look, never automatic blocks:**
  * very fast quiz rounds;
  * 15 or more rounds in a day;
  * bursts of referred sign-ups;
  * repeated duplicate, self or existing-account referral attempts;
  * referrals that qualify very quickly;
  * accounts you marked for review.
* Households and shared devices are not treated as fraud.

## What was tested here, and what needs live checking

| Tested in this environment | Needs live verification |
|---|---|
| Rules engine (amounts, caps, Nigeria days, codes, qualification, budget figures, fraud signals, payment transitions). | Running `rewards_schema.sql` in your Supabase project. |
| The SQL schema on a local PostgreSQL 16, with the same roles as Supabase (`anon`, `authenticated`, `service_role`): caps, frozen earnings, enrolment under simultaneous requests, simultaneous awards, payment rules, audit log, no browser-role access, safe re-run. | Supabase REST and RPC calls with your server key. The request format is unit-tested, but the real network calls were not tested. |
| The same scenarios against the in-memory preview store, plus a check that the Python and SQL rules give identical amounts. | Real Google sign-in, including a referral link kept through Google's sign-in page. This uses the `we_ref` cookie. Sign-in was simulated here. |
| The app with simulated Google identities (Streamlit AppTest and a real Chromium browser): off by default, owner preview, join, quiz and country hooks, referral attribution, owner dashboard, payments, settings. | WhatsApp sharing and copying the link on real phones. These were checked in desktop and phone-sized browser windows, not on real devices. |
