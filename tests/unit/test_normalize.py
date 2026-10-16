"""Task 3: normalization — bounded text, certified parsers, expected_red, environment (A52, A54, A66, A68)."""

from __future__ import annotations

import json

import pytest

import factories as f
from recalith.capture import parsers
from recalith.capture.normalize import RawEvent, action_family_digest, bound_text, normalize_event
from recalith.contracts.common import canonical_json, utf8_len
from recalith.contracts.config import EVENT_PAYLOAD_CAP
from recalith.contracts.events import EventEnvelope, ToolPayload
from recalith.errors import RecalithError


def ctx(tmp_path):
    return f.context(tmp_path)


def tool_raw(key="t1", *, argv=("pytest", "-q"), text="", exit_code=1, outcome="failure", parse_status="exact", kind="tool_finished", **payload_overrides):
    payload = {
        "tool_call_id": "call-1",
        "tool_name": "Bash",
        "arguments": {"command": " ".join(argv)},
        "result_received": kind == "tool_finished",
        "outcome": outcome,
        "exit_code": exit_code,
        "result_text": text,
        "action": {"cwd_path": ".", "tool": "Bash", "action_kind": "test" if parse_status != "unknown" else "unknown", "executable": argv[0] if parse_status != "unknown" else None, "argv": list(argv) if parse_status != "unknown" else None, "paths": [], "raw_digest": None, "parse_status": parse_status, "shell": "bash"},
        "observation": None,
    }
    payload.update(payload_overrides)
    return RawEvent(adapter_id=f.ADAPTER, adapter_version="2.1.301", source_event_key=key, session_id=f.SESSION, host_session_id="h", kind=kind, payload=payload)


def one(tmp_path, raw):
    (env,), notes = normalize_event(ctx(tmp_path), raw)
    return env, notes


# ------------------------------------------------------------------ A68 head/tail


def test_head_tail_keeps_failure_line_with_original_offsets(tmp_path):
    noise = "".join(f"line {i} ✓ résumé 漢字 🎉\n" for i in range(6000))  # ~200 KB, multi-byte throughout
    tail = "FAILED tests/test_parse.py::test_dates - AssertionError: 2026 != 2025\n=== 1 failed, 341 passed in 4.21s ===\n"
    original = noise + tail
    env, notes = one(tmp_path, tool_raw(text=original))
    payload = ToolPayload.model_validate(env.payload)
    assert env.coverage.truncated and notes.warnings["result_text_bounded"] == 1
    assert len(canonical_json(env.payload)) <= EVENT_PAYLOAD_CAP
    head, tail_chunk = payload.text_chunks
    assert (head.stored_field, tail_chunk.stored_field) == ("result_text_head", "result_text_tail")
    for chunk in payload.text_chunks:
        assert original[chunk.original_start : chunk.original_end] == chunk.text  # exact original coordinates
    assert head.original_start == 0 and tail_chunk.original_end == len(original)
    assert utf8_len(head.text) <= 8192 and utf8_len(tail_chunk.text) <= 8192
    assert utf8_len(head.text) > 8192 - 4 and utf8_len(tail_chunk.text) > 8192 - 4  # cut on code-point boundaries
    assert tail in tail_chunk.text
    omitted = tail_chunk.original_start - head.original_end
    assert payload.result_text == head.text + f"\n[recalith: {omitted} code points omitted]\n" + tail_chunk.text
    assert payload.error_signature == "FAILED tests/test_parse.py::test_dates - AssertionError: 2026 != 2025"
    session = [a for a in payload.assertions if a.identity == "pytest:session"]
    assert session and session[0].value == "1 failed, 341 passed" and session[0].passed is False
    json.dumps(env.payload, ensure_ascii=False).encode("utf-8")  # valid UTF-8 throughout


def test_short_output_is_kept_whole(tmp_path):
    env, _ = one(tmp_path, tool_raw(text="=== 2 passed in 0.10s ===", exit_code=0, outcome="success"))
    assert env.payload["result_text"] == "=== 2 passed in 0.10s ===" and env.payload["text_chunks"] == []
    assert not env.coverage.truncated and env.payload["error_signature"] is None


def test_bound_text_never_splits_a_code_point():
    text = "🎉" * 5000  # 4 bytes each
    bounded = bound_text(text, source_field="result_text")
    head, tail = bounded.chunks
    assert utf8_len(head["text"]) == 8192 and utf8_len(tail["text"]) == 8192
    assert head["original_end"] == 2048 and tail["original_start"] == 5000 - 2048


def test_structured_fields_take_priority_over_diagnostic_text(tmp_path):
    big_args = {"command": "x" * 30000, "note": "y" * 30000}
    env, notes = one(tmp_path, tool_raw(text="z" * 100000, arguments=big_args))
    assert len(canonical_json(env.payload)) <= EVENT_PAYLOAD_CAP
    assert env.coverage.truncated
    payload = ToolPayload.model_validate(env.payload)
    for chunk in payload.text_chunks:
        assert chunk.text == "z" * len(chunk.text)


