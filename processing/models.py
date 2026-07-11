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
    GOVERNMENT_SERVICE = "GOVERNMENT_SERVICE"
    DOCUMENT_UPDATE = "DOCUMENT_UPDATE"


class NoticeSubtype(str, Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    CORRIGENDUM = "CORRIGENDUM"
    CANCELLED = "CANCELLED"
    DEADLINE_EXTENDED = "DEADLINE_EXTENDED"
    DEADLINE_REMINDER = "DEADLINE_REMINDER"
    RESULT_PUBLISHED = "RESULT_PUBLISHED"
    ADMIT_CARD_RELEASED = "ADMIT_CARD_RELEASED"


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
    WEST_BENGAL_ONLY = "WEST_BENGAL_ONLY"
    ALL_INDIA = "ALL_INDIA"
    OTHER_STATE_OPEN_TO_ALL = "OTHER_STATE_OPEN_TO_ALL"
    OTHER_STATE_DOMICILE_REQUIRED = "OTHER_STATE_DOMICILE_REQUIRED"
    LOCAL_LANGUAGE_REQUIRED = "LOCAL_LANGUAGE_REQUIRED"
    INSTITUTION_SPECIFIC = "INSTITUTION_SPECIFIC"
    DISTRICT_SPECIFIC = "DISTRICT_SPECIFIC"
    ELIGIBILITY_UNCLEAR = "ELIGIBILITY_UNCLEAR"
    NOT_RELEVANT_TO_WEST_BENGAL = "NOT_RELEVANT_TO_WEST_BENGAL"
    # Legacy values remain readable during the SQLite/Supabase transition.
    WEST_BENGAL = "WEST_BENGAL"
    OTHER_STATE_ONLY = "OTHER_STATE_ONLY"
    UNCLEAR = "UNCLEAR"


class RelevanceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REJECT = "REJECT"


class DeadlineState(str, Enum):
    OPEN = "OPEN"
    CLOSING_SOON = "CLOSING_SOON"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PublicationPriority(str, Enum):
    URGENT = "URGENT"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    DIGEST_ONLY = "DIGEST_ONLY"
    REJECT = "REJECT"


class TelegramDeliveryState(str, Enum):
    NOT_SENT = "NOT_SENT"
    PHOTO_SENT = "PHOTO_SENT"
    TEXT_SENT = "TEXT_SENT"
    FULLY_SENT = "FULLY_SENT"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"


class SourceType(str, Enum):
    RSS = "RSS"
    HTML = "HTML"
    JSON_API = "JSON_API"
    OFFICIAL_PDF_LIST = "OFFICIAL_PDF_LIST"
    SITEMAP = "SITEMAP"
    MANUAL = "MANUAL"


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
    west_bengal_relevance: RelevanceLevel = RelevanceLevel.LOW
    relevance_reason: str | None = None
    domicile_required: bool | None = None
    domicile_state: str | None = None
    local_language_required: bool | None = None
    required_language: str | None = None
    citizenship_requirement: str | None = None
    eligible_states: list[str] = Field(default_factory=list)
    excluded_states: list[str] = Field(default_factory=list)
    work_location: str | None = None
    application_scope: str | None = None
    institution_requirement: str | None = None
    district_requirement: str | None = None
    deadline_state: DeadlineState = DeadlineState.UNKNOWN
    publication_priority: PublicationPriority = PublicationPriority.NORMAL


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
    corrected_structured_data: dict[str, Any] | None = None


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
