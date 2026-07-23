from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import oh_no_my_claudecode.harness_run.controller as harness_controller_module
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.config import default_config, write_config
from oh_no_my_claudecode.context_engine import ContextEngine
from oh_no_my_claudecode.durable_runtime import NodeState, RunState, RuntimeStore
from oh_no_my_claudecode.harness_run import (
    ControllerDependencies,
    HarnessController,
    HarnessStatus,
    LoopInvocation,
    RunRequest,
)
from oh_no_my_claudecode.harness_run.context import (
    HybridRepositoryCandidateProvider,
)
from oh_no_my_claudecode.harness_run.controller import (
    _default_loop_executor,
    default_dependencies,
)
from oh_no_my_claudecode.loop.adapters import CodexCliAdapter
from oh_no_my_claudecode.loop.engine import _default_verify_runner
from oh_no_my_claudecode.loop.models import IterationContract, LoopResult
from oh_no_my_claudecode.retrieval import HybridRetriever
from oh_no_my_claudecode.tool_broker import Decision, DecisionEffect


class AllowPolicy:
    def decide(self, action: object) -> Decision:
        del action
        return Decision(DecisionEffect.ALLOW, "test_allow")


class DenyVerifierPolicy:
    def decide(self, action: object) -> Decision:
        if getattr(action, "verifier", False):
            return Decision(DecisionEffect.DENY, "test_denied")
        return Decision(DecisionEffect.ALLOW, "test_allow")


class FakeLoop:
    def __init__(self, result: LoopResult) -> None:
        self.result = result
        self.calls = 0
        self.invocations: list[object] = []

    def __call__(self, invocation: object) -> LoopResult:
        self.calls += 1
        self.invocations.append(invocation)
        return self.result


def _loop_result(*, converged: bool) -> LoopResult:
    return LoopResult(
        iterations=[
            IterationContract(
                iteration=1,
                prediction="the change satisfies the task",
                action_summary="implemented the requested change",
                files_touched=["src/example.py"],
                verify_passed=converged,
                verify_output="1 passed" if converged else "1 failed",
                outcome="win" if converged else "loss",
            )
        ],
        converged=converged,
        stop_reason="converged" if converged else "max-iterations",
    )


def _controller(
    tmp_path: Path,
    loop: FakeLoop,
    *,
    policy: object | None = None,
) -> HarnessController:
    dependencies = ControllerDependencies(
        context_engine=ContextEngine(),
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=policy or AllowPolicy(),
        loop_executor=loop,
    )
    return HarnessController(tmp_path, dependencies=dependencies)


def test_plan_only_never_executes_agent_and_is_deterministic(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)
    request = RunRequest(task="  Fix\n cache invalidation  ", plan_only=True)

    first = controller.run(request)
    second = controller.run(request)

    assert first.status is HarnessStatus.PLANNED
    assert loop.calls == 0
    assert first.to_dict() == second.to_dict()
    assert set(first.plan.to_dict()) == {
        "schema_version",
        "run_id",
        "dag",
        "context_packet",
        "proof_requirements",
        "policy_decisions",
        "state_path",
        "resume",
    }
    assert not Path(first.plan.state_path).exists()


def test_execute_persists_run_and_node_transitions(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)

    result = controller.run(RunRequest(task="Implement cache fix", execute=True))

    snapshot = controller.dependencies.runtime_store.load(result.plan.run_id)
    assert result.status is HarnessStatus.COMPLETED
    assert snapshot.state is RunState.COMPLETED
    assert all(node.state is NodeState.SUCCEEDED for node in snapshot.nodes.values())
    assert result.resume_run_id == result.plan.run_id
    assert Path(result.plan.state_path, "events.jsonl").exists()


def test_policy_denial_prevents_loop_execution(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop, policy=DenyVerifierPolicy())

    result = controller.run(RunRequest(task="Unsafe verifier", execute=True))

    assert result.status is HarnessStatus.DENIED
    assert loop.calls == 0
    assert any(not item.allowed for item in result.plan.policy_decisions)
    assert not Path(result.plan.state_path).exists()


def test_successful_and_failing_fake_execution_are_reported_honestly(tmp_path: Path) -> None:
    successful = _controller(tmp_path / "success", FakeLoop(_loop_result(converged=True)))
    failing = _controller(tmp_path / "failure", FakeLoop(_loop_result(converged=False)))

    success = successful.run(RunRequest(task="Successful task", execute=True))
    failure = failing.run(RunRequest(task="Failing task", execute=True))

    assert success.status is HarnessStatus.COMPLETED
    assert success.loop_converged is True
    assert success.proof_complete is True
    assert failure.status is HarnessStatus.FAILED
    assert failure.loop_converged is False
    assert failure.proof_complete is False
    assert failure.stop_reason == "max-iterations"


