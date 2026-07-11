from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from config.loader import load_yaml
from processing.models import ExtractedNotice, NoticeCategory, NoticeSubtype


FIELD_LABELS = {
    "department": "বিভাগ", "post_name": "পদের নাম", "total_vacancies": "মোট শূন্যপদ",
    "qualifications": "যোগ্যতা", "age_limit": "বয়সসীমা", "salary": "বেতন",
    "deadline": "শেষ তারিখ", "application_start": "আবেদন শুরু", "application_fee": "আবেদন ফি",
    "apply_mode": "আবেদন পদ্ধতি", "selection_process": "নির্বাচন পদ্ধতি",
    "scheme_name": "প্রকল্পের নাম", "benefit": "সুবিধা", "eligibility": "যোগ্যতা",
    "age_requirement": "বয়সের শর্ত", "income_limit": "আয়ের সীমা",
    "required_documents": "প্রয়োজনীয় নথি", "application_method": "আবেদন পদ্ধতি",
    "beneficiary_group": "উপভোক্তা", "scholarship_name": "স্কলারশিপ",
    "provider": "প্রদানকারী", "benefit_amount": "সহায়তার পরিমাণ",
    "educational_eligibility": "শিক্ষাগত যোগ্যতা", "institution": "প্রতিষ্ঠান",
    "renewal_or_fresh": "নতুন/নবীকরণ",
    "course_or_program": "কোর্স", "academic_session": "শিক্ষাবর্ষ",
    "course": "কোর্স", "semester_or_year": "সেমেস্টার/বর্ষ",
    "board_or_university": "বোর্ড/বিশ্ববিদ্যালয়", "exam_name": "পরীক্ষা",
    "result_date": "ফল প্রকাশ", "credentials_required": "যা প্রয়োজন",
    "rechecking_or_review_information": "পুনর্মূল্যায়ন/রিভিউ",
    "conducting_body": "পরিচালনাকারী সংস্থা", "exam_date": "পরীক্ষার তারিখ",
    "exam_time": "সময়", "admit_card_date": "অ্যাডমিট কার্ড",
    "exam_mode": "পরীক্ষার মাধ্যম", "exam_centres": "পরীক্ষাকেন্দ্র",
    "candidate_instructions": "প্রার্থীদের নির্দেশিকা",
    "notice_subject": "নোটিশের বিষয়", "affected_students": "যাঁদের জন্য",
    "important_date": "গুরুত্বপূর্ণ তারিখ", "action_required": "করণীয়",
    "submission_portal_or_office": "জমা দেওয়ার স্থান/পোর্টাল",
    "counselling_information": "কাউন্সেলিং তথ্য",
    "issuing_department": "প্রকাশকারী বিভাগ", "announcement_subject": "ঘোষণার বিষয়",
    "affected_people": "যাঁদের জন্য", "effective_date": "কার্যকর হওয়ার তারিখ",
    "service_or_portal": "পরিষেবা/পোর্টাল",
    "service_name": "পরিষেবার নাম", "service_location": "প্রযোজ্য স্থান",
    "document_name": "নথির নাম", "change_summary": "কী পরিবর্তন হয়েছে",
}
ICONS = ["🏛️", "📌", "📅", "✅", "📝"]
URL_FIELDS = {
    "official_notification_url", "official_application_url", "official_information_url",
    "official_result_url", "official_notice_url", "official_routine_url",
}
NON_REPEATED_FIELDS = URL_FIELDS | {"action_required", "deadline"}


def _escape(value: object) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return html.escape(str(value), quote=False)


def _display(value: object, limit: int = 240) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)
    clean = " ".join(text.split())
    if len(clean) > limit:
        shortened = clean[: limit + 1].rsplit(" ", 1)[0] or clean[:limit]
        clean = shortened.rstrip("।,;:- ") + "…"
    return html.escape(clean, quote=False)


def public_fields(extracted: ExtractedNotice, limit: int | None = None) -> list[tuple[str, object]]:
    values = [
        (name, field.value)
        for name, field in extracted.fields.items()
        if field.value is not None and name not in NON_REPEATED_FIELDS
    ]
    return values[:limit] if limit else values


