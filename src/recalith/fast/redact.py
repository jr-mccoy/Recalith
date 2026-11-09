"""Credential scrubbing before anything is durably written (SYSTEM_SPEC §13, A34).

Written fresh for Recalith (no Breadcrumbs source copied). Standard library
only: the hook fast path and the service path run the same scrubber.

The scrubber replaces credential-shaped values with ``[REDACTED:<kind>]``
markers. It is a guard, not a guarantee: values that look like ordinary text
cannot be recognized. The original value is never retained anywhere, and
reports carry only kinds and counts. Scrubbing is idempotent, so a scrubbed
payload has a stable digest and duplicate detection still works.
"""

from __future__ import annotations

import re
if False:  # annotations only: importing typing costs hook startup time (SYSTEM_SPEC §5.1.1)
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
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}")),
    ("twilio_key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    # A bare AWS secret access key: exactly 40 base64 characters with mixed case, a digit
    # and a '/' or '+', bounded by non-base64 characters (a longer blob never matches).
    # A run that starts or ends with '/' or holds '//' is a path, never a key.
    ("aws_secret_key", re.compile(r"(?<![A-Za-z0-9/+])(?!/)(?![A-Za-z0-9/+]{0,38}//)(?=[A-Za-z0-9/+]{0,39}[/+])(?=[A-Za-z0-9/+]{0,39}[0-9])(?=[A-Za-z0-9/+]{0,39}[a-z])(?=[A-Za-z0-9/+]{0,39}[A-Z])[A-Za-z0-9/+]{39}[A-Za-z0-9+](?![A-Za-z0-9/+=])")),
)

# PostgreSQL client tools whose --password (and -W) is a prompt switch that takes no value,
# and the MySQL family whose -pVALUE attaches the password to the flag.
_PG_PROMPT_TOOLS = frozenset({"psql", "pg_dump", "pg_dumpall", "pg_restore", "pg_basebackup", "pgbench", "createdb", "dropdb", "createuser", "dropuser", "vacuumdb", "reindexdb", "clusterdb"})
_MYSQL_TOOLS = frozenset({"mysql", "mysqldump", "mysqladmin", "mysqlimport", "mysqlcheck", "mysqlshow", "mariadb", "mariadb-dump", "mariadb-admin"})
_COMMAND_WORD = re.compile(r"(?:^|[\s/\\'\"=(])([A-Za-z_][A-Za-z0-9_.\-]*?)(?:\.exe)?(?=\s)")


def _line_commands(match: re.Match[str]) -> set[str]:
    """The command-like words before a match on its line (a tool named earlier on that line)."""
    text = match.string
    start = text.rfind("\n", 0, match.start()) + 1
    return {m.group(1).lower() for m in _COMMAND_WORD.finditer(text[start:match.start()])}


def _cli_secret_applies(match: re.Match[str]) -> bool:
    flag = match.group(1).strip().lower()
    # `psql --password mydb`: the flag prompts; the next word is a database, not a secret.
    return not (flag == "--password" and _line_commands(match) & _PG_PROMPT_TOOLS)


def _mysql_secret_applies(match: re.Match[str]) -> bool:
    return bool(_line_commands(match) & _MYSQL_TOOLS)


def _url_credential_applies(match: re.Match[str]) -> bool:
    # `http://localhost:4873/@scope/pkg`: a port and a path, not user:password@host.
    return not re.match(r"\d{1,5}/", match.group(2))


def _basic_auth_applies(match: re.Match[str]) -> bool:
    # `docker run -u 1000:1000`: a uid:gid pair, not user:password.
    user = re.split(r"[\s=]", match.group(1).rstrip(":"))[-1].strip("\"'")
    return not (match.group(2).isdigit() and user.isdigit())


_SECRET_NAME_SUFFIX = re.compile(r"(?:password|passwd|pwd|passphrase|secret|token|api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|credentials?|auth)$", re.I)


_AUTH_SCHEMES = frozenset({"bearer", "basic", "digest", "token", "negotiate"})


def _assignment_applies(match: re.Match[str]) -> bool:
    # `Authorization: Bearer X`: the scheme word is not the secret (the authorization rule took X).
    return sensitive_name(match.group(2)) and match.group(3).strip("\"'").lower() not in _AUTH_SCHEMES


