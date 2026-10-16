"""Certified tool-output parsers (DATA_CONTRACTS §1.1 MappingName, §2.1 ToolAssertion).

Typed assertions, the exact error-signature line and observed runtime
versions come only from a parser registered here for that exact invocation
shape. A parser applies only to an exactly parsed argument array; shell text
with unknown parse status, arbitrary JSON printed by a command, and host- or
model-supplied "assertions" never certify anything. An applicable parser that
cannot recognize its grammar yields no assertions and marks parser coverage
incomplete rather than guessing.

Each parser certifies one output grammar at one ``version``; changing what it
recognizes requires a new version.
"""

from __future__ import annotations

import re
from recalith.fast.wire import ENVIRONMENT_GRAMMAR, LIMITS, utf8_len

if False:  # annotations only: importing typing costs hook startup time (SYSTEM_SPEC §5.1.1)
    from typing import Any, Callable, Mapping

ERROR_SIGNATURE_CAP = LIMITS["ERROR_SIGNATURE_CAP"]
TOOL_ASSERTION_IDENTITY_MAX = LIMITS["TOOL_ASSERTION_IDENTITY_MAX"]
TOOL_ASSERTION_VALUE_MAX = LIMITS["TOOL_ASSERTION_VALUE_MAX"]
TOOL_ASSERTIONS_MAX = LIMITS["TOOL_ASSERTIONS_MAX"]

_PYTHON_EXE = re.compile(r"^(?:python(?:\d+(?:\.\d+)?)?|py)$")


class ParseResult:
    __slots__ = ("parser_id", "assertions", "error_signature", "recognized", "runtime")

    def __init__(self, parser_id: str) -> None:
        self.parser_id = parser_id
        self.assertions: list[dict[str, Any]] = []
        self.error_signature: str | None = None
        self.recognized = False
        self.runtime: dict[str, str] = {}


class ParserSpec:
    __slots__ = ("parser_id", "version", "applies", "parse")

    def __init__(self, parser_id: str, version: int, applies: Callable[[Mapping[str, Any]], bool], parse: Callable[[str, int | None], ParseResult]) -> None:
        self.parser_id, self.version, self.applies, self.parse = parser_id, version, applies, parse

    @property
    def qualified_id(self) -> str:
        return f"{self.parser_id}@{self.version}"


def executable_name(executable: str | None) -> str | None:
    if not executable:
        return None
    base = re.split(r"[\\/]", executable)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _exact_argv(action: Mapping[str, Any]) -> list[str] | None:
    if action.get("parse_status") != "exact" or not isinstance(action.get("argv"), list) or not action["argv"]:
        return None
    return action["argv"]


def _python_module(action: Mapping[str, Any], module: str) -> bool:
    argv = _exact_argv(action)
    if argv is None:
        return False
    exe = executable_name(action.get("executable") or argv[0])
    return bool(exe and _PYTHON_EXE.match(exe)) and len(argv) >= 3 and argv[1] == "-m" and argv[2] == module


def _assertion(kind: str, identity: str, value: str, passed: bool | None) -> dict[str, Any] | None:
    if not identity or utf8_len(identity) > TOOL_ASSERTION_IDENTITY_MAX or utf8_len(value) > TOOL_ASSERTION_VALUE_MAX:
        return None
    return {"kind": kind, "identity": identity, "value": value, "passed": passed}


def _signature(line: str | None) -> str | None:
    """An exact line of at most 1 KiB; a longer line is not retained (never clipped)."""
    if line is None:
        return None
    line = line.rstrip("\r")
    return line if line and utf8_len(line) <= ERROR_SIGNATURE_CAP else None


def exit_status_assertion(exit_code: int) -> dict[str, Any]:
    """From the host's structured exit-code field (adapter mapping), not from text."""
    return {"kind": "exit_status", "identity": "exit_status", "value": str(exit_code), "passed": None}


# --------------------------------------------------------------------------
# pytest short summary (pytest >= 6 terminal reporter)
#
# Version 2 also recognizes the undecorated final line that ``pytest -q``
# prints (``1 failed in 0.01s``), observed in real Claude Code 2.1.301 hook
# payloads. The body must consist only of count items or "no tests ran".

_PYTEST_COUNT_ITEM = r"\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|warnings?|deselected|rerun)"
_PYTEST_SUMMARY = re.compile(rf"^(?P<deco>=+ )?(?P<body>(?:{_PYTEST_COUNT_ITEM})(?:, {_PYTEST_COUNT_ITEM})*|no tests ran) in \d+(?:\.\d+)?s(?: \([^)]*\))?(?(deco) =+)$")
_PYTEST_COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed|warnings?|deselected|rerun)")
_PYTEST_RESULT = re.compile(r"^(FAILED|ERROR) (\S+)(?: - .*)?$")
_PYTEST_E_LINE = re.compile(r"^E\s+\S")


def _pytest_applies(action: Mapping[str, Any]) -> bool:
    argv = _exact_argv(action)
    if argv is None:
        return False
    exe = executable_name(action.get("executable") or argv[0])
    return exe in ("pytest", "py.test") or _python_module(action, "pytest")


