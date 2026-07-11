from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import fitz
import pytest
import requests
from pydantic import ValidationError

from database.db import NoticeRepository, connect
from processing.classifier import classify
from processing.deduplicator import is_changed_revision, same_notice
from processing.formatter import format_telegram_message
from processing.models import (
    EligibilityScope,
    EvidenceValue,
    ExtractedNotice,
    NoticeCategory,
    PipelineNotice,
    VerificationStatus,
)
from processing.schemas import CATEGORY_FIELDS
from processing.validators import (
    evidence_supported,
    valid_currency,
    valid_date,
    valid_age_limit,
    valid_percentage,
    valid_vacancy,
    validate_extraction,
)
from processing.verifier import SafeFetcher, canonicalize_url, find_official_document, hostname_is_trusted, validate_official_url
from rendering.renderer import generate_notice_card, render_html, shorten_headline
from sources.base import SourceConfig
from sources.html_source import HTMLSource
from sources.pdf_source import extract_pdf
from sources.rss_source import RSSSource
from telegram.sender import CAPTION_LIMIT, TelegramSender, should_split_caption


FIXTURES = Path(__file__).parent / "fixtures"
TRUSTED = {"wb.gov.in", "psc.wb.gov.in"}


def field(value=None, evidence=None, url="https://psc.wb.gov.in/notice.pdf"):
    return EvidenceValue(value=value, evidence=evidence, evidence_page=1 if evidence else None, source_url=url)


def job_notice(valid=True, scope=EligibilityScope.WEST_BENGAL):
    values = {name: field() for name in CATEGORY_FIELDS[NoticeCategory.JOB]}
    values.update(
        department=field("WBPSC", "WBPSC"),
        post_name=field("Clerk", "Clerk"),
        qualifications=field("Graduate", "Graduate"),
        total_vacancies=field("350", "350 vacancies"),
        deadline=field("31.07.2026", "Last date: 31.07.2026"),
        official_notification_url=field(
            "https://psc.wb.gov.in/notice.pdf",
            "https://psc.wb.gov.in/notice.pdf",
        ),
    )
    if not valid:
        values["total_vacancies"] = field("999", "350 vacancies")
    return ExtractedNotice(
        category=NoticeCategory.JOB,
        title_bn="ক্লার্ক নিয়োগ বিজ্ঞপ্তি",
        issuing_authority=field("WBPSC", "WBPSC"),
        fields=values,
        eligibility_scope=scope,
        eligibility_reason="West Bengal recruitment",
    )


def source_text():
    return "WBPSC Clerk Graduate 350 vacancies Last date: 31.07.2026 https://psc.wb.gov.in/notice.pdf"


def response(url, status=200, body=b"ok", location=None, content_type="text/html"):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result._content = body
    result.headers["Content-Type"] = content_type
    if location:
        result.headers["Location"] = location
    return result


class QueueSession:
    def __init__(self, responses=None, error_first=False):
        self.responses = list(responses or [])
        self.calls = []
        self.error_first = error_first

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/robots.txt"):
            return response(url, status=404)
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.error_first:
            self.error_first = False
            raise requests.ConnectionError("photo failed")
        return response(url, body=b'{"ok":true,"result":{"message_id":42}}', content_type="application/json")


def test_trusted_domain_validation():
    assert hostname_is_trusted("psc.wb.gov.in", TRUSTED)
    assert hostname_is_trusted("files.psc.wb.gov.in", TRUSTED)


@pytest.mark.parametrize("host", ["psc.wb.gov.in.evil.test", "fake-wb.gov.in.test", "evilwb.gov.in", "bit.ly"])
def test_malicious_lookalike_domains(host):
    assert not hostname_is_trusted(host, TRUSTED)
    assert not validate_official_url(f"https://{host}/notice", TRUSTED)


