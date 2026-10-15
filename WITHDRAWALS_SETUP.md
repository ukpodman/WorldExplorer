# Manual withdrawal requests (V21) — setup and operation

Players in the rewards pilot can ask for their earned rewards to be paid out. **World Explorer never moves money.**
You review each request, transfer the money yourself from your own bank account, and then record the payment in the
Owner dashboard.

The feature is **built in but switched off for real players**. Until you switch it on, real players see a grey button
("🔒 Withdraw — Opens after the official launch"). Owner and tester accounts can simulate the whole process. Their
records are marked **TEST RECORD — NOT PAYABLE** and never count as real money owed.

Nothing in this setup changes your existing tables, rewards, referrals or payment records.

## How it works

1. **Eligibility (checked by the database, not only the screen).** A player can request a withdrawal when:
   * they joined the rewards programme (18+ and living in Nigeria are self-declared when joining);
   * at least **30 calendar days** have passed since their **first enrolment** (Nigeria time). Logging in again does not
     restart the count;
   * they have **net verified earnings** from **completed calendar months** that are not already requested,
     approved, paid, held or refused. The current month is never included. "Net verified" means:
     * rewards for referrals you **rejected** are deducted (earned rewards are never negative or edited, so a rejected
       referral is the deduction);
     * a month with a referral reward still **awaiting your review** waits until you approve or reject that referral.
       The player sees that it is being checked;
     * a month is never below zero, and a request is never ₦0 or negative;
   * they have no other request in progress;
   * for real players, live withdrawals are switched on (step 5).
2. **Whole balance only.** A request always covers the full available balance, for example September ₦650 +
   October ₦900 = ₦1,550 when requested in November. November's earnings wait until November ends.
3. **The application.** The player enters their legal name and confirms four statements: the name is correct, the bank
   account is theirs, the beneficiary name must match their identity, and false information can lead to a hold or
   rejection. **The app never asks for bank details.** Submitting does not verify anything; you verify manually.
4. **Notification.** You see the request in the Owner dashboard. Three places show the same number of unread requests:
   the alert at the top, the **💳 Withdrawals (N)** tab, and the 🔔 panel, with one card per new request.
   * **Dashboard already open:** only the notification panel and the alert check for new requests, every 30 seconds
     (one small database read), and a 🔔 toast pops up. The rest of the page does not reload, so a form you are
     filling in is not lost. The figures and table refresh with the **Refresh** button or your next action.
   * **Dashboard closed:** notifications are stored in Supabase and wait for you. A notification disappears only when
     you open the application (*Review Application*), decide on it, or press *Mark all as read*. It stays in the
     history.
   * **E-mail** is optional and separate. The dashboard never depends on it.
5. **Your review** (💰 Rewards & Referral Management → 💳 Withdrawals → *Review Application*). The panel shows:
   * the legal name, registered profile and Google account;
   * the enrolment date, total earnings, months covered and previous withdrawals;
   * referral activity and fraud or duplicate-account prompts.

   Then:
   * **Approve** — needs two ticks: eligibility confirmed, and the bank beneficiary name matches the legal identity.
     **Approving does not transfer money.** The status becomes *Approved — Awaiting Payment*.
   * **Place on hold** or **Reject** — a reason is required, and the player sees it. A rejection releases the earnings
     for a future request, unless you tick *Disqualify these earnings*. That is recorded in the audit log, and those
     earnings stay blocked.
   * **Mark as paid** — only after your bank transfer succeeded. Enter the payment date (and optionally the bank
     reference), tick that you transferred the money, then give a **final confirmation**. The amount must equal the
     approved amount. A request can be paid only once, and each bank reference can be used only once.
   * **One payment record per month, not two ledgers.** When a real request is marked as paid, each covered earning
     month is settled in your **existing `reward_payments` table** (status *Paid*, reference = the WD- reference). The
     existing rules for that table still apply. Your existing Payments tab and Overview figures therefore show it.
     `reward_cashout_payments` keeps the bank transfer itself, because one transfer can cover several months. Reports
     count each payment once.
     * A month counts as settled by a withdrawal because of the withdrawal's own paid record, never because of the
       reference text. Editing a payment can therefore never make it count twice.
     * The WD- reference of such a month cannot be changed. You can still add remarks or a reason, and its amounts,
       date and status stay frozen by the existing rules.
     * Other payments cannot use a reference in the form WD-YYYYMM-XXXX.
     * All other edits in the Payments tab work as before, including changing the reference of an ordinary monthly
       payment.
   * **Verification stays separate.**
     * The withdrawal's own checks (eligibility confirmed, beneficiary name verified, who approved it and when) are
       stored on the request.
     * Approving a withdrawal **never changes the player's general eligibility verification**
       (`reward_accounts.verification`).
     * Your existing payment rules require that verification before a month is approved or paid. So for a real
       request, first verify the player in **Participants** (Eligibility verification = verified). Otherwise the
       approval is refused with that explanation.
     * Test requests do not need it.
   * **Earnings re-checked.** At approval and again at "Mark as paid", the database checks that each covered month
     still has exactly the reserved net amount. If you rejected a referral in between, the request is refused with
     "earnings changed": reject it, and the player can request the correct amount.
