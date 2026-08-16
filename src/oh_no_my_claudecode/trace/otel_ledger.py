"""OTLP export for the verification layer — receipts, ledger, enforcement.

`trace/otel.py` already speaks the GenAI semantic conventions for model/tool
spans. This module exports what no other producer has: the *judgment* events —
run verdicts (receipts), per-memory measured lift (attribution ledger), and
reference-monitor decisions — as plain OTLP JSON dicts.

Why: every eval/observability platform (Phoenix, Braintrust, Langfuse, Arize)
ingests OTel. Emitting standards means ONMC's verdicts render inside the
dashboards teams already pay for — their UI, our judgment. No SDK dependency,
same as the sibling module.

Span kinds emitted (attribute ``onmc.kind``):
- ``verdict``      — one per receipt: verified?, status, policy outcome
- ``attribution``  — one per ledger entry: measured lift, CI, verdict
- ``enforcement``  — one per monitor decision: effect, outcome, blocked?
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from oh_no_my_claudecode.learning.attribution import MemoryLift

_SCOPE = {"name": "onmc.ledger", "version": "1"}


def _attr(key: str, value: object) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _ids(seed: str) -> tuple[str, str]:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return digest[:32], digest[32:48]  # traceId (16 bytes), spanId (8 bytes)


def _span(name: str, seed: str, when_ns: int, attributes: list[dict[str, Any]]) -> dict[str, Any]:
    trace_id, span_id = _ids(seed)
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,  # SPAN_KIND_INTERNAL
        "startTimeUnixNano": str(when_ns),
        "endTimeUnixNano": str(when_ns),
        "attributes": attributes,
    }


def verdict_span(receipt: Mapping[str, object], *, when_ns: int) -> dict[str, Any]:
    """One span per run receipt — the verdict, not the chatter."""
    receipt_hash = str(receipt.get("receipt_hash", ""))
    verified = bool(receipt.get("verified", False))
    attributes = [
        _attr("onmc.kind", "verdict"),
        _attr("onmc.receipt.hash", receipt_hash),
        _attr("onmc.verified", verified),
        _attr("onmc.status", receipt.get("status", "")),
    ]
    policy = receipt.get("policy")
    if isinstance(policy, Mapping):
        attributes.append(_attr("onmc.policy.outcome", policy.get("outcome", "")))
    return _span("onmc.verdict", f"verdict:{receipt_hash}", when_ns, attributes)


def attribution_spans(ledger: Sequence[MemoryLift], *, when_ns: int) -> list[dict[str, Any]]:
    """One span per measured artifact: the memory/skill P&L, dashboard-ready."""
    spans: list[dict[str, Any]] = []
    for entry in ledger:
        spans.append(
            _span(
                "onmc.attribution",
                f"attribution:{entry.memory_id}:{when_ns}",
                when_ns,
                [
                    _attr("onmc.kind", "attribution"),
                    _attr("onmc.artifact.id", entry.memory_id),
                    _attr("onmc.lift.mean", entry.mean_lift),
                    _attr("onmc.lift.ci_low", entry.ci95[0]),
                    _attr("onmc.lift.ci_high", entry.ci95[1]),
                    _attr("onmc.lift.n_tasks", entry.n_tasks),
                    _attr("onmc.lift.verdict", entry.verdict.value),
                ],
            )
        )
    return spans


def enforcement_spans(
    decisions: Sequence[Mapping[str, object]], *, when_ns: int
) -> list[dict[str, Any]]:
    """One span per reference-monitor decision (HarnessResult.enforcement_trace)."""
    spans: list[dict[str, Any]] = []
    for index, decision in enumerate(decisions):
        spans.append(
            _span(
                "onmc.enforcement",
                f"enforce:{index}:{decision.get('resource', '')}:{when_ns}",
                when_ns,
                [
                    _attr("onmc.kind", "enforcement"),
                    _attr("onmc.effect", decision.get("effect_kind", "")),
                    _attr("onmc.outcome", decision.get("outcome", "")),
                    _attr("onmc.enforced", bool(decision.get("enforced", False))),
                ],
            )
        )
    return spans


def to_otlp(spans: Sequence[Mapping[str, Any]], *, service_name: str = "onmc") -> dict[str, Any]:
    """Wrap spans in the OTLP JSON envelope any collector accepts."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", service_name)]},
                "scopeSpans": [{"scope": _SCOPE, "spans": list(spans)}],
            }
        ]
    }


__all__ = ["attribution_spans", "enforcement_spans", "to_otlp", "verdict_span"]
