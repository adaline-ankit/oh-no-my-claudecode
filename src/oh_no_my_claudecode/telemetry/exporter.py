"""Dependency-free OTLP/HTTP JSON trace export.

The exporter sends a standard ``ExportTraceServiceRequest`` JSON envelope.
It is opt-in, performs no background network work, and keeps authentication
headers out of representations and result objects.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

Span = dict[str, object]


@dataclass(frozen=True, slots=True)
class ExportResponse:
    """Minimal HTTP response returned by an injectable transport."""

    status_code: int
    body: bytes = b""


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Honest result of one bounded OTLP export attempt."""

    success: bool
    attempted_spans: int
    exported_spans: int
    rejected_spans: int = 0
    status_code: int | None = None
    error: str | None = None


Transport = Callable[[str, bytes, dict[str, str], float], ExportResponse]


@dataclass(slots=True)
class OtlpHttpExporter:
    """Send already-redacted span dicts through OTLP/HTTP JSON."""

    endpoint: str
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    service_name: str = "oh-no-my-claudecode"
    timeout: float = 10.0
    transport: Transport | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.endpoint = _normalize_trace_endpoint(self.endpoint)
        if not self.service_name.strip():
            raise ValueError("service_name must not be empty")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        normalized_headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
        normalized_headers["content-type"] = "application/json"
        normalized_headers.setdefault("accept", "application/json")
        self.headers = normalized_headers

    def export(self, spans: Sequence[Span]) -> ExportResult:
        """Export *spans* once; never retry or invent acceptance."""
        attempted = len(spans)
        if attempted == 0:
            return ExportResult(success=True, attempted_spans=0, exported_spans=0)
        envelope = _otlp_envelope(spans, service_name=self.service_name)
        body = json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            transport = self.transport or _http_transport
            response = transport(
                self.endpoint,
                body,
                dict(self.headers),
                self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            return ExportResult(
                success=False,
                attempted_spans=attempted,
                exported_spans=0,
                error=f"{type(exc).__name__}: export failed",
            )

        rejected = _rejected_span_count(response.body)
        accepted = max(0, attempted - rejected)
        success = 200 <= response.status_code < 300 and rejected == 0
        return ExportResult(
            success=success,
            attempted_spans=attempted,
            exported_spans=accepted if 200 <= response.status_code < 300 else 0,
            rejected_spans=rejected,
            status_code=response.status_code,
            error=None if success else "collector rejected telemetry",
        )


def _normalize_trace_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OTLP endpoint must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("OTLP endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("OTLP endpoint must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1/traces"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _otlp_envelope(
    spans: Sequence[Span],
    *,
    service_name: str,
) -> dict[str, object]:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": service_name},
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "oh_no_my_claudecode.telemetry",
                        },
                        "spans": list(spans),
                    }
                ],
            }
        ]
    }


def _rejected_span_count(body: bytes) -> int:
    if not body:
        return 0
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    partial = payload.get("partialSuccess", payload.get("partial_success"))
    if not isinstance(partial, dict):
        return 0
    value = partial.get("rejectedSpans", partial.get("rejected_spans", 0))
    if isinstance(value, bool):
        return 0
    if not isinstance(value, int | float | str | bytes | bytearray):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _http_transport(
    endpoint: str,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
) -> ExportResponse:
    request = Request(endpoint, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return ExportResponse(
                status_code=int(response.status),
                body=response.read(),
            )
    except HTTPError as exc:
        return ExportResponse(status_code=exc.code, body=exc.read())
