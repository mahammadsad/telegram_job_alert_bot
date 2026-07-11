# GitHub Pages setup

GitHub Pages is the default website host. Cloudflare is not required.

## Enable Pages

1. Merge PR #1 into `main`.
2. Open the GitHub repository.
3. Click **Settings**.
4. In **Code and automation**, click **Pages**.
5. Under **Build and deployment → Source**, select **GitHub Actions**.
6. Open **Actions → Website Tests and GitHub Pages**.
7. If it did not start automatically after the merge, click **Run workflow** and
   select the `main` branch.
8. Wait for both the `build` and `deploy` jobs to become green.
9. Return to **Settings → Pages** and click **Visit site**.

The expected free address is:

```text
https://mahammadsad.github.io/telegram_job_alert_bot
```

## Required GitHub variables

In **Settings → Secrets and variables → Actions → Variables**, set:

```text
PUBLIC_WEBSITE_URL=https://mahammadsad.github.io/telegram_job_alert_bot
VITE_SUPABASE_URL=your Supabase project URL
VITE_SUPABASE_ANON_KEY=your Supabase anon/public key
VITE_TELEGRAM_CHANNEL_URL=your public Telegram channel URL (optional)
```

The workflow automatically configures Vite's `/telegram_job_alert_bot/` base path,
builds the website, uploads the Pages artifact, and deploys it. A generated `404.html`
keeps direct links such as `/notice/123` working on GitHub Pages.

Never add `SUPABASE_SERVICE_ROLE_KEY` to website variables. Only the public anon key
belongs in a `VITE_` variable.

## Updating the site

After this setup, every website change merged into `main` runs tests, builds, and
deploys automatically. No custom domain or paid plan is needed.
