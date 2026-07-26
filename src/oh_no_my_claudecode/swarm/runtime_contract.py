"""Canonical runtime contract for swarm fan-out/fan-in manifests."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from oh_no_my_claudecode.runtime.contracts import (
    Budget,
    CapabilitySet,
    NodeSpec,
    RetryPolicy,
    RunSpec,
)


@dataclass(frozen=True, slots=True)
class SwarmContractUnit:
    """Minimal unit shape needed to compile a swarm into a runtime graph."""

    unit_id: str
    goal: str
    verify_command: str | None = None
    allowed_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()


def build_swarm_run_spec(
    *,
    swarm_id: str,
    units: tuple[SwarmContractUnit, ...],
    agent: str,
    mode: str,
    concurrency: int,
    max_cost_usd: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float = 1200.0,
) -> RunSpec:
    """Compile one swarm manifest into a canonical ONMC runtime graph.

    The unit nodes are independent and therefore fan out in parallel. The final
    ``fan-in`` node depends on every unit and represents the deterministic ledger
    join: every unit must end in a receipt-backed status before the swarm itself
    is accounted for.
    """
    unit_nodes = tuple(
        NodeSpec(
            node_id=unit.unit_id,
            kind="swarm-unit",
            objective=unit.goal,
            completion_condition=(
                f"{unit.unit_id} records a receipt-backed terminal status for: "
                f"{unit.goal[:160]}"
            ),
            dependencies=(),
            side_effecting=True,
            approval_required=False,
            idempotency_key=f"{swarm_id}:unit:{unit.unit_id}",
            timeout_seconds=timeout_seconds,
            budget=Budget(
                timeout_seconds=timeout_seconds,
                max_cost_usd=max_cost_usd,
                max_tokens=max_tokens,
            ),
            retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0.0),
            capabilities=_unit_capabilities(agent, unit.verify_command),
            metadata={
                "agent": agent,
                "allowed_paths": list(unit.allowed_paths),
                "mode": mode,
                "protected_paths": list(unit.protected_paths),
                "swarm_id": swarm_id,
            },
        )
        for unit in units
    )
    fan_in = NodeSpec(
        node_id="fan-in",
        kind="swarm-fan-in",
        objective="Integrate unit receipts into the swarm manifest.",
        completion_condition=(
            "All swarm units have terminal receipt-backed status and aggregate "
            "stop_reason is recorded."
        ),
        dependencies=tuple(unit.unit_id for unit in units),
        side_effecting=True,
        approval_required=False,
        idempotency_key=f"{swarm_id}:fan-in",
        timeout_seconds=60.0,
        budget=Budget(timeout_seconds=60.0),
        retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0.0),
        capabilities=CapabilitySet(tools=("swarm-ledger",), filesystem_write=True),
        metadata={
            "concurrency": concurrency,
            "mode": mode,
            "swarm_id": swarm_id,
            "units": len(units),
        },
    )
    return RunSpec(
        run_id=f"swarm-{swarm_id}",
        task=f"Execute {len(units)} swarm unit(s) with bounded fan-out and fan-in.",
        nodes=unit_nodes + (fan_in,),
        metadata={
            "concurrency": concurrency,
            "mode": mode,
            "source": "swarm.runtime_contract",
            "swarm_id": swarm_id,
        },
    )


def _unit_capabilities(agent: str, verify_command: str | None) -> CapabilitySet:
    commands: tuple[tuple[str, ...], ...] = ()
    if verify_command:
        argv = tuple(shlex.split(verify_command))
        if argv:
            commands = (argv,)
    return CapabilitySet(
        tools=(agent,),
        commands=commands,
        filesystem_write=True,
    )


__all__ = ["SwarmContractUnit", "build_swarm_run_spec"]
