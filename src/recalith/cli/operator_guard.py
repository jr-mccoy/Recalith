"""The operator command guard (SYSTEM_SPEC §13.1; DATA_CONTRACTS §1.1, §12; decision 0014).

It runs in the CLI process **before any actor is assigned**, on the
*original caller*: the environment the process was started with and its own
standard input. It never clears a marker, never synthesizes a terminal, has
no bypass switch, and never calls the worker/curator environment builder
(``fast.process_env.spawn_environment``), which exists only to build a child
role's environment after authority is settled.

Decision order for an administrative form:

1. **Markers.** Any registered host marker (``CLAUDECODE``,
   ``CLAUDE_CODE_CHILD_SESSION``) or engine role marker
   (``RECALITH_WORKER_INSTALLATION``, ``RECALITH_CURATOR_INSTALLATION``) is a
   refusal, whatever the TTY or token. The refusal names only the marker
   category and explains the external-terminal route.
2. **Token file shape.** A supplied ``--operator-token-file`` must be a
   regular file (no link), owned by the caller with no group/other access
   (POSIX), at most 4 KiB and a strict ``OperatorTokenFile``. Anything else is
   a refusal (exit 6), never "invalid input", and never falls back to the TTY.
3. **TTY or token.** Token create/revoke need the interactive controlling
   terminal (a token never substitutes). First init and existing-install
   forms accept the terminal or a token; for an existing installation a
   supplied token must match an active, unrevoked verifier in its
   ``local.toml``.

Interactive means: POSIX — standard input is a terminal *and* the process has
a controlling terminal (``/dev/tty`` opens); Windows — standard input is a
console input handle (``GetConsoleMode`` succeeds; ``isatty`` alone is true
for ``NUL`` and is not used). These are same-user friction controls, not
authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from dataclasses import dataclass
from typing import Mapping

from pydantic import ValidationError

from recalith.contracts.common import Actor, new_id, utc_now
from recalith.contracts.privacy import OPERATOR_TOKEN_MAX_BYTES, OperatorTokenFile
from recalith.fast.process_env import CURATOR_MARKER, HOST_MARKERS, WORKER_MARKER

MARKER_CATEGORIES = tuple((name, "host_marker") for name in HOST_MARKERS) + ((WORKER_MARKER, "worker_marker"), (CURATOR_MARKER, "curator_marker"))
VERIFIER_SCHEME = "v1"
_VERIFIER_DOMAIN = b"recalith-operator-token-v1\x00"

IDE_ROUTE = (
    "Administrative commands are refused inside a host-agent process tree, even with a terminal and an operator token. "
    "Run this command from an ordinary OS terminal launched outside the host agent (not an IDE terminal that inherits its marker), "
    "using the project launcher .recalith/bin/recalith (or recalith.cmd); for noninteractive automation, pass a provisioned --operator-token-file. "
    "There is no override and the marker is never cleared for you."
)
NONINTERACTIVE_ROUTE = (
    "This administrative command needs an interactive terminal or a valid --operator-token-file. "
    "Run it from an ordinary OS terminal, or give automation a token file provisioned by `recalith operator-token create` at a terminal."
)


class GuardRefusal(Exception):
    """The caller is not authorized for an administrative form (exit 6 ``policy_refused``)."""

    def __init__(self, reason: str, category: str, guidance: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.category = category
        self.guidance = guidance


# --------------------------------------------------------------------------
# The original caller


def marker_category(environ: Mapping[str, str], *, platform: str = os.name) -> str | None:
    """The first registered marker category present in the caller's environment (any value counts)."""
    names = {k.upper(): k for k in environ} if platform == "nt" else {k: k for k in environ}
    for name, category in MARKER_CATEGORIES:
        if (name.upper() if platform == "nt" else name) in names:
            return category
    return None


