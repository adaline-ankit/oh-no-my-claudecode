"""CycloneDX 1.5 Software Bill of Materials (SBOM) generator for onmc.

``onmc sbom`` generates a CycloneDX 1.5 JSON SBOM of the project's
dependencies, reading from ``uv.lock`` (preferred) or falling back to
``pyproject.toml``. The output is deterministic (components sorted by name),
offline, and requires no new dependencies — parsing uses stdlib ``tomllib``
(Python 3.11+) and ``json``.

The package self-registers via the command auto-discovery hook (see
:mod:`oh_no_my_claudecode.command_registry`) — adding it touches no shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.sbom.core import SbomComponent, build_sbom

__all__ = ["SbomComponent", "build_sbom"]