def test_oversized_signature_line_is_not_clipped(tmp_path):
    text = "Ran 1 test in 0.01s\nValueError: " + "v" * 2000 + "\nFAILED (errors=1)"
    env, _ = one(tmp_path, tool_raw(argv=("python", "-m", "unittest"), text=text))
    assert env.payload["error_signature"] is None  # an exact line >1 KiB is not retained
    text2 = "Traceback...\nModuleNotFoundError: No module named 'ledgerlite'\n\nRan 3 tests in 0.01s\n\nFAILED (errors=1)"
    env2, _ = one(tmp_path, tool_raw("t2", argv=("python", "-m", "unittest"), text=text2))
    assert env2.payload["error_signature"] == "ModuleNotFoundError: No module named 'ledgerlite'"


# ------------------------------------------------------------------ certified assertions (A52) and expected_red (A66)


def test_untrusted_assertions_and_expected_red_hint_are_dropped(tmp_path):
    fake = [{"kind": "test_result", "identity": "all", "value": "passed", "passed": True}]
    env, notes = one(tmp_path, tool_raw(text="whatever", argv=("make", "test"), assertions=fake, expected_red=True, error_signature="made up"))
    assert env.payload["expected_red"] is False
    assert notes.warnings["expected_red_hint_dropped"] == 1 and notes.warnings["untrusted_assertions_dropped"] == 1
    assert env.payload["assertions"] == [parsers.exit_status_assertion(1)]  # only the structured exit code
    assert env.payload["error_signature"] is None


def test_strict_envelope_still_rejects_expected_red_true(tmp_path):
    env, _ = one(tmp_path, tool_raw(text="x"))
    data = env.model_dump(mode="json")
    data["payload"]["expected_red"] = True
    data["payload_digest"] = f.digest_of(data["payload"])
    with pytest.raises(ValueError):
        EventEnvelope.model_validate(data)


@pytest.mark.parametrize(
    "argv, parse_status, text, expected",
    [
        (("python", "--version"), "exact", "Python 3.12.4", {"python_version": "3.12.4"}),
        (("/usr/bin/python3.12", "-V"), "exact", "Python 3.12.4\n", {"python_version": "3.12.4"}),
        (("node", "--version"), "exact", "v20.11.1", {"node_version": "20.11.1"}),
        (("echo", "Python", "3.9.0"), "exact", "Python 3.9.0", {}),  # not a version command
        (("python", "--version"), "unknown", "Python 3.12.4", {}),  # ambiguous parse certifies nothing
        (("python", "--version", "--verbose"), "exact", "Python 3.12.4", {}),
        (("python", "--version"), "exact", "Python 3.12.4\nPython 3.11.0", {}),
    ],
)
def test_runtime_versions_only_from_certified_exact_invocations(tmp_path, argv, parse_status, text, expected):
    env, _ = one(tmp_path, tool_raw(argv=argv, parse_status=parse_status, text=text, exit_code=0, outcome="success"))
    parsed = {a["identity"]: a["value"] for a in env.payload["assertions"] if a["kind"] == "parsed_value"}
    assert parsed == expected


def test_failed_version_command_certifies_nothing(tmp_path):
    env, notes = one(tmp_path, tool_raw(argv=("python", "--version"), text="Python 3.12.4", exit_code=1, outcome="failure"))
    assert [a["kind"] for a in env.payload["assertions"]] == ["exit_status"]
    assert not env.coverage.parser_complete and "parser_unrecognized:python_version@1" in notes.warnings


def test_unrecognized_output_marks_parser_coverage_incomplete(tmp_path):
    env, _ = one(tmp_path, tool_raw(text="pytest crashed before printing a summary"))
    assert not env.coverage.parser_complete
    assert [a["kind"] for a in env.payload["assertions"]] == ["exit_status"]


def test_tool_started_has_no_result(tmp_path):
    env, _ = one(tmp_path, tool_raw(kind="tool_started", text="ignored", exit_code=3, outcome="failure"))
    assert env.payload["result_received"] is False and env.payload["outcome"] == "unknown"
    assert env.payload["exit_code"] is None and env.payload["result_text"] is None and env.payload["assertions"] == []


def test_action_family_digest_rules():
    exact = {"cwd_path": "pkg/a", "tool": "Bash", "executable": "pytest", "argv": ["pytest", "-q"], "parse_status": "exact"}
    assert action_family_digest(f.WORKSPACE, exact) == action_family_digest(f.WORKSPACE, dict(exact))
    assert action_family_digest(f.WORKSPACE, exact) != action_family_digest(f.WORKSPACE, dict(exact, cwd_path="pkg/b"))
    assert action_family_digest(f.WORKSPACE, dict(exact, cwd_path=None)) is None
    assert action_family_digest(f.WORKSPACE, dict(exact, parse_status="conservative")) is None