def test_invalid_protocol_and_port_are_rejected():
    assert not validate_official_url("http://wb.gov.in/notice", TRUSTED)
    assert not validate_official_url("https://wb.gov.in:8443/notice", TRUSTED)


def test_redirect_validation_accepts_trusted_chain():
    session = QueueSession([
        response("https://wb.gov.in/start", 302, location="https://psc.wb.gov.in/final"),
        response("https://psc.wb.gov.in/final", body=b"notice"),
    ])
    final, chain = SafeFetcher(TRUSTED, session=session).fetch("https://wb.gov.in/start")
    assert final.url.endswith("/final") and len(chain) == 2


def test_redirect_validation_rejects_unknown_target():
    session = QueueSession([response("https://wb.gov.in/start", 302, location="https://evil.test/login")])
    with pytest.raises(ValueError, match="untrusted"):
        SafeFetcher(TRUSTED, session=session).fetch("https://wb.gov.in/start")


def test_url_canonicalization():
    assert canonicalize_url("HTTPS://PSC.WB.GOV.IN/a/?utm_source=x&b=2") == "https://psc.wb.gov.in/a?b=2"


def test_rss_parsing():
    config = SourceConfig("Karmasandhan", "https://www.karmasandhan.com/feed/", "rss", ["JOB"], allowed_domains=("karmasandhan.com",))
    items = RSSSource(config).parse((FIXTURES / "feed.xml").read_bytes(), config.url)
    assert len(items) == 1 and items[0].candidate_official_links == ["https://psc.wb.gov.in/notice.pdf"]


def test_html_parsing_with_verified_selectors():
    config = SourceConfig(
        "Official", "https://wb.gov.in/notices", "html", ["ADMISSION"], official=True,
        discovery_only=False, item_selector="article.notice", title_selector="h2", link_selector="a.details",
    )
    items = HTMLSource(config).parse((FIXTURES / "listing.html").read_bytes(), config.url)
    assert items[0].discovery_url == "https://wb.gov.in/notice/1"


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_pdf_text_extraction_and_page_numbers():
    parsed = extract_pdf((FIXTURES / "official_notice.pdf").read_bytes(), "https://wb.gov.in/n.pdf")
    assert "[PAGE 1]" in parsed.text and not parsed.scanned_pdf and parsed.content_sha256


def test_scanned_pdf_requires_review():
    assert extract_pdf(make_pdf(""), "https://wb.gov.in/scan.pdf").scanned_pdf


def test_ai_json_enum_validation():
    data = job_notice().model_dump(mode="json")
    data["category"] = "INVENTED"
    with pytest.raises(ValidationError):
        ExtractedNotice.model_validate(data)


def test_unsupported_evidence_rejection():
    assert not evidence_supported("not present", source_text())
    result = validate_extraction(job_notice(valid=False), source_text(), TRUSTED)
    assert not result.valid and any("unsupported value" in error for error in result.errors)


def test_date_currency_and_vacancy_validation():
    assert valid_date("31 July 2026") and not valid_date("soon")
    assert valid_currency("₹3,000") and not valid_currency("many rupees")
    assert valid_vacancy("350 vacancies") and not valid_vacancy("unknown")
    assert valid_percentage("75%") and not valid_percentage("175%")
    assert valid_age_limit("18-30 years") and not valid_age_limit("180 years")


def test_conflicting_deadlines_require_review():
    text = source_text() + "\nLast date: 15.08.2026"
    result = validate_extraction(job_notice(), text, TRUSTED)
    assert not result.valid and result.conflicts == ["conflicting date: deadline"]


def test_category_classification_is_controlled():
    assert classify("Exam result published") == NoticeCategory.RESULT
    assert isinstance(classify("general notice"), NoticeCategory)


def test_duplicate_and_changed_content_detection():
    assert same_notice("https://wb.gov.in/a", "abc", "https://wb.gov.in/a/", "abc")
    assert is_changed_revision("abc", "def")


