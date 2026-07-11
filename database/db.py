from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from database.migrations import run_migrations
from processing.models import PipelineNotice, VerificationStatus


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "jobs.db"


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class NoticeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def discovery_already_posted(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM notices WHERE discovery_url=? AND verification_status='POSTED' LIMIT 1",
            (url,),
        ).fetchone()
        return row is not None

    def official_revision_exists(self, url: str, content_sha256: str, exclude_id: int | None = None) -> bool:
        row = self.conn.execute(
            """SELECT 1 FROM notices
               WHERE final_resolved_url=? AND content_sha256=? AND id != COALESCE(?, -1)
               LIMIT 1""",
            (url, content_sha256, exclude_id),
        ).fetchone()
        return row is not None

    def upsert_discovered(self, notice: PipelineNotice, source_domain: str = "") -> int:
        row = self.conn.execute(
            "SELECT id FROM notices WHERE discovery_url=? ORDER BY revision_number DESC LIMIT 1",
            (notice.discovery_url,),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE notices SET last_checked_at=datetime('now') WHERE id=?", (row[0],)
            )
            self.conn.commit()
            return int(row[0])
        cur = self.conn.execute(
            """INSERT INTO notices
               (category, subtype, title, discovery_url, source_name, source_domain,
                verification_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                notice.category.value,
                notice.subtype.value,
                notice.title,
                notice.discovery_url,
                notice.source_name,
                source_domain,
                notice.verification_status.value,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_verification(self, notice: PipelineNotice) -> int:
        if notice.id is None:
            notice.id = self.upsert_discovered(notice)
        structured = notice.structured.model_dump(mode="json") if notice.structured else None
        evidence = None
        if notice.structured:
            evidence = {
                key: value.model_dump(mode="json")
                for key, value in notice.structured.fields.items()
            }
        current = self.conn.execute(
            "SELECT content_sha256, revision_number FROM notices WHERE id=?", (notice.id,)
        ).fetchone()
        revision = int(current["revision_number"] or 1)
        if (
            current["content_sha256"]
            and notice.content_sha256
            and current["content_sha256"] != notice.content_sha256
        ):
            revision += 1
            notice.subtype = notice.subtype if notice.subtype.value != "NEW" else type(notice.subtype).UPDATED
            notice.verification_status = VerificationStatus.UPDATED
        self.conn.execute(
            """UPDATE notices SET
               category=?, subtype=?, official_page_url=?, official_document_url=?,
               final_resolved_url=?, final_domain=?, trusted_domain=?, content_sha256=?,
               structured_data_json=?, evidence_json=?, verification_score=?,
               verification_status=?, conflict_reason=?, render_status=?, revision_number=?,
               issuing_authority=?, notice_number=?, notice_date=?, deadline=?,
               verified_at=CASE WHEN ?='VERIFIED_OFFICIAL' THEN datetime('now') ELSE verified_at END,
               last_checked_at=datetime('now') WHERE id=?""",
            (
                notice.category.value,
                notice.subtype.value,
                notice.official_page_url,
                notice.official_document_url,
                notice.final_resolved_url,
                notice.final_domain,
                int(bool(notice.final_domain)),
                notice.content_sha256,
                json.dumps(structured, ensure_ascii=False) if structured else None,
                json.dumps(evidence, ensure_ascii=False) if evidence else None,
                notice.verification_score,
                notice.verification_status.value,
                notice.conflict_reason,
                notice.render_status,
                revision,
                _value(notice, "issuing_authority"),
                _value(notice, "notice_number"),
                _value(notice, "notice_date"),
                _field_value(notice, "deadline"),
                notice.verification_status.value,
                notice.id,
            ),
        )
        if notice.content_sha256:
            self.conn.execute(
                """INSERT OR IGNORE INTO notice_revisions
                   (notice_id, revision_number, content_sha256, final_resolved_url,
                    structured_data_json, evidence_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    notice.id,
                    revision,
                    notice.content_sha256,
                    notice.final_resolved_url,
                    json.dumps(structured, ensure_ascii=False) if structured else None,
                    json.dumps(evidence, ensure_ascii=False) if evidence else None,
                ),
            )
        self.conn.commit()
        return revision

    def enqueue_review(self, notice_id: int, reason: str) -> int:
        self.conn.execute(
            """INSERT OR IGNORE INTO review_queue(notice_id, reason)
               VALUES (?, ?)""",
            (notice_id, reason),
        )
        row = self.conn.execute(
            "SELECT id FROM review_queue WHERE notice_id=? AND status='PENDING'", (notice_id,)
        ).fetchone()
        self.conn.commit()
        return int(row[0])

    def mark_posted(self, notice_id: int, photo_id: str | None, text_id: str | None) -> None:
        self.conn.execute(
            """UPDATE notices SET verification_status='POSTED', posted_at=datetime('now'),
               telegram_photo_message_id=?, telegram_text_message_id=? WHERE id=?""",
            (photo_id, text_id, notice_id),
        )
        self.conn.commit()

    def increment_usage(self, provider: str, operation: str) -> int:
        self.conn.execute(
            """INSERT INTO provider_usage(provider, usage_date, operation, calls)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(provider, usage_date, operation) DO UPDATE SET calls=calls+1""",
            (provider, utc_date(), operation),
        )
        self.conn.commit()
        return self.get_usage(provider, operation)

    def get_usage(self, provider: str, operation: str) -> int:
        row = self.conn.execute(
            "SELECT calls FROM provider_usage WHERE provider=? AND usage_date=? AND operation=?",
            (provider, utc_date(), operation),
        ).fetchone()
        return int(row[0]) if row else 0


def _value(notice: PipelineNotice, name: str) -> str | None:
    if not notice.structured:
        return None
    field = getattr(notice.structured, name)
    return str(field.value) if field.value is not None else None


def _field_value(notice: PipelineNotice, name: str) -> str | None:
    if not notice.structured or name not in notice.structured.fields:
        return None
    value = notice.structured.fields[name].value
    return str(value) if value is not None else None