# ------------------------------------------------------------------ environment allowlist (A54)


def test_platform_environment_keeps_only_registered_scalars(tmp_path):
    raw = RawEvent(
        adapter_id=f.ADAPTER, adapter_version="1", source_event_key="s1", session_id=f.SESSION, host_session_id="h", kind="session_started",
        payload={"source": "startup", "environment": {"os": "linux", "arch": "aarch64", "ci": "true", "python_version": "3.13.1", "HOME": "/home/alice", "OPENAI_API_KEY": "sk-proj-" + "q" * 30, "node_version": "/opt/node/bin/node"}},
    )
    env, notes = one(tmp_path, raw)
    assert env.payload["environment"] == {"os": "linux", "arch": "aarch64", "ci": "true"}
    assert notes.warnings["environment_dropped:<unregistered>"] == 2
    assert notes.warnings["environment_dropped:python_version"] == 1 and notes.warnings["environment_dropped:node_version"] == 1
    serialized = canonical_json(env).decode()
    for value in ("/home/alice", "sk-proj-", "3.13.1", "/opt/node", "HOME", "OPENAI_API_KEY"):
        assert value not in serialized


# ------------------------------------------------------------------ routing, identity, Unicode, partitioning


def test_uncertified_sources_never_carry_user_or_tool_authority(tmp_path):
    raw = RawEvent(adapter_id="generic", adapter_version="1", source_event_key="u1", session_id=f.SESSION, host_session_id="h", kind="user_message", payload={"text": "decide X"}, certified=False)
    env, _ = one(tmp_path, raw)
    assert (env.channel, env.authority) == ("user", "untrusted")
    tool, _ = one(tmp_path, RawEvent(**{**tool_raw().__dict__, "certified": False}))
    assert tool.authority == "untrusted"


def test_operator_kinds_are_refused_from_adapters(tmp_path):
    raw = RawEvent(adapter_id=f.ADAPTER, adapter_version="1", source_event_key="d", session_id=f.SESSION, host_session_id="h", kind="operator_declaration", payload={"statement": "x"})
    with pytest.raises(RecalithError, match="policy_refused"):
        normalize_event(ctx(tmp_path), raw)


def test_secret_in_identity_field_is_refused_without_echo(tmp_path):
    secret = "ghp_" + "k" * 36
    raw = RawEvent(adapter_id=f.ADAPTER, adapter_version="1", source_event_key=f"key-{secret}", session_id=f.SESSION, host_session_id="h", kind="user_message", payload={"text": "hi"})
    with pytest.raises(RecalithError) as exc:
        normalize_event(ctx(tmp_path), raw)
    assert exc.value.code == "policy_refused" and secret not in str(exc.value)


def test_lone_surrogates_are_replaced(tmp_path):
    raw = RawEvent(adapter_id=f.ADAPTER, adapter_version="1", source_event_key="u", session_id=f.SESSION, host_session_id="h", kind="user_message", payload={"text": "bad \ud800 char"})
    env, notes = one(tmp_path, raw)
    assert env.payload["text"] == "bad � char" and notes.warnings["invalid_unicode_replaced"] == 1


def test_large_message_is_partitioned_with_original_offsets(tmp_path):
    text = "".join(f"paragraph {i}: ñandú 🦤 " * 3 for i in range(5000))
    raw = RawEvent(adapter_id=f.ADAPTER, adapter_version="1", source_event_key="big", session_id=f.SESSION, host_session_id="h", kind="user_message", payload={"text": text})
    envelopes, notes = normalize_event(ctx(tmp_path), raw)
    assert len(envelopes) >= 4 and notes.warnings["message_partitioned"] == len(envelopes)
    assert [e.source_event_key for e in envelopes] == ["big"] + [f"big#p{i}" for i in range(1, len(envelopes))]
    rebuilt = ""
    for index, env in enumerate(envelopes):
        part = env.payload["text_part"]
        assert part["index"] == index and part["count"] == len(envelopes)
        assert text[part["original_start"] : part["original_end"]] == env.payload["text"]
        assert len(canonical_json(env.payload)) <= EVENT_PAYLOAD_CAP
        rebuilt += env.payload["text"]
    assert rebuilt == text and len({e.event_id for e in envelopes}) == len(envelopes)


def test_normalization_is_deterministic_for_duplicate_detection(tmp_path):
    a, _ = one(tmp_path, tool_raw(text="x" * 50000 + "\n=== 1 failed in 1.0s ==="))
    b, _ = one(tmp_path, tool_raw(text="x" * 50000 + "\n=== 1 failed in 1.0s ==="))
    assert a.event_id == b.event_id and a.payload_digest == b.payload_digest
