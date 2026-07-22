"""Verifier synthesis and proof evaluation without command execution."""

from oh_no_my_claudecode.proof_graph.evaluator import evaluate_proof
from oh_no_my_claudecode.proof_graph.models import (
    Claim,
    ClaimKind,
    DiffMetadata,
    Evidence,
    EvidenceSource,
    Outcome,
    ProofAssessment,
    ProofGraph,
    RiskMetadata,
    TaskKind,
    TaskMetadata,
    VerifierKind,
    VerifierNode,
    VerifierResult,
)
from oh_no_my_claudecode.proof_graph.receipt import ProofReceipt, verify_receipt
from oh_no_my_claudecode.proof_graph.synthesizer import synthesize_proof_graph

__all__ = [
    "Claim",
    "ClaimKind",
    "DiffMetadata",
    "Evidence",
    "EvidenceSource",
    "Outcome",
    "ProofAssessment",
    "ProofGraph",
    "ProofReceipt",
    "RiskMetadata",
    "TaskKind",
    "TaskMetadata",
    "VerifierKind",
    "VerifierNode",
    "VerifierResult",
    "evaluate_proof",
    "synthesize_proof_graph",
    "verify_receipt",
]
