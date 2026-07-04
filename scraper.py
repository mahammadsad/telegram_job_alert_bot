#!/usr/bin/env python3
"""
WB Government Job Scraper -> Gemini (Bengali summary) -> Telegram Broadcaster
==============================================================================

Scrapes a West Bengal government job aggregator for new recruitment posts,
summarizes each one in Bengali using the Gemini API free tier, and posts
the result to a Telegram channel. Designed to run on a schedule inside
GitHub Actions with no external server.

Required environment variables (set as GitHub Secrets):
    TELEGRAM_BOT_TOKEN   - Bot token from @BotFather
    TELEGRAM_CHANNEL_ID  - e.g. "@your_channel" or a numeric chat id
    GEMINI_API_KEY       - API key from Google AI Studio (free tier)

Why an aggregator instead of psc.wb.gov.in / prb.wb.gov.in / mscwb.org
directly: those three official portals turned out to be unreliable from
GitHub Actions runners in testing -- psc.wb.gov.in's robots.txt disallows
bots, prb.wb.gov.in and mscwb.org have broken/legacy TLS configs or block
cloud-provider IP ranges outright. westbengalcareers.com is a WordPress-
based aggregator that republishes the same official notices (WBPSC,
WBPRB, WBMSC, and other WB government bodies) in consistent, crawlable
HTML, and its data was current (same-week postings) when this was tested.

Parsing strategy: on this site's category archive page, every real job
post title is rendered as an `<h2>` tag wrapping a single `<a>` link
(standard WordPress post-loop markup). Site navigation, the sidebar, and
footer links are NOT wrapped in `<h2>`, so restricting extraction to
`<h2><a>` pairs naturally filters out nav/social/footer noise without
needing an aggressive keyword blocklist. A short keyword allowlist is
still applied as a secondary safety net.

If you add more sources later: different job sites use different themes
and layouts, so each new site will likely need its own small extraction
function rather than assuming this same `<h2><a>` pattern applies.
"""

import logging
import os
import sqlite3
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

TARGET_SITES = [
    {"name": "WestBengalCareers", "url": "https://www.westbengalcareers.com/wb-govt-jobs/"},
]

# Secondary safety net only -- primary filtering is structural (see scrape_site).
# A post title must contain at least one of these to be broadcast.
KEYWORDS = ["recruitment", "vacancy", "apply", "post"]

# Belt-and-braces: skip anything matching these even if it slipped through
# the structural <h2><a> filter (e.g. a theme quirk wraps a nav item in h2).
JUNK_TEXT = {
    "home", "contact us", "contact", "about us", "sitemap",
    "privacy policy", "terms of use", "terms & conditions",
    "disclaimer", "older posts", "newer posts", "next", "previous",
    "read more", "leave a comment",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
}

DB_FILE = "jobs.db"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_RATE_LIMIT_DELAY = 6  # seconds -- keeps us at <=10 requests/minute on the free tier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("wb_job_scraper")


# --------------------------------------------------------------------------
# Database / deduplication layer
# --------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Creates jobs.db (if needed) and the seen_jobs table."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            source TEXT,
            found_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    return conn


