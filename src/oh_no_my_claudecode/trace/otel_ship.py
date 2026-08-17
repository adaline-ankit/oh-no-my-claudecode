"""Ship ONMC's OTLP spans to any OTel backend — Langfuse, Phoenix, Grafana.

`otel.py` and `otel_ledger.py` already emit OTLP-JSON; this is the missing
last mile: POST them to a collector so ONMC's verdicts, per-memory lift, and
enforcement decisions render inside the observability UI a team already uses,
instead of only in ONMC's own surfaces.

Configuration is the OpenTelemetry STANDARD environment contract — no ONMC
invention, so any backend's own docs apply verbatim:

    OTEL_EXPORTER_OTLP_ENDPOINT   e.g. https://cloud.langfuse.com/api/public/otel
    OTEL_EXPORTER_OTLP_HEADERS    e.g. Authorization=Basic <base64(pk:sk)>

Zero new dependencies (same injectable Transport as the other adapters).
See docs/observability.md for per-backend setup.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.learning.supabase_store import Transport, _urllib_transport
from oh_no_my_claudecode.ledger.accounting import load_receipts
from oh_no_my_claudecode.trace.otel_ledger import to_otlp, verdict_span


def resolve_otlp_config(env: Mapping[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Read the standard OTel env contract. Empty endpoint = not configured."""
    environ = os.environ if env is None else env
    endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    headers: dict[str, str] = {}
    for pair in environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").split(","):
        if "=" in pair:
            key, _, value = pair.partition("=")
            headers[key.strip()] = value.strip()
    return endpoint, headers


def ship_payload(
    payload: dict[str, Any],
    *,
    endpoint: str,
    headers: Mapping[str, str],
    transport: Transport | None = None,
) -> tuple[int, str]:
    """POST one OTLP payload to ``{endpoint}/v1/traces``. Loud on failure.

    Sends JSON first; if the receiver rejects the content type (415 — e.g.
    Phoenix is protobuf-only), transparently retries as protobuf when the
    ``observe`` extra is installed, and raises with the install hint when not.
    """
    if not endpoint:
        raise ValueError(
            "no OTLP endpoint configured — set OTEL_EXPORTER_OTLP_ENDPOINT "
            "(see docs/observability.md)"
        )
    send: Transport = transport or _urllib_transport
    url = f"{endpoint}/v1/traces"
    status, body = send(
        "POST",
        url,
        {**dict(headers), "Content-Type": "application/json"},
        json.dumps(payload).encode(),
    )
    if status == 415:
        from oh_no_my_claudecode.trace.otel_pb import encode_protobuf

        status, body = send(
            "POST",
            url,
            {**dict(headers), "Content-Type": "application/x-protobuf"},
            encode_protobuf(payload),
        )
    if status >= 300:
        raise RuntimeError(f"otlp ship failed ({status}): {body[:200]}")
    return status, body


def ship_receipts(
    repo_root: Path,
    *,
    endpoint: str | None = None,
    headers: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    scope: str = "project",
) -> int:
    """Export this repo's run receipts as verdict spans and ship them.

    Returns the span count (0 = nothing to ship, nothing sent). Endpoint and
    headers default to the standard OTel env vars.
    """
    env_endpoint, env_headers = resolve_otlp_config()
    receipts = load_receipts(repo_root, scope=scope)
    when_ns = time.time_ns()
    spans = [verdict_span(receipt, when_ns=when_ns) for receipt in receipts]
    if not spans:
        return 0
    ship_payload(
        to_otlp(spans),
        endpoint=endpoint if endpoint is not None else env_endpoint,
        headers=headers if headers is not None else env_headers,
        transport=transport,
    )
    return len(spans)


__all__ = ["resolve_otlp_config", "ship_payload", "ship_receipts"]
