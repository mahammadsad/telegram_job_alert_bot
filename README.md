# সরকারি তথ্যকেন্দ্র

বাংলায় West Bengal-কেন্দ্রিক সরকারি চাকরি, ভর্তি, স্কলারশিপ, পরীক্ষা, প্রকল্প,
পরিষেবা ও গুরুত্বপূর্ণ ঘোষণার free, official-source-verified platform। এটি GitHub
Actions-এ discovery/verification চালায়, Supabase Free-তে data ও admin auth রাখে,
GitHub Pages-এ React website দেখায় এবং Telegram Bot API-তে alert পাঠায়।

## নিরাপত্তার মূল নিয়ম

Aggregator শুধু discovery reference। Publication-এর জন্য exact trusted official
domain, safe redirect chain, official HTML/PDF, field evidence, West Bengal
relevance এবং non-expired deadline লাগবে। অন্য রাজ্যের বাধ্যতামূলক domicile,
অস্পষ্ট eligibility, unsupported AI values ও unverified links publish হয় না। AI
না থাকলে pipeline rule-based facts সংগ্রহ করে item review queue-তে রাখে।

## Repository map

- `sources/`: RSS, verified-selector HTML, JSON API, sitemap, safe full-article inspection
- `processing/`: rules, AI JSON extraction, evidence, eligibility, deadline, formatting
- `database/`: SQLite adapter, Supabase REST adapter, migrations
- `supabase/migrations/`: normalized schema, indexes, functions and RLS
- `telegram/`: image/text delivery with partial-send recovery
- `rendering/`: local 1080×1080 Bengali cards; no image API
- `web/`: React + TypeScript + Vite public site and protected admin
- `.github/workflows/`: pipeline, website, deadlines, optional digest and daily health report
- `docs/`: beginner setup and operating guides

## Quick local verification

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
pytest -q
cd web && npm ci && npm test && npm run build
```

Safe SQLite dry run (never calls Telegram and never writes Supabase):

```bash
DATABASE_BACKEND=sqlite DRY_RUN=true AUTO_POST_ENABLED=false python app.py
```

Start with [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md). The important deployment
guides are [Supabase](docs/SUPABASE_SETUP.md), [GitHub Actions](docs/GITHUB_ACTIONS_SETUP.md),
[GitHub Pages](docs/GITHUB_PAGES_SETUP.md), and [Telegram](docs/TELEGRAM_SETUP.md).

## Intentionally disabled sources

All starter web sources whose current terms, robots policy or selectors have not
been manually verified stay disabled in `config/sources.yaml`. This is a safety
feature. Follow `docs/SOURCE_MANAGEMENT.md`; never enable guessed selectors.

## Cost

There is no mandatory paid component, custom domain, server, image generation,
or paid AI requirement. See `docs/FREE_TIER_GUARDRAILS.md` for limits and usage checks.
