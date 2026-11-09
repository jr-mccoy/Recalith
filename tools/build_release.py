#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build digested release artifacts with the repository's own process (ACCEPTANCE_TESTS §8; decision 0020).

    python tools/build_release.py --out DIR [--skip-build]

1. ``uv build --sdist --wheel`` (the build the CI provisioning step already uses).
2. ``bootstrap.py`` and ``requirements.lock`` are copied into ``--out`` (the
   bootstrap reads the lock beside itself), and every wheelhouse directory
   already in ``--out`` (``wheelhouse-<platform>-<python tag>/`` from
   ``tools/build_wheelhouse.py``, built on each platform) is verified against
   the lock. SHA-256 and size of every artifact, wheelhouse files included,
   go to ``SHA256SUMS`` and the release manifest; the provisioning inputs
   (``bootstrap.py``, ``requirements.lock``, ``uv.lock``) are digested
   alongside (audit 2026-11-06 REL-1).
3. **Shipped-code inventory**: every module under ``src/recalith`` is in the
   wheel, and the wheel holds nothing else but its ``.dist-info`` (no tests,
   evals, tools, probe output or private configuration); the sdist holds only
   what builds and installs the engine (no docs, evals, tests, tools, workflows
   or the design packet; decision 0047).
4. **Dependency and license inventory**: the runtime closure of
   ``requirements.lock`` (exact versions and hashes) with each package's
   declared license from its installed metadata, compared with the tracked
   ``docs/release/DEPENDENCIES.json``; any difference fails the build.
5. **Upstream notices**: no upstream source is adapted (SOURCES_AND_REUSE),
   so no ``THIRD_PARTY_NOTICES.md`` ships; a shipped file carrying a foreign
   copyright header fails the check.

Signing is **not** done: it needs operator signing material (a key or an
attestation identity) that this repository does not hold and must not
create. The manifest records ``signing: unsigned`` with that blocker. Nothing
is tagged, uploaded or published.

Exit 0 when the artifacts were built and every inventory check passed; 1
when a check failed; 4 when the build tool is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_wheelhouse  # noqa: E402

INVENTORY = ROOT / "docs" / "release" / "DEPENDENCIES.json"
PROVISIONING_FILES = ("bootstrap.py", "requirements.lock")
FOREIGN_COPYRIGHT = re.compile(r"Copyright(?![^\n]*Recalith)", re.I)  # a notice that does not name the project's own holder
SDIST_FORBIDDEN = ("docs/", "evals/", "review/", ".github/", "tests/", "tools/", "probe-private/", "MANIFEST.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_lock() -> dict[str, dict]:
    """``requirements.lock``: name -> {version, hashes} (the exact closure bootstrap installs)."""
    out: dict[str, dict] = {}
    current = None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if m:
            current = m.group(1).lower()
            out[current] = {"version": m.group(2), "hashes": []}
            continue
        h = re.search(r"--hash=sha256:([0-9a-f]{64})", line)
        if h and current:
            out[current]["hashes"].append(h.group(1))
    return out


def license_of(name: str) -> str | None:
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return None
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classifiers) or (meta.get("License") or "").strip() or None


def dependency_inventory() -> dict:
    lock = runtime_lock()
    return {
        "source": "requirements.lock (uv export --locked --no-dev --no-emit-project)",
        "packages": {name: {"version": spec["version"], "license": license_of(name), "hash_count": len(spec["hashes"])} for name, spec in sorted(lock.items())},
        "project": {"name": "recalith", "license": _project_license()},
        "upstream_adapted_source": "none (docs/SOURCES_AND_REUSE.md: no copied implementation modules; THIRD_PARTY_NOTICES.md not required)",
    }


def _project_license() -> str | None:
    """The SPDX expression of ``[project].license`` (PEP 639), or the legacy table's text or file."""
    value = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"].get("license")
    return value.get("text") or value.get("file") if isinstance(value, dict) else value


