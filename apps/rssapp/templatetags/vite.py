import json
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

_manifest_cache = None


def _load_manifest():
    global _manifest_cache
    if _manifest_cache is not None and not settings.DEBUG:
        return _manifest_cache
    manifest_path = Path(settings.BASE_DIR) / "static" / "dist" / "manifest.json"
    if not manifest_path.exists():
        return {}
    with open(manifest_path) as f:
        _manifest_cache = json.load(f)
    return _manifest_cache


@register.simple_tag
def vite_assets(entry):
    """
    Output <script> and <link> tags for a Vite entry point.

    In DEBUG mode with VITE_DEV_MODE=True, points to the Vite dev server.
    Otherwise, reads the production manifest.
    """
    vite_dev_mode = getattr(settings, "VITE_DEV_MODE", False)

    if vite_dev_mode:
        vite_url = getattr(settings, "VITE_DEV_URL", "http://localhost:5173")
        base = settings.STATIC_URL.strip("/")
        return mark_safe(
            f'<script type="module" src="{vite_url}/{base}/@vite/client"></script>\n'
            f'<script type="module" src="{vite_url}/{base}/{entry}"></script>'
        )

    manifest = _load_manifest()
    chunk = manifest.get(entry, {})
    if not chunk:
        return ""

    tags = []

    # CSS files
    for css_file in chunk.get("css", []):
        tags.append(f'<link rel="stylesheet" href="{settings.STATIC_URL}dist/{css_file}">')

    # JS entry
    js_file = chunk.get("file", "")
    if js_file:
        tags.append(f'<script type="module" src="{settings.STATIC_URL}dist/{js_file}"></script>')

    return mark_safe("\n".join(tags))
