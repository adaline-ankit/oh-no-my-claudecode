"""Honest, machine-readable conformance contract for coding-agent adapters.

The loop adapters are intentionally small synchronous wrappers.  This module
describes what those wrappers *actually* expose today, including partial and
unsupported lifecycle operations.  Unsupported capabilities are data, not
silently emulated behavior, so experiment code can exclude asymmetric fields
instead of treating an absent value as zero or success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ProviderName = Literal["claude", "codex", "opencode"]
PROVIDERS: tuple[ProviderName, ...] = ("claude", "codex", "opencode")


class AdapterCapability(StrEnum):
    """Operations and controls shared by the provider contract."""

    START = "start"
    OBSERVE = "observe"
    CANCEL = "cancel"
    RESUME = "resume"
    COST = "cost"
    MODEL_SELECTION = "model-selection"
    EFFORT = "effort"
    STRUCTURED_OUTPUT = "structured-output"
    USAGE = "usage"
    TOOL_LIMITS = "tool-limits"


class SupportLevel(StrEnum):
    """How completely an adapter implements a capability."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """One capability label plus the local evidence supporting that label."""

    capability: AdapterCapability
    support: SupportLevel
    evidence: str
    limitation: str = ""

    def __post_init__(self) -> None:
        if not self.evidence.strip():
            raise ValueError("capability evidence must not be empty")
        if self.support is not SupportLevel.SUPPORTED and not self.limitation.strip():
            raise ValueError("partial and unsupported capabilities require a limitation")

    def to_dict(self) -> dict[str, str]:
        return {
            "support": self.support.value,
            "evidence": self.evidence,
            "limitation": self.limitation,
        }


class AdapterCapabilityError(RuntimeError):
    """A requested adapter operation cannot be compared or executed honestly."""

    def __init__(
        self,
        message: str,
        *,
        classification: str,
        capability: AdapterCapability,
        providers: tuple[str, ...],
    ) -> None:
        self.classification = classification
        self.capability = capability
        self.providers = providers
        # Capability mismatch is experiment/runtime configuration evidence, not
        # proof that the coding task itself failed.
        self.task_failure = False
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProviderAdapterContract:
    """Complete capability matrix row for one provider adapter."""

    provider: ProviderName
    capabilities: tuple[CapabilityDeclaration, ...]
    schema_version: str = "1"

    def __post_init__(self) -> None:
        declared = [item.capability for item in self.capabilities]
        if len(declared) != len(set(declared)):
            raise ValueError(f"{self.provider} declares a capability more than once")
        missing = set(AdapterCapability) - set(declared)
        if missing:
            labels = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"{self.provider} is missing capability declarations: {labels}")

    def declaration(self, capability: AdapterCapability) -> CapabilityDeclaration:
        for declaration in self.capabilities:
            if declaration.capability is capability:
                return declaration
        raise AssertionError(f"validated matrix is missing {capability.value}")  # noqa: S101

    def require(
        self,
        capability: AdapterCapability,
        *,
        allow_partial: bool = False,
    ) -> CapabilityDeclaration:
        """Return the declaration or raise a classified non-task failure."""
        declaration = self.declaration(capability)
        if declaration.support is SupportLevel.SUPPORTED:
            return declaration
        if allow_partial and declaration.support is SupportLevel.PARTIAL:
            return declaration
        raise AdapterCapabilityError(
            f"{self.provider} {capability.value} is {declaration.support.value}: "
            f"{declaration.limitation}",
            classification="unsupported-adapter-capability",
            capability=capability,
            providers=(self.provider,),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "capabilities": {
                declaration.capability.value: declaration.to_dict()
                for declaration in self.capabilities
            },
        }


def _declaration(
    capability: AdapterCapability,
    support: SupportLevel,
    evidence: str,
    limitation: str = "",
) -> CapabilityDeclaration:
    return CapabilityDeclaration(capability, support, evidence, limitation)


_CONTRACTS: dict[ProviderName, ProviderAdapterContract] = {
    "claude": ProviderAdapterContract(
        provider="claude",
        capabilities=(
            _declaration(
                AdapterCapability.START,
                SupportLevel.SUPPORTED,
                "one-shot claude -p process invocation",
            ),
            _declaration(
                AdapterCapability.OBSERVE,
                SupportLevel.SUPPORTED,
                "recorded JSON result envelope",
            ),
            _declaration(
                AdapterCapability.CANCEL,
                SupportLevel.PARTIAL,
                "timeout terminates the process; no addressable run handle",
                "ONMC cannot cancel an already-returned or externally resumed Claude run",
            ),
            _declaration(
                AdapterCapability.RESUME,
                SupportLevel.UNSUPPORTED,
                "the adapter does not persist or accept a Claude session id",
                "session resume is not wired through the loop adapter",
            ),
            _declaration(
                AdapterCapability.COST,
                SupportLevel.PARTIAL,
                "available only when total_cost_usd is present",
                "missing provider cost remains unknown rather than zero",
            ),
            _declaration(
                AdapterCapability.MODEL_SELECTION,
                SupportLevel.SUPPORTED,
                "--model is passed to Claude CLI",
            ),
            _declaration(
                AdapterCapability.EFFORT,
                SupportLevel.UNSUPPORTED,
                "no effort flag is accepted by ClaudeCliAdapter",
                "matched effort experiments must omit this arm or add explicit support",
            ),
            _declaration(
                AdapterCapability.STRUCTURED_OUTPUT,
                SupportLevel.PARTIAL,
                "--output-format json is parsed across recorded result layouts",
                "unknown CLI layouts fall back to raw stdout",
            ),
            _declaration(
                AdapterCapability.USAGE,
                SupportLevel.PARTIAL,
                "tokens are read when the JSON result contains usage",
                "missing usage remains unknown",
            ),
            _declaration(
                AdapterCapability.TOOL_LIMITS,
                SupportLevel.PARTIAL,
                "acceptEdits scopes edit approval",
                "no per-tool call ceiling is enforced by this adapter",
            ),
        ),
    ),
    "codex": ProviderAdapterContract(
        provider="codex",
        capabilities=(
            _declaration(
                AdapterCapability.START,
                SupportLevel.SUPPORTED,
                "one-shot codex exec process invocation",
            ),
            _declaration(
                AdapterCapability.OBSERVE,
                SupportLevel.SUPPORTED,
                "recorded stdout and exit status",
            ),
            _declaration(
                AdapterCapability.CANCEL,
                SupportLevel.PARTIAL,
                "timeout terminates the process; no addressable run handle",
                "ONMC cannot cancel an already-returned or externally resumed Codex run",
            ),
            _declaration(
                AdapterCapability.RESUME,
                SupportLevel.UNSUPPORTED,
                "the adapter does not persist or accept a Codex thread id",
                "thread resume is not wired through codex exec",
            ),
            _declaration(
                AdapterCapability.COST,
                SupportLevel.UNSUPPORTED,
                "codex exec does not report machine-readable cost",
                "cost must remain unknown and be excluded from matched comparisons",
            ),
            _declaration(
                AdapterCapability.MODEL_SELECTION,
                SupportLevel.SUPPORTED,
                "--model is passed to codex exec",
            ),
            _declaration(
                AdapterCapability.EFFORT,
                SupportLevel.UNSUPPORTED,
                "no reasoning-effort flag is accepted by CodexCliAdapter",
                "matched effort experiments must omit this arm or add explicit support",
            ),
            _declaration(
                AdapterCapability.STRUCTURED_OUTPUT,
                SupportLevel.UNSUPPORTED,
                "the adapter consumes plain stdout",
                "human-readable stdout is not a versioned result envelope",
            ),
            _declaration(
                AdapterCapability.USAGE,
                SupportLevel.PARTIAL,
                "tokens used is parsed from human-readable stdout",
                "the line can be absent or change across CLI versions",
            ),
            _declaration(
                AdapterCapability.TOOL_LIMITS,
                SupportLevel.PARTIAL,
                "workspace-write constrains filesystem access",
                "no per-tool call ceiling is enforced by this adapter",
            ),
        ),
    ),
    "opencode": ProviderAdapterContract(
        provider="opencode",
        capabilities=(
            _declaration(
                AdapterCapability.START,
                SupportLevel.SUPPORTED,
                "one-shot opencode run process invocation",
            ),
            _declaration(
                AdapterCapability.OBSERVE,
                SupportLevel.SUPPORTED,
                "recorded JSON event stream",
            ),
            _declaration(
                AdapterCapability.CANCEL,
                SupportLevel.PARTIAL,
                "timeout terminates the process; no addressable run handle",
                "ONMC cannot cancel an already-returned or externally resumed OpenCode run",
            ),
            _declaration(
                AdapterCapability.RESUME,
                SupportLevel.UNSUPPORTED,
                "the adapter does not persist or accept an OpenCode session id",
                "session resume is not wired through opencode run",
            ),
            _declaration(
                AdapterCapability.COST,
                SupportLevel.UNSUPPORTED,
                "the recorded event stream exposes usage but not cost",
                "cost must remain unknown and be excluded from matched comparisons",
            ),
            _declaration(
                AdapterCapability.MODEL_SELECTION,
                SupportLevel.SUPPORTED,
                "--model is passed to opencode run",
            ),
            _declaration(
                AdapterCapability.EFFORT,
                SupportLevel.UNSUPPORTED,
                "no effort flag is accepted by OpenCodeCliAdapter",
                "matched effort experiments must omit this arm or add explicit support",
            ),
            _declaration(
                AdapterCapability.STRUCTURED_OUTPUT,
                SupportLevel.PARTIAL,
                "--format json emits a parsed event stream",
                "unknown event layouts fall back to raw stdout",
            ),
            _declaration(
                AdapterCapability.USAGE,
                SupportLevel.PARTIAL,
                "tokens are read when a recorded event contains usage",
                "provider event streams may omit usage",
            ),
            _declaration(
                AdapterCapability.TOOL_LIMITS,
                SupportLevel.UNSUPPORTED,
                "--dir selects the project directory",
                "directory selection is not an enforced tool-call policy",
            ),
        ),
    ),
}


def contract_for(provider: str) -> ProviderAdapterContract:
    """Return a complete provider contract or reject an unknown provider."""
    if provider not in _CONTRACTS:
        raise ValueError("provider must be claude, codex, or opencode")
    return _CONTRACTS[provider]


def all_adapter_contracts() -> tuple[ProviderAdapterContract, ...]:
    """Return the conformance matrix in stable provider order."""
    return tuple(_CONTRACTS[provider] for provider in PROVIDERS)


def shared_fully_supported(
    providers: tuple[str, ...],
) -> tuple[AdapterCapability, ...]:
    """Capabilities that every comparison arm implements completely."""
    if not providers:
        raise ValueError("at least one provider is required")
    contracts = tuple(contract_for(provider) for provider in providers)
    return tuple(
        capability
        for capability in AdapterCapability
        if all(
            contract.declaration(capability).support is SupportLevel.SUPPORTED
            for contract in contracts
        )
    )


def require_comparable(
    providers: tuple[str, ...],
    capability: AdapterCapability,
) -> tuple[CapabilityDeclaration, ...]:
    """Require full support in every arm; never impute missing provider fields."""
    if not providers:
        raise ValueError("at least one provider is required")
    declarations = tuple(
        contract_for(provider).declaration(capability) for provider in providers
    )
    if all(item.support is SupportLevel.SUPPORTED for item in declarations):
        return declarations
    labels = ", ".join(
        f"{provider}={declaration.support.value}"
        for provider, declaration in zip(providers, declarations, strict=True)
    )
    raise AdapterCapabilityError(
        f"{capability.value} is not comparable across arms ({labels})",
        classification="asymmetric-adapter-capability",
        capability=capability,
        providers=providers,
    )


__all__ = [
    "PROVIDERS",
    "AdapterCapability",
    "AdapterCapabilityError",
    "CapabilityDeclaration",
    "ProviderAdapterContract",
    "ProviderName",
    "SupportLevel",
    "all_adapter_contracts",
    "contract_for",
    "require_comparable",
    "shared_fully_supported",
]
