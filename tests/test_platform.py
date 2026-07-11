from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
import requests

from database.db import NoticeRepository, connect
from database.supabase_repository import SupabaseRepository
from processing.deadlines import (
    assign_publication_priority, deadline_state, new_expired_notice_is_publishable,
    parse_notice_date,
)
from processing.eligibility import detect_language_requirement, evaluate_eligibility
from processing.models import (
    DeadlineState, EligibilityScope, NoticeCategory, PublicationPriority, TelegramDeliveryState,
)
from processing.rule_extractor import extract_rule_facts
from scripts.import_sqlite_to_supabase import import_database
from sources.article_source import ArticleInspector
from sources.base import SourceConfig
from telegram.sender import TelegramSender
from telegram.buttons import build_url_keyboard
from processing.verifier import validate_official_url
from rendering.renderer import SharedCardRenderer
from tests.test_system import job_notice, response


class ArticleSession:
    def __init__(self, article: bytes):
        self.article = article
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        if url.endswith("robots.txt"):
            return response(url, body=b"User-agent: *\nAllow: /")
        return response(url, body=self.article)


def test_full_article_inspection_ranks_official_links_and_ignores_shorteners():
    markup = b'''<html><body><a href="https://bit.ly/trap">Apply</a>
      <a href="https://psc.wb.gov.in/n.pdf">Official notification</a>
      <a href="https://evil.test/phish">Advertisement</a></body></html>'''
    config = SourceConfig(
        "Aggregator", "https://agg.test/post", "rss", ["JOB"],
        allowed_domains=("agg.test",), allowed_document_domains=("psc.wb.gov.in",),
        terms_reviewed=True, article_inspection=True,
    )
    text, links = ArticleInspector(config, {"psc.wb.gov.in"}, ArticleSession(markup)).inspect(config.url)
    assert "Official notification" in text
    assert links == ["https://psc.wb.gov.in/n.pdf"]


def test_article_inspection_stays_off_without_terms_review():
    config = SourceConfig("A", "https://agg.test/post", "rss", ["JOB"], allowed_domains=("agg.test",), article_inspection=True)
    session = ArticleSession(b"<a href='https://psc.wb.gov.in/n.pdf'>official</a>")
    assert ArticleInspector(config, {"psc.wb.gov.in"}, session).inspect(config.url) == ("", [])
    assert session.calls == []


@pytest.mark.parametrize(
    ("text", "scope", "expected", "publish"),
    [
        ("West Bengal recruitment. West Bengal candidates may apply.", EligibilityScope.WEST_BENGAL_ONLY, EligibilityScope.WEST_BENGAL_ONLY, True),
        ("Applications are open to candidates from all states.", None, EligibilityScope.ALL_INDIA, True),
        ("Domicile of Delhi required for applicants only.", None, EligibilityScope.OTHER_STATE_DOMICILE_REQUIRED, False),
        ("Applicant must be an Indian citizen.", None, EligibilityScope.ELIGIBILITY_UNCLEAR, False),
    ],
)
def test_official_text_drives_geographic_eligibility(text, scope, expected, publish):
    notice = job_notice(scope=scope or EligibilityScope.UNCLEAR)
    notice.eligibility_reason = text if scope else None
    decision = evaluate_eligibility(notice, text)
    assert decision.scope == expected and decision.auto_publish is publish


def test_local_language_is_detected_and_displayable():
    notice = job_notice(scope=EligibilityScope.ALL_INDIA)
    detect_language_requirement(notice, "Bengali language is mandatory for this post")
    assert notice.local_language_required and notice.required_language == "Bengali"


def test_bengali_deadline_states_and_priorities():
    assert parse_notice_date("৩১ জুলাই ২০২৬") == date(2026, 7, 31)
    assert deadline_state("14 July 2026", today=date(2026, 7, 11)) == DeadlineState.CLOSING_SOON
    assert deadline_state("10 July 2026", today=date(2026, 7, 11)) == DeadlineState.EXPIRED
    assert assign_publication_priority(job_notice().subtype, DeadlineState.CLOSING_SOON) == PublicationPriority.HIGH
    assert new_expired_notice_is_publishable(
        job_notice().subtype, DeadlineState.EXPIRED, NoticeCategory.RESULT
    )


def test_rule_extractor_finds_common_critical_facts():
    facts = extract_rule_facts("Advertisement No: 12/2026\nTotal vacancies: 350\nApplication fee: Rs. 100\nLast date: 31.07.2026")
    assert facts.vacancy_count == "350"
    assert facts.notice_number == "12/2026"
    assert facts.application_fee.replace(" ", "").lower() == "rs.100"
    assert facts.deadline.startswith("31.07.2026")


def test_sqlite_tracks_partial_telegram_delivery(tmp_path):
    connection = connect(tmp_path / "state.db")
    repository = NoticeRepository(connection)
    notice = job_notice()
    from processing.models import PipelineNotice
    pipeline = PipelineNotice(category="JOB", title="x", discovery_url="https://x.test/1", source_name="x", structured=notice)
    pipeline.id = repository.upsert_discovered(pipeline)
    repository.record_telegram_delivery(pipeline.id, "@channel", TelegramDeliveryState.PARTIAL_FAILURE, "44", error="text failed")
    row = repository.get_telegram_delivery(pipeline.id, "@channel")
    assert row["photo_message_id"] == "44" and row["delivery_state"] == "PARTIAL_FAILURE"
    connection.close()


