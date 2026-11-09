#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Recalith release bootstrap: provision one project's pinned runtime, and run the first commands on it.

    python bootstrap.py install --project PATH --wheel recalith-X-py3-none-any.whl \\
        --expected-digest SHA256 --wheelhouse DIR
    python bootstrap.py init --project PATH --profile coding|general --release-profile claude_preview \\
        --wheel WHEEL --expected-digest SHA256 --wheelhouse DIR [--operator-token-file FILE] [--json]
    python bootstrap.py operator-token create --project PATH --output FILE \\
        --wheel WHEEL --expected-digest SHA256 --wheelhouse DIR [--json]
    python bootstrap.py status --project PATH

Standard library only, so it runs before any engine exists. ``install``
installs the explicitly supplied engine wheel (verified against
``--expected-digest``) and its hash-locked dependencies from a local wheelhouse
into ``.recalith/runtime/<version>/venv`` with ``pip --no-index
--require-hashes``: nothing is ever downloaded, and hooks never call this
script. Activation is a single directory rename; a failed provisioning leaves
no half-installed runtime. The project's tracked ``engine.lock`` records the
verified digest. A project that has no ``.recalith/project.toml`` yet (a new
project) and a fresh clone of an initialized one (tracked files, no runtime)
are both provisioned the same way.

``init`` and ``operator-token create`` are the pre-init forms of SYSTEM_SPEC
§13.1: they provision the runtime when it is not there yet, then run exactly
that form of the ``recalith`` CLI on the provisioned interpreter (``python -I
-m recalith --project PATH …``), with this terminal's standard input, so the
operator guard sees the same caller. Their exit code is the CLI's.

Exit codes: 0 success, 2 invalid input, 4 unavailable (missing wheel,
wheelhouse or requirements.lock, or unsupported Python), 5 storage failure
(a file or directory could not be created, read or replaced).
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
DEFAULT_REQUIRES_PYTHON = ">=3.12,<3.15"
MARKER = "provisioned.json"


class BootstrapError(Exception):
    """A refusal with its exit code; the message names the input or state, never a traceback."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def private_mkdir(path: Path) -> None:
    """Create ``path`` (and parents) owner-only where modes exist; an existing directory keeps its contents."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)


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
        f"requires_python = {json.dumps(data.get('requires_python', DEFAULT_REQUIRES_PYTHON))}",
        "",
        "[contracts]",
    ] + [f"{k} = {int(v)}" for k, v in contracts.items()]
    tmp = lock_path.with_name(lock_path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, lock_path)


def check_inputs(wheel: Path, expected: str, wheelhouse: Path) -> tuple[str, str]:
    """``(version, digest)`` of a wheel that exists, is named as a recalith wheel and matches ``--expected-digest``."""
    if not DIGEST_RE.match(expected):
        raise BootstrapError(2, "--expected-digest must be a lowercase SHA-256 hex digest")
    match = WHEEL_RE.match(wheel.name)
    if not match:
        raise BootstrapError(2, f"--wheel {wheel.name} is not a recalith pure-Python wheel (recalith-VERSION-py3-none-any.whl)")
    missing = []
    if not wheel.is_file():
        missing.append(f"the wheel {wheel}")
    if not wheelhouse.is_dir():
        missing.append(f"the wheelhouse directory {wheelhouse}")
    if not REQUIREMENTS.is_file():
        missing.append(f"requirements.lock beside bootstrap.py ({REQUIREMENTS})")
    if missing:
        raise BootstrapError(4, "missing: " + "; ".join(missing) + ". A release carries bootstrap.py, requirements.lock, the wheel and one wheelhouse per platform and Python version.")
    actual = sha256(wheel)
    if actual != expected:
        raise BootstrapError(2, "the wheel's digest does not match --expected-digest; refusing to install")
    return match.group("version"), actual


def provisioned(base: Path, version: str) -> Path | None:
    """The marker of a provisioned runtime for ``version``, or None."""
    marker = base / "runtime" / version / MARKER
    return marker if marker.is_file() else None


