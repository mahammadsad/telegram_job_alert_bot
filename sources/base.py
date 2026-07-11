from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from processing.models import DiscoveredItem


USER_AGENT = "SarkariTathyaKendraBot/1.0 (+Telegram public-information bot)"
MAX_SOURCE_REDIRECTS = 5


def hostname_is_allowed(hostname: str | None, allowed_domains: tuple[str, ...]) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return bool(host) and any(
        host == domain or host.endswith("." + domain) for domain in allowed_domains
    )


def source_url_is_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and hostname_is_allowed(parsed.hostname, allowed_domains)
    )


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    parser_type: str
    categories: list[str]
    official: bool = False
    discovery_only: bool = True
    enabled: bool = False
    allowed_domains: tuple[str, ...] = ()
    allowed_document_domains: tuple[str, ...] = ()
    min_interval_minutes: int = 120
    request_timeout: int = 20
    max_items: int = 20
    item_selector: str | None = None
    title_selector: str | None = None
    link_selector: str | None = None
    summary_selector: str | None = None
    date_selector: str | None = None
    source_type: str = "RSS"
    slug: str = ""
    base_url: str | None = None
    feed_url: str | None = None
    state: str | None = None
    authority_type: str | None = None
    robots_status: str | None = None
    terms_reviewed: bool = False
    selector_verified_at: str | None = None
    notes: str | None = None
    article_inspection: bool = False
    json_items_path: str | None = None
    max_response_bytes: int = 2 * 1024 * 1024

    @classmethod
    def from_dict(cls, data: dict) -> "SourceConfig":
        data = dict(data)
        data.setdefault("url", data.get("feed_url") or data.get("base_url"))
        if data.get("parser_type"):
            data["parser_type"] = str(data["parser_type"]).lower()
        if data.get("source_type"):
            data["source_type"] = str(data["source_type"]).upper()
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        clean = {key: value for key, value in data.items() if key in allowed}
        clean["allowed_domains"] = tuple(
            str(value).lower().rstrip(".") for value in clean.get("allowed_domains", ())
        )
        clean["allowed_document_domains"] = tuple(
            str(value).lower().rstrip(".") for value in clean.get("allowed_document_domains", ())
        )
        return cls(**clean)


class BaseSource(ABC):
    def __init__(self, config: SourceConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.update({"User-Agent": USER_AGENT})

    def robots_allowed(self) -> bool:
        parsed = urlparse(self.config.url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.session.get(
                robots_url,
                timeout=self.config.request_timeout,
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                return False
            if response.status_code >= 400:
                return True
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, self.config.url)
        except requests.RequestException:
            return False

    def fetch(self) -> requests.Response:
        current = self.config.url
        for _ in range(MAX_SOURCE_REDIRECTS + 1):
            if not source_url_is_allowed(current, self.config.allowed_domains):
                raise ValueError(f"source URL is not HTTPS or has an unapproved host: {current}")
            response = self.session.get(
                current,
                timeout=self.config.request_timeout,
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("source redirect response has no Location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > self.config.max_response_bytes:
                raise ValueError(f"source response exceeds {self.config.max_response_bytes} bytes")
            if len(response.content) > self.config.max_response_bytes:
                raise ValueError(f"source response exceeds {self.config.max_response_bytes} bytes")
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(kind in content_type for kind in ("html", "xml", "json", "text")):
                raise ValueError(f"unsupported source content type: {content_type}")
            if not source_url_is_allowed(response.url, self.config.allowed_domains):
                raise ValueError(f"source returned an unapproved final URL: {response.url}")
            return response
        raise ValueError("source exceeded the redirect limit")

    @abstractmethod
    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        raise NotImplementedError

    def discover(self) -> list[DiscoveredItem]:
        if not self.robots_allowed():
            raise PermissionError(f"robots.txt disallows {self.config.url}")
        response = self.fetch()
        return self.parse(response.content, response.url)[: self.config.max_items]
