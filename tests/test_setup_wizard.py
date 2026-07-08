from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from oh_no_my_claudecode.config import load_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.installer import install_claude_hooks
from oh_no_my_claudecode.models import LLMProviderType
from oh_no_my_claudecode.setup.detector import detect_environment
from oh_no_my_claudecode.setup.wizard import (
    _TOTAL_STEPS,
    _integration_phase,
    _provider_phase,
    _render_first_win,
    _ui_handoff,
    run_setup_wizard,
    should_seed_interactively,
)


def test_detector_identifies_claude_code_presence(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    user_settings = tmp_path / "home" / ".claude" / "settings.json"
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: user_settings,
    )
    install_claude_hooks(repo_root=sample_repo, global_settings_path=user_settings)

    detection = detect_environment(sample_repo)

    assert detection.repo_root == sample_repo
    assert detection.commit_count == 3
    assert detection.doc_count >= 2
    assert detection.project_type == "Python project"
    assert detection.claude_code_detected is True
    assert detection.hooks_installed is True
    assert detection.mcp_registered is True


def test_detector_reports_missing_integration(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: tmp_path / "no-home" / ".claude" / "settings.json",
    )

    detection = detect_environment(sample_repo)

    assert detection.claude_code_detected is False
    assert detection.hooks_installed is False
    assert detection.mcp_registered is False


def test_provider_phase_uses_existing_config_without_prompting(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.Prompt.ask",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt not expected")),
    )

    provider, model = _provider_phase(service, yes=False)

    assert provider == "mock"
    assert model == "mock-model"


def test_setup_yes_no_llm_runs_without_prompts(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: sample_repo / ".missing" / "settings.json",
    )

    result = run_setup_wizard(cwd=sample_repo, yes=True, no_llm=True)

    assert result.repo_root == sample_repo.as_posix()
    assert result.provider is None
    assert result.claude_md_generated is True
    assert (sample_repo / "CLAUDE.md").exists()


def test_integration_phase_installs_requested_surfaces(sample_repo: Path) -> None:
    class StubService:
        def __init__(self) -> None:
            self.installs: list[bool] = []
            self.ingest_hook = False

        def install_hooks(self, *, add_mcp_server: bool = False) -> None:
            self.installs.append(add_mcp_server)

        def install_ingest_hook(self) -> None:
            self.ingest_hook = True

    detection = replace(detect_environment(sample_repo), claude_code_detected=True)
    service = StubService()

    hooks_installed, mcp_registered, auto_sync_enabled = _integration_phase(
        service,  # type: ignore[arg-type]
        detection=detection,
        yes=True,
    )

    assert hooks_installed is True
    assert mcp_registered is True
    assert auto_sync_enabled is True
    assert service.installs == [False, True]
    assert service.ingest_hook is True


def test_provider_phase_rejects_raw_api_key_and_stores_env_var_name_only(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    raw_key = "sk-ant-api03-this-should-never-be-stored-in-config-or-logs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-env-value")
    answers = iter(["anthropic", "claude-sonnet-4-5", raw_key, "ANTHROPIC_API_KEY"])

    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.Prompt.ask",
        lambda *args, **kwargs: next(answers),
    )

    seen_keys: list[str] = []

    def fake_validate(provider: object, api_key: str) -> tuple[bool, str]:
        seen_keys.append(api_key)
        return True, "valid"

    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.validate_provider_api_key",
        fake_validate,
    )

    provider, model = _provider_phase(service, yes=False)
    config = load_config(sample_repo)
    config_text = (sample_repo / ".onmc" / "config.yaml").read_text(encoding="utf-8")

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-5"
    assert config.llm.api_key_env_var == "ANTHROPIC_API_KEY"
    assert raw_key not in config_text
    assert seen_keys == ["real-env-value"]


# ---------------------------------------------------------------------------
# New behavioral tests for the glow-up wizard
# ---------------------------------------------------------------------------


def test_step_count_constant_is_stable() -> None:
    """The exported step count must stay at 6 — tests + docs depend on it."""
    assert _TOTAL_STEPS == 6


def test_setup_yes_no_llm_returns_complete_setup_result(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """run_setup_wizard(yes=True, no_llm=True) must return a fully-populated SetupResult."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: sample_repo / ".missing" / "settings.json",
    )

    result = run_setup_wizard(cwd=sample_repo, yes=True, no_llm=True)

    assert result.repo_root == sample_repo.as_posix()
    assert result.provider is None
    assert result.model is None
    assert result.claude_md_generated is True
    assert isinstance(result.extracted_records, int)
    assert result.extracted_records >= 0


def test_setup_yes_no_llm_never_prompts(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """In yes=True mode no Prompt.ask / Confirm.ask should ever fire."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: sample_repo / ".missing" / "settings.json",
    )

    def _bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError("wizard prompted in non-interactive mode")

    monkeypatch.setattr("oh_no_my_claudecode.setup.wizard.Prompt.ask", _bomb)
    monkeypatch.setattr("oh_no_my_claudecode.setup.wizard.Confirm.ask", _bomb)

    # Should not raise
    run_setup_wizard(cwd=sample_repo, yes=True, no_llm=True)


