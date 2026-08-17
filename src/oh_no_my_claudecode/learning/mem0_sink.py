"""M9 concrete: push ledger-approved memories into a mem0 store.

The "be the filter" position made literal: :func:`~.export_adapter.to_export_records`
decides WHAT may leave (harmful and unmeasured memories never do); this sink
decides only WHERE — mem0's platform API. Two design points that matter:

- ``infer: false`` on every write. mem0 normally runs its own LLM extraction
  over incoming text; ONMC memories were already distilled, gated, and
  measured — re-inferring them would launder our evidence into paraphrase.
  They land verbatim, evidence in ``metadata``.
- The sink accepts an :class:`~.export_adapter.ExportBatch`, not raw text —
  there is no code path that ships an unfiltered memory.

Zero new dependencies: same injectable Transport as the Supabase store.
Config: ``MEM0_API_KEY`` (platform) — self-hosted servers pass ``base_url``.
"""

from __future__ import annotations

import json
import os

from oh_no_my_claudecode.learning.export_adapter import ExportBatch
from oh_no_my_claudecode.learning.supabase_store import Transport, _urllib_transport


class Mem0Sink:
    """Ships an ExportBatch's records to mem0; refused records never travel."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://api.mem0.ai",
        transport: Transport | None = None,
    ) -> None:
        self._key = api_key or os.environ.get("MEM0_API_KEY", "")
        if not self._key:
            raise ValueError("Mem0Sink needs MEM0_API_KEY (or api_key=)")
        self._base = base_url.rstrip("/")
        self._transport: Transport = transport or _urllib_transport

    def push(self, batch: ExportBatch, *, user_id: str) -> int:
        """Write each approved record; returns the count. Raises on any failure
        (partial pushes are visible in mem0, never silently swallowed here)."""
        for record in batch.records:
            body = {
                "messages": [{"role": "user", "content": record["memory"]}],
                "user_id": user_id,
                "metadata": record["metadata"],
                "infer": False,  # ONMC already judged; store verbatim
            }
            status, text = self._transport(
                "POST",
                f"{self._base}/v1/memories/",
                {
                    "Authorization": f"Token {self._key}",
                    "Content-Type": "application/json",
                },
                json.dumps(body).encode(),
            )
            if status >= 300:
                raise RuntimeError(f"mem0 write failed ({status}): {text[:200]}")
        return len(batch.records)


__all__ = ["Mem0Sink"]
