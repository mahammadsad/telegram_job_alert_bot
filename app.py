#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from config.loader import load_sources, load_trusted_domains
from database.db import NoticeRepository, connect
from processing.classifier import classify
from processing.extractor import GroqExtractor
from processing.formatter import format_telegram_message
from processing.models import PipelineNotice, VerificationStatus
from processing.validators import validate_extraction
from processing.verifier import find_official_document
from rendering.renderer import generate_notice_card
from sources.source_manager import SourceManager
from telegram.buttons import build_url_keyboard
from telegram.sender import TelegramSender


ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("government_information_bot")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def queue_for_review(
    repository: NoticeRepository,
    sender: TelegramSender,
    notice: PipelineNotice,
    reason: str,
) -> None:
    notice.verification_status = VerificationStatus.MANUAL_REVIEW_REQUIRED
    notice.conflict_reason = reason
    repository.save_verification(notice)
    queue_id = repository.enqueue_review(notice.id, reason)
    logger.warning("review_queued notice_id=%s queue_id=%s reason=%s", notice.id, queue_id, reason)
    sender.send_review(
        f"Review #{queue_id}\n{notice.title}\nReason: {reason}\nDiscovery: {notice.discovery_url}\nOfficial: {notice.final_resolved_url or 'not found'}"
    )


def run() -> int:
    dry_run = env_bool("DRY_RUN")
    auto_post = env_bool("AUTO_POST_ENABLED", True)
    max_items = int(os.getenv("MAX_ITEMS_PER_RUN", os.getenv("MAX_JOBS_PER_RUN", "5")))
    trusted_domains = load_trusted_domains()
    conn = connect(os.getenv("DATABASE_PATH", str(ROOT / "jobs.db")))
    repository = NoticeRepository(conn)
    sender = TelegramSender(dry_run=dry_run)
    extractor = GroqExtractor(repository)
    posted = 0
    try:
        items = SourceManager(load_sources()).discover_all()[:max_items]
        logger.info("pipeline_start discovered=%s max_items=%s dry_run=%s", len(items), max_items, dry_run)
        for item in items:
            if repository.discovery_already_posted(item.discovery_url):
                logger.info("duplicate_skipped url=%s reason=historical_or_posted", item.discovery_url)
                continue
            category = classify(item.title, item.summary, item.category_hints)
            notice = PipelineNotice(
                category=category,
                title=item.title,
                discovery_url=item.discovery_url,
                source_name=item.source_name,
            )
            notice.id = repository.upsert_discovered(notice, item.source_domain)
            candidates = list(item.candidate_official_links)
            if item.official:
                candidates.insert(0, item.discovery_url)
            document, reason = find_official_document(candidates, trusted_domains)
            if not document:
                queue_for_review(repository, sender, notice, reason or "Official source not found")
                continue
            notice.final_resolved_url = document.final_url
            notice.final_domain = document.final_domain
            notice.content_sha256 = document.content_sha256
            if document.content_type == "application/pdf":
                notice.official_document_url = document.final_url
            else:
                notice.official_page_url = document.final_url
            logger.info(
                "official_source_found notice_id=%s final_domain=%s sha256=%s",
                notice.id, document.final_domain, document.content_sha256,
            )
            if repository.official_revision_exists(document.final_url, document.content_sha256, notice.id):
                logger.info("duplicate_skipped notice_id=%s reason=official_url_and_hash", notice.id)
                # Keep diagnostic status without violating the unique revision key.
                notice.verification_status = VerificationStatus.REJECTED
                notice.conflict_reason = "Duplicate official URL and content hash"
                notice.final_resolved_url = None
                repository.save_verification(notice)
                continue
            if document.scanned_pdf:
                queue_for_review(repository, sender, notice, "Official PDF has too little extractable text; scanned PDF requires manual review")
                continue
            try:
                extracted = extractor.extract(
                    item.title,
                    document.text,
                    document.final_url,
                    category,
                    document.extracted_links,
                )
            except Exception as exc:
                logger.exception("ai_extraction_failed notice_id=%s error=%s", notice.id, exc)
                queue_for_review(repository, sender, notice, f"AI extraction failed: {exc}")
                continue
            notice.structured = extracted
            notice.category = extracted.category
            validation = validate_extraction(extracted, document.text, trusted_domains, document.page_text)
            notice.verification_score = validation.score
            if validation.conflicts:
                notice.verification_status = VerificationStatus.CONFLICT_DETECTED
                queue_for_review(repository, sender, notice, "; ".join(validation.conflicts))
                continue
            if not validation.valid:
                notice.verification_status = VerificationStatus.OFFICIAL_INCOMPLETE
                queue_for_review(repository, sender, notice, "; ".join(validation.errors))
                continue
            notice.verification_status = VerificationStatus.VERIFIED_OFFICIAL
            repository.save_verification(notice)
            message = format_telegram_message(extracted)
            image: bytes | None = None
            try:
                image = generate_notice_card(extracted, extracted.category)
                notice.render_status = "SUCCESS"
                if dry_run:
                    output = ROOT / "dry_run_output"
                    output.mkdir(exist_ok=True)
                    (output / f"notice_{notice.id}.png").write_bytes(image)
                    (output / f"notice_{notice.id}.html.txt").write_text(message, encoding="utf-8")
                logger.info("render_success notice_id=%s bytes=%s", notice.id, len(image))
            except Exception as exc:
                notice.render_status = "FAILED"
                logger.exception("render_failed notice_id=%s error=%s; using_text_fallback", notice.id, exc)
            repository.save_verification(notice)
            if not auto_post and not dry_run:
                logger.info("post_skipped notice_id=%s reason=auto_post_disabled", notice.id)
                continue
            keyboard = build_url_keyboard(extracted, trusted_domains)
            result = sender.send(message, image, keyboard)
            if result.success:
                if not dry_run:
                    repository.mark_posted(notice.id, result.photo_message_id, result.text_message_id)
                posted += 1
            else:
                notice.verification_status = VerificationStatus.POST_FAILED
                repository.save_verification(notice)
        logger.info("pipeline_complete posted=%s dry_run=%s", posted, dry_run)
        return posted
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
