from __future__ import annotations

import json
from urllib.parse import urljoin, urlparse

from processing.models import DiscoveredItem, NoticeCategory
from sources.base import BaseSource, source_url_is_allowed


class JSONSource(BaseSource):
    """Configured JSON adapter. Field selectors are explicit keys, never guessed."""

    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        if not self.config.title_selector or not self.config.link_selector:
            raise ValueError(f"{self.config.name} has no verified JSON field selectors")
        payload = json.loads(content)
        rows = payload
        for part in (self.config.json_items_path or "").split("."):
            if part:
                rows = rows[part]
        if not isinstance(rows, list):
            raise ValueError("configured JSON items path is not a list")
        categories = [NoticeCategory(value) for value in self.config.categories]
        results: list[DiscoveredItem] = []
        for row in rows:
            if not isinstance(row, dict) or self.config.title_selector not in row or self.config.link_selector not in row:
                continue
            link = urljoin(base_url, str(row[self.config.link_selector]))
            if not source_url_is_allowed(link, self.config.allowed_domains):
                continue
            results.append(DiscoveredItem(
                title=str(row[self.config.title_selector]), discovery_url=link, source_name=self.config.name,
                source_domain=urlparse(link).hostname or "", category_hints=categories,
                summary=str(row.get(self.config.summary_selector or "", ""))[:10000],
                candidate_official_links=[link] if self.config.official else [],
                official=self.config.official, discovery_only=self.config.discovery_only,
            ))
        return results
