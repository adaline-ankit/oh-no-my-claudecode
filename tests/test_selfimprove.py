"""Tests for ``onmc selfimprove`` -- after-turn learning review.

Coverage
--------
- Correction phrase -> candidate extracted with signal="correction".
- Preference phrase -> candidate extracted with signal="preference".
- Noise / short sentence -> no false-positive candidate.
- Determinism: same input always yields the same output.
- ``--stage`` enqueues candidates into the memstage queue (verified via
  memstage.queue.list_pending on the same repo_root).
- ``--json`` produces a valid JSON envelope with expected keys.
- Empty / whitespace-only input is handled gracefully (no crash).
- No learnings found path: exits cleanly with appropriate message.
- Confirmation phrase -> candidate extracted with signal="confirmation".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.memstage.queue import list_pending
from oh_no_my_claudecode.selfimprove.commands import register
from oh_no_my_claudecode.selfimprove.review import extract_learnings

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app() -> typer.Typer:
    """Build a minimal Typer app with the selfimprove subgroup registered.

    Needs a sentinel command so Typer treats it as a multi-command group,
    which makes the subgroup discovery work the same way as the real CLI.
    """
    app = typer.Typer()

    @app.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover
        ...

    register(app)
    return app


# ---------------------------------------------------------------------------
# Unit tests -- extract_learnings (pure, no I/O)
# ---------------------------------------------------------------------------


class TestExtractLearnings:
    def test_correction_phrase_extracted(self) -> None:
        text = "Actually, you should always use ruff for linting, not flake8."
        candidates = extract_learnings(text)
        assert len(candidates) >= 1
        assert any(c.signal == "correction" for c in candidates)

    def test_preference_phrase_extracted(self) -> None:
        text = "I prefer to use double quotes everywhere in this project."
        candidates = extract_learnings(text)
        assert len(candidates) >= 1
        assert any(c.signal == "preference" for c in candidates)

    def test_confirmation_phrase_extracted(self) -> None:
        text = "Yes, that's right -- keep doing it that way."
        candidates = extract_learnings(text)
        assert len(candidates) >= 1
        assert any(c.signal == "confirmation" for c in candidates)

    def test_noise_short_sentence_no_false_positive(self) -> None:
        text = "Ok. Sure. Got it."
        candidates = extract_learnings(text)
        assert candidates == []

    def test_generic_noise_no_false_positive(self) -> None:
        text = (
            "The function returns a list of strings. "
            "It iterates over the items and filters by length. "
            "The result is sorted alphabetically."
        )
        candidates = extract_learnings(text)
        assert candidates == []

    def test_determinism(self) -> None:
        text = (
            "Actually, you should use pnpm not npm for this project. "
            "I prefer double quotes everywhere. "
            "Yes, that's correct, keep doing that."
        )
        first = extract_learnings(text)
        second = extract_learnings(text)
        assert [c.to_dict() for c in first] == [c.to_dict() for c in second]

    def test_corrections_ranked_before_preferences(self) -> None:
        text = (
            "I prefer to always use type hints. "
            "No, you should not use print statements -- use logging instead."
        )
        candidates = extract_learnings(text)
        signals = [c.signal for c in candidates]
        assert "correction" in signals
        # Corrections must come before preferences in the ranked output
        first_correction = next(i for i, c in enumerate(candidates) if c.signal == "correction")
        preference_indices = [i for i, c in enumerate(candidates) if c.signal == "preference"]
        if preference_indices:
            last_preference = max(preference_indices)
            assert first_correction < last_preference

    def test_empty_input_returns_empty_list(self) -> None:
        assert extract_learnings("") == []
        assert extract_learnings("   \n\n  ") == []

    def test_candidate_to_dict_has_expected_keys(self) -> None:
        text = "Actually, you should always use absolute imports."
        candidates = extract_learnings(text)
        assert len(candidates) >= 1
        d = candidates[0].to_dict()
        assert set(d.keys()) == {"signal", "text", "rationale", "memory_kind", "title"}

    def test_deduplication_same_sentence_once(self) -> None:
        # Repeat the same sentence twice -- should yield only one candidate.
        sentence = "Always use ruff for linting in this project."
        text = f"{sentence} {sentence}"
        candidates = extract_learnings(text)
        texts = [c.text for c in candidates]
        assert len(texts) == len(set(texts))

    def test_going_forward_preference_extracted(self) -> None:
        text = "Going forward, use snake_case for all variable names."
        candidates = extract_learnings(text)
        assert any(c.signal == "preference" for c in candidates)

    def test_from_now_on_preference_extracted(self) -> None:
        text = "From now on, always include docstrings on public functions."
        candidates = extract_learnings(text)
        assert any(c.signal == "preference" for c in candidates)

    def test_memory_kind_mapping(self) -> None:
        correction_text = "No, you should use pathlib not os.path."
        pref_text = "I prefer to always run tests before committing."
        confirm_text = "Yes, that's right, keep doing that."

        corr = extract_learnings(correction_text)
        pref = extract_learnings(pref_text)
        conf = extract_learnings(confirm_text)

        assert any(c.memory_kind == "decision" for c in corr)
        assert any(c.memory_kind == "invariant" for c in pref)
        assert any(c.memory_kind == "doc_fact" for c in conf)

    def test_title_truncated_long_sentence(self) -> None:
        long = "Always " + "x" * 200 + " in this project."
        candidates = extract_learnings(long)
        if candidates:
            # 72 chars + ellipsis = max 73
            assert len(candidates[0].title) <= 75


# ---------------------------------------------------------------------------
# CLI tests -- exercised via flags, not --help
# ---------------------------------------------------------------------------


class TestReviewCommand:
    def test_json_envelope_structure(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.txt"
        transcript.write_text(
            "Actually, you should always use ruff for linting, not flake8.\n"
            "I prefer to keep type hints everywhere.\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            _app(),
            ["selfimprove", "review", "--from-file", str(transcript), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["kind"] == "selfimprove"
        assert "candidates" in data
        assert "count" in data
        assert isinstance(data["candidates"], list)

    def test_json_empty_input_graceful(self, tmp_path: Path) -> None:
        transcript = tmp_path / "empty.txt"
        transcript.write_text("", encoding="utf-8")
        result = runner.invoke(
            _app(),
            ["selfimprove", "review", "--from-file", str(transcript), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kind"] == "selfimprove"
        assert data["count"] == 0
        assert data["candidates"] == []

    def test_no_learnings_human_readable(self, tmp_path: Path) -> None:
        transcript = tmp_path / "noise.txt"
        transcript.write_text(
            "The weather is nice today. Everything is working well.",
            encoding="utf-8",
        )
        result = runner.invoke(
            _app(),
            ["selfimprove", "review", "--from-file", str(transcript)],
        )
        assert result.exit_code == 0
        assert "No learnings" in result.output

    def test_stage_enqueues_into_memstage(self, tmp_path: Path) -> None:
        # Set up a fake git repo root (memstage uses .onmc/memstage/pending/)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        transcript = repo_root / "session.txt"
        transcript.write_text(
            "Actually, you should always use pnpm not npm for package management.",
            encoding="utf-8",
        )

        with patch(
            "oh_no_my_claudecode.selfimprove.commands.discover_repo_root",
            return_value=repo_root,
        ):
            result = runner.invoke(
                _app(),
                [
                    "selfimprove",
                    "review",
                    "--from-file",
                    str(transcript),
                    "--stage",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        pending = list_pending(repo_root)
        assert len(pending) >= 1
        # The staged proposal's summary should contain the correction text
        assert any("pnpm" in p.summary for p in pending)

    def test_stage_with_json_includes_staged_ids(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo2"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        transcript = repo_root / "session.txt"
        transcript.write_text(
            "No, you should use pathlib not os.path for file operations.",
            encoding="utf-8",
        )

        with patch(
            "oh_no_my_claudecode.selfimprove.commands.discover_repo_root",
            return_value=repo_root,
        ):
            result = runner.invoke(
                _app(),
                [
                    "selfimprove",
                    "review",
                    "--from-file",
                    str(transcript),
                    "--stage",
                    "--json",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "staged_ids" in data
        assert isinstance(data["staged_ids"], list)
        assert len(data["staged_ids"]) == len(data["candidates"])
        # Each staged_id starts with "ms-"
        for sid in data["staged_ids"]:
            assert sid.startswith("ms-")

    def test_human_readable_output_shows_candidates(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.txt"
        transcript.write_text(
            "Actually, you should always use ruff for linting, not flake8.\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            _app(),
            ["selfimprove", "review", "--from-file", str(transcript)],
        )
        assert result.exit_code == 0
        assert "CORRECTION" in result.output or "PREFERENCE" in result.output

    def test_missing_file_exits_nonzero(self) -> None:
        result = runner.invoke(
            _app(),
            [
                "selfimprove",
                "review",
                "--from-file",
                "/nonexistent/path/transcript.txt",
            ],
        )
        assert result.exit_code != 0
