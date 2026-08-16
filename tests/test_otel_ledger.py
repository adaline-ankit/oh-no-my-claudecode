"""OTel ledger export: OTLP-shaped, deterministic, verdicts faithful."""

from __future__ import annotations

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift
from oh_no_my_claudecode.trace.otel_ledger import (
    attribution_spans,
    enforcement_spans,
    to_otlp,
    verdict_span,
)

RECEIPT = {
    "receipt_hash": "a" * 64,
    "verified": False,
    "status": "failed",
    "policy": {"outcome": "allow"},
}


def test_verdict_span_is_faithful_and_deterministic() -> None:
    span = verdict_span(RECEIPT, when_ns=1_000)
    again = verdict_span(RECEIPT, when_ns=1_000)
    assert span == again  # deterministic ids from the receipt hash
    assert len(span["traceId"]) == 32 and len(span["spanId"]) == 16
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["onmc.verified"] == {"boolValue": False}  # never upgraded
    assert attrs["onmc.policy.outcome"] == {"stringValue": "allow"}


def test_attribution_and_enforcement_spans_carry_the_numbers() -> None:
    ledger = [MemoryLift("mem_1", 0.3, (0.1, 0.5), 10, LiftVerdict.EARNING)]
    spans = attribution_spans(ledger, when_ns=5)
    attrs = {a["key"]: a["value"] for a in spans[0]["attributes"]}
    assert attrs["onmc.lift.mean"] == {"doubleValue": 0.3}
    assert attrs["onmc.lift.verdict"] == {"stringValue": "earning"}

    enf = enforcement_spans(
        [{"effect_kind": "filesystem", "outcome": "deny", "enforced": True}], when_ns=5
    )
    eattrs = {a["key"]: a["value"] for a in enf[0]["attributes"]}
    assert eattrs["onmc.outcome"] == {"stringValue": "deny"}
    assert eattrs["onmc.enforced"] == {"boolValue": True}


def test_otlp_envelope_shape() -> None:
    payload = to_otlp([verdict_span(RECEIPT, when_ns=1)])
    scope_spans = payload["resourceSpans"][0]["scopeSpans"][0]
    assert scope_spans["scope"]["name"] == "onmc.ledger"
    assert len(scope_spans["spans"]) == 1
    resource_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
    assert resource_attrs[0]["value"] == {"stringValue": "onmc"}
