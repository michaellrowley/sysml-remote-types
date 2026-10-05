"""Retrieves the resource a TypeLink uri points at."""
import re
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_BYTES = 8 * 1024 * 1024
_GH_BLOB = re.compile(r"^/([^/]+)/([^/]+)/blob/(.+)$")


def raw_url(uri):
    """Rewrite github.com blob URLs to their raw-content equivalent."""
    u = urlparse(uri)
    if u.netloc == "github.com":
        m = _GH_BLOB.match(u.path)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return uri


def fetch(uri):
    u = urlparse(uri)
    if u.scheme == "file":
        return Path(unquote(u.path)).read_text(errors="replace")
    if u.scheme not in ("http", "https"):
        raise ValueError(f"unsupported uri scheme '{u.scheme}' in {uri}")
    with urllib.request.urlopen(raw_url(uri), timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"{uri} exceeds {MAX_BYTES} bytes")
    return data.decode("utf-8", "replace")