def provision(project: Path, wheel: Path, expected: str, wheelhouse: Path) -> dict[str, str]:
    """Provision the runtime (idempotent for the same artifact); returns the status record it prints."""
    base = project / ".recalith"
    if not project.is_dir():
        raise BootstrapError(2, f"--project {project} is not an existing directory")
    version, actual = check_inputs(wheel, expected, wheelhouse)
    lock_path = base / "engine.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    requires = lock.get("requires_python", DEFAULT_REQUIRES_PYTHON)
    if not python_supported(requires):
        raise BootstrapError(4, f"Python {sys.version.split()[0]} does not satisfy {requires}")
    target = base / "runtime" / version
    marker = target / MARKER
    if marker.exists():
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        if recorded.get("artifact_sha256") == actual:
            return {"status": "already_provisioned", "version": version, "artifact_sha256": actual}
        raise BootstrapError(2, f"a different artifact is already provisioned for version {version} in {target}; remove that directory explicitly first")
    if target.exists():
        # Never delete a runtime tree this script did not finish writing: a worker may run from it (audit 2026-11-06 CLI-12).
        raise BootstrapError(2, f"{target} exists without a provisioning record; stop any worker using it and remove it explicitly first")
    # The private layout exists before staging, for a new project and for a fresh clone alike (audit 2026-11-06 CLI-1).
    private_mkdir(base)
    private_mkdir(base / "runtime")
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{version}-", dir=base / "runtime"))
    try:
        venv = staging / "venv"
        created = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True, check=False)
        if created.returncode != 0:
            raise BootstrapError(5, "virtual environment creation failed:\n" + (created.stderr or created.stdout)[-2000:])
        reqs = staging / "requirements.txt"
        reqs.write_text(REQUIREMENTS.read_text(encoding="utf-8") + f"recalith @ {wheel.resolve().as_uri()} --hash=sha256:{actual}\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PIP_", "PYTHON"))}
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        result = subprocess.run(
            [str(venv_python(venv)), "-m", "pip", "install", "--no-index", "--find-links", str(wheelhouse), "--require-hashes", "--no-deps", "--only-binary", ":all:", "-r", str(reqs)],
            capture_output=True, text=True, env=env, check=False,
        )
        if result.returncode != 0:
            raise BootstrapError(4, (
                "pip could not install the locked wheels from the local wheelhouse. The wheelhouse must hold every wheel of requirements.lock "
                f"built for this platform and Python {sys.version_info[0]}.{sys.version_info[1]} (tools/build_wheelhouse.py names its directory after both).\n"
                + result.stdout[-2000:] + result.stderr[-2000:]
            ))
        check = subprocess.run([str(venv_python(venv)), "-I", "-c", "import recalith, recalith.contracts; print(recalith.__version__)"], capture_output=True, text=True, check=False)
        if check.returncode != 0 or check.stdout.strip() != version:
            raise BootstrapError(5, "the provisioned runtime failed its import check")
        (staging / MARKER).write_text(json.dumps({"version": version, "artifact_sha256": actual, "python": sys.version.split()[0]}) + "\n", encoding="utf-8")
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    update_engine_lock(lock_path, version, actual)
    return {"status": "provisioned", "version": version, "artifact_sha256": actual}


def install(project: Path, wheel: Path, expected: str, wheelhouse: Path) -> int:
    print(json.dumps(provision(project, wheel, expected, wheelhouse)))
    return 0


def run_cli(project: Path, version: str, argv: list[str]) -> int:
    """Run one ``recalith`` form on the provisioned interpreter with this process's standard streams."""
    python = venv_python(project / ".recalith" / "runtime" / version / "venv")
    command = [str(python), "-I", "-m", "recalith", "--project", str(project), *argv]
    if os.name != "nt":
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(command[0], command)  # the CLI's guard inspects this terminal and this environment
    return subprocess.run(command, check=False).returncode  # Windows: exec would detach from the console


def first_form(project: Path, wheel: Path, expected: str, wheelhouse: Path, argv: list[str]) -> int:
    """A pre-init form: provision when needed (a status line on stderr), then run the form."""
    record = provision(project, wheel, expected, wheelhouse)
    print(f"bootstrap: runtime {record['version']} {record['status']}", file=sys.stderr)
    return run_cli(project, record["version"], argv)


def status(project: Path) -> int:
    base = project / ".recalith"
    lock = tomllib.loads((base / "engine.lock").read_text(encoding="utf-8")) if (base / "engine.lock").exists() else {}
    version = lock.get("engine_version")
    marker = provisioned(base, str(version)) if version else None
    state = {"engine_version": version, "provisioned": marker is not None, "artifact_sha256": lock.get("artifact_sha256")}
    print(json.dumps(state))
    return 0 if marker is not None else 4


def _add_artifact_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--wheelhouse", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    _add_artifact_options(sub.add_parser("install", help="provision the pinned runtime only"))
    p_init = sub.add_parser("init", help="provision, then `recalith init` on the provisioned runtime")
    _add_artifact_options(p_init)
    p_init.add_argument("--profile", required=True, choices=("coding", "general"))
    p_init.add_argument("--release-profile", required=True, choices=("claude_preview", "full"))
    p_init.add_argument("--operator-token-file", type=Path)
    p_init.add_argument("--json", action="store_true")
    p_token = sub.add_parser("operator-token", help="provision, then `recalith operator-token create` on the provisioned runtime")
    p_token.add_argument("action", choices=("create",))
    _add_artifact_options(p_token)
    p_token.add_argument("--output", required=True, type=Path)
    p_token.add_argument("--json", action="store_true")
    p_status = sub.add_parser("status", help="is the pinned runtime provisioned?")
    p_status.add_argument("--project", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    project = ns.project.resolve()
    try:
        if ns.command == "status":
            return status(project)
        if ns.command == "install":
            return install(project, ns.wheel, ns.expected_digest, ns.wheelhouse)
        common = ["--json"] if ns.json else []
        if ns.command == "init":
            token = ["--operator-token-file", str(ns.operator_token_file.resolve())] if ns.operator_token_file else []
            return first_form(project, ns.wheel, ns.expected_digest, ns.wheelhouse, [*common, *token, "init", "--profile", ns.profile, "--release-profile", ns.release_profile])
        return first_form(project, ns.wheel, ns.expected_digest, ns.wheelhouse, [*common, "operator-token", "create", "--output", str(ns.output.resolve())])
    except BootstrapError as exc:
        return fail(exc.code, str(exc))
    except OSError as exc:
        return fail(5, f"{type(exc).__name__}: {exc.strerror or exc}" + (f" ({exc.filename})" if getattr(exc, 'filename', None) else ""))


if __name__ == "__main__":
    sys.exit(main())
