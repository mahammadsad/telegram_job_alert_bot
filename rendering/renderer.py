from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from config.loader import load_yaml
from processing.formatter import FIELD_LABELS, public_fields
from processing.models import ExtractedNotice, NoticeCategory, NoticeSubtype, VerificationStatus
from rendering.category_styles import STYLES


TEMPLATES = Path(__file__).resolve().parent / "templates"
CARD_SUBTYPE_LABELS = {
    NoticeSubtype.UPDATED: "আপডেট",
    NoticeSubtype.CORRIGENDUM: "সংশোধনী",
    NoticeSubtype.CANCELLED: "বাতিল",
    NoticeSubtype.DEADLINE_EXTENDED: "সময়সীমা বৃদ্ধি",
}


def shorten_headline(value: str, limit: int = 105) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    shortened = clean[: limit + 1].rsplit(" ", 1)[0]
    return (shortened or clean[:limit]).rstrip("।,;:- ") + "…"


def shorten_fact(value: object, limit: int = 78) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    shortened = clean[: limit + 1].rsplit(" ", 1)[0]
    return (shortened or clean[:limit]).rstrip("।,;:- ") + "…"


def render_html(extracted: ExtractedNotice, status: VerificationStatus, admin: bool = False) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    config = load_yaml("categories.yaml")["categories"][extracted.category.value]
    primary, accent, icon = STYLES[extracted.category]
    facts = [
        {
            "label": FIELD_LABELS.get(name, name.replace("_", " ").title()),
            "value": shorten_fact(value),
        }
        for name, value in public_fields(extracted, limit=4)
    ]
    template = environment.get_template(f"{extracted.category.value.lower()}.html")
    return template.render(
        title=shorten_headline(extracted.title_bn),
        category_label=(
            config["label"]
            if extracted.subtype == NoticeSubtype.NEW
            else f"{config['label']} • {CARD_SUBTYPE_LABELS[extracted.subtype]}"
        ),
        primary=primary,
        accent=accent,
        icon=icon,
        facts=facts,
        verified=status == VerificationStatus.VERIFIED_OFFICIAL,
        review=admin and status != VerificationStatus.VERIFIED_OFFICIAL,
    )


async def _screenshot(markup: str) -> bytes:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
        await page.set_content(markup, wait_until="networkidle")
        await page.evaluate("() => document.fonts.ready")
        result = await page.screenshot(type="png", full_page=False)
        await browser.close()
        return result


def generate_notice_card(
    notice: ExtractedNotice,
    category: NoticeCategory | None = None,
    status: VerificationStatus = VerificationStatus.VERIFIED_OFFICIAL,
    admin: bool = False,
) -> bytes:
    if category is not None and notice.category != category:
        raise ValueError("notice category does not match requested template")
    markup = render_html(notice, status, admin=admin)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_screenshot(markup))
    raise RuntimeError("generate_notice_card cannot run inside an active async event loop")
