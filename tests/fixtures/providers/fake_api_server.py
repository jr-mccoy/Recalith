"""A loopback fake model API for tests (never a certification subject, never a real network call).

``FakeProvider`` is a threaded HTTP(S) server on 127.0.0.1 owned by the test.
It answers the Anthropic Messages dialect on paths ending ``/messages`` and
the OpenAI Chat Completions dialect on paths ending ``/chat/completions``,
and records every request exactly as received (method, path with query,
header names and values, raw body bytes). Credentials sent to it are
placeholder values built by the tests themselves.

Behaviors (``FakeProvider.behavior``):
  ok            a valid no-op body; a requested output cap below 100 tokens is honored
                (stop at the cap with the dialect's cap reason)
  narrative     answers the real ModelRequest in the user message (``fake_backend.narrative_body``)
  episode       a valid 15 KB build_episode body
  malformed     a 200 response whose JSON is cut off
  truncated     declares a longer Content-Length than it sends, then closes
  non_json      a 200 HTML page
  refusal       the dialect's refusal shape
  cap           stops at the output cap (stop_reason max_tokens / finish_reason length)
  cap_ignored   ignores the cap: a natural stop with 500 reported output tokens
  other_model   reports a different model than the one requested
  no_usage      omits usage
  tool_use      returns a tool call
  thinking      Messages: an empty ``thinking`` block (with a signature) before the text, as current
                thinking-by-default models reply with the default ``omitted`` display (decision 0027)
  thinking_summary   Messages: a ``thinking`` block holding summarized reasoning text, then the text
  redacted_thinking  Messages: a ``redacted_thinking`` block, then the text
  thinking_only      Messages: a ``thinking`` block and no text block
  thinking_two_text  Messages: a ``thinking`` block and two text blocks
  thinking_tool      Messages: a ``thinking`` block, the text and a tool call
  redirect      307 to another loopback path
  status:N      HTTP status N with a small JSON error body
  hang          never answers (until the server closes)
  flood         a 600 KiB body
"""

from __future__ import annotations

import http.server
import json
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_backend  # noqa: E402

NOOP = json.dumps({"operations": [], "no_op_reason": "nothing new"})


def dialect_of(path: str) -> str:
    bare = path.split("?", 1)[0]
    return "messages" if bare.endswith("/messages") else "chat_completions"


def user_text(dialect: str, body: dict) -> str:
    messages = body.get("messages") or []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def requested_cap(body: dict) -> int | None:
    for key in ("max_tokens", "max_completion_tokens"):
        if type(body.get(key)) is int:
            return body[key]
    return None


THINKING_SUMMARY = "SUMMARIZED-REASONING-NOT-A-BODY: weigh the fixture first."


