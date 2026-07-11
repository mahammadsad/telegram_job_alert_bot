from __future__ import annotations

import re
from dataclasses import dataclass, field

from processing.validators import normalize_digits


@dataclass
class RuleFacts:
    deadline: str | None = None
    vacancy_count: str | None = None
    notice_number: str | None = None
    application_fee: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)


PATTERNS = {
    "deadline": r"(?:last\s+date|closing\s+date|deadline|শেষ\s+তারিখ)\s*[:\-]?\s*([0-9০-৯][^\n;]{3,39})",
    "vacancy_count": r"(?:total\s+vacanc(?:y|ies)|মোট\s+শূন্যপদ)\s*[:\-]?\s*([\d,০-৯]+)",
    "notice_number": r"(?:notice|advertisement)\s+(?:no\.?|number)\s*[:\-]?\s*([\w./()\-]{2,80})",
    "application_fee": r"(?:application\s+fee|আবেদন\s+ফি)\s*[:\-]?\s*((?:₹|rs\.?|inr)?\s*[\d,০-৯]+)",
}


def extract_rule_facts(official_text: str) -> RuleFacts:
    facts = RuleFacts()
    normalized = normalize_digits(official_text)
    for name, pattern in PATTERNS.items():
        match = re.search(pattern, normalized, re.I)
        if match:
            setattr(facts, name, match.group(1).strip())
            facts.evidence[name] = match.group(0).strip()[:500]
    return facts
