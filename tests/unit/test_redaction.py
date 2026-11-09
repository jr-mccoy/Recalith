# SPDX-License-Identifier: GPL-3.0-only
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
    "gitlab_token": "glpat-" + "f" * 20,
    "sendgrid_key": "SG." + "g" * 22 + "." + "h" * 43,
    "twilio_key": "SK" + "0123456789abcdef" * 2,
    "aws_secret_key": "abcdEFGH1234/ijklMNOP5678+qrstUVWX9012yz",
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
        # Audit 2026-11-06 (CAP-2, CAP-3): names whose secret word is not the last token, abbreviations,
        # URL passwords with '/', cookie headers, attached mysql passwords, curl basic auth, signed URLs.
        ("SECRET_KEY = 'django-insecure-9f8s7df98s7df'", "assignment", "SECRET_KEY = "),
        ("SECRET_KEY_BASE=3f9a8b7c6d5e4f3a2b1c0d9e", "assignment", "SECRET_KEY_BASE="),
        ("JWT_SIGNING_KEY=AbCdEfGhIjKlMnOp", "assignment", "JWT_SIGNING_KEY="),
        ("ENCRYPTION_KEY=AbCdEfGhIjKlMnOp", "assignment", "ENCRYPTION_KEY="),
        ("DB_PASS=hunter2secret", "assignment", "DB_PASS="),
        ("smtp_pass: hunter2secret", "assignment", "smtp_pass: "),
        ("PGPASSWORD=hunter2secret psql", "assignment", "PGPASSWORD="),
        ("DATABASE_URL=postgres://alice:p/ss+w0rd@db.internal:5432/app", "url_credential", "postgres://alice:"),
        ("< Set-Cookie: session=abc123; Path=/; HttpOnly", "cookie", "Set-Cookie: "),
        ("> Cookie: sessionid=4f9a8b7c; csrftoken=99", "cookie", "Cookie: "),
        ("mysql -u root -pHunter2Secret app", "cli_secret", "mysql -u root -p"),
        ("curl -u alice:S3cretPass https://example.com", "basic_auth", "-u alice:"),
        ("https://acct.blob.core.windows.net/c/b?sv=2020&sig=AbCdEf%2BGhIj", "signed_url", "&sig="),
        ("https://bucket.s3.amazonaws.com/k?X-Amz-Signature=abcdef0123", "signed_url", "X-Amz-Signature="),
    ],
)
def test_contextual_secrets_keep_their_key(text, kind, kept):
    out, report = redact.scrub_text(text)
    assert kept in out and f"[REDACTED:{kind}]" in out and report.counts.get(kind) == 1


def test_authorization_header_keeps_its_scheme_word():
    out, report = redact.scrub_text("Authorization: Bearer abcdefghijklmnop123")
    assert out == "Authorization: Bearer [REDACTED:authorization]" and report.counts == {"authorization": 1}


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
        # Look-alikes the new rules must leave alone (CAP-3, CAP-7).
        "psql --password mydb",
        "pg_dump --password -h db.internal app",
        "mkdir -p build/out",
        "ssh -p 2222 host",
        "docker run -u 1000:1000 image",
        "pip install --user requests",
        "npm view http://localhost:4873/@scope/pkg",
        "test_pass: 12",
        "bypass=true",
        "public_key_path: id_ed25519.pub",
        "Cookies: 3 boxes",
        "src/recalith/controller/WorkerLane2/abcd/e",
        "/Users/Alice/Projects/App2/Assets/Img01/x",
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


@pytest.mark.parametrize(
    "name, sensitive",
    [("SECRET_KEY", True), ("secret_key_base", True), ("JWT_SIGNING_KEY", True), ("ENCRYPTION_KEY", True), ("DB_PASS", True), ("mysql_pass", True),
     ("PGPASSWORD", True), ("oauth", True), ("csrftoken", True), ("test_pass", False), ("pass", False), ("bypass", False), ("password_hint", False), ("primary_key", False)],
)
def test_sensitive_assignment_names(name, sensitive):
    assert redact.sensitive_name(name) is sensitive