def interactive_terminal(fd: int = 0) -> bool:
    """True only for an interactive controlling terminal on standard input (see the module docstring)."""
    if os.name == "nt":  # pragma: no cover - native Windows
        return _windows_console(fd)
    try:
        if not os.isatty(fd):
            return False
    except OSError:
        return False
    try:
        tty = os.open("/dev/tty", os.O_RDWR | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return False  # no controlling terminal (a detached or agent-launched process)
    os.close(tty)
    return True


def _windows_console(fd: int) -> bool:  # pragma: no cover - native Windows
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    mode = wintypes.DWORD()
    return bool(kernel32.GetConsoleMode(wintypes.HANDLE(handle), ctypes.byref(mode)))


# --------------------------------------------------------------------------
# Token files


def load_token_file(path: str | os.PathLike[str]) -> OperatorTokenFile:
    """Read a supplied token file under the shape/ownership rules; a GuardRefusal names only the failed rule."""
    def refuse(reason: str) -> GuardRefusal:
        return GuardRefusal(reason, "token_refused", "The supplied operator token file was refused; a refused token never falls back to terminal authorization.")

    try:
        before = os.lstat(path)
    except OSError:
        raise refuse("token_unreadable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise refuse("token_not_regular_file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise refuse("token_unreadable") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) != (before.st_dev, before.st_ino):
            raise refuse("token_not_regular_file")
        if st.st_size > OPERATOR_TOKEN_MAX_BYTES:
            raise refuse("token_oversized")
        if os.name != "nt":
            if st.st_uid != os.geteuid():
                raise refuse("token_owner_mismatch")
            if st.st_mode & 0o077:
                raise refuse("token_permissions_too_open")
        raw = os.read(fd, OPERATOR_TOKEN_MAX_BYTES + 1)
    finally:
        os.close(fd)
    try:
        return OperatorTokenFile.parse_file_bytes(raw)
    except (ValueError, ValidationError):
        raise refuse("token_malformed") from None  # never echo the file's content


def create_token_file(path: str | os.PathLike[str]) -> OperatorTokenFile:
    """A new standalone private token file (exclusive create, 0600); never overwrites anything."""
    token = OperatorTokenFile.model_validate({"schema": 1, "token_id": new_id("tok"), "secret": secrets.token_urlsafe(32), "created_at": utc_now()})
    data = json.dumps({"schema": 1, "token_id": token.token_id, "secret": token.secret, "created_at": token.created_at}).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise GuardRefusal("token_output_exists", "token_output", "The token output path already exists; a token file is never overwritten.") from None
    except OSError:
        raise GuardRefusal("token_output_unwritable", "token_output", "The token output path cannot be created.") from None
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return token


def make_verifier(token: OperatorTokenFile) -> str:
    """A salted one-way verifier of the token secret (the secret is never stored)."""
    salt = secrets.token_bytes(16)
    return f"{VERIFIER_SCHEME}:{salt.hex()}:{_digest(token, salt)}"


def _digest(token: OperatorTokenFile, salt: bytes) -> str:
    return hashlib.sha256(_VERIFIER_DOMAIN + token.token_id.encode("ascii") + b"\x00" + salt + b"\x00" + token.secret.encode("utf-8")).hexdigest()


def verifier_matches(stored: str, token: OperatorTokenFile) -> bool:
    try:
        scheme, salt_hex, digest = stored.split(":")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    return scheme == VERIFIER_SCHEME and hmac.compare_digest(digest, _digest(token, salt))


# --------------------------------------------------------------------------
# Decisions


@dataclass(frozen=True)
class Caller:
    """What the guard observed about the original caller (no secret material)."""

    interactive: bool
    token: OperatorTokenFile | None


def check_caller(environ: Mapping[str, str], *, token_path: str | None, interactive: bool, terminal_only: bool = False) -> Caller:
    """Steps 1–3 of the module docstring that need no installation (raises :class:`GuardRefusal`)."""
    category = marker_category(environ)
    if category is not None:
        raise GuardRefusal(f"{category}_present", category, IDE_ROUTE)
    token = load_token_file(token_path) if token_path is not None else None
    if terminal_only and not interactive:
        raise GuardRefusal("terminal_required", "unmarked_noninteractive", NONINTERACTIVE_ROUTE + " Token creation and revocation always need the terminal.")
    if not interactive and token is None:
        raise GuardRefusal("terminal_or_token_required", "unmarked_noninteractive", NONINTERACTIVE_ROUTE)
    return Caller(interactive=interactive, token=token)


def check_installed_token(caller: Caller, verifiers: Mapping[str, str], revoked: Mapping[str, str]) -> None:
    """For an existing installation: a supplied token must match an active local verifier."""
    token = caller.token
    if token is None:
        return
    if token.token_id in revoked:
        raise GuardRefusal("token_revoked", "token_refused", "This operator token was revoked for this installation.")
    stored = verifiers.get(token.token_id)
    if stored is None or not verifier_matches(stored, token):
        raise GuardRefusal("token_not_recognized", "token_refused", "The operator token does not match an active verifier of this installation.")


def operator_actor(caller: Caller) -> Actor:
    """Assigned only after every check above passed (DATA_CONTRACTS §1.1)."""
    return Actor(kind="operator", id=caller.token.token_id if caller.token is not None else "terminal", channel="cli")

