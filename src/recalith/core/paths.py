"""Registered path boundaries (SYSTEM_SPEC §13, A33).

The engine may touch only its installation root and explicitly registered
workspace roots. Authorization resolves symlinks and Windows junctions, then
proves containment by *file identity* (device + inode via ``samefile``) of an
existing ancestor, so case-insensitive filesystems, Unicode normalization and
alias paths are handled without lowercasing paths. Boundary escapes are refused
before any target content is read.

Standard library only.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from recalith.errors import RecalithError


def canonical(path: Path | str) -> Path:
    """Absolute path with symlinks/junctions resolved where they exist."""
    p = Path(path)
    if "\x00" in str(p):
        raise RecalithError("policy_refused", "path contains a NUL byte")
    return Path(os.path.realpath(p.expanduser().absolute()))


def same_location(a: Path | str, b: Path | str) -> bool:
    """True when two existing paths name the same filesystem object."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def root_identity(path: Path | str) -> str:
    """Stable identity of an existing directory on this machine (device:inode)."""
    st = os.stat(path)
    return f"{st.st_dev}:{st.st_ino}"


def _contained(target: Path, root: Path) -> bool:
    # Walk existing ancestors of the canonical target; containment holds when
    # one of them is the same filesystem object as the canonical root.
    for candidate in (target, *target.parents):
        if candidate.exists() and same_location(candidate, root):
            return True
        if candidate == root:
            return True
    return False


class PathPolicy:
    """Authorization against the explicitly registered roots of one installation."""

    def __init__(self, roots: Iterable[Path | str]) -> None:
        self.roots = [canonical(r) for r in roots]
        if not self.roots:
            raise ValueError("at least one registered root is required")

    def authorize(self, path: Path | str, *, base: Path | str | None = None) -> Path:
        """Return the canonical path if it lies inside a registered root.

        Relative paths are interpreted against ``base`` (default: the first
        registered root). Traversal, absolute escapes, symlink/junction escapes
        and NUL bytes raise ``policy_refused`` without reading the target.
        """
        raw = str(path)
        if "\x00" in raw:
            raise RecalithError("policy_refused", "path contains a NUL byte")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(base if base is not None else self.roots[0]) / p
        target = canonical(p)
        for root in self.roots:
            if _contained(target, root):
                return target
        raise RecalithError("policy_refused", "path is outside the registered roots")

    def relative(self, path: Path | str) -> str:
        """Normalized portable POSIX path relative to the registered root."""
        target = self.authorize(path)
        for root in self.roots:
            try:
                rel = target.relative_to(root)
            except ValueError:
                # Equivalent root reached through another spelling (case, alias).
                for parent in (target, *target.parents):
                    if parent.exists() and same_location(parent, root):
                        rel = target.relative_to(parent)
                        break
                else:
                    continue
            text = PurePosixPath(*rel.parts).as_posix()
            return "." if text in ("", ".") else text
        raise RecalithError("policy_refused", "path is outside the registered roots")

    def open_read(self, path: Path | str) -> BinaryIO:
        """Open an authorized regular file, refusing a symlink swapped in after the check."""
        target = self.authorize(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(target, flags)
        except OSError as exc:
            raise RecalithError("policy_refused", "path could not be opened safely") from exc
        try:
            opened = os.fstat(fd)
            current = os.stat(target, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise RecalithError("policy_refused", "path changed after authorization")
            # Re-prove containment for the object actually opened.
            self.authorize(target)
        except BaseException:
            os.close(fd)
            raise
        return os.fdopen(fd, "rb")


def is_case_insensitive(directory: Path | str) -> bool:
    """Probe whether ``directory``'s filesystem treats names case-insensitively."""
    probe = Path(directory) / ".recalith-case-probe"
    probe.write_bytes(b"")
    try:
        return Path(directory, ".RECALITH-CASE-PROBE").exists()
    finally:
        probe.unlink()


def private_mkdir(path: Path) -> None:
    """Create a directory (and parents) with owner-only permissions where supported."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
