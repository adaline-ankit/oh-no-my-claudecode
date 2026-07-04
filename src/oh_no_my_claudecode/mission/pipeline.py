"""Mission planner — compose the shipped engineering pipeline into one plan.

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
- :func:`oh_no_my_claudecode.swarm.inline.plan_inline_swarm` — the swarm units
  the mission *would* run (only when ``run_mission(execute=True)``).

Every composed compiler degrades gracefully to empty on a fresh brain or an
empty repo, so ``plan_mission`` never crashes — it emits an empty-but-valid
plan.  The planner itself performs no I/O beyond what those compilers do, and is
deterministic for a fixed ``(storage, repo_root, goal)``: two calls produce
byte-identical plans.

**Plan mode is the default.**  ``plan_mission`` and ``run_mission(execute=False)``
NEVER spawn agents and NEVER touch the swarm state directory — they are a safe,
offline dry-run.  ``run_mission(execute=True)`` calls ``plan_inline_swarm`` to
allocate the swarm manifest and returns the swarm plan, but it too stops short
of spawning any agent: spawning is the model's job, driven from the emitted
plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.codegraph import build_codegraph, neighbors
from oh_no_my_claudecode.guard.compiler import compile_guard
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
    ("plan swarm", "Derive the swarm units the mission would run."),
    ("summary", "Emit one mission plan + receipt (no agents spawned in plan mode)."),
)


@dataclass(frozen=True, slots=True)
class MissionStep:
    """One ordered step of the composed mission pipeline.

    ``name`` is the short stage label; ``detail`` explains what it did; ``status``
    is ``"planned"`` in plan mode and ``"queued"`` for the swarm step under
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
        The goal strings of the swarm units the mission would run.  Always
        populated in the plan (so the user sees the intended fan-out); only
        *materialised* into a swarm manifest under ``run_mission(execute=True)``.
    steps:
        The ordered pipeline stages, for a legible "here's what I did" trace.
    execute:
        ``False`` in plan mode (the default).  ``True`` only when the caller
        explicitly handed off to the swarm.
    swarm:
        The swarm plan dict from ``plan_inline_swarm`` — present ONLY when
        ``execute`` is ``True``.  ``None`` in plan mode.
    """

    goal: str
    pack: ContextPack
    dead_ends: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    swarm_units: list[str] = field(default_factory=list)
    steps: list[MissionStep] = field(default_factory=list)
    execute: bool = False
    swarm: dict[str, Any] | None = None

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
        missing = [p for p in named if not (repo_root / p).exists()]
        if missing:
            return True

    # A build/create verb with no resolved context files to edit → greenfield.
    if marker_hit and not pack.context_files:
        return True
    return marker_hit and bool(named)


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
        units = [f"{goal} — deliverable: {clause}" for clause in deliverables]
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


def _build_steps(execute: bool) -> list[MissionStep]:
    """The ordered pipeline trace; the swarm step is ``queued`` under execute."""
    steps: list[MissionStep] = []
    for name, detail in _PIPELINE_STEPS:
        status = "queued" if (execute and name == "plan swarm") else "planned"
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
        The assembled plan.  ``execute`` is always ``False`` here; use
        :func:`run_mission` with ``execute=True`` to additionally materialise a
        swarm manifest.
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
) -> MissionPlan:
    """Plan the mission and, when ``execute``, hand the plan to the swarm.

    With ``execute=False`` (the default) this is exactly :func:`plan_mission` —
    a safe, offline dry-run that spawns nothing.

    With ``execute=True`` it additionally calls
    :func:`oh_no_my_claudecode.swarm.inline.plan_inline_swarm` to ALLOCATE a
    swarm manifest for the derived units and attaches the resulting swarm plan to
    the returned :class:`MissionPlan`.  It still does **not** spawn any agent —
    spawning is the model's job, driven from the emitted plan (the inline swarm
    is the accountability ledger, not the spawner).

    Parameters
    ----------
    execute:
        When ``True``, materialise the swarm manifest via ``plan_inline_swarm``.
    concurrency:
        Advisory fan-out width recorded on the swarm manifest.
    swarm_id:
        Optional explicit swarm id (tests inject a deterministic value).

    Returns
    -------
    MissionPlan
        The plan, with ``execute`` reflecting the requested mode and ``swarm``
        populated only when ``execute`` is ``True``.
    """
    plan = plan_mission(storage, repo_root, goal, budget=budget)
    if not execute:
        return plan

    # Import here so plan mode never imports the swarm machinery.
    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

    swarm_plan = plan_inline_swarm(
        repo_root,
        plan.swarm_units,
        concurrency=concurrency,
        swarm_id=swarm_id,
    )
    return MissionPlan(
        goal=plan.goal,
        pack=plan.pack,
        dead_ends=plan.dead_ends,
        blast_radius=plan.blast_radius,
        swarm_units=plan.swarm_units,
        steps=_build_steps(execute=True),
        execute=True,
        swarm=swarm_plan,
    )


def render_mission_markdown(plan: MissionPlan) -> str:
    """Render *plan* to a terse, deterministic "here's what I'll do" panel.

    Pure function of the plan — side-effect free and byte-identical for a fixed
    plan.  Sections with no items render a short placeholder so the shape of the
    mission is always legible.
    """
    mode = "EXECUTE (hand off to swarm)" if plan.execute else "PLAN (dry-run, no agents)"
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

    lines.append("## Swarm units (would run)")
    if plan.swarm_units:
        lines.extend(f"- {shorten(unit, max_length=160)}" for unit in plan.swarm_units)
    else:
        lines.append("_(none)_")
    lines.append("")

    if plan.execute and plan.swarm is not None:
        sid = plan.swarm.get("swarm_id", "(unknown)")
        lines.append("## Swarm")
        lines.append(f"- swarm_id: `{sid}`")
        lines.append(f"- manifest: `{plan.swarm.get('manifest_path', '')}`")
        lines.append("- agents spawned: **none** (drive the fan-out from this plan)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
