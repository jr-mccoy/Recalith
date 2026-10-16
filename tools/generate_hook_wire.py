#!/usr/bin/env python3
"""Generate (or check) the stdlib wire validators used by the hook fast path.

    python tools/generate_hook_wire.py          # rewrite src/recalith/fast/wire_generated.py
    python tools/generate_hook_wire.py --check  # exit 1 on drift from the strict contracts

The strict Pydantic contracts stay authoritative (DATA_CONTRACTS §1). This tool
derives from them the primitive tables that ``recalith.fast.wire`` interprets
without importing Pydantic: shared limits, identifier/digest/time grammars, the
environment allowlist grammar and a JSON-Schema subset of each hook-relevant
model. Every field-level check function and every model validator is emitted
by name. A field check the generator does not know, or a model rule with no
stdlib implementation in ``recalith.fast.wire.RULES``, fails generation, so a
new strict rule cannot silently go unenforced on the fast path. Cross-field
rules are implemented by hand in ``wire.RULES``; the shared fixture suite
(``test_fast_and_strict_validation_agree``) proves the verdicts agree.
"""

from __future__ import annotations

import argparse
import functools
import json
import pprint
import typing
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import BaseModel  # noqa: E402
from pydantic.json_schema import GenerateJsonSchema  # noqa: E402

from recalith.contracts import common, config, context, events  # noqa: E402

TARGET = ROOT / "src" / "recalith" / "fast" / "wire_generated.py"
MODELS = {
    "EventEnvelope": events.EventEnvelope,
    "ToolPayload": events.ToolPayload,
    "AgentAttemptPayload": events.AgentAttemptPayload,
    "Segment": events.Segment,
    "CaptureReceipt": events.CaptureReceipt,
    "SessionScratch": context.SessionScratch,
}
FIELD_CHECKS = {
    common._check_id: "id",
    common._check_digest: "digest",
    common._check_utc: "utc",
    common._check_portable_path: "portable_path",
    common._check_json_object: "json_object",
    common._check_environment: "environment",
}
CONSTRAINT_VALIDATORS = {
    "min_length_validator": {"str": "minLength", "list": "minItems"},
    "max_length_validator": {"str": "maxLength", "list": "maxItems"},
}
LIMIT_NAMES = (
    "EVENT_PAYLOAD_CAP", "SEGMENT_CAP", "WIRE_STDOUT_CAP", "RESULT_TEXT_HEAD", "RESULT_TEXT_TAIL", "ERROR_SIGNATURE_CAP",
    "EXTENSIONS_CAP", "HOOK_SOFT_DEADLINE_MS", "SESSION_LOCK_WAIT_MS", "SESSION_SCRATCH_CAP", "SESSION_SCRATCH_ENTRIES",
    "SESSION_SCRATCH_OUTCOMES", "TOOL_ASSERTION_IDENTITY_MAX", "TOOL_ASSERTION_VALUE_MAX", "TOOL_ASSERTIONS_MAX", "KIB",
)
KEEP = {
    "type", "properties", "required", "additionalProperties", "items", "anyOf", "enum", "const", "$ref",
    "minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minItems", "maxItems", "propertyNames", "x-check", "x-rule", "x-utf8-max",
}


ANNOTATIONS = {"title", "description", "default", "examples", "$defs", "patternProperties"}


class GenerationError(RuntimeError):
    pass


class _Marked(GenerateJsonSchema):
    """JSON Schema with each after-validator recorded by name."""

    def function_after_schema(self, schema: Any) -> Any:
        inner = dict(super().function_after_schema(schema))
        func = schema["function"]["function"]
        if isinstance(func, functools.partial):
            # Pydantic applies a constraint that follows a custom validator as an internal partial.
            keyword = CONSTRAINT_VALIDATORS.get(getattr(func.func, "__name__", ""))
            if keyword is None or len(func.keywords) != 1:
                raise GenerationError(f"unsupported internal constraint validator {func!r}")
            (value,) = func.keywords.values()
            kind = schema["schema"].get("type") if schema["schema"].get("type") != "function-after" else schema["schema"]["schema"].get("type")
            inner[keyword[kind]] = value
            return inner
        if func in FIELD_CHECKS:
            inner["x-check"] = FIELD_CHECKS[func]
        elif hasattr(func, "utf8_max"):
            inner["x-utf8-max"] = func.utf8_max
        elif "." in func.__qualname__ and "<locals>" not in func.__qualname__:
            inner["x-rule"] = func.__qualname__  # a model validator: Class._name
        else:
            raise GenerationError(f"field check {func.__qualname__!r} has no stdlib equivalent; extend FIELD_CHECKS and recalith.fast.wire")
        return inner


    def function_before_schema(self, schema: Any) -> Any:
        inner = dict(super().function_before_schema(schema))
        func = schema["function"]["function"]
        if getattr(func, "exact_type", None) not in ("int", "bool"):
            raise GenerationError(f"before-validator {getattr(func, '__qualname__', func)!r} has no stdlib equivalent")
        # The stdlib interpreter's JSON types are already exact (bool is never an integer).
        return inner


