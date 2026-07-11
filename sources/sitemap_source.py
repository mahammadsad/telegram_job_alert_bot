from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from processing.models import DiscoveredItem, NoticeCategory
from sources.base import BaseSource, source_url_is_allowed


class SitemapSource(BaseSource):
    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        soup = BeautifulSoup(content, "xml")
        categories = [NoticeCategory(value) for value in self.config.categories]
        results = []
        for location in soup.find_all("loc"):
            url = location.get_text(strip=True)
            if not source_url_is_allowed(url, self.config.allowed_domains):
                continue
            results.append(DiscoveredItem(
                title=urlparse(url).path.rsplit("/", 1)[-1].replace("-", " ") or self.config.name,
                discovery_url=url, source_name=self.config.name, source_domain=urlparse(url).hostname or "",
                category_hints=categories, candidate_official_links=[url] if self.config.official else [],
                official=self.config.official, discovery_only=self.config.discovery_only,
            ))
        return results
