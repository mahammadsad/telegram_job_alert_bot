#!/usr/bin/env python3
"""
WB Government Job Scraper (RSS) -> Gemini AI (Text & Image) -> Telegram
==============================================================================
Scrapes government job feeds, extracts details, generates a Bengali HTML summary
and a modern AI banner card, and broadcasts both to a Telegram channel.

FIXES applied vs. the original draft (search "# FIX:" for each spot):
  1. Telegram HTML-escaping bug that broke on any job link containing "&".
  2. Gemini now returns structured JSON instead of pre-built HTML, so the
     Python code controls escaping/formatting instead of trusting the model.
  3. DB path anchored to the script's own directory (safe for cron).
  4. Gemini model names are env-overridable (Google renames/retires these often).
  5. Global quota short-circuit across multiple feeds.
  6. Per-item try/except so one bad item can't crash the whole run.
"""

import base64
import html
import json
import logging
import os
import re
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

# FIX #3: anchor the DB to the script's own folder, not the cwd it happens to
# be launched from (important once this runs under cron/systemd).
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

# FIX #4: Gemini model names change frequently. Override via env vars without
# touching code. Before deploying, confirm these are still live for your key:
#   curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
GEMINI_TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

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

# FIX #2: Ask Gemini for structured JSON fields instead of a finished HTML
# string. This means Python (not the model) controls exactly how the final
# Telegram message is assembled and escaped -- no more trusting an LLM to
# never forget to escape a URL or insert stray text.
JOB_FIELD_KEYS = [
    "department", "post_name", "total_vacancies", "qualifications",
    "age_limit", "salary", "deadline", "apply_mode", "official_link",
]

def build_gemini_prompt(title: str, content: str) -> str:
    return f"""You are analyzing a West Bengal government job recruitment notice.

TITLE: {title}
DETAILS: {content}

Extract the following fields and respond with ONLY a single valid JSON object.
No markdown code fences, no commentary, no text before or after the JSON.

Keys (use exactly these):
- "department": department/organization name, in Bengali
- "post_name": post name(s), in Bengali
- "total_vacancies": total number of vacancies
- "qualifications": educational qualifications, in Bengali, concise (max ~25 words)
- "age_limit": age limit
- "salary": salary or pay scale
- "deadline": application deadline date
- "apply_mode": how to apply (online/offline), in Bengali
- "official_link": the single most relevant raw https:// URL for the official
  notification or application form. If none is found, use an empty string.

For any text field where the detail is genuinely not present, use the Bengali
string "বিজ্ঞপ্তি দেখুন". Do not translate or alter the official_link value."""


def extract_job_fields(title: str, content: str) -> dict | str | None:
    """Returns a dict of fields, the sentinel string "RATE_LIMIT_EXHAUSTED", or None on failure."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    payload = {
        "contents": [{"parts": [{"text": build_gemini_prompt(title, content)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 800,
            "responseMimeType": "application/json",
        },
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
            candidates = data.get("candidates")
            if not candidates or not candidates[0].get("content"):
                logger.error(f"Gemini returned no usable content (likely safety block): {data}")
                return None

            raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
            # Defensive: strip accidental ```json fences even though we asked
            # for raw JSON via responseMimeType.
            raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()

            fields = json.loads(raw_text)
            missing = [k for k in JOB_FIELD_KEYS if k not in fields]
            if missing:
                logger.warning(f"Gemini JSON missing keys {missing}; filling defaults.")
                for k in missing:
                    fields[k] = ""
            return fields

        except json.JSONDecodeError as e:
            logger.error(f"Gemini did not return valid JSON on attempt {attempt}: {e}")
            time.sleep(5)
        except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
            logger.error(f"Gemini Text API parsing error on attempt {attempt}: {e}")
            time.sleep(5)

    if resp is not None and resp.status_code == 429:
        return "RATE_LIMIT_EXHAUSTED"

    return None


def build_telegram_message(fields: dict) -> str:
    """Assembles the final Bengali HTML caption ourselves, escaping every
    inserted value. This is what actually fixes the '&' -> Bad Request bug."""

    def esc(value) -> str:
        text = str(value).strip() if value else "বিজ্ঞপ্তি দেখুন"
        return html.escape(text, quote=False)

    link_raw = str(fields.get("official_link") or "").strip()
    link = html.escape(link_raw, quote=False) if link_raw else "অফিসিয়াল ওয়েবসাইট দেখুন"

    return (
        "🚨 <b>নতুন সরকারি চাকরির আপডেট!</b> 🚨\n\n"
        f"🏢 <b>বিভাগ:</b> {esc(fields.get('department'))}\n"
        f"💼 <b>পদের নাম:</b> {esc(fields.get('post_name'))}\n"
        f"📊 <b>মোট শূন্যপদ:</b> {esc(fields.get('total_vacancies'))}\n"
        f"🎓 <b>শিক্ষাগত যোগ্যতা:</b> {esc(fields.get('qualifications'))}\n"
        f"⏳ <b>বয়সসীমা:</b> {esc(fields.get('age_limit'))}\n"
        f"💰 <b>বেতন:</b> {esc(fields.get('salary'))}\n"
        f"📅 <b>আবেদনের শেষ তারিখ:</b> {esc(fields.get('deadline'))}\n"
        f"📝 <b>আবেদন পদ্ধতি:</b> {esc(fields.get('apply_mode'))}\n"
        f"🔗 <b>অফিসিয়াল লিঙ্ক:</b> {link}"
    )


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

def scrape_site(session: requests.Session, site_name: str, url: str, conn: sqlite3.Connection) -> tuple[int, bool]:
    """Returns (new_jobs_sent, quota_exhausted)."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return 0, False

    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")
    logger.info(f"[{site_name}] Scanned {len(items)} items in RSS feed.")

    seen_this_run = set()
    new_jobs_sent = 0

    for item in items:
        try:
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

            # Extract structured fields via Gemini
            fields = extract_job_fields(text, article_text)
            time.sleep(GEMINI_RATE_LIMIT_DELAY)

            if fields == "RATE_LIMIT_EXHAUSTED":
                logger.error("API quota exhausted. Halting scraper run.")
                return new_jobs_sent, True

            if not fields:
                logger.warning(f"Gemini extraction failed for '{text[:50]}'; skipping.")
                continue

            bengali_message = build_telegram_message(fields)

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

        except Exception as e:
            # FIX #6: one malformed item shouldn't take down the whole run.
            logger.error(f"Unexpected error processing an item from {site_name}: {e}", exc_info=True)
            continue

    return new_jobs_sent, False


def main() -> None:
    conn = init_db()
    session = requests.Session()
    session.headers.update(HEADERS)

    total_new = 0
    try:
        for site in TARGET_SITES:
            new_jobs, quota_exhausted = scrape_site(session, site["name"], site["url"], conn)
            total_new += new_jobs
            if quota_exhausted:
                logger.error("Stopping run early: Gemini quota exhausted.")
                break
            time.sleep(2)
    finally:
        conn.close()

    logger.info(f"Run complete. {total_new} new job(s) broadcast to Telegram.")

if __name__ == "__main__":
    main()
