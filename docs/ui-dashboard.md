# ONMC Visual Dashboard

## Objective

Provide a local, read-only dashboard that makes ONMC memory, tasks, repository hotspots,
and health signals easy to inspect and share. The first release targets maintainers and
coding-agent users who want a useful visual surface without operating a hosted service.

## Command

```bash
onmc ui --host 127.0.0.1 --port 8765
```

Options:

- `--host`: bind address; defaults to loopback
- `--port`: TCP port; defaults to `8765`
- `--no-open`: do not open the system browser

## API Contract

`GET /api/dashboard` returns one JSON document:

- repository identity and ingest timestamp
- memory counts, records, kinds, confidence, and provenance
- task records with attempt, artifact, and output counts
- directory and hot-file codegraph data
- doctor health sections, warnings, errors, and readiness state
- shareable readiness report

Static assets are served from the installed Python package. Unknown paths return `404`.

## Interface

- persistent sidebar with Overview, Memory, Tasks, Codegraph, and Health views
- compact overview metrics and current activity
- searchable and filterable memory table
- task table with status and linked record counts
- canvas-based repository hotspot graph
- health checklist and copyable report
- responsive layout for 320px through 1440px viewports
- keyboard-accessible controls, visible focus, semantic headings, and useful empty/error states

## Boundaries

- read-only: no state mutation from browser
- local-first: no external assets, telemetry, accounts, or hosted dependency
- safe default: bind to `127.0.0.1`
- no new runtime framework dependency
- browser receives rendered data only through same-origin JSON

## Verification

- payload and HTTP route tests
- static asset packaging test
- CLI help/reference update
- full Python quality gates
- real-browser desktop and mobile screenshots
- zero browser console errors
