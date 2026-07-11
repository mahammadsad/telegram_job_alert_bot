# সরকারি তথ্যকেন্দ্র Telegram bot

This project discovers Bengali public-information notices, verifies them against
allowlisted official sources, creates a Bengali Telegram message and a 1080×1080
PNG locally, and publishes only records that pass every hard verification gate.
It runs on scheduled GitHub Actions; no permanent server is needed.

Gemini is no longer used. Images are created free of API charges with Jinja2,
HTML/CSS, Playwright Chromium, and Noto Bengali fonts. Groq remains responsible
only for controlled JSON extraction/classification/translation—not fact creation.

## Supported categories

`JOB`, `WELFARE_SCHEME`, `SCHOLARSHIP`, `ADMISSION`, `RESULT`, `EXAMINATION`,
`EDUCATION_NOTICE`, `UNIVERSITY_NOTICE`, and `GOVERNMENT_ANNOUNCEMENT` are fixed
enums. Notices may be `NEW`, `UPDATED`, `CORRIGENDUM`, `CANCELLED`, or
`DEADLINE_EXTENDED`.

## Architecture

- `sources/`: RSS and configuration-driven HTML discovery; PDF extraction.
- `processing/`: fixed classification, Groq JSON extraction, official URL and
  redirect verification, deterministic evidence/value validation, formatting,
  and duplicate/revision checks.
- `database/`: idempotent migrations and repositories for notices, revisions,
  source checks, provider usage, and review items.
- `rendering/`: autoescaped HTML templates and local Playwright screenshots.
- `telegram/`: safe URL buttons, caption splitting, and text fallback.
- `scripts/`: migration, review queue, and category-card tools.
- `config/`: sources, categories/themes, and exact trusted-domain allowlist.

The pipeline rule is deliberately strict:

```text
Aggregator discovery → trusted official page/PDF → Groq extraction
→ deterministic evidence validation → local render → Telegram
```

Karmasandhan is discovery-only. Its statements can never be official evidence.
An official URL and final redirect host must be allowlisted, downloadable, and
support every critical extracted claim. Missing data, invalid AI JSON, scanned
PDFs, conflicts, untrusted links, and unsupported evidence go to manual review.
A verification score is diagnostic and can never bypass a hard gate.

## Secrets and settings

Required GitHub Actions secrets for live automatic posting:

- `GROQ_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`

Optional secret:

- `TELEGRAM_REVIEW_CHAT_ID` — private admin chat for review notifications.

Optional Actions variables/environment values:

- `GROQ_TEXT_MODEL` (default `llama-3.3-70b-versatile`)
- `GROQ_RATE_LIMIT_DELAY` (default `3`)
- `GROQ_RETRY_BASE_DELAY` (default `20`)
- `GROQ_MAX_RETRIES` (default `3`)
- `GROQ_DAILY_TEXT_LIMIT` (default `1000`)
- `MAX_ITEMS_PER_RUN` (default `5`)
- `DRY_RUN` (default `false`)
- `AUTO_POST_ENABLED` (default `true`)
- `LOG_LEVEL` (default `INFO`)
- `DATABASE_PATH` (local-only optional override)

Copy `.env.example` to `.env` for reference, but export the values in your shell;
the application intentionally does not load secret files implicitly.

## Local setup

