"""Backend protocol for executing canonical ONMC runtime graphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from oh_no_my_claudecode.runtime.contracts import NodeResult, NodeSpec, RunResult, RunSpec


class NodeHandler(Protocol):
    """Callable that executes one node and returns a typed result."""

    def __call__(self, node: NodeSpec) -> NodeResult:
        """Execute *node* once."""
        ...


class ExecutionBackend(Protocol):
    """A graph executor behind ONMC's stable runtime contract."""

    def execute(
        self,
        spec: RunSpec,
        handlers: Mapping[str, NodeHandler],
        *,
        resume: bool = False,
    ) -> RunResult:
        """Execute or resume *spec* with node-id keyed handlers."""
        ...
