# oh-no-my-claudecode (`onmc`)

[![CI](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml/badge.svg)](https://github.com/adaline-ankit/oh-no-my-claudecode/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/adaline-ankit/oh-no-my-claudecode)](https://github.com/adaline-ankit/oh-no-my-claudecode/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Your code changed. Your agent's memory should too.

**Keep the task. Refresh the evidence.** ONMC gives Claude Code an adaptive working
context: the goal, constraints, decisions, and next step survive compaction;
recalled claims lose eligibility when their source files change.

Local SQLite. No model calls to compile working context. Inspect every inclusion,
exclusion, and withdrawal. Use native Claude hooks, or the same state through CLI
and MCP with other coding agents.

![ONMC demo: a remembered 30-second TTL is withdrawn after its source changes to 60 seconds; constraints and next step are restored, repeated context emits zero characters.](docs/assets/working-context-demo.gif)

*Animated rendering of [real Git, SQLite, and hook results](docs/assets/working-context-demo.json).
Eight checks, no model calls. [Static image](docs/assets/working-context-demo.png)
· [Run it yourself](#try-the-demo-without-an-api-key)*

### What changes in your workflow

| When this happens | ONMC supplies |
|---|---|
| You start a task | A session-specific goal and explicit constraints |
| You move between files | Relevant repository memory within a fixed character budget |
| A recalled fact's source changes, even before commit | A withdrawal notice and a refreshed packet |
| Claude compacts or resumes | Current goal, constraints, saved decisions, and next step |
| Nothing relevant changed | No duplicate packet |
| You need to inspect the decision | Source anchors and inclusion/exclusion reasons |

This is advisory context. ONMC cannot erase old conversation text or guarantee
that an agent follows instructions. Source freshness is not semantic correctness.
[Read the exact behavior and limits.](docs/working-context.md)

## Try it in your repo

**Adaptive working context is on `main`; it is not in the latest PyPI release,
`v0.113.0`.** Install from Git for this feature. Python 3.11+ and Git required.

```bash
uv tool install --force 'git+https://github.com/adaline-ankit/oh-no-my-claudecode.git@main'
cd your-repo
onmc init
onmc ingest --no-llm
onmc working enable \
  --constraint "Preserve existing public APIs" \
  --constraint "Add no new runtime dependencies"
claude
```

Start or resume Claude after enabling so it reloads project hooks and MCP settings.
Existing custom hooks are preserved. Automatic `CLAUDE.md` refresh preserves
user-authored or edited files. `onmc working disable` stops adaptive injection.

Claude can save decisions and next steps with `record_working_note`. A new session
gets a separate goal and notes; working notes are not automatically promoted to
repository memory.

**Codex and other MCP clients:** use `start_working_context`,
`get_working_context`, and `record_working_note` with an explicit session ID.
Native automatic working-context hooks currently target Claude Code.
[CLI examples and MCP setup](docs/working-context.md)
· [Codex integration](docs/integrations/codex.md)

For the latest **released** package and its existing memory/runtime features:

```bash
uv tool install oh-no-my-claudecode
onmc setup --no-llm
```

## More than a context packet

Working context sits on ONMC's existing repository memory and execution harness.
Use the pieces independently.

| Capability | Entry point | What it provides |
|---|---|---|
| Repository memory | `onmc ingest`, `onmc brief`, `onmc guard` | Provenance, ranked recall, and recorded failed approaches |
| Adaptive working context | `onmc working` | Session state, source checks, bounded packets, repeat suppression |
| Controlled execution | `onmc run` | Plan preview, explicit execution, configured verifier, durable run state |
| Inspectable evidence | Receipts, trace, eval, replay | Tamper-evident records and reproducible checks |
| Portable knowledge | `onmc sync` | Git-portable repository memory in `.agent-memory` |
| Agent access | CLI, Python API, hooks, MCP | Multiple interfaces to the same local store |

Preview a task without invoking a model:

```bash
onmc run "fix cache expiration"
```

Then explicitly execute with an installed, authenticated agent and a verifier
appropriate to your project:

```bash
onmc run "fix cache expiration" --execute \
  --agent codex \
  --verifier "python -m pytest -q --cov=your_package --cov-report=json" \
  --max-iterations 3 \
  --isolate
```

Replace `your_package` with your package name; the example needs `pytest-cov`.
A passing command alone may not satisfy the configured proof requirements.
ONMC evaluates repository evidence rather than accepting the agent's claim of
completion. The verifier still needs to test the behavior you care about.

Mutation checks, full adjudication, external attestation, and optional provider
integrations have their own configuration and dependencies. They do not all run
by default. Cost is only known when the selected provider reports it.
[Execution guide](docs/harness-run.md) · [Capability catalog](docs/shipped-capabilities.md)

## What the measurements show

All numbers below come from **internal experiments** with published protocols and
artifacts. They are not a general coding-accuracy claim.

| Experiment | Result | What it establishes |
|---|---|---|
| Synthetic working-context event suite | **117/117** eligibility/delivery checks; legacy path **99/117** | Covered transitions behave as specified; legacy delivered 18 stale/deleted claims |
| Adaptive vs forced-refresh delivery | **36.5% fewer injected characters** | Repeat suppression in this event suite; adaptive still used more characters than legacy |
| 10,000-memory synthetic corpus | **2.48 ms p50**, **20.20 ms p95** | In-process packet compilation on one Apple M4; excludes process startup |
| Live Codex pilot, three tasks per arm | **3/3 vs 3/3**; 18 grader tests passed per arm | Successful pilot execution; **no demonstrated accuracy improvement** |
| Frozen code retrieval, 40 queries | BM25 R@5 **0.950**; hybrid **0.875** | BM25 won this corpus; it remains the default |

[Working-context protocol](docs/benchmarks/working-context.md)
· [Raw results and limitations](docs/benchmarks/results/2026-09-19-working-context/README.md)
· [Broader harness evidence](docs/evidence/sota-report.md)

The broader publication gate remains **blocked**. ONMC publishes ties, losses,
and missing evidence alongside favorable component results. Larger held-out,
long-session coding evaluations are still needed.

## Try the demo without an API key

From a source checkout:

```bash
git clone https://github.com/adaline-ankit/oh-no-my-claudecode.git
cd oh-no-my-claudecode
uv sync --extra dev --locked
uv run --locked python scripts/demo-working-context.py \
  --output /tmp/working-context-demo.json
```

The demo creates a temporary Git repo, remembers a 30-second cache TTL, changes
the source to 60 seconds **without changing its timestamp**, and checks that the
old claim is withdrawn. It also checks restoration, session isolation, budgets,
and zero-character repeat delivery. It does not run Claude or Codex.

## Explore or contribute

- [Working context](docs/working-context.md): hooks, notes, freshness rules, and budgets
- [Architecture](docs/architecture.md): storage, context compiler, runtime, and evidence boundaries
- [CLI reference](docs/cli-reference.md): generated command reference
- [Shipped capabilities](docs/shipped-capabilities.md): broader feature catalog
- [Roadmap](docs/roadmap.md): the next hard problems
- [Contributing](CONTRIBUTING.md): setup and quality gates
- [Share-ready demo and copy](docs/launch/adaptive-working-context.md): current launch material

Useful contributions: a held-out long-session benchmark, independent child-agent
working state, richer source anchors, and failure cases where context was fresh
but the agent still made the wrong decision. Open an issue with a reproducible
case. The project is MIT licensed and welcomes independent replication.
