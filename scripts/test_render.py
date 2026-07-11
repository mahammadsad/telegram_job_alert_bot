#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from processing.models import EvidenceValue, ExtractedNotice, NoticeCategory  # noqa: E402
from processing.schemas import CATEGORY_FIELDS  # noqa: E402
from rendering.renderer import generate_notice_card  # noqa: E402


TITLES = {
    NoticeCategory.JOB: "পশ্চিমবঙ্গ সরকারি দপ্তরে ক্লার্ক নিয়োগ বিজ্ঞপ্তি",
    NoticeCategory.WELFARE_SCHEME: "নতুন জনকল্যাণ প্রকল্পে আবেদন সংক্রান্ত বিজ্ঞপ্তি",
    NoticeCategory.SCHOLARSHIP: "ছাত্রছাত্রীদের স্কলারশিপ আবেদন শুরু",
    NoticeCategory.ADMISSION: "স্নাতক কোর্সে অনলাইন ভর্তি বিজ্ঞপ্তি",
    NoticeCategory.RESULT: "পরীক্ষার ফলাফল প্রকাশিত হয়েছে",
    NoticeCategory.EXAMINATION: "পরীক্ষার সময়সূচি ও প্রার্থীদের নির্দেশিকা",
    NoticeCategory.EDUCATION_NOTICE: "শিক্ষার্থীদের জন্য গুরুত্বপূর্ণ শিক্ষা নোটিশ",
    NoticeCategory.UNIVERSITY_NOTICE: "বিশ্ববিদ্যালয়ের সেমেস্টার সংক্রান্ত জরুরি নোটিশ",
    NoticeCategory.GOVERNMENT_ANNOUNCEMENT: "জনসাধারণের জন্য গুরুত্বপূর্ণ সরকারি ঘোষণা",
}


def sample(category: NoticeCategory) -> ExtractedNotice:
    fields = {
        name: EvidenceValue(
            value=("https://wb.gov.in/notice.pdf" if name.endswith("_url") else "যাচাইকৃত নমুনা তথ্য"),
            evidence="যাচাইকৃত নমুনা তথ্য",
            evidence_page=1,
            source_url="https://wb.gov.in/notice.pdf",
        )
        for name in CATEGORY_FIELDS[category]
    }
    return ExtractedNotice(
        category=category,
        title_bn=TITLES[category],
        issuing_authority=EvidenceValue(value="পশ্চিমবঙ্গ সরকার", evidence="পশ্চিমবঙ্গ সরকার", evidence_page=1),
        fields=fields,
        eligibility_scope="WEST_BENGAL" if category == NoticeCategory.JOB else None,
    )


def main() -> None:
    output = ROOT / "render_samples"
    output.mkdir(exist_ok=True)
    for category in NoticeCategory:
        image = generate_notice_card(sample(category), category)
        path = output / f"{category.value.lower()}.png"
        path.write_bytes(image)
        print(path)


if __name__ == "__main__":
    main()
