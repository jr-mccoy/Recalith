"""Owned host-settings installation with an ownership manifest (SYSTEM_SPEC §2.2; decision 0019).

One host settings file (a JSON object) receives *owned* entries: hook groups
appended to ``hooks.<event>`` and deny rules appended to
``permissions.deny``. Everything else in the file is unrelated and is
preserved: on install it is parsed and rewritten in the host's own two-space
JSON form; on removal, when the remaining settings are semantically the file
that existed before installation, the exact original bytes are written back
(byte for byte), from a private before-copy kept beside the ownership record.

The ownership record ``.recalith/run/integrations/<host>.json`` (private,
ignored) stores the exact owned entries, the owned ignore line, the
settings' before/after digests and the state:

- ``installing``: written *before* the settings change, so a crash at any
  later step is recovered by re-running install or remove (an intended entry
  found unchanged in the file is treated as owned);
- ``installed``;
- ``reconcile``: a removal found owned entries modified by someone else and
  left them in place for the operator to reconcile; install refuses
  (``revision_conflict``) while an edited owned entry is still there, so
  there is never a second copy beside an edited one.

Removal deletes only unchanged owned entries and reports modified and missing
ones. A pre-existing identical deny rule or ignore line is never owned (it
stays). Existing permission rules are never loosened: install only appends.
Writes are atomic (temporary file, flush, ``fsync``, rename) and private.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from recalith.core.paths import private_mkdir
from recalith.errors import RecalithError
from recalith.fast import failpoints

OWNERSHIP_SCHEMA = 1
OWNERSHIP_DIR = Path(".recalith") / "run" / "integrations"
MAX_SETTINGS_BYTES = 1024 * 1024

# Failpoints of the persisted integration steps (the kill/restart family ``failpoints.INTEGRATION``).
AFTER_RECORD = failpoints.INTEGRATE_AFTER_RECORD
AFTER_SETTINGS = failpoints.INTEGRATE_AFTER_SETTINGS
AFTER_IGNORE = failpoints.INTEGRATE_AFTER_IGNORE
AFTER_MANIFEST = failpoints.INTEGRATE_AFTER_MANIFEST
REMOVE_AFTER_SETTINGS = failpoints.REMOVE_AFTER_SETTINGS
REMOVE_AFTER_IGNORE = failpoints.REMOVE_AFTER_IGNORE
REMOVE_AFTER_MANIFEST = failpoints.REMOVE_AFTER_MANIFEST


@dataclass(frozen=True)
class Desired:
    """What an integration wants to own in one settings file."""

    hooks: Sequence[tuple[str, dict[str, Any]]]  # (event, exact group)
    deny: Sequence[str]
    ignore_line: str
    marker: str  # a substring that identifies an owned hook command even after an edit


@dataclass
class Outcome:
    settings: str = "unchanged"  # installed | updated | unchanged
    removed: dict[str, int] = field(default_factory=lambda: {"hooks": 0, "deny": 0})
    modified: list[dict[str, str]] = field(default_factory=list)
    missing: list[dict[str, str]] = field(default_factory=list)
    unrelated_preserved: str = "not_applicable"  # byte_identical | semantically_identical | not_applicable
    formatting_preserved: bool = True


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _dump(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def atomic_write(path: Path, data: bytes, *, private: bool = True) -> None:
    """Temporary file in the same directory, flush, fsync, rename (0600 when private)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name != "nt":
            os.chmod(tmp, 0o600 if private else 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_settings(path: Path) -> tuple[dict[str, Any], bytes | None]:
    """The settings object and its exact bytes (None when absent); malformed is ``invalid_schema``, nothing is changed."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        raise RecalithError("storage_failure", f"the host settings file cannot be read ({type(exc).__name__})") from None
    if len(raw) > MAX_SETTINGS_BYTES:
        raise RecalithError("invalid_schema", "the host settings file exceeds 1 MiB")
    try:
        data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError):
        raise RecalithError("invalid_schema", "the host settings file is not valid JSON; nothing was changed") from None
    if not isinstance(data, dict):
        raise RecalithError("invalid_schema", "the host settings file is not a JSON object; nothing was changed")
    for key, kind in (("hooks", dict), ("permissions", dict)):
        if key in data and not isinstance(data[key], kind):
            raise RecalithError("invalid_schema", f"the host settings field {key!r} is not an object; nothing was changed")
    if isinstance(data.get("permissions"), dict) and "deny" in data["permissions"] and not isinstance(data["permissions"]["deny"], list):
        raise RecalithError("invalid_schema", "permissions.deny is not a list; nothing was changed")
    return data, raw


class Ownership:
    """The private ownership record of one host integration in one installation."""

    def __init__(self, root: Path, host_id: str) -> None:
        self.root = Path(root)
        self.host_id = host_id
        self.dir = self.root / OWNERSHIP_DIR
        self.path = self.dir / f"{host_id}.json"
        self.before_copy = self.dir / f"{host_id}.settings-before.json"

    def load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise RecalithError("invalid_schema", "the integration ownership record is unreadable; nothing was changed") from None
        if not isinstance(data, dict) or data.get("ownership_schema") != OWNERSHIP_SCHEMA or data.get("host_id") != self.host_id:
            raise RecalithError("invalid_schema", "the integration ownership record is invalid; nothing was changed")
        return data

    def save(self, record: dict[str, Any]) -> None:
        private_mkdir(self.dir)
        atomic_write(self.path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def delete(self) -> None:
        for path in (self.path, self.before_copy):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        with contextlib.suppress(OSError):
            self.dir.rmdir()


# --------------------------------------------------------------------------
# Entry matching


def _hook_state(data: dict[str, Any], event: str, group: dict[str, Any], marker: str) -> str:
    """``present`` (exactly), ``modified`` (an edited owned group is there) or ``missing``."""
    groups = (data.get("hooks") or {}).get(event) or []
    if group in groups:
        return "present"
    command = group["hooks"][0]["command"]
    for g in groups:
        text = json.dumps(g)
        if marker in text and (command in text or json.dumps(command)[1:-1] in text):
            return "modified"
    return "missing"


def _remove_group(data: dict[str, Any], event: str, group: dict[str, Any]) -> None:
    groups = data["hooks"][event]
    groups.remove(group)
    if not groups:
        del data["hooks"][event]
    if not data["hooks"]:
        del data["hooks"]


def _remove_rule(data: dict[str, Any], rule: str) -> None:
    deny = data["permissions"]["deny"]
    deny.remove(rule)
    if not deny:
        del data["permissions"]["deny"]
    if not data["permissions"]:
        del data["permissions"]


def _strip_owned(data: dict[str, Any], owned: dict[str, Any], marker: str, outcome: Outcome | None = None) -> dict[str, Any]:
    """A copy of ``data`` without the unchanged owned entries (recording what was modified or missing)."""
    out = json.loads(json.dumps(data))
    for item in owned.get("hooks", []):
        state = _hook_state(out, item["event"], item["group"], marker)
        if state == "present":
            _remove_group(out, item["event"], item["group"])
            if outcome is not None:
                outcome.removed["hooks"] += 1
        elif outcome is not None:
            (outcome.modified if state == "modified" else outcome.missing).append({"kind": "hook", "event": item["event"]})
    for rule in owned.get("deny", []):
        if rule in ((out.get("permissions") or {}).get("deny") or []):
            _remove_rule(out, rule)
            if outcome is not None:
                outcome.removed["deny"] += 1
        elif outcome is not None:
            outcome.missing.append({"kind": "deny_rule", "rule": rule})
    return out


# --------------------------------------------------------------------------
# Ignore line


def _ignore_lines(path: Path) -> tuple[list[str], bytes | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return [], None
    return raw.decode("utf-8", "replace").splitlines(), raw


def _ensure_ignore(path: Path, plan: dict[str, Any]) -> None:
    """Append the planned owned ignore line when it is not there yet (a pre-existing line is never owned)."""
    if not plan.get("owned"):
        return
    lines, raw = _ignore_lines(path)
    if plan["line"] in lines:
        return
    text = "" if raw is None else raw.decode("utf-8", "replace")
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(path, (text + plan["line"] + "\n").encode("utf-8"), private=False)


def _remove_ignore(path: Path, entry: dict[str, Any] | None) -> None:
    if not entry or not entry.get("owned"):
        return
    lines, raw = _ignore_lines(path)
    if raw is None or entry["line"] not in lines:
        return
    text = raw.decode("utf-8", "replace")
    kept = [ln for ln in text.splitlines(keepends=True) if ln.rstrip("\r\n") != entry["line"]]
    if not kept and entry.get("file_created"):
        path.unlink()
        return
    atomic_write(path, "".join(kept).encode("utf-8"), private=False)


# --------------------------------------------------------------------------
# Install and remove


def install(root: Path, host_id: str, settings_rel: Path, desired: Desired, *, extra: dict[str, Any], now: str) -> tuple[Outcome, dict[str, Any]]:
    """Install the desired owned entries; returns the outcome and the final ownership record (state ``installed``).

    The caller persists the final record with :func:`finish` after its own
    last step. Persisted order: the ``installing`` record (intended entries,
    ignore plan, private before-copy), the settings, the ignore line.
    """
    root = Path(root)
    own = Ownership(root, host_id)
    record = own.load()
    settings_path = root / settings_rel
    data, raw = read_settings(settings_path)
    marker = desired.marker
    outcome = Outcome()
    if record is None:
        # The pre-install state: exact bytes kept privately so removal can restore them byte for byte.
        before = {"existed": raw is not None, "sha256": _sha(raw), "claude_dir_existed": settings_path.parent.exists()}
        private_mkdir(own.dir)
        if raw is not None:
            atomic_write(own.before_copy, raw)
        record = {"ownership_schema": OWNERSHIP_SCHEMA, "host_id": host_id, "scope": "local", "settings_path": settings_rel.as_posix(), "before": before, "installed_at": now, "owned": {"hooks": [], "deny": [], "gitignore": None}}
    ours = _ours(record)
    probe = Outcome()
    base = _strip_owned(data, ours, marker, probe)  # the settings without anything we own (unchanged entries)
    if probe.modified:
        raise RecalithError("revision_conflict", "owned host entries were modified; reconcile them (see `integrate claude --remove`) before integrating again")
    base_deny = list((base.get("permissions") or {}).get("deny") or [])
    owned_hooks = [{"event": e, "group": g} for e, g in desired.hooks]
    owned_deny = [r for r in desired.deny if r not in base_deny]
    preexisting = [r for r in desired.deny if r in base_deny]
    ignore_plan = (record["owned"].get("gitignore") or None)
    if ignore_plan is None or ignore_plan.get("line") != desired.ignore_line:
        lines, ignore_raw = _ignore_lines(root / ".gitignore")
        ignore_plan = {"path": ".gitignore", "line": desired.ignore_line, "owned": desired.ignore_line not in lines, "file_created": ignore_raw is None}
    intended = dict(record, **extra, state="installing", updated_at=now, owned={"hooks": owned_hooks, "deny": owned_deny, "gitignore": ignore_plan}, previous_owned=ours, deny_preexisting=preexisting)
    own.save(intended)
    failpoints.hit(AFTER_RECORD)
    target = json.loads(json.dumps(base))
    for event, group in desired.hooks:
        groups = target.setdefault("hooks", {}).setdefault(event, [])
        if group not in groups:
            groups.append(group)
    if owned_deny:
        target.setdefault("permissions", {}).setdefault("deny", []).extend(owned_deny)
    order = [*data.keys(), *[k for k in target if k not in data]]
    target = {k: target[k] for k in order if k in target}  # keep the user's key order
    new_raw = _dump(target)
    if raw is not None and new_raw == raw:
        outcome.settings = "unchanged"
    else:
        outcome.settings = "updated" if _canonical(base) != _canonical(data) else "installed"
        atomic_write(settings_path, new_raw)
    outcome.formatting_preserved = raw is None or not raw.strip() or _dump(json.loads(raw.decode("utf-8"))) == raw
    failpoints.hit(AFTER_SETTINGS)
    _ensure_ignore(root / ".gitignore", ignore_plan)
    failpoints.hit(AFTER_IGNORE)
    final = dict(intended, state="installed", settings_after_sha256=_sha(new_raw))
    final.pop("previous_owned", None)
    return outcome, final


def _ours(record: dict[str, Any]) -> dict[str, Any]:
    """Every entry this record may own: the current set plus, after a crash during an update, the previous one."""
    owned = record.get("owned") or {}
    previous = record.get("previous_owned") or {}
    hooks = list(owned.get("hooks") or [])
    hooks += [h for h in previous.get("hooks") or [] if h not in hooks]
    deny = list(owned.get("deny") or [])
    deny += [r for r in previous.get("deny") or [] if r not in deny]
    return {"hooks": hooks, "deny": deny}


def finish(root: Path, host_id: str, record: dict[str, Any]) -> None:
    """Persist the final record (after the caller's own step, e.g. the hook manifest)."""
    Ownership(Path(root), host_id).save(record)


def remove(root: Path, host_id: str, *, marker: str, after_settings=None) -> tuple[Outcome, dict[str, Any] | None]:
    """Remove unchanged owned entries; restore the original bytes when nothing else changed.

    Returns ``(outcome, record)``; ``record`` is None when the integration is
    gone, or the record in state ``reconcile`` when modified owned entries
    were left in place.
    """
    root = Path(root)
    own = Ownership(root, host_id)
    record = own.load()
    outcome = Outcome()
    if record is None:
        return outcome, None
    settings_path = root / record["settings_path"]
    data, raw = read_settings(settings_path)
    owned = _ours(record)  # after a crash during an update, the previous entries are ours too
    remaining = _strip_owned(data, owned, marker, outcome)
    before = record.get("before") or {}
    before_bytes = own.before_copy.read_bytes() if own.before_copy.exists() else None
    if raw is not None:
        if before.get("existed") and before_bytes is not None and _sha(before_bytes) == before.get("sha256") and _canonical(json.loads(before_bytes.decode("utf-8") or "{}")) == _canonical(remaining):
            if raw != before_bytes:
                atomic_write(settings_path, before_bytes)
            outcome.unrelated_preserved = "byte_identical"
        elif not before.get("existed") and remaining == {}:
            settings_path.unlink()
            if not before.get("claude_dir_existed"):
                with contextlib.suppress(OSError):
                    settings_path.parent.rmdir()
            outcome.unrelated_preserved = "byte_identical"
        else:
            new_raw = _dump(remaining)
            if new_raw != raw:
                atomic_write(settings_path, new_raw)
            outcome.unrelated_preserved = "semantically_identical"
    failpoints.hit(REMOVE_AFTER_SETTINGS)
    if after_settings is not None:
        after_settings()
    if outcome.modified:
        kept = dict(record, state="reconcile", owned={"hooks": [h for h in owned["hooks"] if {"kind": "hook", "event": h["event"]} in outcome.modified], "deny": [], "gitignore": record["owned"].get("gitignore")})
        kept.pop("previous_owned", None)
        own.save(kept)
        return outcome, kept
    _remove_ignore(root / ".gitignore", record["owned"].get("gitignore"))
    failpoints.hit(REMOVE_AFTER_IGNORE)
    own.delete()
    return outcome, None


__all__ = ["Desired", "Outcome", "Ownership", "install", "finish", "remove", "read_settings", "atomic_write", "OWNERSHIP_SCHEMA", "OWNERSHIP_DIR"]
