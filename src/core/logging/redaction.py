"""Best-effort redaction of secrets before they reach a log sink."""

import re
from typing import Any, Mapping

_SENSITIVE_KEY = (
    r"(?:password|passwd|passphrase|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|authorization|auth|session|cookie|bearer|"
    r"client[_-]?secret|refresh[_-]?token)"
)

_SENSITIVE_KEY_RE = re.compile(_SENSITIVE_KEY, re.IGNORECASE)
_KEY_VALUE_RE = re.compile(
    rf"(?P<key>[A-Za-z0-9_.-]*{_SENSITIVE_KEY}[A-Za-z0-9_.-]*)(?P<sep>\s*=\s*)(?P<value>[^\s,;\"']+)",
    re.IGNORECASE,
)
_SENSITIVE_FLAG_RE = re.compile(
    rf"(?P<flag>--?[A-Za-z0-9_-]*{_SENSITIVE_KEY}[A-Za-z0-9_-]*)" r"(?P<sep>(?:=|\s+))(?P<value>[^\s,;\"']+)",
    re.IGNORECASE,
)
_AUTHORIZATION_RE = re.compile(
    r"(?im)\b(?P<header>authorization\s*:\s*)(?P<value>[^\r\n]+)",
)
_QUOTED_KEY_VALUE_RE = re.compile(
    rf"(?P<prefix>(?P<key_quote>['\"])?[A-Za-z0-9_.-]*{_SENSITIVE_KEY}[A-Za-z0-9_.-]*"
    rf"(?P=key_quote)?\s*[:=]\s*)(?P<value_quote>['\"])?(?P<value>[^\"'\s,;}}]+)(?P=value_quote)?",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\b(?P<prefix>bearer|basic)\s+(?P<value>[A-Za-z0-9._~+/=-]+)")
_URL_USERINFO_RE = re.compile(r"(?P<scheme>https?://)(?P<userinfo>[^/@\s]+)@")


def is_sensitive_key(key: str) -> bool:
    """Report whether a field name is normally secret."""
    return bool(_SENSITIVE_KEY_RE.search(str(key)))


def redact_text(value: Any) -> str:
    """Mask common secret shapes in a string without hiding ordinary values."""
    text = str(value)
    text = _AUTHORIZATION_RE.sub(lambda match: f"{match.group('header')}***", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group('prefix')} ***", text)
    text = _URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}***@", text)
    text = _SENSITIVE_FLAG_RE.sub(lambda match: f"{match.group('flag')}{match.group('sep')}***", text)
    text = _KEY_VALUE_RE.sub(lambda match: f"{match.group('key')}{match.group('sep')}***", text)
    text = _QUOTED_KEY_VALUE_RE.sub(_redact_quoted_pair, text)
    return text


def _redact_quoted_pair(match: re.Match) -> str:
    quote = match.group("value_quote") or ""
    return f"{match.group('prefix')}{quote}***{quote}"


def redact_value(key: str, value: Any) -> Any:
    """Redact a mapping value when its key looks sensitive."""
    if is_sensitive_key(key):
        return "***"
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a redacted shallow copy of a mapping."""
    return {str(key): redact_value(str(key), value) for key, value in values.items()}


def redact_command(command: list[str] | tuple[str, ...]) -> list[str]:
    """Redact secret command-line values while keeping the command readable."""
    result = []
    redact_next = False
    for argument in command:
        text = str(argument)
        if redact_next:
            result.append("***")
            redact_next = False
            continue
        if text.startswith("-") and "=" not in text and is_sensitive_key(text.lstrip("-")):
            result.append(redact_text(text))
            redact_next = True
            continue
        result.append(redact_text(text))
    return result
