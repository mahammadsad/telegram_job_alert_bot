from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from processing.models import DiscoveredItem, NoticeCategory
from sources.base import BaseSource, source_url_is_allowed


class HTMLSource(BaseSource):
    """Configuration-driven parser; it refuses to guess site selectors."""

    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        if not all((self.config.item_selector, self.config.title_selector, self.config.link_selector)):
            raise ValueError(f"{self.config.name} has no verified HTML selectors")
        soup = BeautifulSoup(content, "lxml")
        categories = [NoticeCategory(value) for value in self.config.categories]
        results: list[DiscoveredItem] = []
        for node in soup.select(self.config.item_selector):
            title_node = node.select_one(self.config.title_selector)
            link_node = node.select_one(self.config.link_selector)
            if not title_node or not link_node or not link_node.get("href"):
                continue
            link = urljoin(base_url, link_node["href"])
            if not source_url_is_allowed(link, self.config.allowed_domains):
                continue
            results.append(
                DiscoveredItem(
                    title=title_node.get_text(" ", strip=True),
                    discovery_url=link,
                    source_name=self.config.name,
                    source_domain=urlparse(link).hostname or "",
                    category_hints=categories,
                    summary=node.get_text("\n", strip=True),
                    candidate_official_links=[link] if self.config.official else [],
                    official=self.config.official,
                    discovery_only=self.config.discovery_only,
                )
            )
        return results
