from __future__ import annotations

import json
import logging
import os
import time

import requests
from pydantic import ValidationError

from database.base import Repository
from processing.models import ExtractedNotice, NoticeCategory
from processing.schemas import CATEGORY_FIELDS


logger = logging.getLogger(__name__)
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def build_prompt(
    title: str,
    source_text: str,
    source_url: str,
    category: NoticeCategory,
    candidate_links: list[str],
) -> str:
    fields = CATEGORY_FIELDS[category]
    return f"""Extract a verified public notice as JSON.
Source title: {title}
Source URL: {source_url}
Controlled category: {category.value}
Candidate official links: {json.dumps(candidate_links, ensure_ascii=False)}
Required field names: {json.dumps(fields)}

SOURCE TEXT (page markers like [PAGE 2] must be respected):
{source_text[:50000]}

Return ONLY valid JSON with exactly this shape:
{{
  "category": "{category.value}",
  "subtype": "NEW|UPDATED|CORRIGENDUM|CANCELLED|DEADLINE_EXTENDED",
  "title_bn": "faithful Bengali title",
  "issuing_authority": {{"value": null, "evidence": null, "evidence_page": null, "source_url": "{source_url}"}},
  "notice_number": {{"value": null, "evidence": null, "evidence_page": null, "source_url": "{source_url}"}},
  "notice_date": {{"value": null, "evidence": null, "evidence_page": null, "source_url": "{source_url}"}},
  "fields": {{ each required field name maps to the same value/evidence/evidence_page/source_url object }},
  "eligibility_scope": null,
  "eligibility_reason": null
}}

Rules:
1. Extract only facts explicitly present in SOURCE TEXT; never infer dates, counts, amounts, fees, eligibility, links, or documents.
2. Use null for absent facts. Never use promotional language.
3. Every non-null critical value must have a short direct evidence excerpt and page number when page markers exist.
4. Preserve raw official URLs. Never call a third-party/aggregator page official.
5. Do not create claims from the headline when full source text is available.
6. For every category, eligibility_scope must use one controlled value: WEST_BENGAL_ONLY,
   ALL_INDIA, OTHER_STATE_OPEN_TO_ALL, OTHER_STATE_DOMICILE_REQUIRED,
   LOCAL_LANGUAGE_REQUIRED, INSTITUTION_SPECIFIC, DISTRICT_SPECIFIC,
   ELIGIBILITY_UNCLEAR, or NOT_RELEVANT_TO_WEST_BENGAL.
7. eligibility_reason must be a short direct excerpt proving the selected scope.
   "Indian citizen" alone never proves ALL_INDIA eligibility.
8. Include all required field names and no invented field names.
"""


class GroqExtractor:
    def __init__(self, repository: Repository, session: requests.Session | None = None):
        self.repository = repository
        self.session = session or requests.Session()
        self.provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
        self.model = os.getenv("AI_TEXT_MODEL", os.getenv("GROQ_TEXT_MODEL", "")).strip() or (
            "test-model" if session is not None else ""
        )
        self.max_retries = int(os.getenv("GROQ_MAX_RETRIES", "3"))
        self.base_delay = float(os.getenv("GROQ_RETRY_BASE_DELAY", "20"))
        self.rate_delay = float(os.getenv("GROQ_RATE_LIMIT_DELAY", "3"))
        self.daily_limit = int(os.getenv("AI_DAILY_CALL_LIMIT", os.getenv("GROQ_DAILY_TEXT_LIMIT", "100")))

    def extract(self, title: str, text: str, source_url: str, category: NoticeCategory, links: list[str]) -> ExtractedNotice:
        key = os.getenv("AI_API_KEY", os.getenv("GROQ_API_KEY", "")).strip()
        if self.provider != "groq":
            raise RuntimeError(f"Unsupported AI_PROVIDER: {self.provider}; use groq or disable AI")
        if not key:
            raise RuntimeError("AI_API_KEY is not configured")
        if not self.model:
            raise RuntimeError("AI_TEXT_MODEL is not configured")
        prompt = build_prompt(title, text, source_url, category, links)
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            if self.repository.get_usage(self.provider, "extract") >= self.daily_limit:
                raise RuntimeError("Groq daily text limit reached")
            self.repository.increment_usage(self.provider, "extract")
            try:
                response = self.session.post(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "Return one valid JSON object. Extract facts only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0,
                        "max_completion_tokens": 4000,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=45,
                )
                if response.status_code == 429:
                    delay = float(response.headers.get("retry-after", self.base_delay * 2 ** (attempt - 1)))
                    logger.warning("groq_rate_limited attempt=%s delay=%s", attempt, delay)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                result = ExtractedNotice.model_validate_json(raw)
                if result.category != category:
                    raise ValueError(f"AI changed controlled category from {category.value} to {result.category.value}")
                expected = set(CATEGORY_FIELDS[category])
                if set(result.fields) != expected:
                    raise ValueError(f"AI fields do not match schema; missing={expected-set(result.fields)}, extra={set(result.fields)-expected}")
                if self.rate_delay:
                    time.sleep(self.rate_delay)
                return result
            except (requests.RequestException, KeyError, IndexError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.error("groq_extraction_failed attempt=%s error=%s", attempt, exc)
                if attempt < self.max_retries:
                    time.sleep(min(10, self.base_delay))
        raise RuntimeError(f"Groq extraction failed: {last_error}")