def _prune(node: Any) -> Any:
    if isinstance(node, dict):
        out = {}
        if "patternProperties" in node:
            # A Pydantic dict with constrained keys: every key must match and every value validates.
            if len(node["patternProperties"]) != 1 or "additionalProperties" in node:
                raise GenerationError("only single-pattern constrained dict keys are supported")
            ((pattern, value_schema),) = node["patternProperties"].items()
            node = {**node, "propertyNames": {"pattern": pattern}, "additionalProperties": value_schema}
        for key, value in node.items():
            if key == "properties":
                out[key] = {name: _prune(sub) for name, sub in value.items()}
            elif key in KEEP:
                out[key] = _prune(value) if key not in ("enum", "const", "required") else value
            elif key not in ANNOTATIONS:
                raise GenerationError(f"JSON Schema keyword {key!r} has no stdlib interpretation; extend recalith.fast.wire")
        if out.get("$ref"):
            out["$ref"] = out["$ref"].rsplit("/", 1)[-1]
        return out
    if isinstance(node, list):
        return [_prune(item) for item in node]
    return node


def _rules(node: Any, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        if "x-rule" in node:
            found.add(node["x-rule"])
        for value in node.values():
            _rules(value, found)
    elif isinstance(node, list):
        for value in node:
            _rules(value, found)
    return found


def _model_classes(model: type[BaseModel], found: dict[str, type[BaseModel]]) -> dict[str, type[BaseModel]]:
    found[model.__name__] = model
    for field in model.model_fields.values():
        stack = [field.annotation]
        while stack:
            annotation = stack.pop()
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                if annotation.__name__ not in found:
                    _model_classes(annotation, found)
            else:
                stack.extend(typing.get_args(annotation))
    return found


def _defaults(model: type[BaseModel]) -> dict[str, Any]:
    """JSON values Pydantic fills for omitted optional fields (model_dump includes them)."""
    out = {}
    for name, field in model.model_fields.items():
        if field.is_required():
            continue
        value = field.get_default(call_default_factory=True, validated_data={})
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        json.dumps(value, allow_nan=False)  # defaults must be plain JSON
        out[name] = value
    return out


def build() -> dict[str, Any]:
    models: dict[str, Any] = {}
    defs: dict[str, Any] = {}
    classes: dict[str, type[BaseModel]] = {}
    for name, model in MODELS.items():
        _model_classes(model, classes)
        schema = model.model_json_schema(mode="validation", schema_generator=_Marked)
        for def_name, def_schema in schema.pop("$defs", {}).items():
            pruned = _prune(def_schema)
            if def_name in defs and defs[def_name] != pruned:
                raise GenerationError(f"two different definitions named {def_name}")
            defs[def_name] = pruned
        models[name] = _prune(schema)
    for name in models:
        defs.pop(name, None)
    for table in (models, defs):
        for name, schema in table.items():
            if name not in classes:
                raise GenerationError(f"no model class found for definition {name}")
            defaults = _defaults(classes[name])
            if defaults:
                schema["x-defaults"] = defaults
    return {
        "LIMITS": {name: getattr(config, name) for name in LIMIT_NAMES},
        "ID_PREFIXES": sorted(common.ID_PREFIXES),
        "ID_PATTERN": common.ID_RE.pattern,
        "DIGEST_PATTERN": common.DIGEST_RE.pattern,
        "UTC_PATTERN": common.UTC_RE.pattern,
        "PORTABLE_BAD_PATTERN": common._PORTABLE_BAD.pattern,
        "ENVIRONMENT_GRAMMAR": {key: pattern.pattern for key, pattern in common.ENVIRONMENT_GRAMMAR.items()},
        "MODELS": models,
        "DEFS": dict(sorted(defs.items())),
    }


def render(tables: dict[str, Any]) -> str:
    lines = [
        '"""GENERATED by tools/generate_hook_wire.py from recalith.contracts; do not edit.',
        "",
        "Primitive tables interpreted by :mod:`recalith.fast.wire`. Regenerate after any",
        "contract change; CI runs ``python tools/generate_hook_wire.py --check``.",
        '"""',
        "",
        "# fmt: off",
    ]
    for name, value in tables.items():
        rendered = pprint.pformat(value, width=120, sort_dicts=True)
        lines.append(f"{name} = {rendered}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def check_rules(tables: dict[str, Any]) -> list[str]:
    from recalith.fast import wire

    needed = _rules(tables["MODELS"], set()) | _rules(tables["DEFS"], set())
    return sorted(needed - set(wire.RULES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail on drift instead of rewriting")
    args = parser.parse_args(argv)
    try:
        tables = build()
    except GenerationError as exc:
        print(f"generate_hook_wire: {exc}", file=sys.stderr)
        return 1
    text = render(tables)
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"generate_hook_wire: {TARGET.relative_to(ROOT)} is out of date; run tools/generate_hook_wire.py", file=sys.stderr)
            return 1
    else:
        TARGET.write_text(text, encoding="utf-8", newline="\n")
    missing = check_rules(tables)
    if missing:
        print(f"generate_hook_wire: strict model rules without a stdlib implementation in recalith.fast.wire.RULES: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
