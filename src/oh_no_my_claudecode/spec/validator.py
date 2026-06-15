"""Conformance validator for the .agent-memory/ open spec (version 1).

Validates that a .agent-memory/ directory produced by any conformant writer
matches the Agent Memory Format Specification (AGENT-MEMORY-SPEC.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models.attempt import AttemptKind, AttemptStatus
from oh_no_my_claudecode.models.memory import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory_artifact import MemoryArtifactType
from oh_no_my_claudecode.models.task import TaskStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPEC_VERSION = "1"
"""Current Agent Memory Format Specification version."""

SUPPORTED_VERSIONS = frozenset({"1"})
"""All format versions this validator can check."""

_MEMORY_KIND_VALUES = frozenset(k.value for k in MemoryKind)
_SOURCE_TYPE_VALUES = frozenset(s.value for s in SourceType)
_STALENESS_VALUES: frozenset[str] = frozenset({"fresh", "stale", "orphaned", "unanchored"})
_TASK_STATUS_VALUES = frozenset(s.value for s in TaskStatus)
_ATTEMPT_KIND_VALUES = frozenset(k.value for k in AttemptKind)
_ATTEMPT_STATUS_VALUES = frozenset(s.value for s in AttemptStatus)
_ARTIFACT_TYPE_VALUES = frozenset(t.value for t in MemoryArtifactType)

# Required fields per record type (must be present and non-None / non-missing).
_MANIFEST_REQUIRED = frozenset({"version", "repo_root", "exported_at", "onmc_version", "counts"})
_COUNTS_REQUIRED = frozenset({"memories", "tasks", "attempts", "artifacts"})
_MEMORY_REQUIRED = frozenset(
    {
        "id",
        "kind",
        "title",
        "summary",
        "details",
        "source_type",
        "source_ref",
        "tags",
        "confidence",
        "feedback_score",
        "created_at",
        "updated_at",
    }
)
_TASK_REQUIRED = frozenset(
    {
        "task_id",
        "title",
        "description",
        "status",
        "created_at",
        "repo_root",
        "branch",
    }
)
_ATTEMPT_REQUIRED = frozenset(
    {
        "attempt_id",
        "task_id",
        "summary",
        "kind",
        "status",
        "created_at",
    }
)
_ARTIFACT_REQUIRED = frozenset(
    {
        "memory_id",
        "task_id",
        "type",
        "title",
        "summary",
        "why_it_matters",
        "evidence",
        "confidence",
        "created_at",
    }
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class SpecValidationError(ValueError):
    """Raised when validation fails and the caller wants an exception."""


@dataclass
class SpecValidationReport:
    """Outcome of a conformance validation run."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Counters for the pass report
    memories_checked: int = 0
    tasks_checked: int = 0

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.passed = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        status = "PASS" if self.passed else "FAIL"
        lines.append(
            f"[{status}] memories={self.memories_checked} tasks={self.tasks_checked} "
            f"errors={len(self.errors)} warnings={len(self.warnings)}"
        )
        for err in self.errors:
            lines.append(f"  ERROR: {err}")
        for warn in self.warnings:
            lines.append(f"  WARN:  {warn}")
        return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_agent_memory_dir(path: Path) -> SpecValidationReport:
    """Validate that *path* conforms to the Agent Memory Format Specification.

    Returns a :class:`SpecValidationReport`. ``report.passed`` is ``True`` iff
    no errors were found. Warnings do not affect the pass/fail outcome.

    Validation is non-fatal: it collects all errors before returning so callers
    get the full picture rather than failing on the first problem.
    """
    report = SpecValidationReport(passed=True)

    if not path.exists():
        report.add_error(f"Directory does not exist: {path}")
        return report

    if not path.is_dir():
        report.add_error(f"Path is not a directory: {path}")
        return report

    manifest = _validate_manifest(path, report)
    if manifest is None:
        # Cannot proceed without a valid manifest.
        return report

    _validate_memories(path, manifest, report)
    _validate_tasks(path, manifest, report)

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path, report: SpecValidationReport, label: str) -> dict | None:  # type: ignore[type-arg]
    """Load and parse a JSON file; record an error and return None on failure."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.add_error(f"Cannot read {label}: {exc}")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.add_error(f"Invalid JSON in {label}: {exc}")
        return None
    if not isinstance(data, dict):
        report.add_error(f"{label} must be a JSON object, got {type(data).__name__}")
        return None
    return data


def _check_required(
    obj: dict,  # type: ignore[type-arg]
    required: frozenset[str],
    label: str,
    report: SpecValidationReport,
) -> bool:
    """Return True iff all required keys are present; record errors otherwise."""
    missing = required - obj.keys()
    if missing:
        report.add_error(f"{label}: missing required fields: {sorted(missing)}")
        return False
    return True


def _check_enum(
    obj: dict,  # type: ignore[type-arg]
    field_name: str,
    allowed: frozenset[str],
    label: str,
    report: SpecValidationReport,
) -> None:
    value = obj.get(field_name)
    if value is not None and value not in allowed:
        report.add_error(
            f"{label}: invalid {field_name!r} value {value!r}; "
            f"allowed: {sorted(allowed)}"
        )


def _check_nullable_enum(
    obj: dict,  # type: ignore[type-arg]
    field_name: str,
    allowed: frozenset[str],
    label: str,
    report: SpecValidationReport,
) -> None:
    """Validate an enum field that may be null/None."""
    value = obj.get(field_name)
    if value is not None and value not in allowed:
        report.add_error(
            f"{label}: invalid {field_name!r} value {value!r}; "
            f"allowed: {sorted(allowed)} or null"
        )


def _validate_manifest(
    base: Path,
    report: SpecValidationReport,
) -> dict | None:  # type: ignore[type-arg]
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        report.add_error("manifest.json is missing")
        return None

    manifest = _load_json(manifest_path, report, "manifest.json")
    if manifest is None:
        return None

    if not _check_required(manifest, _MANIFEST_REQUIRED, "manifest.json", report):
        return None

    version = manifest.get("version")
    if version not in SUPPORTED_VERSIONS:
        report.add_error(
            f"manifest.json: unsupported version {version!r}; "
            f"this validator supports: {sorted(SUPPORTED_VERSIONS)}"
        )
        return None

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        report.add_error("manifest.json: 'counts' must be an object")
        return None

    if not _check_required(counts, _COUNTS_REQUIRED, "manifest.json.counts", report):
        return None

    for count_field in ("memories", "tasks", "attempts", "artifacts"):
        val = counts.get(count_field)
        if not isinstance(val, int) or val < 0:
            report.add_error(
                f"manifest.json.counts.{count_field}: must be a non-negative integer, got {val!r}"
            )

    return manifest


def _validate_memories(
    base: Path,
    manifest: dict,  # type: ignore[type-arg]
    report: SpecValidationReport,
) -> None:
    memories_dir = base / "memories"
    if not memories_dir.exists():
        expected = manifest.get("counts", {}).get("memories", 0)
        if expected > 0:
            report.add_error(
                f"memories/ directory is missing but manifest.counts.memories={expected}"
            )
        return

    memory_files = sorted(memories_dir.glob("*/*.json"))

    for mem_path in memory_files:
        label = f"memories/{mem_path.parent.name}/{mem_path.name}"
        data = _load_json(mem_path, report, label)
        if data is None:
            continue

        if "memory" not in data:
            report.add_error(f"{label}: top-level key 'memory' is missing")
            continue

        mem = data["memory"]
        if not isinstance(mem, dict):
            report.add_error(f"{label}: 'memory' must be an object")
            continue

        if not _check_required(mem, _MEMORY_REQUIRED, label, report):
            continue

        _check_enum(mem, "kind", _MEMORY_KIND_VALUES, label, report)
        _check_enum(mem, "source_type", _SOURCE_TYPE_VALUES, label, report)
        _check_nullable_enum(mem, "staleness", _STALENESS_VALUES, label, report)

        # Validate confidence range
        confidence = mem.get("confidence")
        if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
            report.add_error(
                f"{label}: 'confidence' must be a float in [0.0, 1.0], got {confidence!r}"
            )

        # Validate kind matches directory
        kind_dir = mem_path.parent.name
        declared_kind = mem.get("kind")
        if declared_kind is not None and declared_kind != kind_dir:
            report.add_error(
                f"{label}: 'kind' is {declared_kind!r} but file is in {kind_dir!r}/ directory"
            )

        report.memories_checked += 1

    # Cross-check count
    expected_count = manifest.get("counts", {}).get("memories", 0)
    actual_count = len(memory_files)
    if actual_count != expected_count:
        report.add_warning(
            f"manifest.counts.memories={expected_count} but found {actual_count} memory file(s)"
        )


def _validate_tasks(
    base: Path,
    manifest: dict,  # type: ignore[type-arg]
    report: SpecValidationReport,
) -> None:
    tasks_dir = base / "tasks"
    if not tasks_dir.exists():
        expected = manifest.get("counts", {}).get("tasks", 0)
        if expected > 0:
            report.add_error(
                f"tasks/ directory is missing but manifest.counts.tasks={expected}"
            )
        return

    task_files = sorted(tasks_dir.glob("*.json"))
    total_attempts = 0
    total_artifacts = 0

    for task_path in task_files:
        label = f"tasks/{task_path.name}"
        data = _load_json(task_path, report, label)
        if data is None:
            continue

        # Validate task object
        if "task" not in data:
            report.add_error(f"{label}: top-level key 'task' is missing")
            continue

        task = data["task"]
        if not isinstance(task, dict):
            report.add_error(f"{label}: 'task' must be an object")
            continue

        if _check_required(task, _TASK_REQUIRED, f"{label}.task", report):
            _check_enum(task, "status", _TASK_STATUS_VALUES, f"{label}.task", report)

        # Validate attempts array
        attempts = data.get("attempts", [])
        if not isinstance(attempts, list):
            report.add_error(f"{label}: 'attempts' must be an array")
        else:
            for idx, attempt in enumerate(attempts):
                a_label = f"{label}.attempts[{idx}]"
                if not isinstance(attempt, dict):
                    report.add_error(f"{a_label}: must be an object")
                    continue
                if _check_required(attempt, _ATTEMPT_REQUIRED, a_label, report):
                    _check_enum(attempt, "kind", _ATTEMPT_KIND_VALUES, a_label, report)
                    _check_enum(attempt, "status", _ATTEMPT_STATUS_VALUES, a_label, report)
                total_attempts += 1

        # Validate artifacts array
        artifacts = data.get("artifacts", [])
        if not isinstance(artifacts, list):
            report.add_error(f"{label}: 'artifacts' must be an array")
        else:
            for idx, artifact in enumerate(artifacts):
                art_label = f"{label}.artifacts[{idx}]"
                if not isinstance(artifact, dict):
                    report.add_error(f"{art_label}: must be an object")
                    continue
                if _check_required(artifact, _ARTIFACT_REQUIRED, art_label, report):
                    _check_enum(artifact, "type", _ARTIFACT_TYPE_VALUES, art_label, report)
                total_artifacts += 1

        report.tasks_checked += 1

    # Cross-check counts
    expected_tasks = manifest.get("counts", {}).get("tasks", 0)
    if len(task_files) != expected_tasks:
        report.add_warning(
            f"manifest.counts.tasks={expected_tasks} but found {len(task_files)} task file(s)"
        )

    expected_attempts = manifest.get("counts", {}).get("attempts", 0)
    if total_attempts != expected_attempts:
        report.add_warning(
            f"manifest.counts.attempts={expected_attempts} but found {total_attempts} attempt(s)"
        )

    expected_artifacts = manifest.get("counts", {}).get("artifacts", 0)
    if total_artifacts != expected_artifacts:
        report.add_warning(
            f"manifest.counts.artifacts={expected_artifacts} "
            f"but found {total_artifacts} artifact(s)"
        )
