from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

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
    NoticeSubtype.DEADLINE_REMINDER: "শেষ তারিখের স্মরণিকা",
    NoticeSubtype.RESULT_PUBLISHED: "ফল প্রকাশ",
    NoticeSubtype.ADMIT_CARD_RELEASED: "অ্যাডমিট কার্ড",
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
    public = public_fields(extracted)
    fact_pairs: list[tuple[str, object]] = public[:2]
    scope_labels = {
        "WEST_BENGAL_ONLY": "শুধু পশ্চিমবঙ্গ", "WEST_BENGAL": "পশ্চিমবঙ্গ",
        "ALL_INDIA": "সর্বভারতীয়", "OTHER_STATE_OPEN_TO_ALL": "অন্য রাজ্য—সবার জন্য উন্মুক্ত",
        "LOCAL_LANGUAGE_REQUIRED": "ভাষার শর্তসহ আবেদনযোগ্য",
    }
    if extracted.eligibility_scope:
        fact_pairs.append(("eligibility_scope", scope_labels.get(
            extracted.eligibility_scope.value, extracted.eligibility_scope.value
        )))
    deadline = extracted.fields.get("deadline")
    if deadline and deadline.value:
        fact_pairs.append(("deadline", deadline.value))
    if extracted.local_language_required:
        fact_pairs.append(("language_requirement", extracted.required_language or "অফিসিয়াল নোটিশ দেখুন"))
    elif extracted.domicile_required is not None:
        domicile = extracted.domicile_state or ("প্রয়োজন" if extracted.domicile_required else "প্রয়োজন নেই")
        fact_pairs.append(("domicile", domicile))
    elif extracted.work_location:
        fact_pairs.append(("work_location", extracted.work_location))
    fact_pairs.extend(public[2:])
    seen: set[str] = set()
    facts = []
    extra_labels = {
        "eligibility_scope": "আবেদনযোগ্যতা", "language_requirement": "ভাষার শর্ত",
        "domicile": "ডোমিসাইল", "work_location": "প্রযোজ্য স্থান",
    }
    for name, value in fact_pairs:
        if name in seen:
            continue
        seen.add(name)
        facts.append({
            "label": extra_labels.get(name, FIELD_LABELS.get(name, name.replace("_", " ").title())),
            "value": shorten_fact(value),
        })
        if len(facts) == 5:
            break
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


class SharedCardRenderer:
    """Lazy reusable Chromium/page for a complete synchronous pipeline run."""
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def generate(
        self, notice: ExtractedNotice, category: NoticeCategory | None = None,
        status: VerificationStatus = VerificationStatus.VERIFIED_OFFICIAL,
        admin: bool = False,
    ) -> bytes:
        if category is not None and notice.category != category:
            raise ValueError("notice category does not match requested template")
        if self._page is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._page = self._browser.new_page(viewport={"width":1080,"height":1080},device_scale_factor=1)
        self._page.set_content(render_html(notice, status, admin=admin), wait_until="networkidle")
        self._page.evaluate("() => document.fonts.ready")
        return self._page.screenshot(type="png", full_page=False)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None
