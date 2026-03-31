from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from oh_no_my_claudecode.config import load_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import LLMProviderType
from oh_no_my_claudecode.setup.detector import detect_environment
from oh_no_my_claudecode.setup.wizard import (
    _integration_phase,
    _provider_phase,
    run_setup_wizard,
)


def test_detector_identifies_claude_code_presence(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {"PreCompact": [], "PostCompact": []},
                "mcpServers": {"onmc": {"command": "onmc", "args": ["serve", "--mcp"]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.detector.claude_settings_path",
        lambda: settings_path,
    )

    detection = detect_environment(sample_repo)

    assert detection.repo_root == sample_repo
    assert detection.commit_count == 3
    assert detection.doc_count >= 2
    assert detection.project_type == "Python project"
    assert detection.claude_code_detected is True
    assert detection.hooks_installed is True
    assert detection.mcp_registered is True


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
        "oh_no_my_claudecode.setup.detector.claude_settings_path",
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
