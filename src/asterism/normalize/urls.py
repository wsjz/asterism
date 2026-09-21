from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "spm", "from"})


def canonical_url(value: str) -> str:
    """Return a stable form of ``value`` for use as an identity.

    Lowercases the scheme and host, removes the fragment, drops known
    tracking parameters, sorts the remaining query, and strips a trailing
    slash from non-root paths. Raises ``ValueError`` if the input is not an
    absolute http(s) URL.
    """
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("invalid URL")
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must be absolute http or https")
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
    ]
    query.sort()
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query, doseq=True), "")
    )
