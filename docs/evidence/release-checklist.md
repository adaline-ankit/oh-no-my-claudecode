# Benchmark release checklist

This checklist is fail-closed. A checked infrastructure item does not imply that
ONMC earned an external quality, cost, or state-of-the-art claim.

## Evidence inputs

- [ ] Portfolio manifest passes
  `scripts/validate_benchmark_manifest.py --require-publication-ready`.
- [ ] Portfolio revision, code SHA, environment digest, verifier digest, agents,
  models, seeds, limits, and approved hard cost ceiling are frozen.
- [ ] At least 50 discriminative tasks cover multiple repositories, languages,
  and task classes.
- [ ] Bare agent, context-only, canonical single-agent ONMC,
  trajectory-routed ONMC, and selective swarm use matched controls.
- [ ] Three or more agent/model configurations run across three or more seeds.
- [ ] The powered sample size is justified by effect size, variance, confidence
  level, and non-inferiority margin.

## Evidence completeness

- [ ] Every usable cell has a raw ATIF trajectory and verifier artifact.
- [ ] Raw artifact index paths are local to the artifact root and hashes verify.
- [ ] Frozen verifier calibration artifact matches the current corpus and
  adjudicator, rejects prose-only completion and protected-suite weakening, and
  catches mutation negative controls.
- [ ] Pass rates, pass@k, paired deltas, confidence intervals, latency, tokens,
  and failure taxonomy are complete.
- [ ] Cost coverage is symmetric and complete for every compared arm.
- [ ] Failed, excluded, infrastructure-failed, and saturated tasks are disclosed.
- [ ] Independent leakage audit confirms hidden or time-sliced material was
  unavailable to agents.
- [ ] `scripts/gate_external_claim.py` allows the exact proposed release text.

## Local release validation

- [ ] `ruff check .`
- [ ] `mypy src`
- [ ] `pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80`
- [ ] `python scripts/generate-cli-reference.py --check`
- [ ] `python -m build`
- [ ] `python -m twine check dist/*`
- [ ] `python scripts/release_artifact_smoke.py --dist-dir dist --offline`
- [ ] Harbor `nop`/local Docker non-vacuity smoke behaves as documented.
- [ ] Release artifacts are signed and independently verified.

The artifact smoke installs the built wheel in a disposable environment and
runs one explicitly labelled fixture comparison with zero model calls. It proves
the package and fixture execution path, not external benchmark performance.

## Publish stop

Do not tag, upload, or publish while any item above is unchecked. The current
[generated report](sota-report.md) remains not publication-ready and is the
authoritative blocker list for the committed evidence.
