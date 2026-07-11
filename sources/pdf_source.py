from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from processing.models import OfficialDocument


MIN_PDF_TEXT = 80


def extract_pdf(content: bytes, source_url: str) -> OfficialDocument:
    document = fitz.open(stream=content, filetype="pdf")
    pages: dict[int, str] = {}
    links: list[str] = []
    for page_number, page in enumerate(document, start=1):
        pages[page_number] = page.get_text("text").strip()
        for link in page.get_links():
            if link.get("uri"):
                links.append(link["uri"])
    combined = "\n\n".join(f"[PAGE {number}]\n{text}" for number, text in pages.items())
    if links:
        combined += "\n\n[EXTRACTED DOCUMENT LINKS]\n" + "\n".join(dict.fromkeys(links))
    return OfficialDocument(
        requested_url=source_url,
        final_url=source_url,
        final_domain="",
        content_type="application/pdf",
        content_sha256=hashlib.sha256(content).hexdigest(),
        text=combined,
        page_text=pages,
        extracted_links=list(dict.fromkeys(links)),
        scanned_pdf=len("".join(pages.values()).strip()) < MIN_PDF_TEXT,
    )


def extract_pdf_file(path: str | Path, source_url: str = "file://fixture.pdf") -> OfficialDocument:
    return extract_pdf(Path(path).read_bytes(), source_url)
