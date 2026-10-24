# Operator verification and legal review checklist (before publishing)

**Proposed identification:** "World Explorer — Operated by OKETORIAH KÖNIGREICH LTD."
**Company:** OKETORIAH KÖNIGREICH LTD, CAC RC 7160552, incorporated 30 September 2023, Private Company Limited by
Shares, Nigeria.

This list was prepared by Claude, which is not a lawyer, from the app's real data flows. Use it with a Nigerian
corporate and data-protection lawyer, and an EU adviser if section C applies. Nothing in the app names the company
until both secrets are set: `[legal] operator_verified = true` and `[legal] published = true`.

## A. Is the company genuinely the operator?

1. **CAC status.** Obtain a current CAC status report and check:
   - the company is active;
   - its directors and shareholders;
   - its registered address;
   - that annual returns are filed.
2. **Objects.** Confirm the Memorandum and Articles of Association do not restrict operating an educational software
   service (and, later, a rewards programme). Update the registered nature of business if advised.
3. **Board resolution.** A resolution that the company owns or operates World Explorer and authorises the director(s)
   to run it.
4. **Intellectual property.** A written assignment or licence from the individual developer to the company covering:
   - the code;
   - the "World Explorer" brand and content;
   - the data compilations.
   Optionally, run a trademark search for "World Explorer" in Nigeria.
5. **Service accounts in the company's name**, or documented as held for the company:
   - GitHub repository;
   - Streamlit Community Cloud;
   - Supabase organisation and billing;
   - the Google sign-in client (consent-screen publisher and support email);
   - the contact email.
6. **Money flows.** Any future payments must come from a **company bank account**, not a personal one. Confirm
   bookkeeping, the company TIN and the tax treatment of rewards.

## B. Data protection (Nigeria Data Protection Act 2023, GAID 2025)

1. **Controller.** Confirm the company is the data controller, with the director acting for it.
2. **NDPC registration.** Assess whether the company is a data controller of major importance under the GAID 2025
   tiers. If so, register, pay the fees, and diarise the compliance audit returns or the renewal.
3. **DPO.** Designate a Data Protection Officer if required, and publish the contact.
4. **Processors.** Put data processing terms in place with Supabase and Streamlit/Snowflake. Note Google and
   Wikimedia as independent providers.
5. **Cross-border transfers.** Data is hosted outside Nigeria: Streamlit in the US, Supabase in [region]. Choose and
   document the transfer basis, then complete Privacy Policy section 6.
6. **Children.** Decide the approach in Privacy Policy section 9. A child under the NDPA is under 18, and parental
   consent is required. School Learning targets secondary-school students, so this decision matters before sign-in
   is promoted to students.
7. **Retention periods** (Privacy Policy section 7) and a **deletion procedure**.
8. **Breach response:** a 72-hour notification procedure.
9. **Assessment.** Consider a data protection impact assessment for the rewards and referral features before they
   go live.

## C. Cross-border legal responsibilities

1. **EU law.** If a director or any processing activity of the company is based in the EU (for example in Germany),
   or the app is offered to people in the EU, ask whether the GDPR and national rules also apply. These include
   cookie consent and provider-identification (imprint) duties. If they do, confirm whether an EU representative is
   needed and what the policies must add.
2. **Governing law.** Confirm Nigerian governing law and the dispute forum for users outside Nigeria.

## D. Friends & Family Pilot and any future rewards

1. **Rewards rules.** Confirm whether cash rewards for learning activity need approval or registration, for example
   under Federal Competition and Consumer Protection Commission (FCCPC) rules on sales promotions. Confirm that no
   lottery or gaming rules apply: there is no chance element and no paid entry.
2. **Identity checks** before any payment (beneficiary name match), plus record-keeping.
3. **Friends and family.** Fairness and conflict-of-interest wording for participants related to the operator.
4. **Rules wording.** Review the existing in-app rewards rules (`ui/rewards_page.py`, `TERMS`, version
   `2026-10-founding50-1`) so they name the company as operator. Bump `rewards.TERMS_VERSION` when the wording
   changes.

## E. Switch-on order (owner, after approval)

Every document stays a draft until **all** of the following hold. The app checks them and shows what is missing in
Owner dashboard → ⚖️ Legal & switches:

1. **Finalise the documents.** Your lawyer finalises each document in `legal/`:
   - remove the DRAFT notice and every [open item];
   - set a final version line, e.g. `*Version: 2026-11-05*`.
2. **Fill the secrets.** In Streamlit secrets, set `[legal] contact_email` and `[legal] registered_address`.
3. **Confirm the operator.** Set `[legal] operator_verified = true` once section A is complete. Before that, the
   company is never shown as operator or data controller.
4. **Approve each document's exact content.** Owner dashboard → ⚖️ Legal & switches shows each document's SHA-256
   checksum. After the legal review of that exact text, copy the values in:
   ```toml
   [legal.approved]
   privacy = "<checksum shown for the Privacy Policy>"
   terms = "<checksum shown for the Terms of Use>"
   pilot = "<checksum shown for the pilot terms>"
   ```
   Any later change to a document (even one character, even with the same version line) unpublishes it until you
   approve its new checksum. Approving `privacy` and `terms` publishes the general notice for **every** user,
   independently of any programme.
5. **Open the Friends & Family Pilot:**
   - run `supabase/pilot_invitations_migration.sql` (after approval);
   - in the Founding 50 tab, press "Record the published pilot terms": applicants must accept exactly that version,
     which is kept with each application;
   - invite people;
   - switch the pilot ON.
   Only invited people can apply; you approve each application, at most 50. If the pilot terms change later,
   applications pause until you record the new version.
6. **Later, and only when separately authorised:**
   - public rewards enrolment: the rewards switches, then in the Founding 50 tab, "Record the current public
     programme rules" (after their review), then "Allow public applications";
   - then `withdrawals_active` and `payouts_active`.
   All money switches stay closed while the Privacy Policy and Terms of Use are not published.
