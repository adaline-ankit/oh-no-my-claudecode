"""Pure, offline change-rehearsal engine — the repo "digital twin".

Before an agent edits code, it can *rehearse* the change against the structural
code graph: predict the blast radius (which files depend on the touched files),
surface the tests that cover them, and flag high-risk touches (hub nodes with
many dependents).  Nothing here executes code or edits files — a twin is an
analysis of *what would break*, not a sandbox runner.

Everything is deterministic and stdlib-only (plus importing
:mod:`oh_no_my_claudecode.codegraph`, which is itself offline / stdlib-only).
:func:`build_rehearsal` accepts an optional ``neighbors_fn`` so callers (and
tests) can inject a blast-radius lookup; it defaults to the real
:func:`oh_no_my_claudecode.codegraph.neighbors` bound to a freshly-built graph.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.codegraph import Neighbors, build_codegraph, neighbors
from oh_no_my_claudecode.core.repo import is_test_path, relative_path

# A file with at least this many dependents is a "hub" — touching it has wide
# blast radius, so we flag it high-risk regardless of anything else.
HIGH_RISK_DEPENDENTS = 5

# The type of an injectable blast-radius lookup: given a repo-relative target
# path, return its :class:`~oh_no_my_claudecode.codegraph.models.Neighbors`.
NeighborsFn = Callable[[str], Neighbors]

RiskLevel = str  # "high" | "low"


@dataclass(slots=True)
class TouchedFile:
    """The rehearsed impact of touching a single file.

    Fields
    ------
    path:
        Repo-relative POSIX path of the file the agent intends to edit.
    dependents:
        Files that (transitively-one-hop) import this file — the blast radius.
    covering_tests:
        Test files that exercise this file (directly, via import edges).
    risk:
        ``"high"`` when the file is a hub (``>= HIGH_RISK_DEPENDENTS``
        dependents), otherwise ``"low"``.
    resolved:
        Whether the file was found in the code graph.  An unresolved path
        (typo, brand-new file, or graph not yet built) yields an empty,
        low-risk entry rather than an error.
    """

    path: str
    dependents: list[str] = field(default_factory=list)
    covering_tests: list[str] = field(default_factory=list)
    risk: RiskLevel = "low"
    resolved: bool = True

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict (deterministic order)."""
        return {
            "path": self.path,
            "dependents": list(self.dependents),
            "covering_tests": list(self.covering_tests),
            "risk": self.risk,
            "resolved": self.resolved,
        }


@dataclass(slots=True)
class RehearsalPlan:
    """The full rehearsal of a proposed multi-file change.

    Fields
    ------
    touched:
        Per-file impact, in the order the caller supplied the paths (deduped).
    total_blast:
        Count of distinct dependent files across all touched files (excluding
        the touched files themselves).
    high_risk:
        Touched paths classified ``"high"`` risk, sorted.
    suggested_tests:
        Deduped, sorted union of every covering test — the set an agent should
        run before/after the edit.
    note:
        Human-readable caveat, e.g. when the graph was empty so no blast radius
        could be computed.
    """

    touched: list[TouchedFile] = field(default_factory=list)
    total_blast: int = 0
    high_risk: list[str] = field(default_factory=list)
    suggested_tests: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict (deterministic order)."""
        return {
            "touched": [tf.to_dict() for tf in self.touched],
            "total_blast": self.total_blast,
            "high_risk": list(self.high_risk),
            "suggested_tests": list(self.suggested_tests),
            "note": self.note,
        }


def _normalise(path: str) -> str:
    """Normalise a user-supplied path to the graph's repo-relative POSIX form."""
    return path.strip().replace("\\", "/").lstrip("./")


