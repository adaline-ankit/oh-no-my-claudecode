"""Milestone 6 — the external-proof *portfolio* harness.

This module turns the experiment kernel into something an operator can point at
a real corpus of coding tasks and a real coding agent (Claude / Codex CLI) to
produce an honest, comparative :class:`~.kernel.ExperimentReport`. It adds three
things the kernel deliberately leaves out:

- **A task corpus vocabulary.** :class:`TaskSpec` describes one real coding task
  — a pinned repo, a prompt, and a *verifier command* whose exit status (never
  agent self-report) decides pass/fail. :class:`PortfolioManifest` freezes a set
  of those tasks together with an :class:`~.contracts.ExperimentManifest` and an
  explicit :class:`~.contracts.BenchmarkAuditStatus`.

- **A claim gate.** A portfolio may only back an *external* claim when its audit
  status is ``VALID`` **and** it runs more than one trial (honest uncertainty).
  Otherwise results are labelled ``internal`` — the runner refuses to overstate.

- **An agent seam.** :class:`AgentAdapter` is the protocol a real Claude/Codex
  CLI adapter implements. :class:`FixtureAgentAdapter` is a deterministic,
  seeded, in-process stand-in used by tests (no subprocess, no network, no cost).
  :class:`CliAgentAdapter` is a documented skeleton that raises
  :class:`CredentialsRequiredError` rather than ever touching a paid API.

**Zero paid calls.** Nothing in this module contacts an LLM, spawns an agent
subprocess, or reads a secret. The real execution path is a seam, not an
implementation — M6 is *ready to run*, not *running*.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from . import stats
from .contracts import (
    SCHEMA_VERSION,
    BenchmarkAuditStatus,
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
    MetricLabel,
    RunId,
    TrialResult,
)
from .kernel import ExperimentReport, ExperimentRunner

__all__ = [
    "AgentAdapter",
    "ClaimLevel",
    "CliAgentAdapter",
    "CredentialsRequiredError",
    "FixtureAgentAdapter",
    "PortfolioManifest",
    "PortfolioReport",
    "PortfolioRunner",
    "RepoRef",
    "TaskKind",
    "TaskSpec",
    "TrialExclusion",
    "load_portfolio",
    "STARTER_PORTFOLIO_PATH",
]

#: Location of the shipped schema-demonstrator corpus (SUSPECT audit on purpose).
STARTER_PORTFOLIO_PATH = (
    Path(__file__).resolve().parents[3] / "datasets" / "experiment" / "portfolio_starter.json"
)

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_URL_RE = re.compile(r"^(https?|git|ssh|file)://|^git@")


class TaskKind(StrEnum):
    """The task archetypes an external portfolio is expected to span.

    A credible external claim exercises more than one shape of work — a bench
    that is all ``bugfix`` proves little about ``ambiguity`` or ``long-running``
    behaviour. The runner does not enforce a mix, but the vocabulary makes the
    coverage of a corpus auditable.
    """

    BUGFIX = "bugfix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TEST = "test"
    AMBIGUITY = "ambiguity"
    LONG_RUNNING = "long-running"


class ClaimLevel(StrEnum):
    """How strongly a report may be cited.

    ``EXTERNAL`` is reserved for a ``VALID``-audited, multi-trial portfolio —
    the only combination that supports an outward-facing claim. Everything else
    is ``INTERNAL`` (useful for iteration, never for marketing).
    """

    EXTERNAL = "external"
    INTERNAL = "internal"


class CredentialsRequiredError(RuntimeError):
    """Raised when a real-run adapter is invoked without agent CLIs + credentials.

    Its existence is the guarantee that the fixture-tested harness cannot
    silently fall through to a paid API call: the real seam fails loud and
    early instead of spending money.
    """


@dataclass(frozen=True, slots=True)
class RepoRef:
    """A pinned repository the task runs against — reproducible by construction."""

    name: str
    url: str
    pinned_sha: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("repo name must not be empty")
        if not _URL_RE.search(self.url):
            raise ValueError(f"repo url must be a real clone url, got {self.url!r}")
        if not _SHA_RE.match(self.pinned_sha):
            raise ValueError(f"pinned_sha must be 7-64 hex chars, got {self.pinned_sha!r}")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "url": self.url, "pinned_sha": self.pinned_sha}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RepoRef:
        return cls(
            name=_get_str(data, "name"),
            url=_get_str(data, "url"),
            pinned_sha=_get_str(data, "pinned_sha"),
        )


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One real coding task in the portfolio.

    ``verifier_argv`` is the command whose exit code adjudicates the task — a
    verified outcome, never the agent's own word (blueprint truth rule 6).
    ``expected_outcome`` is a human-readable description of what "passed" means,
    kept for auditability of the corpus.
    """

    task_id: str
    repo: RepoRef
    prompt: str
    verifier_argv: tuple[str, ...]
    task_kind: TaskKind
    expected_outcome: str

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if not self.verifier_argv:
            raise ValueError("verifier_argv must not be empty (a task needs a verifier)")
        if any(not isinstance(arg, str) or not arg for arg in self.verifier_argv):
            raise ValueError("verifier_argv entries must be non-empty strings")
        if not isinstance(self.task_kind, TaskKind):
            raise ValueError("task_kind must be a TaskKind")
        if not self.expected_outcome.strip():
            raise ValueError("expected_outcome must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "repo": self.repo.to_dict(),
            "prompt": self.prompt,
            "verifier_argv": list(self.verifier_argv),
            "task_kind": self.task_kind.value,
            "expected_outcome": self.expected_outcome,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskSpec:
        return cls(
            task_id=_get_str(data, "task_id"),
            repo=RepoRef.from_dict(_get_mapping(data, "repo")),
            prompt=_get_str(data, "prompt"),
            verifier_argv=_get_str_tuple(data, "verifier_argv"),
            task_kind=TaskKind(_get_str(data, "task_kind")),
            expected_outcome=_get_str(data, "expected_outcome"),
        )


@dataclass(frozen=True, slots=True)
class PortfolioManifest:
    """A frozen task corpus + experiment manifest + honest audit provenance.

    The audit status lives here (not just on the embedded experiment manifest)
    because *the portfolio* is the unit an external claim is made about: it is
    the corpus, its provenance, and the comparison design together.
    """

    experiment: ExperimentManifest
    tasks: tuple[TaskSpec, ...]
    audit_status: BenchmarkAuditStatus = BenchmarkAuditStatus.SUSPECT
    leakage_notes: str = ""

    def __post_init__(self) -> None:
        if not self.tasks:
            raise ValueError("a portfolio needs at least one task")
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task_id values must be unique within a portfolio")

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(t.task_id for t in self.tasks)

    def task(self, task_id: str) -> TaskSpec:
        for spec in self.tasks:
            if spec.task_id == task_id:
                return spec
        raise KeyError(task_id)

    @property
    def is_claim_ready(self) -> bool:
        """A portfolio may back an *external* claim only when its audit is VALID.

        This is the hard gate from the invariant; the runner additionally
        requires >1 trial before it will actually stamp a result ``external``.
        """
        return self.audit_status is BenchmarkAuditStatus.VALID

    def claim_level(self) -> ClaimLevel:
        """``EXTERNAL`` iff audit is VALID *and* the design has >1 trial."""
        if self.is_claim_ready and self.experiment.requires_uncertainty:
            return ClaimLevel.EXTERNAL
        return ClaimLevel.INTERNAL

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "experiment": self.experiment.to_dict(),
            "tasks": [t.to_dict() for t in self.tasks],
            "audit_status": self.audit_status.value,
            "leakage_notes": self.leakage_notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PortfolioManifest:
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported portfolio schema version: {version!r}")
        tasks = tuple(TaskSpec.from_dict(t) for t in _get_mapping_seq(data, "tasks"))
        return cls(
            experiment=_experiment_from_dict(_get_mapping(data, "experiment")),
            tasks=tasks,
            audit_status=BenchmarkAuditStatus(_get_str(data, "audit_status")),
            leakage_notes=_get_str(data, "leakage_notes", default=""),
        )


@runtime_checkable
class AgentAdapter(Protocol):
    """The seam a real coding-agent runner implements.

    Given a :class:`TaskSpec` and a :class:`~.contracts.Condition`, run the task
    once and return a *verified* :class:`~.contracts.TrialResult`. The trial
    index is not part of this contract — :class:`PortfolioRunner` stamps the
    canonical :class:`~.contracts.RunId` — so an adapter only has to know how to
    execute one (task, condition) pair.
    """

    def run(self, task: TaskSpec, condition: Condition) -> TrialResult: ...


@dataclass(frozen=True, slots=True)
class FixtureAgentAdapter:
    """Deterministic, in-process :class:`AgentAdapter` for tests — zero cost.

    Every metric is a pure function of ``(seed, task_id, condition)`` so a
    portfolio run is byte-for-byte reproducible. ``pass_bias`` pins each
    condition's pass probability (default ``0.5``); ``cost_scale`` shifts a
    condition's metric magnitudes so paired deltas are non-trivial. No
    subprocess, no network, no secrets — this is the whole point of M6 being
    runnable without spending money.
    """

    seed: int = 0
    pass_bias: Mapping[Condition, float] = field(default_factory=dict)
    cost_scale: Mapping[Condition, float] = field(default_factory=dict)
    metric_label: MetricLabel = MetricLabel.MEASURED

    def _unit(self, task: TaskSpec, condition: Condition, salt: str) -> float:
        seed = stats.derive_seed(self.seed, salt, condition.value, task.task_id)
        # A stable pseudo-uniform draw in [0, 1) via the low bits of the seed.
        return (seed % 1_000_000) / 1_000_000.0

    def run(self, task: TaskSpec, condition: Condition) -> TrialResult:
        bias = self.pass_bias.get(condition, 0.5)
        scale = self.cost_scale.get(condition, 1.0)
        passed = self._unit(task, condition, "pass") < bias
        cost = round(scale * (0.10 + self._unit(task, condition, "cost")), 6)
        latency = round(scale * (100.0 + 900.0 * self._unit(task, condition, "latency")), 3)
        turns = 1 + int(self._unit(task, condition, "turns") * 10)
        tokens = 500 + int(self._unit(task, condition, "tokens") * 5000)
        # trial is stamped by the runner; 0 is a discarded placeholder.
        run_id = RunId(
            experiment_id="fixture-agent",
            condition=condition,
            task_id=task.task_id,
            trial=0,
        )
        return TrialResult(
            run_id=run_id,
            passed=passed,
            metric_label=self.metric_label,
            cost_usd=cost,
            latency_ms=latency,
            turns=turns,
            tool_calls=turns,
            context_tokens=tokens,
        )


@dataclass(frozen=True, slots=True)
class CliAgentAdapter:
    """Skeleton for a *real* Claude/Codex CLI adapter — intentionally inert.

    A real implementation would clone ``task.repo`` at its pinned sha, run the
    agent CLI named by ``agent_cmd`` under the given ``condition``, execute
    ``task.verifier_argv`` and read its exit status. **None of that happens
    here.** This worker performs zero paid calls, so :meth:`run` refuses to
    execute: without explicit credentials it raises
    :class:`CredentialsRequiredError`, and even with them it raises
    :class:`NotImplementedError` because the execution body is deliberately left
    unwired for M6. It reads no secrets from the environment itself.
    """

    agent_cmd: tuple[str, ...]
    credentials_present: bool = False

    def __post_init__(self) -> None:
        if not self.agent_cmd:
            raise ValueError("agent_cmd must not be empty (name the agent CLI to invoke)")

    def run(self, task: TaskSpec, condition: Condition) -> TrialResult:
        if not self.credentials_present:
            raise CredentialsRequiredError(
                "CliAgentAdapter requires agent CLIs + credentials to run "
                f"{task.task_id!r} under {condition.value!r}. Provide them explicitly "
                "and wire a real execution body; this M6 skeleton makes zero paid calls."
            )
        raise NotImplementedError(
            "CliAgentAdapter real execution is an intentional seam left unwired in M6 — "
            "implement repo checkout, agent invocation, and verifier exec here."
        )


@dataclass(frozen=True, slots=True)
class TrialExclusion:
    """A single (task, condition, trial) cell that could not be measured."""

    run_id: str
    task_id: str
    condition: Condition
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "condition": self.condition.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    """A comparative report plus its honest claim provenance and accounting."""

    experiment_id: str
    claim_level: ClaimLevel
    audit_status: BenchmarkAuditStatus
    is_claim_ready: bool
    total_trials: int
    executed_trials: int
    excluded_trials: int
    report: ExperimentReport
    exclusions: tuple[TrialExclusion, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "claim_level": self.claim_level.value,
            "audit_status": self.audit_status.value,
            "is_claim_ready": self.is_claim_ready,
            "total_trials": self.total_trials,
            "executed_trials": self.executed_trials,
            "excluded_trials": self.excluded_trials,
            "report": self.report.to_dict(),
            "exclusions": [e.to_dict() for e in self.exclusions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


class _BridgeAdapter:
    """Adapt an :class:`AgentAdapter` to the kernel's :class:`TrialAdapter`.

    Maps a kernel :class:`~.contracts.RunId` to its :class:`TaskSpec`, drives the
    agent, and stamps the canonical run id onto the returned result. An agent
    error is caught, recorded as an exclusion, and surfaced as a failed,
    ``ESTIMATED``-labelled trial so the aggregate degrades honestly rather than
    crashing the whole comparison.
    """

    def __init__(self, manifest: PortfolioManifest, adapter: AgentAdapter) -> None:
        self._manifest = manifest
        self._adapter = adapter
        self.exclusions: list[TrialExclusion] = []

    def run(self, run_id: RunId) -> TrialResult:
        task = self._manifest.task(run_id.task_id)
        try:
            result = self._adapter.run(task, run_id.condition)
        except Exception as exc:  # noqa: BLE001 - honest failure accounting, not swallowing
            self.exclusions.append(
                TrialExclusion(
                    run_id=run_id.slug,
                    task_id=run_id.task_id,
                    condition=run_id.condition,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            return TrialResult(
                run_id=run_id,
                passed=False,
                metric_label=MetricLabel.ESTIMATED,
            )
        return replace(result, run_id=run_id)


class PortfolioRunner:
    """Drive a :class:`PortfolioManifest` + :class:`AgentAdapter` to a report.

    Delegates the ``condition x task x trial`` grid, seeded ordering, bootstrap
    CIs, and paired deltas to :class:`~.kernel.ExperimentRunner` — this class
    only adds the corpus binding, the error/exclusion ledger, and the claim gate.
    """

    def __init__(
        self,
        manifest: PortfolioManifest,
        adapter: AgentAdapter,
        *,
        baseline: Condition = Condition.BARE_AGENT,
    ) -> None:
        self._manifest = manifest
        self._bridge = _BridgeAdapter(manifest, adapter)
        # Structural check: the bridge is a valid kernel adapter.
        self._runner: ExperimentRunner = ExperimentRunner(
            manifest.experiment,
            manifest.task_ids,
            self._bridge,
            baseline=baseline,
        )

    @property
    def manifest(self) -> PortfolioManifest:
        return self._manifest

    def run(self) -> PortfolioReport:
        report = self._runner.run()
        exclusions = tuple(self._bridge.exclusions)
        experiment = self._manifest.experiment
        total = len(experiment.conditions) * len(self._manifest.tasks) * experiment.trials
        excluded = len(exclusions)
        return PortfolioReport(
            experiment_id=experiment.experiment_id.value,
            claim_level=self._manifest.claim_level(),
            audit_status=self._manifest.audit_status,
            is_claim_ready=self._manifest.is_claim_ready,
            total_trials=total,
            executed_trials=total - excluded,
            excluded_trials=excluded,
            report=report,
            exclusions=exclusions,
        )


# --------------------------------------------------------------------------- #
# JSON loading helpers — typed, validating extractors over untyped JSON.
# --------------------------------------------------------------------------- #


def _get_str(data: Mapping[str, object], key: str, *, default: str | None = None) -> str:
    if key not in data:
        if default is not None:
            return default
        raise ValueError(f"missing required string field {key!r}")
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(f"field {key!r} must be a string, got {type(value).__name__}")
    return value


def _get_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"field {key!r} must be an integer")
    return value


def _get_str_tuple(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"field {key!r} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"field {key!r} must contain only strings")
        out.append(item)
    return tuple(out)


def _get_mapping(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"field {key!r} must be an object")
    return value


def _get_mapping_seq(data: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    value = data.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"field {key!r} must be a list of objects")
    out: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"field {key!r} must contain only objects")
        out.append(item)
    return out


def _experiment_from_dict(data: Mapping[str, object]) -> ExperimentManifest:
    env = _get_mapping(data, "environment")
    environment = Environment(
        code_sha=_get_str(env, "code_sha"),
        config_hash=_get_str(env, "config_hash"),
        model=_get_str(env, "model"),
        provider=_get_str(env, "provider"),
        image=_get_str(env, "image", default="local"),
    )
    conditions = tuple(Condition(c) for c in _get_str_tuple(data, "conditions"))
    return ExperimentManifest(
        experiment_id=ExperimentId(_get_str(data, "experiment_id")),
        task_set_revision=_get_str(data, "task_set_revision"),
        conditions=conditions,
        trials=_get_int(data, "trials"),
        seed=_get_int(data, "seed"),
        environment=environment,
        audit_status=BenchmarkAuditStatus(_get_str(data, "audit_status", default="suspect")),
        leakage_notes=_get_str(data, "leakage_notes", default=""),
    )


def load_portfolio(path: Path | str = STARTER_PORTFOLIO_PATH) -> PortfolioManifest:
    """Load and validate a :class:`PortfolioManifest` from a JSON file."""
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, Mapping):
        raise ValueError("portfolio JSON root must be an object")
    return PortfolioManifest.from_dict(data)