def format_telegram_message(extracted: ExtractedNotice, checked_at: datetime | None = None) -> str:
    config = load_yaml("categories.yaml")["categories"][extracted.category.value]
    checked_at = checked_at or datetime.now(ZoneInfo("Asia/Kolkata"))
    lines = [
        f"{category_icon(extracted.category)} <b>{_escape(config['label'])}</b>",
    ]
    if extracted.subtype != NoticeSubtype.NEW:
        lines.append(f"🔔 <b>{_escape(subtype_label(extracted.subtype))}</b>")
    lines.extend(["", f"<b>{_display(extracted.title_bn, 300)}</b>", ""])
    for index, (name, value) in enumerate(public_fields(extracted)):
        label = FIELD_LABELS.get(name, name.replace("_", " ").title())
        lines.append(f"{ICONS[index % len(ICONS)]} <b>{_escape(label)}:</b> {_display(value)}")
    scope_labels = {
        "WEST_BENGAL_ONLY": "শুধু পশ্চিমবঙ্গ", "WEST_BENGAL": "পশ্চিমবঙ্গ",
        "ALL_INDIA": "সর্বভারতীয়", "OTHER_STATE_OPEN_TO_ALL": "অন্য রাজ্য—সবার জন্য উন্মুক্ত",
        "LOCAL_LANGUAGE_REQUIRED": "ভাষার শর্তসহ আবেদনযোগ্য",
        "DISTRICT_SPECIFIC": "নির্দিষ্ট জেলা", "INSTITUTION_SPECIFIC": "নির্দিষ্ট প্রতিষ্ঠান",
        "ELIGIBILITY_UNCLEAR": "যোগ্যতা অস্পষ্ট", "UNCLEAR": "যোগ্যতা অস্পষ্ট",
    }
    if extracted.eligibility_scope:
        lines.append(
            f"🌍 <b>আবেদনযোগ্যতা:</b> {_escape(scope_labels.get(extracted.eligibility_scope.value, extracted.eligibility_scope.value))}"
        )
    domicile = "প্রয়োজন" if extracted.domicile_required else "প্রয়োজন নেই" if extracted.domicile_required is False else "উল্লেখ নেই"
    if extracted.domicile_state:
        domicile += f" ({extracted.domicile_state})"
    lines.append(f"🏠 <b>ডোমিসাইল:</b> {_escape(domicile)}")
    if extracted.local_language_required:
        lines.append(f"🗣️ <b>ভাষার শর্ত:</b> {_escape(extracted.required_language or 'অফিসিয়াল বিজ্ঞপ্তি দেখুন')}")
    if extracted.work_location:
        lines.append(f"📍 <b>প্রযোজ্য স্থান:</b> {_display(extracted.work_location)}")
    deadline = extracted.fields.get("deadline")
    deadline_text = deadline.value if deadline and deadline.value else "প্রযোজ্য নয় / অফিসিয়াল নোটিশ দেখুন"
    lines.append(f"📅 <b>শেষ তারিখ:</b> {_display(deadline_text)}")
    action = extracted.fields.get("action_required")
    if action and action.value:
        lines.extend(["", f"👉 <b>করণীয়:</b> {_display(action.value, 350)}"])
    links = official_links(extracted)
    if links:
        lines.extend(["", "🔗 <b>অফিসিয়াল লিঙ্ক:</b>"])
        for label, url in links:
            lines.append(f'• <a href="{html.escape(url, quote=True)}">{_escape(label)}</a>')
    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━",
            "🛡️ তথ্যের অবস্থা: অফিসিয়াল উৎস থেকে যাচাইকৃত",
            f"🗓️ সর্বশেষ যাচাই: {checked_at.strftime('%d-%m-%Y %I:%M %p')}",
            "⚠️ আবেদন বা পদক্ষেপ নেওয়ার আগে অফিসিয়াল বিজ্ঞপ্তি পড়ুন।",
            "",
            " ".join(config["hashtags"][:4]),
        ]
    )
    return "\n".join(lines)


def official_links(extracted: ExtractedNotice) -> list[tuple[str, str]]:
    labels = {
        "official_notification_url": "অফিসিয়াল বিজ্ঞপ্তি",
        "official_application_url": "অনলাইনে আবেদন",
        "official_information_url": "অফিসিয়াল তথ্য",
        "official_result_url": "রেজাল্ট দেখুন",
        "official_notice_url": "অফিসিয়াল নোটিশ",
        "official_routine_url": "অফিসিয়াল রুটিন",
    }
    return [
        (labels[name], str(extracted.fields[name].value))
        for name in labels
        if name in extracted.fields and extracted.fields[name].value
    ]


def category_icon(category: NoticeCategory) -> str:
    return {
        NoticeCategory.JOB: "💼", NoticeCategory.WELFARE_SCHEME: "🤝",
        NoticeCategory.SCHOLARSHIP: "🎓", NoticeCategory.ADMISSION: "🏫",
        NoticeCategory.RESULT: "📋", NoticeCategory.EXAMINATION: "🗓️",
        NoticeCategory.EDUCATION_NOTICE: "📚", NoticeCategory.UNIVERSITY_NOTICE: "🏛️",
        NoticeCategory.GOVERNMENT_ANNOUNCEMENT: "📢",
        NoticeCategory.GOVERNMENT_SERVICE: "🏢", NoticeCategory.DOCUMENT_UPDATE: "📄",
    }[category]


def subtype_label(subtype: NoticeSubtype) -> str:
    return {
        NoticeSubtype.NEW: "নতুন বিজ্ঞপ্তি",
        NoticeSubtype.UPDATED: "আপডেটেড বিজ্ঞপ্তি",
        NoticeSubtype.CORRIGENDUM: "সংশোধনী বিজ্ঞপ্তি",
        NoticeSubtype.CANCELLED: "বাতিল বিজ্ঞপ্তি",
        NoticeSubtype.DEADLINE_EXTENDED: "আবেদনের সময়সীমা বৃদ্ধি",
        NoticeSubtype.DEADLINE_REMINDER: "শেষ তারিখের স্মরণিকা",
        NoticeSubtype.RESULT_PUBLISHED: "ফলাফল প্রকাশিত",
        NoticeSubtype.ADMIT_CARD_RELEASED: "অ্যাডমিট কার্ড প্রকাশিত",
    }[subtype]
