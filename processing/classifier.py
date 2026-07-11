from __future__ import annotations

from processing.models import NoticeCategory


KEYWORDS: dict[NoticeCategory, tuple[str, ...]] = {
    NoticeCategory.RESULT: ("result", "ফলাফল"),
    NoticeCategory.EXAMINATION: ("exam", "admit card", "routine", "পরীক্ষা"),
    NoticeCategory.ADMISSION: ("admission", "counselling", "ভর্তি"),
    NoticeCategory.SCHOLARSHIP: ("scholarship", "স্কলারশিপ"),
    NoticeCategory.WELFARE_SCHEME: ("scheme", "benefit", "প্রকল্প"),
    NoticeCategory.UNIVERSITY_NOTICE: ("university", "বিশ্ববিদ্যাল"),
    NoticeCategory.EDUCATION_NOTICE: ("education", "student", "শিক্ষা"),
    NoticeCategory.JOB: ("recruitment", "vacancy", "post", "চাকরি"),
}


def classify(title: str, text: str = "", hints: list[NoticeCategory] | None = None) -> NoticeCategory:
    haystack = f"{title} {text[:2000]}".lower()
    for category, words in KEYWORDS.items():
        if any(word in haystack for word in words):
            return category
    if hints:
        return hints[0]
    return NoticeCategory.GOVERNMENT_ANNOUNCEMENT

