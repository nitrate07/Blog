"""SSRF-resistant source retrieval and small, dependency-free text extraction."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from .config import Settings, settings
from .models import SourceQuality


class UnsafeURL(ValueError):
    pass


@dataclass(frozen=True)
class RetrievedSource:
    url: str
    title: str | None
    text: str
    quality: SourceQuality


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


def validate_public_url(url: str, *, resolve_host: bool = True) -> str:
    """Reject credentials, non-web URLs, loopback/private addresses and private DNS targets."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeURL("URL must be a public http(s) URL without credentials")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise UnsafeURL("local network URLs are not allowed")
    try:
        if _is_ip_literal(host) and not _is_public_ip(host):
            raise UnsafeURL("private network URLs are not allowed")
        if resolve_host:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
            if not addresses or any(not _is_public_ip(address) for address in addresses):
                raise UnsafeURL("URL must resolve only to public addresses")
    except socket.gaierror as exc:
        raise UnsafeURL("URL hostname could not be resolved") from exc
    return url


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def classify_source(url: str, text: str = "") -> SourceQuality:
    host = (urlsplit(url).hostname or "").lower()
    corpus = f"{host} {text[:2000]}".lower()
    if host.endswith((".gov", ".edu", ".int")) or any(name in host for name in ("who.int", "nih.gov", "pubmed", "clinicaltrials.gov", "fda.gov", "ema.europa.eu")):
        return SourceQuality.PRIMARY
    if any(term in corpus for term in ("systematic review", "meta-analysis", "review article", "journalistic investigation")):
        return SourceQuality.SECONDARY
    if any(term in host for term in ("blog", "medium", "reddit", "facebook", "x.com", "twitter")):
        return SourceQuality.TERTIARY
    return SourceQuality.UNKNOWN


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "br", "li", "h1", "h2", "h3", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title.append(data)
        self.parts.append(data)


def extract_html(html: str) -> tuple[str | None, str]:
    parser = _TextExtractor()
    parser.feed(html)
    title = " ".join(" ".join(parser.title).split()) or None
    text = re.sub(r"\n{2,}", "\n", unescape(" ".join(parser.parts)))
    return title, " ".join(text.split())


class SourceFetcher:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    async def fetch(self, url: str) -> RetrievedSource:
        current_url = validate_public_url(url)
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers={"User-Agent": self.config.user_agent}) as client:
            for _ in range(self.config.max_redirects + 1):
                response = await client.get(current_url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response has no location")
                    current_url = validate_public_url(urljoin(current_url, location))
                    continue
                response.raise_for_status()
                declared_size = int(response.headers.get("content-length", "0") or 0)
                if declared_size > self.config.max_response_bytes:
                    raise ValueError("response exceeds size limit")
                body = await response.aread()
                if len(body) > self.config.max_response_bytes:
                    raise ValueError("response exceeds size limit")
                title, text = extract_html(body.decode(response.encoding or "utf-8", errors="replace"))
                if not text:
                    raise ValueError("source did not contain readable text")
                return RetrievedSource(current_url, title, text, classify_source(current_url, text))
        raise ValueError("too many redirects")
