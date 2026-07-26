# ONMC Visual Dashboard

## Objective

Provide a local, read-only dashboard that makes ONMC memory, tasks, repository hotspots,
and health signals easy to inspect and share. The first release targets maintainers and
coding-agent users who want a useful visual surface without operating a hosted service.

## Command

```bash
onmc ui --host 127.0.0.1 --port 8765
```

Mission Control is a read-only view over the canonical `onmc run` runtime.
It replays append-only events from `.onmc/harness-runtime`, shows the active
node and persisted action, and labels proof as `pending`, `rejected`,
`unproven`, or `verified`. `verified` requires a matching integrity-valid
harness receipt; a completed event or agent summary is never enough.

For a terminal-only view:

```bash
onmc missioncontrol
```

Options:

- `--host`: bind address; defaults to loopback
- `--port`: TCP port; defaults to `8765`
- `--no-open`: do not open the system browser
- `--export PATH`: write a standalone HTML snapshot instead of starting the server

## Portable Snapshot

```bash
onmc ui --export onmc-brain.html
```

Snapshot export embeds current dashboard data, CSS, and JavaScript into one HTML file. It makes no
network requests and carries a restrictive Content Security Policy. The same search, filters,
navigation, codegraph, and health views work without ONMC running.

Snapshots contain repository paths, memories, task state, and health findings. Review the generated
file before attaching it to an issue, release, or public post. Use `--no-open` in automation.

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
- browser receives rendered data through same-origin JSON or an explicitly exported snapshot

## Verification

- payload and HTTP route tests
- static asset packaging test
- CLI help/reference update
- full Python quality gates
- real-browser desktop and mobile screenshots
- zero browser console errors
- standalone snapshot and script-termination escaping tests