def test_normalized_evidence_rows_are_written(tmp_path):
    connection = connect(tmp_path / "evidence.db")
    repository = NoticeRepository(connection)
    from processing.models import PipelineNotice, VerificationStatus
    pipeline = PipelineNotice(
        category="JOB", title="Evidence", discovery_url="https://x.test/e",
        source_name="x", structured=job_notice(),
        verification_status=VerificationStatus.VERIFIED_OFFICIAL,
        final_resolved_url="https://psc.wb.gov.in/notice.pdf",
    )
    pipeline.id = repository.upsert_discovered(pipeline)
    repository.save_verification(pipeline)
    count = connection.execute(
        "select count(*) from notice_evidence where notice_id=?", (pipeline.id,)
    ).fetchone()[0]
    assert count >= 5
    connection.close()


def test_review_correction_prepends_official_url_and_data(tmp_path):
    import json
    from processing.models import PipelineNotice
    connection = connect(tmp_path / "correction.db")
    repository = NoticeRepository(connection)
    pipeline = PipelineNotice(
        category="JOB", title="Correction", discovery_url="https://agg.test/c",
        source_name="a", metadata={
            "candidate_official_links": ["https://psc.wb.gov.in/old.pdf"]
        },
    )
    pipeline.id = repository.upsert_discovered(pipeline)
    queue_id = repository.enqueue_review(pipeline.id, "fix")
    connection.execute(
        """update review_queue set status='RETRY', corrected_official_url=?,
           corrected_structured_data_json=? where id=?""",
        ("https://psc.wb.gov.in/new.pdf", json.dumps(job_notice().model_dump(mode="json")), queue_id),
    )
    connection.commit()
    item = repository.review_candidates()[0]
    assert item["candidate_official_links"][0].endswith("new.pdf")
    assert item["corrected_structured_data"]["category"] == "JOB"
    connection.close()


class TextOnlySession:
    def __init__(self): self.calls=[]
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs));return response(url,body=b'{"result":{"message_id":55}}',content_type="application/json")


def test_partial_retry_skips_duplicate_photo(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret");monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@channel")
    session=TextOnlySession();result=TelegramSender(session=session).send("x"*1100,b"image",previous_photo_id="44")
    assert result.success and result.photo_message_id == "44" and result.text_message_id == "55"
    assert len(session.calls)==1 and session.calls[0][0].endswith("sendMessage")


def test_sqlite_to_supabase_import_dry_run_is_repeatable(tmp_path):
    db = tmp_path / "old.db"
    connection = connect(db)
    connection.execute("insert into notices(category,title,discovery_url,verification_status) values('JOB','Old','https://x.test/old','POSTED')")
    connection.commit();connection.close()
    first = import_database(db, object(), dry_run=True)  # type: ignore[arg-type]
    second = import_database(db, object(), dry_run=True)  # type: ignore[arg-type]
    assert first == second and first["notices"] == 1


def test_supabase_migration_has_rls_and_public_verification_gate():
    sql = (Path(__file__).parents[1] / "supabase/migrations/202607110001_platform.sql").read_text()
    assert "enable row level security" in sql.lower()
    assert "publication_status='PUBLISHED'" in sql
    assert "service-role" in sql.lower()


class SupabaseSession:
    def __init__(self): self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = b'[{"id":7,"discovery_url":"https://a.test/n","verification_status":"POSTED","official_document_hash":"abc","final_resolved_url":"https://wb.gov.in/n","structured_data":{}}]'
        return response(url, body=payload, content_type="application/json")
    def close(self): pass


def test_supabase_adapter_uses_service_role_only_server_side():
    session = SupabaseSession()
    repository = SupabaseRepository("https://project.supabase.co", "service-secret", session)
    row = repository.get_by_discovery_url("https://a.test/n")
    assert row["content_sha256"] == "abc"
    headers = session.calls[0][2]["headers"]
    assert headers["Authorization"] == "Bearer service-secret"
    assert "service-secret" not in session.calls[0][1]


def test_ssrf_style_local_addresses_are_never_official():
    trusted = {"127.0.0.1", "localhost", "wb.gov.in"}
    assert not validate_official_url("https://127.0.0.1/admin", trusted)
    assert not validate_official_url("https://localhost/admin", trusted)


def test_keyboard_adds_safe_public_detail_link(monkeypatch):
    monkeypatch.setenv("PUBLIC_WEBSITE_URL", "https://example.pages.dev")
    keyboard = build_url_keyboard(job_notice(), {"psc.wb.gov.in"}, 42)
    assert keyboard["inline_keyboard"][-1][0]["url"] == "https://example.pages.dev/notice/42"


def test_shared_renderer_reuses_one_browser_for_multiple_cards():
    renderer = SharedCardRenderer()
    try:
        first = renderer.generate(job_notice())
        page = renderer._page
        second = renderer.generate(job_notice())
        assert first.startswith(b"\x89PNG") and second.startswith(b"\x89PNG")
        assert renderer._page is page
    finally:
        renderer.close()