def compose(dialect: str, *, model: Any, text: str | None, stop: str, output_tokens: int | None, usage: bool = True, tool: bool = False, refusal: bool = False, thinking: str | None = None, texts: int = 1) -> dict:
    if dialect == "messages":
        content: list[dict] = []
        if thinking == "redacted":
            content.append({"type": "redacted_thinking", "data": "redacted-fake-opaque"})
        elif thinking is not None:
            content.append({"type": "thinking", "thinking": thinking, "signature": "sig-fake"})
        if text is not None:
            content.extend({"type": "text", "text": text} for _ in range(texts))
        if tool:
            content.append({"type": "tool_use", "id": "toolu_fake", "name": "read_file", "input": {}})
        reason = {"stop": "end_turn", "cap": "max_tokens", "refusal": "refusal", "tool": "tool_use"}[stop]
        out: dict[str, Any] = {"id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": content, "stop_reason": reason, "stop_sequence": None}
        if usage:
            out["usage"] = {"input_tokens": 40, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 2, "output_tokens": output_tokens}
        return out
    message: dict[str, Any] = {"role": "assistant", "content": text, "refusal": "I can't help with that." if refusal else None}
    if tool:
        message["tool_calls"] = [{"id": "call_fake", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
    reason = {"stop": "stop", "cap": "length", "refusal": "stop", "tool": "tool_calls"}[stop]
    out = {"id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": model, "choices": [{"index": 0, "message": message, "finish_reason": reason}]}
    if usage:
        out["usage"] = {"prompt_tokens": 45, "completion_tokens": output_tokens, "total_tokens": 45 + (output_tokens or 0), "prompt_tokens_details": {"cached_tokens": 2}}
    return out


class FakeProvider:
    """``with FakeProvider() as fake:`` serves on ``fake.base_url`` until the block ends."""

    def __init__(self, behavior: str = "ok", *, delay: float = 0.0, tls: ssl.SSLContext | None = None, host: str = "127.0.0.1") -> None:
        self.behavior = behavior
        self.delay = delay
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._closing = threading.Event()
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                self._send(404, b"{}")

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                record = {"method": "POST", "path": self.path, "headers": [(k, v) for k, v in self.headers.items()], "body": raw}
                with fake._lock:
                    fake.requests.append(record)
                if fake.delay:
                    time.sleep(fake.delay)
                fake.answer(self, raw)

            def _send(self, status: int, data: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.send_header("request-id", "req_fake")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        self.Handler = Handler
        self._server = http.server.ThreadingHTTPServer((host, 0), Handler)
        self._server.daemon_threads = True
        if tls is not None:
            self._server.socket = tls.wrap_socket(self._server.socket, server_side=True)
        self.scheme = "https" if tls is not None else "http"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def url(self, path: str) -> str:
        return self.base_url + path

    def __enter__(self) -> "FakeProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._closing.set()
        self._server.shutdown()
        self._server.server_close()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.requests)

    # ------------------------------------------------------------------ replies

    def answer(self, handler: Any, raw: bytes) -> None:
        behavior = self.behavior
        dialect = dialect_of(handler.path)
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        model = body.get("model")
        cap = requested_cap(body)
        if behavior == "hang":
            self._closing.wait(3600)
            return
        if behavior.startswith("status:"):
            code = int(behavior.split(":", 1)[1])
            handler._send(code, json.dumps({"type": "error", "error": {"type": "fake_error", "message": "fake"}}).encode(), extra={"retry-after": "1"} if code == 429 else None)
            return
        if behavior == "redirect":
            handler._send(307, b"", extra={"location": self.url("/elsewhere")})
            return
        if behavior == "non_json":
            handler._send(200, b"<html><body>gateway</body></html>", "text/html")
            return
        if behavior == "truncated":
            data = json.dumps(compose(dialect, model=model, text=NOOP, stop="stop", output_tokens=5)).encode()
            handler.send_response(200)
            handler.send_header("content-type", "application/json")
            handler.send_header("content-length", str(len(data) + 500))
            handler.end_headers()
            handler.wfile.write(data[: len(data) // 2])
            handler.wfile.flush()
            handler.close_connection = True
            return
        if behavior == "flood":
            handler._send(200, b"{\"pad\": \"" + b"z" * (600 * 1024) + b"\"}")
            return
        text, stop, out_tokens, kwargs = NOOP, "stop", 7, {}
        if behavior == "narrative":
            try:
                text = fake_backend.narrative_body(json.loads(user_text(dialect, body)))
            except ValueError:
                text = NOOP
        elif behavior == "episode":
            text = fake_backend.body_episode(15_600)
            out_tokens = 5000
        elif behavior == "malformed":
            handler._send(200, json.dumps(compose(dialect, model=model, text=NOOP, stop="stop", output_tokens=5)).encode()[:-7])
            return
        elif behavior == "refusal":
            stop, kwargs = ("refusal", {"refusal": True}) if dialect == "messages" else ("refusal", {"refusal": True})
            text = None if dialect != "messages" else ""
        elif behavior == "cap":
            stop, out_tokens = "cap", cap
            text = NOOP[:20]
        elif behavior == "cap_ignored":
            out_tokens = 500
            text = json.dumps({"operations": [], "no_op_reason": "x" * 1500})
        elif behavior == "other_model":
            model = f"{model}-substitute"
        elif behavior == "no_usage":
            kwargs = {"usage": False}
        elif behavior == "tool_use":
            stop, kwargs = "tool", {"tool": True}
        elif behavior == "thinking":
            kwargs, out_tokens = {"thinking": ""}, 61  # thinking tokens are billed as output
        elif behavior == "thinking_summary":
            kwargs, out_tokens = {"thinking": THINKING_SUMMARY}, 61
        elif behavior == "redacted_thinking":
            kwargs, out_tokens = {"thinking": "redacted"}, 61
        elif behavior == "thinking_only":
            kwargs, text = {"thinking": ""}, None
        elif behavior == "thinking_two_text":
            kwargs = {"thinking": "", "texts": 2}
        elif behavior == "thinking_tool":
            stop, kwargs = "tool", {"thinking": "", "tool": True}
        elif behavior == "ok" and cap is not None and cap < 100:
            stop, out_tokens, text = "cap", cap, "word " * cap
        handler._send(200, json.dumps(compose(dialect, model=model, text=text, stop=stop, output_tokens=out_tokens, **kwargs)).encode())


def make_tls(tmp: Path) -> tuple[ssl.SSLContext, Path] | None:
    """A throwaway CA and loopback server certificate made with the openssl CLI (None when unavailable)."""
    import shutil
    import subprocess

    openssl = shutil.which("openssl")
    if openssl is None:
        return None
    tmp.mkdir(parents=True, exist_ok=True)
    ca_key, ca_crt, key, csr, crt, ext = (tmp / n for n in ("ca.key", "ca.crt", "srv.key", "srv.csr", "srv.crt", "ext.cnf"))
    ext.write_text("subjectAltName=IP:127.0.0.1,DNS:localhost\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\n", encoding="utf-8")
    ca_ext = tmp / "ca.cnf"
    ca_ext.write_text("[req]\ndistinguished_name=dn\nx509_extensions=v3\n[dn]\n[v3]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n", encoding="utf-8")
    steps = [
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(ca_key), "-out", str(ca_crt), "-days", "2", "-subj", "/CN=recalith-test-ca", "-config", str(ca_ext)],
        [openssl, "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", "/CN=127.0.0.1"],
        [openssl, "x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(crt), "-days", "2", "-extfile", str(ext)],
    ]
    for step in steps:
        if subprocess.run(step, capture_output=True, timeout=60).returncode != 0:
            return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt), str(key))
    return ctx, ca_crt


__all__ = ["FakeProvider", "make_tls", "compose", "NOOP"]
