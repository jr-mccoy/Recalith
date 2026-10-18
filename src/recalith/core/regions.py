"""Nondeclaration regions of user-channel text (SYSTEM_SPEC §7.1.2; decision 0011).

A sentence on the user channel is a declaration only when the user actually
said it. Text the user *quoted, pasted or attached* is not: fenced code,
blockquotes, attached or imported documents, recognizable email and diff
blocks, and pasted machine output whose authorship is uncertain (tracebacks,
log runs, terminal transcripts, indented code). :func:`regions` marks those
spans mechanically from the stored string, and admission checks a declaring
span against them by intersection. The absence of a region is not proof of
authorship, and there is deliberately **no first-person-verb heuristic**:
quoted prose may say "I want", and a genuine instruction may be terse or not
in English.

Offsets are Unicode code points into the exact stored string (the
``SpanLocator`` coordinates). Lines end at ``\\r\\n``, ``\\r`` or ``\\n``, so the
result does not depend on the platform that produced the text. Every rule
errs toward a larger region: an unclosed fence, attachment or email header
block runs to the end of the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

KINDS = ("fenced_code", "blockquote", "attachment", "email", "diff", "pasted")

_NEWLINE = re.compile(r"\r\n|\r|\n")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_QUOTE = re.compile(r"^ {0,3}>")
_ATTACH_OPEN = re.compile(r"^\s*<(document|attachment|file|pasted[-_ ]?text|email|quote|quoted|context|source|transcript)\b[^>]*>", re.I)
_PASTE_MARKER = re.compile(r"\[Pasted text #\d+[^\]]*\]", re.I)
_EMAIL_HEADER = re.compile(r"^\s*(From|To|Cc|Bcc|Subject|Date|Sent|Reply-To)\s*:\s*\S", re.I)
_EMAIL_DIVIDER = re.compile(r"^\s*-{2,}\s*(Original Message|Forwarded message)\s*-{2,}", re.I)
_EMAIL_WROTE = re.compile(r"^\s*On .{1,200}\bwrote:\s*$")
_DIFF_START = re.compile(r"^(diff --git |@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@)")
_DIFF_OLD = re.compile(r"^--- \S")
_DIFF_NEW = re.compile(r"^\+\+\+ \S")
_DIFF_LINE = re.compile(r"^([ +\-@\\]|index |new file mode|deleted file mode|similarity index|rename (?:from|to) |old mode|new mode|Binary files )")
_TRACEBACK = re.compile(r"^Traceback \(most recent call last\):\s*$")
_EXCEPTION = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt|Warning)\b")
_LOG_LINE = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|(?:DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL|TRACE)\b)")
_SHELL_PROMPT = re.compile(r"^(\$|>>>|PS [A-Za-z]:\\[^>]*>|[A-Za-z]:\\[^>]*>) \S")
_INDENTED = re.compile(r"^( {4}|\t)\S")


@dataclass(frozen=True)
class Region:
    kind: str
    start: int
    end: int  # exclusive; code points


@dataclass(frozen=True)
class _Line:
    start: int
    end: int  # end of the content, before the line terminator
    next: int  # start of the next line
    text: str

    @property
    def blank(self) -> bool:
        return not self.text.strip()


def lines(text: str) -> list[_Line]:
    """Lines with code-point offsets; any of CRLF, CR or LF ends a line."""
    out: list[_Line] = []
    pos = 0
    for match in _NEWLINE.finditer(text):
        out.append(_Line(pos, match.start(), match.end(), text[pos : match.start()]))
        pos = match.end()
    if pos < len(text) or not out:
        out.append(_Line(pos, len(text), len(text), text[pos:]))
    return out


def regions(text: str) -> list[Region]:
    """Every nondeclaration region of ``text``, sorted by start."""
    ls = lines(text)
    found: list[Region] = []
    found += _fences(ls, len(text))
    fenced = [(r.start, r.end) for r in found]

    def inside_fence(line: _Line) -> bool:
        return any(s <= line.start < e for s, e in fenced)

    rest = [line for line in ls if not inside_fence(line)]
    found += _runs(rest, "blockquote", lambda i, ln: bool(_QUOTE.match(ln.text)), lazy=True)
    found += _attachments(rest, len(text))
    found += [Region("attachment", line.start + m.start(), line.start + m.end()) for line in rest for m in _PASTE_MARKER.finditer(line.text)]
    found += _email(rest, len(text))
    found += _diffs(rest)
    found += _tracebacks(rest)
    found += _runs(rest, "pasted", lambda i, ln: bool(_LOG_LINE.match(ln.text)), minimum=2)
    found += _shell(rest)
    found += _indented(ls, rest)
    return sorted(found, key=lambda r: (r.start, r.end, r.kind))


def intersects(found: Iterable[Region], start: int, end: int) -> list[Region]:
    """The regions a span ``[start, end)`` overlaps."""
    return [r for r in found if r.start < end and start < r.end]


# --------------------------------------------------------------------------
# Rules


def _fences(ls: Sequence[_Line], length: int) -> list[Region]:
    out = []
    i = 0
    while i < len(ls):
        m = _FENCE.match(ls[i].text)
        if m is None:
            i += 1
            continue
        mark = m.group(1)
        closing = re.compile(r"^ {0,3}" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}\s*$")
        j = i + 1
        while j < len(ls) and not closing.match(ls[j].text):
            j += 1
        end = ls[j].end if j < len(ls) else length
        out.append(Region("fenced_code", ls[i].start, end))
        i = j + 1
    return out


def _runs(ls: Sequence[_Line], kind: str, match, *, minimum: int = 1, lazy: bool = False) -> list[Region]:
    """Maximal runs of consecutive matching lines (``lazy``: Markdown continuation lines join a quote)."""
    out = []
    i = 0
    while i < len(ls):
        if not match(i, ls[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(ls) and _adjacent(ls[j], ls[j + 1]) and (match(j + 1, ls[j + 1]) or (lazy and not ls[j + 1].blank)):
            j += 1
        if j - i + 1 >= minimum:
            out.append(Region(kind, ls[i].start, ls[j].end))
        i = j + 1
    return out


def _adjacent(a: _Line, b: _Line) -> bool:
    return a.next == b.start


def _attachments(ls: Sequence[_Line], length: int) -> list[Region]:
    out = []
    i = 0
    while i < len(ls):
        m = _ATTACH_OPEN.match(ls[i].text)
        if m is None:
            i += 1
            continue
        closing = re.compile(r"</" + re.escape(m.group(1)) + r"\s*>", re.I)
        j = i
        while j < len(ls) and not closing.search(ls[j].text, m.end() if j == i else 0):
            j += 1
        end = ls[j].end if j < len(ls) else length
        out.append(Region("attachment", ls[i].start + m.start(), end))
        i = j + 1
    return out


def _email(ls: Sequence[_Line], length: int) -> list[Region]:
    for i, line in enumerate(ls):
        headers = i + 1 < len(ls) and _EMAIL_HEADER.match(line.text) and _EMAIL_HEADER.match(ls[i + 1].text) and _adjacent(line, ls[i + 1])
        if headers or _EMAIL_DIVIDER.match(line.text) or _EMAIL_WROTE.match(line.text):
            return [Region("email", line.start, length)]  # an email body follows its header to the end
    return []


def _diffs(ls: Sequence[_Line]) -> list[Region]:
    out = []
    i = 0
    while i < len(ls):
        start = bool(_DIFF_START.match(ls[i].text)) or (i + 1 < len(ls) and bool(_DIFF_OLD.match(ls[i].text)) and bool(_DIFF_NEW.match(ls[i + 1].text)))
        if not start:
            i += 1
            continue
        j = i
        while j + 1 < len(ls) and _adjacent(ls[j], ls[j + 1]) and (ls[j + 1].blank or _DIFF_LINE.match(ls[j + 1].text) or _DIFF_START.match(ls[j + 1].text)):
            j += 1
        out.append(Region("diff", ls[i].start, ls[j].end))
        i = j + 1
    return out


def _tracebacks(ls: Sequence[_Line]) -> list[Region]:
    out = []
    i = 0
    while i < len(ls):
        if not _TRACEBACK.match(ls[i].text):
            i += 1
            continue
        j = i
        while j + 1 < len(ls) and _adjacent(ls[j], ls[j + 1]) and not ls[j + 1].blank:
            j += 1
            if _EXCEPTION.match(ls[j].text):
                break
        out.append(Region("pasted", ls[i].start, ls[j].end))
        i = j + 1
    return out


def _shell(ls: Sequence[_Line]) -> list[Region]:
    """A terminal transcript: a prompt line and the output lines that follow it, up to a blank line."""
    out = []
    i = 0
    while i < len(ls):
        if not _SHELL_PROMPT.match(ls[i].text):
            i += 1
            continue
        j = i
        while j + 1 < len(ls) and _adjacent(ls[j], ls[j + 1]) and not ls[j + 1].blank:
            j += 1
        out.append(Region("pasted", ls[i].start, ls[j].end))
        i = j + 1
    return out


def _indented(all_lines: Sequence[_Line], ls: Sequence[_Line]) -> list[Region]:
    """Markdown indented code: indented lines after a blank line (or at the start of the text)."""
    index = {line.start: k for k, line in enumerate(all_lines)}
    out = []
    i = 0
    while i < len(ls):
        k = index[ls[i].start]
        if not _INDENTED.match(ls[i].text) or (k > 0 and not all_lines[k - 1].blank):
            i += 1
            continue
        j = i
        while j + 1 < len(ls) and _adjacent(ls[j], ls[j + 1]) and (_INDENTED.match(ls[j + 1].text) or ls[j + 1].blank):
            j += 1
        while j > i and ls[j].blank:
            j -= 1
        out.append(Region("pasted", ls[i].start, ls[j].end))
        i = j + 1
    return out


__all__ = ["Region", "KINDS", "regions", "intersects", "lines"]
