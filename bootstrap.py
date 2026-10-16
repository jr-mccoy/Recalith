#!/usr/bin/env python3
"""Recalith release bootstrap: provision one project's pinned runtime.

    python bootstrap.py install --project PATH --wheel recalith-X-py3-none-any.whl \
        --expected-digest SHA256 --wheelhouse DIR
    python bootstrap.py status --project PATH

Standard library only, so it runs before any engine exists. It installs the
explicitly supplied engine wheel (verified against ``--expected-digest``) and its
hash-locked dependencies from a local wheelhouse into
``.recalith/runtime/<version>/venv`` with ``pip --no-index --require-hashes``:
nothing is ever downloaded, and hooks never call this script. Activation is a
single directory rename; a failed provisioning leaves no half-installed runtime.
The project's tracked ``engine.lock`` records the verified digest.

Exit codes: 0 success, 2 invalid input, 4 unavailable (missing wheel/wheelhouse
or unsupported Python), 5 storage failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

WHEEL_RE = re.compile(r"^recalith-(?P<version>[0-9][0-9A-Za-z.+!]*)-py3-none-any\.whl$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIREMENTS = Path(__file__).resolve().parent / "requirements.lock"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(code: int, message: str) -> int:
    print(f"bootstrap: {message}", file=sys.stderr)
    return code


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def python_supported(spec: str) -> bool:
    """Evaluate the lock's simple '>=X.Y,<A.B' requirement without packaging."""
    current = sys.version_info[:2]
    for part in spec.split(","):
        part = part.strip()
        match = re.fullmatch(r"(>=|<)(\d+)\.(\d+)", part)
        if not match:
            return False
        bound = (int(match.group(2)), int(match.group(3)))
        if match.group(1) == ">=" and current < bound:
            return False
        if match.group(1) == "<" and current >= bound:
            return False
    return True


def update_engine_lock(lock_path: Path, version: str, digest: str) -> None:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    contracts = data.get("contracts", {})
    lines = [
        "# Exact engine pin for this project (tracked). Written by the release bootstrap after",
        "# verifying the wheel digest.",
        "lock_schema = 1",
        f"engine_version = {json.dumps(version)}",
        'provisioning = "wheel"',
        f"artifact_sha256 = {json.dumps(digest)}",
        f"requires_python = {json.dumps(data.get('requires_python', '>=3.12,<3.15'))}",
        "",
        "[contracts]",
    ] + [f"{k} = {int(v)}" for k, v in contracts.items()]
    tmp = lock_path.with_name(lock_path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, lock_path)


def install(project: Path, wheel: Path, expected: str, wheelhouse: Path) -> int:
    base = project / ".recalith"
    if not (base / "project.toml").exists():
        return fail(2, "project has no .recalith/project.toml; run init from the bootstrapped runtime or the release init entry point")
    if not DIGEST_RE.match(expected):
        return fail(2, "--expected-digest must be a lowercase SHA-256 hex digest")
    match = WHEEL_RE.match(wheel.name)
    if not match:
        return fail(2, "wheel file name is not a recalith pure-Python wheel")
    if not wheel.is_file() or not wheelhouse.is_dir() or not REQUIREMENTS.is_file():
        return fail(4, "wheel, wheelhouse or requirements.lock is missing")
    actual = sha256(wheel)
    if actual != expected:
        return fail(2, "wheel digest does not match --expected-digest; refusing to install")
    lock = tomllib.loads((base / "engine.lock").read_text(encoding="utf-8")) if (base / "engine.lock").exists() else {}
    if not python_supported(lock.get("requires_python", ">=3.12,<3.15")):
        return fail(4, f"Python {sys.version.split()[0]} does not satisfy {lock.get('requires_python')}")
    version = match.group("version")
    target = base / "runtime" / version
    marker = target / "provisioned.json"
    if marker.exists():
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        if recorded.get("artifact_sha256") == actual:
            print(json.dumps({"status": "already_provisioned", "version": version}))
            return 0
        return fail(2, "a different artifact is already provisioned for this version; remove it explicitly first")
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{version}-", dir=base / "runtime"))
    try:
        venv = staging / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
        reqs = staging / "requirements.txt"
        reqs.write_text(REQUIREMENTS.read_text(encoding="utf-8") + f"recalith @ {wheel.resolve().as_uri()} --hash=sha256:{actual}\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PIP_", "PYTHON"))}
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        result = subprocess.run(
            [str(venv_python(venv)), "-m", "pip", "install", "--no-index", "--find-links", str(wheelhouse), "--require-hashes", "--no-deps", "--only-binary", ":all:", "-r", str(reqs)],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            return fail(4, "pip could not install the locked wheels from the local wheelhouse:\n" + result.stdout[-2000:] + result.stderr[-2000:])
        check = subprocess.run([str(venv_python(venv)), "-I", "-c", "import recalith, recalith.contracts; print(recalith.__version__)"], capture_output=True, text=True)
        if check.returncode != 0 or check.stdout.strip() != version:
            return fail(5, "provisioned runtime failed its import check")
        (staging / "provisioned.json").write_text(json.dumps({"version": version, "artifact_sha256": actual, "python": sys.version.split()[0]}) + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    except subprocess.CalledProcessError as exc:
        return fail(5, f"virtual environment creation failed: {exc}")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    update_engine_lock(base / "engine.lock", version, actual)
    print(json.dumps({"status": "provisioned", "version": version, "artifact_sha256": actual}))
    return 0


def status(project: Path) -> int:
    base = project / ".recalith"
    lock = tomllib.loads((base / "engine.lock").read_text(encoding="utf-8")) if (base / "engine.lock").exists() else {}
    version = lock.get("engine_version")
    marker = base / "runtime" / str(version) / "provisioned.json"
    state = {"engine_version": version, "provisioned": marker.exists(), "artifact_sha256": lock.get("artifact_sha256")}
    print(json.dumps(state))
    return 0 if marker.exists() else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_install = sub.add_parser("install")
    p_install.add_argument("--project", required=True, type=Path)
    p_install.add_argument("--wheel", required=True, type=Path)
    p_install.add_argument("--expected-digest", required=True)
    p_install.add_argument("--wheelhouse", required=True, type=Path)
    p_status = sub.add_parser("status")
    p_status.add_argument("--project", required=True, type=Path)
    ns = parser.parse_args(argv)
    project = ns.project.resolve()
    if ns.command == "install":
        return install(project, ns.wheel, ns.expected_digest, ns.wheelhouse)
    return status(project)


if __name__ == "__main__":
    sys.exit(main())
