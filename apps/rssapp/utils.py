import hashlib
import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


def category_label(value):
    """Normalize a feed category value, defaulting to 'Uncategorized'."""
    cleaned = (value or "").strip()
    return cleaned if cleaned else "Uncategorized"


def normalize_url(url: str) -> str:
    """Normalize URL by removing utm_* params, sorting query keys, and dropping fragment."""
    parts = urlsplit(url)
    clean_query_items = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower().startswith("utm_"):
            continue
        clean_query_items.append((key, value))

    clean_query_items.sort(key=lambda item: (item[0], item[1]))
    normalized_query = urlencode(clean_query_items, doseq=True)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, normalized_query, ""))


def generate_article_hash(
    title: str, normalized_link: str, guid: Optional[str] = None
) -> str:
    """Always return a SHA-256 hex digest that fits in max_length=64."""
    if guid and guid.strip():
        return hashlib.sha256(guid.strip().encode("utf-8")).hexdigest()

    key = f"{title.strip()}\n{normalized_link.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/loopback IP (SSRF protection)."""
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return True
    except socket.gaierror:
        return True  # Treat unresolvable hosts as disallowed
    return False


def fetch_feed_title(url: str) -> str:
    """Fetch an RSS/Atom feed URL and extract the feed title."""
    import xml.etree.ElementTree as ET

    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return ""
        if _is_private_ip(parts.hostname or ""):
            return ""

        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Feedee/1.0 (feed title fetcher)"},
            allow_redirects=True,
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.content)

        # RSS 2.0: <rss><channel><title>
        channel = root.find("channel")
        if channel is not None:
            title_el = channel.find("title")
            if title_el is not None and title_el.text:
                return title_el.text.strip()

        # Atom: <feed xmlns="http://www.w3.org/2005/Atom"><title>
        atom_ns = "http://www.w3.org/2005/Atom"
        title_el = root.find(f"{{{atom_ns}}}title")
        if title_el is not None and title_el.text:
            return title_el.text.strip()

        # Fallback: first <title> anywhere
        title_el = root.find(".//title")
        if title_el is not None and title_el.text:
            return title_el.text.strip()

    except Exception:
        logger.debug("Failed to fetch feed title for %s", url, exc_info=True)

    return ""


def fetch_url_metadata(url: str) -> dict:
    """
    Fetch a URL and extract title, description, and OGP thumbnail.
    Returns dict with keys: title, description, thumbnail_url (all strings, may be empty).
    """
    result = {"title": "", "description": "", "thumbnail_url": ""}

    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return result
        if _is_private_ip(parts.hostname or ""):
            return result

        resp = requests.get(
            url,
            timeout=5,
            headers={"User-Agent": "Feedee/1.0 (bookmark metadata fetcher)"},
            allow_redirects=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type:
            return result

        soup = BeautifulSoup(resp.content, "html.parser")

        # OGP takes priority
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_image = soup.find("meta", property="og:image")

        result["title"] = (
            (og_title["content"] if og_title and og_title.get("content") else "")
            or (soup.title.string if soup.title and soup.title.string else "")
        ).strip()

        meta_desc = soup.find("meta", attrs={"name": "description"})
        result["description"] = (
            (og_desc["content"] if og_desc and og_desc.get("content") else "")
            or (meta_desc["content"] if meta_desc and meta_desc.get("content") else "")
        ).strip()

        result["thumbnail_url"] = (
            og_image["content"] if og_image and og_image.get("content") else ""
        ).strip()

    except Exception:
        logger.debug("Failed to fetch metadata for %s", url, exc_info=True)

    return result
