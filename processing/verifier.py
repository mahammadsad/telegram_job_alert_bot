from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser

from processing.models import OfficialDocument
from sources.base import USER_AGENT
from sources.pdf_source import extract_pdf


logger = logging.getLogger(__name__)
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "shorturl.at"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def hostname_is_trusted(hostname: str | None, trusted_domains: set[str]) -> bool:
    host = (hostname or "").lower().rstrip(".")
    if not host or host in SHORTENERS:
        return False
    return any(
        host == domain.lower().rstrip(".")
        or host.endswith("." + domain.lower().rstrip("."))
        for domain in trusted_domains
    )


def validate_official_url(url: str, trusted_domains: set[str]) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return False
    return hostname_is_trusted(parsed.hostname, trusted_domains)


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
    port = f":{parsed_port}" if parsed_port and parsed_port != 443 else ""
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query_parts = [part for part in parsed.query.split("&") if part and not part.lower().startswith(("utm_", "fbclid="))]
    return urlunparse((scheme, host + port, path, "", "&".join(sorted(query_parts)), ""))


@dataclass
class SafeFetcher:
    trusted_domains: set[str]
    session: requests.Session | None = None
    timeout: int = 25
    max_redirects: int = 5

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        self._robots_cache: dict[str, bool] = {}
        if hasattr(self.session, "headers"):
            self.session.headers.update({"User-Agent": USER_AGENT})

    def robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots_cache:
            return self._robots_cache[origin]
        robots_url = origin + "/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=self.timeout, allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                allowed = False
            elif response.status_code >= 400:
                allowed = True
            else:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                allowed = parser.can_fetch(USER_AGENT, url)
        except requests.RequestException:
            # A missing/unreachable robots file is treated as no published
            # restriction; request caps and a descriptive user agent remain.
            allowed = True
        self._robots_cache[origin] = allowed
        return allowed

    def fetch(self, url: str) -> tuple[requests.Response, list[str]]:
        current = url
        chain: list[str] = []
        for _ in range(self.max_redirects + 1):
            if not validate_official_url(current, self.trusted_domains):
                raise ValueError(f"untrusted URL in redirect chain: {current}")
            if not self.robots_allowed(current):
                raise PermissionError(f"robots.txt disallows verification fetch: {current}")
            response = self.session.get(current, timeout=self.timeout, allow_redirects=False)
            chain.append(current)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("redirect response has no Location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            if not validate_official_url(response.url, self.trusted_domains):
                raise ValueError(f"untrusted final URL: {response.url}")
            return response, chain
        raise ValueError("too many redirects")


def response_to_document(
    response: requests.Response, requested_url: str, redirect_chain: list[str] | None = None
) -> OfficialDocument:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    content = response.content
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"official document exceeds {MAX_DOCUMENT_BYTES} bytes")
    final_domain = urlparse(response.url).hostname or ""
    if content_type == "application/pdf" or content.startswith(b"%PDF"):
        document = extract_pdf(content, requested_url)
        return document.model_copy(
            update={
                "final_url": response.url,
                "final_domain": final_domain,
                "redirect_chain": redirect_chain or [requested_url],
            }
        )
    if content_type and not (
        content_type.startswith("text/html")
        or content_type.startswith("application/xhtml")
        or content_type.startswith("text/plain")
    ):
        raise ValueError(f"unsupported official content type: {content_type}")
    soup = BeautifulSoup(content, "lxml")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    links = [urljoin(response.url, node["href"]) for node in soup.find_all("a", href=True)]
    visible_text = soup.get_text("\n", strip=True)
    source_text = visible_text
    if links:
        source_text += "\n\n[EXTRACTED DOCUMENT LINKS]\n" + "\n".join(dict.fromkeys(links))
    return OfficialDocument(
        requested_url=requested_url,
        final_url=response.url,
        final_domain=final_domain,
        content_type=content_type or "text/html",
        content_sha256=hashlib.sha256(content).hexdigest(),
        text=source_text,
        page_text={1: source_text},
        extracted_links=list(dict.fromkeys(links)),
        redirect_chain=redirect_chain or [requested_url],
    )


def find_official_document(
    candidate_links: list[str], trusted_domains: set[str], session: requests.Session | None = None
) -> tuple[OfficialDocument | None, str | None]:
    fetcher = SafeFetcher(trusted_domains, session=session)
    failures: list[str] = []
    for link in candidate_links:
        if not validate_official_url(link, trusted_domains):
            failures.append(f"untrusted candidate: {link}")
            continue
        try:
            response, chain = fetcher.fetch(link)
            return response_to_document(response, link, chain), None
        except Exception as exc:
            logger.warning("official_fetch_failed url=%s error=%s", link, exc)
            failures.append(f"{link}: {exc}")
    return None, "; ".join(failures) if failures else "No official candidate URL found"
