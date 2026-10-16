"""A33: traversal, symlink/junction swap, case variation, Unicode and spaces.

Case-insensitive coverage is claimed only on a filesystem that actually is
case-insensitive (native Windows/NTFS, default macOS APFS, or a provisioned
Linux casefold directory); on a case-sensitive filesystem that test is skipped
with an explicit reason rather than reported as passing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from recalith.core.paths import PathPolicy, canonical, is_case_insensitive, root_identity, same_location
from recalith.errors import RecalithError


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "work space é"
    (root / "src" / "naïve dir").mkdir(parents=True)
    (root / "src" / "naïve dir" / "file name ü.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    return root, outside


def symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable here ({type(exc).__name__}); coverage gap reported, not passed")


def refused(policy: PathPolicy, path) -> None:
    with pytest.raises(RecalithError) as info:
        policy.authorize(path)
    assert info.value.code == "policy_refused"


def test_unicode_and_spaces_are_authorized(tree):
    root, _ = tree
    policy = PathPolicy([root])
    target = policy.authorize("src/naïve dir/file name ü.txt")
    assert target.read_text(encoding="utf-8") == "inside"
    assert policy.relative(target) == "src/naïve dir/file name ü.txt"
    assert policy.relative(root) == "."


def test_traversal_and_absolute_escapes_are_refused(tree):
    root, outside = tree
    policy = PathPolicy([root])
    for bad in ("../outside/secret.txt", "src/../../outside/secret.txt", str(outside / "secret.txt"), "src/\x00x"):
        refused(policy, bad)


def test_symlink_escape_is_refused(tree):
    root, outside = tree
    symlink_or_skip(root / "escape", outside, directory=True)
    policy = PathPolicy([root])
    refused(policy, "escape/secret.txt")
    symlink_or_skip(root / "inner", root / "src", directory=True)
    assert policy.authorize("inner/naïve dir/file name ü.txt").read_text(encoding="utf-8") == "inside"


def test_symlink_swapped_in_after_authorization_is_refused(tree):
    root, outside = tree
    policy = PathPolicy([root])
    target = root / "src" / "data.txt"
    target.write_text("ok", encoding="utf-8")
    with policy.open_read("src/data.txt") as fh:
        assert fh.read() == b"ok"
    authorized = policy.authorize("src/data.txt")
    target.unlink()
    symlink_or_skip(target, outside / "secret.txt", directory=False)
    with pytest.raises(RecalithError, match="policy_refused"):
        policy.open_read(authorized)


def test_equivalent_root_spellings_share_identity(tree):
    root, _ = tree
    assert same_location(root, canonical(str(root) + os.sep + "src" + os.sep + ".."))
    assert root_identity(root) == root_identity(canonical(root))


def test_case_variation_on_case_insensitive_filesystem(tree):
    root, _ = tree
    if not is_case_insensitive(root):
        pytest.skip("filesystem is case-sensitive; case-insensitive coverage is NOT claimed on this platform")
    policy = PathPolicy([root])
    variant = Path(str(root).upper()) if sys.platform != "win32" else Path(str(root).swapcase())
    assert policy.authorize(variant / "SRC" / "naïve dir" / "file name ü.txt").read_text(encoding="utf-8") == "inside"
    assert policy.relative(variant / "src") in ("src", "SRC")


def test_case_variation_on_case_sensitive_filesystem_is_a_different_path(tree):
    root, _ = tree
    if is_case_insensitive(root):
        pytest.skip("filesystem is case-insensitive")
    policy = PathPolicy([root])
    # A differently-cased sibling outside the registered root is not the root.
    upper = root.parent / root.name.upper()
    upper.mkdir()
    refused(policy, upper)


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions exist only on native Windows")
def test_windows_junction_escape_is_refused(tree):  # pragma: no cover - native Windows runner
    root, outside = tree
    junction = root / "junction"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    if created.returncode != 0:
        pytest.skip("could not create a junction on this runner")
    refused(PathPolicy([root]), "junction/secret.txt")
