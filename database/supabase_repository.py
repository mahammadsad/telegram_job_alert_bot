from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from processing.deduplicator import same_notice
from processing.deadlines import parse_notice_date
from processing.models import PipelineNotice, TelegramDeliveryState, VerificationStatus
from processing.verifier import canonicalize_url


class SupabaseRepository:
    """Small PostgREST adapter for GitHub Actions service-role access.

    Browser code never imports this class or receives its key. Requests have
    explicit timeouts and errors are raised so failed writes cannot look posted.
    """

    def __init__(
        self, url: str | None = None, service_role_key: str | None = None,
        session: requests.Session | None = None,
    ):
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.url or not self.key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.session = session or requests.Session()
        self.headers = {
            "apikey": self.key, "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json", "Accept": "application/json",
        }

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, path: str, *, params: dict | None = None, body: object = None,
                 prefer: str | None = None) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        response = self.session.request(
            method, f"{self.url}/rest/v1/{path}", headers=headers, params=params,
            json=body, timeout=30,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    def _one(self, table: str, params: dict[str, str]) -> dict | None:
        rows = self._request("GET", table, params={**params, "limit": "1"})
        return rows[0] if rows else None

    def get_by_discovery_url(self, url: str) -> dict | None:
        row = self._one("notices", {"discovery_url": f"eq.{url}", "order": "revision_number.desc"})
        if row:
            row["content_sha256"] = row.get("official_document_hash")
            row["final_domain"] = row.get("official_domain")
            row["structured_data_json"] = json.dumps(row.get("structured_data") or {})
        return row

    def list_sources(self) -> list[dict]:
        rows = self._request("GET", "sources", params={"order": "name.asc"}) or []
        for row in rows:
            row["url"] = row.get("feed_url") or row.get("base_url")
        return rows

    @staticmethod
    def is_legacy_posted(row: dict | None) -> bool:
        if not row or row.get("verification_status") != VerificationStatus.POSTED.value:
            return False
        structured = row.get("structured_data") or {}
        return bool(structured.get("legacy_seen_job")) or not (
            row.get("final_resolved_url") and row.get("official_document_hash")
        )

    @staticmethod
    def is_same_posted_revision(row: dict | None, final_url: str, content_sha256: str) -> bool:
        if not row or row.get("verification_status") != VerificationStatus.POSTED.value:
            return False
        return same_notice(
            row.get("canonical_official_url") or row.get("final_resolved_url"),
            row.get("official_document_hash"), final_url, content_sha256,
        )

    def official_revision_exists(self, url: str, content_sha256: str, exclude_id: int | None = None) -> bool:
        params = {
            "or": f"(canonical_official_url.eq.{canonicalize_url(url)},final_resolved_url.eq.{url})",
            "official_document_hash": f"eq.{content_sha256}", "select": "id",
        }
        rows = self._request("GET", "notices", params=params) or []
        return any(int(row["id"]) != int(exclude_id or -1) for row in rows)

    def upsert_discovered(self, notice: PipelineNotice, source_domain: str = "") -> int:
        existing = self.get_by_discovery_url(notice.discovery_url)
        data = {
            "category": notice.category.value, "subtype": notice.subtype.value,
            "original_title": notice.title, "discovery_url": notice.discovery_url,
            "source_name": notice.source_name, "source_domain": source_domain,
            "discovery_summary": notice.metadata.get("summary"),
            "candidate_official_links": notice.metadata.get("candidate_official_links", []),
            "source_official": bool(notice.metadata.get("official")),
            "discovery_only": bool(notice.metadata.get("discovery_only", True)),
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            self._request("PATCH", "notices", params={"id": f"eq.{existing['id']}"}, body=data)
            return int(existing["id"])
        rows = self._request("POST", "notices", body=data, prefer="return=representation")
        return int(rows[0]["id"])

    def save_verification(self, notice: PipelineNotice) -> int:
        if notice.id is None:
            notice.id = self.upsert_discovered(notice)
        current = self._one("notices", {"id": f"eq.{notice.id}"}) or {}
        revision = int(current.get("revision_number") or 1)
        old_hash = current.get("official_document_hash")
        if old_hash and notice.content_sha256 and old_hash != notice.content_sha256:
            revision += 1
            if notice.subtype.value == "NEW":
                notice.subtype = type(notice.subtype).UPDATED
        structured = notice.structured.model_dump(mode="json") if notice.structured else None
        data = {
            "category": notice.category.value, "subtype": notice.subtype.value,
            "title_bn": notice.structured.title_bn if notice.structured else None,
            "official_page_url": notice.official_page_url,
            "official_document_url": notice.official_document_url,
            "final_resolved_url": notice.final_resolved_url,
            "canonical_official_url": canonicalize_url(notice.final_resolved_url) if notice.final_resolved_url else None,
            "official_domain": notice.final_domain, "official_document_hash": notice.content_sha256,
            "structured_data": structured, "verification_score": notice.verification_score,
            "verification_status": notice.verification_status.value,
            "conflict_reason": notice.conflict_reason, "render_status": notice.render_status,
            "revision_number": revision, "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if notice.structured:
            data.update({
                "issuing_authority": _ev(notice, "issuing_authority"),
                "notice_number": _ev(notice, "notice_number"), "notice_date": _ev(notice, "notice_date"),
                "deadline": parse_notice_date(_field(notice, "deadline")).isoformat() if parse_notice_date(_field(notice, "deadline")) else None,
                "original_deadline_text": _field(notice, "deadline"),
                "eligibility_status": notice.structured.eligibility_scope.value if notice.structured.eligibility_scope else None,
                "west_bengal_relevance": notice.structured.west_bengal_relevance.value,
                "relevance_reason": notice.structured.relevance_reason,
                "deadline_state": notice.structured.deadline_state.value,
                "publication_priority": notice.structured.publication_priority.value,
            })
        if notice.verification_status == VerificationStatus.VERIFIED_OFFICIAL:
            data["verified_at"] = datetime.now(timezone.utc).isoformat()
        self._request("PATCH", "notices", params={"id": f"eq.{notice.id}"}, body=data)
        if notice.content_sha256:
            self._request(
                "POST", "notice_revisions",
                params={"on_conflict": "notice_id,revision_number"},
                body={"notice_id": notice.id, "revision_number": revision,
                      "official_document_hash": notice.content_sha256,
                      "official_url": notice.final_resolved_url, "structured_data": structured},
                prefer="resolution=merge-duplicates",
            )
        if notice.structured:
            self._request("DELETE", "notice_evidence", params={"notice_id": f"eq.{notice.id}"})
            evidence_fields = {
                "issuing_authority": notice.structured.issuing_authority,
                "notice_number": notice.structured.notice_number,
                "notice_date": notice.structured.notice_date,
                **notice.structured.fields,
            }
            rows = [
                {
                    "notice_id": notice.id, "field_name": name, "extracted_value": value.value,
                    "evidence_text": value.evidence, "page_number": value.evidence_page,
                    "source_url": value.source_url or notice.final_resolved_url,
                    "validation_status": "VALID" if notice.verification_status == VerificationStatus.VERIFIED_OFFICIAL else "PENDING",
                }
                for name, value in evidence_fields.items() if value.value is not None and (value.source_url or notice.final_resolved_url)
            ]
            if rows:
                self._request("POST", "notice_evidence", body=rows)
        return revision

    def enqueue_review(self, notice_id: int, reason: str) -> int:
        existing = self._one("review_queue", {"notice_id": f"eq.{notice_id}", "status": "eq.PENDING"})
        if existing:
            return int(existing["id"])
        rows = self._request("POST", "review_queue", body={"notice_id": notice_id, "review_reason": reason}, prefer="return=representation")
        return int(rows[0]["id"])

    def review_candidates(self) -> list[dict]:
        queue = self._request("GET", "review_queue", params={"status": "in.(APPROVED,RETRY)", "select": "id,notice_id,corrected_official_url,corrected_structured_data"}) or []
        results: list[dict] = []
        for item in queue:
            row = self._one("notices", {"id": f"eq.{item['notice_id']}"})
            if row:
                results.append({
                    "title": row["original_title"], "discovery_url": row["discovery_url"],
                    "source_name": row.get("source_name") or "Review queue",
                    "source_domain": row.get("source_domain") or "", "category_hints": [row["category"]],
                    "summary": row.get("discovery_summary") or "",
                    "candidate_official_links": list(dict.fromkeys(
                        ([item["corrected_official_url"]] if item.get("corrected_official_url") else [])
                        + (row.get("candidate_official_links") or [])
                    )),
                    "official": bool(row.get("source_official")), "discovery_only": bool(row.get("discovery_only", True)),
                    "corrected_structured_data": item.get("corrected_structured_data"),
                })
            self._request("PATCH", "review_queue", params={"id": f"eq.{item['id']}"}, body={"status": "PROCESSING"})
        return results

    def mark_posted(self, notice_id: int, photo_id: str | None, text_id: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._request("PATCH", "notices", params={"id": f"eq.{notice_id}"}, body={
            "verification_status": "POSTED", "publication_status": "PUBLISHED", "posted_at": now,
        })
        self._request("PATCH", "review_queue", params={"notice_id": f"eq.{notice_id}", "status": "in.(PENDING,APPROVED,RETRY,PROCESSING)"}, body={
            "status": "RESOLVED", "resolved_at": now, "updated_at": now,
        })

    def mark_digest_ready(self, notice_id: int) -> None:
        self._request("PATCH", "notices", params={"id": f"eq.{notice_id}"}, body={
            "publication_status": "PUBLISHED", "verification_status": "VERIFIED_OFFICIAL",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def record_telegram_delivery(self, notice_id: int, channel_id: str, state: TelegramDeliveryState,
                                 photo_id: str | None = None, text_id: str | None = None,
                                 error: str | None = None) -> None:
        self._request("POST", "telegram_posts", params={"on_conflict": "notice_id,channel_id"}, body={
            "notice_id": notice_id, "channel_id": channel_id, "photo_message_id": photo_id,
            "text_message_id": text_id, "delivery_state": state.value, "error": (error or "")[:2000],
        }, prefer="resolution=merge-duplicates")

    def get_telegram_delivery(self, notice_id: int, channel_id: str) -> dict | None:
        return self._one("telegram_posts", {"notice_id": f"eq.{notice_id}", "channel_id": f"eq.{channel_id}"})

    def source_check_due(self, source_name: str, min_interval_minutes: int) -> bool:
        if min_interval_minutes <= 0:
            return True
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=min_interval_minutes)).isoformat()
        return self._one("source_checks", {"source_name": f"eq.{source_name}", "checked_at": f"gt.{cutoff}"}) is None

    def record_source_check(self, source_name: str, source_url: str, status: str, detail: str = "") -> None:
        self._request("POST", "source_checks", body={"source_name": source_name, "source_url": source_url,
                                                        "status": status, "detail": detail[:2000]})
        source = self._one("sources", {"name": f"eq.{source_name}"})
        if source:
            now = datetime.now(timezone.utc).isoformat()
            update = {
                "health_status": "HEALTHY" if status == "SUCCESS" else "FAILING",
                "consecutive_failures": 0 if status == "SUCCESS" else int(source.get("consecutive_failures") or 0) + 1,
                "last_success_at" if status == "SUCCESS" else "last_failure_at": now,
                "updated_at": now,
            }
            self._request("PATCH", "sources", params={"id": f"eq.{source['id']}"}, body=update)

    def get_usage(self, provider: str, operation: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._one("provider_usage", {"provider": f"eq.{provider}", "usage_date": f"eq.{today}", "operation": f"eq.{operation}"})
        return int(row["calls"]) if row else 0

    def increment_usage(self, provider: str, operation: str) -> int:
        result = self._request("POST", "rpc/increment_provider_usage", body={"p_provider": provider, "p_operation": operation})
        return int(result)

    def start_pipeline_run(self, dry_run: bool) -> int:
        rows = self._request("POST", "pipeline_runs", body={"dry_run": dry_run}, prefer="return=representation")
        return int(rows[0]["id"])

    def finish_pipeline_run(self, run_id: int, stats: dict[str, object], state: str = "COMPLETED") -> None:
        self._request("PATCH", "pipeline_runs", params={"id": f"eq.{run_id}"}, body={
            "ended_at": datetime.now(timezone.utc).isoformat(), "state": state,
            "sources_checked": int(stats.get("sources_checked", 0)),
            "items_discovered": int(stats.get("items_discovered", 0)),
            "items_verified": int(stats.get("items_verified", 0)), "items_posted": int(stats.get("items_posted", 0)),
            "items_rejected": int(stats.get("items_rejected", 0)), "items_queued": int(stats.get("items_queued", 0)),
            "duplicates": int(stats.get("duplicates", 0)), "errors": stats.get("errors", []),
        })


def _ev(notice: PipelineNotice, name: str) -> str | None:
    value = getattr(notice.structured, name).value if notice.structured else None
    return str(value) if value is not None else None


def _field(notice: PipelineNotice, name: str) -> str | None:
    value = notice.structured.fields.get(name).value if notice.structured and name in notice.structured.fields else None
    return str(value) if value is not None else None
