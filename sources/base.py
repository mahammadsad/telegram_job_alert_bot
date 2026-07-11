from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from processing.models import DiscoveredItem


USER_AGENT = "SarkariTathyaKendraBot/1.0 (+Telegram public-information bot)"


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

    @classmethod
    def from_dict(cls, data: dict) -> "SourceConfig":
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        clean = {key: value for key, value in data.items() if key in allowed}
        clean["allowed_domains"] = tuple(clean.get("allowed_domains", ()))
        clean["allowed_document_domains"] = tuple(clean.get("allowed_document_domains", ()))
        return cls(**clean)


class BaseSource(ABC):
    def __init__(self, config: SourceConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def robots_allowed(self) -> bool:
        parsed = urlparse(self.config.url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.config.request_timeout)
            if response.status_code >= 400:
                return True
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, self.config.url)
        except requests.RequestException:
            return True

    def fetch(self) -> requests.Response:
        response = self.session.get(
            self.config.url,
            timeout=self.config.request_timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        final_host = (urlparse(response.url).hostname or "").lower().rstrip(".")
        if self.config.allowed_domains and not any(
            final_host == domain or final_host.endswith("." + domain)
            for domain in self.config.allowed_domains
        ):
            raise ValueError(f"source redirected to an unapproved domain: {final_host}")
        return response

    @abstractmethod
    def parse(self, content: bytes, base_url: str) -> list[DiscoveredItem]:
        raise NotImplementedError

    def discover(self) -> list[DiscoveredItem]:
        if not self.robots_allowed():
            raise PermissionError(f"robots.txt disallows {self.config.url}")
        response = self.fetch()
        return self.parse(response.content, response.url)[: self.config.max_items]
