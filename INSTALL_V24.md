# Installing World Explorer V24 (Learn redesign + School Learning) without losing any user information

V24 changes **only application files**. It does not touch the database, accounts, points, badges, rewards, Founding 50, referrals, withdrawals,
Streamlit secrets or Google sign-in settings. Users' saved profiles keep working unchanged. School Learning saving stays off until you
separately approve and run its migration (see `SCHOOL_LEARNING_SETUP.md`).

## 1. Put the code on the staging branch (no merge, no deploy)

The branch is called `v24-school-learning-staging` and is based on production `main` at **6857bd4** (PR #9 merged). Choose one way:

**A. From the git bundle** (keeps the commit history):
```bash
git clone https://github.com/ukpodman/WorldExplorer.git && cd WorldExplorer
git fetch /path/to/WorldExplorer_V24.bundle v24-school-learning-staging:v24-school-learning-staging
git push origin v24-school-learning-staging          # creates the branch on GitHub; main is untouched
```

**B. From the changed-files ZIP:**
```bash
git checkout main && git pull && git checkout -b v24-school-learning-staging
unzip -o WorldExplorer_V24_changed_files.zip          # copies each file to the same path
git add -A && git commit -m "V24: Learn redesign and School Learning" && git push origin v24-school-learning-staging
```

`FILE_MANIFEST.txt` lists every added and modified file with its SHA-256. Check a few against your copy after unzipping.

## 2. Review it safely before production

* Open a pull request from `v24-school-learning-staging` into `main`, but **do not merge it yet**.
* Optional: deploy the branch as a separate Streamlit Cloud test app (Create app → this repository → branch `v24-school-learning-staging`) with the **same secrets as production but without a `[school]` section**. School Learning then runs in its no-saving mode and writes nothing to the database.
* Run the tests: `pip install -r requirements.txt && python -m unittest discover tests`. The expected result is in `TEST_RESULTS.txt`.

## 3. Release, when you approve

1. Merge the pull request. Streamlit Cloud redeploys `main` automatically. No secrets change is needed.
2. Check:
   * Learn → 🌍 World Geography: search, continent chips, the map, the photo and Quiz me.
   * Learn → 📚 School Learning: open a lesson, practise a round, open the dashboard.
   * The Quiz, music and your existing account still work.
3. **Rollback:** revert the merge commit on `main`. No data clean-up is needed, because V24 itself wrote nothing to the database.

## 4. Optional, separate approval: saving School Learning progress to accounts

Follow `SCHOOL_LEARNING_SETUP.md`: back up the database, review and run `supabase/school_learning_migration.sql`, run the verification
queries, then add the `[school]` section to secrets. Until then, students' progress stays in the browser tab, or on their device if they switch that on.

## What is new on users' devices

* A first-party cookie `we_school` is written **only** when a student switches on "Keep my progress on this device". It holds lesson positions and scores, with no personal details. Switching it off deletes it.
* No new external requests. The maps are bundled. The only external image is the existing Wikimedia photo of the Lekki–Ikoyi bridge, already used in World Geography.
