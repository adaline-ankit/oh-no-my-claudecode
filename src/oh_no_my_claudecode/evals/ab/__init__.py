"""Outcome-level A/B eval harness — ONMC+Claude Code vs Claude Code alone.

Usage
-----
    from oh_no_my_claudecode.evals.ab.runner import run_suite
    from oh_no_my_claudecode.evals.ab.tasks import BUILTIN_TASKS, PUBLIC_REPO_TASKS

    report = run_suite(BUILTIN_TASKS, fixture=True)   # CI-safe, no LLM
    live = run_suite(PUBLIC_REPO_TASKS)               # pinned public repos
    print(report.to_markdown())

CLI
---
    onmc eval ab [--fixture | --public-repo] [--json] [--task <id>]
"""
