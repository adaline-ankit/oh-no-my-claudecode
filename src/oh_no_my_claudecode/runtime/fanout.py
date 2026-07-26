"""Dependency-aware fan-out planning for canonical runtime graphs."""

from __future__ import annotations

from oh_no_my_claudecode.runtime.contracts import NodeSpec, RunSpec, RuntimeContractError


def dependency_layers(spec: RunSpec) -> tuple[tuple[NodeSpec, ...], ...]:
    """Group a ``RunSpec`` into deterministic dependency-ready execution layers.

    Nodes in the same layer have no dependencies on each other and may run in
    parallel. Layer and node order are stable: ties preserve the source order
    from the original ``RunSpec``.
    """
    by_id = {node.node_id: node for node in spec.nodes}
    source_index = {node.node_id: index for index, node in enumerate(spec.nodes)}
    completed: set[str] = set()
    remaining = set(by_id)
    layers: list[tuple[NodeSpec, ...]] = []
    while remaining:
        ready_ids = sorted(
            (
                node_id
                for node_id in remaining
                if all(dependency in completed for dependency in by_id[node_id].dependencies)
            ),
            key=source_index.__getitem__,
        )
        if not ready_ids:
            raise RuntimeContractError("runtime graph has no dependency-ready nodes")
        layers.append(tuple(by_id[node_id] for node_id in ready_ids))
        completed.update(ready_ids)
        remaining.difference_update(ready_ids)
    return tuple(layers)


__all__ = ["dependency_layers"]
