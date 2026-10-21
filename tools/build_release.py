#!/usr/bin/env python3
"""Build digested release artifacts with the repository's own process (ACCEPTANCE_TESTS §8; decision 0020).

    python tools/build_release.py --out DIR [--skip-build]

1. ``uv build --sdist --wheel`` (the build the CI provisioning step already uses).
2. SHA-256 and size of every artifact, written to ``SHA256SUMS`` and the
   release manifest; the provisioning inputs (``bootstrap.py``,
   ``requirements.lock``, ``uv.lock``) are digested alongside.
3. **Shipped-code inventory**: every module under ``src/recalith`` is in the
   wheel, and the wheel holds nothing else but its ``.dist-info`` (no tests,
   evals, tools, probe output or private configuration).
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
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "release" / "DEPENDENCIES.json"
FOREIGN_COPYRIGHT = re.compile(r"Copyright \(c\)|Copyright 20\d\d (?!Recalith)", re.I)


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
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^license\s*=\s*(.+)$', text, re.M)
    return m.group(1).strip() if m else None


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
    problems = []
    if tracked != inventory:
        problems.append("dependency_inventory_differs_from_docs/release/DEPENDENCIES.json")
    if any(p["license"] is None for p in inventory["packages"].values()):
        problems.append("dependency_license_unknown")
    if wheel["modules_missing_from_wheel"] or wheel["unexpected_files"]:
        problems.append("wheel_contents_differ_from_src")
    if wheel["foreign_copyright_headers"]:
        problems.append("foreign_copyright_without_notice")
    artifacts = {}
    for path in [*wheels, *sdists]:
        artifacts[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    inputs = {name: sha256(ROOT / name) for name in ("bootstrap.py", "requirements.lock", "uv.lock", "pyproject.toml")}
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", check=False).stdout.strip() or None
    version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    manifest = {
        "release_manifest_schema": 1, "name": "recalith", "version": version, "profile": "claude_preview", "commit": commit,
        "artifacts": artifacts, "provisioning_inputs": inputs, "dependency_inventory": inventory, "wheel_inventory": wheel, "problems": problems,
        "signing": {"state": "unsigned", "blocker": "signing needs operator material (a signing key or an attestation identity the owner selects); none is created by the build"},
        "publication": "none: nothing is tagged, uploaded or published by this tool",
        "readiness_note": "a built artifact is not a readiness claim: claude_preview stays blocked until the live gate passes (B1)",
    }
    (out / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{a['sha256']}  {name}\n" for name, a in sorted(artifacts.items())), encoding="utf-8")
    print(json.dumps({"artifacts": artifacts, "problems": problems, "signing": manifest["signing"]["state"]}, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
