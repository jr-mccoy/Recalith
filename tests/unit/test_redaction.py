"""Task 3: credential scrubbing before durable capture (A34)."""

from __future__ import annotations

import json

import pytest

from recalith.capture import redact

CASES = {
    "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END " + "RSA PRIVATE KEY-----",
    "anthropic_key": "sk-ant-api03-" + "a" * 40,
    "openai_key": "sk-proj-" + "B" * 30,
    "github_token": "ghp_" + "c" * 36,
    "aws_access_key_id": "AKIA" + "ABCDEFGHIJKLMNOP",
    "slack_token": "xox" + "b-1234567890-abcdefghij",
    "google_api_key": "AIza" + "d" * 35,
    "stripe_key": "sk_live_" + "e" * 24,
    "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJ" + "zdWIiOiJ0ZXN0In0." + "c2lnbmF0dXJlLWZha2U",
}


@pytest.mark.parametrize("kind", sorted(CASES))
def test_token_formats_are_replaced(kind):
    secret = CASES[kind]
    out, report = redact.scrub_text(f"before {secret} after")
    assert secret not in out and f"[REDACTED:{kind}]" in out
    assert out.startswith("before ") and out.endswith(" after")
    assert report.counts == {kind: 1}


@pytest.mark.parametrize(
    "text, kind, kept",
    [
        ("https://deploy:hunter2pass@example.com/x", "url_credential", "https://deploy:"),
        ("Authorization: Bearer abcdefghijklmnop123", "authorization", "Authorization: Bearer "),
        ("curl -H 'X: y' bearer abcdefghijklmnopqrstu", "bearer_token", "bearer "),
        ("mysql --password=s3cr3tvalue -u root", "cli_secret", "--password="),
        ("tool --api-key  kq83jd92kd", "cli_secret", "--api-key  "),
        ("export DB_PASSWORD=correct-horse", "assignment", "DB_PASSWORD="),
        ('{"client_secret": "abc123xyz"}', "assignment", '"client_secret": '),
        ("AUTH_TOKEN: 'quoted value here'", "assignment", "AUTH_TOKEN: "),
    ],
)
def test_contextual_secrets_keep_their_key(text, kind, kept):
    out, report = redact.scrub_text(text)
    assert kept in out and f"[REDACTED:{kind}]" in out and report.counts.get(kind) == 1


@pytest.mark.parametrize(
    "text",
    [
        "max_tokens=500 and tokens: 12",
        "author: Jane Doe",
        "the password is wrong, try again",
        "export GITHUB_TOKEN=$GITHUB_TOKEN",
        "token=${CI_TOKEN}",
        "password=***",
        "keyboard=us",
        "sk-short",
    ],
)
def test_ordinary_text_and_references_are_untouched(text):
    out, report = redact.scrub_text(text)
    assert out == text and report.total == 0


def test_scrubbing_is_idempotent_and_reports_only_kinds():
    text = " ".join(CASES.values()) + " password=abc123 https://u:p4ss@host"
    once, report = redact.scrub_text(text)
    twice, again = redact.scrub_text(once)
    assert once == twice and again.total == 0
    dumped = json.dumps(report.counts)
    for secret in CASES.values():
        assert secret not in dumped


def test_json_keys_values_and_nested_structures():
    value = {
        "api_key": "plain-looking-value",
        "apiKey": "another",
        "headers": {"Authorization": "Basic Zm9vOmJhcg=="},
        "token_count": "12",
        "items": ["safe", "ghp_" + "x" * 36],
        "ghp_" + "y" * 36: "key itself is a token",
        "password": "",
        "secret": "$SECRET_REF",
    }
    out, report = redact.scrub_json(value)
    assert out["api_key"] == out["apiKey"] == "[REDACTED:sensitive_field]"
    assert out["headers"]["Authorization"] == "[REDACTED:sensitive_field]"
    assert out["token_count"] == "12"  # not a credential name
    assert out["items"] == ["safe", "[REDACTED:github_token]"]
    assert "[REDACTED:github_token]" in out and out["password"] == "" and out["secret"] == "$SECRET_REF"
    assert redact.scrub_json(out)[1].total == 0


@pytest.mark.parametrize("key, sensitive", [("password", True), ("db_password", True), ("ApiKey", True), ("client_secret", True), ("refresh_token", True), ("password_hint", False), ("token_count", False), ("author", False), ("auth_method", False), ("keyboard", False)])
def test_sensitive_key_names(key, sensitive):
    assert redact.sensitive_key(key) is sensitive


def test_truncated_private_key_is_still_removed():
    text = "start\n-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n(output truncated)"
    out, _ = redact.scrub_text(text)
    assert out == "start\n[REDACTED:private_key]"


def test_recalith_markers_are_never_rescrubbed():
    # A bounded result_text whose head ends at "token=" must survive a capture-time re-scrub.
    text = "run --x\ntoken=\n[recalith: 1008 code points omitted]\nzzz"
    out, report = redact.scrub_text(text)
    assert out == text and report.total == 0
