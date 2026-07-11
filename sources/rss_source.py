from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from processing.models import DiscoveredItem, NoticeCategory
from sources.base import BaseSource, source_url_is_allowed


class RSSSource(BaseSource):
    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        soup = BeautifulSoup(content, "xml")
        results: list[DiscoveredItem] = []
        categories = [NoticeCategory(value) for value in self.config.categories]
        for item in soup.find_all("item"):
            title_node, link_node = item.find("title"), item.find("link")
            if not title_node or not link_node:
                continue
            description = item.find("content:encoded") or item.find("description")
            body_html = description.text if description else ""
            body = BeautifulSoup(body_html, "html.parser")
            discovery_url = urljoin(base_url, link_node.get_text(strip=True))
            if not source_url_is_allowed(discovery_url, self.config.allowed_domains):
                continue
            candidate_links: list[str] = []
            for anchor in body.find_all("a", href=True):
                href = urljoin(base_url, anchor["href"].strip())
                parsed = urlparse(href)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if any(
                    parsed.hostname == domain or (parsed.hostname or "").endswith("." + domain)
                    for domain in self.config.allowed_domains
                ):
                    continue
                if self.config.allowed_document_domains and not any(
                    parsed.hostname == domain or (parsed.hostname or "").endswith("." + domain)
                    for domain in self.config.allowed_document_domains
                ):
                    continue
                candidate_links.append(href)
            results.append(
                DiscoveredItem(
                    title=title_node.get_text(strip=True),
                    discovery_url=discovery_url,
                    source_name=self.config.name,
                    source_domain=urlparse(base_url).hostname or "",
                    category_hints=categories,
                    summary=body.get_text("\n", strip=True)[:10000],
                    candidate_official_links=list(dict.fromkeys(candidate_links))[:10],
                    official=self.config.official,
                    discovery_only=self.config.discovery_only,
                )
            )
        return results
