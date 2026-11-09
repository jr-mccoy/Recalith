# SPDX-License-Identifier: GPL-3.0-only
"""The release layout tools (audit 2026-11-06 REL-1, decision 0046): a wheelhouse is checked against the lock and named
for its platform and Python; the release copies the bootstrap and the lock and verifies every wheelhouse it ships."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools")]

import build_release  # noqa: E402
import build_wheelhouse  # noqa: E402

LOCK = (ROOT / "requirements.lock").read_text(encoding="utf-8")


def _fake_wheelhouse(target: Path, *, platform: str = "linux-x86_64", tag: str = "cp313", lock_text: str = LOCK) -> dict[str, str]:
    """A wheelhouse of stand-in wheels whose digests are patched into a lock copy (the tool only compares digests)."""
    target.mkdir(parents=True)
    wheels = {}
    patched = lock_text
    for name, hashes in build_wheelhouse.locked_hashes(lock_text).items():
        path = target / f"{name.replace('-', '_')}-0-py3-none-any.whl"
        path.write_bytes(f"wheel {name}".encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        patched = patched.replace(next(iter(sorted(hashes))), digest, 1)
        wheels[path.name] = digest
    (target / build_wheelhouse.MANIFEST).write_text(json.dumps({
        "wheelhouse_schema": 1, "platform": platform, "python_tag": tag, "requirements_lock_sha256": hashlib.sha256(patched.encode("utf-8")).hexdigest(), "wheels": wheels, "problems": [],
    }), encoding="utf-8")
    (target / "lock.patched").write_text(patched, encoding="utf-8")
    return wheels


def test_wheelhouse_check_wants_every_locked_wheel_once_with_a_locked_digest(tmp_path):
    house = tmp_path / "wheelhouse-linux-x86_64-cp313"
    wheels = _fake_wheelhouse(house)
    patched = (house / "lock.patched").read_text(encoding="utf-8")
    assert build_wheelhouse.check(house, patched) == ([], wheels)
    (house / "pydantic_core-0-py3-none-any.whl").write_bytes(b"tampered")
    problems, _ = build_wheelhouse.check(house, patched)
    assert sorted(problems) == ["digest of pydantic_core-0-py3-none-any.whl is not in requirements.lock", "no wheel for pydantic-core"]  # a tampered wheel counts for nothing
    (house / "pydantic_core-0-py3-none-any.whl").unlink()
    (house / "requests-0-py3-none-any.whl").write_bytes(b"stranger")
    problems, _ = build_wheelhouse.check(house, patched)
    assert sorted(problems) == ["no wheel for pydantic-core", "unexpected wheel requests-0-py3-none-any.whl"]


def test_wheelhouse_is_named_for_its_platform_and_python_and_never_mixed(tmp_path, monkeypatch):
    assert build_wheelhouse.wheelhouse_name("win-amd64", "cp313") == "wheelhouse-win-amd64-cp313"
    monkeypatch.setattr(build_wheelhouse, "interpreter_tags", lambda python: ("linux-x86_64", "cp313"))
    _fake_wheelhouse(tmp_path / "wheelhouse-linux-x86_64-cp313", platform="win-amd64")  # a manifest for another platform in the way
    assert build_wheelhouse.main(["--out", str(tmp_path)]) == 2
    stray = tmp_path / "other" / "wheelhouse-linux-x86_64-cp313"
    stray.mkdir(parents=True)
    (stray / "something.whl").write_bytes(b"x")
    assert build_wheelhouse.main(["--out", str(tmp_path / "other")]) == 2  # a directory without a manifest is not adopted


def test_release_verifies_each_shipped_wheelhouse_against_the_lock(tmp_path, monkeypatch):
    good = tmp_path / "wheelhouse-linux-x86_64-cp313"
    _fake_wheelhouse(good)
    patched = (good / "lock.patched").read_text(encoding="utf-8")
    houses = build_release.wheelhouses(tmp_path, patched)
    assert houses["wheelhouse-linux-x86_64-cp313"]["problems"] == [] and houses["wheelhouse-linux-x86_64-cp313"]["wheels"] == 6
    stale = build_release.wheelhouses(tmp_path, LOCK)  # built from another lock: every digest differs and the lock digest too
    assert "wheelhouse was built from another requirements.lock" in stale["wheelhouse-linux-x86_64-cp313"]["problems"]
    misnamed = tmp_path / "wheelhouse-win-amd64-cp312"
    shutil.copytree(good, misnamed)
    assert "wheelhouse directory name does not match its manifest" in build_release.wheelhouses(tmp_path, patched)["wheelhouse-win-amd64-cp312"]["problems"]


def test_release_layout_carries_the_bootstrap_and_the_lock(tmp_path, monkeypatch):
    """``--skip-build`` over a wheel and sdist copies bootstrap.py and requirements.lock beside them and digests all four."""
    (tmp_path / "recalith-0-py3-none-any.whl").write_bytes(b"wheel")
    _sdist(tmp_path / "recalith-0.tar.gz", {"recalith-0/src/recalith/__init__.py": "# SPDX-License-Identifier: GPL-3.0-only\n", "recalith-0/README.md": "r"})
    monkeypatch.setattr(build_release, "wheel_inventory", lambda wheel: {"files": 0, "modules_missing_from_wheel": [], "unexpected_files": [], "foreign_copyright_headers": [], "dist_info": []})
    monkeypatch.setattr(build_release, "dependency_inventory", lambda: json.loads(build_release.INVENTORY.read_text(encoding="utf-8")))
    assert build_release.main(["--out", str(tmp_path), "--skip-build"]) == 0
    sums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")
    for name in build_release.PROVISIONING_FILES:
        assert (tmp_path / name).read_bytes() == (ROOT / name).read_bytes() and f"  {name}\n" in sums
    manifest = json.loads((tmp_path / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["artifacts"]) == {"recalith-0-py3-none-any.whl", "recalith-0.tar.gz", "bootstrap.py", "requirements.lock"} and manifest["wheelhouses"] == {}
    assert manifest["sdist_inventory"] == {"files": 2, "repository_files_in_sdist": [], "foreign_copyright_headers": []}


def _sdist(path: Path, members: dict[str, str]) -> None:
    import io
    import tarfile

    with tarfile.open(path, "w:gz") as tf:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_sdist_inventory_names_repository_files_and_foreign_notices(tmp_path):
    """Audit 2026-11-06 REL-2, REL-8: the sdist holds what builds the engine; a notice that is not the project's own is flagged."""
    sdist = tmp_path / "recalith-0.tar.gz"
    _sdist(sdist, {
        "recalith-0/src/recalith/a.py": "# SPDX-License-Identifier: GPL-3.0-only\n# Copyright (C) 2026 Recalith contributors\n",
        "recalith-0/src/recalith/b.py": "# Copyright (c) 2019 Somebody Else\n",
        "recalith-0/docs/BUILD_PROGRESS.md": "x", "recalith-0/review/ROUND_1.md": "x", "recalith-0/tests/unit/test_x.py": "x", "recalith-0/MANIFEST.json": "{}",
    })
    inventory = build_release.sdist_inventory(sdist)
    assert inventory["repository_files_in_sdist"] == ["MANIFEST.json", "docs/BUILD_PROGRESS.md", "review/ROUND_1.md", "tests/unit/test_x.py"]
    assert inventory["foreign_copyright_headers"] == ["recalith-0/src/recalith/b.py"]


def test_every_health_reason_code_has_a_meaning():
    """Audit 2026-11-06 REL-10: the human status explains every code health can flag (the OPERATIONS §2 table as code)."""
    import re

    from recalith.operations import health, reasons

    source = (ROOT / "src" / "recalith" / "operations" / "health.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'flag\("(?:degraded|unavailable)", "([a-z_]+)"', source)) | set(health.SCHEMA_REASON.values())
    codes |= {"provider_not_configured", "selected_auth_missing", "request_capture_only", "route_uncertified", "not_autonomous_ready", "worker_crashed"}
    missing = sorted(c for c in codes if reasons.explain(c)[0] == "no description registered for this code")
    assert missing == [], missing
    assert reasons.explain("budget_exhausted:ordinary.invocations")[1].startswith("nothing")  # prefixed codes use their prefix
    assert reasons.explain("certification_failed:output_cap")[1] == reasons.RECERTIFY
