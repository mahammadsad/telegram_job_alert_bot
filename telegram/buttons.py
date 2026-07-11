from __future__ import annotations

import os
from urllib.parse import urlparse

from processing.formatter import official_links
from processing.models import ExtractedNotice
from processing.verifier import validate_official_url


def build_url_keyboard(extracted: ExtractedNotice, trusted_domains: set[str], notice_id: int | None = None) -> dict | None:
    buttons = [
        {"text": label, "url": url}
        for label, url in official_links(extracted)
        if validate_official_url(url, trusted_domains)
    ][:4]
    website = os.getenv("PUBLIC_WEBSITE_URL", "").rstrip("/")
    if website and notice_id is not None:
        parsed = urlparse(website)
        try:
            safe = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and parsed.port in {None,443}
        except ValueError:
            safe = False
        if safe:
            buttons.append({"text":"ওয়েবসাইটে সম্পূর্ণ তথ্য","url":f"{website}/notice/{notice_id}"})
    if not buttons:
        return None
    return {"inline_keyboard": [[button] for button in buttons]}
