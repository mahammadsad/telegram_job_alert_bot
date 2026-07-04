#!/usr/bin/env python3
"""
WB Government Job Scraper (RSS) -> Gemini (Strict HTML Template) -> Telegram
==============================================================================
"""

import logging
import os
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# Switched to RSS feed for reliability and speed
TARGET_SITES = [
    {"name": "Karmasandhan", "url": "https://www.karmasandhan.com/feed/"},
]

KEYWORDS = ["recruitment", "vacancy", "apply", "post"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
}

DB_FILE = "jobs.db"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Generous delay to protect the Gemini Free Tier limit
GEMINI_RATE_LIMIT_DELAY = 10 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("wb_job_scraper")


# --------------------------------------------------------------------------
# Database / Deduplication Layer
# --------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
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
# Gemini AI Layer (Strict HTML Template + Circuit Breaker)
# --------------------------------------------------------------------------

def build_gemini_prompt(title: str, content: str) -> str:
    return f"""You are a professional Bengali government-job news editor.

Read the following job notification details carefully:
TITLE: {title}
DETAILS: {content}

You MUST extract the data and fill out the EXACT HTML template below in fluent Bengali. 
Do NOT write paragraphs. Do NOT use Markdown asterisks (**). Use ONLY the <b> tags provided in the template.
If a specific detail is not found in the DETAILS text, write "বিজ্ঞপ্তি দেখুন" (See notification).

COPY THIS TEMPLATE EXACTLY AND FILL IN THE BRACKETS:

🚨 <b>নতুন সরকারি চাকরির আপডেট!</b> 🚨

🏢 <b>বিভাগ:</b> [Insert Department Name]
💼 <b>পদের নাম:</b> [Insert Post Name(s)]
📊 <b>মোট শূন্যপদ:</b> [Insert Total Vacancies]
🎓 <b>শিক্ষাগত যোগ্যতা:</b> [Insert Educational Qualifications]
⏳ <b>বয়সসীমা:</b> [Insert Age Limit]
💰 <b>বেতন:</b> [Insert Salary/Pay Scale]
📅 <b>আবেদনের শেষ তারিখ:</b> [Insert Application Deadline]
📝 <b>আবেদন পদ্ধতি:</b> [Insert How to Apply (Online/Offline)]

Output ONLY the filled HTML template."""


def generate_bengali_summary(title: str, content: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    payload = {
        "contents": [{"parts": [{"text": build_gemini_prompt(title, content)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800},
    }

    resp = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(f"{GEMINI_ENDPOINT}?key={api_key}", json=payload, timeout=30)
            
            if resp.status_code == 429:
                logger.warning(f"Attempt {attempt}: Gemini rate-limited (429). Sleeping 20s...")
                time.sleep(20)
                continue
                
            if resp.status_code != 200:
                logger.error(f"Gemini API Error {resp.status_code}: {resp.text}")
                resp.raise_for_status()

            data = resp.json()
            
            if "candidates" in data and not data["candidates"][0].get("content"):
                logger.error(f"Gemini blocked this content due to safety filters: {data}")
                return None

            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
        except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
            logger.error(f"Gemini API parsing error on attempt {attempt}: {e}")
            time.sleep(5)
            
    # Circuit Breaker Signal
    if resp is not None and resp.status_code == 429:
        return "RATE_LIMIT_EXHAUSTED"
        
    return None


# --------------------------------------------------------------------------
# Telegram Broadcast Layer
# --------------------------------------------------------------------------

def send_to_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    
    if not token or not channel_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True, 
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# --------------------------------------------------------------------------
# Scraping Layer (RSS XML Parser)
# --------------------------------------------------------------------------

def scrape_site(session: requests.Session, site_name: str, url: str, conn: sqlite3.Connection) -> int:
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return 0

    # Parse as XML
    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")
    logger.info(f"[{site_name}] Scanned {len(items)} items in RSS feed.")

    seen_this_run = set()
    new_jobs_sent = 0

    for item in items:
        title_tag = item.find("title")
        link_tag = item.find("link")
        # Handle variations in RSS feed tags for the main content
        content_tag = item.find("content:encoded") or item.find("description")
        
        if not title_tag or not link_tag:
            continue

        text = title_tag.text.strip()
        full_url = link_tag.text.strip()
        
        # Strip HTML tags out of the description payload
        article_text = ""
        if content_tag:
            article_text = BeautifulSoup(content_tag.text, "html.parser").get_text(separator="\n", strip=True)[:4000]

        if not any(kw in text.lower() for kw in KEYWORDS):
            continue

        if full_url in seen_this_run or is_job_seen(conn, full_url):
            continue
            
        seen_this_run.add(full_url)
        logger.info(f"[{site_name}] Processing: {text[:80]}")

        bengali_message = generate_bengali_summary(text, article_text)
        time.sleep(GEMINI_RATE_LIMIT_DELAY)

        # Catch the circuit breaker signal
        if bengali_message == "RATE_LIMIT_EXHAUSTED":
            logger.error("API quota exhausted. Halting the scraper to save GitHub Actions minutes.")
            return new_jobs_sent

        if not bengali_message:
            logger.warning(f"Gemini failed for '{text[:50]}'; will retry next run.")
            continue

        # Post to Telegram
        if send_to_telegram(bengali_message):
            mark_job_seen(conn, full_url, text, site_name)
            new_jobs_sent += 1
        else:
            logger.warning(f"Telegram send failed for {full_url}; will retry next run.")

    return new_jobs_sent


def main() -> None:
    conn = init_db()
    session = requests.Session()
    session.headers.update(HEADERS)

    total_new = 0
    try:
        for site in TARGET_SITES:
            total_new += scrape_site(session, site["name"], site["url"], conn)
            time.sleep(2)
    finally:
        conn.close()

    logger.info(f"Run complete. {total_new} new job(s) broadcast to Telegram.")

if __name__ == "__main__":
    main()
