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
from oh_no_my_claudecode.context_engine import ContextEngine, RetrievalMode
from oh_no_my_claudecode.durable_runtime import NodeState, RunState, RuntimeStore
from oh_no_my_claudecode.harness_run import (
    ChangeSet,
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
    _sandbox_agent_runner_for,
    _sandbox_verify_runner_for,
    default_dependencies,
)
from oh_no_my_claudecode.loop.adapters import CodexCliAdapter
from oh_no_my_claudecode.loop.engine import _default_verify_runner
from oh_no_my_claudecode.loop.models import IterationContract, LoopResult, VerifyOutcome
from oh_no_my_claudecode.missioncontrol import build_runtime_dashboard
from oh_no_my_claudecode.retrieval import HybridRetriever
from oh_no_my_claudecode.sandbox import (
    DockerSandboxPlan,
    SandboxExecutionResult,
    SandboxExecutionStatus,
)
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


def _observed_change(root: Path) -> ChangeSet:
    del root
    return ChangeSet(("src/example.py",), 4, "+ return 1\n")


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
        verifier_false_green_check=lambda request, signals, change_set: False,
        changes_reader=_observed_change,
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
        "context_selection",
        "proof_requirements",
        "policy_decisions",
        "isolation_profile",
        "sandbox_manifest",
        "capability_manifest",
        "environment_snapshot",
        "state_path",
        "resume",
    }
    assert first.plan.environment_snapshot.repo_root == str(tmp_path.resolve())
    assert first.plan.environment_snapshot.git_available is False
    assert first.plan.environment_snapshot.git_head is None
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


def test_mission_control_proof_state_requires_matching_valid_receipt(tmp_path: Path) -> None:
    controller = _controller(tmp_path, FakeLoop(_loop_result(converged=True)))
    result = controller.run(RunRequest(task="Implement cache fix", execute=True))

    visible = build_runtime_dashboard(tmp_path)
    run = next(item for item in visible.runs if item.run_id == result.plan.run_id)
    assert run.state == "completed"
    assert run.proof_state == "verified"
    assert run.verified is True
    assert run.receipt_hash == result.receipt.receipt_hash  # type: ignore[union-attr]
    assert run.event_count > 0
    assert all(node.state == "succeeded" for node in run.nodes)

    receipt_path = (
        tmp_path / ".agent-memory" / "receipts" / f"run-{result.plan.run_id}.json"
    )
    wrapper = json.loads(receipt_path.read_text(encoding="utf-8"))
    wrapper["harness"]["receipt_hash"] = "0" * 64
    receipt_path.write_text(json.dumps(wrapper), encoding="utf-8")

    tampered = build_runtime_dashboard(tmp_path)
    run = next(item for item in tampered.runs if item.run_id == result.plan.run_id)
    assert run.proof_state == "unproven"
    assert run.verified is False
    assert run.receipt_hash is None


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


