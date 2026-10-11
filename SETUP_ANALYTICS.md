# Pilot measurement and feedback — setup

Measurement and the feedback form stay **off** until you finish the steps below. The rest of the app works the
same either way, and player progress (the existing `world_explorer_profiles` table) is never touched.

## 1. Create the two tables in Supabase (SQL editor)

Open your Supabase project → **SQL Editor** → **New query**, paste this and press **Run**. It follows the same
rules as the profiles table: Row Level Security on, no access for the browser roles (`anon`, `authenticated`),
access only for the server key (`service_role`), which the app already uses on the server.

```sql
-- Usage events for the pilot (pseudonymous; no names, emails, IP addresses or answers)
create table if not exists public.world_explorer_events (
  event_key   text primary key,                       -- deterministic: repeated sends are ignored
  occurred_at timestamptz not null default now(),     -- set by the database (UTC)
  event       text not null check (event in ('visit','round_start','round_complete','link','consent_declined')),
  anon_id     text check (anon_id is null or anon_id ~ '^(g|u):[0-9a-f]{32}$'),
  signed_in   boolean not null default false,
  mode        text check (mode is null or mode in ('regular','daily','daily_replay','practice')),
  day         date,                                   -- Daily Challenge date (UTC) for daily rounds
  round_id    text check (round_id is null or round_id ~ '^[0-9a-f]{16}$'),
  linked_id   text check (linked_id is null or linked_id ~ '^g:[0-9a-f]{32}$'),
  device      text check (device is null or device in ('phone','tablet','desktop')),
  lang        text,
  test        boolean not null default false,
  app_version text
);
create index if not exists world_explorer_events_time on public.world_explorer_events (occurred_at);

-- Feedback messages (only what the person typed, plus page, device type, language and time)
create table if not exists public.world_explorer_feedback (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  page        text,
  device      text,
  description text not null check (length(description) between 1 and 2000),
  contact     text check (contact is null or length(contact) <= 120),
  lang        text,
  app_version text
);

alter table public.world_explorer_events   enable row level security;
alter table public.world_explorer_feedback enable row level security;
revoke all on public.world_explorer_events   from anon, authenticated;
revoke all on public.world_explorer_feedback from anon, authenticated;
grant select, insert on public.world_explorer_events   to service_role;
grant select, insert on public.world_explorer_feedback to service_role;
```

No policies are needed: the browser roles have no access at all, and the app talks to Supabase only from the
server. Nothing in the app can update or delete these rows.

## 2. Switch it on in the app's secrets

In Streamlit Community Cloud → your app → **Settings → Secrets**, add this section **below** what is already
there (do not change the existing `[auth]` or `[profiles]` sections — the app reuses the `[profiles]` URL and
server key for these tables):

```toml
[analytics]
enabled = true
owner_emails = ["you@example.com"]          # Google account(s) allowed to open the owner dashboard
salt = "replace-with-a-long-random-string"  # makes signed-in pseudonyms unguessable; keep it private, never change it during the pilot
```

Create the salt once, for example with `python -c "import secrets; print(secrets.token_hex(24))"`.
Changing it later splits signed-in people into new ids.

## 3. Open the owner dashboard

1. Sign in with Google using an address listed in `owner_emails`.
2. Open **☰ Settings → Privacy → Owner dashboard**.

The check runs on the server every time the page loads. Visitors who are not signed in as an owner see only
"This page is not available", and no data is loaded for them.

## 4. Keep your own visits out of the numbers

* Anything you do while signed in as an owner is flagged as test traffic automatically.
* On each phone, tablet or browser you test with, open the dashboard once and switch on **Mark this browser as
  test traffic**. This sets the `we_test` cookie, and that browser's events are flagged from then on, including
  when you play as a guest.
* The dashboard leaves out every person who has any flagged event. Switch on **Include owner/test traffic** to
  see the numbers with them included.

## 5. Privacy notice and consent (please read)

* **Consent.** Guests' measurement uses an identifier stored on the device (the `we_aid` cookie). For signed-in
  players it uses a pseudonymous code. The app therefore records nothing until the visitor chooses **Allow** in
  the bar at the top, or switches on **Settings → Privacy → Share anonymous usage statistics**.
  * **No thanks** is as easy as Allow.
  * The choice can be changed at any time in Settings → Privacy.
  * **Switching off reaches every open tab.** "No thanks" in any tab of a browser stops measurement at once in
    all open tabs of that browser, without a reload. When signed in, it also stops the person's other open
    sessions on other devices.
  * **Events still waiting to be sent are discarded.** They are checked again just before sending.
  * "Allow" reaches only the tabs of the same browser. Allowing on one device never switches statistics on for
    another device.
  * This works within one running copy of the app (Streamlit Community Cloud runs one). After an app restart
    every tab starts a new session and reads the cookie again.
  * **Global Privacy Control:** a browser sending Global Privacy Control (`Sec-GPC: 1`) is never asked and never
    measured, even if it chose **Allow** earlier.
    * Its id cookie is removed.
    * Settings shows the switch locked off, with an explanation.
    * The signal is read when the page loads. Tabs already open in the same browser stop as soon as one tab
      loads with it.
  * Apart from the id after **Allow**, the app only stores the choice itself (`we_consent`).
  * One anonymous row without any identifier is written when someone says no, so you can see how much traffic
    is not measured.
* **Sign-in cookie.** `we_handoff` is set only when a guest asks to save their progress with Google, so the
  progress can be found again after Google's page. It is part of the service the person asked for.
  * The server copy and the cookie last 30 minutes.
  * They stay until the account save that includes the progress succeeds. If that save fails, a refresh within
    30 minutes of the last attempt adds the progress again.
  * The saved profile records a one-way id of the transfer, never the token, so the progress is never added
    twice: not on retries, not on a repeated sign-in, not in several tabs.

* **Privacy notice.** Give testers a short notice before the pilot, for example in the invitation. It should
  cover:
  * who runs the pilot and how to reach you;
  * what is recorded (the list in `core/analytics.py`, also shown in Settings → Privacy);
  * the purpose (improving the app during the pilot);
  * that Supabase stores the data, and in which region;
  * how long you keep it (suggestion: delete the events table four weeks after the pilot ends);
  * how to ask for deletion.
  * Feedback messages are stored with any contact details the person chose to add.
* I am not a lawyer. In the EU, rules on device storage (ePrivacy/TTDSG §25) and the GDPR apply to pseudonymous
  ids. The consent-first design above is meant to meet them, but please have the notice checked for your
  situation.

## 6. Deleting data

* **One person:** delete their rows by `anon_id` (Table Editor → filter). Signed-in ids cannot be reversed to an
  email address. To find someone's id, ask them to tell you the time they played, or delete everything.
* **Everything after the pilot:** `drop table public.world_explorer_events; drop table public.world_explorer_feedback;`

## Limits of guest identity

* **Same browser, same device:** a guest stays the same person across refreshes and visits.
* **Another device or browser, cleared site data, a private window that is closed:** the guest counts as a new
  person.
* **Safari (iPhone, iPad, Mac):** cookies written by page scripts are kept for at most 7 days after the last
  visit. A guest who returns after more than 7 days counts as new; this affects the 7-day return rate only at its
  edge.
* **Signed-in players** count as one person on every device. If they allowed statistics as a guest on a device
  first, that guest id is merged into the account (the `link` event).
