from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from dateutil import parser as date_parser

from processing.models import EligibilityScope, ExtractedNotice, NoticeCategory
from processing.schemas import REQUIRED_FIELDS, is_critical
from processing.verifier import validate_official_url
from processing.verifier import canonicalize_url


@dataclass
class ValidationResult:
    valid: bool
    score: int
    errors: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[^\w\u0980-\u09ff₹%]+", " ", normalized).strip()


def normalize_digits(value: str) -> str:
    return value.translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789"))


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
    normalized_source = normalize_digits(normalize_text(source_text))
    for item in values:
        candidate = normalize_digits(normalize_text(str(item)))
        if candidate and candidate not in normalized_source:
            numbers = re.findall(r"\d+(?:[.,]\d+)?", candidate)
            if numbers and not all(number.replace(",", "") in normalized_source.replace(",", "") for number in numbers):
                return False
    return True


def valid_date(value: str) -> bool:
    translated = normalize_digits(value)
    bengali_months = {
        "জানুয়ারি": "January", "ফেব্রুয়ারি": "February", "মার্চ": "March",
        "এপ্রিল": "April", "মে": "May", "জুন": "June", "জুলাই": "July",
        "আগস্ট": "August", "সেপ্টেম্বর": "September", "অক্টোবর": "October",
        "নভেম্বর": "November", "ডিসেম্বর": "December",
    }
    for bengali, english in bengali_months.items():
        translated = translated.replace(bengali, english)
    try:
        date_parser.parse(translated, fuzzy=True, dayfirst=True)
        numbers = re.findall(r"\d+", translated)
        has_named_month = bool(
            re.search(
                r"january|february|march|april|may|june|july|august|september|october|november|december",
                translated,
                re.I,
            )
        )
        return len(numbers) >= 2 or (has_named_month and bool(numbers))
    except (ValueError, OverflowError):
        return False


def valid_currency(value: str) -> bool:
    normalized = normalize_digits(value)
    return bool(
        re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+", normalized, re.I)
        or re.search(r"[\d,]+(?:\.\d+)?\s*(?:টাকা|rupees?)", normalized, re.I)
    )


def valid_vacancy(value: str | int) -> bool:
    match = re.search(r"\d[\d,]*", normalize_digits(str(value)))
    return bool(match and int(match.group().replace(",", "")) >= 0)


def valid_percentage(value: str) -> bool:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", normalize_digits(value))
    return bool(matches) and all(0 <= float(number) <= 100 for number in matches)


def valid_age_limit(value: str) -> bool:
    ages = [int(number) for number in re.findall(r"\b\d{1,3}\b", normalize_digits(value))]
    return bool(ages) and all(0 <= age <= 100 for age in ages)


def valid_notice_number(value: str) -> bool:
    return bool(re.fullmatch(r"[\w./()\- ]{2,80}", value.strip(), re.UNICODE))


def detect_date_conflict(source_text: str, field_name: str) -> bool:
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


CONFLICT_LABELS: dict[str, tuple[str, ...]] = {
    "total_vacancies": ("total vacancies", "total vacancy", "মোট শূন্যপদ", "শূন্যপদের মোট সংখ্যা"),
    "application_fee": ("application fee", "আবেদন ফি"),
    "benefit_amount": ("benefit amount", "scholarship amount", "সহায়তার পরিমাণ", "বৃত্তির পরিমাণ"),
    "income_limit": ("income limit", "আয়ের সীমা"),
}


def detect_numeric_conflict(source_text: str, field_name: str) -> bool:
    """Conservatively flag repeated labelled scalar values that disagree.

    Unlabelled numbers and ordinary ranges are ignored because notices often
    contain category-wise counts, dates, and fee slabs that are not conflicts.
    """
    labels = CONFLICT_LABELS.get(field_name)
    if not labels:
        return False
    normalized = normalize_digits(source_text)
    values: set[str] = set()
    for label in labels:
        pattern = re.compile(
            rf"{re.escape(label)}\s*(?:is|are|:|-)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",
            re.I,
        )
        values.update(match.replace(",", "") for match in pattern.findall(normalized))
    return len(values) > 1


