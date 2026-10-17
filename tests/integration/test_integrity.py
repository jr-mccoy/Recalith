"""Task 5 integrity: the revision chain is a full-release capability (A65 full variant).

Preview reserves the ``revision_chain`` table and leaves it empty; it never
reports chain or full-row verification. ``storage/integrity.py``, chain
computation and incremental/full verification are not built in this profile,
so the full-only tests below are explicitly unavailable (skipped with their
reason), never passed. The one runnable test pins the preview behavior.
"""

from __future__ import annotations

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
from recalith.contracts.common import new_id
from recalith.contracts.operations import ProposedOperation
from recalith.controller import apply
from recalith.storage import db

FULL_ONLY = pytest.mark.skip(reason="unavailable in claude_preview: the revision hash chain and storage/integrity.py are full-release work (IMPLEMENTATION_PLAN Task 5; A65 full variant)")


def test_preview_revision_chain_is_reserved_and_unpopulated(tmp_path):
    """Real applications, a service write and an undo commit with no chain entries and no integrity module."""
    root = osc.project(tmp_path)
    created = apply.apply_operations(
        osc.operator(root), [ProposedOperation.model_validate(osc.op("c", "propose_claim", osc.claim(osc.ORIGINAL), evidence=[osc.link(root, "fail")]))],
        read_set=osc.read_set(root), submission_id=new_id("op"), now=ws.START,
    )
    preview = apply.preview_undo(osc.context(root), created.operation_ids[0])
    apply.apply_undo(osc.operator(root), created.operation_ids[0], preview_digest=preview.preview_digest, now=ws.START)
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        columns = [r[1] for r in view.execute("PRAGMA table_info(revision_chain)").fetchall()]
        entries = view.execute("SELECT COUNT(*) FROM revision_chain").fetchone()[0]
    assert columns == ["sequence", "previous_hash", "operation_id", "row_digests", "purge_marker", "tombstone_epoch", "entry_hash"]
    assert entries == 0 and osc.meta(root).store_revision > 0
    with pytest.raises(ImportError):
        __import__("recalith.storage.integrity")


@FULL_ONLY
def test_unlogged_row_mutation_is_detected():
    raise AssertionError("full-only")


@FULL_ONLY
def test_authorized_purge_extends_chain():
    raise AssertionError("full-only")


@FULL_ONLY
def test_incremental_verification_reports_range_and_coverage():
    raise AssertionError("full-only")


@FULL_ONLY
def test_full_integrity_checks_every_current_row():
    raise AssertionError("full-only")


@FULL_ONLY
def test_preview_store_gets_an_honest_baseline_when_chain_activates():
    raise AssertionError("full-only")
