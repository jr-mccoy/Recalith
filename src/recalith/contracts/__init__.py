"""Strict worker/service contracts (DATA_CONTRACTS).

Importing this package imports Pydantic. Synchronous hook code under
``recalith.fast`` must never import it (SYSTEM_SPEC §5.1.1).
"""

from . import common, config, context, events, health, jobs, memory, operations, privacy, transfers

__all__ = ["common", "config", "context", "events", "health", "jobs", "memory", "operations", "privacy", "transfers"]
