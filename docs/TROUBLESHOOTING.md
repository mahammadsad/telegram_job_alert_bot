# Troubleshooting

- **Supabase 401/403:** verify the production workflow has the service-role secret and
  the website has only the anon key. Re-run the SQL migration/RLS setup.
- **Website shows no notices:** confirm a row is both `publication_status=PUBLISHED`
  and `verification_status` is `VERIFIED_OFFICIAL` or `POSTED`.
- **Source skipped:** it may be disabled, inside its minimum interval, disallowed by
  robots, oversized, wrong content type, or missing verified selectors.
- **No AI model/key:** expected reduced mode; review items are queued instead of invented.
- **Scanned PDF:** it needs human review; OCR is not silently trusted.
- **Chromium error:** run `python -m playwright install chromium`; install Noto Bengali fonts.
- **Telegram partial failure:** inspect `telegram_posts`; retry sends missing text without
  blindly duplicating the photo. Delete manually only after checking the channel.
- **Failed GitHub run:** open Actions, expand the red step, fix the named configuration,
  then choose **Re-run failed jobs**. Concurrency prevents a simultaneous publisher.
- **Import duplicate:** re-running is safe. If a real conflict remains, compare discovery
  URL, canonical official URL, document hash and revision number before editing.
