"""The typed-state measurement's arrival model (ACCEPTANCE_TESTS §7; decision 0022).

Arrivals are placed at a uniformly random phase of an *idle* worker's 5-second
cycle. The cycle must be read from an idle status written after the previous
trial reached typed state: until the ingesting poll writes its own status, the
file still holds the idle status from before it, and a plan made from that one
puts the next arrival in the 1-second active window after ingestion and records
a phase against a cycle that already ended. That is what made Windows' measured
cycle look 1-1.5 s longer than its cadence.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import measure_worker_latency as mwl  # noqa: E402


def _status(last_poll_wall: float, *, state: str = "idle", worked: bool = False) -> dict:
    return {"state": state, "poll": {"last_poll_wall": last_poll_wall, "last_poll_worked": worked, "idle_seconds": 5}, "counters": {"polls": 1}}


def test_a_status_from_before_the_previous_trial_is_not_a_settled_idle_cycle(monkeypatch, tmp_path):
    previous_done = 1000.0
    stream = iter([_status(996.0), _status(1000.4, state="running", worked=True), _status(1001.4)])
    current = {"s": None}

    def read_status(_root):
        return current["s"]

    monkeypatch.setattr(mwl.worker, "read_status", read_status)
    current["s"] = next(stream)  # still the idle poll before the ingesting one
    assert mwl.idle_status(tmp_path, after=previous_done) is None
    current["s"] = next(stream)  # the ingesting poll
    assert mwl.idle_status(tmp_path, after=previous_done) is None
    current["s"] = next(stream)  # the first idle poll after typed state
    assert mwl.idle_status(tmp_path, after=previous_done)["poll"]["last_poll_wall"] == 1001.4


def test_the_first_trial_takes_any_idle_status(monkeypatch, tmp_path):
    monkeypatch.setattr(mwl.worker, "read_status", lambda _root: _status(5.0))
    assert mwl.idle_status(tmp_path) is not None
