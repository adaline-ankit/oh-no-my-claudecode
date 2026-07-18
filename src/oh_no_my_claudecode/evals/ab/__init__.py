"""Outcome-level A/B eval harness — ONMC+Claude Code vs Claude Code alone.

Usage
-----
    from oh_no_my_claudecode.evals.ab.runner import run_suite
    from oh_no_my_claudecode.evals.ab.tasks import BUILTIN_TASKS

    report = run_suite(BUILTIN_TASKS, fixture=True)   # CI-safe, no LLM
    print(report.to_markdown())

CLI
---
    onmc eval ab [--fixture] [--json] [--task <id>]
"""
