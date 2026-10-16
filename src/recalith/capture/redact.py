"""Credential scrubbing before anything is durably written (SYSTEM_SPEC §13, A34).

Written fresh for Recalith (no Breadcrumbs source copied). Standard library
only, so the Task 3b fast path can run the same scrubber.

The scrubber replaces credential-shaped values with ``[REDACTED:<kind>]``
markers. It is a guard, not a guarantee: values that look like ordinary text
cannot be recognized. The original value is never retained anywhere, and
reports carry only kinds and counts. Scrubbing is idempotent, so a scrubbed
payload has a stable digest and duplicate detection still works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MARKER_PREFIX = "[REDACTED:"


def marker(kind: str) -> str:
    return f"{MARKER_PREFIX}{kind}]"


# Ordered: specific token formats first, so a generic assignment rule later
# sees an already-redacted value and leaves it alone.
_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
)

# (kind, pattern, group index of the secret value) — the key/prefix is kept.
_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("url_credential", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]{1,15}://[^\s/:@]+:)([^\s/@]+)(@)"), 2),
    ("authorization", re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic|token|digest)\s+)([^\s\"',;]+)"), 2),
    ("bearer_token", re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/\-]{12,}=*)"), 2),
    (
        "cli_secret",
        re.compile(r"(?i)((?<![\w-])--?(?:password|passwd|pass|token|api[-_]?key|secret|client[-_]secret|auth[-_]token|access[-_]token|private[-_]key)(?:=|\s+))(\"[^\"]*\"|'[^']*'|[^\s\"']+)"),
        2,
    ),
    (
        "assignment",
        re.compile(
            r"(?i)(\b[A-Za-z0-9_.\-]*(?:password|passwd|pwd|passphrase|secret|token|api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|credentials?|auth)\b[\"']?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;&]+)"
        ),
        2,
    ),
)

_ENV_REFERENCE = re.compile(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%[A-Za-z_][A-Za-z0-9_]*%)$")
_PLACEHOLDERS = frozenset({"", "true", "false", "null", "none", "***", "<redacted>", "redacted", "changeme"})

# JSON object keys whose string values are always treated as secrets.
_SENSITIVE_LAST = frozenset({"password", "passwd", "pwd", "passphrase", "secret", "token", "apikey", "credential", "credentials", "authorization", "cookie", "bearer", "auth", "privatekey", "accesskey", "secretkey"})
_SENSITIVE_PAIRS = frozenset({("api", "key"), ("access", "key"), ("private", "key"), ("secret", "key"), ("session", "key"), ("client", "secret"), ("auth", "token"), ("access", "token"), ("refresh", "token"), ("id", "token")})
_KEY_PARTS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


@dataclass
class ScrubReport:
    """Kinds and counts only; never the matched values."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def merge(self, other: "ScrubReport") -> None:
        for kind, n in other.counts.items():
            self.add(kind, n)


# Markers Recalith itself writes (redaction and bounded-text omission markers).
_OWN_MARKERS = (MARKER_PREFIX, "[recalith:")


def _is_reference_or_placeholder(value: str) -> bool:
    bare = value.strip("\"'")
    return bare.startswith(_OWN_MARKERS) or bare.lower() in _PLACEHOLDERS or bool(_ENV_REFERENCE.match(bare))


def _sub_token(kind: str, pattern: re.Pattern[str], text: str, report: ScrubReport) -> str:
    def repl(match: re.Match[str]) -> str:
        report.add(kind)
        return marker(kind)

    return pattern.sub(repl, text)


def _sub_context(kind: str, pattern: re.Pattern[str], group: int, text: str, report: ScrubReport) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group(group)
        if _is_reference_or_placeholder(value):
            return match.group(0)
        report.add(kind)
        parts = [match.group(i) or "" for i in range(1, (pattern.groups or 0) + 1)]
        quote = value[0] if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2 else ""
        parts[group - 1] = f"{quote}{marker(kind)}{quote}"
        return "".join(parts)

    return pattern.sub(repl, text)


def scrub_text(text: str, report: ScrubReport | None = None) -> tuple[str, ScrubReport]:
    report = report if report is not None else ScrubReport()
    if not text:
        return text, report
    out = text
    for kind, pattern in _TOKEN_PATTERNS:
        out = _sub_token(kind, pattern, out, report)
    for kind, pattern, group in _CONTEXT_PATTERNS:
        out = _sub_context(kind, pattern, group, out, report)
    return out, report


def contains_secret(text: str) -> bool:
    return scrub_text(text)[1].total > 0


def sensitive_key(key: str) -> bool:
    if key.startswith(MARKER_PREFIX):
        return False  # an already-scrubbed key; keeps scrubbing idempotent
    parts = [p.lower() for p in _KEY_PARTS.findall(key)]
    if not parts:
        return False
    if parts[-1] in _SENSITIVE_LAST:
        return True
    return any(pair in _SENSITIVE_PAIRS for pair in zip(parts, parts[1:]))


def scrub_json(value: Any, report: ScrubReport | None = None, *, _key: str | None = None) -> tuple[Any, ScrubReport]:
    """Return a scrubbed copy of a JSON value and the kinds/counts removed."""
    report = report if report is not None else ScrubReport()
    return _scrub(value, report, _key), report


def _scrub(value: Any, report: ScrubReport, key: str | None) -> Any:
    if isinstance(value, str):
        if key is not None and sensitive_key(key) and not _is_reference_or_placeholder(value):
            report.add("sensitive_field")
            return marker("sensitive_field")
        return scrub_text(value, report)[0]
    if isinstance(value, list):
        return [_scrub(item, report, None) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            new_key = scrub_text(raw_key, report)[0] if isinstance(raw_key, str) else raw_key
            while new_key in out:  # two keys scrubbed to the same marker stay distinct
                new_key = f"{new_key}#"
            out[new_key] = _scrub(item, report, raw_key if isinstance(raw_key, str) else None)
        return out
    return value
