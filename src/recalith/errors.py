"""Service error type shared by every layer.

Standard library only, so the fast hook path may raise or translate it without
importing the Pydantic contracts.
"""

from __future__ import annotations

# Stable error codes (IMPLEMENTATION_PLAN Task 1, DATA_CONTRACTS §12).
ERROR_CODES = frozenset(
    {
        "foreign_installation",
        "invalid_schema",
        "revision_conflict",
        "capability_unavailable",
        "storage_failure",
        "policy_refused",
        "not_captured",
        "capability_degraded",
        "event_identity_conflict",
        "backup_unavailable_after_forget",
        # Added in Task 2 (decision 0003): a moved or copied checkout needs operator action.
        "installation_relocated",
    }
)

# CLI exit codes for the codes above (DATA_CONTRACTS §12).
EXIT_CODES = {
    "invalid_schema": 2,
    "revision_conflict": 3,
    "capability_unavailable": 4,
    "installation_relocated": 4,
    "storage_failure": 5,
    "policy_refused": 6,
    "not_captured": 7,
    "capability_degraded": 8,
}


class RecalithError(Exception):
    """A service failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unregistered RecalithError code: {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, 5)