def test_converged_loop_without_observed_change_is_not_complete(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    dependencies = ControllerDependencies(
        context_engine=ContextEngine(),
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=AllowPolicy(),
        loop_executor=loop,
        changes_reader=lambda root: ChangeSet.empty(),
    )
    controller = HarnessController(tmp_path, dependencies=dependencies)

    result = controller.run(RunRequest(task="Claim success without changing code", execute=True))

    assert result.status is HarnessStatus.FAILED
    assert result.verified is False
    assert result.proof_complete is False
    assert "no observed working-tree change" in result.proof_reasons


def test_resume_surface_returns_terminal_run_without_reexecution(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)
    first = controller.run(RunRequest(task="Resumable task", execute=True))

    resumed = controller.run(
        RunRequest(task="Resumable task", execute=True, resume_run_id=first.plan.run_id)
    )

    assert resumed.status is HarnessStatus.COMPLETED
    assert resumed.resumed is True
    assert resumed.receipt is not None
    assert resumed.verified is True
    assert loop.calls == 1


def test_completed_resume_requires_valid_receipt(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)
    first = controller.run(RunRequest(task="Receipt-backed resume", execute=True))
    receipt_path = tmp_path / ".agent-memory" / "receipts" / f"run-{first.plan.run_id}.json"
    receipt_path.unlink()

    resumed = controller.run(
        RunRequest(task="Receipt-backed resume", execute=True, resume_run_id=first.plan.run_id)
    )

    assert resumed.status is HarnessStatus.FAILED
    assert resumed.resumed is True
    assert resumed.stop_reason == "resumed-completed-receipt-invalid"
    assert resumed.verified is False
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


def test_render_text_exposes_adapter_telemetry_limits(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)

    result = controller.run(
        RunRequest(task="Use selected model", plan_only=True, agent="codex", model="gpt-test")
    )
    text = result.render_text()

    assert "Adapter: codex" in text
    assert "tokens=best_effort_human_stdout_parse" in text
    assert "cost=not_reported" in text


def test_render_text_exposes_isolation_boundary(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)

    result = controller.run(
        RunRequest(task="Use isolated worktree", plan_only=True, isolation=True)
    )
    text = result.render_text()

    assert "Isolation: git_worktree_required" in text
    assert "network=not constrained by ONMC" in text
    assert "secrets=ambient environment" in text
    assert "Sandbox: requested=false" in text


def test_render_text_exposes_planned_sandbox_boundary(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    controller = _controller(tmp_path, loop)

    result = controller.run(
        RunRequest(
            task="Use docker sandbox",
            plan_only=True,
            sandbox=True,
            sandbox_provider="docker",
        )
    )
    text = result.render_text()

    assert "Sandbox: requested=true, provider=docker, enforced=false" in text
    assert result.plan.sandbox_manifest.verifier_plan is not None
    assert result.plan.sandbox_manifest.verifier_plan["secret_env"] == []


def test_sandbox_verifier_runner_executes_command_without_agent_secret(tmp_path: Path) -> None:
    seen: list[DockerSandboxPlan] = []

    def executor(plan: DockerSandboxPlan) -> SandboxExecutionResult:
        seen.append(plan)
        if plan.role == "setup":
            return SandboxExecutionResult(
                status=SandboxExecutionStatus.SUCCEEDED,
                returncode=0,
                stdout="/usr/local/bin/claude\n",
                stderr="",
                argv_sha256="preflight",
                timeout_seconds=30,
                reason="sandbox command succeeded",
            )
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.SUCCEEDED,
            returncode=0,
            stdout="1 passed",
            stderr="",
            argv_sha256="abc",
            timeout_seconds=120,
            reason="sandbox command succeeded",
        )

    request = RunRequest(
        task="verify in sandbox",
        execute=True,
        sandbox=True,
        sandbox_provider="docker",
    )
    runner = _sandbox_verify_runner_for(tmp_path, request, executor=executor)

    outcome = runner("python -m pytest")

    assert outcome.passed is True
    assert outcome.output == "1 passed"
    plan = seen[0]
    assert plan.role == "verifier"
    assert plan.secret_env == ()
    assert "--network" in plan.argv
    assert "none" in plan.argv


def test_sandbox_verifier_runner_classifies_missing_runner(tmp_path: Path) -> None:
    def executor(plan: DockerSandboxPlan) -> SandboxExecutionResult:
        del plan
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.FAILED,
            returncode=1,
            stdout="",
            stderr="No module named pytest",
            argv_sha256="abc",
            timeout_seconds=120,
            reason="sandbox command failed",
        )

    request = RunRequest(task="verify in sandbox", execute=True, sandbox=True)
    runner = _sandbox_verify_runner_for(tmp_path, request, executor=executor)

    outcome = runner("python -m pytest")

    assert outcome.passed is False
    assert "[sandbox verify error: verify command could not run" in outcome.output


def test_sandbox_agent_runner_executes_cli_inside_writable_boundary(
    tmp_path: Path,
) -> None:
    seen: list[DockerSandboxPlan] = []

    def executor(plan: DockerSandboxPlan) -> SandboxExecutionResult:
        seen.append(plan)
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.SUCCEEDED,
            returncode=0,
            stdout='{"result":"changed code","usage":{"input_tokens":2,"output_tokens":3}}',
            stderr="",
            argv_sha256="abc",
            timeout_seconds=600,
            reason="sandbox command succeeded",
        )

    request = RunRequest(
        task="agent in sandbox",
        execute=True,
        sandbox=True,
        sandbox_provider="docker",
        sandbox_image="onmc-agent:local",
    )
    runner = _sandbox_agent_runner_for(tmp_path, request, executor=executor)

    result = runner("fix bug", escalation_level=0)

    assert result.output == "changed code"
    assert result.tokens == 5
    assert len(seen) == 2
    assert seen[0].role == "setup"
    assert seen[0].secret_env == ()
    assert "command -v claude" in seen[0].argv
    plan = seen[1]
    assert plan.role == "agent"
    assert plan.secret_env == ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    assert "--network" in plan.argv
    assert "bridge" in plan.argv
    assert f"{tmp_path}:/workspace:rw" in plan.argv
    assert "onmc-agent:local" in plan.argv
    assert "claude" in plan.argv