def test_json_keys_use_the_same_name_rules_as_text():
    out, _ = redact.scrub_json({"DB_PASS": "x1", "SECRET_KEY": "x2", "pass": "y", "test_pass": "12"})
    assert out == {"DB_PASS": "[REDACTED:sensitive_field]", "SECRET_KEY": "[REDACTED:sensitive_field]", "pass": "y", "test_pass": "12"}


@pytest.mark.parametrize(
    "argv, want",
    [
        # Audit 2026-11-06 (FP-1): a split command line separates a secret flag from its value.
        (["mytool", "--password", "hunter2secret", "--host", "db"], ["mytool", "--password", "[REDACTED:cli_secret]", "--host", "db"]),
        (["deploy", "--api-key", "kq83jd92kd", "--token", "t0k3n"], ["deploy", "--api-key", "[REDACTED:cli_secret]", "--token", "[REDACTED:cli_secret]"]),
        (["curl", "-H", "Authorization: Bearer abcdefghijklmnop123", "https://x"], ["curl", "-H", "Authorization: Bearer [REDACTED:authorization]", "https://x"]),
        (["curl", "-u", "alice:S3cretPass", "https://x"], ["curl", "-u", "alice:[REDACTED:basic_auth]", "https://x"]),
        (["mysql", "-u", "root", "-pHunter2Secret", "app"], ["mysql", "-u", "root", "-p[REDACTED:cli_secret]", "app"]),
        (["tool", "--password=s3cr3tvalue"], ["tool", "--password=[REDACTED:cli_secret]"]),
        # Left alone: a prompt switch, a uid:gid, flags that take no secret, references.
        (["psql", "--password", "mydb"], ["psql", "--password", "mydb"]),
        (["docker", "run", "-u", "1000:1000", "img"], ["docker", "run", "-u", "1000:1000", "img"]),
        (["mkdir", "-p", "out"], ["mkdir", "-p", "out"]),
        (["tool", "--token", "$CI_TOKEN"], ["tool", "--token", "$CI_TOKEN"]),
    ],
)
def test_argv_is_scrubbed_across_neighbouring_elements(argv, want):
    out, report = redact.scrub_argv(argv)
    assert out == want and len(out) == len(argv)
    assert redact.scrub_argv(out)[0] == out  # idempotent
    # The same rule applies wherever an `argv` array sits in a scrubbed JSON payload.
    assert redact.scrub_json({"action": {"argv": argv}})[0] == {"action": {"argv": want}}


@pytest.mark.parametrize(
    "text",
    ["a.key-" * 2730, "a.pass-" * 2340, "x://y:z" * 2340, "key" * 5461, "k" * 16000 + "_key=v"],
    ids=["dotted_keys", "dotted_pass", "url_runs", "repeated_word", "long_name"],
)
def test_scrubbing_stays_linear_on_adversarial_tool_output(text):
    """Found while fixing the audit's Phase 0: on 0.1.0.dev10, 16 KiB of ``a.key-`` took 8.2 s to scrub (two free
    runs around the secret word backtracked quadratically), inside a hook with 250 ms in all. Each case now takes
    a few milliseconds; the bound is loose so a slow runner never flakes, and still catches the quadratic shape."""
    import time

    start = time.perf_counter()
    redact.scrub_text(text)
    assert time.perf_counter() - start < 1.0


def test_every_corpus_shape_scrubs_idempotently():
    corpus = list(CASES.values()) + [
        "SECRET_KEY = 'django-insecure-9f8s7df98s7df'", "DB_PASS=hunter2secret", "postgres://alice:p/ss+w0rd@db/app",
        "Set-Cookie: a=1; b=2", "mysql -pHunter2", "curl -u alice:S3cret x", "https://h/x?sig=abc&y=1", "psql --password mydb",
    ]
    for text in corpus:
        once, _ = redact.scrub_text(text)
        twice, again = redact.scrub_text(once)
        assert twice == once and again.total == 0, text


def test_truncated_private_key_is_still_removed():
    text = "start\n-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n(output truncated)"
    out, _ = redact.scrub_text(text)
    assert out == "start\n[REDACTED:private_key]"


def test_recalith_markers_are_never_rescrubbed():
    # A bounded result_text whose head ends at "token=" must survive a capture-time re-scrub.
    text = "run --x\ntoken=\n[recalith: 1008 code points omitted]\nzzz"
    out, report = redact.scrub_text(text)
    assert out == text and report.total == 0
