"""Incident recall — match an error/stacktrace against past failures/fixes.

Given a raw error text or stacktrace, ``compile_recall`` returns a ranked list
of memory entries that describe similar past failures, what was tried, and how
it was resolved.

Normalisation strategy
----------------------
Error text is deliberately noisy:
- Line numbers change with every edit
- Memory addresses and hex constants differ per run
- Timestamps and UUIDs are irrelevant
- File paths carry useful signal (module/file names) but not the line numbers

We strip the noise while keeping the signal tokens (exception type, error
message words, module names) before building the FTS query and running
token-overlap scoring.

Bias
----
Memories of kind ``FAILED_APPROACH`` and ``GOTCHA`` are boosted because they
represent "we hit this before — here is the fix."  ``DECISION`` entries are
included at normal weight because design decisions sometimes explain *why* an
error occurs.  All other kinds receive a small general-context bonus.

Honest empty result
-------------------
When no relevant memories exist the result is empty with a ``no_data_hint``
message telling the caller how to populate the brain (``onmc mine``).
"""

from __future__ import annotations

from oh_no_my_claudecode.recall.compiler import (
    RecallEntry,
    RecallResult,
    ScoreBreakdown,
    compile_recall,
)

__all__ = ["RecallEntry", "RecallResult", "ScoreBreakdown", "compile_recall"]
