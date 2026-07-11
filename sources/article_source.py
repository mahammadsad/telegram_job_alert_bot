from __future__ import annotations

from urllib.parse import parse_qsl, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from processing.verifier import SHORTENERS, validate_official_url
from sources.base import MAX_SOURCE_REDIRECTS, USER_AGENT, SourceConfig, source_url_is_allowed


PREFERRED_TERMS = (
    "official notification", "advertisement", "recruitment notice", "apply online",
    "result", "admission", "scholarship", "government order", "official notice",
    "অফিসিয়াল", "বিজ্ঞপ্তি", "আবেদন",
)
TRACKING_HOST_PARTS = ("doubleclick", "googlesyndication", "facebook.com", "twitter.com")


class ArticleInspector:
    def __init__(self, config: SourceConfig, trusted_domains: set[str], session: requests.Session | None = None):
        self.config = config
        self.trusted_domains = trusted_domains
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.update({"User-Agent": USER_AGENT})

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=self.config.request_timeout, allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                return False
            if response.status_code >= 400:
                return True
            parser = RobotFileParser(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, url)
        except requests.RequestException:
            return False  # Article inspection is optional, so uncertainty fails closed.

    def _fetch(self, url: str) -> requests.Response:
        current = url
        for _ in range(MAX_SOURCE_REDIRECTS + 1):
            if not source_url_is_allowed(current, self.config.allowed_domains):
                raise ValueError("article redirect left the discovery source")
            response = self.session.get(current, timeout=self.config.request_timeout, allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("article redirect has no Location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            if len(response.content) > self.config.max_response_bytes:
                raise ValueError("aggregator article is oversized")
            if "html" not in response.headers.get("Content-Type", "text/html").lower():
                raise ValueError("aggregator article is not HTML")
            return response
        raise ValueError("article redirect limit exceeded")

    def inspect(self, article_url: str) -> tuple[str, list[str]]:
        if not self.config.article_inspection or not self.config.terms_reviewed:
            return "", []
        if not self._robots_allowed(article_url):
            return "", []
        response = self._fetch(article_url)
        soup = BeautifulSoup(response.content, "lxml")
        for node in soup(["script", "style", "iframe", "form", "noscript"]):
            node.decompose()
        ranked: list[tuple[int, int, str]] = []
        for index, anchor in enumerate(soup.find_all("a", href=True)[:250]):
            href = urljoin(response.url, anchor["href"].strip())
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if host in SHORTENERS or any(part in host for part in TRACKING_HOST_PARTS):
                continue
            if parse_qsl(parsed.query) and any(key.lower().startswith("utm_") for key, _ in parse_qsl(parsed.query)):
                # Tracking parameters are stripped by canonicalization later; they do not improve ranking.
                pass
            if not validate_official_url(href, self.trusted_domains):
                continue
            if self.config.allowed_document_domains and not any(
                host == domain or host.endswith("." + domain) for domain in self.config.allowed_document_domains
            ):
                continue
            context = f"{anchor.get_text(' ', strip=True)} {anchor.get('title', '')}".lower()
            score = sum(2 for term in PREFERRED_TERMS if term in context)
            if parsed.path.lower().endswith(".pdf"):
                score += 1
            ranked.append((-score, index, href))
        links = list(dict.fromkeys(item[2] for item in sorted(ranked)))[:10]
        return soup.get_text("\n", strip=True)[:20000], links
