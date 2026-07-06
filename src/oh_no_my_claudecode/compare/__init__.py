"""Side-by-side comparison of two swarm runs (``onmc compare``).

Public re-exports mirror the ``postmortem``/``timeline`` package convention:
the pure core lives in :mod:`oh_no_my_claudecode.compare.compare`, the CLI
surface in :mod:`oh_no_my_claudecode.compare.commands` (auto-discovered via
:func:`oh_no_my_claudecode.command_registry.register_feature_commands`).
"""

from __future__ import annotations

from oh_no_my_claudecode.compare.compare import (
    Comparison,
    MetricComparison,
    RunMetrics,
    build_comparison,
    build_run_metrics,
    render_text,
)

__all__ = [
    "Comparison",
    "MetricComparison",
    "RunMetrics",
    "build_comparison",
    "build_run_metrics",
    "render_text",
]
