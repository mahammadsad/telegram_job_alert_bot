# Cloudflare Pages setup

> Optional alternative only. This project now deploys through GitHub Pages by default.
> You may skip this entire document and use `docs/GITHUB_PAGES_SETUP.md` instead.

## Before you start

Merge PR #1 into the repository's `main` branch first. Cloudflare cannot deploy the
new `web/` application from `main` until that pull request has been merged.

You will not see a Pages project's **Settings** menu before creating the project.
First create and deploy the Pages project; Cloudflare shows its Settings afterward.

## Dashboard connection (easiest)

1. Open the Cloudflare dashboard and select your Cloudflare **account**, not a domain.
2. In the left sidebar select **Workers & Pages**.
3. Select **Create application → Pages → Connect to Git**.
4. If Cloudflare first shows an application gallery, choose **Pages** and then
   **Connect to Git**. Do not choose a Worker template.
5. Authorize GitHub and select `mahammadsad/telegram_job_alert_bot`.
6. Select **Begin setup**, then use:

   - **Production branch:** `main`
   - **Framework preset:** `React (Vite)` (or leave the preset blank)
   - **Root directory (advanced):** `web`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`

7. For the first deployment, add only `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY`, and optionally `VITE_TELEGRAM_CHANNEL_URL`.
   Do **not** wait for `VITE_PUBLIC_WEBSITE_URL`; you do not have that URL yet.
8. Click **Save and Deploy**. Cloudflare will create and display a free address such as
   `https://your-project.pages.dev`. No custom domain is required.
9. Select **Continue to project**. The Pages project's **Settings** menu is now visible.
10. Copy the new production URL.
11. In the Pages project open **Settings → Environment variables** and add
   `VITE_PUBLIC_WEBSITE_URL` with the copied URL.
12. In GitHub open **Settings → Secrets and variables → Actions → Variables** and add
   `PUBLIC_WEBSITE_URL` with the same copied URL.
13. Click **Deployments → Retry deployment**, or run the GitHub website workflow again.

If **Workers & Pages** is missing entirely, return to the Cloudflare account home and
check that you are not inside a specific website/domain dashboard. The menu is at the
account level.

This two-deployment bootstrap is normal: the first deployment creates the URL; the
second deployment uses it for canonical sitemap links and Telegram website buttons.

Never add `SUPABASE_SERVICE_ROLE_KEY` to Cloudflare Pages. The SPA uses Supabase anon
access plus RLS. For deep links, add a Cloudflare Pages SPA fallback if your Pages
project does not automatically serve `index.html` for routes.

The repository's `.github/workflows/web.yml` deploys only to GitHub Pages. If you
choose this optional Cloudflare route, connect the repository through Cloudflare's
dashboard instead; no Cloudflare secrets are required by the repository workflows.
