import hashlib
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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


def generate_article_hash(title: str, normalized_link: str, guid: Optional[str] = None) -> str:
    """Use GUID when available; otherwise hash title + normalized link."""
    if guid and guid.strip():
        return guid.strip()

    key = f"{title.strip()}\n{normalized_link.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
