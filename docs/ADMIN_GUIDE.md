# Admin guide

Open `/admin/login`, enter the email registered in Supabase, and use the magic link.
Only a `profiles` row with `reviewer` or `admin` role passes the dashboard guard and RLS.

## Review an item

1. Open **review queue** and read `review_reason`.
2. Open the discovery reference only for context; use an official URL as proof.
3. Correct `corrected_official_url`/structured data in Supabase Table Editor if needed,
   include page evidence, and record an admin note.
4. Click **সংশোধন করে পুনরায় যাচাই**. This sets `RETRY`; it does not publish.
5. The next pipeline re-downloads and re-validates the official document.
6. Reject with a clear reason when eligibility, relevance, source or deadline fails.

Manual overrides need an official URL, reason, actor and timestamp in `audit_logs`.
They must remain internally distinct from `VERIFIED_OFFICIAL`; never describe an
override as automatic verification.

Use the source, pipeline, notices, and Telegram tabs for health/status inspection.