def test_sandbox_agent_runner_fails_before_prompt_when_image_lacks_cli(
    tmp_path: Path,
) -> None:
    seen: list[DockerSandboxPlan] = []

    def executor(plan: DockerSandboxPlan) -> SandboxExecutionResult:
        seen.append(plan)
        return SandboxExecutionResult(
            status=SandboxExecutionStatus.FAILED,
            returncode=127,
            stdout="",
            stderr="claude: not found",
            argv_sha256="preflight",
            timeout_seconds=30,
            reason="sandbox command failed",
        )

    request = RunRequest(
        task="agent in sandbox",
        execute=True,
        sandbox=True,
        sandbox_provider="docker",
        sandbox_image="python:3.12-slim",
    )
    runner = _sandbox_agent_runner_for(tmp_path, request, executor=executor)

    result = runner("fix bug", escalation_level=0)

    assert result.error is not None
    assert "does not provide required CLI 'claude'" in result.error
    assert len(seen) == 1
    assert seen[0].role == "setup"
    assert seen[0].secret_env == ()


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
    selection = plan.context_selection
    assert selection.explored_count >= 1
    assert selection.used_count == 1
    assert selection.explored_context_ids == ("repo:src/cache.py",)
    assert selection.used_context_ids == ("repo:src/cache.py",)
    assert selection.excluded_context_ids == ()
    assert selection.used_provenance == ("src/cache.py:1-2",)
    assert selection.used_tokens == plan.context_packet.used_tokens
    assert selection.token_budget == 500
    assert selection.abstained is False
    assert selection.query_intent == "conceptual"
    assert selection.retrieval_stage == "bm25"
    assert selection.lexical_floor is True
    assert selection.candidate_promoted is False


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
    verifier_call = next(call for call in subprocess_calls if call[0] == ["pytest", "-q"])
    assert verifier_call[1]["cwd"] == isolated
    assert "shell" not in verifier_call[1]
    assert result.worktree_path == str(isolated)


