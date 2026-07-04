#!/usr/bin/env python3
"""
WB Government Job Scraper -> Gemini (Comprehensive Bengali Summary) -> Telegram
==============================================================================
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

KEYWORDS = ["recruitment", "vacancy", "apply", "post"]

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
GEMINI_RATE_LIMIT_DELAY = 6 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("wb_job_scraper")


# --------------------------------------------------------------------------
# Database / deduplication layer
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
# Gemini AI layer (Comprehensive Summary)
# --------------------------------------------------------------------------

def build_gemini_prompt(title: str, content: str) -> str:
    return f"""You are a professional Bengali government-job news editor.

Read the following job notification details carefully:
TITLE: {title}
DETAILS: {content}

Write a highly detailed, comprehensive summary of this job strictly in natural, fluent Bengali. 
Extract and include crucial details such as:
- Name of the Department/Organization
- Name of the Post(s)
- Total Vacancies
- Educational Qualifications / Eligibility
- Age Limit
- Salary / Pay Scale
- Application Deadline and Important Dates
- How to apply (Online/Offline)

Format the text nicely using emojis as bullet points. 
DO NOT use Markdown like asterisks (*) or underscores (_) because it breaks the messaging app. Use standard plain text formatting with line breaks. 
DO NOT include any links, URLs, or mention the source website."""


def generate_bengali_summary(title: str, content: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    payload = {
        "contents": [{"parts": [{"text": build_gemini_prompt(title, content)}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }

    for attempt in range(1, 3):
        try:
            resp = requests.post(f"{GEMINI_ENDPOINT}?key={api_key}", json=payload, timeout=30)
            if resp.status_code == 429:
                time.sleep(15)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            logger.error(f"Gemini API error: {e}")
            time.sleep(5)
    return None


# --------------------------------------------------------------------------
# Telegram broadcast layer
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
        # Removed parse_mode completely to prevent any formatting crashes
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
# Scraping layer
# --------------------------------------------------------------------------

def scrape_site(session: requests.Session, site_name: str, url: str, conn: sqlite3.Connection) -> int:
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return 0

    soup = BeautifulSoup(resp.text, "html.parser")
    headings = soup.find_all("h2")
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

        logger.info(f"[{site_name}] Fetching inner content for: {text[:80]}")
        
        # --- NEW: Fetching the inner article content for Gemini ---
        try:
            article_resp = session.get(full_url, timeout=20)
            article_resp.raise_for_status()
            article_soup = BeautifulSoup(article_resp.text, "html.parser")
            
            # Try to grab the main entry content, fallback to all paragraphs
            content_div = article_soup.find(class_="entry-content")
            if content_div:
                article_text = content_div.get_text(separator="\n", strip=True)
            else:
                paragraphs = article_soup.find_all("p")
                article_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
                
            # Limit characters to avoid breaking Gemini's API limits
            article_text = article_text[:4000]
            
        except Exception as e:
            logger.error(f"Failed to extract inner content for {full_url}: {e}")
            continue

        bengali_message = generate_bengali_summary(text, article_text)
        time.sleep(GEMINI_RATE_LIMIT_DELAY)

        if not bengali_message:
            logger.warning(f"Gemini failed for '{text[:50]}'; will retry next run.")
            continue

        # Sending ONLY the summary. No links attached.
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
