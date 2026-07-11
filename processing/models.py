from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NoticeCategory(str, Enum):
    JOB = "JOB"
    WELFARE_SCHEME = "WELFARE_SCHEME"
    SCHOLARSHIP = "SCHOLARSHIP"
    ADMISSION = "ADMISSION"
    RESULT = "RESULT"
    EXAMINATION = "EXAMINATION"
    EDUCATION_NOTICE = "EDUCATION_NOTICE"
    UNIVERSITY_NOTICE = "UNIVERSITY_NOTICE"
    GOVERNMENT_ANNOUNCEMENT = "GOVERNMENT_ANNOUNCEMENT"


class NoticeSubtype(str, Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    CORRIGENDUM = "CORRIGENDUM"
    CANCELLED = "CANCELLED"
    DEADLINE_EXTENDED = "DEADLINE_EXTENDED"


class VerificationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    OFFICIAL_SOURCE_FOUND = "OFFICIAL_SOURCE_FOUND"
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"
    OFFICIAL_INCOMPLETE = "OFFICIAL_INCOMPLETE"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    REJECTED = "REJECTED"
    POSTED = "POSTED"
    POST_FAILED = "POST_FAILED"
    UPDATED = "UPDATED"
    CANCELLED = "CANCELLED"


class EligibilityScope(str, Enum):
    ALL_INDIA = "ALL_INDIA"
    WEST_BENGAL = "WEST_BENGAL"
    OTHER_STATE_ONLY = "OTHER_STATE_ONLY"
    UNCLEAR = "UNCLEAR"


class EvidenceValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | int | float | list[str] | None = None
    evidence: str | None = None
    evidence_page: int | None = Field(default=None, ge=1)
    source_url: str | None = None

    @field_validator("evidence")
    @classmethod
    def short_evidence(cls, value: str | None) -> str | None:
        return value[:500].strip() if value else None


class ExtractedNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: NoticeCategory
    subtype: NoticeSubtype = NoticeSubtype.NEW
    title_bn: str
    issuing_authority: EvidenceValue
    notice_number: EvidenceValue = Field(default_factory=EvidenceValue)
    notice_date: EvidenceValue = Field(default_factory=EvidenceValue)
    fields: dict[str, EvidenceValue]
    eligibility_scope: EligibilityScope | None = None
    eligibility_reason: str | None = None


class DiscoveredItem(BaseModel):
    title: str
    discovery_url: str
    source_name: str
    source_domain: str
    category_hints: list[NoticeCategory] = Field(default_factory=list)
    summary: str = ""
    candidate_official_links: list[str] = Field(default_factory=list)
    official: bool = False
    discovery_only: bool = True


class OfficialDocument(BaseModel):
    requested_url: str
    final_url: str
    final_domain: str
    content_type: str
    content_sha256: str
    text: str
    page_text: dict[int, str] = Field(default_factory=dict)
    extracted_links: list[str] = Field(default_factory=list)
    redirect_chain: list[str] = Field(default_factory=list)
    scanned_pdf: bool = False


class PipelineNotice(BaseModel):
    id: int | None = None
    category: NoticeCategory
    subtype: NoticeSubtype = NoticeSubtype.NEW
    title: str
    discovery_url: str
    source_name: str
    official_page_url: str | None = None
    official_document_url: str | None = None
    final_resolved_url: str | None = None
    final_domain: str | None = None
    trusted_domain: bool = False
    content_sha256: str | None = None
    structured: ExtractedNotice | None = None
    verification_score: int = 0
    verification_status: VerificationStatus = VerificationStatus.DISCOVERED
    conflict_reason: str | None = None
    render_status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