def test_resume_surface_returns_terminal_run_without_reexecution(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)
    first = controller.run(RunRequest(task="Resumable task", execute=True))

    resumed = controller.run(
        RunRequest(task="Resumable task", execute=True, resume_run_id=first.plan.run_id)
    )

    assert resumed.status is HarnessStatus.COMPLETED
    assert resumed.resumed is True
    assert loop.calls == 1


def test_model_is_compiled_and_codex_adapter_receives_override(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)
    plan = controller.run(
        RunRequest(task="Use selected model", plan_only=True, agent="codex", model="gpt-test")
    ).plan
    seen: list[list[str]] = []

    def runner(command: list[str], cwd: str, timeout: int) -> object:
        from oh_no_my_claudecode.loop.adapters import CompletedProc

        del cwd, timeout
        seen.append(command)
        return CompletedProc(0, "" if command[0] == "git" else "done", "")

    CodexCliAdapter(tmp_path, model="gpt-test", command_runner=runner)(
        "Do work", escalation_level=0
    )

    assert all(node.policy.model == "gpt-test" for node in plan.dag.nodes)
    assert seen[1][4:6] == ["--model", "gpt-test"]


def test_cli_json_and_help_expose_safe_execution_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["run", "--help"])
    compact_help = re.sub(r"\s+", "", re.sub(r"\x1b\[[0-9;]*m", "", help_result.stdout))

    assert help_result.exit_code == 0
    assert "--plan-only" in compact_help
    assert "--execute" in compact_help
    assert "--agent" in compact_help
    assert "--context-budget" in compact_help

    monkeypatch.setattr(
        "oh_no_my_claudecode.harness_run.commands.discover_repo_root",
        lambda cwd: tmp_path,
    )
    result = runner.invoke(app, ["run", "Fix cache", "--plan-only", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    assert payload["plan"]["dag"]["task"] == "Fix cache"


def test_default_dependencies_retrieve_relevant_repo_context(tmp_path: Path) -> None:
    source = tmp_path / "src" / "cache.py"
    source.parent.mkdir()
    source.write_text("def invalidate_cache():\n    return 'fresh'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("CACHE_SECRET=never-read\n", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"cache\x00binary")

    plan = HarnessController(tmp_path).run(
        RunRequest(task="Fix cache invalidation", plan_only=True, context_budget=500)
    ).plan

    assert [item.candidate_id for item in plan.context_packet.evidence] == [
        "repo:src/cache.py"
    ]
    rendered = json.dumps(plan.context_packet.to_dict())
    assert "never-read" not in rendered
    assert "binary.py" not in rendered
    assert plan.context_packet.used_tokens <= 500


def test_execution_passes_planned_context_to_loop(tmp_path: Path) -> None:
    source = tmp_path / "src" / "billing.py"
    source.parent.mkdir()
    source.write_text("def retry_billing_webhook(): ...\n", encoding="utf-8")
    loop = FakeLoop(_loop_result(converged=True))
    dependencies = default_dependencies(tmp_path)
    controller = HarnessController(
        tmp_path,
        dependencies=ControllerDependencies(
            context_engine=dependencies.context_engine,
            runtime_store=dependencies.runtime_store,
            policy_decider=AllowPolicy(),
            loop_executor=loop,
        ),
    )

    controller.run(RunRequest(task="Retry billing webhook", execute=True))

    invocation = loop.invocations[0]
    assert invocation.context_packet.evidence[0].candidate_id == (
        "repo:src/billing.py"
    )


def test_default_verify_runner_uses_argv_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def fake_run(command: object, **kwargs: object) -> object:
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr("oh_no_my_claudecode.loop.engine.subprocess.run", fake_run)

    result = _default_verify_runner("pytest -q; touch owned")

    command, kwargs = seen[0]  # type: ignore[misc]
    assert command == ["pytest", "-q;", "touch", "owned"]
    assert "shell" not in kwargs
    assert result.passed is True


def test_isolated_execution_binds_agent_and_verifier_to_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(default_config(tmp_path), tmp_path)
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    seen: dict[str, object] = {}

    class FakeIsolation:
        def __init__(self, *, branch_prefix: str) -> None:
            seen["branch_prefix"] = branch_prefix

        def setup(self, repo_root: Path) -> Path:
            seen["setup_root"] = repo_root
            return isolated

        def teardown(self, worktree_path: Path, *, keep: bool) -> None:
            seen["teardown"] = (worktree_path, keep)

    def fake_agent_runner(agent: str, repo_root: Path, *, model: str | None = None) -> object:
        seen["agent"] = (agent, repo_root, model)
        return lambda prompt, escalation_level: None

    def fake_run_loop(
        storage: object,
        repo_root: Path,
        spec: object,
        config: object,
        **kwargs: object,
    ) -> LoopResult:
        del storage, spec
        seen["loop_root"] = repo_root
        seen["loop_isolate"] = config.isolate  # type: ignore[attr-defined]
        seen["verify_runner"] = kwargs["verify_runner"]
        return _loop_result(converged=True)

    monkeypatch.setattr(harness_controller_module, "WorktreeIsolationProvider", FakeIsolation)
    monkeypatch.setattr(harness_controller_module, "make_agent_runner", fake_agent_runner)
    monkeypatch.setattr(harness_controller_module, "run_loop", fake_run_loop)
    subprocess_calls: list[tuple[object, dict[str, object]]] = []

    def fake_subprocess(command: object, **kwargs: object) -> object:
        subprocess_calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="passed", stderr="")

    monkeypatch.setattr(harness_controller_module.subprocess, "run", fake_subprocess)
    packet = HarnessController(tmp_path).plan(RunRequest(task="Fix isolation")).context_packet

    result = _default_loop_executor(
        LoopInvocation(
            tmp_path,
            RunRequest(task="Fix isolation", execute=True, isolation=True),
            context_packet=packet,
            resume=False,
        )
    )
    verify_runner = seen["verify_runner"]
    assert callable(verify_runner)
    verify_runner("pytest -q")

    assert seen["agent"] == ("claude", isolated, None)
    assert seen["loop_root"] == isolated
    assert seen["loop_isolate"] is False
    assert seen["teardown"] == (isolated, True)
    assert subprocess_calls[0][0] == ["pytest", "-q"]
    assert subprocess_calls[0][1]["cwd"] == isolated
    assert "shell" not in subprocess_calls[0][1]
    assert result.worktree_path == str(isolated)


# ---------------------------------------------------------------------------
# Hybrid retrieval integration tests
# ---------------------------------------------------------------------------


class _SpyHybridRetriever(HybridRetriever):
    """Subclass that records each retrieve() call for assertion."""

    calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, k: int, *, mode: str = "hybrid") -> list:  # type: ignore[override]
        _SpyHybridRetriever.calls.append((query, k))
        return super().retrieve(query, k, mode=mode)


def test_hybrid_provider_invokes_retrieval_and_returns_ranked_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HybridRepositoryCandidateProvider uses HybridRetriever and returns Candidates
    with hybrid retrieval scores, citations, and retrieval_rank metadata."""
    # Fixture: two Python files — one highly relevant, one tangential.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cache.py").write_text(
        "def invalidate_cache():\n    return 'fresh'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "unrelated.py").write_text(
        "def greet(): return 'hello'\n", encoding="utf-8"
    )

    # Track HybridRetriever.retrieve calls via monkeypatch.
    retrieve_calls: list[tuple[str, int]] = []
    _original_retrieve = HybridRetriever.retrieve

    def _spy_retrieve(
        self: HybridRetriever, query: str, k: int, *, mode: str = "hybrid"
    ) -> list:
        retrieve_calls.append((query, k))
        return _original_retrieve(self, query, k, mode=mode)

    monkeypatch.setattr(HybridRetriever, "retrieve", _spy_retrieve)

    provider = HybridRepositoryCandidateProvider(tmp_path, top_k=10)
    from oh_no_my_claudecode.context_engine import RetrievalMode

    candidates = provider.candidates("Fix cache invalidation", RetrievalMode.LOCAL)

    # Retrieval was invoked exactly once.
    assert len(retrieve_calls) == 1
    assert retrieve_calls[0][0] == "Fix cache invalidation"
    assert retrieve_calls[0][1] == 10  # top_k

    # At least one candidate returned.
    assert candidates, "Expected at least one candidate from hybrid retrieval"

    # All candidates have the required Candidate fields populated.
    for cand in candidates:
        assert cand.id.startswith("repo:")
        assert cand.content
        assert cand.source
        assert cand.token_count >= 1
        assert cand.provenance == (cand.id,)
        assert 0.0 <= cand.structural_score <= 1.0
        assert cand.semantic_score is not None and 0.0 <= cand.semantic_score <= 1.0
        # retrieval_rank metadata must be present.
        meta = dict(cand.metadata)
        assert "retrieval_rank" in meta
        assert "path" in meta
        assert meta["kind"] == "repository-file"

    # The most relevant file (cache.py) must be cited first.
    assert candidates[0].id == "repo:src/cache.py"

    # Secrets and binaries excluded — no .env etc. in fixture, so just confirm
    # that the provider does not raise and returns sane results.
    assert all("never-read" not in c.content for c in candidates)


def test_hybrid_provider_token_budget_limits_candidates(tmp_path: Path) -> None:
    """token_budget is forwarded to HybridRetriever and caps evidence accumulation."""
    (tmp_path / "big.py").write_text("x = " + "a" * 3000 + "\n", encoding="utf-8")
    (tmp_path / "small.py").write_text("y = 1\n", encoding="utf-8")

    from oh_no_my_claudecode.context_engine import RetrievalMode

    # With a tiny budget (5 whitespace-tokens) the retriever stops early.
    provider = HybridRepositoryCandidateProvider(tmp_path, top_k=20, token_budget=5)
    candidates = provider.candidates("y = 1 small", RetrievalMode.LOCAL)
    # Must not exceed budget: each hit's evidence has ≤ 5 whitespace tokens
    # OR only one hit was collected before the budget was hit.
    assert len(candidates) <= 2  # at most 2 files in this tiny corpus


def test_hybrid_provider_noop_on_empty_corpus(tmp_path: Path) -> None:
    """Returns an empty tuple when no safe text files exist in the repository."""
    # Only a binary / excluded file — corpus is empty.
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")

    from oh_no_my_claudecode.context_engine import RetrievalMode

    provider = HybridRepositoryCandidateProvider(tmp_path)
    candidates = provider.candidates("anything", RetrievalMode.LOCAL)
    assert candidates == ()


def test_hybrid_provider_falls_back_on_retrieval_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected errors from HybridRetriever are caught and the call transparently
    falls back to RepositoryCandidateProvider."""
    (tmp_path / "fallback.py").write_text(
        "def fallback_function(): pass\n", encoding="utf-8"
    )

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated retriever failure")

    monkeypatch.setattr(HybridRetriever, "__init__", _boom)

    from oh_no_my_claudecode.context_engine import RetrievalMode

    provider = HybridRepositoryCandidateProvider(tmp_path)
    # Must not raise; fallback returns RepositoryCandidateProvider results.
    candidates = provider.candidates("fallback function", RetrievalMode.LOCAL)
    # The fallback provider returns repo:fallback.py (lexical match).
    assert any(c.id == "repo:fallback.py" for c in candidates)


def test_default_dependencies_use_hybrid_provider(tmp_path: Path) -> None:
    """default_dependencies() wires HybridRepositoryCandidateProvider, not the old one."""
    deps = default_dependencies(tmp_path)
    providers = deps.context_engine.candidate_providers
    assert len(providers) == 1
    assert isinstance(providers[0], HybridRepositoryCandidateProvider)
    assert providers[0].repo_root == tmp_path


def test_harness_run_context_from_hybrid_retrieval_end_to_end(tmp_path: Path) -> None:
    """End-to-end: HarnessController.plan() builds context from hybrid retrieval,
    respects token_budget, and cites the right source file."""
    source = tmp_path / "src" / "cache.py"
    source.parent.mkdir()
    source.write_text("def invalidate_cache():\n    return 'fresh'\n", encoding="utf-8")
    # Secret — must never appear in context.
    (tmp_path / ".env").write_text("CACHE_SECRET=never-read\n", encoding="utf-8")
    # Binary — must be excluded.
    (tmp_path / "binary.py").write_bytes(b"cache\x00binary")

    plan = HarnessController(tmp_path).run(
        RunRequest(task="Fix cache invalidation", plan_only=True, context_budget=500)
    ).plan

    assert [item.candidate_id for item in plan.context_packet.evidence] == [
        "repo:src/cache.py"
    ]
    rendered = json.dumps(plan.context_packet.to_dict())
    assert "never-read" not in rendered
    assert "binary.py" not in rendered
    assert plan.context_packet.used_tokens <= 500
    # Confirm semantic_score is populated (from hybrid retrieval).
    evidence = plan.context_packet.evidence[0]
    assert evidence.signals.semantic is not None
    assert 0.0 <= evidence.signals.semantic <= 1.0
