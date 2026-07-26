"""Mission planner and executable harness entry point.

``plan_mission`` is the keystone: it threads a single goal through the existing,
already-shipped *pure* compilers and assembles a single :class:`MissionPlan`.
It **orchestrates**; it does not reimplement any retrieval, scoring, or graph
logic.  The composed pieces are:

- :func:`oh_no_my_claudecode.guard.compiler.compile_guard` — recorded dead-ends
  to avoid (the "do not retry" list).
- :func:`oh_no_my_claudecode.pack.builder.build_pack` — the deterministic,
  offline context pack (dead-ends + decisions + reuse + context files).
- :func:`oh_no_my_claudecode.codegraph.builder.build_codegraph` +
  :func:`~oh_no_my_claudecode.codegraph.builder.neighbors` — the blast radius
  (which files depend on the ones the pack points at).
- :class:`oh_no_my_claudecode.harness_run.controller.HarnessController` — the
  real execution path used by ``run_mission(execute=True)``.

Every composed compiler degrades gracefully to empty on a fresh brain or an
empty repo, so ``plan_mission`` never crashes — it emits an empty-but-valid
plan.  The planner itself performs no I/O beyond what those compilers do, and is
deterministic for a fixed ``(storage, repo_root, goal)``: two calls produce
byte-identical plans.

**Plan mode is the default.** ``plan_mission`` and ``run_mission(execute=False)``
never spawn agents. ``run_mission(execute=True)`` delegates to the same
verifier-backed harness used by ``onmc run --execute``. Mission no longer
pretends that writing a pending swarm manifest is execution.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.codegraph import build_codegraph, neighbors
from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.harness import RiskLevel
from oh_no_my_claudecode.harness_run.budget_modes import BudgetMode
from oh_no_my_claudecode.harness_run.models import AgentName, HarnessResult, RunRequest
from oh_no_my_claudecode.pack.builder import (
    DEFAULT_BUDGET,
    ContextPack,
    build_pack,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten

# How many dead-ends the mission surfaces up front (mirrors the pack's cap).
_DEAD_END_LIMIT = 5

# How many files of blast radius (dependents) to carry into the plan.
_BLAST_RADIUS_LIMIT = 12

# Cap on the number of swarm units we ever emit — a hard ceiling against runaway
# fan-out on a wide context pack or a goal that names dozens of clauses.
_SWARM_UNIT_LIMIT = 12

# Case-insensitive signals that a goal describes greenfield work (building things
# that do not exist yet) rather than modifying existing files.  Matched as whole
# words / phrase prefixes so "created" doesn't false-match "fix the cache".
_GREENFIELD_MARKERS: tuple[str, ...] = (
    "new module",
    "new file",
    "new package",
    "new command",
    "new service",
    "add ",
    "build ",
    "create ",
    "scaffold ",
    "implement ",
    "introduce ",
)

# A path-ish token in the goal, e.g. ``src/foo/bar.py`` or ``src/.../<name>/``.
_PATH_TOKEN = re.compile(r"[\w./-]*[\w-]/[\w./-]+")

# Default fan-out width for the swarm the mission would run.
DEFAULT_CONCURRENCY = 4

# The fixed, ordered pipeline the mission composes.  Surfaced verbatim so the
# rendered plan always tells the user exactly what ran, in order.
_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("recall / guard", "Surface recorded dead-ends to avoid (compile_guard)."),
    ("pack", "Assemble the offline context pack (build_pack)."),
    ("codegraph", "Compute the blast radius of the context files (neighbors)."),
    ("compile harness", "Compile the typed execution DAG, context, policy, and proof contract."),
    ("execute / verify / prove", "Run the agent loop and accept only verifier-backed proof."),
    ("learn candidate", "Propose a quarantined learning candidate from the observed outcome."),
)

HarnessRunner = Callable[[RunRequest], HarnessResult]


@dataclass(frozen=True, slots=True)
class MissionStep:
    """One ordered step of the composed mission pipeline.

    ``name`` is the short stage label; ``detail`` explains what it did; ``status``
    is ``"planned"`` in plan mode and the real harness stage outcome under
    ``--execute``.
    """

    name: str
    detail: str
    status: str = "planned"

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {"name": self.name, "detail": self.detail, "status": self.status}


@dataclass(frozen=True, slots=True)
class MissionPlan:
    """The single magical outcome of ``onmc mission``: one assembled plan.

    Attributes
    ----------
    goal:
        The (stripped) mission goal.
    pack:
        The composed :class:`~oh_no_my_claudecode.pack.builder.ContextPack`.
    dead_ends:
        Short "do not retry" titles surfaced from the guard (deduped subset of
        the pack's dead-ends, kept top-level so the plan leads with them).
    blast_radius:
        Repo-relative files that depend on the pack's context files — the
        downstream surface a change is likely to disturb.
    swarm_units:
        Deterministic candidate work units retained for plan compatibility.
        Mission execution currently runs the typed harness against the complete
        goal; explicit swarm execution remains a separate workflow.
    steps:
        The ordered pipeline stages, for a legible "here's what I did" trace.
    execute:
        ``False`` in plan mode (the default). ``True`` when the caller delegated
        execution to the shared harness.
    swarm:
        Deprecated compatibility field. Mission no longer allocates an inline
        swarm manifest; callers should use ``onmc swarm plan`` explicitly.
    harness:
        Serialized :class:`HarnessResult` from real execution. ``None`` in plan
        mode.
    """

    goal: str
    pack: ContextPack
    dead_ends: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    swarm_units: list[str] = field(default_factory=list)
    steps: list[MissionStep] = field(default_factory=list)
    execute: bool = False
    swarm: dict[str, Any] | None = None
    harness: dict[str, Any] | None = None

    @property
    def is_empty(self) -> bool:
        """True when neither the pack nor the blast radius produced material."""
        return self.pack.is_empty and not self.blast_radius

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict for the ``--json`` CLI surface."""
        return {
            "goal": self.goal,
            "execute": self.execute,
            "dead_ends": list(self.dead_ends),
            "blast_radius": list(self.blast_radius),
            "swarm_units": list(self.swarm_units),
            "steps": [s.to_dict() for s in self.steps],
            "pack": self.pack.to_dict(),
            "swarm": self.swarm,
            "harness": self.harness,
        }


def _collect_dead_ends(storage: SQLiteStorage, goal: str) -> list[str]:
    """Top-level dead-end titles for the plan header.  Graceful empty."""
    if not goal:
        return []
    try:
        result = compile_guard(storage, goal, limit=_DEAD_END_LIMIT)
    except Exception:  # noqa: BLE001 - a fresh/empty brain must never crash the mission
        return []
    return [entry.title for entry in result.entries]


def _collect_blast_radius(repo_root: Path, context_files: list[str]) -> list[str]:
    """Files that depend on the pack's context files (the change's surface).

    Builds the code graph once and unions the dependents of every context file.
    Context files themselves are excluded — the blast radius is what *else* a
    change disturbs.  Degrades to empty on an empty/unreadable repo.
    """
    if not context_files:
        return []
    try:
        graph = build_codegraph(repo_root)
    except Exception:  # noqa: BLE001 - graceful empty on empty/unreadable repo
        return []

    seed = set(context_files)
    radius: set[str] = set()
    for path in context_files:
        try:
            blast = neighbors(graph, path)
        except Exception:  # noqa: BLE001, S112 - one bad target must not sink the plan
            continue
        radius.update(blast.dependents)
    ordered = sorted(radius - seed)
    return ordered[:_BLAST_RADIUS_LIMIT]


def _named_paths(goal: str) -> list[str]:
    """Path-ish tokens the goal explicitly names (e.g. ``src/foo/bar.py``)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _PATH_TOKEN.finditer(goal):
        token = match.group(0).strip("/")
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _is_greenfield(goal: str, repo_root: Path | None, pack: ContextPack) -> bool:
    """Heuristic: is this goal building NEW things rather than editing existing?

    Greenfield when the goal text carries a build/create marker, OR it names paths
    that do not yet exist under the repo.  If the pack already resolved real
    context files that the goal points at, we treat it as change-work — there is
    something concrete to modify.
    """
    lowered = goal.lower()
    marker_hit = any(marker in lowered for marker in _GREENFIELD_MARKERS)

    named = _named_paths(goal)
    if named and repo_root is not None:
        existing = [p for p in named if (repo_root / p).exists()]
        # The goal points at real files on disk → change-work, even if it also
        # carries a build/create verb ("add tests to src/foo.py"). Concrete
        # targets to edit win over the marker. Named paths that don't exist yet
        # → building new things (greenfield).
        return not existing

    # No named paths (or no repo_root to check): a build/create verb with no
    # resolved context files to edit is greenfield; otherwise change-work.
    return marker_hit and not pack.context_files


def _split_deliverables(goal: str) -> list[str]:
    """Parse the distinct deliverables named in a greenfield goal.

    Tries, in order: explicit numbered clauses ``(1) ... (2) ...``; then newline
    splits; then ``" and "`` splits.  Returns the cleaned, de-duplicated clauses
    in stable first-seen order.  Empty when nothing splits out.
    """
    numbered = re.findall(r"\(\s*\d+\s*\)\s*(.*?)(?=\(\s*\d+\s*\)|$)", goal, flags=re.DOTALL)
    if len(numbered) >= 2:
        clauses = numbered
    else:
        by_line = [line for line in goal.splitlines() if line.strip()]
        clauses = by_line if len(by_line) >= 2 else re.split(r"\s+and\s+|\s*[,;]\s*", goal)

    seen: set[str] = set()
    out: list[str] = []
    for raw in clauses:
        clause = raw.strip().strip("-•*").strip()
        clause = re.sub(r"^\(\s*\d+\s*\)\s*", "", clause).strip()
        if len(clause) < 3:
            continue
        key = clause.lower()
        if key not in seen:
            seen.add(key)
            out.append(clause)
    return out


def _dedupe(units: list[str]) -> list[str]:
    """Drop later units whose goal string exactly matches an earlier one."""
    seen: set[str] = set()
    out: list[str] = []
    for unit in units:
        if unit not in seen:
            seen.add(unit)
            out.append(unit)
    return out


def _derive_swarm_units(
    goal: str,
    pack: ContextPack,
    blast_radius: list[str],
    repo_root: Path | None = None,
) -> list[str]:
    """Derive the swarm unit goals the mission would run.

    Deterministic and offline.  Two regimes:

    - **Greenfield** (building new modules that don't exist yet): decompose by the
      DISTINCT deliverables named in the goal — one focused sub-goal per
      deliverable.  This avoids the degenerate case where a generic context pack
      yields N near-identical units all carrying the same goal.
    - **Change-work** (modifying real existing files): one focused unit per
      context file, deduped and capped, plus a final blast-radius verify unit.

    In both regimes we NEVER emit two units with an identical goal string, and we
    always fall back to a single unit carrying the raw goal when nothing else can
    be derived — the mission always has at least one unit to run.
    """
    units: list[str]
    if _is_greenfield(goal, repo_root, pack):
        deliverables = _split_deliverables(goal)
        # Cap greenfield fan-out too: a goal that splits into dozens of clauses
        # must not reintroduce the runaway fan-out the change-work path guards.
        units = [f"{goal} — deliverable: {clause}" for clause in deliverables][:_SWARM_UNIT_LIMIT]
    else:
        units = [f"{goal} — focus on `{path}`" for path in pack.context_files]
        units = _dedupe(units)[:_SWARM_UNIT_LIMIT]
        if blast_radius:
            files = ", ".join(f"`{p}`" for p in blast_radius[:5])
            units.append(f"Verify the change against its blast radius: {files}")

    units = _dedupe(units)
    if not units:
        units = [goal]
    return units


def _build_steps(
    execute: bool,
    *,
    harness_status: str | None = None,
    learn_status: str | None = None,
) -> list[MissionStep]:
    """Build the ordered pipeline trace with an honest execution status."""
    steps: list[MissionStep] = []
    for name, detail in _PIPELINE_STEPS:
        if not execute:
            status = "planned"
        elif name in {"recall / guard", "pack", "codegraph", "compile harness"}:
            status = "completed"
        elif name == "learn candidate":
            status = learn_status or harness_status or "executed"
        else:
            status = harness_status or "executed"
        steps.append(MissionStep(name=name, detail=detail, status=status))
    return steps


def plan_mission(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    *,
    budget: int = DEFAULT_BUDGET,
) -> MissionPlan:
    """Compose the engineering pipeline into a single deterministic plan.

    This is plan mode: it assembles the mission plan WITHOUT spawning any agent
    and without touching the swarm state directory.  Safe, deterministic, and
    offline.

    Parameters
    ----------
    storage:
        Open memory store (for dead-ends + decisions, via the pack and guard).
    repo_root:
        Repository root (for the code graph, reuse radar, and blast radius).
    goal:
        The mission goal — the thing the user wants done.
    budget:
        Character budget passed through to the context pack renderer.

    Returns
    -------
    MissionPlan
        The assembled plan. ``execute`` is always ``False`` here; use
        :func:`run_mission` with ``execute=True`` to run the shared harness.
    """
    clean_goal = goal.strip()

    pack = build_pack(storage, repo_root, clean_goal, budget=budget)
    dead_ends = _collect_dead_ends(storage, clean_goal)
    blast_radius = _collect_blast_radius(repo_root, pack.context_files)
    swarm_units = _derive_swarm_units(clean_goal, pack, blast_radius, repo_root)
    steps = _build_steps(execute=False)

    return MissionPlan(
        goal=clean_goal,
        pack=pack,
        dead_ends=dead_ends,
        blast_radius=blast_radius,
        swarm_units=swarm_units,
        steps=steps,
        execute=False,
        swarm=None,
        harness=None,
    )


def run_mission(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    *,
    budget: int = DEFAULT_BUDGET,
    execute: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    swarm_id: str | None = None,
    agent: AgentName = "claude",
    model: str = "default",
    verifier: str = "pytest",
    max_iterations: int = 10,
    max_cost_usd: float | None = None,
    isolate: bool = True,
    risk: RiskLevel = RiskLevel.MEDIUM,
    context_budget: int = 4_000,
    budget_mode: BudgetMode = BudgetMode.STANDARD,
    resume_run_id: str | None = None,
    harness_runner: HarnessRunner | None = None,
) -> MissionPlan:
    """Plan the mission and, when ``execute``, run the real ONMC harness.

    With ``execute=False`` (the default) this is exactly :func:`plan_mission` —
    a safe dry-run that spawns nothing.

    With ``execute=True`` it delegates to
    :class:`oh_no_my_claudecode.harness_run.controller.HarnessController`.
    That path launches the selected headless agent, runs the configured verifier,
    enforces limits and policy, persists durable state, and writes a proof receipt.

    Parameters
    ----------
    execute:
        When ``True``, invoke the shared verifier-backed harness.
    concurrency, swarm_id:
        Deprecated compatibility arguments from the old manifest-only Mission.
        They are ignored. Use ``onmc swarm plan`` for inline swarm allocation.
    harness_runner:
        Injectable execution boundary for tests.

    Returns
    -------
    MissionPlan
        The plan, with ``harness`` populated from the real execution result.
    """
    plan = plan_mission(storage, repo_root, goal, budget=budget)
    if not execute:
        return plan

    # Preserve old keyword arguments for API compatibility while making
    # execution semantics honest. Inline swarm allocation remains an explicit
    # `onmc swarm plan` operation.
    _ = (concurrency, swarm_id)

    if harness_runner is None:
        from oh_no_my_claudecode.harness_run.controller import HarnessController

        harness_runner = HarnessController(repo_root).run

    result = harness_runner(
        RunRequest(
            task=plan.goal,
            execute=True,
            agent=agent,
            model=model,
            verifier=verifier,
            max_iterations=max_iterations,
            max_cost_usd=max_cost_usd,
            isolation=isolate,
            risk=risk,
            context_budget=context_budget,
            budget_mode=budget_mode,
            resume_run_id=resume_run_id,
        )
    )
    learn_stage = next(
        (stage for stage in result.stages if stage.name.value == "learn-candidate"),
        None,
    )
    return MissionPlan(
        goal=plan.goal,
        pack=plan.pack,
        dead_ends=plan.dead_ends,
        blast_radius=plan.blast_radius,
        swarm_units=plan.swarm_units,
        steps=_build_steps(
            execute=True,
            harness_status=result.status.value,
            learn_status=learn_stage.status.value if learn_stage is not None else None,
        ),
        execute=True,
        swarm=None,
        harness=result.to_dict(),
    )


def render_mission_markdown(plan: MissionPlan) -> str:
    """Render *plan* to a terse, deterministic "here's what I'll do" panel.

    Pure function of the plan — side-effect free and byte-identical for a fixed
    plan.  Sections with no items render a short placeholder so the shape of the
    mission is always legible.
    """
    mode = "EXECUTE (verifier-backed harness)" if plan.execute else "PLAN (dry-run, no agents)"
    lines: list[str] = [
        "# Mission",
        "",
        f"**Goal:** {plan.goal or '(none)'}",
        f"**Mode:** {mode}",
        "",
        "## Pipeline",
    ]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"{i}. **{step.name}** [{step.status}] — {step.detail}")
    lines.append("")

    lines.append("## Dead ends (do not retry)")
    if plan.dead_ends:
        lines.extend(f"- {shorten(title, max_length=120)}" for title in plan.dead_ends)
    else:
        lines.append("_(none recorded)_")
    lines.append("")

    lines.append("## Context files")
    if plan.pack.context_files:
        lines.extend(f"- `{path}`" for path in plan.pack.context_files)
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Blast radius (dependents)")
    if plan.blast_radius:
        lines.extend(f"- `{path}`" for path in plan.blast_radius)
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Candidate work units")
    if plan.swarm_units:
        lines.extend(f"- {shorten(unit, max_length=160)}" for unit in plan.swarm_units)
    else:
        lines.append("_(none)_")
    lines.append("")

    if plan.execute and plan.harness is not None:
        harness_plan = plan.harness.get("plan", {})
        run_id = harness_plan.get("run_id", "(unknown)") if isinstance(harness_plan, dict) else ""
        lines.append("## Harness result")
        lines.append(f"- run_id: `{run_id}`")
        lines.append(f"- status: **{plan.harness.get('status', 'unknown')}**")
        lines.append(f"- verified: **{plan.harness.get('verified', False)}**")
        lines.append(f"- stop_reason: `{plan.harness.get('stop_reason', 'unknown')}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
