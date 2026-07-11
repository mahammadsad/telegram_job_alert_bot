#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.supabase_repository import SupabaseRepository  # noqa: E402


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "select 1 from sqlite_master where type='table' and name=?", (table,)
    ).fetchone() is not None


def parse_json(value: object, fallback: object) -> object:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def notice_payload(row: sqlite3.Row) -> dict:
    fields = set(row.keys())
    get = lambda key, default=None: row[key] if key in fields else default
    structured = parse_json(get("structured_data_json"), {})
    return {
        "category": get("category", "JOB"), "subtype": get("subtype", "NEW"),
        "original_title": get("title") or "Imported notice", "title_bn": get("title_bn"),
        "issuing_authority": get("issuing_authority"), "discovery_url": get("discovery_url"),
        "source_name": get("source_name"), "source_domain": get("source_domain"),
        "discovery_summary": get("discovery_summary"),
        "candidate_official_links": parse_json(get("candidate_official_links_json"), []),
        "source_official": bool(get("source_official", 0)), "discovery_only": bool(get("discovery_only", 1)),
        "official_page_url": get("official_page_url"), "official_document_url": get("official_document_url"),
        "final_resolved_url": get("final_resolved_url"), "canonical_official_url": get("canonical_official_url"),
        "official_domain": get("final_domain"), "official_document_hash": get("content_sha256"),
        "notice_number": get("notice_number"), "notice_date": get("notice_date"),
        "original_deadline_text": get("deadline"), "eligibility_status": get("eligibility_status"),
        "west_bengal_relevance": get("west_bengal_relevance", "LOW"),
        "relevance_reason": get("relevance_reason"), "deadline_state": get("deadline_state", "UNKNOWN"),
        "publication_priority": get("publication_priority", "NORMAL"),
        "publication_status": "PUBLISHED" if get("verification_status") == "POSTED" else get("publication_status", "DRAFT"),
        "verification_score": get("verification_score", 0), "verification_status": get("verification_status", "DISCOVERED"),
        "structured_data": structured, "conflict_reason": get("conflict_reason"),
        "render_status": get("render_status"), "revision_number": get("revision_number", 1),
        "manually_approved": bool(get("manually_approved", 0)), "first_seen_at": get("first_seen_at"),
        "last_checked_at": get("last_checked_at"), "verified_at": get("verified_at"), "posted_at": get("posted_at"),
    }


def import_database(path: Path, repository: SupabaseRepository, dry_run: bool = False) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    counts = {"notices": 0, "revisions": 0, "source_checks": 0, "review_queue": 0}
    id_map: dict[int, int] = {}
    try:
        for row in connection.execute("select * from notices order by id"):
            payload = notice_payload(row)
            if not payload["discovery_url"]:
                continue
            if dry_run:
                new_id = int(row["id"])
            else:
                result = repository._request(
                    "POST", "notices", params={"on_conflict": "discovery_url"}, body=payload,
                    prefer="resolution=merge-duplicates,return=representation",
                )
                new_id = int(result[0]["id"])
            id_map[int(row["id"])] = new_id
            counts["notices"] += 1

        if table_exists(connection, "notice_revisions"):
            for row in connection.execute("select * from notice_revisions order by id"):
                if int(row["notice_id"]) not in id_map:
                    continue
                payload = {
                    "notice_id": id_map[int(row["notice_id"])], "revision_number": int(row["revision_number"]),
                    "official_document_hash": row["content_sha256"], "official_url": row["final_resolved_url"],
                    "structured_data": parse_json(row["structured_data_json"], {}), "detected_at": row["detected_at"],
                }
                if not dry_run:
                    repository._request("POST", "notice_revisions", params={"on_conflict": "notice_id,revision_number"},
                                        body=payload, prefer="resolution=merge-duplicates")
                counts["revisions"] += 1

        if table_exists(connection, "source_checks"):
            for row in connection.execute("select * from source_checks order by id"):
                payload = {key: row[key] for key in ("source_name", "source_url", "status", "detail", "checked_at")}
                fingerprint = "\x1f".join(str(payload.get(key) or "") for key in sorted(payload))
                payload["legacy_import_key"] = hashlib.sha256(fingerprint.encode()).hexdigest()
                if not dry_run:
                    repository._request(
                        "POST", "source_checks", params={"on_conflict": "legacy_import_key"},
                        body=payload, prefer="resolution=ignore-duplicates",
                    )
                counts["source_checks"] += 1

        if table_exists(connection, "review_queue"):
            for row in connection.execute("select * from review_queue order by id"):
                if int(row["notice_id"]) not in id_map:
                    continue
                payload = {
                    "notice_id": id_map[int(row["notice_id"])], "review_reason": row["reason"],
                    "status": row["status"], "admin_note": row["reviewer_note"],
                    "created_at": row["created_at"], "updated_at": row["updated_at"],
                }
                if not dry_run:
                    existing = repository._one("review_queue", {"notice_id": f"eq.{payload['notice_id']}", "status": f"eq.{payload['status']}"})
                    if not existing:
                        repository._request("POST", "review_queue", body=payload)
                counts["review_queue"] += 1
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotently import jobs.db into Supabase")
    parser.add_argument("--database", type=Path, default=ROOT / "jobs.db")
    parser.add_argument("--dry-run", action="store_true", help="Validate and count without writing")
    args = parser.parse_args()
    if not args.database.exists():
        raise SystemExit(f"SQLite database not found: {args.database}")
    repository = SupabaseRepository() if not args.dry_run else object()
    try:
        counts = import_database(args.database, repository, args.dry_run)  # type: ignore[arg-type]
    finally:
        if not args.dry_run:
            repository.close()  # type: ignore[union-attr]
    print(json.dumps({"dry_run": args.dry_run, **counts}, indent=2))


if __name__ == "__main__":
    main()
