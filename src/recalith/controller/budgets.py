"""UTC-day model budgets and output bounds (SYSTEM_SPEC §6.3; DATA_CONTRACTS §8).

Each installation has one ledger per UTC day in ``provider_usage``: one
:class:`BudgetReservation` per model invocation. The daily totals (default
90 calls, 900,000 input and 180,000 output estimates) are split into a
*protected* reserve (30 / 300,000 / 60,000) for ``review_claims``, correction
review and ``revalidate``, and the *ordinary* remainder (60 / 600,000 /
120,000). Protected purposes take the protected pool first and may borrow
whatever ordinary capacity remains; ordinary purposes never touch the
protected pool. Priority changes the order of launches, never these limits.

Before every launch the worker reserves the actual estimated request size
(``ceil(UTF-8 bytes / 3)``, labeled an estimate) plus the purpose's fixed
output allowance (1,500 task narrative; 8,000 episode/extraction; 3,000
review/revalidation). A reservation that does not fit is not made, and the
job waits with a visible ``budget_exhausted:<pool>.<dimension>`` reason. Every
launched attempt is charged, failures included. After the call the
reservation is *charged*: provider-reported usage replaces the local estimate
when it is returned; an answered call without reported output is charged its
measured body estimate; an interrupted call with unknown usage keeps the whole
reservation. Overage beyond a reservation is charged too, so it pauses further
calls and stays visible rather than being forgiven.

Output is bounded twice and separately: the raw host stdout (wire) at
256 KiB while reading, and the decoded logical JSON body at ``3 ×`` the
reserved output allowance, counted in its original UTF-8 bytes before strict
parsing. Neither is ever compacted or clipped to pass.

90 is only the call ceiling: twelve 8,000-token extractions plus sixteen
1,500-token task narratives (120,000) and twenty 3,000-token reviews (60,000)
fully reserve the output pools after 48 calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from recalith.contracts.common import new_id
from recalith.contracts.config import MODEL_INPUT_CAP, PROTECTED_PURPOSES, PURPOSE_OUTPUT_ALLOWANCE, STDERR_CAP, WIRE_STDOUT_CAP, BudgetConfig, body_cap_for, estimate_tokens
from recalith.contracts.jobs import BudgetReservation, LocalUsage, PoolAllocation
from recalith.contracts.operations import ModelProposalBody, UsageReport, parse_model_body
from recalith.storage.db import Txn

DIMENSIONS = ("invocations", "input_estimate", "output_estimate")
POOLS = ("protected", "ordinary")
MAX_INPUT_ESTIMATE = estimate_tokens(MODEL_INPUT_CAP)


@dataclass(frozen=True)
class Amounts:
    invocations: int = 0
    input_estimate: int = 0
    output_estimate: int = 0

    def __add__(self, other: "Amounts") -> "Amounts":
        return Amounts(self.invocations + other.invocations, self.input_estimate + other.input_estimate, self.output_estimate + other.output_estimate)

    def __sub__(self, other: "Amounts") -> "Amounts":
        return Amounts(self.invocations - other.invocations, self.input_estimate - other.input_estimate, self.output_estimate - other.output_estimate)

    def get(self, dim: str) -> int:
        return getattr(self, dim)

    def as_dict(self) -> dict[str, int]:
        return {d: self.get(d) for d in DIMENSIONS}


def pool_limits(config: BudgetConfig) -> dict[str, Amounts]:
    protected = Amounts(config.protected_invocations, config.protected_input_estimate, config.protected_output_estimate)
    total = Amounts(config.daily_invocations, config.daily_input_estimate, config.daily_output_estimate)
    return {"protected": protected, "ordinary": total - protected}


def utc_day(now: str) -> str:
    return now[:10]


def is_protected(purpose: str) -> bool:
    return purpose in PROTECTED_PURPOSES


# --------------------------------------------------------------------------
# Charged amounts per reservation


def actual_usage(res: BudgetReservation) -> tuple[int, int]:
    """(input, output) charged for a reservation in state ``charged``."""
    reported, local = res.reported_usage, res.local_estimated_usage
    if reported is not None and reported.input_tokens is not None:
        input_used = reported.input_tokens
    elif local is not None:
        input_used = local.input_estimate
    else:
        input_used = res.estimated_input_limit
    if reported is not None and reported.output_tokens is not None:
        output_used = reported.output_tokens
    elif local is not None:
        output_used = local.output_estimate
    else:
        output_used = res.estimated_output_limit  # interrupted with unknown usage: the reservation stays charged
    return input_used, output_used


def _split(amount: int, protected_alloc: int, ordinary_alloc: int, *, overage_to: str) -> tuple[int, int]:
    """Charge the protected allocation first, then ordinary; overage goes to ``overage_to``."""
    p = min(amount, protected_alloc)
    o = min(amount - p, ordinary_alloc)
    rest = amount - p - o
    return (p + rest, o) if overage_to == "protected" else (p, o + rest)


def charged_by_pool(res: BudgetReservation) -> dict[str, Amounts]:
    """What this reservation currently consumes from each pool."""
    if res.state == "released":
        return {"protected": Amounts(), "ordinary": Amounts()}
    if res.state == "reserved":
        return {
            "protected": Amounts(res.protected.invocations, res.protected.input_estimate, res.protected.output_estimate),
            "ordinary": Amounts(res.ordinary.invocations, res.ordinary.input_estimate, res.ordinary.output_estimate),
        }
    input_used, output_used = actual_usage(res)
    overage_to = "protected" if res.protected.invocations else "ordinary"
    p_in, o_in = _split(input_used, res.protected.input_estimate, res.ordinary.input_estimate, overage_to=overage_to)
    p_out, o_out = _split(output_used, res.protected.output_estimate, res.ordinary.output_estimate, overage_to=overage_to)
    return {"protected": Amounts(res.protected.invocations, p_in, p_out), "ordinary": Amounts(res.ordinary.invocations, o_in, o_out)}


def reservations(view: Any, day: str) -> list[BudgetReservation]:
    rows = view.execute("SELECT body FROM provider_usage WHERE utc_day = ? ORDER BY rowid", (day,)).fetchall()
    return [BudgetReservation.model_validate_json(r[0]) for r in rows]


def used_by_pool(view: Any, day: str) -> dict[str, Amounts]:
    used = {"protected": Amounts(), "ordinary": Amounts()}
    for res in reservations(view, day):
        for pool, amount in charged_by_pool(res).items():
            used[pool] = used[pool] + amount
    return used


# --------------------------------------------------------------------------
# Planning a reservation


@dataclass(frozen=True)
class Plan:
    protected: Amounts
    ordinary: Amounts


@dataclass(frozen=True)
class Refusal:
    reason: str  # budget_exhausted:<pool>.<dimension>


def plan(purpose: str, input_estimate: int, *, used: Mapping[str, Amounts], limits: Mapping[str, Amounts]) -> Plan | Refusal:
    """Allocate one invocation's reservation across the pools, or say why it cannot fit."""
    output = PURPOSE_OUTPUT_ALLOWANCE[purpose]
    remaining = {pool: limits[pool] - used[pool] for pool in POOLS}
    ordinary = remaining["ordinary"]
    if not is_protected(purpose):
        for dim, need in (("invocations", 1), ("input_estimate", input_estimate), ("output_estimate", output)):
            if need > ordinary.get(dim):
                return Refusal(f"budget_exhausted:ordinary.{dim}")
        return Plan(protected=Amounts(), ordinary=Amounts(1, input_estimate, output))
    protected = remaining["protected"]
    alloc_p: dict[str, int] = {}
    alloc_o: dict[str, int] = {}
    for dim, need in (("invocations", 1), ("input_estimate", input_estimate), ("output_estimate", output)):
        take_p = min(need, max(protected.get(dim), 0))
        if dim == "invocations" and take_p < need:
            take_p = 0  # an invocation is indivisible: protected, or else ordinary
        take_o = need - take_p
        if take_o > max(ordinary.get(dim), 0):
            return Refusal(f"budget_exhausted:protected+ordinary.{dim}")
        alloc_p[dim], alloc_o[dim] = take_p, take_o
    return Plan(protected=Amounts(**alloc_p), ordinary=Amounts(**alloc_o))


