"""Parse HTML articles into structured, embeddable chunks."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArticleChunk:
    article_id: str
    chunk_index: int
    title: str
    heading: str | None
    text: str
    language: str
    category: str
    verdict: str
    rating_value: int
    claim_reviewed: str
    file_number: int
    source_url: str
    chunk_type: str  # "metadata", "body", "evidence", "verdict", "sources"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "heading": self.heading or "",
            "language": self.language,
            "category": self.category,
            "verdict": self.verdict,
            "rating_value": str(self.rating_value),
            "claim_reviewed": self.claim_reviewed,
            "file_number": str(self.file_number),
            "source_url": self.source_url,
            "chunk_type": self.chunk_type,
        }

    def to_embedding_text(self) -> str:
        parts = [self.title]
        if self.heading:
            parts.append(self.heading)
        parts.append(self.text)
        return " ".join(parts)


class _ArticleHTMLParser(HTMLParser):
    """Extract structured content from an Arı Kaynak article HTML file."""

    def __init__(self) -> None:
        super().__init__()
        self._ld_json_scripts: list[dict[str, Any]] = []
        self._in_ld_json = False
        self._ld_json_buffer: list[str] = []
        self._in_article_body = False
        self._in_title_tag = False
        self._title_parts: list[str] = []
        self._body_parts: list[str] = []
        self._current_heading: str | None = None
        self._heading_buffer: list[str] = []
        self._ignored_depth = 0
        self._body_depth = 0
        self._current_tag: str | None = None
        self._tag_stack: list[str] = []
        self._meta: dict[str, str] = {}
        self._sections: list[tuple[str | None, list[str]]] = []
        self._current_section_heading: str | None = None
        self._current_section_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "script" and attr_dict.get("type") == "application/ld+json":
            self._in_ld_json = True
            self._ld_json_buffer = []
            return
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if tag == "title":
            self._in_title_tag = True
            return
        if tag == "meta":
            name = attr_dict.get("name", "") or attr_dict.get("property", "")
            content = attr_dict.get("content", "")
            if name and content:
                self._meta[name] = content
            return
        if tag == "div" and "article-body" in (attr_dict.get("class", "") or ""):
            self._in_article_body = True
            self._body_depth = 0
        if self._in_article_body:
            self._body_depth += 1
            if tag in {"h1", "h2", "h3"}:
                if self._current_section_parts and (self._current_section_heading or self._current_section_parts):
                    self._sections.append((self._current_section_heading, list(self._current_section_parts)))
                    self._current_section_parts = []
                self._current_heading = tag
                self._heading_buffer = []
            if tag in {"p", "li"}:
                self._current_section_parts.append("")
            if tag in {"p", "br", "li", "h1", "h2", "h3"}:
                self._body_parts.append("\n")
        self._tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld_json:
            self._in_ld_json = False
            try:
                data = json.loads(" ".join(self._ld_json_buffer))
                self._ld_json_scripts.append(data)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("Skipping malformed ld+json block: %s", exc)
            return
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag == "title":
            self._in_title_tag = False
            return
        if self._in_article_body:
            if tag in {"h1", "h2", "h3"}:
                heading_text = " ".join(self._heading_buffer).strip()
                self._current_section_heading = heading_text
                self._current_heading = None
            if tag in {"p", "br", "li", "h1", "h2", "h3"}:
                self._body_parts.append("\n")
            self._body_depth -= 1
            if self._body_depth <= 0:
                self._in_article_body = False
                if self._current_section_parts:
                    self._sections.append((self._current_section_heading, list(self._current_section_parts)))
                    self._current_section_heading = None
                    self._current_section_parts = []
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_ld_json:
            self._ld_json_buffer.append(data)
            return
        if self._in_title_tag:
            self._title_parts.append(data)
            return
        if self._in_article_body:
            if self._current_heading is not None:
                self._heading_buffer.append(data)
            self._body_parts.append(data)
            if self._current_section_parts is not None:
                if self._current_section_parts:
                    self._current_section_parts[-1] += data
                else:
                    self._current_section_parts.append(data)

    def get_result(self) -> _ParseResult:
        title = " ".join(" ".join(self._title_parts).split()) or None
        body = re.sub(r"\n{2,}", "\n", " ".join(self._body_parts))
        body = " ".join(body.split())
        claim_review_data = None
        article_data = None
        for script in self._ld_json_scripts:
            if script.get("@type") == "ClaimReview":
                claim_review_data = script
            if script.get("@type") == "Article":
                article_data = script
        return _ParseResult(
            title=title,
            body=body,
            sections=self._sections,
            ld_json_scripts=self._ld_json_scripts,
            claim_review=claim_review_data,
            article_data=article_data,
            meta=self._meta,
        )


@dataclass
class _ParseResult:
    title: str | None
    body: str
    sections: list[tuple[str | None, list[str]]]
    ld_json_scripts: list[dict[str, Any]]
    claim_review: dict[str, Any] | None
    article_data: dict[str, Any] | None
    meta: dict[str, str]

    @property
    def language(self) -> str:
        if self.article_data:
            return self.article_data.get("inLanguage", "en")
        return "tr" if "/tr/" in self.meta.get("og:url", "") else "en"

    @property
    def verdict(self) -> str:
        if self.claim_review:
            rating = self.claim_review.get("reviewRating", {})
            return rating.get("alternateName", "Unknown")
        return "Unknown"

    @property
    def rating_value(self) -> int:
        if self.claim_review:
            rating = self.claim_review.get("reviewRating", {})
            return rating.get("ratingValue", 0)
        return 0

    @property
    def claim_reviewed_text(self) -> str:
        if self.claim_review:
            return self.claim_review.get("claimReviewed", "")
        return ""

    @property
    def source_url(self) -> str:
        return self.meta.get("og:url", "")

    @property
    def description(self) -> str:
        return self.meta.get("og:description", "") or self.meta.get("description", "")

    @property
    def file_number_from_title(self) -> int:
        match = re.search(r"FILE No\. (\d+)", self.body[:500])
        if match:
            return int(match.group(1))
        return 0


def parse_article(html: str) -> list[ArticleChunk]:
    parser = _ArticleHTMLParser()
    parser.feed(html)
    result = parser.get_result()
    if not result.title:
        return []
    file_number = result.file_number_from_title
    category = _extract_category(result)
    article_id = _make_article_id(result)
    chunks: list[ArticleChunk] = []
    chunks.append(ArticleChunk(
        article_id=article_id,
        chunk_index=0,
        title=result.title,
        heading=None,
        text=_build_metadata_text(result),
        language=result.language,
        category=category,
        verdict=result.verdict,
        rating_value=result.rating_value,
        claim_reviewed=result.claim_reviewed_text,
        file_number=file_number,
        source_url=result.source_url,
        chunk_type="metadata",
    ))
    for idx, (heading, parts) in enumerate(result.sections):
        section_text = " ".join(parts).strip()
        if not section_text or len(section_text) < 30:
            continue
        chunk_type = _classify_section(heading, section_text)
        chunks.append(ArticleChunk(
            article_id=article_id,
            chunk_index=idx + 1,
            title=result.title,
            heading=heading,
            text=section_text,
            language=result.language,
            category=category,
            verdict=result.verdict,
            rating_value=result.rating_value,
            claim_reviewed=result.claim_reviewed_text,
            file_number=file_number,
            source_url=result.source_url,
            chunk_type=chunk_type,
        ))
    if not chunks:
        chunks.append(ArticleChunk(
            article_id=article_id,
            chunk_index=0,
            title=result.title,
            heading=None,
            text=result.body[:2000],
            language=result.language,
            category=category,
            verdict=result.verdict,
            rating_value=result.rating_value,
            claim_reviewed=result.claim_reviewed_text,
            file_number=file_number,
            source_url=result.source_url,
            chunk_type="body",
        ))
    return chunks


def parse_all_articles(articles_dir: Path, tr_dir: Path | None = None) -> list[ArticleChunk]:
    all_chunks: list[ArticleChunk] = []
    seen_ids: set[str] = set()
    if articles_dir.exists():
        for html_file in sorted(articles_dir.glob("*.html")):
            html = html_file.read_text(encoding="utf-8")
            chunks = parse_article(html)
            for chunk in chunks:
                if chunk.article_id not in seen_ids:
                    seen_ids.add(chunk.article_id)
            all_chunks.extend(chunks)
    if tr_dir and tr_dir.exists():
        en_ids = {c.article_id for c in all_chunks}
        for html_file in sorted(tr_dir.glob("*.html")):
            html = html_file.read_text(encoding="utf-8")
            chunks = parse_article(html)
            for chunk in chunks:
                if chunk.article_id not in en_ids:
                    all_chunks.append(chunk)
    return all_chunks


def _make_article_id(result: _ParseResult) -> str:
    source_url = result.source_url
    if source_url:
        slug = source_url.rstrip("/").split("/")[-1].replace(".html", "")
        lang = result.language
        return f"{lang}:{slug}"
    title = result.title or "unknown"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{result.language}:{slug}"


def _extract_category(result: _ParseResult) -> str:
    for script in result.ld_json_scripts:
        if script.get("@type") == "ClaimReview":
            pass
    for meta_key in ("article:section", "category"):
        if meta_key in result.meta:
            return result.meta[meta_key]
    for keyword in ("supplement", "exercise", "nutrition", "longevity", "women"):
        text = (result.title or "").lower() + " " + result.description.lower()
        if keyword in text:
            return keyword.capitalize()
    return "Health"


def _classify_section(heading: str | None, text: str) -> str:
    if not heading:
        return "body"
    h = heading.lower()
    if "verdict" in h or "conclusion" in h:
        return "verdict"
    if "source" in h or "reference" in h:
        return "sources"
    if "evidence" in h or "study" in h or "finding" in h or "result" in h:
        return "evidence"
    return "body"


def _build_metadata_text(result: _ParseResult) -> str:
    parts = [
        f"Title: {result.title}",
        f"Verdict: {result.verdict} ({result.rating_value}/5)",
        f"Claim: {result.claim_reviewed_text}",
        f"Language: {result.language}",
        f"Source: {result.source_url}",
    ]
    if result.description:
        parts.append(f"Description: {result.description}")
    return " | ".join(parts)
