from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService, _detect_leaked_keys
from oh_no_my_claudecode.models import LLMProviderType


def test_doctor_exit_code_zero_when_checks_pass(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.generate_claude_md(no_llm=True)
    service.sync_commit()
    service.install_sync_hook()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "ONMC Health Check" in result.stdout


def test_doctor_exit_code_zero_when_provider_env_var_is_missing(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.configure_llm(
        provider=LLMProviderType.ANTHROPIC,
        model="claude-sonnet-4-5",
        api_key_env_var="ANTHROPIC_API_KEY",
        temperature=0.0,
        max_tokens=1200,
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY not set in current environment" in result.stdout


def test_doctor_exit_code_one_when_provider_key_is_invalid(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.configure_llm(
        provider=LLMProviderType.ANTHROPIC,
        model="claude-sonnet-4-5",
        api_key_env_var="ANTHROPIC_API_KEY",
        temperature=0.0,
        max_tokens=1200,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-invalid-test-key")
    monkeypatch.setattr(
        "oh_no_my_claudecode.core.service.validate_provider_api_key",
        lambda provider, api_key: (False, "invalid credentials"),
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "anthropic key is invalid" in result.stdout.lower()


def test_detect_leaked_keys_finds_provider_secret_patterns(tmp_path: Path) -> None:
    onmc_dir = tmp_path / ".onmc"
    logs_dir = onmc_dir / "logs"
    logs_dir.mkdir(parents=True)
    leak_path = logs_dir / "llm-calls.jsonl"
    leak_path.write_text(
        "sk-ant-api03-this-value-should-trigger-a-doctor-warning-1234567890",
        encoding="utf-8",
    )

    warnings = _detect_leaked_keys(onmc_dir)

    assert len(warnings) == 1
    assert leak_path.as_posix() in warnings[0]


def test_doctor_warns_when_legacy_global_hooks_remain(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    fake_home = tmp_path / "home"
    global_settings = fake_home / ".claude" / "settings.json"
    global_settings.parent.mkdir(parents=True, exist_ok=True)
    global_settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostCompact": [
                        {
                            "matcher": "",
                            "hooks": [
                                {"type": "command", "command": "onmc hooks post-compact"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("oh_no_my_claudecode.hooks.installer.Path.home", lambda: fake_home)

    ok, report = service.doctor()

    assert ok is True
    assert any("Legacy onmc hooks" in warning for warning in report["warnings"])
    assert any("MCP server not registered" in line for line in report["claude"])
