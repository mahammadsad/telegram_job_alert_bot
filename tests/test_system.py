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
from processing.extractor import GroqExtractor
from processing.formatter import format_telegram_message
from processing.models import (
    EligibilityScope,
    EvidenceValue,
    ExtractedNotice,
    NoticeCategory,
    NoticeSubtype,
    PipelineNotice,
    VerificationStatus,
)
from processing.schemas import CATEGORY_FIELDS
from processing.validators import (
    detect_numeric_conflict,
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
from telegram.sender import telegram_text_length


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


class GroqSession:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        content = self.contents.pop(0)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        return response(url, body=body, content_type="application/json")


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


def test_discovery_redirect_is_rejected_before_unknown_host_is_contacted():
    session = QueueSession([
        response("https://www.karmasandhan.com/feed/", 302, location="https://evil.test/feed"),
    ])
    config = SourceConfig(
        "Karmasandhan",
        "https://www.karmasandhan.com/feed/",
        "rss",
        ["JOB"],
        allowed_domains=("karmasandhan.com",),
    )
    with pytest.raises(ValueError, match="unapproved host"):
        RSSSource(config, session=session).fetch()
    assert [call[1] for call in session.calls] == ["https://www.karmasandhan.com/feed/"]


def test_url_canonicalization():
    assert canonicalize_url("HTTPS://PSC.WB.GOV.IN/a/?utm_source=x&b=2") == "https://psc.wb.gov.in/a?b=2"


def test_rss_parsing():
    config = SourceConfig("Karmasandhan", "https://www.karmasandhan.com/feed/", "rss", ["JOB"], allowed_domains=("karmasandhan.com",))
    items = RSSSource(config).parse((FIXTURES / "feed.xml").read_bytes(), config.url)
    assert len(items) == 1 and items[0].candidate_official_links == ["https://psc.wb.gov.in/notice.pdf"]


def test_rss_rejects_unapproved_discovery_item_url():
    config = SourceConfig(
        "Karmasandhan",
        "https://www.karmasandhan.com/feed/",
        "rss",
        ["JOB"],
        allowed_domains=("karmasandhan.com",),
    )
    payload = b"""<rss><channel><item><title>Trap</title>
        <link>https://evil.test/phish</link><description>Notice</description>
        </item></channel></rss>"""
    assert RSSSource(config).parse(payload, config.url) == []


def test_html_parsing_with_verified_selectors():
    config = SourceConfig(
        "Official", "https://wb.gov.in/notices", "html", ["ADMISSION"], official=True,
        discovery_only=False, allowed_domains=("wb.gov.in",),
        item_selector="article.notice", title_selector="h2", link_selector="a.details",
    )
    items = HTMLSource(config).parse((FIXTURES / "listing.html").read_bytes(), config.url)
    assert items[0].discovery_url == "https://wb.gov.in/notice/1"


def test_west_bengal_portal_listing_uses_official_pdf_and_date():
    config = SourceConfig(
        "West Bengal State Portal",
        "https://wb.gov.in/documents-notification.aspx",
        "html",
        ["GOVERNMENT_ANNOUNCEMENT"],
        official=True,
        discovery_only=False,
        allowed_domains=("wb.gov.in",),
        item_selector="#ContentPlaceHolder1_gv > tr",
        title_selector="td:first-child p",
        link_selector="td:first-child > a[href]",
        date_selector="td:nth-of-type(2)",
    )

    items = HTMLSource(config).parse(
        (FIXTURES / "wb_portal_notifications.html").read_bytes(), config.url
    )

    assert len(items) == 1
    assert items[0].title == "Latest official notice"
    assert items[0].discovery_url == "https://wb.gov.in/upload/latest-notice.pdf"
    assert items[0].candidate_official_links == [items[0].discovery_url]
    assert "09-07-2026" in items[0].summary


def test_wbjeeb_listing_accepts_only_the_exact_nic_document_host():
    config = SourceConfig(
        "WBJEEB",
        "https://wbjeeb.nic.in/current-events/",
        "html",
        ["ADMISSION", "RESULT", "EXAMINATION", "EDUCATION_NOTICE"],
        official=True,
        discovery_only=False,
        allowed_domains=("wbjeeb.nic.in", "cdnbbsr.s3waas.gov.in"),
        item_selector=".doc-table tbody > tr",
        title_selector="td:first-child > a[href]",
        link_selector="td:first-child > a[href]",
    )

    items = HTMLSource(config).parse(
        (FIXTURES / "wbjeeb_current_events.html").read_bytes(), config.url
    )

    assert len(items) == 1
    assert items[0].title == "Notice regarding WBJEE counselling"
    assert items[0].discovery_url == (
        "https://cdnbbsr.s3waas.gov.in/official-bucket/notice.pdf"
    )
    assert items[0].official is True


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


def test_groq_json_mode_and_malformed_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    monkeypatch.setenv("GROQ_MAX_RETRIES", "2")
    monkeypatch.setenv("GROQ_RETRY_BASE_DELAY", "0")
    monkeypatch.setenv("GROQ_RATE_LIMIT_DELAY", "0")
    conn = connect(tmp_path / "groq.db")
    repo = NoticeRepository(conn)
    valid = job_notice().model_dump_json()
    session = GroqSession(["not-json", valid])
    extracted = GroqExtractor(repo, session=session).extract(
        "Clerk recruitment",
        source_text(),
        "https://psc.wb.gov.in/notice.pdf",
        NoticeCategory.JOB,
        ["https://psc.wb.gov.in/notice.pdf"],
    )
    assert extracted.category == NoticeCategory.JOB
    assert len(session.calls) == 2
    assert session.calls[-1][1]["json"]["response_format"] == {"type": "json_object"}
    repair_prompt = session.calls[-1][1]["json"]["messages"][-1]["content"]
    assert "previous response failed schema validation" in repair_prompt.lower()
    assert repo.get_usage("groq", "extract") == 2
    conn.close()


def test_unsupported_evidence_rejection():
    assert not evidence_supported("not present", source_text())
    result = validate_extraction(job_notice(valid=False), source_text(), TRUSTED)
    assert not result.valid and any("unsupported value" in error for error in result.errors)


def test_date_currency_and_vacancy_validation():
    assert valid_date("31 July 2026") and not valid_date("soon") and not valid_date("2026")
    assert valid_currency("₹3,000") and not valid_currency("many rupees")
    assert valid_vacancy("350 vacancies") and not valid_vacancy("unknown")
    assert valid_percentage("75%") and not valid_percentage("175%")
    assert valid_age_limit("18-30 years") and not valid_age_limit("180 years")
    assert valid_date("৩১ জুলাই ২০২৬")
    assert valid_currency("৩,০০০ টাকা")


def test_conflicting_deadlines_require_review():
    text = source_text() + "\nLast date: 15.08.2026"
    result = validate_extraction(job_notice(), text, TRUSTED)
    assert not result.valid and result.conflicts == ["conflicting date: deadline"]


def test_conflicting_labelled_vacancy_counts_require_review():
    text = source_text() + "\nTotal vacancies: 350\nTotal vacancies: 400"
    assert detect_numeric_conflict(text, "total_vacancies")
    result = validate_extraction(job_notice(), text, TRUSTED)
    assert not result.valid
    assert "conflicting numeric value: total_vacancies" in result.conflicts


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
    assert notice.subtype == NoticeSubtype.UPDATED
    assert conn.execute("SELECT count(*) FROM notice_revisions").fetchone()[0] == 2
    conn.close()


def test_content_reversion_still_creates_a_new_revision(tmp_path):
    conn = connect(tmp_path / "revision-reversion.db")
    repo = NoticeRepository(conn)
    notice = PipelineNotice(
        category="JOB",
        title="N",
        discovery_url="https://x.test/reversion",
        source_name="x",
        content_sha256="a",
        final_resolved_url="https://wb.gov.in/reversion",
    )
    notice.id = repo.upsert_discovered(notice)
    assert repo.save_verification(notice) == 1
    notice.content_sha256 = "b"
    assert repo.save_verification(notice) == 2
    notice.content_sha256 = "a"
    assert repo.save_verification(notice) == 3
    assert conn.execute("SELECT count(*) FROM notice_revisions").fetchone()[0] == 3
    conn.close()


def test_database_preserves_top_level_and_category_evidence(tmp_path):
    conn = connect(tmp_path / "evidence.db")
    repo = NoticeRepository(conn)
    notice = PipelineNotice(
        category="JOB",
        title="Evidence",
        discovery_url="https://x.test/evidence",
        source_name="x",
        structured=job_notice(),
    )
    notice.id = repo.upsert_discovered(notice)
    repo.save_verification(notice)
    stored = json.loads(
        conn.execute("SELECT evidence_json FROM notices WHERE id=?", (notice.id,)).fetchone()[0]
    )
    assert stored["issuing_authority"]["evidence"] == "WBPSC"
    assert stored["fields"]["deadline"]["evidence"] == "Last date: 31.07.2026"
    conn.close()


def test_unchanged_posted_revision_is_detected(tmp_path):
    conn = connect(tmp_path / "posted.db")
    repo = NoticeRepository(conn)
    notice = PipelineNotice(
        category="JOB",
        title="N",
        discovery_url="https://feed.test/n",
        source_name="feed",
        content_sha256="abc",
        final_resolved_url="https://wb.gov.in/n/?utm_source=feed",
        trusted_domain=True,
    )
    notice.id = repo.upsert_discovered(notice)
    repo.save_verification(notice)
    repo.mark_posted(notice.id, "1", "2")
    row = repo.get_by_discovery_url(notice.discovery_url)
    assert repo.is_same_posted_revision(row, "https://wb.gov.in/n", "abc")
    assert not repo.is_same_posted_revision(row, "https://wb.gov.in/n", "changed")
    conn.close()


def test_review_approval_retains_candidate_links_for_next_run(tmp_path):
    conn = connect(tmp_path / "review-retry.db")
    repo = NoticeRepository(conn)
    notice = PipelineNotice(
        category="JOB",
        title="Review me",
        discovery_url="https://aggregator.test/n",
        source_name="Aggregator",
        metadata={
            "summary": "Recruitment summary",
            "candidate_official_links": ["https://psc.wb.gov.in/n.pdf"],
            "official": False,
            "discovery_only": True,
        },
    )
    notice.id = repo.upsert_discovered(notice, "aggregator.test")
    queue_id = repo.enqueue_review(notice.id, "needs review")
    conn.execute("UPDATE review_queue SET status='APPROVED' WHERE id=?", (queue_id,))
    conn.commit()
    candidates = repo.review_candidates()
    assert candidates[0]["candidate_official_links"] == ["https://psc.wb.gov.in/n.pdf"]
    assert conn.execute("SELECT status FROM review_queue WHERE id=?", (queue_id,)).fetchone()[0] == "PROCESSING"
    conn.close()


def test_source_minimum_interval_is_persisted(tmp_path):
    conn = connect(tmp_path / "source-check.db")
    repo = NoticeRepository(conn)
    assert repo.source_check_due("Fixture", 120)
    repo.record_source_check("Fixture", "https://example.test/feed", "SUCCESS", "discovered=1")
    assert not repo.source_check_due("Fixture", 120)
    assert repo.source_check_due("Fixture", 0)
    conn.close()


def test_bengali_html_formatting_escapes_source_values():
    notice = job_notice()
    notice.title_bn = "চাকরি <script>alert(1)</script>"
    message = format_telegram_message(notice)
    assert "&lt;script&gt;" in message and "অফিসিয়াল উৎস থেকে যাচাইকৃত" in message
    hashtags = [part for part in message.split() if part.startswith("#")]
    assert 2 <= len(hashtags) <= 4


@pytest.mark.parametrize("category", list(NoticeCategory))
def test_generated_messages_stay_within_telegram_limit(category):
    values = {
        name: field(
            "https://wb.gov.in/notice.pdf" if name.endswith("_url") else "দীর্ঘ যাচাইকৃত তথ্য " * 80,
            "দীর্ঘ যাচাইকৃত তথ্য",
            url="https://wb.gov.in/notice.pdf",
        )
        for name in CATEGORY_FIELDS[category]
    }
    notice = ExtractedNotice(
        category=category,
        title_bn="খুব দীর্ঘ সরকারি বিজ্ঞপ্তির শিরোনাম " * 50,
        issuing_authority=field(
            "পশ্চিমবঙ্গ সরকার",
            "পশ্চিমবঙ্গ সরকার",
            url="https://wb.gov.in/notice.pdf",
        ),
        fields=values,
        eligibility_scope=EligibilityScope.WEST_BENGAL if category == NoticeCategory.JOB else None,
    )
    assert telegram_text_length(format_telegram_message(notice)) <= 4096


def test_updated_notice_is_visibly_labelled():
    notice = job_notice()
    notice.subtype = NoticeSubtype.UPDATED
    message = format_telegram_message(notice)
    markup = render_html(notice, VerificationStatus.VERIFIED_OFFICIAL)
    assert "আপডেটেড বিজ্ঞপ্তি" in message
    assert "সরকারি চাকরি • আপডেট" in markup


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
    assert telegram_text_length("<b>abc</b>") == 3
    assert not should_split_caption("<b>" + "x" * CAPTION_LIMIT + "</b>")


def test_evidence_source_and_official_link_consistency():
    notice = job_notice()
    notice.fields["official_notification_url"] = field(
        "https://psc.wb.gov.in/not-in-source.pdf",
        "https://psc.wb.gov.in/notice.pdf",
    )
    result = validate_extraction(
        notice,
        source_text(),
        TRUSTED,
        official_source_url="https://psc.wb.gov.in/notice.pdf",
    )
    assert not result.valid
    assert any("not present in source" in error for error in result.errors)

    notice = job_notice()
    notice.fields["deadline"].source_url = "https://wb.gov.in/different"
    result = validate_extraction(
        notice,
        source_text(),
        TRUSTED,
        official_source_url="https://psc.wb.gov.in/notice.pdf",
    )
    assert any("invalid evidence source URL: deadline" == error for error in result.errors)


def test_downloaded_official_pdf_url_is_self_authenticating_metadata():
    notice = job_notice()
    official_url = "https://psc.wb.gov.in/notice-2026-07.pdf"
    for metadata_field in (notice.issuing_authority, notice.notice_number, notice.notice_date):
        metadata_field.source_url = official_url
    for field_value in notice.fields.values():
        field_value.source_url = official_url
    notice.fields["official_notification_url"] = EvidenceValue(
        value=official_url,
        evidence=None,
        evidence_page=None,
        source_url=official_url,
    )
    paged_text = "[PAGE 1]\n" + source_text().replace(
        " https://psc.wb.gov.in/notice.pdf", ""
    )
    result = validate_extraction(
        notice,
        paged_text,
        TRUSTED,
        page_text={1: source_text()},
        official_source_url=official_url,
    )
    assert result.valid


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
