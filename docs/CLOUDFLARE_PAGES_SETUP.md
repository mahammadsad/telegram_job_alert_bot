# Cloudflare Pages setup

## Dashboard connection (easiest)

1. Open Cloudflare dashboard and click **Workers & Pages → Create → Pages → Connect to Git**.
2. Authorize GitHub and select this repository.
3. Set **Root directory** to `web`, **Build command** to `npm run build`, and
   **Build output directory** to `dist`.
4. Add environment variables `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`,
   `VITE_PUBLIC_WEBSITE_URL`, and `VITE_TELEGRAM_CHANNEL_URL`.
5. Click **Save and Deploy**. Use the free `pages.dev` address; no domain is required.

Never add `SUPABASE_SERVICE_ROLE_KEY` to Cloudflare Pages. The SPA uses Supabase anon
access plus RLS. For deep links, add a Cloudflare Pages SPA fallback if your Pages
project does not automatically serve `index.html` for routes.

The alternative `.github/workflows/web.yml` deployment needs a scoped Cloudflare API
token with Pages edit permission and the account ID. Tests and the build run before deploy.
