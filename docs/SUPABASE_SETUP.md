# Supabase setup

## Create tables and RLS

1. Open your Supabase project.
2. Click **SQL Editor → New query**.
3. Open `supabase/migrations/202607110001_platform.sql` in GitHub, copy all of it,
   paste it into the query, and click **Run**.
4. In **Table Editor**, confirm that `notices`, `sources`, `review_queue`,
   `pipeline_runs`, `telegram_posts`, and `profiles` exist.

## Get keys

Open **Project Settings → API** (or **Connect → App Frameworks** in the current UI).
Copy the Project URL, anon/public key, and service-role key. The service-role key is
only a GitHub secret. Never add it to `web/`, a `VITE_` variable, logs, screenshots,
or GitHub Pages build variables.

## Create the first admin

1. Open **Authentication → Users → Add user** and create/invite your email.
2. Copy that user's UUID.
3. Open **SQL Editor** and run, replacing only the UUID/email placeholders:

```sql
insert into public.profiles(id,email,role)
values ('USER_UUID_HERE','YOUR_EMAIL_HERE','admin')
on conflict(id) do update set role='admin', email=excluded.email;
```

The public anon role can select only `PUBLISHED` notices whose verification state
is official. RLS denies review notes, logs, source checks, delivery state and admin data.

## Apply future migrations

Run new files in `supabase/migrations/` in filename order from the SQL Editor. The
pipeline deliberately does not execute arbitrary DDL using a browser or anon key.

After configuring the Supabase environment values locally, load the disabled starter
catalogue once with `python scripts/sync_sources_to_supabase.py`. It is idempotent and
keeps unreviewed sources disabled.
