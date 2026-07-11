from __future__ import annotations

from processing.models import NoticeCategory


CATEGORY_FIELDS: dict[NoticeCategory, list[str]] = {
    NoticeCategory.JOB: [
        "department", "post_name", "total_vacancies", "qualifications", "age_limit",
        "salary", "deadline", "application_start", "application_fee", "apply_mode",
        "selection_process", "official_notification_url", "official_application_url",
    ],
    NoticeCategory.WELFARE_SCHEME: [
        "scheme_name", "department", "benefit", "eligibility", "age_requirement",
        "income_limit", "required_documents", "application_method", "application_start",
        "deadline", "beneficiary_group", "official_information_url", "official_application_url",
    ],
    NoticeCategory.SCHOLARSHIP: [
        "scholarship_name", "provider", "benefit_amount", "educational_eligibility",
        "income_limit", "required_documents", "application_start", "deadline",
        "renewal_or_fresh", "official_information_url", "official_application_url",
    ],
    NoticeCategory.ADMISSION: [
        "institution", "course_or_program", "academic_session", "eligibility",
        "application_start", "deadline", "application_fee", "selection_process",
        "counselling_information", "official_notification_url", "official_application_url",
    ],
    NoticeCategory.RESULT: [
        "board_or_university", "exam_name", "academic_session", "result_date",
        "credentials_required", "rechecking_or_review_information", "official_result_url",
        "official_notice_url",
    ],
    NoticeCategory.EXAMINATION: [
        "conducting_body", "exam_name", "exam_date", "exam_time", "admit_card_date",
        "exam_mode", "exam_centres", "candidate_instructions", "official_routine_url",
        "official_notice_url",
    ],
    NoticeCategory.EDUCATION_NOTICE: [
        "institution", "notice_subject", "affected_students", "course", "semester_or_year",
        "important_date", "action_required", "submission_portal_or_office",
        "required_documents", "official_notice_url",
    ],
    NoticeCategory.UNIVERSITY_NOTICE: [
        "institution", "notice_subject", "affected_students", "course", "semester_or_year",
        "important_date", "action_required", "submission_portal_or_office",
        "required_documents", "official_notice_url",
    ],
    NoticeCategory.GOVERNMENT_ANNOUNCEMENT: [
        "issuing_department", "announcement_subject", "affected_people", "effective_date",
        "action_required", "required_documents", "service_or_portal", "official_notice_url",
    ],
    NoticeCategory.GOVERNMENT_SERVICE: [
        "service_name", "department", "eligibility", "required_documents",
        "application_method", "deadline", "service_location",
        "official_information_url", "official_application_url",
    ],
    NoticeCategory.DOCUMENT_UPDATE: [
        "document_name", "issuing_department", "affected_people", "change_summary",
        "effective_date", "deadline", "action_required", "required_documents",
        "official_notice_url", "official_application_url",
    ],
}


REQUIRED_FIELDS: dict[NoticeCategory, set[str]] = {
    NoticeCategory.JOB: {"department", "post_name", "qualifications", "official_notification_url"},
    NoticeCategory.WELFARE_SCHEME: {"scheme_name", "department", "benefit", "eligibility", "official_information_url"},
    NoticeCategory.SCHOLARSHIP: {"scholarship_name", "provider", "educational_eligibility", "official_information_url"},
    NoticeCategory.ADMISSION: {"institution", "course_or_program", "eligibility", "official_notification_url"},
    NoticeCategory.RESULT: {"board_or_university", "exam_name", "official_result_url"},
    NoticeCategory.EXAMINATION: {"conducting_body", "exam_name", "exam_date", "official_notice_url"},
    NoticeCategory.EDUCATION_NOTICE: {"institution", "notice_subject", "affected_students", "official_notice_url"},
    NoticeCategory.UNIVERSITY_NOTICE: {"institution", "notice_subject", "affected_students", "official_notice_url"},
    NoticeCategory.GOVERNMENT_ANNOUNCEMENT: {"issuing_department", "announcement_subject", "affected_people", "official_notice_url"},
    NoticeCategory.GOVERNMENT_SERVICE: {"service_name", "department", "eligibility", "official_information_url"},
    NoticeCategory.DOCUMENT_UPDATE: {"document_name", "issuing_department", "change_summary", "official_notice_url"},
}


CRITICAL_NAME_PARTS = ("date", "deadline", "vacanc", "amount", "salary", "age", "fee", "limit", "url")


def is_critical(field_name: str) -> bool:
    return any(part in field_name for part in CRITICAL_NAME_PARTS)
