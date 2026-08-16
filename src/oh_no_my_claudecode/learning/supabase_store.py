"""Supabase-hosted earned-memory store — the fleet's shared knowledge base.

Implements the :class:`~.ingest.MemorySink` protocol over Supabase's PostgREST
API, so `GatedIngestor` can promote straight into the hosted plane: only
gate-promoted memories are ever written, retirement is a timestamp (evidence is
never deleted), and the measured ledger + attested receipts ride along.

Zero new dependencies: PostgREST is plain JSON over HTTP, which stdlib
``urllib`` covers. The transport is injectable so tests run fully offline.

Config: ``SUPABASE_URL`` + ``SUPABASE_KEY`` (service or anon+RLS). Schema:
``migrations/supabase/0001_earned_memory.sql``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Protocol

from oh_no_my_claudecode.learning.attribution import MemoryLift
from oh_no_my_claudecode.learning.ingest import IngestedMemory


class Transport(Protocol):
    """One HTTP call: returns (status_code, response_body_text)."""

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]: ...


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


class SupabaseEarnedMemoryStore:
    """MemorySink + ledger/receipt persistence against a Supabase project."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        self._url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self._key = key or os.environ.get("SUPABASE_KEY", "")
        if not self._url or not self._key:
            raise ValueError(
                "Supabase store needs SUPABASE_URL and SUPABASE_KEY "
                "(create a project, run migrations/supabase/0001_earned_memory.sql)"
            )
        self._transport: Transport = transport or _urllib_transport

    # -- internals ----------------------------------------------------------
    def _call(
        self, method: str, table: str, payload: object | None, query: str = ""
    ) -> tuple[int, str]:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        body = json.dumps(payload).encode() if payload is not None else None
        return self._transport(method, f"{self._url}/rest/v1/{table}{query}", headers, body)

    # -- MemorySink protocol -------------------------------------------------
    def write(self, memory: IngestedMemory) -> str:
        record = memory.to_dict()
        status, text = self._call("POST", "earned_memories", record)
        if status >= 300:
            raise RuntimeError(f"supabase write failed ({status}): {text[:200]}")
        return memory.memory_id

    def remove(self, memory_id: str) -> bool:
        # Evidence-based retirement: timestamp, never delete — the trail stays.
        status, _ = self._call(
            "PATCH",
            "earned_memories",
            {"retired_at": "now()"},
            query=f"?memory_id=eq.{memory_id}",
        )
        return status < 300

    # -- ledger + receipts ----------------------------------------------------
    def record_ledger(self, ledger: Sequence[MemoryLift]) -> int:
        rows = [
            {
                "memory_id": entry.memory_id,
                "mean_lift": entry.mean_lift,
                "ci_low": entry.ci95[0],
                "ci_high": entry.ci95[1],
                "n_tasks": entry.n_tasks,
                "verdict": entry.verdict.value,
            }
            for entry in ledger
        ]
        if not rows:
            return 0
        status, text = self._call("POST", "memory_ledger", rows)
        if status >= 300:
            raise RuntimeError(f"supabase ledger write failed ({status}): {text[:200]}")
        return len(rows)

    def record_receipt(
        self, receipt_hash: str, repo: str, verified: bool, envelope: dict[str, object]
    ) -> None:
        status, text = self._call(
            "POST",
            "receipts",
            {
                "receipt_hash": receipt_hash,
                "repo": repo,
                "verified": verified,
                "envelope": envelope,
            },
        )
        if status >= 300:
            raise RuntimeError(f"supabase receipt write failed ({status}): {text[:200]}")


__all__ = ["SupabaseEarnedMemoryStore", "Transport"]
