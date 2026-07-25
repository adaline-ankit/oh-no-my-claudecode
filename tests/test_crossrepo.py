"""Tests for the ``crossrepo`` feature — cross-repo impact map + federated recall.

All tests are pure functions over constructed ``tmp_path`` inputs: fake sibling
repos with overlapping top-level package names and minimal ``.agent-memory/``
exports built to the real schema. No network, no LLM, no git.

Covers:
- scan_repos finds modules shared across ≥2 repos as impacts
- non-shared modules are excluded from impacts
- a non-repo path is skipped with a note (graceful)
- scan is deterministic (sorted repos, impacts, repo lists)
- federated_recall attributes hits to the right repo
- recall ranks query matches by token overlap (title weighted highest)
- recall is graceful when a repo has no export / empty query
- recall labels cross-repo provenance and origin-repo quarantine (never filters)
- CLI: scan and recall smoke via CliRunner, incl. --json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.crossrepo import commands as crossrepo_commands
from oh_no_my_claudecode.crossrepo.commands import _render_recall_plain
from oh_no_my_claudecode.crossrepo.crossrepo import (
    CROSSREPO_PROVENANCE_NOTE,
    PROVENANCE_CROSS_REPO,
    PROVENANCE_UNPROMOTED,
    RecallHit,
    federated_recall,
    scan_repos,
)
from oh_no_my_claudecode.hooks.prompt_recall import unpromoted_source_ref
from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.models.memory import MemoryKind, SourceType
from oh_no_my_claudecode.sync.schema import ExportCounts, SyncManifest

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_repo(root: Path, *, modules: list[str], layout: str = "src") -> Path:
    """Create a fake repo at *root* with the given top-level *modules*.

    ``layout="src"`` places packages under ``src/``; ``layout="flat"`` places
    them at the repo root. A ``pyproject.toml`` marker is always written so the
    directory is recognised as a repo even in flat layout.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    base = root / "src" if layout == "src" else root
    base.mkdir(parents=True, exist_ok=True)
    for module in modules:
        pkg = base / module
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    return root


def _write_export(
    root: Path,
    memories: list[MemoryEntry],
    *,
    unpromoted_ids: set[str] | None = None,
) -> None:
    """Write a minimal valid ``.agent-memory/`` export into *root*.

    Mirrors the real exporter layout: ``manifest.json`` at the export root and
    one ``memories/<kind>/<id>.json`` payload per memory.

    ``unpromoted_ids`` sets the explicit ``unpromoted`` record flag on the named
    memories, the way the real exporter does for quarantined entries.
    """
    flagged = unpromoted_ids or set()
    agent_mem = root / ".agent-memory"
    agent_mem.mkdir(parents=True, exist_ok=True)
    manifest = SyncManifest(
        repo_root=root.as_posix(),
        exported_at=datetime(2024, 1, 1, tzinfo=UTC),
        onmc_version="0.0.0-test",
        counts=ExportCounts(memories=len(memories), tasks=0, attempts=0, artifacts=0),
    )
    (agent_mem / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    for memory in memories:
        target = agent_mem / "memories" / memory.kind.value / f"{memory.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "memory": memory.model_dump(mode="json"),
                    "unpromoted": memory.id in flagged,
                }
            ),
            encoding="utf-8",
        )


