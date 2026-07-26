from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.experiment.verifier_calibration import calibrate_default_verifier
from oh_no_my_claudecode.verifier.calibration import (
    DEFAULT_EXTERNAL_CORPUS_PATH,
    calibrate_external_corpus,
    load_external_corpus,
)


def test_default_verifier_calibration_uses_external_corpus_and_honest_intervals() -> None:
    report = calibrate_default_verifier()

    assert report.corpus_kind == "external-frozen"
    assert report.corpus_revision == "verifier-external-v2-2026-07-26"
    assert report.caught_false_green == 12
    assert report.missed_false_green == 0
    assert report.false_green_cases == 12
    assert report.cleared_legitimate == 12
    assert report.false_positive_legitimate == 0
    assert report.legitimate_cases == 12
    assert report.sensitivity == 1.0
    assert report.specificity == 1.0
    assert report.sensitivity_ci_low < report.min_sensitivity
    assert report.specificity_ci_low < report.min_specificity
    assert report.point_gate_passed is True
    assert report.ci_gate_supported is False
    assert report.claim_ready is False
    assert report.required_perfect_false_green_cases > report.false_green_cases
    assert report.required_perfect_legitimate_cases > report.legitimate_cases
    assert any("confidence interval" in reason for reason in report.reasons)


def test_external_corpus_is_frozen_and_all_cases_have_external_provenance() -> None:
    corpus = load_external_corpus(DEFAULT_EXTERNAL_CORPUS_PATH)

    assert corpus.schema_version == "2"
    assert corpus.revision == "verifier-external-v2-2026-07-26"
    assert len(corpus.cases) == 24
    assert {case.expected_label.value for case in corpus.cases} == {
        "false-green",
        "true-fix",
    }
    assert len({case.case_id for case in corpus.cases}) == 24
    assert len({case.source.repository_url for case in corpus.cases}) >= 6
    for case in corpus.cases:
        assert case.source.repository_url.startswith("https://github.com/")
        assert len(case.source.pinned_sha) >= 7
        assert case.source.task_id
        assert case.source.verifier_argv


def test_external_corpus_digest_rejects_post_freeze_edits(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_EXTERNAL_CORPUS_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["evidence"]["agent_claimed_complete"] = False
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content_sha256"):
        load_external_corpus(path)


def test_external_calibration_fails_closed_on_missing_deterministic_evidence(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_EXTERNAL_CORPUS_PATH.read_text(encoding="utf-8"))
    payload["cases"][12]["evidence"]["changed_code_reached"] = None
    path = tmp_path / "missing-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = calibrate_external_corpus(path, verify_digest=False)

    assert report.missed_false_green == 0
    assert report.false_positive_legitimate == 1
    assert report.specificity < 1.0
    assert report.claim_ready is False
    assert "changed-code reachability evidence missing" in report.cases[12].reasons
