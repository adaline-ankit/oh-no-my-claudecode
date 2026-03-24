# Prompt Compiler

The prompt compiler is ONMC's first bridge between deterministic repo memory and optional LLM reasoning.

It does not run an agent loop. It compiles a structured prompt so a provider-backed call can reason over high-signal repo context instead of raw task text alone.

## Goals

- keep prompt construction inspectable
- inject repo-specific memory before model reasoning
- separate instructions, task context, negative memory, and output contracts
- avoid large unstructured dumps

## Modes

### `solve`

Goal:

- propose the next best engineering approach
- respect repo memory and constraints
- avoid repeated failures
- recommend likely files and validations

Structured output shape:

- `approach_summary`
- `files_to_inspect`
- `risks`
- `validations`
- `confidence`

### `review`

Goal:

- critique a proposed or likely fix
- identify assumptions, missing checks, architectural risks, and likely regressions

Structured output shape:

- `concerns`
- `assumptions`
- `likely_regressions`
- `required_tests`

### `teach`

Goal:

- explain how to think about the task at a staff-engineer level
- summarize root-cause reasoning, false leads, and transferable lessons

Structured output shape:

- `reasoning_map`
- `system_lesson`
- `false_lead_analysis`
- `mental_model_upgrade`

## Prompt Sections

Each compiled prompt separates:

1. mode goal
2. instructions
3. task record
4. repo context from the deterministic brief
5. relevant repo memory with provenance
6. prior attempts
7. negative memory
8. validation guidance
9. provenance summary
10. output contract

## Why Memory Is Injected This Way

ONMC is memory-first. The prompt compiler uses the deterministic brief as the spine, then adds task-scoped records around it:

- repo memory provides durable facts, decisions, invariants, hotspots, and validation rules
- attempts preserve what was already tried
- negative memory highlights failures and design conflicts so the model does not repeat them
- validation guidance keeps the response tied to likely repo checks
- provenance keeps the prompt grounded in where the signals came from

This keeps the model in a reasoning role instead of using it to rediscover repo context from scratch.
