import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "earthdata_token",
    "password",
    "refresh_token",
    "sas",
    "secret",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:access[_-]?token|api[_-]?key|client[_-]?secret|"
    r"earthdata[_-]?token|password|refresh[_-]?token|sas|secret|"
    r"sig|signature|token)\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^&\s,;]+)"
)
_AUTH_HEADER = re.compile(
    r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s]+@")


def redact_sensitive_text(value: str) -> str:
    redacted = _BEARER.sub(f"Bearer {REDACTED}", value)
    redacted = _AUTH_HEADER.sub(rf"\1{REDACTED}", redacted)
    redacted = _SENSITIVE_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)
    redacted = _URL_CREDENTIALS.sub(rf"\1{REDACTED}@", redacted)
    token = os.getenv("EARTHDATA_TOKEN", "").strip()
    if token:
        redacted = redacted.replace(token, REDACTED)
    return redacted


def redact_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return redact_sensitive_text(value)
        netloc = parts.netloc.rsplit("@", 1)
        if len(netloc) == 2:
            netloc = [f"{REDACTED}@{netloc[1]}"]
        query = [
            (key, REDACTED if key.casefold() in _SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
        sanitized = urlunsplit(
            (parts.scheme, netloc[0], parts.path, urlencode(query), "")
        )
    except ValueError:
        return redact_sensitive_text(value)
    return redact_sensitive_text(sanitized)
