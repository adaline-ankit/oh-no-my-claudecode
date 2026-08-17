# Observability — see ONMC inside the dashboards you already use

ONMC emits OpenTelemetry: GenAI-convention spans for model/tool activity
(`trace/otel.py`) and **judgment spans no other producer has** — run verdicts,
per-memory measured lift, enforcement decisions (`trace/otel_ledger.py`).
`onmc observe` ships them to any OTLP backend. Their UI, ONMC's judgment.

Configuration is the standard OTel env contract — nothing ONMC-specific:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=...   # backend OTLP base URL
export OTEL_EXPORTER_OTLP_HEADERS=...    # comma-separated k=v auth headers
onmc observe --dry-run                   # count + target, sends nothing
onmc observe                             # ship verdict spans
```

## Langfuse (hosted, recommended first stop)

1. Create a project at cloud.langfuse.com → Settings → API Keys.
2. Build the Basic token from your keypair and point the env at their OTel
   endpoint:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(printf 'pk-lf-…:sk-lf-…' | base64)"
onmc observe
```

Spans appear under Tracing with `onmc.kind = verdict | attribution |
enforcement` attributes — filter on `onmc.verified = false` for the failures
feed, or chart `onmc.lift.mean` by `onmc.artifact.id` for the memory P&L.

## Arize Phoenix (local, free, OTel-native)

```bash
uvx arize-phoenix serve                     # UI on http://localhost:6006
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006
onmc observe
```

## Grafana Cloud / any collector

Point `OTEL_EXPORTER_OTLP_ENDPOINT` at your OTLP-HTTP gateway (e.g.
`https://otlp-gateway-<region>.grafana.net/otlp`) with
`OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <token>"`. Anything that
speaks OTLP/HTTP JSON works — the payload is standards-shaped.

## What ships

| span name | attributes | reading it |
|---|---|---|
| `onmc.verdict` | `onmc.receipt.hash`, `onmc.verified`, `onmc.status`, `onmc.policy.outcome` | did runs actually verify — the false-green feed |
| `onmc.attribution` | `onmc.artifact.id`, `onmc.lift.mean`, `onmc.lift.ci_low/high`, `onmc.lift.verdict` | which memories/skills earn their place |
| `onmc.enforcement` | `onmc.effect`, `onmc.outcome`, `onmc.enforced` | what the reference monitor blocked |

Span/trace ids are deterministic (derived from receipt hashes), so re-shipping
is idempotent in backends that dedupe on id.
