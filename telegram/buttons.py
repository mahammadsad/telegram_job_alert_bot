from __future__ import annotations

from processing.formatter import official_links
from processing.models import ExtractedNotice
from processing.verifier import validate_official_url


def build_url_keyboard(extracted: ExtractedNotice, trusted_domains: set[str]) -> dict | None:
    buttons = [
        {"text": label, "url": url}
        for label, url in official_links(extracted)
        if validate_official_url(url, trusted_domains)
    ][:4]
    if not buttons:
        return None
    return {"inline_keyboard": [[button] for button in buttons]}

