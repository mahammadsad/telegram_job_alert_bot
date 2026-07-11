from __future__ import annotations

import re
from dataclasses import dataclass

from processing.models import EligibilityScope, ExtractedNotice, RelevanceLevel
from processing.validators import normalize_digits


WB_NAMES = ("west bengal", "পশ্চিমবঙ্গ")
ALL_INDIA_PATTERNS = (
    r"candidates?\s+from\s+all\s+(?:states|over\s+india)",
    r"all\s+india\s+(?:basis|candidates?)",
    r"open\s+to\s+candidates?\s+from\s+all\s+states",
    r"সকল\s+রাজ্যের\s+প্রার্থী",
)
DOMICILE_PATTERNS = (
    r"domicile\s+(?:certificate\s+)?(?:of|from|required)\s+([a-z ]{3,30})",
    r"resident\s+of\s+([a-z ]{3,30})\s+(?:only|required)",
)
LANGUAGE_NAMES = ("Bengali", "Hindi", "English", "Odia", "Assamese", "Marathi", "Tamil", "Telugu")
INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa",
    "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal", "delhi", "jammu and kashmir",
    "ladakh", "puducherry", "chandigarh",
}


@dataclass(frozen=True)
class EligibilityDecision:
    scope: EligibilityScope
    relevance: RelevanceLevel
    reason: str
    auto_publish: bool
    review: bool = False


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def evaluate_eligibility(notice: ExtractedNotice, official_text: str) -> EligibilityDecision:
    """Derive geography only from explicit official-notice wording.

    "Indian citizen" deliberately does not prove nationwide eligibility.
    Existing structured values are accepted only when their evidence is present in
    the official text; otherwise the deterministic result is unclear.
    """
    text = normalize_digits(official_text)
    lowered = text.lower()
    scope = notice.eligibility_scope
    evidence = (notice.eligibility_reason or "").strip()
    evidence_present = bool(evidence and evidence.lower() in lowered)

    domicile_state: str | None = None
    for pattern in DOMICILE_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            candidate = " ".join(match.group(1).split()).strip(" .,:;-").lower()
            exact = next((state for state in INDIAN_STATES if candidate.startswith(state)), None)
            if exact:
                domicile_state = exact.title()
                break
    if notice.domicile_required and notice.domicile_state:
        domicile_state = notice.domicile_state

    wb_context = any(name in lowered for name in WB_NAMES)
    all_india = _has(text, ALL_INDIA_PATTERNS)
    other_domicile = bool(domicile_state and "west bengal" not in domicile_state.lower())

    if other_domicile:
        decision = EligibilityDecision(
            EligibilityScope.OTHER_STATE_DOMICILE_REQUIRED,
            RelevanceLevel.REJECT,
            f"Official notice requires {domicile_state} domicile",
            False,
        )
    elif scope == EligibilityScope.NOT_RELEVANT_TO_WEST_BENGAL:
        decision = EligibilityDecision(scope, RelevanceLevel.REJECT, evidence or "Not relevant to West Bengal", False)
    elif all_india:
        decision = EligibilityDecision(
            EligibilityScope.ALL_INDIA, RelevanceLevel.HIGH,
            "Official notice explicitly permits candidates from all states", True,
        )
    elif scope == EligibilityScope.OTHER_STATE_OPEN_TO_ALL and evidence_present:
        decision = EligibilityDecision(scope, RelevanceLevel.MEDIUM, evidence, True)
    elif wb_context and (scope in {EligibilityScope.WEST_BENGAL_ONLY, EligibilityScope.WEST_BENGAL} or evidence_present):
        decision = EligibilityDecision(EligibilityScope.WEST_BENGAL_ONLY, RelevanceLevel.HIGH, evidence or "West Bengal notice", True)
    elif scope == EligibilityScope.LOCAL_LANGUAGE_REQUIRED and evidence_present:
        decision = EligibilityDecision(scope, RelevanceLevel.MEDIUM, evidence, True)
    elif scope in {EligibilityScope.INSTITUTION_SPECIFIC, EligibilityScope.DISTRICT_SPECIFIC}:
        decision = EligibilityDecision(scope, RelevanceLevel.MEDIUM, evidence or "Scope needs confirmation", False, True)
    elif scope in {EligibilityScope.OTHER_STATE_DOMICILE_REQUIRED, EligibilityScope.OTHER_STATE_ONLY}:
        decision = EligibilityDecision(EligibilityScope.OTHER_STATE_DOMICILE_REQUIRED, RelevanceLevel.REJECT, evidence or "Other-state domicile required", False)
    else:
        decision = EligibilityDecision(
            EligibilityScope.ELIGIBILITY_UNCLEAR, RelevanceLevel.LOW,
            "Official notice does not clearly establish West Bengal eligibility", False, True,
        )

    notice.eligibility_scope = decision.scope
    notice.west_bengal_relevance = decision.relevance
    notice.relevance_reason = decision.reason
    notice.eligibility_reason = decision.reason
    notice.application_scope = decision.scope.value
    if not notice.work_location:
        if decision.scope == EligibilityScope.WEST_BENGAL_ONLY:
            notice.work_location = "West Bengal"
        elif decision.scope == EligibilityScope.ALL_INDIA:
            notice.work_location = "All India"
    if domicile_state:
        notice.domicile_required = True
        notice.domicile_state = domicile_state
    return decision


def detect_language_requirement(notice: ExtractedNotice, official_text: str) -> None:
    for language in LANGUAGE_NAMES:
        match = re.search(
            rf"(?:knowledge|proficiency|ability)\s+(?:in|to\s+read.*)\s+{language}|{language}\s+language\s+(?:is\s+)?(?:required|mandatory)",
            official_text,
            re.I,
        )
        if match:
            notice.local_language_required = True
            notice.required_language = language
            if notice.eligibility_scope in {EligibilityScope.ALL_INDIA, EligibilityScope.OTHER_STATE_OPEN_TO_ALL}:
                # The geography stays publishable; Telegram prominently displays the condition.
                return
