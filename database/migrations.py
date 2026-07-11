from __future__ import annotations

import json
import logging
import sqlite3


logger = logging.getLogger(__name__)


MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            subtype TEXT NOT NULL DEFAULT 'NEW',
            title TEXT NOT NULL,
            issuing_authority TEXT,
            discovery_url TEXT NOT NULL,
            official_page_url TEXT,
            official_document_url TEXT,
            final_resolved_url TEXT,
            source_name TEXT,
            source_domain TEXT,
            final_domain TEXT,
            trusted_domain INTEGER NOT NULL DEFAULT 0,
            notice_number TEXT,
            notice_date TEXT,
            published_date TEXT,
            deadline TEXT,
            structured_data_json TEXT,
            evidence_json TEXT,
            content_sha256 TEXT,
            verification_score INTEGER NOT NULL DEFAULT 0,
            verification_status TEXT NOT NULL DEFAULT 'DISCOVERED',
            conflict_reason TEXT,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_checked_at TEXT NOT NULL DEFAULT (datetime('now')),
            verified_at TEXT,
            posted_at TEXT,
            telegram_photo_message_id TEXT,
            telegram_text_message_id TEXT,
            render_status TEXT,
            revision_number INTEGER NOT NULL DEFAULT 1,
            manually_approved INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_notices_discovery_url ON notices(discovery_url);
        CREATE INDEX IF NOT EXISTS idx_notices_official_url ON notices(final_resolved_url);
        CREATE INDEX IF NOT EXISTS idx_notices_hash ON notices(content_sha256);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_notice_revision
            ON notices(final_resolved_url, content_sha256)
            WHERE final_resolved_url IS NOT NULL AND content_sha256 IS NOT NULL;
        CREATE TABLE IF NOT EXISTS notice_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id INTEGER NOT NULL REFERENCES notices(id),
            revision_number INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            final_resolved_url TEXT,
            structured_data_json TEXT,
            evidence_json TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(notice_id, revision_number),
            UNIQUE(notice_id, content_sha256)
        );
        CREATE TABLE IF NOT EXISTS source_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT,
            checked_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS review_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id INTEGER NOT NULL REFERENCES notices(id),
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewer_note TEXT,
            UNIQUE(notice_id, status)
        );
        CREATE TABLE IF NOT EXISTS provider_usage (
            provider TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            operation TEXT NOT NULL,
            calls INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(provider, usage_date, operation)
        );
    """),
    (2, """
        ALTER TABLE notices ADD COLUMN canonical_official_url TEXT;
        ALTER TABLE notices ADD COLUMN discovery_summary TEXT;
        ALTER TABLE notices ADD COLUMN candidate_official_links_json TEXT;
        ALTER TABLE notices ADD COLUMN source_official INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE notices ADD COLUMN discovery_only INTEGER NOT NULL DEFAULT 1;
        CREATE INDEX IF NOT EXISTS idx_notices_canonical_official_url
            ON notices(canonical_official_url);
        CREATE INDEX IF NOT EXISTS idx_source_checks_name_checked
            ON source_checks(source_name, checked_at);
    """),
    (3, """
        ALTER TABLE notice_revisions RENAME TO notice_revisions_old;
        CREATE TABLE notice_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id INTEGER NOT NULL REFERENCES notices(id),
            revision_number INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            final_resolved_url TEXT,
            structured_data_json TEXT,
            evidence_json TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(notice_id, revision_number)
        );
        INSERT INTO notice_revisions (
            id, notice_id, revision_number, content_sha256, final_resolved_url,
            structured_data_json, evidence_json, detected_at
        )
        SELECT id, notice_id, revision_number, content_sha256, final_resolved_url,
               structured_data_json, evidence_json, detected_at
        FROM notice_revisions_old;
        DROP TABLE notice_revisions_old;
        CREATE INDEX idx_notice_revisions_hash
            ON notice_revisions(notice_id, content_sha256);
    """),
    (4, """
        ALTER TABLE notices ADD COLUMN title_bn TEXT;
        ALTER TABLE notices ADD COLUMN title_en TEXT;
        ALTER TABLE notices ADD COLUMN eligibility_status TEXT;
        ALTER TABLE notices ADD COLUMN west_bengal_relevance TEXT NOT NULL DEFAULT 'LOW';
        ALTER TABLE notices ADD COLUMN relevance_reason TEXT;
        ALTER TABLE notices ADD COLUMN deadline_state TEXT NOT NULL DEFAULT 'UNKNOWN';
        ALTER TABLE notices ADD COLUMN publication_priority TEXT NOT NULL DEFAULT 'NORMAL';
        ALTER TABLE notices ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'DRAFT';
        ALTER TABLE notices ADD COLUMN eligibility_json TEXT;
        CREATE INDEX IF NOT EXISTS idx_notices_category_status ON notices(category, publication_status);
        CREATE INDEX IF NOT EXISTS idx_notices_deadline ON notices(deadline, deadline_state);
        CREATE INDEX IF NOT EXISTS idx_notices_relevance ON notices(west_bengal_relevance);

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL, parser_type TEXT NOT NULL, base_url TEXT NOT NULL,
            feed_url TEXT, official INTEGER NOT NULL DEFAULT 0, discovery_only INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 0, categories_json TEXT NOT NULL DEFAULT '[]', state TEXT,
            authority_type TEXT, allowed_domains_json TEXT NOT NULL DEFAULT '[]',
            allowed_document_domains_json TEXT NOT NULL DEFAULT '[]', item_selector TEXT,
            title_selector TEXT, link_selector TEXT, summary_selector TEXT, date_selector TEXT,
            min_interval_minutes INTEGER NOT NULL DEFAULT 120, request_timeout INTEGER NOT NULL DEFAULT 20,
            max_items INTEGER NOT NULL DEFAULT 20, robots_status TEXT, terms_reviewed INTEGER NOT NULL DEFAULT 0,
            selector_verified_at TEXT, last_success_at TEXT, last_failure_at TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0, health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            notes TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS notice_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, notice_id INTEGER NOT NULL REFERENCES notices(id),
            field_name TEXT NOT NULL, extracted_value TEXT, evidence_text TEXT, page_number INTEGER,
            source_url TEXT NOT NULL, validation_status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL DEFAULT (datetime('now')),
            ended_at TEXT, state TEXT NOT NULL DEFAULT 'RUNNING', sources_checked INTEGER NOT NULL DEFAULT 0,
            items_discovered INTEGER NOT NULL DEFAULT 0, items_verified INTEGER NOT NULL DEFAULT 0,
            items_posted INTEGER NOT NULL DEFAULT 0, items_rejected INTEGER NOT NULL DEFAULT 0,
            items_queued INTEGER NOT NULL DEFAULT 0, duplicates INTEGER NOT NULL DEFAULT 0,
            errors_json TEXT NOT NULL DEFAULT '[]', dry_run INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS telegram_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, notice_id INTEGER NOT NULL REFERENCES notices(id),
            channel_id TEXT NOT NULL, photo_message_id TEXT, text_message_id TEXT,
            delivery_state TEXT NOT NULL DEFAULT 'NOT_SENT', error TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(notice_id, channel_id)
        );
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY, email TEXT, role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, categories_json TEXT NOT NULL DEFAULT '[]',
            relevance_json TEXT NOT NULL DEFAULT '[]', district TEXT, telegram_chat_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(user_id)
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT, action TEXT NOT NULL,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, reason TEXT NOT NULL,
            changes_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """),
    (5, """
        ALTER TABLE review_queue ADD COLUMN corrected_official_url TEXT;
        ALTER TABLE review_queue ADD COLUMN corrected_structured_data_json TEXT;
        ALTER TABLE review_queue ADD COLUMN priority TEXT NOT NULL DEFAULT 'NORMAL';
        ALTER TABLE review_queue ADD COLUMN assigned_reviewer TEXT;
        ALTER TABLE review_queue ADD COLUMN resolved_at TEXT;
    """),
    (6, """
        CREATE TABLE IF NOT EXISTS publication_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, digest_date TEXT NOT NULL UNIQUE,
            notice_ids_json TEXT NOT NULL DEFAULT '[]', telegram_message_id TEXT,
            delivery_state TEXT NOT NULL DEFAULT 'NOT_SENT', error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """),
]


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_legacy_seen_jobs(conn: sqlite3.Connection) -> int:
    if not _has_table(conn, "seen_jobs"):
        return 0
    rows = conn.execute("SELECT url, title, source, found_at FROM seen_jobs").fetchall()
    before = conn.total_changes
    for url, title, source, found_at in rows:
        conn.execute(
            """
            INSERT INTO notices (
                category, subtype, title, discovery_url, source_name,
                verification_status, posted_at, first_seen_at, last_checked_at,
                structured_data_json
            )
            SELECT 'JOB', 'NEW', ?, ?, ?, 'POSTED', ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM notices WHERE discovery_url = ? AND verification_status = 'POSTED'
            )
            """,
            (
                title or "Historical job",
                url,
                source,
                found_at,
                found_at,
                found_at,
                json.dumps({"legacy_seen_job": True}),
                url,
            ),
        )
    return conn.total_changes - before


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        logger.info("database_migration applied version=%s", version)
    migrated = migrate_legacy_seen_jobs(conn)
    conn.commit()
    logger.info("database_migration legacy_rows_added=%s", migrated)
