"""Safe projections; command output and container environments are never API payloads."""

import re
from urllib.parse import urlsplit, urlunsplit

SENSITIVE = re.compile(
    r"(?i)(password|passwd|token|api.?key|cookie.?secret|credential|private.?key|authorization|environment)"
)
ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|api_key|secret)\s*[=:]\s*[^\s,;]+"
)


def clean(value):
    if isinstance(value, dict):
        return {
            str(k): clean(v) for k, v in value.items() if not SENSITIVE.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = ASSIGNMENT.sub(r"\1=[REDACTED]", value)
        # redact credentials and all query parameters from absolute URLs
        if value.startswith(("http://", "https://", "postgresql://")):
            try:
                u = urlsplit(value)
                host = u.netloc.rsplit("@", 1)[-1]
                return urlunsplit((u.scheme, host, u.path, "", ""))
            except ValueError:
                return "[invalid URL]"
        value = re.sub(
            r"(?i)\b(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{20,}", "[REDACTED]", value
        )
    return value


def reject_secret_fields(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if SENSITIVE.search(str(k)):
                raise ValueError(
                    "secret values and environment fields are not permitted"
                )
            reject_secret_fields(v)
    elif isinstance(value, list):
        for v in value:
            reject_secret_fields(v)
    elif isinstance(value, str) and clean(value) != value:
        raise ValueError("secret-like value is not permitted")
