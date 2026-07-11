from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from dateutil import parser as date_parser

from processing.models import EligibilityScope, ExtractedNotice, NoticeCategory
from processing.schemas import REQUIRED_FIELDS, is_critical
from processing.verifier import validate_official_url


@dataclass
class ValidationResult:
    valid: bool
    score: int
    errors: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[^\w\u0980-\u09ff₹%]+", " ", normalized).strip()


def evidence_supported(evidence: str | None, source_text: str) -> bool:
    if not evidence:
        return False
    needle, haystack = normalize_text(evidence), normalize_text(source_text)
    if not needle:
        return False
    if needle in haystack:
        return True
    windows = [haystack[i : i + len(needle) + 30] for i in range(0, len(haystack), max(20, len(needle) // 2))]
    return any(SequenceMatcher(None, needle, window).ratio() >= 0.82 for window in windows)


def value_supported(value: object, source_text: str) -> bool:
    if value is None:
        return True
    values = value if isinstance(value, list) else [value]
    normalized_source = normalize_text(source_text)
    for item in values:
        candidate = normalize_text(str(item))
        if candidate and candidate not in normalized_source:
            numbers = re.findall(r"\d+(?:[.,]\d+)?", candidate)
            if numbers and not all(number.replace(",", "") in normalized_source.replace(",", "") for number in numbers):
                return False
    return True


def valid_date(value: str) -> bool:
    try:
        date_parser.parse(value, fuzzy=True, dayfirst=True)
        return bool(re.search(r"\d", value))
    except (ValueError, OverflowError):
        return False


def valid_currency(value: str) -> bool:
    return bool(re.search(r"(?:₹|rs\.?|inr|টাকা)\s*[\d,]+", value, re.I))


def valid_vacancy(value: str | int) -> bool:
    match = re.search(r"\d[\d,]*", str(value))
    return bool(match and int(match.group().replace(",", "")) >= 0)


def valid_percentage(value: str) -> bool:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", value)
    return bool(matches) and all(0 <= float(number) <= 100 for number in matches)


def valid_age_limit(value: str) -> bool:
    ages = [int(number) for number in re.findall(r"\b\d{1,3}\b", value)]
    return bool(ages) and all(0 <= age <= 100 for age in ages)


def valid_notice_number(value: str) -> bool:
    return bool(re.fullmatch(r"[\w./()\- ]{2,80}", value.strip(), re.UNICODE))


def detect_date_conflict(source_text: str, field_name: str, value: str) -> bool:
    if "date" not in field_name and "deadline" not in field_name:
        return False
    # Multiple dates in a notice are normal. Only compare dates attached to
    # the same semantic label (deadline/last date) within a short context.
    contexts = re.findall(
        r"(?:deadline|last\s+date|closing\s+date|শেষ\s+তারিখ|অন্তিম\s+তারিখ)[^\n]{0,80}",
        source_text,
        re.I,
    )
    labelled_dates = {
        match
        for context in contexts
        for match in re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", context)
    }
    return "deadline" in field_name and len(labelled_dates) > 1


def validate_extraction(
    notice: ExtractedNotice,
    source_text: str,
    trusted_domains: set[str],
    page_text: dict[int, str] | None = None,
) -> ValidationResult:
    errors: list[str] = []
    conflicts: list[str] = []
    score = 70  # trusted domain + downloaded official notice + issuing authority
    required = REQUIRED_FIELDS[notice.category]
    missing = sorted(name for name in required if name not in notice.fields or notice.fields[name].value is None)
    if notice.issuing_authority.value is None:
        missing.append("issuing_authority")
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    for name in ("issuing_authority", "notice_number", "notice_date"):
        field = getattr(notice, name)
        if field.value is None:
            continue
        evidence_source = source_text
        if field.evidence_page is not None and page_text is not None:
            evidence_source = page_text.get(field.evidence_page, "")
            if not evidence_source:
                errors.append(f"invalid evidence page: {name}")
                continue
        if not evidence_supported(field.evidence, evidence_source):
            errors.append(f"unsupported evidence: {name}")
        if name == "notice_date" and not valid_date(str(field.value)):
            errors.append("invalid date: notice_date")
        if name == "notice_number" and not valid_notice_number(str(field.value)):
            errors.append("invalid notice number")
    verified_critical = 0
    for name, field in notice.fields.items():
        if field.value is None:
            continue
        evidence_source = source_text
        if field.evidence_page is not None and page_text is not None:
            evidence_source = page_text.get(field.evidence_page, "")
            if not evidence_source:
                errors.append(f"invalid evidence page: {name}")
                continue
        if not evidence_supported(field.evidence, evidence_source):
            errors.append(f"unsupported evidence: {name}")
        if is_critical(name):
            if not value_supported(field.value, source_text):
                errors.append(f"unsupported value: {name}")
            else:
                verified_critical += 1
        if name.endswith("_url") and not validate_official_url(str(field.value), trusted_domains):
            errors.append(f"untrusted URL: {name}")
        if ("date" in name or name == "deadline") and not valid_date(str(field.value)):
            errors.append(f"invalid date: {name}")
        if "vacanc" in name and not valid_vacancy(field.value):
            errors.append(f"invalid vacancy count: {name}")
        if "age" in name and not valid_age_limit(str(field.value)):
            errors.append(f"invalid age limit: {name}")
        if "%" in str(field.value) and not valid_percentage(str(field.value)):
            errors.append(f"invalid percentage: {name}")
        if detect_date_conflict(source_text, name, str(field.value)):
            conflicts.append(f"conflicting date: {name}")
    if notice.category == NoticeCategory.JOB and notice.eligibility_scope not in {
        EligibilityScope.ALL_INDIA,
        EligibilityScope.WEST_BENGAL,
    }:
        errors.append(f"job eligibility is {notice.eligibility_scope or 'UNCLEAR'}")
    if verified_critical:
        score += 15
    if conflicts:
        score -= 50
    score = max(0, min(100, score))
    return ValidationResult(not errors and not conflicts and score >= 80, score, errors, conflicts)