def fits_lower_bound(purpose: str, *, used: Mapping[str, Amounts], limits: Mapping[str, Amounts]) -> Refusal | None:
    """Can any request of this purpose fit (one input estimate plus its output allowance)?"""
    result = plan(purpose, 1, used=used, limits=limits)
    return result if isinstance(result, Refusal) else None


def reserve(txn: Txn, *, job_id: str, purpose: str, input_estimate: int, now: str, config: BudgetConfig) -> BudgetReservation | Refusal:
    """Insert a ``reserved`` reservation inside the caller's (fenced) transaction."""
    if not 0 < input_estimate <= MAX_INPUT_ESTIMATE:
        return Refusal("model_input_oversized")
    day = utc_day(now)
    result = plan(purpose, input_estimate, used=used_by_pool(txn, day), limits=pool_limits(config))
    if isinstance(result, Refusal):
        return result
    output = PURPOSE_OUTPUT_ALLOWANCE[purpose]
    res = BudgetReservation(
        reservation_id=new_id("rsv"),
        job_id=job_id,
        invocation_id=new_id("inv"),
        utc_day=day,
        purpose=purpose,
        ordinary=PoolAllocation(**result.ordinary.as_dict()),
        protected=PoolAllocation(**result.protected.as_dict()),
        estimated_input_limit=input_estimate,
        estimated_output_limit=output,
        max_response_body_bytes=body_cap_for(purpose),
        state="reserved",
    )
    txn.execute(
        "INSERT INTO provider_usage (reservation_id, job_id, invocation_id, utc_day, purpose, state, provider_id, model, body) VALUES (?, ?, ?, ?, ?, 'reserved', NULL, NULL, ?)",
        (res.reservation_id, job_id, res.invocation_id, day, purpose, res.model_dump_json()),
    )
    txn.mutated(serving_relevant=False)
    return res


