# GitHub Actions setup

Open **GitHub repository → Settings → Secrets and variables → Actions**.

Under **Secrets**, click **New repository secret** for each:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `TELEGRAM_REVIEW_CHAT_ID` (private admin chat; optional)
- `AI_API_KEY` (optional Groq free-tier key)

Under **Variables**, add:

- `AI_TEXT_MODEL` (a currently available free-tier model; do not leave AI enabled without it)
- `AI_ENABLED=true`, `AI_DAILY_CALL_LIMIT=100`
- `MAX_ITEMS_PER_RUN=10`, `MAX_POSTS_PER_RUN=5`, `MAX_POSTS_PER_CATEGORY=2`
- `AUTO_POST_ENABLED=true`
- `DAILY_DIGEST_ENABLED=false` (change to `true` after testing the digest workflow)
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- `VITE_TELEGRAM_CHANNEL_URL`

Set `PUBLIC_WEBSITE_URL` to the predictable GitHub Pages address:

```text
https://mahammadsad.github.io/telegram_job_alert_bot
```

It is used for Telegram website buttons, digest links, and the production sitemap.

Run **Actions → Government Information Pipeline → Run workflow** with dry run first.
The production concurrency group prevents overlapping publish runs. `jobs.db` is
not committed. Deadline maintenance runs daily, and the health workflow reports
source failures, queue size, posts and Telegram failures.

`Daily Deadline Maintenance` changes deadline states and creates one high-priority
review candidate when a published deadline first enters the three-day window. The
optional `Daily Bengali Digest` sends `DIGEST_ONLY` education/university items once
per date; its unique database row prevents a duplicate daily digest.

To recover from failure, open **Actions**, open the red run, expand the failed step,
fix the named secret/source/model, and click **Re-run failed jobs**. A recorded partial
Telegram photo is not blindly posted again; only the missing text is retried.
