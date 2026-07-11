#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from config.loader import load_sources, load_trusted_domains
from database.base import Repository
from database.db import NoticeRepository, connect
from database.factory import create_repository
from processing.classifier import classify
from processing.deduplicator import is_changed_revision
from processing.extractor import GroqExtractor
from processing.formatter import format_telegram_message
from processing.models import (
    DiscoveredItem,
    EvidenceValue,
    ExtractedNotice,
    NoticeSubtype,
    PipelineNotice,
    VerificationStatus,
)
from processing.schemas import CATEGORY_FIELDS
from processing.validators import validate_extraction
from processing.deadlines import assign_publication_priority, deadline_state, new_expired_notice_is_publishable
from processing.eligibility import detect_language_requirement, evaluate_eligibility
from processing.rule_extractor import extract_rule_facts
from processing.verifier import find_official_document
from rendering.renderer import SharedCardRenderer
from sources.source_manager import SourceManager
from telegram.buttons import build_url_keyboard
from telegram.sender import TelegramSender


ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("government_information_bot")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def validate_runtime_config(dry_run: bool, auto_post: bool) -> None:
    if dry_run or not auto_post:
        return
    missing = [
        name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise RuntimeError("Missing required live-posting variables: " + ", ".join(missing))


def queue_for_review(
    repository: Repository,
    sender: TelegramSender,
    notice: PipelineNotice,
    reason: str,
) -> None:
    if notice.verification_status in {
        VerificationStatus.DISCOVERED,
        VerificationStatus.OFFICIAL_SOURCE_FOUND,
        VerificationStatus.UNDER_VERIFICATION,
    }:
        notice.verification_status = VerificationStatus.MANUAL_REVIEW_REQUIRED
    notice.conflict_reason = reason
    repository.save_verification(notice)
    queue_id = repository.enqueue_review(notice.id, reason)
    logger.warning("review_queued notice_id=%s queue_id=%s reason=%s", notice.id, queue_id, reason)
    sender.send_review(
        f"Review #{queue_id}\n{notice.title}\nReason: {reason}\nDiscovery: {notice.discovery_url}\nOfficial: {notice.final_resolved_url or 'not found'}"
    )


def database_path_for_run(dry_run: bool) -> Path:
    configured = os.getenv("DATABASE_PATH", "").strip()
    primary = Path(configured) if configured else ROOT / "jobs.db"
    if not dry_run:
        return primary
    output = ROOT / "dry_run_output"
    output.mkdir(exist_ok=True)
    dry_database = output / "dry_run.db"
    if primary.exists() and primary.resolve() != dry_database.resolve():
        shutil.copy2(primary, dry_database)
    elif dry_database.exists():
        dry_database.unlink()
    logger.info("dry_run_database path=%s production_database_unchanged=true", dry_database)
    return dry_database


def merge_items(review_items: list[dict], discovered: list[DiscoveredItem]) -> list[DiscoveredItem]:
    merged = [DiscoveredItem.model_validate(item) for item in review_items] + discovered
    unique: dict[str, DiscoveredItem] = {}
    for item in merged:
        unique.setdefault(item.discovery_url, item)
    return list(unique.values())


def partial_rule_extraction(
    title: str, category, source_url: str, rule_facts, page_text: dict[int, str]
) -> ExtractedNotice:
    fields = {name: EvidenceValue(source_url=source_url) for name in CATEGORY_FIELDS[category]}
    mapping = {
        "deadline": ("deadline", rule_facts.deadline),
        "total_vacancies": ("vacancy_count", rule_facts.vacancy_count),
        "application_fee": ("application_fee", rule_facts.application_fee),
    }
    for field_name, (fact_name, value) in mapping.items():
        if field_name not in fields or value is None:
            continue
        evidence = rule_facts.evidence.get(fact_name)
        page = next((number for number, text in page_text.items() if evidence and evidence in text), None)
        fields[field_name] = EvidenceValue(
            value=value, evidence=evidence, evidence_page=page, source_url=source_url,
        )
    notice_number_evidence = rule_facts.evidence.get("notice_number")
    number_page = next(
        (number for number, text in page_text.items() if notice_number_evidence and notice_number_evidence in text), None
    )
    return ExtractedNotice(
        category=category, title_bn=title,
        issuing_authority=EvidenceValue(source_url=source_url),
        notice_number=EvidenceValue(
            value=rule_facts.notice_number, evidence=notice_number_evidence,
            evidence_page=number_page, source_url=source_url,
        ),
        fields=fields,
    )


def run() -> int:
    dry_run = env_bool("DRY_RUN")
    auto_post = env_bool("AUTO_POST_ENABLED", True)
    max_items = int(os.getenv("MAX_ITEMS_PER_RUN", os.getenv("MAX_JOBS_PER_RUN", "5")))
    max_posts = int(os.getenv("MAX_POSTS_PER_RUN", "5"))
    max_category_posts = int(os.getenv("MAX_POSTS_PER_CATEGORY", "2"))
    validate_runtime_config(dry_run, auto_post)
    trusted_domains = load_trusted_domains()
    if dry_run:
        conn = connect(database_path_for_run(True))
        handle = None
        repository: Repository = NoticeRepository(conn)
    else:
        handle = create_repository(database_path_for_run(False))
        repository = handle.repository
        conn = None
    sender = TelegramSender(dry_run=dry_run)
    extractor = GroqExtractor(repository)
    posted = 0
    category_posts: dict[str, int] = {}
    card_renderer = SharedCardRenderer()
    stats: dict[str, object] = {
        "sources_checked": 0, "items_discovered": 0, "items_verified": 0,
        "items_posted": 0, "items_rejected": 0, "items_queued": 0,
        "duplicates": 0, "errors": [],
    }
    run_id: int | None = None
    try:
        run_id = repository.start_pipeline_run(dry_run)  # type: ignore[attr-defined]
        review_items = repository.review_candidates()
        registry = repository.list_sources()  # type: ignore[attr-defined]
        source_configs = registry or load_sources()
        source_manager = SourceManager(
            source_configs, repository=repository, respect_intervals=not dry_run,
            trusted_domains=trusted_domains,
        )
        discovered = source_manager.discover_all()
        stats["sources_checked"] = source_manager.checked_count
        stats["items_discovered"] = len(discovered)
        items = merge_items(review_items, discovered)[:max_items]
        logger.info("pipeline_start discovered=%s max_items=%s dry_run=%s", len(items), max_items, dry_run)
        for item in items:
            existing = repository.get_by_discovery_url(item.discovery_url)
            if repository.is_legacy_posted(existing):
                logger.info("duplicate_skipped url=%s reason=legacy_posted", item.discovery_url)
                stats["duplicates"] = int(stats["duplicates"]) + 1
                continue
            category = classify(item.title, item.summary, item.category_hints)
            notice = PipelineNotice(
                category=category,
                title=item.title,
                discovery_url=item.discovery_url,
                source_name=item.source_name,
                metadata={
                    "summary": item.summary,
                    "candidate_official_links": item.candidate_official_links,
                    "official": item.official,
                    "discovery_only": item.discovery_only,
                },
            )
            notice.id = repository.upsert_discovered(notice, item.source_domain)
            candidates = list(item.candidate_official_links)
            if item.official:
                candidates.insert(0, item.discovery_url)
            if existing is not None and existing["final_resolved_url"]:
                candidates.append(existing["final_resolved_url"])
            candidates = list(dict.fromkeys(candidates))
            document, reason = find_official_document(candidates, trusted_domains)
            if not document:
                queue_for_review(repository, sender, notice, reason or "Official source not found")
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            notice.final_resolved_url = document.final_url
            notice.final_domain = document.final_domain
            notice.trusted_domain = True
            notice.content_sha256 = document.content_sha256
            changed_revision = is_changed_revision(
                existing["content_sha256"] if existing is not None else None,
                document.content_sha256,
            )
            retained_updated_revision = bool(
                existing is not None
                and int(existing["revision_number"] or 1) > 1
                and existing["content_sha256"] == document.content_sha256
                and existing["subtype"] == NoticeSubtype.UPDATED.value
            )
            if changed_revision or retained_updated_revision:
                notice.subtype = NoticeSubtype.UPDATED
            if document.content_type == "application/pdf":
                notice.official_document_url = document.final_url
            else:
                notice.official_page_url = document.final_url
            logger.info(
                "official_source_found notice_id=%s final_domain=%s sha256=%s",
                notice.id, document.final_domain, document.content_sha256,
            )
            if repository.is_same_posted_revision(existing, document.final_url, document.content_sha256):
                logger.info("duplicate_skipped notice_id=%s reason=unchanged_posted_revision", notice.id)
                stats["duplicates"] = int(stats["duplicates"]) + 1
                continue
            if repository.official_revision_exists(document.final_url, document.content_sha256, notice.id):
                logger.info("duplicate_skipped notice_id=%s reason=official_url_and_hash", notice.id)
                # Keep diagnostic status without violating the unique revision key.
                notice.verification_status = VerificationStatus.REJECTED
                notice.conflict_reason = "Duplicate official URL and content hash"
                notice.final_resolved_url = None
                notice.content_sha256 = None
                notice.trusted_domain = False
                repository.save_verification(notice)
                stats["duplicates"] = int(stats["duplicates"]) + 1
                continue
            if document.scanned_pdf:
                queue_for_review(repository, sender, notice, "Official PDF has too little extractable text; scanned PDF requires manual review")
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            rule_facts = extract_rule_facts(document.text)
            try:
                if item.corrected_structured_data:
                    extracted = ExtractedNotice.model_validate(item.corrected_structured_data)
                    if extracted.category != category:
                        raise ValueError("Admin correction changed the controlled category")
                else:
                    if not env_bool("AI_ENABLED", True):
                        raise RuntimeError("AI extraction is disabled; deterministic facts stored for review")
                    extracted = extractor.extract(
                        item.title,
                        document.text,
                        document.final_url,
                        category,
                        document.extracted_links,
                    )
            except Exception as exc:
                logger.exception("ai_extraction_failed notice_id=%s error=%s", notice.id, exc)
                partial = partial_rule_extraction(
                    item.title, category, document.final_url, rule_facts, document.page_text
                )
                evaluate_eligibility(partial, document.text)
                detect_language_requirement(partial, document.text)
                partial_deadline = partial.fields.get("deadline")
                partial.deadline_state = deadline_state(partial_deadline.value if partial_deadline else None)
                partial.publication_priority = assign_publication_priority(
                    partial.subtype, partial.deadline_state, partial.category
                )
                notice.structured = partial
                queue_for_review(repository, sender, notice, f"AI extraction failed: {exc}")
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            notice.structured = extracted
            notice.category = extracted.category
            if notice.subtype == NoticeSubtype.UPDATED and extracted.subtype == NoticeSubtype.NEW:
                extracted.subtype = NoticeSubtype.UPDATED
            notice.subtype = extracted.subtype
            decision = evaluate_eligibility(extracted, document.text)
            detect_language_requirement(extracted, document.text)
            deadline_field = extracted.fields.get("deadline")
            extracted.deadline_state = deadline_state(
                deadline_field.value if deadline_field else None,
                cancelled=extracted.subtype == NoticeSubtype.CANCELLED,
            )
            extracted.publication_priority = assign_publication_priority(
                extracted.subtype, extracted.deadline_state, extracted.category
            )
            if rule_facts.deadline and deadline_field and deadline_field.value:
                from processing.validators import normalize_digits
                if normalize_digits(str(rule_facts.deadline)) not in normalize_digits(str(deadline_field.value)) and normalize_digits(str(deadline_field.value)) not in normalize_digits(str(rule_facts.deadline)):
                    notice.verification_status = VerificationStatus.CONFLICT_DETECTED
                    queue_for_review(repository, sender, notice, "AI deadline conflicts with deterministic extraction")
                    stats["items_queued"] = int(stats["items_queued"]) + 1
                    continue
            if decision.review:
                queue_for_review(repository, sender, notice, decision.reason)
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            if not decision.auto_publish:
                notice.verification_status = VerificationStatus.REJECTED
                notice.conflict_reason = decision.reason
                repository.save_verification(notice)
                stats["items_rejected"] = int(stats["items_rejected"]) + 1
                continue
            if not new_expired_notice_is_publishable(extracted.subtype, extracted.deadline_state, extracted.category):
                notice.verification_status = VerificationStatus.REJECTED
                notice.conflict_reason = "Deadline already passed"
                repository.save_verification(notice)
                stats["items_rejected"] = int(stats["items_rejected"]) + 1
                continue
            validation = validate_extraction(
                extracted,
                document.text,
                trusted_domains,
                document.page_text,
                official_source_url=document.final_url,
            )
            notice.verification_score = validation.score
            logger.info(
                "verification_result notice_id=%s category=%s score=%s valid=%s errors=%s conflicts=%s",
                notice.id,
                notice.category.value,
                validation.score,
                validation.valid,
                validation.errors,
                validation.conflicts,
            )
            if validation.conflicts:
                notice.verification_status = VerificationStatus.CONFLICT_DETECTED
                queue_for_review(repository, sender, notice, "; ".join(validation.conflicts))
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            if not validation.valid:
                notice.verification_status = VerificationStatus.OFFICIAL_INCOMPLETE
                queue_for_review(repository, sender, notice, "; ".join(validation.errors))
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            notice.verification_status = VerificationStatus.VERIFIED_OFFICIAL
            repository.save_verification(notice)
            stats["items_verified"] = int(stats["items_verified"]) + 1
            if notice.verification_status != VerificationStatus.VERIFIED_OFFICIAL:
                queue_for_review(repository, sender, notice, "Hard verification status was not preserved")
                stats["items_queued"] = int(stats["items_queued"]) + 1
                continue
            if extracted.publication_priority.value == "DIGEST_ONLY" and not dry_run:
                repository.mark_digest_ready(notice.id)  # type: ignore[attr-defined]
                logger.info("digest_deferred notice_id=%s category=%s", notice.id, extracted.category.value)
                continue
            message = format_telegram_message(extracted)
            image: bytes | None = None
            try:
                image = card_renderer.generate(extracted, extracted.category)
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
            if posted >= max_posts and not dry_run:
                logger.info("post_deferred notice_id=%s reason=max_posts_per_run", notice.id)
                continue
            category_key = extracted.category.value
            if category_posts.get(category_key, 0) >= max_category_posts and not dry_run:
                logger.info("post_deferred notice_id=%s reason=category_rate_limit category=%s", notice.id, category_key)
                continue
            keyboard = build_url_keyboard(extracted, trusted_domains, notice.id)
            previous = repository.get_telegram_delivery(notice.id, sender.channel_id)  # type: ignore[attr-defined]
            previous_photo = previous["photo_message_id"] if previous else None
            result = sender.send(message, image, keyboard, previous_photo_id=previous_photo)
            repository.record_telegram_delivery(  # type: ignore[attr-defined]
                notice.id, sender.channel_id or "dry-run", result.state,
                result.photo_message_id, result.text_message_id, result.error,
            )
            if result.success:
                if not dry_run:
                    repository.mark_posted(notice.id, result.photo_message_id, result.text_message_id)
                    posted += 1
                    category_posts[category_key] = category_posts.get(category_key, 0) + 1
                    stats["items_posted"] = posted
                else:
                    logger.info("dry_run_eligible notice_id=%s telegram_called=false", notice.id)
            else:
                notice.verification_status = VerificationStatus.POST_FAILED
                repository.save_verification(notice)
        logger.info("pipeline_complete posted=%s dry_run=%s", posted, dry_run)
        repository.finish_pipeline_run(run_id, stats)  # type: ignore[attr-defined]
        return posted
    except Exception as exc:
        stats["errors"] = [str(exc)]
        if run_id is not None:
            repository.finish_pipeline_run(run_id, stats, "FAILED")  # type: ignore[attr-defined]
        raise
    finally:
        if conn is not None:
            conn.close()
        if handle is not None:
            handle.close()
        card_renderer.close()


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
