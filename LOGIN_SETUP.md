# Online sign-in checklist (Google + Streamlit Community Cloud)

This app uses Streamlit's built-in sign-in (`st.login` / `st.user`, from `streamlit[auth]==1.65.0`).
Guests can always play; sign-in only adds saving across visits.

## Why “Error 400: redirect_uri_mismatch” happens

When someone presses **Continue with Google**, Streamlit sends Google the exact value of
`[auth] redirect_uri` from the app's secrets. Google then compares it, character for
character, with the **Authorized redirect URIs** of the OAuth client whose ID is
`[auth.google] client_id`. If that exact address is not in the list, Google stops with
`redirect_uri_mismatch`.

This is a configuration mismatch between the app's secrets and Google Cloud.
**Code cannot fix it.** The app only helps you diagnose it: open ☰ Settings, then
**Sign-in help for the app owner**. It shows the callback address for the address you are
actually using (it never shows any secret).

## Steps for the app owner

1. **Find the app's real address.** Open the deployed app and copy the address bar up to the
   domain, for example `https://your-app-name.streamlit.app`. No path, no trailing slash.
2. **The callback is that address plus `/oauth2callback`.** For example:
   `https://your-app-name.streamlit.app/oauth2callback`
3. **Set the deployed secrets.** Go to Streamlit Community Cloud → your app → ⋮ → **Settings** →
   **Secrets**. The `redirect_uri` must be the callback from step 2. Keep your existing values
   for the other keys; never paste them into chat, issues or commits.

   ```toml
   [auth]
   redirect_uri = "https://your-app-name.streamlit.app/oauth2callback"
   cookie_secret = "…long random string…"

   [auth.google]
   client_id = "…apps.googleusercontent.com"
   client_secret = "…"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

   [profiles]
   url = "https://YOUR_PROJECT.supabase.co"
   server_key = "…"
   ```
   Save. The app restarts with the new secrets.
4. **Register the same callback with Google.** Go to Google Cloud Console → **APIs & Services** (or
   **Google Auth Platform**) → **Clients** / **Credentials**. Open the OAuth client whose
   **Client ID is exactly the `client_id` in your secrets**. Projects often have several clients,
   and editing the wrong one is a common cause. Under **Authorized redirect URIs**, add:
   - `https://your-app-name.streamlit.app/oauth2callback` (identical to `redirect_uri`)
   - `http://localhost:8502/oauth2callback` (for local development; keep it)

   Save. Google says changes can take a few minutes to apply.
5. **Test in a private window.** Open the app, ☰ Settings → **Continue with Google**.

### Common mismatches to check
- `http` vs `https`, `www.` or a different subdomain, a trailing slash, `/oauth2callback` missing
  or misspelled.
- The app was renamed or redeployed under a new `*.streamlit.app` address.
- Secrets were updated, but the URI was added to a *different* OAuth client.
- You open the app through a custom domain but `redirect_uri` uses the `streamlit.app` address
  (or the reverse). Streamlit also requires the browser's address to match `redirect_uri`.

## Local development (port 8502)

Use a separate, uncommitted `.streamlit/secrets.toml` on your computer. Streamlit accepts one
`redirect_uri` per running app, so local and deployed secrets differ only in this line:

```toml
[auth]
redirect_uri = "http://localhost:8502/oauth2callback"
```

Run `streamlit run app.py --server.port 8502`. The same Google client can list both callbacks.
`.gitignore` already excludes `.streamlit/secrets.toml`. Never commit it or put it in the ZIP.

## Testing vs Production in Google's “Audience” settings

Per Google's help page *Manage App Audience* (checked 2026-10-08):

- **Testing:** normally only Google accounts listed as **test users** (up to 100) can sign in.
  They see an "unverified app" warning, and their authorisation expires after 7 days.
- **Exception that applies to this app:** if an app requests only name, email and profile
  (`openid`, `email`, `profile`), users do **not** need to be on the test list, see no warning,
  and their authorisation does not expire after 7 days. Streamlit's `st.login` requests exactly
  `openid profile email` by default, and this app does not change that. If you ever add other
  scopes (through `client_kwargs`), the Testing limits apply to everyone else.
- **In production** (after **Publish app**): any Google account can sign in. With only these basic
  scopes, Google may still ask for brand verification before your app name and logo appear on
  the consent screen.
- If other players still cannot sign in, check that the audience is **External** (not
  **Internal**, which limits sign-in to your Google Workspace organisation). Also check whether a
  player's own organisation blocks third-party apps.

## Saved profiles (Supabase)

- Create the table using the SQL in `README.md`. Only the server key in secrets can read or write it.
- If Supabase is unreachable, the app says so, retries after a minute, and **never writes until it
  has read the saved profile successfully**. An outage cannot overwrite saved progress with an
  empty profile.
- Profiles saved by earlier versions load unchanged. New settings (sound on/off, volume, places to
  include) are optional and default to off / 40% / UN states.

## What has and has not been tested

- **Tested here:** with real Streamlit 1.65.0 (AppTest), the app falls back to guest mode
  without secrets. Each misconfiguration (missing settings, wrong path, `http` on a public host,
  address mismatch, sign-in package missing) is diagnosed. A failed profile read never triggers
  a write.
- **Not tested here (needs your deployed app and accounts):** a real Google sign-in round trip,
  and real Supabase reads and writes.
