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
from oh_no_my_claudecode.harness_run.controller import (
    _default_loop_executor,
    default_dependencies,
)
from oh_no_my_claudecode.loop.adapters import CodexCliAdapter
from oh_no_my_claudecode.loop.engine import _default_verify_runner
from oh_no_my_claudecode.loop.models import IterationContract, LoopResult
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
