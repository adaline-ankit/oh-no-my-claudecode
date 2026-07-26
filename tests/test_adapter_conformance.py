"""Recorded, offline conformance tests for every supported loop adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from oh_no_my_claudecode.loop.adapter_contract import (
    AdapterCapability,
    AdapterCapabilityError,
    SupportLevel,
    all_adapter_contracts,
    contract_for,
    require_comparable,
    shared_fully_supported,
)
from oh_no_my_claudecode.loop.adapters import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    CommandRunner,
    CompletedProc,
    OpenCodeCliAdapter,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "adapter_conformance"
PROVIDERS = ("claude", "codex", "opencode")
LIFECYCLE_CAPABILITIES = (
    AdapterCapability.START,
    AdapterCapability.OBSERVE,
    AdapterCapability.CANCEL,
    AdapterCapability.RESUME,
    AdapterCapability.COST,
)


def _fixtures() -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted(FIXTURE_DIR.glob("*.json"))]


def _recorded_runner(fixture: dict[str, Any]) -> tuple[CommandRunner, list[list[str]]]:
    calls: list[list[str]] = []

    def runner(cmd: list[str], cwd: str, timeout: int) -> CompletedProc:  # noqa: ARG001
        calls.append(cmd)
        if cmd[0] == "git":
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=int(fixture["returncode"]),
            stdout=str(fixture["stdout"]),
            stderr=str(fixture["stderr"]),
        )

    return runner, calls


def _adapter_factory(provider: str) -> type[
    ClaudeCliAdapter | CodexCliAdapter | OpenCodeCliAdapter
]:
    factories = {
        "claude": ClaudeCliAdapter,
        "codex": CodexCliAdapter,
        "opencode": OpenCodeCliAdapter,
    }
    return factories[provider]


def test_matrix_declares_every_capability_for_every_provider() -> None:
    contracts = all_adapter_contracts()

    assert tuple(contract.provider for contract in contracts) == PROVIDERS
    for contract in contracts:
        assert {item.capability for item in contract.capabilities} == set(AdapterCapability)
        for declaration in contract.capabilities:
            assert declaration.evidence.strip()
            if declaration.support is not SupportLevel.SUPPORTED:
                assert declaration.limitation.strip()


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda item: item["provider"])
def test_recorded_lifecycle_labels_match_matrix(fixture: dict[str, Any]) -> None:
    contract = contract_for(str(fixture["provider"]))
    operations = fixture["operations"]

    assert fixture["schema_version"] == "1"
    assert set(operations) == {capability.value for capability in LIFECYCLE_CAPABILITIES}
    for capability in LIFECYCLE_CAPABILITIES:
        recorded = operations[capability.value]
        declaration = contract.declaration(capability)
        assert recorded["support"] == declaration.support.value
        assert recorded["evidence"] == declaration.evidence


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda item: item["provider"])
def test_recorded_start_and_observe_parse_stably(
    fixture: dict[str, Any],
    tmp_path: Path,
) -> None:
    runner, calls = _recorded_runner(fixture)
    factory = _adapter_factory(str(fixture["provider"]))
    adapter = factory(
        tmp_path,
        model=str(fixture["model"]),
        command_runner=runner,
    )

    result = adapter(str(fixture["prompt"]), escalation_level=0)
    expected = fixture["expected"]

    assert result.output == expected["output"]
    assert result.tokens == expected["tokens"]
    assert result.cost_usd == expected["cost_usd"]
    assert result.error == expected["error"]
    agent_calls = [call for call in calls if call[0] != "git"]
    assert len(agent_calls) == 1
    assert agent_calls[0][0] == fixture["provider"]
    assert str(fixture["model"]) in agent_calls[0]


def test_cancel_and_resume_are_never_silently_imputed() -> None:
    for provider in PROVIDERS:
        contract = contract_for(provider)
        assert contract.declaration(AdapterCapability.CANCEL).support is SupportLevel.PARTIAL
        assert contract.declaration(AdapterCapability.RESUME).support is SupportLevel.UNSUPPORTED

        with pytest.raises(AdapterCapabilityError) as exc:
            contract.require(AdapterCapability.CANCEL)
        assert exc.value.classification == "unsupported-adapter-capability"
        assert exc.value.task_failure is False

        contract.require(AdapterCapability.CANCEL, allow_partial=True)
        with pytest.raises(AdapterCapabilityError):
            contract.require(AdapterCapability.RESUME, allow_partial=True)


def test_cost_is_unknown_and_excluded_when_any_arm_cannot_report_it() -> None:
    assert AdapterCapability.COST not in shared_fully_supported(PROVIDERS)

    with pytest.raises(AdapterCapabilityError) as exc:
        require_comparable(PROVIDERS, AdapterCapability.COST)

    assert exc.value.classification == "asymmetric-adapter-capability"
    assert "codex=unsupported" in str(exc.value)
    assert "opencode=unsupported" in str(exc.value)


def test_shared_contract_only_contains_fully_supported_fields() -> None:
    shared = shared_fully_supported(PROVIDERS)

    assert AdapterCapability.START in shared
    assert AdapterCapability.OBSERVE in shared
    assert AdapterCapability.MODEL_SELECTION in shared
    assert AdapterCapability.COST not in shared
    assert AdapterCapability.USAGE not in shared
    assert AdapterCapability.RESUME not in shared


def test_fixture_suite_covers_every_provider_without_live_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        raise AssertionError("recorded conformance must never spawn a live provider")

    monkeypatch.setattr("subprocess.run", forbidden)
    fixtures = _fixtures()
    assert {fixture["provider"] for fixture in fixtures} == set(PROVIDERS)
    assert all(str(fixture["cli_version"]).startswith("recorded-") for fixture in fixtures)