def test_setup_yes_no_llm_never_launches_server(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """In yes=True mode _ui_handoff must NOT call subprocess.Popen (would hang CI).

    We test _ui_handoff directly with yes=True and assert it never invokes Popen.
    """
    import oh_no_my_claudecode.setup.wizard as wizard_mod

    popen_calls: list[object] = []

    def _bomb_popen(cmd: object, **kwargs: object) -> object:
        popen_calls.append(cmd)
        raise AssertionError(f"subprocess.Popen must not be called in yes=True mode: {cmd}")

    monkeypatch.setattr(wizard_mod.subprocess, "Popen", _bomb_popen)

    wizard_mod._ui_handoff(yes=True)  # noqa: SLF001

    assert popen_calls == [], "subprocess.Popen must not be called in yes=True mode"


def test_ui_handoff_yes_mode_never_prompts_or_spawns(monkeypatch: object) -> None:
    """_ui_handoff(yes=True) must not ask and not call Popen."""
    launched: list[object] = []
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.subprocess.Popen",
        lambda *a, **kw: launched.append(a),
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.Confirm.ask",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not prompt")),
    )

    _ui_handoff(yes=True)  # must complete silently

    assert launched == []


def test_first_win_skipped_gracefully_on_empty_brain(sample_repo: Path) -> None:
    """_render_first_win must not raise when the brain has no memories."""
    service = OnmcService(sample_repo)
    service.init_project()
    # Do NOT call ingest — brain is empty
    detection = detect_environment(sample_repo)

    # Must not raise anything
    _render_first_win(service, detection)


def test_first_win_skipped_gracefully_on_recall_exception(sample_repo: Path) -> None:
    """_render_first_win must swallow arbitrary exceptions from recall."""
    service = OnmcService(sample_repo)
    service.init_project()
    detection = detect_environment(sample_repo)

    with patch.object(service, "recall", side_effect=RuntimeError("boom")):
        _render_first_win(service, detection)  # must not raise


def test_should_seed_interactively_false_when_yes() -> None:
    """Non-interactive mode must never trigger seeding regardless of memory count."""
    assert should_seed_interactively(0, yes=True) is False
    assert should_seed_interactively(1, yes=True) is False


def test_should_seed_interactively_true_when_sparse_and_interactive(
    monkeypatch: object,
) -> None:
    """Interactive TTY mode with <5 memories should offer seeding."""
    import sys as _sys

    import oh_no_my_claudecode.setup.wizard as _wiz

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    assert _wiz.should_seed_interactively(0, yes=False) is True
    assert _wiz.should_seed_interactively(4, yes=False) is True
    assert _wiz.should_seed_interactively(5, yes=False) is False


def test_should_seed_interactively_false_when_no_tty(monkeypatch: object) -> None:
    """Non-TTY stdin (piped install) must never trigger interactive seeding."""
    import sys as _sys

    import oh_no_my_claudecode.setup.wizard as _wiz

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    assert _wiz.should_seed_interactively(0, yes=False) is False
    assert _wiz.should_seed_interactively(4, yes=False) is False


def test_setup_non_tty_no_prompts(sample_repo: object, monkeypatch: object) -> None:
    """run_setup_wizard with non-TTY stdin and yes=False must not call any prompt.

    This simulates the curl|bash scenario where stdin is a pipe and --yes is
    not explicitly passed.  All prompts must auto-use their defaults.
    """
    import sys as _sys
    from pathlib import Path as _Path

    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.user_settings_path",
        lambda: _Path(str(sample_repo)) / ".missing" / "settings.json",
    )
    # Simulate a non-TTY stdin (pipe)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)

    def _bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"wizard prompted under non-TTY stdin: {args}")

    monkeypatch.setattr("oh_no_my_claudecode.setup.wizard.Prompt.ask", _bomb)
    monkeypatch.setattr("oh_no_my_claudecode.setup.wizard.Confirm.ask", _bomb)

    # Must complete without raising (uses all defaults: generate CLAUDE.md, skip hooks)
    result = run_setup_wizard(cwd=_Path(str(sample_repo)), yes=False, no_llm=True)

    assert result.claude_md_generated is True


def test_ui_handoff_non_tty_no_prompts_or_spawns(monkeypatch: object) -> None:
    """_ui_handoff with non-TTY stdin must not prompt and not call Popen."""
    import sys as _sys

    import oh_no_my_claudecode.setup.wizard as _wiz

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    launched: list[object] = []
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.subprocess.Popen",
        lambda *a, **kw: launched.append(a),
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.Confirm.ask",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not prompt under non-TTY")),
    )

    _wiz._ui_handoff(yes=False)  # noqa: SLF001

    assert launched == []
