"""Secret redaction for URLs, errors, logs and public API responses.

Upstream APIs (NASA DONKI/NeoWs) put keys in the query string. Those URLs and
the resulting httpx exception strings must never be persisted, logged or
served verbatim.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "REDACTED"

_SENSITIVE_PARAMS = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth",
    "authorization",
    "secret",
    "password",
    "client_secret",
}

# Match `name=value` in query strings / exception text. Word-boundary before
# the parameter name avoids false positives inside unrelated words.
_QUERY_RE = re.compile(
    r"(?i)(?P<prefix>[?&;])(?P<name>" + "|".join(sorted(_SENSITIVE_PARAMS)) + r")=(?P<value>[^&\s'\"<>]+)"
)


def redact_url(url: str | None) -> str | None:
    """Return *url* with sensitive query parameter values replaced."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = [
        (name, REDACTED if name.lower() in _SENSITIVE_PARAMS else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(pairs, doseq=True)))


def redact_secrets(text: str | None) -> str | None:
    """Return *text* with sensitive `name=value` pairs redacted.

    Handles full URLs and httpx exception messages that embed a URL.
    """
    if not text:
        return text
    return _QUERY_RE.sub(lambda m: f"{m.group('prefix')}{m.group('name')}={REDACTED}", text)
