import hashlib
import ipaddress
import logging
import socket
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

try:
    import trafilatura
except ImportError:  # pragma: no cover - optional dependency
    trafilatura = None


def category_label(value):
    """Normalize a feed group value, defaulting to 'Ungrouped'."""
    cleaned = (value or "").strip()
    return cleaned if cleaned else "Ungrouped"


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


def generate_bookmark_hash(normalized_url: str) -> str:
    """Generate SHA-256 hash for bookmark deduplication based on normalized URL."""
    if not normalized_url or not normalized_url.strip():
        return ""
    return hashlib.sha256(normalized_url.strip().encode("utf-8")).hexdigest()


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


def _fetch_external_response(
    url: str,
    *,
    timeout: int = 8,
    accept: str = "text/html,application/xhtml+xml",
    allow_non_html: bool = False,
    method: str = "GET",
) -> Optional[requests.Response]:
    """Fetch an external URL while preserving the existing SSRF guardrails."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if _is_private_ip(parts.hostname or ""):
        return None

    try:
        resp = requests.request(
            method.upper(),
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Feedee/1.0 (+feed discovery)",
                "Accept": accept,
            },
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception:
        logger.debug("Failed to fetch %s via %s", url, method, exc_info=True)
        return None

    content_type = resp.headers.get("content-type", "")
    if not allow_non_html and "html" not in content_type.lower():
        return None

    return resp


def _fetch_html_response(url: str, *, timeout: int = 8) -> Optional[requests.Response]:
    return _fetch_external_response(url, timeout=timeout)


def _looks_like_feed_response(response: requests.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    if any(
        token in content_type
        for token in (
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
            "application/rdf+xml",
        )
    ):
        return True

    sample = (response.text or "")[:1000].lower()
    return "<rss" in sample or "<feed" in sample or "<rdf:rdf" in sample


def _extract_feed_title(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""

    for elem in root.iter():
        if elem.tag.endswith("title") and (elem.text or "").strip():
            return elem.text.strip()
    return ""


def discover_feed_url(url: str) -> dict:
    """Resolve a homepage or feed URL to a concrete RSS/Atom feed URL."""
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return {
            "feed_url": "",
            "title": "",
            "discovered": False,
            "error": "EMPTY_URL",
            "error_detail": "Please enter a URL.",
        }

    response = _fetch_external_response(
        cleaned_url,
        accept="application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, application/xhtml+xml",
        allow_non_html=True,
    )
    if response is None:
        # Determine the specific reason for failure
        parts = urlsplit(cleaned_url)
        if parts.scheme not in ("http", "https"):
            return {
                "feed_url": "",
                "title": "",
                "discovered": False,
                "error": "INVALID_URL",
                "error_detail": "URL must start with http:// or https://.",
            }
        if _is_private_ip(parts.hostname or ""):
            return {
                "feed_url": "",
                "title": "",
                "discovered": False,
                "error": "PRIVATE_IP",
                "error_detail": "Cannot access private or local networks for security reasons.",
            }
        # Network error or HTTP error
        return {
            "feed_url": "",
            "title": "",
            "discovered": False,
            "error": "NETWORK_ERROR",
            "error_detail": "Could not connect to the website. Please check the URL and try again.",
        }

    if _looks_like_feed_response(response):
        return {
            "feed_url": response.url,
            "title": _extract_feed_title(response.text)
            or urlsplit(response.url).netloc,
            "discovered": response.url != cleaned_url,
            "error": "",
            "error_detail": "",
        }

    soup = BeautifulSoup(response.text, "html.parser")
    page_title = (
        soup.title.string.strip()
        if soup.title and soup.title.string
        else urlsplit(cleaned_url).netloc
    )

    candidates = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        rel_values = (
            [str(item).lower() for item in rel]
            if isinstance(rel, list)
            else [str(rel).lower()]
        )
        link_type = (link.get("type") or "").lower()
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if "alternate" in rel_values and (
            "rss" in link_type or "atom" in link_type or href.endswith(".xml")
        ):
            candidates.append(urljoin(response.url, href))

    base = f"{urlsplit(response.url).scheme}://{urlsplit(response.url).netloc}"
    for path in ("/feed", "/feed.xml", "/rss", "/rss.xml", "/atom.xml", "/index.xml"):
        candidates.append(urljoin(base, path))

    for candidate in dict.fromkeys(candidates):
        head_response = _fetch_external_response(
            candidate,
            timeout=5,
            accept="application/rss+xml, application/atom+xml, application/xml, text/xml",
            allow_non_html=True,
            method="HEAD",
        )
        if head_response is not None and _looks_like_feed_response(head_response):
            return {
                "feed_url": candidate,
                "title": page_title,
                "discovered": True,
                "error": "",
                "error_detail": "",
            }

        candidate_response = _fetch_external_response(
            candidate,
            timeout=5,
            accept="application/rss+xml, application/atom+xml, application/xml, text/xml, text/html",
            allow_non_html=True,
        )
        if candidate_response is not None and _looks_like_feed_response(
            candidate_response
        ):
            return {
                "feed_url": candidate_response.url,
                "title": _extract_feed_title(candidate_response.text) or page_title,
                "discovered": True,
                "error": "",
                "error_detail": "",
            }

    return {
        "feed_url": "",
        "title": page_title,
        "discovered": False,
        "error": "NO_FEED_FOUND",
        "error_detail": "No RSS or Atom feed found at this URL. Try the homepage or look for a feed link on the website.",
    }


def _extract_content_with_bs4(html: str, url: str) -> str:
    """Fallback article extraction when a dedicated extractor is unavailable."""
    soup = BeautifulSoup(html, "html.parser")

    for selector in (
        "script",
        "style",
        "noscript",
        "iframe",
        "nav",
        "aside",
        "footer",
        "form",
        "button",
        "svg",
    ):
        for node in soup.select(selector):
            node.decompose()

    for selector in (
        ".share",
        ".sharing",
        ".social",
        ".sidebar",
        ".related",
        ".recommend",
        ".comments",
        ".advert",
        ".ads",
        "[role='navigation']",
        "[aria-label='breadcrumb']",
    ):
        for node in soup.select(selector):
            node.decompose()

    root = (
        soup.find("article")
        or soup.find("main")
        or soup.select_one("[itemprop='articleBody']")
        or soup.select_one(
            ".post-content, .entry-content, .article-content, .content-body, .post-body, .article-body, .entry-body"
        )
        or soup.body
    )
    if root is None:
        return ""

    for tag in root.select("a[href]"):
        tag["href"] = urljoin(url, tag.get("href", ""))
    for tag in root.select("img[src]"):
        tag["src"] = urljoin(url, tag.get("src", ""))

    fragments = []
    for node in root.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "ul",
            "ol",
            "li",
            "blockquote",
            "pre",
            "code",
            "table",
            "img",
        ]
    ):
        if node.name == "img" and not node.get("src"):
            continue
        if node.name != "img" and not node.get_text(" ", strip=True):
            continue
        fragments.append(str(node))

    return "\n".join(fragments).strip()


def extract_article_content(url: str) -> dict:
    """Best-effort full-text extraction with a clean summary fallback contract."""
    try:
        response = _fetch_html_response(url)
        if response is None:
            return {"content": "", "source": "summary", "status": "skipped"}

        html = response.text
        extracted = ""
        if trafilatura is not None:
            try:
                extracted = (
                    trafilatura.extract(
                        html,
                        url=url,
                        output_format="html",
                        include_links=True,
                        include_images=True,
                        include_tables=True,
                        favor_recall=True,
                    )
                    or ""
                ).strip()
            except Exception:
                logger.debug("Trafilatura extraction failed for %s", url, exc_info=True)

        if not extracted:
            extracted = _extract_content_with_bs4(html, url)

        if extracted:
            return {
                "content": extracted,
                "source": "extracted",
                "status": "success",
            }
        return {"content": "", "source": "summary", "status": "failed"}
    except Exception:
        logger.info("Failed to extract article content for %s", url, exc_info=True)
        return {"content": "", "source": "summary", "status": "failed"}


def fetch_url_metadata(url: str) -> dict:
    """
    Fetch a URL and extract title, description, and OGP thumbnail.
    Returns dict with keys: title, description, thumbnail_url (all strings, may be empty).
    """
    result = {"title": "", "description": "", "thumbnail_url": ""}

    try:
        resp = _fetch_html_response(url, timeout=5)
        if resp is None:
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
