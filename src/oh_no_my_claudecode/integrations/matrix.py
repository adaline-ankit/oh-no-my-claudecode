"""The integration truth table: installed / configured / live, never assumed.

Each third-party ONMC composes with is probed at three honest levels:

    installed   the optional package imports (or n/a for zero-dep adapters)
    configured  the env vars/keys it needs are present
    live        an actual network probe succeeded (only with ``--probe``)

No level is inferred from another — a configured key that fails its probe
shows exactly that. The output is the answer to "are the third-party things
actually integrated?", per thing, with the missing step named.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module

from oh_no_my_claudecode.learning.supabase_store import Transport, _urllib_transport


@dataclass(frozen=True, slots=True)
class IntegrationStatus:
    name: str
    role: str
    installed: bool | None  # None = zero-dep, nothing to install
    configured: bool
    live: bool | None  # None = not probed
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "role": self.role,
            "installed": self.installed,
            "configured": self.configured,
            "live": self.live,
            "detail": self.detail,
        }


def _importable(module: str) -> bool:
    try:
        import_module(module)
    except ImportError:
        return False
    return True


def _get(url: str, headers: Mapping[str, str], transport: Transport) -> tuple[int, str]:
    try:
        return transport("GET", url, dict(headers), None)
    except OSError as error:
        return 0, str(error)


def collect_matrix(
    *,
    probe: bool = False,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> list[IntegrationStatus]:
    """Build the matrix. Probes only when asked; failures are data, not raises."""
    environ = os.environ if env is None else env
    send: Transport = transport or _urllib_transport
    rows: list[IntegrationStatus] = []

    def probe_status(
        url: str, headers: Mapping[str, str], ok: Callable[[int], bool]
    ) -> tuple[bool | None, str]:
        if not probe:
            return None, "not probed (--probe)"
        status, body = _get(url, headers, send)
        return ok(status), f"HTTP {status}" if status else f"unreachable: {body[:60]}"

    # -- memory ---------------------------------------------------------------
    mem0_key = environ.get("MEM0_API_KEY", "")
    live, detail = (
        probe_status(
            "https://api.mem0.ai/v1/memories/?user_id=onmc-probe",
            {"Authorization": f"Token {mem0_key}"},
            lambda s: s < 400,
        )
        if mem0_key
        else (None, "set MEM0_API_KEY (free tier: app.mem0.ai)")
    )
    rows.append(
        IntegrationStatus(
            "mem0", "memory store behind the export filter", None, bool(mem0_key), live, detail
        )
    )

    supa_url = environ.get("SUPABASE_URL", "")
    supa_key = environ.get("SUPABASE_KEY", "")
    live, detail = (
        probe_status(
            f"{supa_url.rstrip('/')}/rest/v1/earned_memories?select=memory_id&limit=1",
            {"apikey": supa_key, "Authorization": f"Bearer {supa_key}"},
            lambda s: s < 400,
        )
        if supa_url and supa_key
        else (None, "set SUPABASE_URL + SUPABASE_KEY, apply migrations/supabase/0001")
    )
    rows.append(
        IntegrationStatus(
            "supabase",
            "hosted knowledge base (pgvector, RLS)",
            None,
            bool(supa_url and supa_key),
            live,
            detail,
        )
    )

    rows.append(
        IntegrationStatus(
            "sqlite-vec",
            "local vector recall",
            _importable("sqlite_vec"),
            True,
            None,
            "local extension; exercised by the recall tests",
        )
    )

    # -- observability ----------------------------------------------------------
    otlp = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    live, detail = (
        probe_status(f"{otlp}/v1/traces", {}, lambda s: s in (200, 400, 405, 415))
        if otlp
        else (None, "set OTEL_EXPORTER_OTLP_ENDPOINT (see docs/observability.md)")
    )
    rows.append(
        IntegrationStatus(
            "otlp-backend",
            "langfuse/jaeger/phoenix/grafana via `onmc observe`",
            None,
            bool(otlp),
            live,
            detail,
        )
    )
    rows.append(
        IntegrationStatus(
            "otlp-protobuf",
            "fallback for JSON-rejecting receivers (phoenix)",
            _importable("opentelemetry.proto"),
            True,
            None,
            "extra: pip install 'oh-no-my-claudecode[observe]'",
        )
    )

    # -- harness / evals ----------------------------------------------------------
    rows.append(
        IntegrationStatus(
            "langgraph",
            "optional harness execution backend",
            _importable("langgraph"),
            True,
            None,
            "extra backend; inert when absent",
        )
    )
    rows.append(
        IntegrationStatus(
            "sigstore",
            "keyless receipt signing (rekor)",
            _importable("sigstore"),
            True,
            None,
            "extra: pip install 'oh-no-my-claudecode[attest]'; signing needs OIDC",
        )
    )
    e2b = environ.get("E2B_API_KEY", "")
    rows.append(
        IntegrationStatus(
            "e2b",
            "hosted sandbox for benchmark runs",
            None,
            bool(e2b),
            None,
            "set E2B_API_KEY" if not e2b else "configured",
        )
    )
    rows.append(
        IntegrationStatus(
            "harbor-format",
            "repo-bench tasks in terminal-bench-2 layout",
            None,
            True,
            None,
            "exporter: evals/ab/harbor_export.py (offline)",
        )
    )
    return rows


__all__ = ["IntegrationStatus", "collect_matrix"]
