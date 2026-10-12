"""Retrieves the resource a TypeLink uri points at."""
import re
import urllib.request
from urllib.parse import unquote, urlparse

DEFAULT_MAX_BYTES = 8 * 1024 ** 2
_GH_BLOB = re.compile(r"^/([^/]+)/([^/]+)/blob/(.+)$")


def raw_url(uri):
    """Rewrite github.com blob URLs to their raw-content equivalent."""
    u = urlparse(uri)
    if u.netloc == "github.com":
        m = _GH_BLOB.match(u.path)
        if m:
            # GitHub's blob page is HTML; the raw host serves the linked file itself.
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return uri


def fetch(uri, max_bytes=DEFAULT_MAX_BYTES):
    """Return the text at uri; http(s) and file: only. Larger than max_bytes is an error."""
    u = urlparse(uri)
    if u.scheme == "file":
        with open(unquote(u.path), "rb") as f:
            # Read one byte beyond the limit so oversized resources are detectable.
            data = f.read(max_bytes + 1)
    elif u.scheme in ("http", "https"):
        with urllib.request.urlopen(raw_url(uri), timeout=30) as r:
            # Bound the network read rather than downloading an untrusted file in full.
            data = r.read(max_bytes + 1)
    else:
        raise ValueError(f"unsupported uri scheme '{u.scheme}' in {uri}")
    if len(data) > max_bytes:
        raise ValueError(f"{uri} exceeds {max_bytes} bytes (see --max-bytes)")
    return data.decode("utf-8", "replace")
