"""Pure SBOM generation logic — no CLI, no side effects.

Reads dependency metadata from ``uv.lock`` (preferred) or falls back to
``pyproject.toml`` when no lockfile is present.  Produces a CycloneDX 1.5
JSON-serialisable dict.

All parsing uses stdlib only (``tomllib``, ``json``, ``re``, ``datetime``).
No network calls, no new pip dependencies.

CycloneDX 1.5 spec:
  https://cyclonedx.org/docs/1.5/json/
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SAFE_PURL_NAME = re.compile(r"[^A-Za-z0-9._-]")
"""Characters that are NOT safe in a PyPI purl name segment."""


def _normalise_purl_name(name: str) -> str:
    """Normalise a package name for use in a ``pkg:pypi/`` purl.

    PyPI purl convention: lowercase, hyphens only (no underscores).
    See https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#pypi
    """
    return name.lower().replace("_", "-").replace(".", "-")


def _purl(name: str, version: str) -> str:
    """Build a ``pkg:pypi/<name>@<version>`` package URL."""
    return f"pkg:pypi/{_normalise_purl_name(name)}@{version}"


def _self_version(repo_root: Path) -> str:
    """Return the project version from pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        return str(data.get("project", {}).get("version", "0.0.0"))
    return "0.0.0"


def _self_name(repo_root: Path) -> str:
    """Return the project name from pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        return str(data.get("project", {}).get("name", "unknown"))
    return "unknown"


def _serial(repo_root: Path) -> int:
    """Deterministic serial number derived from the repo root path hash."""
    digest = hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()
    return int(digest[:8], 16)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class SbomComponent:
    """A single resolved dependency in the SBOM.

    Fields mirror the CycloneDX 1.5 ``component`` object for a library.
    """

    name: str
    """Canonical package name (as in uv.lock / PyPI)."""
    version: str
    """Pinned version string."""

    def to_cyclonedx(self) -> dict[str, str]:
        """Return a CycloneDX 1.5 ``component`` object (JSON-serialisable)."""
        return {
            "type": "library",
            "name": self.name,
            "version": self.version,
            "purl": _purl(self.name, self.version),
        }


# ---------------------------------------------------------------------------
# Lockfile / pyproject parsers
# ---------------------------------------------------------------------------


def _parse_uv_lock(lock_path: Path) -> list[SbomComponent]:
    """Parse ``uv.lock`` and return one :class:`SbomComponent` per entry.

    ``uv.lock`` is TOML.  Each ``[[package]]`` table has at least ``name`` and
    ``version`` keys.  We parse via ``tomllib``; the resulting dict has a
    ``"package"`` list under the top-level key.

    The project's own entry is included (we filter it out at call-site so the
    SBOM ``components`` list is strictly *dependencies*, not the root).
    """
    with lock_path.open("rb") as fh:
        data = tomllib.load(fh)

    components: list[SbomComponent] = []
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if name and version:
            components.append(SbomComponent(name=name, version=version))
    return components


def _parse_pyproject(pyproject_path: Path) -> list[SbomComponent]:
    """Extract declared dependencies from ``pyproject.toml``.

    This is a *best-effort* fallback when no lockfile is available.  We only
    read ``project.dependencies`` (and optional-dependency groups) and strip the
    version specifiers, so the result may be unpinned (version = "unknown").

    The format is PEP 508: ``"requests>=2.0,<3"`` → name ``requests``,
    version ``unknown`` (we cannot resolve without the resolver).
    """
    dep_split = re.compile(r"[>=<!;,\[]")

    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    raw_deps: list[str] = list(project.get("dependencies", []))
    for extras in project.get("optional-dependencies", {}).values():
        raw_deps.extend(extras)

    seen: set[str] = set()
    components: list[SbomComponent] = []
    for dep in raw_deps:
        name_raw = dep_split.split(dep.strip(), maxsplit=1)[0].strip()
        if not name_raw or name_raw in seen:
            continue
        seen.add(name_raw)
        components.append(SbomComponent(name=name_raw, version="unknown"))
    return components


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_sbom(repo_root: Path) -> dict[str, Any]:
    """Build a CycloneDX 1.5 SBOM dict for the project at *repo_root*.

    **Source priority:**
    1. ``uv.lock`` — preferred; fully pinned, deterministic.
    2. ``pyproject.toml`` — fallback; declared deps only, unpinned.
    3. Empty components list — if neither file exists (graceful).

    The root project itself appears only in ``metadata.component``.
    Dependencies appear in ``components`` sorted alphabetically by name.

    Returns a JSON-serialisable :class:`dict` conforming to CycloneDX 1.5.
    """
    lock_path = repo_root / "uv.lock"
    pyproject_path = repo_root / "pyproject.toml"

    proj_name = _self_name(repo_root)
    proj_version = _self_version(repo_root)

    if lock_path.exists():
        raw_components = _parse_uv_lock(lock_path)
        # Exclude the root project itself from the components list.
        components = sorted(
            (c for c in raw_components if c.name.lower() != proj_name.lower()),
            key=lambda c: c.name.lower(),
        )
    elif pyproject_path.exists():
        raw_components = _parse_pyproject(pyproject_path)
        components = sorted(raw_components, key=lambda c: c.name.lower())
    else:
        components = []

    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "serialNumber": f"urn:uuid:onmc-sbom-{_serial(repo_root):08x}",
        "metadata": {
            "timestamp": timestamp,
            "tools": [
                {
                    "vendor": "onmc",
                    "name": "oh-no-my-claudecode",
                    "version": _self_version(repo_root),
                }
            ],
            "component": {
                "type": "application",
                "name": proj_name,
                "version": proj_version,
                "purl": _purl(proj_name, proj_version),
            },
        },
        "components": [c.to_cyclonedx() for c in components],
    }
