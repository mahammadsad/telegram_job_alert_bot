# Source management

A source registry row includes parser/source type, URLs, allowed hosts, categories,
selectors, intervals, robots/terms review, health, failures and notes. Production reads
enabled Supabase sources; YAML remains a safe local fallback.

Before enabling a source:

1. Open its `robots.txt` and terms in a normal browser. Do not bypass blocks.
2. Confirm the exact official/aggregator owner and HTTPS domains.
3. For HTML/JSON, inspect the current listing and enter exact verified selectors/keys.
4. Set `terms_reviewed=true` and record `selector_verified_at` and notes.
5. Use at least a 120-minute interval, timeout ≤30 seconds, and ≤20 items initially.
6. Test with dry run. Confirm every final evidence link is an allowed official domain.
7. Enable only after the result is stable. Disable immediately after repeated failures.

Full aggregator article inspection additionally requires `article_inspection=true`.
It is fail-closed for uncertain robots access, caps redirects/bytes/links, ignores
tracking/shortener links, and never treats article text as official evidence.
