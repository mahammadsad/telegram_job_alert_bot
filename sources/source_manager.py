from __future__ import annotations

import logging
from typing import Protocol

import requests

from processing.models import DiscoveredItem
from sources.base import SourceConfig
from sources.html_source import HTMLSource
from sources.rss_source import RSSSource
from sources.json_source import JSONSource
from sources.sitemap_source import SitemapSource


logger = logging.getLogger(__name__)
PARSERS = {"rss": RSSSource, "html": HTMLSource, "json_api": JSONSource, "sitemap": SitemapSource}


class SourceCheckStore(Protocol):
    def source_check_due(self, source_name: str, min_interval_minutes: int) -> bool: ...
    def record_source_check(
        self, source_name: str, source_url: str, status: str, detail: str = ""
    ) -> None: ...


class SourceManager:
    def __init__(
        self,
        source_configs: list[dict],
        session: requests.Session | None = None,
        repository: SourceCheckStore | None = None,
        respect_intervals: bool = True,
        trusted_domains: set[str] | None = None,
    ):
        self.configs = [SourceConfig.from_dict(item) for item in source_configs]
        self.session = session
        self.repository = repository
        self.respect_intervals = respect_intervals
        self.trusted_domains = trusted_domains or set()
        self.checked_count = 0
        self.success_count = 0
        self.failure_count = 0

    def discover_all(self) -> list[DiscoveredItem]:
        items: list[DiscoveredItem] = []
        for config in self.configs:
            if not config.enabled:
                logger.info("source_skipped name=%r reason=disabled", config.name)
                continue
            if self.repository and self.respect_intervals and not self.repository.source_check_due(
                config.name, config.min_interval_minutes
            ):
                logger.info(
                    "source_skipped name=%r reason=min_interval interval_minutes=%s",
                    config.name,
                    config.min_interval_minutes,
                )
                continue
            parser = PARSERS.get(config.parser_type)
            if not parser:
                logger.error("source_failed name=%r reason=unknown_parser", config.name)
                if self.repository:
                    self.repository.record_source_check(
                        config.name, config.url, "FAILED", "unknown parser"
                    )
                continue
            logger.info("source_check name=%r url=%s", config.name, config.url)
            self.checked_count += 1
            try:
                if parser is RSSSource:
                    discovered = parser(config, self.session, self.trusted_domains).discover()
                else:
                    discovered = parser(config, self.session).discover()
                logger.info("source_discovered name=%r count=%s", config.name, len(discovered))
                if self.repository:
                    self.repository.record_source_check(
                        config.name, config.url, "SUCCESS", f"discovered={len(discovered)}"
                    )
                items.extend(discovered)
                self.success_count += 1
            except Exception as exc:
                logger.exception("source_failed name=%r error=%s", config.name, exc)
                if self.repository:
                    self.repository.record_source_check(config.name, config.url, "FAILED", str(exc))
                self.failure_count += 1
        return items
