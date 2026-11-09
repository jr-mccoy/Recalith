# SPDX-License-Identifier: GPL-3.0-only
"""Audit 2026-11-06 Phase 1, item 1.12: small fixes, one test each (decision 0044).

STO-3 read views accept only read pragmas; CTL-8 the stop request is a private file; CAP-11 continuity judges a
paused task by when its pause began; CTL-7 a request names the timeout its launch uses; CAP-13 a source tail whose
every event is refused does not pin its cursor.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
from recalith.contracts.common import format_utc, parse_utc, utc_now
from recalith.controller import worker
from recalith.errors import RecalithError
from recalith.storage import db, records
from recalith.working import tasks


@pytest.fixture
def root(tmp_path):
    return ws.init_project(tmp_path, "proj")


@pytest.mark.parametrize("sql", ["PRAGMA user_version = 99", "PRAGMA user_version(99)", "PRAGMA journal_mode = DELETE", "PRAGMA wal_checkpoint(TRUNCATE)", "PRAGMA optimize", "PRAGMA main.secure_delete = ON", "UPDATE events SET payload = NULL"])
def test_read_views_refuse_writes_including_pragma_writes(root, sql):
    with db.open_store(ws.context(root)) as store, store.read() as view:
        with pytest.raises(RecalithError) as refused:
            view.execute(sql)
        assert refused.value.code == "policy_refused"
        assert view.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION  # unchanged


@pytest.mark.parametrize("sql", ["PRAGMA user_version", "PRAGMA quick_check", "PRAGMA main.table_list", "PRAGMA main.table_info(events)", "PRAGMA foreign_key_check", "SELECT 1", "WITH x AS (SELECT 1) SELECT * FROM x"])
def test_read_views_still_allow_reads(root, sql):
    with db.open_store(ws.context(root)) as store, store.read() as view:
        view.execute(sql).fetchall()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_stop_request_is_a_private_file(root):
    worker.request_stop(root)
    path = root / ".recalith" / "run" / worker.STOP_FILE
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_continuity_judges_a_paused_task_by_when_its_pause_began(tmp_path):
    """A narrative patch to a task paused days ago refreshed ``updated_at`` and made it look freshly paused."""
    from recalith.contracts.memory import TaskState

    root = osc.project(tmp_path)  # a project with captured real sessions, as the operation tests use
    task_id = osc.seed_task(root)
    ctx = ws.context(root)
    now = utc_now()
    long_ago = format_utc(parse_utc(now).replace(year=parse_utc(now).year - 1))
    with db.open_store(ctx) as store, store.transaction() as txn:
        revision = records.head(txn, "task", task_id)[0]
        current = records.load(txn, "task", task_id, revision)
        paused = current.model_copy(update={"revision": revision + 1, "status": "paused", "updated_at": long_ago})
        records.write_task(txn, TaskState.model_validate(paused.model_dump()), workspace_id=ctx.workspace_id)
        patched = paused.model_copy(update={"revision": revision + 2, "title": "Renamed by a later narrative", "updated_at": now})
        records.write_task(txn, TaskState.model_validate(patched.model_dump()), workspace_id=ctx.workspace_id)
        txn.mutated(serving_relevant=True)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        assert records.head(view, "task", task_id) == (revision + 2, "paused")
        assert tasks.paused_at(view, task_id, revision + 2) == long_ago
        assert task_id not in tasks.continuity_candidates(view, ctx.workspace_id, exclude=(), now=now, pause_hours=24)


def test_a_model_request_names_the_timeout_its_launch_uses(root, monkeypatch):
    seen = {}
    from recalith.controller import requests

    real = requests.runtime_preparer

    def spy(ctx, **kw):
        seen.update(kw)
        return real(ctx, **kw)

    monkeypatch.setattr(requests, "runtime_preparer", spy)

    class Supervisor:
        def __init__(self, *a, **k):
            self.backend = object()

    monkeypatch.setattr(worker, "ProviderSupervisor", Supervisor)
    worker.configured_provider(ws.context(root), {})
    assert seen["timeout_seconds"] == worker._project_config(ws.context(root)).budgets.timeout_seconds


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_backup_journal_directory_is_private(root, tmp_path):
    """STO-4: ``run/backups`` (journals naming staging and destination paths) was created with the umask, 0755."""
    from recalith.storage import backup

    backup.create(ws.context(root), tmp_path / "copy")
    journals = root / ".recalith" / "run" / "backups"
    assert journals.is_dir() and stat.S_IMODE(os.stat(journals).st_mode) == 0o700
