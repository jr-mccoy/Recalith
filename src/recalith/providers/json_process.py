"""Generic configured JSON-process backend (SYSTEM_SPEC §9.1).

A local model adapter can speak this envelope: the request JSON on stdin, one
JSON object on stdout ``{"type": "result", "result": "<body JSON as a
string>", "usage": {...}}``. Unknown metadata keys are ignored and never
interpreted; usage values that are not nonnegative integers are unknown.

A generic process exposes no host diagnostic from which the engine could
establish its effective tool and customization isolation, so this backend
has no certification procedure in this build: a configured ``json_process``
route is reported unavailable (``backend_certification_unavailable``) and
never launched by the worker. Tests use the adapter directly, against fake
processes that are never certification subjects.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

BACKEND = "json_process"
ENVELOPE = "json_result_object"


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def argv(executable: str, args: Sequence[str], *, model: str, system_prompt: str) -> list[str]:
    return [executable] + [a.replace("{model}", model).replace("{system_prompt}", system_prompt) for a in args]


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def unwrap(stdout: bytes, *, expect: Any = None) -> tuple[bytes, dict[str, Any]]:
    data = json.loads(stdout.decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(data, dict) or data.get("type") != "result" or not isinstance(data.get("result"), str):
        raise ValueError("not a json_process result envelope")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model = data.get("model")
    return data["result"].encode("utf-8"), {
        "input_tokens": _int(usage.get("input_tokens")),
        "output_tokens": _int(usage.get("output_tokens")),
        "provider_request_id": None,
        "resolved_model": model if isinstance(model, str) and len(model) <= 128 else None,
    }


__all__ = ["BACKEND", "argv", "unwrap"]
