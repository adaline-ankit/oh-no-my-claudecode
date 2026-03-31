from __future__ import annotations

import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from oh_no_my_claudecode.claude_md.updater import update_claude_md
from oh_no_my_claudecode.llm.base import BaseLLMProvider
from oh_no_my_claudecode.storage import SQLiteStorage


class _MemoryChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        *,
        repo_root: Path,
        storage: SQLiteStorage,
        provider: BaseLLMProvider | None,
        log_path: Path | None,
    ) -> None:
        self.repo_root = repo_root
        self.storage = storage
        self.provider = provider
        self.log_path = log_path
        self._last_run = 0.0

    def on_modified(self, event: object) -> None:
        path = Path(getattr(event, "src_path", ""))
        if path.name != "memory.db":
            return
        now = time.monotonic()
        if now - self._last_run < 1.0:
            return
        self._last_run = now
        update_claude_md(
            repo_root=self.repo_root,
            storage=self.storage,
            provider=self.provider,
            log_path=self.log_path,
            write=True,
        )


def watch_claude_md(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
) -> None:
    """Watch the ONMC state directory and regenerate CLAUDE.md on changes."""
    handler = _MemoryChangeHandler(
        repo_root=repo_root,
        storage=storage,
        provider=provider,
        log_path=log_path,
    )
    observer = Observer()
    observer.schedule(handler, str(repo_root / ".onmc"), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(0.5)
    finally:
        observer.stop()
        observer.join()