6. **The player** follows the request on 💰 My Rewards. Its status goes from Pending Review to Under Review or On Hold,
   then to Approved — Awaiting Payment, and finally to Paid (or Rejected). Their history lists every request.

## 1. Run the database migration (one time)

Supabase → **SQL Editor** → **New query** → paste the whole of `supabase/withdrawals_migration.sql` → **Run**.

* Run `supabase/rewards_schema.sql` first (it already exists in your project). The migration stops with a clear
  message if the rewards tables are missing.
* It only **adds** five tables (`reward_cashout_settings`, `reward_cashout_requests`, `reward_cashout_months`,
  `reward_cashout_payments`, `reward_owner_notifications`), plus functions, triggers and one extra safety trigger on
  `reward_payments`. Running it again is safe and keeps all data.
* **Security:**
  * Row Level Security is on, and the browser roles have no access at all.
  * Only the server key used by the app on the server can use the tables and functions.
  * The app only ever reads the signed-in player's own requests.
* **Persistence:** applications, notifications, decisions and payments are stored in these Supabase tables, so they
  survive app restarts. The in-memory "preview" store is used only by owners and testers on a copy of the app with
  no Supabase storage configured; it is labelled in the dashboard and is never used for real players.
* **Built-in protections:**
  * the earning months of a request are reserved, so they can never be requested or paid twice;
  * one open request per person;
  * concurrent clicks are serialised with database locks;
  * approved and paid amounts must match;
  * a payment is recorded once and can never be changed;
  * requests and payments can only change through the withdrawal functions;
  * every change goes to `reward_audit_log`;
  * the existing monthly payment review cannot approve or pay a month that a request holds. Its other workflows are
    unchanged (open reviews, hold, reject, remarks, and approve or pay months that no request holds);
  * real approvals and payments are refused by the database while `real_payouts` is off, whatever the app sends;
  * owner decisions need an email listed in `owner_emails`. The app passes the email of the signed-in Google owner,
    taken on the server from Google's verified sign-in, never from anything typed into the page or the address.
* If the app reports "function not found" right after the migration, Supabase has not yet refreshed its API cache.
  Wait a minute, or run `notify pgrst, 'reload schema';` in the SQL Editor.

## 2. Allow yourself to make decisions (one time)

The database checks who may approve and record payments. Run this, replacing the email with the Google account you
use for the Owner dashboard (it must also be in `[analytics] owner_emails`):

```sql
update public.reward_cashout_settings
   set owner_emails = array['you@example.com'], updated_by = 'you@example.com'
 where id = 1;
```

Until you do this, the dashboard shows "Owner listed in database: NO", and approvals are refused.

## 3. Optional secrets (Streamlit Cloud → Settings → Secrets)

```toml
[rewards]
# existing keys stay as they are (enabled, payouts_active, tester_emails, …)
withdrawals_active = false          # keep false until legal and compliance review
bank_fingerprint_key = "PASTE-40+-RANDOM-CHARACTERS"   # optional, see below

[email]                             # optional owner e-mails
smtp_host = "smtp.example.com"
smtp_port = 587                     # 465 = SSL, otherwise STARTTLS
username = "SMTP_USERNAME"
password = "SMTP_PASSWORD"
sender = "World Explorer <noreply@example.com>"
owner_to = ["you@example.com"]
```

