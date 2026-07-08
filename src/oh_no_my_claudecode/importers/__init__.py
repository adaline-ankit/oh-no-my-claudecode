"""Importers for ``onmc import``: pull skills/memories from external tool formats.

Sources supported
-----------------
``omc``
    oh-my-claudecode skill files (``.omc/skills/*.md``).  Imported as
    :class:`~oh_no_my_claudecode.models.Skill` objects tagged ``imported:omc``.

``hermes``
    Nous hermes-agent context files (``MEMORY.md``, ``USER.md``).  Imported as
    :class:`~oh_no_my_claudecode.models.MemoryEntry` records tagged ``imported:hermes``.

``langchain``
    LangChain document loaders (PDFs, web pages, notebooks, directories).
    Imported as :class:`~oh_no_my_claudecode.models.MemoryEntry` records tagged
    ``imported:langchain``.  Requires the ``langchain`` optional extra; reports
    unavailable gracefully when absent.

``<path>``
    Generic ``.md`` file or directory.  Imported as skills (default) or memories
    (``as_kind="memory"``), tagged ``imported:md``.

Public API
----------
:func:`run_import` — top-level orchestrator used by the CLI and the service layer.
:class:`ImportResult` — result dataclass returned by :func:`run_import`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oh_no_my_claudecode.importers.base import ImportResult
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

from . import hermes as _hermes
from . import langchain_loader as _langchain
from . import markdown as _markdown
from . import omc as _omc

__all__ = ["ImportResult", "run_import"]


def run_import(
    storage: SQLiteStorage,
    source: str,
    path: Path | None = None,
    *,
    dry_run: bool = False,
    as_kind: str = "skill",
    cwd: Path | None = None,
    loader: Any = None,
    splitter: Any = None,
) -> ImportResult:
    """Import external tool knowledge into *storage*.

    Parameters
    ----------
    storage:
        Initialised :class:`~oh_no_my_claudecode.storage.sqlite.SQLiteStorage` instance.
    source:
        Source selector: ``"omc"``, ``"hermes"``, ``"langchain"``, or a
        filesystem path string.
    path:
        Optional explicit path override.  When *None* the importer auto-detects
        default locations.
    dry_run:
        When *True*, parse and report without writing anything to the store.
    as_kind:
        ``"skill"`` or ``"memory"`` — controls how generic markdown paths are
        imported.  For ``omc`` this is always ``"skill"``; for ``hermes`` and
        ``langchain`` always ``"memory"``.
    cwd:
        Working directory override (defaults to :func:`Path.cwd`).
    loader:
        LangChain document loader instance.  Required when *source* is
        ``"langchain"``; ignored for all other sources.
    splitter:
        LangChain text splitter instance.  Optional when *source* is
        ``"langchain"``; defaults to ``RecursiveCharacterTextSplitter``.

    Returns
    -------
    ImportResult
        Summary: source, as_kind, imported, skipped, dry_run, items (names/titles).

    Raises
    ------
    FileNotFoundError
        When no importable content is found at the expected location(s).
    ValueError
        When *as_kind* is not ``"skill"`` or ``"memory"``, or when
        *source* is ``"langchain"`` but the extra is unavailable.
    """
    if as_kind not in ("skill", "memory"):
        msg = f"as_kind must be 'skill' or 'memory', got: {as_kind!r}"
        raise ValueError(msg)

    base_cwd = cwd or Path.cwd()

    if source == "omc":
        return _run_omc_import(storage, path, dry_run=dry_run, cwd=base_cwd)

    if source == "hermes":
        return _run_hermes_import(storage, path, dry_run=dry_run, cwd=base_cwd)

    if source == "langchain":
        return _run_langchain_import(
            storage,
            loader=loader,
            splitter=splitter,
            dry_run=dry_run,
        )

    # Generic markdown path: source IS the path string.
    md_path = path if path is not None else Path(source)
    return _run_markdown_import(storage, md_path, dry_run=dry_run, as_kind=as_kind)


# ── Private orchestrators ──────────────────────────────────────────────────────


def _run_omc_import(
    storage: SQLiteStorage,
    path: Path | None,
    *,
    dry_run: bool,
    cwd: Path,
) -> ImportResult:
    dirs = _omc.resolve_omc_dirs(path, cwd=cwd)
    skills = _omc.parse(dirs)

    imported = 0
    skipped = 0
    item_names: list[str] = []

    for skill in skills:
        item_names.append(skill.name)
        if dry_run:
            continue
        existing = storage.get_skill(skill.id)
        if existing is not None:
            skipped += 1
        else:
            storage.add_skill(skill)
            imported += 1

    if dry_run:
        return ImportResult(
            source="omc",
            as_kind="skill",
            imported=0,
            skipped=0,
            dry_run=True,
            items=item_names,
        )

    return ImportResult(
        source="omc",
        as_kind="skill",
        imported=imported,
        skipped=skipped,
        dry_run=False,
        items=item_names,
    )


def _run_hermes_import(
    storage: SQLiteStorage,
    path: Path | None,
    *,
    dry_run: bool,
    cwd: Path,
) -> ImportResult:
    files = _hermes.resolve_hermes_files(path, cwd=cwd)
    memories = _hermes.parse(files)

    imported = 0
    skipped = 0
    item_names: list[str] = []

    for memory in memories:
        item_names.append(memory.title)
        if dry_run:
            continue
        existing = storage.get_memory(memory.id)
        if existing is not None:
            skipped += 1
        else:
            storage.upsert_memories([memory])
            imported += 1

    if dry_run:
        return ImportResult(
            source="hermes",
            as_kind="memory",
            imported=0,
            skipped=0,
            dry_run=True,
            items=item_names,
        )

    return ImportResult(
        source="hermes",
        as_kind="memory",
        imported=imported,
        skipped=skipped,
        dry_run=False,
        items=item_names,
    )


def _run_langchain_import(
    storage: SQLiteStorage,
    *,
    loader: Any,
    splitter: Any,
    dry_run: bool,
) -> ImportResult:
    if not _langchain.available():
        msg = (
            "The 'langchain' extra is required for source='langchain'. "
            "Install it with: pip install 'oh-no-my-claudecode[langchain]'"
        )
        raise ValueError(msg)

    if loader is None:
        msg = "A 'loader' must be provided when source='langchain'."
        raise ValueError(msg)

    source_ref = getattr(loader, "file_path", None) or "langchain"
    if not isinstance(source_ref, str):
        source_ref = str(source_ref)

    memories = _langchain.parse_with_loader(loader, splitter=splitter, source_ref=source_ref)

    imported = 0
    skipped = 0
    item_names: list[str] = []

    for memory in memories:
        item_names.append(memory.title)
        if dry_run:
            continue
        existing = storage.get_memory(memory.id)
        if existing is not None:
            skipped += 1
        else:
            storage.upsert_memories([memory])
            imported += 1

    if dry_run:
        return ImportResult(
            source="langchain",
            as_kind="memory",
            imported=0,
            skipped=0,
            dry_run=True,
            items=item_names,
        )

    return ImportResult(
        source="langchain",
        as_kind="memory",
        imported=imported,
        skipped=skipped,
        dry_run=False,
        items=item_names,
    )


def _run_markdown_import(
    storage: SQLiteStorage,
    path: Path,
    *,
    dry_run: bool,
    as_kind: str,
) -> ImportResult:
    files = _markdown.resolve_md_paths(path)
    item_names: list[str] = []
    imported = 0
    skipped = 0

    if as_kind == "skill":
        skills = _markdown.parse_as_skills(files)
        for skill in skills:
            item_names.append(skill.name)
            if dry_run:
                continue
            if storage.get_skill(skill.id) is not None:
                skipped += 1
            else:
                storage.add_skill(skill)
                imported += 1
    else:
        memories = _markdown.parse_as_memories(files)
        for memory in memories:
            item_names.append(memory.title)
            if dry_run:
                continue
            if storage.get_memory(memory.id) is not None:
                skipped += 1
            else:
                storage.upsert_memories([memory])
                imported += 1

    if dry_run:
        return ImportResult(
            source=str(path),
            as_kind=as_kind,
            imported=0,
            skipped=0,
            dry_run=True,
            items=item_names,
        )

    return ImportResult(
        source=str(path),
        as_kind=as_kind,
        imported=imported,
        skipped=skipped,
        dry_run=False,
        items=item_names,
    )
