"""The curator's HTTP transport child for direct-API backends (decision 0023).

    python -I http_transport.py   < spec.json

Standard library only, never ``recalith``: the worker launches this file by
path with its own interpreter through ``controller.launch.run_bounded``, so
the timeout and tree kill, the wire/stderr caps, the curator role
environment, the private root, the spawn record and crash reaping all apply.

The parent (``providers.api``) builds the whole request; this child is a
transport only. It reads one JSON specification on stdin::

    {"transport_schema": 1, "method": "POST", "url": ..., "headers": {...},
     "auth": {"header": "x-api-key"|"authorization"|"api-key", "scheme": "raw"|"bearer", "env_key": NAME} | null,
     "body": "<exact request body>", "timeout_seconds": N, "max_response_bytes": N, "echo": {...}}

adds the credential from its own environment *by name* (never from the
specification), sends the request exactly once and writes one JSON header line
followed by the raw response body::

    {"transport_schema": 1, "outcome": "response"|"transport_error", "status": N,
     "headers": {...a few named response headers...}, "reason": CODE|null,
     "overflow": bool, "tls": {...}, "echo": {...}}\\n<body bytes>

Rules this file keeps (and tests audit): ``http`` only to a loopback host;
TLS always verified with the default context (system trust, or a managed
bundle reached only through ``SSL_CERT_FILE``/``SSL_CERT_DIR`` in the
environment); proxies only from the environment, never the platform's system
settings; no redirect is ever followed; no retry. Nothing is written to
stderr except a content-free reason for an internal failure, and no
credential, header value or body is ever echoed.
"""

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TRANSPORT_SCHEMA = 1
SPEC_CAP = 512 * 1024
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
RESPONSE_HEADERS = ("content-type", "request-id", "x-request-id", "retry-after", "location")
USER_AGENT_DEFAULT = "recalith"


def _opener(context):
    """Proxy, HTTP and HTTPS handlers only: no error processor and no redirect handler, so every status,
    a 3xx included, comes back as the final response (a key never moves to another origin)."""
    proxies = urllib.request.getproxies_environment()  # the curator environment only, never system settings
    director = urllib.request.OpenerDirector()
    director.addheaders = []
    for handler in (urllib.request.ProxyHandler(proxies), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(context=context)):
        director.add_handler(handler)
    return director


def _emit(header, body=b""):
    out = sys.stdout.buffer
    out.write(json.dumps(header, sort_keys=True).encode("utf-8") + b"\n")
    out.write(body)
    out.flush()


def _error(reason, echo, **extra):
    _emit({"transport_schema": TRANSPORT_SCHEMA, "outcome": "transport_error", "status": None, "reason": reason, "headers": {}, "overflow": False, "tls": None, "echo": echo, **extra})


def _classify(exc):
    """A content-free reason for a failure that produced no HTTP response."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError):
            return "tls_verification_failed"
        if isinstance(exc, ssl.SSLError):
            return "tls_handshake_failed"
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return "provider_timeout"
        if isinstance(exc, ConnectionError) or isinstance(exc, socket.gaierror):
            return "endpoint_unreachable"
        if isinstance(exc, urllib.error.URLError):
            exc = exc.reason if isinstance(exc.reason, BaseException) else None
            continue
        if isinstance(exc, OSError):
            return "endpoint_unreachable"
        exc = exc.__cause__ or exc.__context__
    return "provider_failed"


def _valid(spec):
    if not isinstance(spec, dict) or spec.get("transport_schema") != TRANSPORT_SCHEMA or spec.get("method") != "POST":
        return False
    if not isinstance(spec.get("url"), str) or not isinstance(spec.get("body"), str) or not isinstance(spec.get("headers"), dict):
        return False
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in spec["headers"].items()):
        return False
    auth = spec.get("auth")
    if auth is not None and not (isinstance(auth, dict) and auth.get("header") in ("x-api-key", "authorization", "api-key") and auth.get("scheme") in ("raw", "bearer") and isinstance(auth.get("env_key"), str)):
        return False
    return type(spec.get("timeout_seconds")) in (int, float) and type(spec.get("max_response_bytes")) is int and spec["max_response_bytes"] > 0


def main():
    raw = sys.stdin.buffer.read(SPEC_CAP + 1)
    try:
        spec = json.loads(raw.decode("utf-8")) if len(raw) <= SPEC_CAP else None
    except ValueError:
        spec = None
    if not _valid(spec):
        sys.stderr.write("transport_spec_invalid\n")
        return 2
    echo = spec.get("echo") if isinstance(spec.get("echo"), dict) else {}
    url = spec["url"]
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        _error("insecure_endpoint_refused", echo)
        return 0
    if parts.scheme == "http" and host not in LOOPBACK_HOSTS or parts.scheme not in ("http", "https") or parts.username or parts.password:
        _error("insecure_endpoint_refused", echo)  # checked again here, whatever the parent validated
        return 0
    headers = dict(spec["headers"])
    auth = spec.get("auth")
    if auth is not None:
        value = os.environ.get(auth["env_key"])
        if not value:
            _error("selected_auth_missing", echo)
            return 0
        headers[auth["header"]] = ("Bearer " + value) if auth["scheme"] == "bearer" else value
    context = ssl.create_default_context()  # verification and hostname checking stay on; there is no switch
    request = urllib.request.Request(url, data=spec["body"].encode("utf-8"), headers=headers, method="POST")
    cap = spec["max_response_bytes"]
    try:
        response = _opener(context).open(request, timeout=float(spec["timeout_seconds"]))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a content-free reason
        _error(_classify(exc), echo)
        return 0
    tls = None
    try:
        sock = response.fp.raw._sock if hasattr(response.fp, "raw") else None
        if isinstance(sock, ssl.SSLSocket):
            tls = {"verified": True, "version": sock.version()}
    except AttributeError:
        tls = None
    try:
        status = int(response.status)
        selected = {k: str(response.headers.get(k))[:256] for k in RESPONSE_HEADERS if response.headers.get(k) is not None}
        try:
            body = response.read(cap + 1)
        except Exception as exc:  # noqa: BLE001 - a body cut short (IncompleteRead, reset, timeout)
            _error("provider_response_incomplete" if _classify(exc) == "provider_failed" else _classify(exc), echo, status=status)
            return 0
    finally:
        response.close()
    overflow = len(body) > cap
    declared = response.headers.get("content-length")
    if not overflow and declared is not None and declared.isdigit() and len(body) < int(declared):
        _error("provider_response_incomplete", echo, status=status)  # the server closed before its declared length
        return 0
    _emit({"transport_schema": TRANSPORT_SCHEMA, "outcome": "response", "status": status, "reason": None, "headers": selected, "overflow": overflow, "tls": tls, "echo": echo}, body[:cap])
    return 0


if __name__ == "__main__":
    sys.exit(main())