def test_existing_database_migration_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE seen_jobs(id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT, source TEXT, found_at TEXT)")
    raw.execute("INSERT INTO seen_jobs(url,title,source,found_at) VALUES ('https://x.test/1','Old','Feed','2025-01-01')")
    raw.commit(); raw.close()
    conn = connect(path); conn.close()
    conn = connect(path)
    assert conn.execute("SELECT count(*) FROM notices WHERE verification_status='POSTED'").fetchone()[0] == 1
    conn.close()


def test_changed_content_creates_revision(tmp_path):
    conn = connect(tmp_path / "revision.db")
    repo = NoticeRepository(conn)
    notice = PipelineNotice(category="JOB", title="N", discovery_url="https://x.test", source_name="x", content_sha256="a", final_resolved_url="https://wb.gov.in/n")
    notice.id = repo.upsert_discovered(notice)
    repo.save_verification(notice)
    notice.content_sha256 = "b"
    assert repo.save_verification(notice) == 2
    assert conn.execute("SELECT count(*) FROM notice_revisions").fetchone()[0] == 2
    conn.close()


def test_bengali_html_formatting_escapes_source_values():
    notice = job_notice()
    notice.title_bn = "চাকরি <script>alert(1)</script>"
    message = format_telegram_message(notice)
    assert "&lt;script&gt;" in message and "অফিসিয়াল উৎস থেকে যাচাইকৃত" in message
    hashtags = [part for part in message.split() if part.startswith("#")]
    assert 2 <= len(hashtags) <= 4


def test_long_bengali_headline_wrapping_and_html_safety():
    title = "খুব দীর্ঘ বাংলা সরকারি বিজ্ঞপ্তির শিরোনাম " * 8
    shortened = shorten_headline(title)
    assert len(shortened) <= 106 and shortened.endswith("…")
    notice = job_notice(); notice.title_bn = title + " <bad>"
    markup = render_html(notice, VerificationStatus.VERIFIED_OFFICIAL)
    assert "<bad>" not in markup and "অফিসিয়াল উৎস" in markup


def test_png_generation_1080_square():
    image = generate_notice_card(job_notice())
    # PNG IHDR stores the actual pixel dimensions at bytes 16..24. PDF-style
    # readers may rescale a 96-DPI PNG to 72-DPI display points (810×810).
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", image[16:24]) == (1080, 1080)


def test_telegram_caption_length_handling():
    assert not should_split_caption("x" * CAPTION_LIMIT)
    assert should_split_caption("x" * (CAPTION_LIMIT + 1))


def test_telegram_photo_failure_falls_back_to_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@channel")
    session = QueueSession(error_first=True)
    result = TelegramSender(session=session).send("verified", b"png")
    assert result.success and len(session.calls) == 2


def test_aggregator_only_notice_enters_review_queue(tmp_path):
    document, reason = find_official_document([], TRUSTED)
    assert document is None and "No official" in reason
    conn = connect(tmp_path / "review.db"); repo = NoticeRepository(conn)
    notice = PipelineNotice(category="JOB", title="Aggregator", discovery_url="https://agg.test/1", source_name="agg")
    notice.id = repo.upsert_discovered(notice)
    queue_id = repo.enqueue_review(notice.id, reason)
    assert queue_id and conn.execute("SELECT count(*) FROM review_queue").fetchone()[0] == 1
    conn.close()


def test_verified_official_notice_becomes_postable():
    result = validate_extraction(job_notice(), source_text(), TRUSTED)
    assert result.valid and result.score >= 80


def test_other_state_only_job_rejected():
    result = validate_extraction(job_notice(scope=EligibilityScope.OTHER_STATE_ONLY), source_text(), TRUSTED)
    assert not result.valid and any("eligibility" in error for error in result.errors)


def test_dry_run_prevents_telegram_calls():
    session = QueueSession()
    result = TelegramSender(session=session, dry_run=True).send("message", b"png")
    assert result.success and session.calls == []
