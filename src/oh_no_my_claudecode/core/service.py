from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.brief.compiler import compile_brief
from oh_no_my_claudecode.config import (
    compiled_dir,
    config_exists,
    create_state_dirs,
    database_path,
    default_config,
    load_config,
    state_dir,
    write_config,
)
from oh_no_my_claudecode.core.repo import discover_repo_root
from oh_no_my_claudecode.ingest.pipeline import run_ingest
from oh_no_my_claudecode.memory.catalog import MemoryCatalog
from oh_no_my_claudecode.models import (
    BriefArtifact,
    IngestResult,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now


class OnmcService:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()

    def init_project(self) -> tuple[Path, ProjectConfig]:
        repo_root = discover_repo_root(self.cwd)
        config = load_config(repo_root) if config_exists(repo_root) else default_config(repo_root)
        create_state_dirs(config, repo_root)
        write_config(config, repo_root)
        storage = SQLiteStorage(database_path(config, repo_root))
        storage.initialize()
        storage.set_meta("initialized_at", isoformat_utc(utc_now()))
        return repo_root, config

    def ingest(self) -> tuple[Path, IngestResult]:
        repo_root, config, storage = self._load_context()
        return repo_root, run_ingest(repo_root, config, storage)

    def compile_brief(self, task: str) -> tuple[Path, BriefArtifact]:
        repo_root, config, storage = self._load_context()
        artifact = compile_brief(repo_root, config, storage, task)
        output_name = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-brief.md"
        output_path = compiled_dir(config, repo_root) / output_name
        output_path.write_text(artifact.to_markdown(), encoding="utf-8")
        artifact.output_path = output_path.as_posix()
        return repo_root, artifact

    def list_memories(self, *, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).list(kind=kind)

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        _, _, storage = self._load_context()
        return MemoryCatalog(storage).get(memory_id)

    def status(self) -> dict[str, str]:
        repo_root, config, storage = self._load_context()
        meta = storage.all_meta()
        return {
            "repo_root": repo_root.as_posix(),
            "memories": str(storage.memory_count()),
            "last_ingest_at": meta.get("last_ingest_at", "never"),
            "storage_path": database_path(config, repo_root).as_posix(),
            "state_dir": state_dir(config, repo_root).as_posix(),
            "doc_globs": ", ".join(config.ingest.doc_globs),
            "max_brief_memories": str(config.brief.max_memories),
        }

    def _load_context(self) -> tuple[Path, ProjectConfig, SQLiteStorage]:
        repo_root = discover_repo_root(self.cwd)
        if not config_exists(repo_root):
            msg = "ONMC is not initialized. Run `onmc init` first."
            raise FileNotFoundError(msg)
        config = load_config(repo_root)
        create_state_dirs(config, repo_root)
        storage = SQLiteStorage(database_path(config, repo_root))
        storage.initialize()
        return repo_root, config, storage
