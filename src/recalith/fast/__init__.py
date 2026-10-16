"""Standard-library hook fast path (SYSTEM_SPEC §5.1.1; DATA_CONTRACTS §2.3).

Everything under ``recalith.fast`` imports only the Python standard library
and other ``recalith.fast`` modules: never Pydantic, ``packaging``, SQLite
writes, the service/CLI layers, provider code or optional extras. This
initializer deliberately imports nothing, so ``import recalith.fast.entry``
loads only what the hook needs. ``tests/platform/test_hook_imports.py``
inspects the real transitive import inventory in fresh processes.
"""
