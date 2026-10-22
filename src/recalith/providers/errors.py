"""Provider failure types shared by the adapters (no engine imports)."""

from __future__ import annotations


class IsolationViolation(ValueError):
    """The effective launch no longer matches its certification; the backend is disabled.

    ``code`` is a content-free reason (``isolation_tools_exposed``,
    ``host_version_changed``, ``auth_route_mismatch``, ...). A violation is
    never retried through another provider, route or weaker launch.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code[:64]


class ProviderCallFailed(Exception):
    """One provider call produced no acceptable response (``code`` names why); it is charged.

    ``usage`` carries what the provider reported for the failed call (for
    example a reply stopped at the output cap), so the charge uses it.
    """

    def __init__(self, code: str, *, usage: dict | None = None) -> None:
        super().__init__(code)
        self.code = code[:64]
        self.usage = usage
