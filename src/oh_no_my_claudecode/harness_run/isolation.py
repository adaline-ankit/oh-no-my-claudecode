"""Declared isolation and capability boundary for one harness run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IsolationProfile:
    """Honest pre-execution boundary declaration embedded in runtime contracts."""

    requested: bool
    mode: str
    filesystem: str
    process: str
    network: str
    secrets: str
    cleanup: str
    limitations: tuple[str, ...]
    schema_version: str = "1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "requested": self.requested,
            "mode": self.mode,
            "filesystem": self.filesystem,
            "process": self.process,
            "network": self.network,
            "secrets": self.secrets,
            "cleanup": self.cleanup,
            "limitations": list(self.limitations),
        }


def isolation_profile(*, requested: bool) -> IsolationProfile:
    """Return the declared isolation profile for a harness request."""
    if requested:
        return IsolationProfile(
            requested=True,
            mode="git_worktree_required",
            filesystem="agent and verifier run from an isolated git worktree",
            process="not isolated by ONMC; subprocesses execute on the host",
            network="not constrained by ONMC",
            secrets="ambient environment and local agent credentials remain visible",
            cleanup="failed runs remove the worktree; verified runs preserve it for review",
            limitations=(
                "This is repository change isolation, not a container or microVM.",
                "Network, process, kernel, and secret boundaries require a "
                "Harbor/Docker/cloud sandbox.",
                "ONMC refuses in-place execution when requested worktree setup fails.",
            ),
        )
    return IsolationProfile(
        requested=False,
        mode="in_place",
        filesystem="agent and verifier run in the caller's working tree",
        process="not isolated by ONMC; subprocesses execute on the host",
        network="not constrained by ONMC",
        secrets="ambient environment and local agent credentials remain visible",
        cleanup="no isolation cleanup; caller owns working-tree changes",
        limitations=(
            "No ONMC isolation boundary was requested for this run.",
            "Use --isolate for worktree change isolation.",
            "Use a container or Harbor-backed runner for process, network, and secret isolation.",
        ),
    )


__all__ = ["IsolationProfile", "isolation_profile"]