Python 3.11 is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium
python scripts/migrate.py
python app.py
```

On Ubuntu, install Bengali fonts with:

```bash
sudo apt-get install fonts-noto-core fonts-noto-extra fonts-noto-color-emoji
```

The legacy `python scraper.py` command remains as a compatibility wrapper.

## Safe dry run

`DRY_RUN=true` never calls Telegram. It still discovers, verifies, extracts, and
renders eligible notices, saving cards/messages in `dry_run_output/`:

```bash
DRY_RUN=true AUTO_POST_ENABLED=false python app.py
```

A Groq key is still needed if a new official notice reaches extraction. Offline
tests and sample rendering never contact live government sites or Telegram.

## Tests and sample cards

```bash
pytest -q
python scripts/test_render.py
```

The render script creates one local PNG per category under `render_samples/`.
Tests use local HTML/RSS and generated PDF fixtures; they do not depend on live
government websites.

## Review queue

```bash
python scripts/review_queue.py list
python scripts/review_queue.py show 12
python scripts/review_queue.py approve 12
python scripts/review_queue.py reject 12 --reason "Official notice is superseded"
python scripts/review_queue.py retry 12
```

Approval marks an item for fresh verification on the next schedule. It does not
override trusted-domain, evidence, conflict, or required-field gates. No webhook
or permanently running approval bot is required.

Approved/retry items retain their discovery summary and candidate official links
in SQLite, so the next run can reconsider them even if they have moved out of the
source feed's newest-item window.

## Adding sources, domains, and templates

To add a source, edit `config/sources.yaml`. Set its parser type and categories,
rate/timeout limits, allowed domains, and whether it is official or discovery
only. HTML sources require manually verified `item_selector`, `title_selector`,
and `link_selector`; never guess them. Check robots.txt and the site's terms.

To trust an official host, add the exact base hostname to
`config/trusted_domains.yaml`. Subdomains are accepted safely; lookalikes such as
`wb.gov.in.evil.example` are rejected. Review ownership before adding any host.

To change a category card, edit its small template in `rendering/templates/` and
theme in `rendering/category_styles.py`, then run the render script and tests.
Templates inherit the autoescaped base and show only up to five verified facts.
Do not use official emblems, political figures, party colours, or copied seals.

## GitHub Actions

The workflow runs on schedule and supports manual dispatch. In GitHub open
**Actions → Bengali Government Information Bot → Run workflow**. Select dry run
to prevent Telegram calls. Open the individual run to inspect source counts,
official final domains, verification decisions, queue reasons, rendering, and
Telegram results. Dry-run cards are available as a workflow artifact.

The workflow installs Chromium/fonts, migrates the database, runs tests, executes
the pipeline, and commits `jobs.db` only when changed. Concurrency prevents two
runs from racing on SQLite.

Each source's `min_interval_minutes` is enforced through the `source_checks`
table. Successes and failures are recorded without storing credentials.

## Database compatibility and revisions

Migrations never delete `seen_jobs` or provider-history tables. Existing
`seen_jobs` records are copied idempotently to generic `notices` as historical
`POSTED` jobs, preventing reposts. Every downloaded official response gets a
SHA-256 hash. A changed response at the same canonical URL creates a new
`notice_revisions` entry and is reprocessed as an update rather than silently
deduplicated.

Dry runs copy `jobs.db` to `dry_run_output/dry_run.db`; the production database
and Telegram are not changed.

## Common problems

- **No official URL found:** expected for aggregator-only items; inspect the queue.
- **Scanned PDF:** intentionally not OCRed; review the official PDF manually.
- **Chromium missing:** run `python -m playwright install --with-deps chromium`.
- **Bengali boxes/missing glyphs:** install Noto Bengali fonts and run `fc-cache -f`.
- **Groq extraction failure:** check key/model/quota and retry the queue item.
- **Telegram 400 error:** inspect escaped message/validated buttons in logs; secrets
  are never logged.
- **No post despite a high score:** a hard verification gate failed; read the queue
  reason. Scores never override gates.

## Safety limitations

Automated extraction cannot guarantee that an authority has not published a new
correction elsewhere. Always read the linked official notice before acting.
Scanned documents, conflicts, incomplete notices, unknown redirects, and unclear
categories require humans. The bot does not scrape personal data and should be
run with reasonable intervals in compliance with robots.txt and website terms.

Official portal starters (`wb.gov.in`, WBPSC, WBPRB, WBBSE, WBCHSE, and WBJEEB)
remain disabled in `sources.yaml` pending manual verification of current listing
selectors. This is intentional; the configuration documents the work instead of
pretending unverified selectors function.
