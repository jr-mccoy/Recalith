"""Recalith: autonomous memory for one project.

This package initializer is deliberately import-light: synchronous hook entry
points under ``recalith.fast`` must not transitively import Pydantic or other
heavy modules through it (SYSTEM_SPEC §5.1.1).
"""

__version__ = "0.1.0.dev0"