def _try_relative(repo_root: Path, raw: str) -> str:
    """Best-effort convert an absolute-or-relative *raw* path to repo-relative.

    Falls back to a plain normalise when *raw* is outside *repo_root* or not a
    real path — :func:`neighbors` also accepts suffix / bare-name targets, so a
    non-resolving value is still handed through untouched.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return relative_path(repo_root, candidate)
        except ValueError:
            return _normalise(raw)
    return _normalise(raw)


def build_rehearsal(
    repo_root: Path,
    touched_paths: list[str],
    *,
    neighbors_fn: NeighborsFn | None = None,
) -> RehearsalPlan:
    """Rehearse a change to *touched_paths* against the code graph.

    Pure and offline: reads the structural graph, never mutates anything and
    never executes or edits code.  For each touched path it resolves the blast
    radius (dependents), the covering tests, and a risk classification; then it
    aggregates the plan-level totals.

    Parameters
    ----------
    repo_root:
        Absolute repo root — used to build the default graph and to normalise
        absolute touched paths to repo-relative form.
    touched_paths:
        The files the agent intends to edit (repo-relative or absolute).  Order
        is preserved; duplicates are dropped.
    neighbors_fn:
        Optional injected blast-radius lookup ``(target) -> Neighbors``.  When
        ``None`` a graph is built once from *repo_root* and the real
        :func:`oh_no_my_claudecode.codegraph.neighbors` is bound to it.  This is
        the seam tests use to run without a real graph.

    Returns
    -------
    RehearsalPlan
        Always valid.  An empty graph or empty *touched_paths* yields an
        empty-but-valid plan with an explanatory ``note`` — never raises.
    """
    lookup, graph_empty = _resolve_lookup(repo_root, neighbors_fn)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in touched_paths:
        norm = _try_relative(repo_root, raw)
        if norm and norm not in seen:
            seen.add(norm)
            ordered.append(norm)

    touched: list[TouchedFile] = []
    blast: set[str] = set()
    tests: set[str] = set()
    high_risk: list[str] = []

    touched_set = set(ordered)
    for path in ordered:
        result = lookup(path)
        resolved = bool(result.target_files)
        covering = sorted(result.tests)
        covering_set = set(result.tests)
        # Dependents = non-test blast radius: drop co-touched siblings (an agent
        # editing both sides of an edge isn't "breaking" the other) and drop the
        # covering tests (they're surfaced separately, not counted as breakage).
        dependents = sorted(
            d
            for d in result.dependents
            if d not in touched_set and d not in covering_set and not is_test_path(d)
        )
        risk = _classify_risk(dependents)

        touched.append(
            TouchedFile(
                path=path,
                dependents=dependents,
                covering_tests=covering,
                risk=risk,
                resolved=resolved,
            )
        )
        blast.update(dependents)
        tests.update(covering)
        if risk == "high":
            high_risk.append(path)

    note = _build_note(graph_empty=graph_empty, touched=touched)

    return RehearsalPlan(
        touched=touched,
        total_blast=len(blast),
        high_risk=sorted(high_risk),
        suggested_tests=sorted(tests),
        note=note,
    )


def _classify_risk(dependents: list[str]) -> RiskLevel:
    """Classify a touched file's risk from its dependent count."""
    return "high" if len(dependents) >= HIGH_RISK_DEPENDENTS else "low"


def _resolve_lookup(
    repo_root: Path, neighbors_fn: NeighborsFn | None
) -> tuple[NeighborsFn, bool]:
    """Return the effective neighbours lookup and whether the graph is empty.

    When *neighbors_fn* is injected we trust it and report ``graph_empty=False``
    (the caller owns the data).  Otherwise a graph is built once from
    *repo_root* and its file count decides emptiness.
    """
    if neighbors_fn is not None:
        return neighbors_fn, False
    graph = build_codegraph(repo_root)
    return (lambda target: neighbors(graph, target)), graph.file_count == 0


def _build_note(*, graph_empty: bool, touched: list[TouchedFile]) -> str:
    """Compose the plan-level caveat note."""
    if graph_empty:
        return (
            "Code graph is empty — no blast radius could be computed. "
            "Run `onmc codegraph` first (or check this is a source repo)."
        )
    unresolved = [tf.path for tf in touched if not tf.resolved]
    if unresolved:
        joined = ", ".join(sorted(unresolved))
        return (
            f"Not found in the code graph (new file or typo?): {joined}. "
            "Their blast radius is empty; edit with care."
        )
    return ""