def is_job_seen(conn: sqlite3.Connection, url: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen_jobs WHERE url = ? LIMIT 1", (url,))
    return cur.fetchone() is not None


def mark_job_seen(conn: sqlite3.Connection, url: str, title: str, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs (url, title, source) VALUES (?, ?, ?)",
        (url, title, source),
    )
    conn.commit()


# --------------------------------------------------------------------------
# robots.txt compliance
# --------------------------------------------------------------------------

def is_scraping_allowed(url: str, user_agent: str) -> bool:
    """
    Checks the target site's robots.txt before scraping it.
    If robots.txt cannot be read at all (network hiccup, no file), we
    proceed cautiously (default-allow), matching the standard robots.txt
    convention. If it explicitly disallows the path, we respect that.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception as e:
        logger.warning(f"Could not read {robots_url} ({e}); proceeding cautiously.")
        return True


# --------------------------------------------------------------------------
# Gemini AI layer (Bengali summary generation)
# --------------------------------------------------------------------------

def build_gemini_prompt(title: str, source_name: str) -> str:
    return f"""You are a professional Bengali government-job news editor.

Given this English notification title from {source_name}, an official West Bengal government recruitment body:

"{title}"

Write a Telegram broadcast message STRICTLY and ENTIRELY in fluent, natural Bengali (no English words except unavoidable proper nouns). Follow this EXACT structure, keeping the emoji and Markdown bold (*text*) exactly as shown:

🚨 *নতুন সরকারি চাকরির আপডেট!* 🚨

🏢 *বিভাগ:* [department name in Bengali, inferred from the title]
💼 *পদের নাম:* [post/job name in Bengali]
🎓 *যোগ্যতা:* [likely eligibility inferred from the title, or "বিস্তারিত জানতে বিজ্ঞপ্তি দেখুন" if unclear]
📅 *আবেদনের শেষ তারিখ:* [date if present in the title, or "বিজ্ঞপ্তি দেখুন" if not]

Output ONLY the four-line block above, fully in Bengali. Do not add a preamble, explanation, the source link, or code block formatting."""


def generate_bengali_summary(title: str, source_name: str) -> str | None:
    """Calls the Gemini API and returns the Bengali summary text, or None on failure."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    payload = {
        "contents": [{"parts": [{"text": build_gemini_prompt(title, source_name)}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400},
    }

    for attempt in range(1, 3):
        try:
            resp = requests.post(f"{GEMINI_ENDPOINT}?key={api_key}", json=payload, timeout=30)

            if resp.status_code == 429:
                logger.warning("Gemini rate-limited (429). Backing off 15s before retry...")
                time.sleep(15)
                continue

            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            logger.error(f"Gemini API error (attempt {attempt}/2): {e}")
            time.sleep(5)

    return None


# --------------------------------------------------------------------------
# Telegram broadcast layer
# --------------------------------------------------------------------------

def send_to_telegram(message: str) -> bool:
    """Posts a message to the configured Telegram channel. Returns True on success."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token or not channel_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is not set.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 400:
            # Gemini's free-form Bengali text can occasionally contain characters
            # that break Telegram's legacy Markdown parser (stray * or _).
            # Retry once as plain text so the job still gets delivered.
            logger.warning("Telegram rejected Markdown formatting; retrying as plain text.")
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# --------------------------------------------------------------------------
# Scraping layer
# --------------------------------------------------------------------------

def scrape_site(session: requests.Session, site_name: str, url: str, conn: sqlite3.Connection) -> int:
    """Scrapes one site, broadcasts any new job postings, returns count of new jobs sent."""
    if not is_scraping_allowed(url, HEADERS["User-Agent"]):
        logger.warning(f"[{site_name}] robots.txt disallows automated access to {url}. Skipping.")
        return 0

    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"[{site_name}] Failed to fetch {url}: {e}")
        return 0

    soup = BeautifulSoup(resp.text, "html.parser")

    # Structural extraction: each real post title on this site's category
    # archive page is an <h2> wrapping a single <a>. Section headings that
    # aren't posts (e.g. "Post Wise Recruitment in West Bengal") are plain
    # <h2> tags with no link, so they're skipped automatically.
    headings = soup.find_all("h2")
    logger.info(f"[{site_name}] Scanned {len(headings)} <h2> headings on {url}")

    seen_this_run = set()
    new_jobs_sent = 0

    for h2 in headings:
        a = h2.find("a", href=True)
        if a is None:
            continue

        text = a.get_text(strip=True)
        href = a["href"].strip()

        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if not text or text.lower() in JUNK_TEXT or len(text) < 6:
            continue
        if not any(kw in text.lower() for kw in KEYWORDS):
            continue

        full_url = urljoin(url, href)
        if full_url in seen_this_run:
            continue
        seen_this_run.add(full_url)

        if is_job_seen(conn, full_url):
            continue

        job_title = text
        logger.info(f"[{site_name}] New job found: {job_title[:80]}")

        bengali_message = generate_bengali_summary(job_title, site_name)
        time.sleep(GEMINI_RATE_LIMIT_DELAY)  # always pause after a Gemini call attempt

        if not bengali_message:
            logger.warning(f"[{site_name}] Gemini failed for '{job_title[:50]}'; will retry next run.")
            continue

        final_message = f"{bengali_message}\n\n🔗 [বিস্তারিত দেখুন/আবেদন করুন]({full_url})"

        if send_to_telegram(final_message):
            mark_job_seen(conn, full_url, job_title, site_name)
            new_jobs_sent += 1
        else:
            logger.warning(f"[{site_name}] Telegram send failed for {full_url}; will retry next run.")

    return new_jobs_sent


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> None:
    required_env = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "GEMINI_API_KEY"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise SystemExit(1)

    conn = init_db()
    session = requests.Session()
    session.headers.update(HEADERS)

    total_new = 0
    try:
        for site in TARGET_SITES:
            total_new += scrape_site(session, site["name"], site["url"], conn)
            time.sleep(2)  # be polite between sites
    finally:
        conn.close()

    logger.info(f"Run complete. {total_new} new job(s) broadcast to Telegram.")


if __name__ == "__main__":
    main()
