"""Deterministically compile task, risk, and diff metadata into a verifier DAG."""

from __future__ import annotations

from oh_no_my_claudecode.proof_graph.models import (
    DiffMetadata,
    Outcome,
    ProofGraph,
    RiskMetadata,
    TaskKind,
    TaskMetadata,
    VerifierKind,
    VerifierNode,
)

_SECURITY_MARKERS = ("auth", "crypto", "permission", "secret", "security", "token")
_BROWSER_SUFFIXES = (".css", ".html", ".jsx", ".tsx", ".vue", ".svelte")
_BROWSER_MARKERS = ("browser", "frontend", "ui/", "web/")
_PERFORMANCE_MARKERS = ("bench", "perf", "benchmark")


def _path_has_marker(paths: tuple[str, ...], markers: tuple[str, ...]) -> bool:
    return any(marker in path.lower() for path in paths for marker in markers)


def _has_browser_path(paths: tuple[str, ...]) -> bool:
    return any(path.lower().endswith(_BROWSER_SUFFIXES) for path in paths) or _path_has_marker(
        paths, _BROWSER_MARKERS
    )


def _targeted_test_argv(paths: tuple[str, ...]) -> tuple[str, ...]:
    tests = tuple(path for path in paths if path.startswith("tests/") and path.endswith(".py"))
    return ("python", "-m", "pytest", "-q", *tests)


def synthesize_proof_graph(
    task: TaskMetadata,
    risk: RiskMetadata,
    diff: DiffMetadata,
) -> ProofGraph:
    """Return a canonical verifier plan without running any command.

    The fixed ordering is also a topological ordering. Optional security,
    browser, and performance nodes are inferred conservatively from either an
    explicit risk bit or well-known changed-path markers.
    """
    if not task.claims:
        raise ValueError("at least one claim is required")
    if not diff.changed_files:
        raise ValueError("at least one changed file is required")
    if not task.task_id.strip():
        raise ValueError("task id must not be empty")
    if not task.summary.strip():
        raise ValueError("task summary must not be empty")

    claim_ids = [claim.claim_id.strip() for claim in task.claims]
    if any(not claim_id for claim_id in claim_ids):
        raise ValueError("claim ids must not be empty")
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim ids must be unique")
    if any(not claim.statement.strip() for claim in task.claims):
        raise ValueError("claim statements must not be empty")

    canonical_task = TaskMetadata(
        task_id=task.task_id.strip(),
        summary=task.summary.strip(),
        kind=task.kind,
        claims=tuple(sorted(task.claims, key=lambda claim: claim.claim_id)),
    )
    canonical_diff = DiffMetadata(
        changed_files=tuple(sorted(set(diff.changed_files))),
        languages=tuple(sorted({language.lower() for language in diff.languages})),
    )

    specifications: list[tuple[VerifierKind, tuple[str, ...], Outcome]] = []
    if task.kind is TaskKind.BUGFIX:
        specifications.append(
            (
                VerifierKind.REPRODUCE,
                _targeted_test_argv(canonical_diff.changed_files),
                Outcome.FAILED,
            )
        )
    specifications.extend(
        [
            (
                VerifierKind.TARGETED_TESTS,
                _targeted_test_argv(canonical_diff.changed_files),
                Outcome.PASSED,
            ),
            (VerifierKind.REGRESSION, ("python", "-m", "pytest", "-q"), Outcome.PASSED),
            (
                VerifierKind.STATIC_ANALYSIS,
                ("python", "-m", "compileall", "-q", "src"),
                Outcome.PASSED,
            ),
            (VerifierKind.TYPE_CHECK, ("mypy", "src"), Outcome.PASSED),
            (VerifierKind.LINT, ("ruff", "check", "."), Outcome.PASSED),
        ]
    )

    paths = canonical_diff.changed_files
    if risk.security or _path_has_marker(paths, _SECURITY_MARKERS):
        specifications.append(
            (VerifierKind.SECURITY, ("python", "-m", "pip_audit"), Outcome.PASSED)
        )
    if risk.browser or _has_browser_path(paths):
        specifications.append(
            (
                VerifierKind.BROWSER,
                ("python", "-m", "pytest", "-q", "-m", "browser"),
                Outcome.PASSED,
            )
        )
    if risk.performance or _path_has_marker(paths, _PERFORMANCE_MARKERS):
        specifications.append(
            (
                VerifierKind.PERFORMANCE,
                ("python", "-m", "pytest", "-q", "-m", "performance"),
                Outcome.PASSED,
            )
        )

    nodes: list[VerifierNode] = []
    previous_id: str | None = None
    for index, (kind, argv, expected) in enumerate(specifications, start=1):
        verifier_id = f"verify:{index:02d}:{kind.value}"
        dependencies = (previous_id,) if previous_id is not None else ()
        nodes.append(VerifierNode(verifier_id, kind, argv, expected, dependencies))
        previous_id = verifier_id

    return ProofGraph(canonical_task, risk, canonical_diff, tuple(nodes))
