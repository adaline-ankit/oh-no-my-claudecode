"""FTS5 full-text search over onmc's persisted history.

``onmc session-search <query>`` does fast full-text search across onmc's
entire stored text corpus (memories, attempts, tasks, memory_artifacts) using
SQLite's FTS5 engine.  Falls back to LIKE-based scanning when FTS5 is absent.
Raw retrieval — no LLM.
"""

from __future__ import annotations

from oh_no_my_claudecode.sessionsearch.index import Hit, search

__all__ = ["Hit", "search"]
