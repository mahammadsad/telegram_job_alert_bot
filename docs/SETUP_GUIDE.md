# Setup guide (beginner friendly)

Complete these in order. Keep every secret private; never paste one into a source file.

1. Open Supabase, click **New project**, choose the Free plan, and wait for setup.
2. Follow `SUPABASE_SETUP.md` to run the SQL migration and create your admin.
3. Create a Telegram bot/channel using `TELEGRAM_SETUP.md`.
4. In GitHub open the repository, click **Settings → Secrets and variables → Actions**.
5. Add the secrets/variables listed in `GITHUB_ACTIONS_SETUP.md`.
6. Set `PUBLIC_WEBSITE_URL` to
   `https://mahammadsad.github.io/telegram_job_alert_bot`.
7. Enable and deploy the website using `GITHUB_PAGES_SETUP.md`.
8. In GitHub click **Actions → Government Information Pipeline → Run workflow**.
9. First choose **dry_run: true**. Download `dry-run-output` from the completed run.
10. Inspect logs/cards. Then run without dry run only after trusted sources and Telegram are correct.

For an old database, first run a no-write check:

```bash
python scripts/import_sqlite_to_supabase.py --database jobs.db --dry-run
```

Then export `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, remove `--dry-run`, and
run it again. Re-running is safe: notice discovery URLs and revision numbers are upserted.