def _make_memory(
    mem_id: str,
    title: str,
    summary: str,
    tags: list[str],
    *,
    source_ref: str = "docs/x.md",
) -> MemoryEntry:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return MemoryEntry(
        id=mem_id,
        kind=MemoryKind.INVARIANT,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.DOC,
        source_ref=source_ref,
        tags=tags,
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# scan_repos
# ---------------------------------------------------------------------------


def test_scan_finds_shared_modules_as_impacts(tmp_path: Path) -> None:
    _make_repo(tmp_path / "alpha", modules=["auth", "billing", "alpha_only"])
    _make_repo(tmp_path / "beta", modules=["auth", "billing", "beta_only"])
    _make_repo(tmp_path / "gamma", modules=["auth", "gamma_only"])

    result = scan_repos([tmp_path / "alpha", tmp_path / "beta", tmp_path / "gamma"])

    impacts = {i.shared_module: i.repos for i in result.impacts}
    # auth appears in all three, billing in two → both are ripple surfaces.
    assert impacts["auth"] == ["alpha", "beta", "gamma"]
    assert impacts["billing"] == ["alpha", "beta"]


def test_scan_excludes_non_shared_modules(tmp_path: Path) -> None:
    _make_repo(tmp_path / "alpha", modules=["auth", "alpha_only"])
    _make_repo(tmp_path / "beta", modules=["auth", "beta_only"])

    result = scan_repos([tmp_path / "alpha", tmp_path / "beta"])

    shared = {i.shared_module for i in result.impacts}
    assert "auth" in shared
    assert "alpha_only" not in shared
    assert "beta_only" not in shared


def test_scan_skips_non_repo_path(tmp_path: Path) -> None:
    _make_repo(tmp_path / "alpha", modules=["auth"])
    not_a_repo = tmp_path / "just_a_dir"
    not_a_repo.mkdir()
    missing = tmp_path / "does_not_exist"

    result = scan_repos([tmp_path / "alpha", not_a_repo, missing])

    assert [r.name for r in result.repos] == ["alpha"]
    skipped_reasons = dict(result.skipped)
    assert not_a_repo.resolve().as_posix() not in [r.path for r in result.repos]
    # Both bad paths recorded, neither raised.
    assert any("not a repo" in reason for reason in skipped_reasons.values())
    assert any("does not exist" in reason for reason in skipped_reasons.values())


def test_scan_flat_layout_and_determinism(tmp_path: Path) -> None:
    _make_repo(tmp_path / "flatrepo", modules=["shared", "flatx"], layout="flat")
    _make_repo(tmp_path / "srcrepo", modules=["shared", "srcx"], layout="src")

    first = scan_repos([tmp_path / "srcrepo", tmp_path / "flatrepo"])
    second = scan_repos([tmp_path / "flatrepo", tmp_path / "srcrepo"])

    # Order-independent + deterministic: sorted by repo name regardless of input order.
    assert [r.name for r in first.repos] == [r.name for r in second.repos] == [
        "flatrepo",
        "srcrepo",
    ]
    assert [i.shared_module for i in first.impacts] == ["shared"]
    assert first.impacts[0].repos == ["flatrepo", "srcrepo"]


def test_scan_empty_input() -> None:
    result = scan_repos([])
    assert result.repos == []
    assert result.impacts == []


# ---------------------------------------------------------------------------
# federated_recall
# ---------------------------------------------------------------------------


def test_recall_attributes_hits_to_right_repo(tmp_path: Path) -> None:
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    beta = _make_repo(tmp_path / "beta", modules=["auth"])
    _write_export(
        alpha,
        [_make_memory("m-a1", "Auth token rotation", "how alpha rotates auth tokens", ["auth"])],
    )
    _write_export(
        beta,
        [_make_memory("m-b1", "Billing retries", "beta billing retry policy", ["billing"])],
    )

    hits = federated_recall([alpha, beta], "auth token")

    assert len(hits) == 1
    assert hits[0].repo == "alpha"
    assert hits[0].memory_id == "m-a1"


def test_recall_ranks_by_token_overlap(tmp_path: Path) -> None:
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [
            # Query word in the TITLE → weighted highest.
            _make_memory("m-title", "cache invalidation", "unrelated body text", []),
            # Query word only in the SUMMARY → lower score.
            _make_memory("m-summary", "unrelated heading", "note about cache behaviour", []),
        ],
    )

    hits = federated_recall([alpha], "cache")

    assert [h.memory_id for h in hits] == ["m-title", "m-summary"]
    assert hits[0].score > hits[1].score


