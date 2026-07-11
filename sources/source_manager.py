from __future__ import annotations

import logging

import requests

from processing.models import DiscoveredItem
from sources.base import SourceConfig
from sources.html_source import HTMLSource
from sources.rss_source import RSSSource


logger = logging.getLogger(__name__)
PARSERS = {"rss": RSSSource, "html": HTMLSource}


class SourceManager:
    def __init__(self, source_configs: list[dict], session: requests.Session | None = None):
        self.configs = [SourceConfig.from_dict(item) for item in source_configs]
        self.session = session

    def discover_all(self) -> list[DiscoveredItem]:
        items: list[DiscoveredItem] = []
        for config in self.configs:
            if not config.enabled:
                logger.info("source_skipped name=%r reason=disabled", config.name)
                continue
            parser = PARSERS.get(config.parser_type)
            if not parser:
                logger.error("source_failed name=%r reason=unknown_parser", config.name)
                continue
            logger.info("source_check name=%r url=%s", config.name, config.url)
            try:
                discovered = parser(config, self.session).discover()
                logger.info("source_discovered name=%r count=%s", config.name, len(discovered))
                items.extend(discovered)
            except Exception as exc:
                logger.exception("source_failed name=%r error=%s", config.name, exc)
        return items