def get_reservation(view: Any, reservation_id: str) -> BudgetReservation | None:
    row = view.execute("SELECT body FROM provider_usage WHERE reservation_id = ?", (reservation_id,)).fetchone()
    return None if row is None else BudgetReservation.model_validate_json(row[0])


def charge(txn: Txn, reservation_id: str, *, reported: UsageReport | None, local: LocalUsage | None, provider_id: str | None = None, model: str | None = None) -> BudgetReservation:
    """Settle a launched reservation; only a known smaller usage releases capacity."""
    res = get_reservation(txn, reservation_id)
    if res is None:
        raise KeyError(reservation_id)
    if res.state != "reserved":
        return res  # already settled (idempotent)
    settled = res.model_copy(update={"state": "charged", "reported_usage": reported, "local_estimated_usage": local})
    settled = BudgetReservation.model_validate(settled.model_dump())
    txn.execute(
        "UPDATE provider_usage SET state = 'charged', provider_id = COALESCE(?, provider_id), model = COALESCE(?, model), body = ? WHERE reservation_id = ?",
        (provider_id, model, settled.model_dump_json(), reservation_id),
    )
    txn.mutated(serving_relevant=False)
    return settled


def charge_interrupted(txn: Txn, *, keep: Iterable[str] = ()) -> int:
    """Settle every unsettled reservation (a worker died mid-call): unknown usage keeps the reservation."""
    keep = set(keep)
    count = 0
    for (reservation_id,) in txn.execute("SELECT reservation_id FROM provider_usage WHERE state = 'reserved'").fetchall():
        if reservation_id not in keep:
            charge(txn, reservation_id, reported=None, local=None)
            count += 1
    return count


# --------------------------------------------------------------------------
# Output bounds (worker side of A30)


class OutputRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_wire(stdout: bytes, *, overflowed: bool) -> None:
    """The raw host envelope is bounded at 256 KiB while reading; overflow is a rejection."""
    if overflowed or len(stdout) > WIRE_STDOUT_CAP:
        raise OutputRejected("wire_stdout_oversized")


def decode_body(body: bytes, reservation: BudgetReservation) -> ModelProposalBody:
    """Count the decoded body's original UTF-8 bytes against ``3 ×`` the allowance, then parse strictly."""
    if len(body) > reservation.max_response_body_bytes:
        raise OutputRejected("response_body_oversized")
    try:
        return parse_model_body(body, purpose=reservation.purpose, body_cap=reservation.max_response_body_bytes)
    except ValueError:
        raise OutputRejected("response_invalid") from None


# --------------------------------------------------------------------------
# Visible summaries (status/health inputs)


def summary(view: Any, day: str, config: BudgetConfig) -> dict[str, Any]:
    """Per-pool use and remaining capacity, exhausted dimensions and per-purpose totals."""
    limits = pool_limits(config)
    used = {"protected": Amounts(), "ordinary": Amounts()}
    per_purpose: dict[str, dict[str, int]] = {}
    states: dict[str, int] = {}
    for res in reservations(view, day):
        states[res.state] = states.get(res.state, 0) + 1
        charged = charged_by_pool(res)
        for pool in POOLS:
            used[pool] = used[pool] + charged[pool]
        total = charged["protected"] + charged["ordinary"]
        entry = per_purpose.setdefault(res.purpose, {"calls": 0, "input_estimate": 0, "output_estimate": 0})
        entry["calls"] += total.invocations
        entry["input_estimate"] += total.input_estimate
        entry["output_estimate"] += total.output_estimate
    pools = {}
    for pool in POOLS:
        remaining = limits[pool] - used[pool]
        pools[pool] = {"limit": limits[pool].as_dict(), "used": used[pool].as_dict(), "remaining": remaining.as_dict(), "exhausted": [d for d in DIMENSIONS if remaining.get(d) <= 0], "overage": [d for d in DIMENSIONS if remaining.get(d) < 0]}
    return {"utc_day": day, "pools": pools, "per_purpose": per_purpose, "reservation_states": states, "estimates_are_local": True}


def waiting_reasons(job_bodies: Iterable[str]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for body in job_bodies:
        code = json.loads(body).get("last_error_code")
        if code:
            reasons[code] = reasons.get(code, 0) + 1
    return reasons


__all__ = [
    "Amounts", "Plan", "Refusal", "OutputRejected", "pool_limits", "utc_day", "plan", "fits_lower_bound", "reserve", "charge",
    "charge_interrupted", "check_wire", "decode_body", "summary", "used_by_pool", "charged_by_pool", "actual_usage", "STDERR_CAP", "WIRE_STDOUT_CAP",
]