def test_recall_graceful_no_export(tmp_path: Path) -> None:
    # Repo exists but has no .agent-memory export.
    no_export = _make_repo(tmp_path / "noexport", modules=["auth"])
    with_export = _make_repo(tmp_path / "hasexport", modules=["auth"])
    _write_export(
        with_export,
        [_make_memory("m-1", "auth flow", "auth login flow", ["auth"])],
    )

    hits = federated_recall([no_export, with_export], "auth")

    assert [h.repo for h in hits] == ["hasexport"]


def test_recall_empty_query(tmp_path: Path) -> None:
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(alpha, [_make_memory("m-1", "auth flow", "auth login", ["auth"])])
    assert federated_recall([alpha], "") == []


def test_recall_no_match(tmp_path: Path) -> None:
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(alpha, [_make_memory("m-1", "auth flow", "auth login", ["auth"])])
    assert federated_recall([alpha], "kubernetes helm chart") == []


# ---------------------------------------------------------------------------
# Provenance labelling (cross-repo trust boundary)
# ---------------------------------------------------------------------------


def test_recall_labels_ordinary_hit_as_unreviewed_cross_repo(tmp_path: Path) -> None:
    """A hit the origin repo never quarantined is still unreviewed *here*."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(alpha, [_make_memory("m-1", "auth flow", "auth login flow", ["auth"])])

    hits = federated_recall([alpha], "auth")

    assert len(hits) == 1
    assert hits[0].unpromoted is False
    assert hits[0].provenance == PROVENANCE_CROSS_REPO
    assert hits[0].to_dict()["provenance"] == PROVENANCE_CROSS_REPO


def test_recall_flags_origin_quarantine_from_source_ref_prefix(tmp_path: Path) -> None:
    """The reserved ``unpromoted:`` source_ref prefix marks the hit."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [
            _make_memory(
                "m-quarantined",
                "auth flow",
                "auth login flow",
                ["auth"],
                source_ref=unpromoted_source_ref("autopilot:plan"),
            )
        ],
    )

    hits = federated_recall([alpha], "auth")

    assert [h.memory_id for h in hits] == ["m-quarantined"]
    assert hits[0].unpromoted is True
    assert hits[0].provenance == PROVENANCE_UNPROMOTED


def test_recall_flags_origin_quarantine_from_record_flag(tmp_path: Path) -> None:
    """The explicit ``unpromoted`` record flag marks the hit on its own."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [_make_memory("m-flagged", "auth flow", "auth login flow", ["auth"])],
        unpromoted_ids={"m-flagged"},
    )

    hits = federated_recall([alpha], "auth")

    assert hits[0].unpromoted is True
    assert hits[0].provenance == PROVENANCE_UNPROMOTED


def test_recall_false_flag_cannot_launder_prefixed_source_ref(tmp_path: Path) -> None:
    """``"unpromoted": false`` must not clear an already-prefixed source_ref."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    # unpromoted_ids omitted → the record is written with "unpromoted": false
    # while the source_ref still carries the reserved prefix.  Union wins.
    _write_export(
        alpha,
        [
            _make_memory(
                "m-launder",
                "auth flow",
                "auth login flow",
                ["auth"],
                source_ref=unpromoted_source_ref("docs/x.md"),
            )
        ],
    )

    hits = federated_recall([alpha], "auth")

    assert hits[0].unpromoted is True