def _parse_pytest(text: str, exit_code: int | None) -> ParseResult:
    result = ParseResult("pytest_summary")
    lines = text.splitlines()
    summary = None
    for line in reversed(lines):
        match = _PYTEST_SUMMARY.match(line.strip())
        if match:
            summary = match.group("body")
            break
    if summary is None:
        return result
    result.recognized = True
    counts: dict[str, int] = {}
    for number, label in _PYTEST_COUNT.findall(summary):
        key = {"error": "errors", "warning": "warnings"}.get(label, label)
        counts[key] = counts.get(key, 0) + int(number)
    failed = counts.get("failed", 0) + counts.get("errors", 0)
    ran = failed + counts.get("passed", 0) + counts.get("xfailed", 0) + counts.get("xpassed", 0)
    verdict = None if ran == 0 else failed == 0
    session = _assertion("test_result", "pytest:session", summary, verdict)
    if session:
        result.assertions.append(session)
    first_failure = None
    for line in lines:
        match = _PYTEST_RESULT.match(line.rstrip("\r"))
        if not match:
            continue
        first_failure = first_failure or line
        item = _assertion("test_result", match.group(2), match.group(1).lower(), False)
        if item and len(result.assertions) < TOOL_ASSERTIONS_MAX - 1:
            result.assertions.append(item)
    if first_failure is None:
        e_lines = [ln for ln in lines if _PYTEST_E_LINE.match(ln)]
        first_failure = e_lines[-1].strip() if e_lines else None
    result.error_signature = _signature(first_failure) if failed else None
    return result


# --------------------------------------------------------------------------
# unittest text runner

_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in \d+(?:\.\d+)?s$")
_UNITTEST_STATUS = re.compile(r"^(OK|FAILED)(?: \((?P<detail>[^)]*)\))?$")
_UNITTEST_RESULT = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)")
_EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt)\b(?::.*)?$")


def _unittest_applies(action: Mapping[str, Any]) -> bool:
    return _python_module(action, "unittest")


def _parse_unittest(text: str, exit_code: int | None) -> ParseResult:
    result = ParseResult("unittest_summary")
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    ran = status = None
    for index in range(len(lines) - 1, -1, -1):
        match = _UNITTEST_STATUS.match(lines[index].strip())
        if match and status is None:
            status = match
            for back in range(index - 1, -1, -1):
                ran_match = _UNITTEST_RAN.match(lines[back].strip())
                if ran_match:
                    ran = int(ran_match.group(1))
                    break
            break
    if status is None or ran is None:
        return result
    result.recognized = True
    ok = status.group(1) == "OK"
    session = _assertion("test_result", "unittest:session", f"Ran {ran} tests; {status.group(0)}", None if ran == 0 else ok)
    if session:
        result.assertions.append(session)
    for line in lines:
        match = _UNITTEST_RESULT.match(line)
        if match:
            item = _assertion("test_result", f"{match.group(3)}.{match.group(2)}", match.group(1).lower(), False)
            if item and len(result.assertions) < TOOL_ASSERTIONS_MAX - 1:
                result.assertions.append(item)
    if not ok:
        exceptions = [ln for ln in lines if _EXCEPTION_LINE.match(ln)]
        result.error_signature = _signature(exceptions[-1]) if exceptions else None
    return result


# --------------------------------------------------------------------------
# Runtime version commands (A52): exact `python --version` / `node --version`

_PYTHON_VERSION = re.compile(r"^Python (\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?\+?)$")
_NODE_VERSION = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)$")


def _version_applies(names: Callable[[str], bool], flags: tuple[str, ...]) -> Callable[[Mapping[str, Any]], bool]:
    def applies(action: Mapping[str, Any]) -> bool:
        argv = _exact_argv(action)
        if argv is None or len(argv) != 2 or argv[1] not in flags:
            return False
        exe = executable_name(action.get("executable") or argv[0])
        return bool(exe and names(exe))

    return applies


def _version_parser(parser_id: str, key: str, pattern: re.Pattern[str]) -> Callable[[str, int | None], ParseResult]:
    def parse(text: str, exit_code: int | None) -> ParseResult:
        result = ParseResult(parser_id)
        stripped = text.strip()
        match = pattern.match(stripped) if exit_code == 0 and "\n" not in stripped else None
        if match and ENVIRONMENT_GRAMMAR[key].match(match.group(1)):
            result.recognized = True
            result.runtime[key] = match.group(1)
            item = _assertion("parsed_value", key, match.group(1), None)
            if item:
                result.assertions.append(item)
        return result

    return parse


CERTIFIED_PARSERS: tuple[ParserSpec, ...] = (
    ParserSpec("pytest_summary", 2, _pytest_applies, _parse_pytest),
    ParserSpec("unittest_summary", 1, _unittest_applies, _parse_unittest),
    ParserSpec("python_version", 1, _version_applies(lambda e: bool(_PYTHON_EXE.match(e)), ("--version", "-V")), _version_parser("python_version", "python_version", _PYTHON_VERSION)),
    ParserSpec("node_version", 1, _version_applies(lambda e: e in ("node", "nodejs"), ("--version", "-v")), _version_parser("node_version", "node_version", _NODE_VERSION)),
)


def applicable_parser(action: Mapping[str, Any]) -> ParserSpec | None:
    for spec in CERTIFIED_PARSERS:
        if spec.applies(action):
            return spec
    return None
