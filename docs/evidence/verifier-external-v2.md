# Verifier External v2 Calibration Evidence

This slice replaces the publication gate's repo-local-only calibration with a
content-addressed external fixture corpus:

- Corpus: `datasets/verifier_external_v2.json`
- Frozen revision: `verifier-external-v2-2026-07-26`
- Corpus SHA-256: `85f4bbd125bc81522ef57d063aa0a503cea4b319a6f5b35aef3edec2b5d99e2c`
- Machine-readable report: `docs/evidence/verifier_external_v2_report.json`
- Reproduction command:
  `python scripts/calibrate_verifier_external.py --out docs/evidence/verifier_external_v2_report.json`

## Observed result

The deterministic adjudicator caught 12 of 12 deceptive false-green fixtures
and cleared 12 of 12 reference true-fix fixtures. The point estimates are
therefore sensitivity `1.0` and specificity `1.0`.

The publication gate remains closed. The two-sided Wilson 95% intervals are
`[0.758, 1.0]` for both metrics, so their lower bounds do not meet the
pre-registered sensitivity `0.95` and specificity `0.98` targets. With zero
observed errors, at least 73 false-green observations and 189 legitimate
true-fix observations are needed for those respective lower bounds.

## What this evidence does and does not prove

The 24 cases are paired, deterministic evidence fixtures grounded in six pinned
external repositories and their upstream verifier commands. They exercise test
deletion, skip injection, assertion weakening, verifier narrowing, fixture
tampering, vacuous tests, missing reachability, surviving targeted mutants,
missing baseline reproduction, dual-verifier disagreement, and agent-only
completion.

They are not 24 independent live agent trials. The external verifier-quality
claim must remain blocked until a larger independently replayed corpus reaches
the confidence-bound gate. LLM review remains advisory and is excluded from the
pass calculation.
