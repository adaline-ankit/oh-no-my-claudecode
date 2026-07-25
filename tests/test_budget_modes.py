"""Tests for tiny/standard/deep budget modes and their run-path wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.harness_run.budget_modes import (
    BudgetMode,
    resolve_budget_profile,
)
from oh_no_my_claudecode.harness_run.controller import HarnessController
from oh_no_my_claudecode.harness_run.models import RunRequest


def test_profiles_are_ordered_by_budget() -> None:
    tiny = resolve_budget_profile(BudgetMode.TINY)
    std = resolve_budget_profile(BudgetMode.STANDARD)
    deep = resolve_budget_profile(BudgetMode.DEEP)
    assert tiny.token_budget < std.token_budget < deep.token_budget
    assert tiny.top_k < std.top_k < deep.top_k


def test_code_is_bm25_first_except_deep() -> None:
    assert resolve_budget_profile(BudgetMode.TINY).retrieval_mode == "bm25"
    assert resolve_budget_profile(BudgetMode.STANDARD).retrieval_mode == "bm25"
    assert resolve_budget_profile(BudgetMode.DEEP).retrieval_mode == "hybrid"


def test_tiny_uses_utility_first_packing() -> None:
    assert resolve_budget_profile(BudgetMode.TINY).utility_first is True
    assert resolve_budget_profile(BudgetMode.STANDARD).utility_first is False


def test_override_replaces_token_budget_only() -> None:
    profile = resolve_budget_profile(BudgetMode.TINY, token_budget_override=9_999)
    assert profile.token_budget == 9_999
    assert profile.top_k == resolve_budget_profile(BudgetMode.TINY).top_k
    assert profile.retrieval_mode == "bm25"


def test_override_ignored_when_non_positive() -> None:
    profile = resolve_budget_profile(BudgetMode.STANDARD, token_budget_override=0)
    assert profile.token_budget == resolve_budget_profile(BudgetMode.STANDARD).token_budget


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="huge"):
        resolve_budget_profile("huge")


def test_controller_builds_mode_aware_dependencies(tmp_path: Path) -> None:
    controller = HarnessController(tmp_path)
    request = RunRequest(task="fix the cache layer", budget_mode=BudgetMode.DEEP)
    controller.plan(request)
    provider = controller.dependencies.context_engine.candidate_providers[0]
    assert provider.retrieval_mode == "hybrid"  # type: ignore[attr-defined]
    assert provider.top_k == 40  # type: ignore[attr-defined]

    controller_tiny = HarnessController(tmp_path)
    controller_tiny.plan(RunRequest(task="fix the cache layer", budget_mode=BudgetMode.TINY))
    assert controller_tiny.dependencies.context_engine.config.utility_first is True
    tiny_provider = controller_tiny.dependencies.context_engine.candidate_providers[0]
    assert tiny_provider.retrieval_mode == "bm25"  # type: ignore[attr-defined]


def test_injected_dependencies_are_not_overridden(tmp_path: Path) -> None:
    from oh_no_my_claudecode.harness_run.controller import default_dependencies

    injected = default_dependencies(tmp_path, resolve_budget_profile(BudgetMode.DEEP))
    controller = HarnessController(tmp_path, dependencies=injected)
    controller.plan(RunRequest(task="anything at all", budget_mode=BudgetMode.TINY))
    # Injected deps win: still the DEEP-configured hybrid provider.
    provider = controller.dependencies.context_engine.candidate_providers[0]
    assert provider.retrieval_mode == "hybrid"  # type: ignore[attr-defined]