def test_recall_labels_rather_than_filters_quarantined_hits(tmp_path: Path) -> None:
    """Cross-repo recall stays a feature: a quarantined hit is shown, not dropped."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [
            _make_memory("m-clean", "auth rotation", "rotate auth tokens", ["auth"]),
            _make_memory(
                "m-dirty",
                "auth rotation",
                "rotate auth tokens",
                ["auth"],
                source_ref=unpromoted_source_ref("autopilot:learn"),
            ),
        ],
    )

    hits = federated_recall([alpha], "auth rotation")

    assert {h.memory_id for h in hits} == {"m-clean", "m-dirty"}
    assert {h.memory_id: h.unpromoted for h in hits} == {"m-clean": False, "m-dirty": True}


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_scan_json(tmp_path: Path) -> None:
    _make_repo(tmp_path / "alpha", modules=["auth", "alpha_only"])
    _make_repo(tmp_path / "beta", modules=["auth", "beta_only"])

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["crossrepo", "scan", str(tmp_path / "alpha"), str(tmp_path / "beta"), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    shared = {i["shared_module"] for i in payload["impacts"]}
    assert shared == {"auth"}


def test_cli_recall_json(tmp_path: Path) -> None:
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [_make_memory("m-a1", "Auth token rotation", "rotate auth tokens", ["auth"])],
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["crossrepo", "recall", "auth token", "--repo", str(alpha), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["repo"] == "alpha"
    assert payload[0]["memory_id"] == "m-a1"


def test_cli_recall_json_carries_provenance(tmp_path: Path) -> None:
    """A ``--json`` consumer never sees the banner, so provenance rides per-hit."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [
            _make_memory(
                "m-a1",
                "Auth token rotation",
                "rotate auth tokens",
                ["auth"],
                source_ref=unpromoted_source_ref("autopilot:learn"),
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["crossrepo", "recall", "auth token", "--repo", str(alpha), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["unpromoted"] is True
    assert payload[0]["provenance"] == PROVENANCE_UNPROMOTED


def test_cli_recall_renders_unreviewed_banner_and_marker(tmp_path: Path) -> None:
    """Rendered output states the trust boundary and marks quarantined hits."""
    alpha = _make_repo(tmp_path / "alpha", modules=["auth"])
    _write_export(
        alpha,
        [
            _make_memory("m-clean", "Auth token rotation", "rotate auth tokens", ["auth"]),
            _make_memory(
                "m-dirty",
                "Auth token cache",
                "cache auth tokens",
                ["auth"],
                source_ref=unpromoted_source_ref("autopilot:learn"),
            ),
        ],
    )

    runner = CliRunner()
    result = runner.invoke(app, ["crossrepo", "recall", "auth token", "--repo", str(alpha)])

    assert result.exit_code == 0, result.output
    # Both hits are still presented — labelling, not filtering.
    assert "rotation" in result.output
    assert "cache" in result.output
    # Standing trust-boundary note for the whole result set.  Asserted on single
    # words because Rich hard-wraps the caption at the terminal width.
    assert "unreviewed" in result.output
    assert "cross-repo" in result.output
    # Per-hit marker, on exactly the one hit quarantined in its origin repo.
    # "unpromoted" appears nowhere else in the rendered output.
    assert result.output.count("unpromoted") == 1


def test_plain_renderer_carries_banner_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-Rich fallback renderer must not lose the provenance labels.

    ``typer.echo`` is captured directly rather than via ``capsys`` because this
    project runs pytest with ``-p no:capture``.
    """
    hits = [
        RecallHit(
            repo="alpha",
            memory_id="m-clean",
            title="Auth token rotation",
            summary="rotate auth tokens",
            tags=["auth"],
            score=10,
        ),
        RecallHit(
            repo="beta",
            memory_id="m-dirty",
            title="Auth token cache",
            summary="cache auth tokens",
            tags=["auth"],
            score=5,
            unpromoted=True,
        ),
    ]

    captured: list[str] = []
    monkeypatch.setattr(
        crossrepo_commands.typer, "echo", lambda message, **_: captured.append(str(message))
    )
    _render_recall_plain(hits, "auth token")
    out = "\n".join(captured)

    assert CROSSREPO_PROVENANCE_NOTE in out
    assert "Auth token rotation" in out
    assert "⚠ unpromoted in origin repo — Auth token cache" in out
    # The clean hit is not mislabelled as quarantined.
    assert "⚠ unpromoted in origin repo — Auth token rotation" not in out


def test_cli_recall_no_repos_errors() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["crossrepo", "recall", "auth"])
    assert result.exit_code == 1