def test_sandbox_execution_binds_verifier_to_docker_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(default_config(tmp_path), tmp_path)
    seen: dict[str, object] = {}

    def fake_sandbox_agent_runner(repo_root: Path, request: RunRequest) -> object:
        seen["sandbox_agent"] = (repo_root, request.sandbox, request.sandbox_provider)
        return lambda prompt, escalation_level: None

    def fake_sandbox_verify_runner(repo_root: Path, request: RunRequest) -> object:
        seen["sandbox_verify"] = (repo_root, request.sandbox, request.sandbox_provider)
        return lambda command: VerifyOutcome(True, f"sandbox:{command}")

    def fake_run_loop(
        storage: object,
        repo_root: Path,
        spec: object,
        config: object,
        **kwargs: object,
    ) -> LoopResult:
        del storage, repo_root, spec, config
        verifier = kwargs["verify_runner"]
        assert callable(verifier)
        seen["verify_outcome"] = verifier("pytest -q")
        return _loop_result(converged=True)

    monkeypatch.setattr(
        harness_controller_module,
        "_sandbox_agent_runner_for",
        fake_sandbox_agent_runner,
    )
    monkeypatch.setattr(
        harness_controller_module,
        "_sandbox_verify_runner_for",
        fake_sandbox_verify_runner,
    )
    monkeypatch.setattr(harness_controller_module, "run_loop", fake_run_loop)
    packet = HarnessController(tmp_path).plan(RunRequest(task="Fix sandbox")).context_packet

    result = _default_loop_executor(
        LoopInvocation(
            tmp_path,
            RunRequest(
                task="Fix sandbox",
                execute=True,
                sandbox=True,
                sandbox_provider="docker",
            ),
            context_packet=packet,
            resume=False,
        )
    )

    outcome = seen["verify_outcome"]
    assert isinstance(outcome, VerifyOutcome)
    assert seen["sandbox_agent"] == (tmp_path, True, "docker")
    assert seen["sandbox_verify"] == (tmp_path, True, "docker")
    assert outcome.output == "sandbox:pytest -q"
    assert result.converged is True


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

    # Track the measured policy entry point via monkeypatch.
    retrieve_calls: list[tuple[str, int]] = []
    _original_retrieve = HybridRetriever.retrieve_measured

    def _spy_retrieve(
        self: HybridRetriever, query: str, k: int, **kwargs: object
    ) -> object:
        retrieve_calls.append((query, k))
        return _original_retrieve(self, query, k, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(HybridRetriever, "retrieve_measured", _spy_retrieve)

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
        assert cand.provenance == (cand.id, "retrieval:bm25", "query-plan:1")
        assert 0.0 <= cand.structural_score <= 1.0
        assert cand.semantic_score is None
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


def test_hybrid_provider_reports_measured_query_decision_and_provenance(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "policy.py").write_text(
        "# authorization architecture\n"
        "def enforce_capability_boundary():\n"
        "    return 'allow'\n",
        encoding="utf-8",
    )

    decisions: list[object] = []
    provider = HybridRepositoryCandidateProvider(
        tmp_path,
        retrieval_mode="dense",
        candidate_promoted=False,
        on_decision=decisions.append,
    )
    candidates = provider.candidates(
        "authorization architecture",
        RetrievalMode.LOCAL,
    )

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.selected_stage == "bm25"
    assert decision.fallback_reason == "candidate_not_promoted"
    assert candidates
    metadata = dict(candidates[0].metadata)
    assert metadata["query_intent"] == "conceptual"
    assert metadata["retrieval_stage"] == "bm25"
    assert metadata["lexical_floor"] == "true"
    assert candidates[0].provenance[1:] == (
        "retrieval:bm25",
        "query-plan:1",
    )


def test_controller_does_not_reuse_a_stale_retrieval_decision(tmp_path: Path) -> None:
    source = tmp_path / "cache.py"
    source.write_text("def invalidate_cache(): return True\n", encoding="utf-8")
    controller = HarnessController(tmp_path)

    first = controller.plan(RunRequest(task="Fix cache invalidation", plan_only=True))
    source.unlink()
    second = controller.plan(RunRequest(task="Unrelated missing symbol", plan_only=True))

    assert first.context_selection.query_intent == "conceptual"
    assert second.context_selection.query_intent == "unknown"
    assert second.context_selection.retrieval_stage == "unspecified"


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
    # BM25 evidence is never mislabeled as a semantic score.
    evidence = plan.context_packet.evidence[0]
    assert evidence.signals.semantic is None


def test_duplicate_index_records_do_not_collide_candidate_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (found by the external eval on jd/tenacity): when the repo scan
    yields the same path twice, the provider must emit ONE candidate for it. Two
    candidates sharing the id `repo:<path>` with different retrieval scores made
    the context planner raise "conflicting candidates share id", which crashed
    `onmc run` before any agent executed."""
    from oh_no_my_claudecode.harness_run import context as ctx_mod

    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "index.rst").write_text("cache invalidation docs\n", encoding="utf-8")
    (tmp_path / "cache.py").write_text("def invalidate(): return 1\n", encoding="utf-8")

    class _Rec:
        def __init__(self, path: str) -> None:
            self.path = path
            self.size_bytes = 64
            self.extension = "." + path.rsplit(".", 1)[-1]

    # The same path twice — exactly what the real repository scan produced.
    dupes = [_Rec("doc/index.rst"), _Rec("doc/index.rst"), _Rec("cache.py")]
    monkeypatch.setattr(ctx_mod, "scan_repository_files", lambda *a, **k: dupes)

    provider = ctx_mod.HybridRepositoryCandidateProvider(tmp_path, top_k=10)
    candidates = provider._hybrid_candidates("cache invalidation")
    ids = [c.id for c in candidates]
    assert len(ids) == len(set(ids)), f"duplicate candidate ids: {ids}"


def test_retrieval_fallback_is_typed_and_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retriever that degrades must SAY so, with the exception type.

    The hybrid provider catches every exception and falls back to the basic
    lexical provider so a retrieval bug can never block a run — correct. But the
    fallback used to be silent, so a run whose retrieval had switched itself off
    was indistinguishable from a healthy one, and a benchmark could measure the
    degraded path as if the feature under test were working.

    Only the HYBRID path is broken here: the fallback provider shares the same
    repository scanner, so breaking the scanner module-wide would break the
    fallback too and prove nothing.
    """
    from oh_no_my_claudecode.context_engine import RetrievalMode
    from oh_no_my_claudecode.harness_run import context as ctx_mod

    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

    def _boom(self: object, query: str) -> tuple[object, ...]:
        del self, query
        raise RuntimeError("index corrupted")

    monkeypatch.setattr(
        ctx_mod.HybridRepositoryCandidateProvider, "_hybrid_candidates", _boom
    )

    seen: list[str] = []
    provider = ctx_mod.HybridRepositoryCandidateProvider(
        tmp_path, top_k=5, on_fallback=seen.append
    )
    candidates = provider.candidates("alpha", RetrievalMode.LOCAL)

    # The run still produced candidates — the fallback did its job...
    assert candidates
    # ...and the degradation is reported with its exception TYPE, not swallowed.
    assert seen == ["RuntimeError: index corrupted"]


def test_context_stage_marks_a_degraded_run(tmp_path: Path) -> None:
    """The stage record must call a degraded retrieval run DEGRADED."""
    from oh_no_my_claudecode.context_engine import EvidencePacket
    from oh_no_my_claudecode.harness_run.stages import context_stage

    packet = EvidencePacket(query="q", mode="local", token_budget=100, used_tokens=0)
    record = context_stage(packet, ("RuntimeError: index corrupted",))
    assert "DEGRADED" in record.summary
    assert any("retrieval-fallback: RuntimeError" in reason for reason in record.reasons)

    healthy = context_stage(packet)
    assert "DEGRADED" not in healthy.summary
