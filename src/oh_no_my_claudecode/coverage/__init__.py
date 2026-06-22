"""Coverage analysis: which repo areas does memory actually cover?"""

from __future__ import annotations

from oh_no_my_claudecode.coverage.compiler import (
    CoverageReport,
    SubsystemRow,
    UncoveredHotspot,
    compile_coverage,
)

__all__ = [
    "CoverageReport",
    "SubsystemRow",
    "UncoveredHotspot",
    "compile_coverage",
]