def url_supported(url: str, source_text: str, official_source_url: str | None = None) -> bool:
    target = canonicalize_url(url)
    if official_source_url and canonicalize_url(official_source_url) == target:
        return True
    for candidate in re.findall(r"https://[^\s<>\]\[\"']+", source_text, re.I):
        try:
            if canonicalize_url(candidate.rstrip(".,);")) == target:
                return True
        except (TypeError, ValueError):
            continue
    return False


def evidence_source_valid(
    source_url: str | None,
    trusted_domains: set[str],
    official_source_url: str | None,
) -> bool:
    if not source_url or not validate_official_url(source_url, trusted_domains):
        return False
    if official_source_url is None:
        return True
    return canonicalize_url(source_url) == canonicalize_url(official_source_url)


def validate_extraction(
    notice: ExtractedNotice,
    source_text: str,
    trusted_domains: set[str],
    page_text: dict[int, str] | None = None,
    official_source_url: str | None = None,
) -> ValidationResult:
    errors: list[str] = []
    conflicts: list[str] = []
    score = 60  # trusted final domain + successfully downloaded official page/PDF
    requires_page = "[PAGE " in source_text
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
        if not evidence_source_valid(field.source_url, trusted_domains, official_source_url):
            errors.append(f"invalid evidence source URL: {name}")
        if requires_page and field.evidence_page is None:
            errors.append(f"missing evidence page: {name}")
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
    if notice.issuing_authority.value is not None:
        score += 5
    if notice.notice_date.value is not None:
        score += 5
    verified_critical = 0
    for name, field in notice.fields.items():
        if field.value is None:
            continue
        direct_source_link = bool(
            name.endswith("_url")
            and official_source_url
            and canonicalize_url(str(field.value)) == canonicalize_url(official_source_url)
        )
        if not evidence_source_valid(field.source_url, trusted_domains, official_source_url):
            errors.append(f"invalid evidence source URL: {name}")
        if requires_page and field.evidence_page is None and not direct_source_link:
            errors.append(f"missing evidence page: {name}")
        evidence_source = source_text
        if field.evidence_page is not None and page_text is not None:
            evidence_source = page_text.get(field.evidence_page, "")
            if not evidence_source:
                errors.append(f"invalid evidence page: {name}")
                continue
        if not direct_source_link and not evidence_supported(field.evidence, evidence_source):
            errors.append(f"unsupported evidence: {name}")
        if is_critical(name):
            if not value_supported(field.value, source_text):
                errors.append(f"unsupported value: {name}")
            else:
                verified_critical += 1
        if name.endswith("_url") and not validate_official_url(str(field.value), trusted_domains):
            errors.append(f"untrusted URL: {name}")
        if name.endswith("_url") and not url_supported(
            str(field.value), source_text, official_source_url
        ):
            errors.append(f"official URL is not present in source: {name}")
        if ("date" in name or name == "deadline") and not valid_date(str(field.value)):
            errors.append(f"invalid date: {name}")
        if "vacanc" in name and not valid_vacancy(field.value):
            errors.append(f"invalid vacancy count: {name}")
        if "age" in name and not valid_age_limit(str(field.value)):
            errors.append(f"invalid age limit: {name}")
        if any(part in name for part in ("amount", "salary", "fee", "income_limit")):
            if re.search(r"[₹\d০-৯]|(?:rs\.?|inr|টাকা|rupees?)", str(field.value), re.I) and not valid_currency(str(field.value)):
                errors.append(f"invalid currency amount: {name}")
        if "%" in str(field.value) and not valid_percentage(str(field.value)):
            errors.append(f"invalid percentage: {name}")
        if detect_date_conflict(source_text, name):
            conflicts.append(f"conflicting date: {name}")
        if detect_numeric_conflict(source_text, name):
            conflicts.append(f"conflicting numeric value: {name}")
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
    errors = list(dict.fromkeys(errors))
    conflicts = list(dict.fromkeys(conflicts))
    return ValidationResult(not errors and not conflicts and score >= 80, score, errors, conflicts)