* **E-mail** is optional. The e-mail contains the player's name, the reference, the amount and the date (no legal
  name, no bank details). If it fails, the request is still saved and shown in the dashboard.
* **Bank fingerprint** is optional. When you check a player's bank account, you can type the bank and the 10-digit
  account number into the review panel. The app stores only a keyed fingerprint (HMAC-SHA256), never the number. If
  another profile uses the same account, you see a warning; nothing is blocked automatically. Generate a key with
  `python -c "import secrets; print(secrets.token_urlsafe(40))"`. Keep it secret and never change it afterwards, or
  old fingerprints will no longer match.

Never put real secrets in GitHub. They belong only in Streamlit Cloud's Secrets box.

## 4. Test everything first (test mode)

With real withdrawals still off:

1. Sign in with your owner account → 💰 My Rewards → join, if you have not yet. Owner records are always test records.
2. Open **🧪 Simulation (test account only)**:
   * **Add simulated activity for this month** — earns test rewards for each day of the month so far;
   * **Simulate a later date** — for example 31 days, to pass the 30-day wait and close the current month.
3. Press the green **💰 Request Withdrawal** button and submit the application.
4. Owner dashboard → 💳 Withdrawals → the 🔔 card → *Review Application* → approve, hold, reject or mark as paid.
   Test requests can be approved and paid even while payouts are off. They stay labelled TEST RECORD — NOT PAYABLE,
   are never written into `reward_payments`, and never count in real figures.
5. Request again: the button stays grey because those months are paid. This is the duplicate-payment protection.
6. Turn on **Include test records** to see the test figures, and use **Test records → Clear test records** to remove
   them. Real records can never be deleted.

## 5. Going live (only after legal and compliance review)

Real requests need **both** switches. Real approvals and payments also need payouts:

| Switch | Where | Effect |
|---|---|---|
| `withdrawals_active = true` | Streamlit secrets `[rewards]` | the app allows real requests |
| `live_requests = true` | database (SQL below) | the database accepts real requests |
| `payouts_active = true` | Streamlit secrets `[rewards]` | the app lets you approve real requests and record real payments |
| `real_payouts = true` | database (SQL below) | the database accepts real approvals and payments |

```sql
-- only after legal and compliance review
update public.reward_cashout_settings set live_requests = true, updated_by = 'you@example.com' where id = 1;
update public.reward_cashout_settings set real_payouts = true, updated_by = 'you@example.com' where id = 1;
```

As delivered, all four are **off**. The migration creates the database switches as `false`, and the app switches
default to `false` when they are missing from secrets. Owner and tester simulations work with everything off. There
are no automatic bank transfers in World Explorer at all.

To switch off again: set `withdrawals_active = false` and/or `live_requests = false` to stop new requests, and
`payouts_active = false` and/or `real_payouts = false` to stop approvals and payments. Requests already submitted
stay in the dashboard.

## Reports

**💳 Withdrawals** shows:

* the counts by status, the amount awaiting payment, the total paid and the remaining budget;
* a searchable table, filtered by player, request date, amount, earning month and status, with CSV export;
* **Financial accounting**, with CSV export for both tables:
  * **By earning month** — the liability stays in the month it was earned (September's ₦800 is September's
    liability even if paid in November);
  * **By payment month** — the cash you transferred, by the month you sent it.

*Remaining budget* = monthly budget × programme months so far − rewards earned + refused rewards. An earned reward
counts as owed until it is paid or refused, so it is never counted twice.

## What was and was not tested

* **Tested here:**
  * every database rule on a local PostgreSQL 16 with the real SQL: eligibility, Nigeria dates, completed months,
    duplicates, simultaneous requests and payments, approve, pay and reject, access for browser roles, re-running the
    migration, and the audit log;
  * the same rules in the in-memory store;
  * the app screens with Streamlit's test runner;
  * a full player → owner → payment flow in a Chromium browser at phone, tablet and desktop sizes.
* **Not tested:**
  * your live Supabase project (the migration was not run there);
  * real Google sign-in;
  * real SMTP delivery;
  * any bank transfer;
  * a physical iPhone or Android device.
