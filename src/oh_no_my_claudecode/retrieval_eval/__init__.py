"""Offline retrieval quality evaluation harness.

Provides Recall@k, MRR@k, nDCG@k, and Precision@k metrics over a frozen
labeled dataset.  Entirely offline and deterministic — no LLM calls, no
network access, no randomness.

Usage::

    from oh_no_my_claudecode.retrieval_eval.runner import run_evaluation
    from oh_no_my_claudecode.retrieval_eval.adapters import RecallAdapter, GuardAdapter

    report = run_evaluation([RecallAdapter(), GuardAdapter()])
    print(report.to_markdown())
"""

from oh_no_my_claudecode.retrieval_eval.metrics import (
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from oh_no_my_claudecode.retrieval_eval.runner import RetrievalReport, run_evaluation

__all__ = [
    "RetrievalReport",
    "mrr_at_k",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "run_evaluation",
]
