# Free-tier guardrails

The architecture needs no paid server, card, custom domain, image API or subscription:
GitHub Actions runs scheduled Python; Supabase Free stores structured data/auth;
GitHub Pages hosts static assets; Telegram Bot API posts; Playwright renders local
temporary PNGs; PyMuPDF reads linked official PDFs; Groq is optional.

Hard controls:

- `AI_DAILY_CALL_LIMIT` stops calls and queues work; one provider/account is used.
- Source intervals, item/byte/redirect limits and `MAX_ITEMS_PER_RUN` cap scraping.
- `MAX_POSTS_PER_RUN` and duplicate/revision keys prevent Telegram floods.
- Per-category limits and one-row-per-day digest protection prevent burst/duplicate posts.
- Posters exist only during a run/artifact retention; PDFs remain official links.
- `provider_usage`, `pipeline_runs`, `source_checks` and daily health reports show use.
- AI-disabled/provider-failure mode continues discovery/rules and sends ambiguous items to review.
- No committed production database or large storage copy is required.

Check monthly: Supabase **Settings → Usage**, GitHub **Settings → Billing → Actions**,
GitHub **Settings → Pages** and **Actions**, and the AI provider usage page.
Reduce schedules/limits before approaching a free quota. Never rotate accounts or keys
to bypass a provider limit; disable AI instead.
