from __future__ import annotations

from datetime import date, datetime

from dateutil import parser as date_parser

from processing.models import DeadlineState, NoticeCategory, NoticeSubtype, PublicationPriority
from processing.validators import normalize_digits


BENGALI_MONTHS = {
    "জানুয়ারি": "January", "ফেব্রুয়ারি": "February", "মার্চ": "March",
    "এপ্রিল": "April", "মে": "May", "জুন": "June", "জুলাই": "July",
    "আগস্ট": "August", "সেপ্টেম্বর": "September", "অক্টোবর": "October",
    "নভেম্বর": "November", "ডিসেম্বর": "December",
}


def parse_notice_date(value: object | None) -> date | None:
    if value is None:
        return None
    text = normalize_digits(str(value)).strip()
    for bn, en in BENGALI_MONTHS.items():
        text = text.replace(bn, en)
    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return parsed.date()


def deadline_state(value: object | None, *, today: date | None = None, cancelled: bool = False) -> DeadlineState:
    if cancelled:
        return DeadlineState.CANCELLED
    deadline = parse_notice_date(value)
    if deadline is None:
        return DeadlineState.UNKNOWN
    delta = (deadline - (today or datetime.now().date())).days
    if delta < 0:
        return DeadlineState.EXPIRED
    if delta <= 3:
        return DeadlineState.CLOSING_SOON
    return DeadlineState.OPEN


def assign_publication_priority(
    subtype: NoticeSubtype, state: DeadlineState, category: NoticeCategory | None = None
) -> PublicationPriority:
    if subtype in {NoticeSubtype.CANCELLED, NoticeSubtype.CORRIGENDUM, NoticeSubtype.DEADLINE_EXTENDED}:
        return PublicationPriority.URGENT
    if state == DeadlineState.EXPIRED:
        return PublicationPriority.REJECT
    if state == DeadlineState.CLOSING_SOON:
        return PublicationPriority.HIGH
    if category in {NoticeCategory.EDUCATION_NOTICE, NoticeCategory.UNIVERSITY_NOTICE}:
        return PublicationPriority.DIGEST_ONLY
    return PublicationPriority.NORMAL


def new_expired_notice_is_publishable(
    subtype: NoticeSubtype, state: DeadlineState, category: NoticeCategory | None = None
) -> bool:
    if state != DeadlineState.EXPIRED:
        return True
    return category in {NoticeCategory.RESULT, NoticeCategory.GOVERNMENT_ANNOUNCEMENT} or subtype in {
        NoticeSubtype.CANCELLED, NoticeSubtype.CORRIGENDUM,
        NoticeSubtype.RESULT_PUBLISHED,
    }
