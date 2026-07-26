# OpenTelemetry and Phoenix

ONMC records traces locally first. Network export is optional, synchronous, and disabled unless a
caller constructs `OtlpHttpExporter`.

## What ONMC exports

- Real recorded start/end timestamps. If an end time was not observed, the span is zero-length and
  carries `onmc.duration.complete=false`; ONMC does not invent a one-millisecond duration.
- Provider-reported input, output, cache-read, cache-creation, reasoning, and cost fields when they
  exist.
- `onmc.usage.complete=false` and `onmc.cost.complete=false` when provider data is incomplete. A
  total-only token count remains total-only; ONMC never derives a 60/40 input/output split.
- Explicit parent-child relationships for runtime runs, nodes, tools, model calls, retrieval,
  verification, policy, routing, and promotion decisions, plus runtime DAG dependency links.
- Content capture disabled by default. Prompt, output, query, target, error text, tool arguments,
  and local paths are omitted. Opt-in content capture still redacts common API keys, bearer tokens,
  credential assignments, and home-directory usernames.

`onmc trace report <session-id> --otel spans.json` writes spans from the raw session events. It does
not reconstruct spans from aggregated counters because those counters contain no real timestamps or
hierarchy.

## Send OTLP/HTTP JSON

The dependency-free exporter implements the OTLP/HTTP JSON
`ExportTraceServiceRequest` envelope:

```python
from oh_no_my_claudecode.telemetry import OtlpHttpExporter
from oh_no_my_claudecode.trace.otel import to_otel_spans
from oh_no_my_claudecode.trace.recorder import load_session_events

_, events = load_session_events(repo_root, session_id)
spans = to_otel_spans(events, session_id=session_id)

result = OtlpHttpExporter(
    "http://localhost:4318",
    service_name="onmc",
).export(spans)
if not result.success:
    raise RuntimeError(result.error)
```

Passing a base collector URL appends `/v1/traces`. Authentication headers are accepted through the
`headers` argument, but they are excluded from exporter representations and export results. Load
them from the environment or a secret manager; do not commit them.

The exporter performs one bounded request and no automatic retry. Its result distinguishes attempted,
exported, and collector-rejected span counts.

## Phoenix

Phoenix is an optional UI sink; ONMC's local trace session remains canonical. Phoenix documents its
self-hosted UI and HTTP collector on port `6006`, with traces accepted at `/v1/traces`. Its current
self-hosted endpoint documentation specifies OTLP **Protobuf**, while ONMC's dependency-free exporter
sends standard OTLP/HTTP **JSON**. Use an OpenTelemetry Collector as the format bridge instead of
assuming direct JSON ingestion:

```yaml
# otel-collector.yaml
receivers:
  otlp:
    protocols:
      http:

exporters:
  otlphttp/phoenix:
    endpoint: http://phoenix:6006
    headers:
      x-project-name: onmc

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp/phoenix]
```

Point `OtlpHttpExporter` at the collector's port `4318`. The collector accepts OTLP/HTTP JSON and its
`otlphttp` exporter sends OTLP Protobuf to Phoenix. Open `http://localhost:6006` and verify the
run → node → child hierarchy and measured attributes.

For a disposable local Phoenix instance, follow the official Docker guide and use `latest` only for
the smoke test. Pin an explicit Phoenix version for persistent or production use.

References:

- [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
- [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [Phoenix Docker deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [Phoenix endpoint reference](https://arize.com/docs/phoenix/learn/faqs/what-is-my-phoenix-endpoint)