def wheel_inventory(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        texts = {n: zf.read(n) for n in names if n.endswith(".py")}
    expected = sorted(str(p.relative_to(ROOT / "src")).replace("\\", "/") for p in (ROOT / "src" / "recalith").rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    shipped = sorted(n for n in names if not n.split("/")[0].endswith(".dist-info"))
    foreign = sorted(n for n, data in texts.items() if FOREIGN_COPYRIGHT.search(data.decode("utf-8", "replace")))
    return {
        "files": len(names), "modules_missing_from_wheel": sorted(set(expected) - set(shipped)), "unexpected_files": sorted(set(shipped) - set(expected)),
        "foreign_copyright_headers": foreign, "dist_info": sorted({n.split("/")[0] for n in names if n.split("/")[0].endswith(".dist-info")}),
    }


def wheelhouses(out: Path, lock_text: str) -> dict[str, dict]:
    """Every ``wheelhouse-*`` directory in ``out``: its manifest's platform and tag, and the lock check re-run here."""
    found: dict[str, dict] = {}
    for directory in sorted(p for p in out.glob("wheelhouse-*") if p.is_dir()):
        manifest_path = directory / build_wheelhouse.MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found[directory.name] = {"problems": ["wheelhouse manifest missing or unreadable"]}
            continue
        problems, wheels = build_wheelhouse.check(directory, lock_text)
        if manifest.get("requirements_lock_sha256") != hashlib.sha256(lock_text.encode("utf-8")).hexdigest():
            problems.append("wheelhouse was built from another requirements.lock")
        if build_wheelhouse.wheelhouse_name(str(manifest.get("platform")), str(manifest.get("python_tag"))) != directory.name:
            problems.append("wheelhouse directory name does not match its manifest")
        found[directory.name] = {"platform": manifest.get("platform"), "python_tag": manifest.get("python_tag"), "wheels": len(wheels), "problems": problems}
    return found


def sdist_inventory(sdist: Path) -> dict:
    """The source distribution's members, and any that belong to the repository rather than the engine (REL-2)."""
    import tarfile

    with tarfile.open(sdist) as tf:
        names = [m.name.split("/", 1)[1] for m in tf.getmembers() if m.isfile() and "/" in m.name]
    stray = sorted(n for n in names if any(n == p.rstrip("/") or n.startswith(p) for p in SDIST_FORBIDDEN))
    texts = []
    with tarfile.open(sdist) as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith(".py"):
                texts.append((m.name, tf.extractfile(m).read().decode("utf-8", "replace")))
    foreign = sorted(n for n, text in texts if FOREIGN_COPYRIGHT.search(text))
    return {"files": len(names), "repository_files_in_sdist": stray, "foreign_copyright_headers": foreign}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-build", action="store_true", help="digest and check artifacts already in --out")
    parser.add_argument("--write-inventory", action="store_true", help="rewrite docs/release/DEPENDENCIES.json from the current lock (review the diff)")
    ns = parser.parse_args(argv)
    out = ns.out
    out.mkdir(parents=True, exist_ok=True)
    if not ns.skip_build:
        uv = shutil.which("uv")
        if uv is None:
            print("error: uv is not installed (the repository's build uses `uv build`)", file=sys.stderr)
            return 4
        proc = subprocess.run([uv, "build", "--sdist", "--wheel", "-o", str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
        if proc.returncode != 0:
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
    wheels = sorted(out.glob("recalith-*.whl"))
    sdists = sorted(out.glob("recalith-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"error: expected one wheel and one sdist in {out}, found {len(wheels)} and {len(sdists)}", file=sys.stderr)
        return 1
    inventory = dependency_inventory()
    if ns.write_inventory:
        INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        INVENTORY.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tracked = json.loads(INVENTORY.read_text(encoding="utf-8")) if INVENTORY.exists() else None
    wheel = wheel_inventory(wheels[0])
    sdist = sdist_inventory(sdists[0])
    problems = []
    if sdist["repository_files_in_sdist"]:
        problems.append("sdist_carries_repository_files")
    if sdist["foreign_copyright_headers"]:
        problems.append("foreign_copyright_without_notice")
    if tracked != inventory:
        problems.append("dependency_inventory_differs_from_docs/release/DEPENDENCIES.json")
    if any(p["license"] is None for p in inventory["packages"].values()):
        problems.append("dependency_license_unknown")
    if wheel["modules_missing_from_wheel"] or wheel["unexpected_files"]:
        problems.append("wheel_contents_differ_from_src")
    if wheel["foreign_copyright_headers"] and "foreign_copyright_without_notice" not in problems:
        problems.append("foreign_copyright_without_notice")
    for name in PROVISIONING_FILES:  # the bootstrap and the lock it reads beside itself travel with the wheel (REL-1)
        shutil.copyfile(ROOT / name, out / name)
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    houses = wheelhouses(out, lock_text)
    for name, house in houses.items():
        problems += [f"wheelhouse_{name}:{p}" for p in house["problems"]]
    artifacts = {}
    for path in [*wheels, *sdists, *(out / name for name in PROVISIONING_FILES)]:
        artifacts[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    for name in houses:
        for path in sorted(p for p in (out / name).iterdir() if p.is_file()):
            artifacts[f"{name}/{path.name}"] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    inputs = {name: sha256(ROOT / name) for name in ("bootstrap.py", "requirements.lock", "uv.lock", "pyproject.toml")}
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", check=False).stdout.strip() or None
    version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    manifest = {
        "release_manifest_schema": 1, "name": "recalith", "version": version, "profile": "claude_preview", "commit": commit,
        "artifacts": artifacts, "provisioning_inputs": inputs, "wheelhouses": houses, "dependency_inventory": inventory, "wheel_inventory": wheel, "sdist_inventory": sdist, "problems": problems,
        "layout": "the wheel, the sdist, bootstrap.py, requirements.lock, one wheelhouse-<platform>-<python tag>/ per supported platform and Python version, SHA256SUMS and this manifest",
        "signing": {"state": "unsigned", "blocker": "signing needs operator material (a signing key or an attestation identity the owner selects); none is created by the build"},
        "publication": "none: nothing is tagged, uploaded or published by this tool",
        "readiness_note": "a built artifact is not a readiness claim: claude_preview is ready only when docs/release/claude_preview_checklist.json says so",
    }
    (out / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{a['sha256']}  {name}\n" for name, a in sorted(artifacts.items())), encoding="utf-8")
    print(json.dumps({"artifacts": sorted(artifacts), "wheelhouses": sorted(houses), "problems": problems, "signing": manifest["signing"]["state"]}, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