# (kind, pattern, group index of the secret value, predicate or None) — the key/prefix is kept.
_CONTEXT_PATTERNS = (
    ("url_credential", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]{1,15}://[^\s/:@]{1,256}+:)([^\s@]{1,256}+)(@)"), 2, _url_credential_applies),
    ("authorization", re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic|token|digest)\s+)([^\s\"',;]+)"), 2, None),
    ("bearer_token", re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/\-]{12,}=*)"), 2, None),
    # A whole Cookie/Set-Cookie header value, up to the end of its line (or an escaped newline).
    ("cookie", re.compile(r"(?i)\b((?:set-)?cookie\s*:\s*)((?:(?!\\n)[^\r\n])+)"), 2, None),
    ("signed_url", re.compile(r"(?i)([?&](?:sig|x-amz-signature|x-goog-signature|signature)=)([^&\s\"'#]+)"), 2, None),
    (
        "cli_secret",
        re.compile(r"(?i)((?<![\w-])--?(?:password|passwd|pass|token|api[-_]?key|secret|client[-_]secret|auth[-_]token|access[-_]token|private[-_]key)(?:=|\s+))(\"[^\"]*\"|'[^']*'|[^\s\"']+)"),
        2,
        _cli_secret_applies,
    ),
    ("cli_secret", re.compile(r"((?<![\w-])-p)(\"[^\"]*\"|'[^']*'|[^\s\"'-][^\s\"']*)"), 2, _mysql_secret_applies),
    ("basic_auth", re.compile(r"((?<![\w-])(?:-u|--user|--proxy-user)(?:=|\s+)[\"']?[^\s:\"']+:)([^\s\"']+)"), 2, _basic_auth_applies),
    (
        "assignment",
        # The name is matched once and never backtracked into: it starts only where no name character precedes it,
        # is taken whole (possessive, at most 128 characters) and must hold a secret word within its first 64.
        # Two free runs around the word backtracked quadratically: 16 KiB of "a.key-" took 8.2 s on 0.1.0.dev10,
        # and the hook has 250 ms in all (SYSTEM_SPEC §5.1.1).
        re.compile(r"(?i)((?<![A-Za-z0-9_.\-])((?=[A-Za-z0-9_.\-]{0,64}(?:pass|pwd|secret|token|key|credential|auth|cookie))[A-Za-z0-9_.\-]{1,128}+)[\"']?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',;&]+)"),
        3,
        _assignment_applies,
    ),
)

_ENV_REFERENCE = re.compile(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%[A-Za-z_][A-Za-z0-9_]*%)$")
_PLACEHOLDERS = frozenset({"", "true", "false", "null", "none", "***", "<redacted>", "redacted", "changeme"})

# JSON object keys whose string values are always treated as secrets.
_SENSITIVE_LAST = frozenset({"password", "passwd", "pwd", "passphrase", "secret", "token", "apikey", "credential", "credentials", "authorization", "cookie", "bearer", "auth", "privatekey", "accesskey", "secretkey"})
_SENSITIVE_PAIRS = frozenset({("api", "key"), ("access", "key"), ("private", "key"), ("secret", "key"), ("session", "key"), ("signing", "key"), ("encryption", "key"), ("master", "key"), ("client", "secret"), ("auth", "token"), ("access", "token"), ("refresh", "token"), ("id", "token")})
_KEY_PARTS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")

# argv flags whose *next* element is the secret (`--password VALUE`); the same vocabulary as cli_secret.
_SECRET_FLAG = re.compile(r"(?i)^--?(?:password|passwd|pass|token|api[-_]?key|secret|client[-_]secret|auth[-_]token|access[-_]token|private[-_]key)$")
_BASIC_AUTH_FLAG = frozenset({"-u", "--user", "--proxy-user"})


class ScrubReport:
    """Kinds and counts only; never the matched values."""

    __slots__ = ("counts",)

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts: dict[str, int] = dict(counts or {})

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


def _sub_context(kind: str, pattern: re.Pattern[str], group: int, applies, text: str, report: ScrubReport) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group(group)
        if _is_reference_or_placeholder(value) or (applies is not None and not applies(match)):
            return match.group(0)
        report.add(kind)
        quote = value[0] if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2 else ""
        whole, base = match.group(0), match.start()
        start, end = match.span(group)
        return whole[: start - base] + f"{quote}{marker(kind)}{quote}" + whole[end - base :]

    return pattern.sub(repl, text)


