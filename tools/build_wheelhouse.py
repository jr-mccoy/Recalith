#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build the hash-locked wheelhouse one platform and Python version needs (audit 2026-11-06 REL-1).

    python tools/build_wheelhouse.py --out DIR [--python PYTHON]

``bootstrap.py`` installs ``requirements.lock`` with ``pip install --no-index
--require-hashes --only-binary :all:`` from a local directory of wheels. Pure
wheels are the same everywhere, but ``pydantic-core`` is compiled, so a
wheelhouse is specific to the platform and Python minor version that will run
the engine. This tool downloads exactly the locked wheels for *this*
interpreter (or ``--python``) into ``DIR/wheelhouse-<platform>-<python tag>``
(for example ``wheelhouse-linux-x86_64-cp313`` or ``wheelhouse-win-amd64-cp313``)
and writes ``WHEELHOUSE.json`` beside them: the platform, the Python tag, the
lock's digest and every wheel's name and SHA-256. A directory holding a
wheelhouse for another platform or Python is refused rather than mixed.

Every downloaded wheel's digest is checked against ``requirements.lock``
before the manifest is written. The download uses pip from the chosen
interpreter (``python -m pip``); in a uv project without pip, run it as
``uv run --with pip python tools/build_wheelhouse.py …``.

Exit 0 when the wheelhouse is complete; 1 when a wheel is missing or its digest
is not in the lock; 2 for a refused directory; 4 when pip is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
MANIFEST = "WHEELHOUSE.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def locked_hashes(lock_text: str) -> dict[str, set[str]]:
    """package name -> the SHA-256 digests requirements.lock accepts for it."""
    out: dict[str, set[str]] = {}
    current = None
    for line in lock_text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==", line)
        if m:
            current = m.group(1).lower().replace("_", "-")
            out.setdefault(current, set())
            continue
        h = re.search(r"--hash=sha256:([0-9a-f]{64})", line)
        if h and current:
            out[current].add(h.group(1))
    return out


def interpreter_tags(python: str) -> tuple[str, str]:
    """``(platform, python tag)`` of ``python``: this process's own, or the named interpreter's."""
    if python == sys.executable:
        return sysconfig.get_platform(), f"cp{sys.version_info[0]}{sys.version_info[1]}"
    code = "import sys, sysconfig; print(sysconfig.get_platform()); print(f'cp{sys.version_info[0]}{sys.version_info[1]}')"
    proc = subprocess.run([python, "-c", code], capture_output=True, text=True, check=True)
    platform, tag = proc.stdout.split()
    return platform, tag


def wheelhouse_name(platform: str, tag: str) -> str:
    return f"wheelhouse-{platform}-{tag}"


def download(python: str, target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [python, "-m", "pip", "download", "--only-binary", ":all:", "--require-hashes", "--no-deps", "-r", str(LOCK), "-d", str(target), "--disable-pip-version-check"],
        capture_output=True, text=True, check=False,
    )


def check(target: Path, lock_text: str) -> tuple[list[str], dict[str, str]]:
    """``(problems, wheel name -> digest)``: every locked package present once, every wheel's digest in the lock."""
    hashes = locked_hashes(lock_text)
    wheels = {p.name: sha256(p) for p in sorted(target.glob("*.whl"))}
    problems = []
    found: dict[str, int] = {name: 0 for name in hashes}
    for name, digest in wheels.items():
        package = name.split("-")[0].lower().replace("_", "-")
        if package not in hashes:
            problems.append(f"unexpected wheel {name}")
        elif digest not in hashes[package]:
            problems.append(f"digest of {name} is not in requirements.lock")
        else:
            found[package] += 1
    problems += [f"no wheel for {name}" for name, count in found.items() if count == 0]
    problems += [f"more than one wheel for {name}" for name, count in found.items() if count > 1]
    return problems, wheels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="the directory that receives wheelhouse-<platform>-<tag>/")
    parser.add_argument("--python", default=sys.executable, help="the interpreter whose platform and version the wheelhouse is for (default: this one)")
    ns = parser.parse_args(argv)
    try:
        platform, tag = interpreter_tags(ns.python)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: cannot query {ns.python}: {exc}", file=sys.stderr)
        return 4
    target = ns.out / wheelhouse_name(platform, tag)
    manifest_path = target / MANIFEST
    lock_text = LOCK.read_text(encoding="utf-8")
    lock_digest = hashlib.sha256(lock_text.encode("utf-8")).hexdigest()
    if manifest_path.exists():
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (recorded.get("platform"), recorded.get("python_tag")) != (platform, tag):
            print(f"error: {target} holds a wheelhouse for {recorded.get('platform')} {recorded.get('python_tag')}; refusing to mix", file=sys.stderr)
            return 2
    elif target.exists() and any(target.iterdir()):
        print(f"error: {target} exists without a {MANIFEST}; remove it or let this tool create the directory", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    proc = download(ns.python, target)
    if proc.returncode != 0:
        pip_missing = "No module named pip" in proc.stderr
        print(proc.stderr[-2000:], file=sys.stderr)
        if pip_missing:
            print("error: pip is not available in that interpreter (in a uv project: uv run --with pip python tools/build_wheelhouse.py ...)", file=sys.stderr)
        return 4 if pip_missing else 1
    problems, wheels = check(target, lock_text)
    manifest = {"wheelhouse_schema": 1, "platform": platform, "python_tag": tag, "requirements_lock_sha256": lock_digest, "wheels": wheels, "problems": problems}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"wheelhouse": str(target), "platform": platform, "python_tag": tag, "wheels": len(wheels), "problems": problems}, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
