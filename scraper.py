#!/usr/bin/env python3
"""
WB Government Job Scraper (RSS) -> Gemini AI (Text & Image) -> Telegram
==============================================================================
Scrapes government job feeds, extracts details, generates a Bengali HTML summary
and a modern AI banner card, and broadcasts both to a Telegram channel.
"""

import base64
import logging
import os
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

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

# Gemini Models
GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

GEMINI_TEXT_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TEXT_MODEL}:generateContent"
GEMINI_IMAGE_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"

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
# Gemini AI Layer (Text & Image Generation)
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
🔗 <b>অফিসিয়াল লিঙ্ক:</b> [Insert the raw https:// URL of the official government website or application link found in the details. Do NOT use HTML <a> tags. Just write the raw URL so it becomes clickable. If no official link is found, write "অফিসিয়াল ওয়েবসাইট দেখুন"]

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
            resp = requests.post(f"{GEMINI_TEXT_ENDPOINT}?key={api_key}", json=payload, timeout=30)
            
            if resp.status_code == 429:
                logger.warning(f"Attempt {attempt}: Gemini text generation rate-limited (429). Sleeping 20s...")
                time.sleep(20)
                continue
                
            if resp.status_code != 200:
                logger.error(f"Gemini Text API Error {resp.status_code}: {resp.text}")
                resp.raise_for_status()

            data = resp.json()
            if "candidates" in data and not data["candidates"][0].get("content"):
                logger.error(f"Gemini blocked text content due to safety filters: {data}")
                return None

            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
        except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
            logger.error(f"Gemini Text API parsing error on attempt {attempt}: {e}")
            time.sleep(5)
            
    if resp is not None and resp.status_code == 429:
        return "RATE_LIMIT_EXHAUSTED"
        
    return None


def generate_job_image(title: str, content: str) -> bytes | None:
    """Generates a modern AI banner image featuring Bengali typography for the job post."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    logger.info("Generating AI banner image for job post...")
    
    prompt = (
        f"Create a modern, vibrant, high-resolution digital announcement card/banner for a West Bengal government job vacancy.\n"
        f"Job Title: {title}\n"
        f"Context Details: {content[:400]}\n\n"
        f"Visual Requirements:\n"
        f"- Professional Indian government employment infographic aesthetic.\n"
        f"- Include clean, legible Bengali typography summarizing the job title/post prominently on the banner.\n"
        f"- Color scheme: Deep corporate royal blue, elegant gold, and clean white highlights.\n"
        f"- Modern layout featuring subtle digital UI elements, official-style badges, and clean design composition suitable for social media announcement."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"]
        }
    }

    try:
        resp = requests.post(f"{GEMINI_IMAGE_ENDPOINT}?key={api_key}", json=payload, timeout=45)
        
        if resp.status_code == 429:
            logger.warning("Gemini Image API rate-limited (429). Skipping image generation.")
            return None
            
        if resp.status_code != 200:
            logger.warning(f"Gemini Image API Error {resp.status_code}: {resp.text}")
            return None

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and "data" in inline_data:
                logger.info("AI banner image successfully generated.")
                return base64.b64decode(inline_data["data"])
                
    except Exception as e:
        logger.error(f"Image generation failed: {e}")

    return None


# --------------------------------------------------------------------------
# Telegram Broadcast Layer
# --------------------------------------------------------------------------

def send_to_telegram(message: str, image_bytes: bytes | None = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    
    if not token or not channel_id:
        logger.error("Telegram credentials missing.")
        return False

    # Attempt to send as Photo if image exists
    if image_bytes:
        photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
        
        # Telegram sendPhoto captions have a strict 1024-character limit
        if len(message) <= 1000:
            try:
                files = {"photo": ("job_post.png", image_bytes, "image/png")}
                payload = {
                    "chat_id": channel_id,
                    "caption": message,
                    "parse_mode": "HTML"
                }
                resp = requests.post(photo_url, data=payload, files=files, timeout=30)
                resp.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                logger.warning(f"Telegram sendPhoto with caption failed ({e}). Attempting split broadcast...")

        # If caption exceeds 1000 chars or combined send failed: Send photo first, then text
        try:
            files = {"photo": ("job_post.png", image_bytes, "image/png")}
            resp_img = requests.post(photo_url, data={"chat_id": channel_id}, files=files, timeout=30)
            resp_img.raise_for_status()
            logger.info("Standalone image banner broadcast successfully.")
        except Exception as e:
            logger.warning(f"Failed to send image banner: {e}")

    # Broadcast standard Text Message (up to 4096 chars)
    text_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True, 
    }

    try:
        resp = requests.post(text_url, json=payload, timeout=20)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram sendMessage failed: {e}")
        return False


# --------------------------------------------------------------------------
# Scraping Layer (RSS XML Parser + Official Link Extractor)
# --------------------------------------------------------------------------

def scrape_site(session: requests.Session, site_name: str, url: str, conn: sqlite3.Connection) -> int:
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return 0

    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")
    logger.info(f"[{site_name}] Scanned {len(items)} items in RSS feed.")

    seen_this_run = set()
    new_jobs_sent = 0

    for item in items:
        title_tag = item.find("title")
        link_tag = item.find("link")
        content_tag = item.find("content:encoded") or item.find("description")
        
        if not title_tag or not link_tag:
            continue

        text = title_tag.text.strip()
        full_url = link_tag.text.strip()
        
        if not any(kw in text.lower() for kw in KEYWORDS):
            continue

        if full_url in seen_this_run or is_job_seen(conn, full_url):
            continue
            
        seen_this_run.add(full_url)
        logger.info(f"[{site_name}] Processing: {text[:80]}")

        article_text = ""
        if content_tag:
            content_html = content_tag.text
            article_soup = BeautifulSoup(content_html, "html.parser")
            
            # 1. Extract external links BEFORE stripping HTML
            external_links = []
            for a_tag in article_soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                anchor_text = a_tag.get_text(strip=True)
                
                lower_href = href.lower()
                if not href or href.startswith(("#", "javascript", "mailto")):
                    continue
                if any(junk in lower_href for junk in ["karmasandhan.com", "t.me", "facebook.com", "whatsapp", "twitter.com"]):
                    continue
                
                external_links.append(f"{anchor_text}: {href}")
            
            # 2. Extract plain text
            article_text = article_soup.get_text(separator="\n", strip=True)
            
            # 3. Append extracted links for Gemini analysis
            if external_links:
                unique_links = list(dict.fromkeys(external_links))[:5]
                article_text += "\n\nPOSSIBLE OFFICIAL LINKS FOUND:\n" + "\n".join(unique_links)

        article_text = article_text[:4000]

        # Generate Text Summary
        bengali_message = generate_bengali_summary(text, article_text)
        time.sleep(GEMINI_RATE_LIMIT_DELAY)

        if bengali_message == "RATE_LIMIT_EXHAUSTED":
            logger.error("API quota exhausted. Halting scraper run.")
            return new_jobs_sent

        if not bengali_message:
            logger.warning(f"Gemini summary failed for '{text[:50]}'; skipping.")
            continue

        # Generate AI Image Banner
        image_bytes = generate_job_image(text, article_text)
        if image_bytes:
            time.sleep(5)  # Brief pause between AI calls

        # Broadcast to Telegram
        if send_to_telegram(bengali_message, image_bytes):
            mark_job_seen(conn, full_url, text, site_name)
            new_jobs_sent += 1
        else:
            logger.warning(f"Telegram broadcast failed for {full_url}; will retry next run.")

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