def scrub_text(text: str, report: ScrubReport | None = None) -> tuple[str, ScrubReport]:
    report = report if report is not None else ScrubReport()
    if not text:
        return text, report
    out = text
    for kind, pattern in _TOKEN_PATTERNS:
        out = _sub_token(kind, pattern, out, report)
    for kind, pattern, group, applies in _CONTEXT_PATTERNS:
        out = _sub_context(kind, pattern, group, applies, out, report)
    return out, report


def _tool_name(executable: str) -> str:
    base = re.split(r"[\\/]", executable)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def scrub_argv(argv: list[str], report: ScrubReport | None = None) -> tuple[list[str], ScrubReport]:
    """Scrub an argument array element by element *and* across neighbouring elements.

    A split command line separates a flag from its value (``--password``,
    ``VALUE``), so no single element shows the pair; the element after a secret
    flag is redacted here. The array keeps its length, so action identity stays
    exact for everything that is not a secret.
    """
    report = report if report is not None else ScrubReport()
    tool = _tool_name(argv[0]) if argv else ""
    out: list[str] = []
    for i, arg in enumerate(argv):
        prev = argv[i - 1] if i else None
        if prev is not None and _SECRET_FLAG.match(prev) and not (tool in _PG_PROMPT_TOOLS and prev.lower() == "--password") and not _is_reference_or_placeholder(arg):
            report.add("cli_secret")
            out.append(marker("cli_secret"))
        elif prev in _BASIC_AUTH_FLAG and ":" in arg and not _is_reference_or_placeholder(arg) and not all(p.isdigit() for p in arg.split(":", 1)):
            report.add("basic_auth")
            out.append(arg.split(":", 1)[0] + ":" + marker("basic_auth"))
        elif i and tool in _MYSQL_TOOLS and arg.startswith("-p") and len(arg) > 2 and not arg[2:].startswith(_OWN_MARKERS):
            report.add("cli_secret")
            out.append("-p" + marker("cli_secret"))
        else:
            out.append(scrub_text(arg, report)[0])
    return out, report


def contains_secret(text: str) -> bool:
    return scrub_text(text)[1].total > 0


def _name_parts(key: str) -> list[str]:
    return [p.lower() for p in _KEY_PARTS.findall(key)]


def sensitive_key(key: str) -> bool:
    if key.startswith(MARKER_PREFIX):
        return False  # an already-scrubbed key; keeps scrubbing idempotent
    parts = _name_parts(key)
    if not parts:
        return False
    if parts[-1] in _SENSITIVE_LAST:
        return True
    return any(pair in _SENSITIVE_PAIRS for pair in zip(parts, parts[1:], strict=False))  # adjacent pairs: the shorter tail ends it


def sensitive_name(name: str) -> bool:
    """A text assignment's name (``SECRET_KEY=``, ``DB_PASS:``) holds a secret.

    The same token rules as JSON keys, plus names ending in a secret word
    (``PGPASSWORD``, ``oauth``) and an abbreviated ``*_PASS``.
    """
    if name.startswith(MARKER_PREFIX):
        return False
    if _SECRET_NAME_SUFFIX.search(name) or sensitive_key(name):
        return True
    parts = _name_parts(name)
    # `DB_PASS`, `SMTP_PASS`, `db_pass`: an abbreviated password; not `test_pass` or `bypass`.
    return len(parts) > 1 and parts[-1] == "pass" and (name.isupper() or parts[-2] in _PASS_OWNERS)


_PASS_OWNERS = frozenset({"db", "database", "mysql", "pg", "postgres", "sql", "redis", "smtp", "mail", "ftp", "sftp", "ldap", "admin", "root", "user", "proxy", "rabbitmq", "mongo"})


def scrub_json(value: Any, report: ScrubReport | None = None, *, _key: str | None = None) -> tuple[Any, ScrubReport]:
    """Return a scrubbed copy of a JSON value and the kinds/counts removed."""
    report = report if report is not None else ScrubReport()
    return _scrub(value, report, _key), report


def _scrub(value: Any, report: ScrubReport, key: str | None) -> Any:
    if isinstance(value, str):
        if key is not None and sensitive_name(key) and not _is_reference_or_placeholder(value):
            report.add("sensitive_field")
            return marker("sensitive_field")
        return scrub_text(value, report)[0]
    if isinstance(value, list):
        if key == "argv" and value and all(isinstance(item, str) for item in value):
            return scrub_argv(value, report)[0]
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
