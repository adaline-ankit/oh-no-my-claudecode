"""Pure, offline unit tests for the drift enforcement heuristic.

No filesystem, storage, or network: the ``(path, text)`` stream is injected as
an in-memory provider, and memories are constructed directly.
"""

from __future__ import annotations

from datetime import datetime

from oh_no_my_claudecode.drift.drift import (
    DriftReport,
    check_drift,
    extract_signal,
)
from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind, SourceType

_TS = datetime(2026, 1, 1, 12, 0, 0)


def _memory(
    *,
    mid: str,
    kind: MemoryKind,
    title: str,
    summary: str = "",
) -> MemoryEntry:
    return MemoryEntry(
        id=mid,
        kind=kind,
        title=title,
        summary=summary,
        details="",
        source_type=SourceType.MANUAL,
        source_ref="manual",
        confidence=1.0,
        created_at=_TS,
        updated_at=_TS,
    )


def _provider(files: list[tuple[str, str]]):
    """Return an injectable zero-arg provider over an in-memory file list."""

    def _p():
        return list(files)

    return _p


def test_forbidden_import_is_flagged() -> None:
    """An invariant 'never use requests' flags code that imports requests."""
    mem = _memory(
        mid="m1",
        kind=MemoryKind.INVARIANT,
        title="never use requests",
        summary="use httpx instead for all HTTP",
    )
    files = [
        ("src/client.py", "import requests\n\ndef fetch():\n    return requests.get('x')\n"),
        ("src/ok.py", "import httpx\n"),
    ]
    report = check_drift([mem], _provider(files))
    assert report.checked == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.memory_id == "m1"
    assert finding.confidence >= 0.7  # strong forbid signal
    assert "src/client.py" in finding.evidence
    assert "requests" in finding.signal


def test_honored_invariant_is_not_flagged() -> None:
    """The same invariant does NOT fire when code honors it (no requests)."""
    mem = _memory(
        mid="m1",
        kind=MemoryKind.INVARIANT,
        title="never use requests",
        summary="use httpx instead",
    )
    files = [("src/ok.py", "import httpx\n\ndef fetch():\n    return httpx.get('x')\n")]
    report = check_drift([mem], _provider(files))
    assert report.checked == 1
    assert report.findings == []
    assert any("no drift detected" in n for n in report.notes)


def test_whole_word_match_avoids_false_positive() -> None:
    """'requests' must not match a substring like 'requests_helper'."""
    mem = _memory(mid="m1", kind=MemoryKind.INVARIANT, title="never use requests")
    files = [("src/ok.py", "import requests_helper\nfrom myrequests import x\n")]
    report = check_drift([mem], _provider(files))
    assert report.findings == []


def test_required_token_absent_is_flagged_with_lower_confidence() -> None:
    """An 'always use X' directive fires (softly) when X is absent everywhere."""
    mem = _memory(mid="m2", kind=MemoryKind.DECISION, title="always use pathlib for paths")
    files = [("src/a.py", "import os\nx = os.path.join('a', 'b')\n")]
    report = check_drift([mem], _provider(files))
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.memory_id == "m2"
    # require-absent is weaker than forbid-present: confidence is halved.
    assert finding.confidence < 0.7
    assert "pathlib" in finding.evidence


def test_required_token_present_is_not_flagged() -> None:
    mem = _memory(mid="m2", kind=MemoryKind.DECISION, title="always use pathlib for paths")
    files = [("src/a.py", "from pathlib import Path\nx = Path('a')\n")]
    report = check_drift([mem], _provider(files))
    assert report.findings == []


def test_prefer_over_flags_losing_token() -> None:
    """'prefer httpx over requests' flags code that still uses requests."""
    mem = _memory(mid="m3", kind=MemoryKind.DECISION, title="prefer httpx over requests")
    files = [("src/c.py", "import requests\n")]
    report = check_drift([mem], _provider(files))
    assert len(report.findings) == 1
    assert report.findings[0].memory_id == "m3"
    assert "requests" in report.findings[0].signal


def test_empty_memories_yields_empty_report_with_note() -> None:
    report = check_drift([], _provider([("src/a.py", "import requests\n")]))
    assert isinstance(report, DriftReport)
    assert report.findings == []
    assert report.checked == 0
    assert any("nothing to check" in n for n in report.notes)


def test_no_checkable_directive_notes_gracefully() -> None:
    """A memory with no directive shape produces a helpful note, no crash."""
    mem = _memory(mid="m4", kind=MemoryKind.GOTCHA, title="the emulator sometimes hangs")
    report = check_drift([mem], _provider([("src/a.py", "import requests\n")]))
    assert report.checked == 0
    assert report.findings == []
    assert any("no checkable directives" in n for n in report.notes)


def test_no_files_notes_gracefully() -> None:
    mem = _memory(mid="m1", kind=MemoryKind.INVARIANT, title="never use requests")
    report = check_drift([mem], _provider([]))
    assert report.findings == []
    assert any("no source files" in n for n in report.notes)


def test_min_confidence_filters_findings() -> None:
    """A high --min-confidence drops the weaker require-absent finding."""
    mem = _memory(mid="m2", kind=MemoryKind.DECISION, title="always use pathlib for paths")
    files = [("src/a.py", "import os\n")]
    unfiltered = check_drift([mem], _provider(files))
    assert len(unfiltered.findings) == 1
    filtered = check_drift([mem], _provider(files), min_confidence=0.9)
    assert filtered.findings == []
    assert filtered.checked == 1


def test_deterministic_across_runs() -> None:
    mems = [
        _memory(mid="m1", kind=MemoryKind.INVARIANT, title="never use requests"),
        _memory(mid="m2", kind=MemoryKind.DECISION, title="always use pathlib"),
        _memory(mid="m3", kind=MemoryKind.DECISION, title="prefer httpx over urllib"),
    ]
    files = [("src/a.py", "import requests\nimport urllib\n")]
    r1 = check_drift(mems, _provider(files))
    r2 = check_drift(mems, _provider(files))
    assert r1.to_dict() == r2.to_dict()
    # findings sorted by descending confidence
    confs = [f.confidence for f in r1.findings]
    assert confs == sorted(confs, reverse=True)


def test_findings_sorted_by_confidence_then_id() -> None:
    mems = [
        _memory(mid="z_forbid", kind=MemoryKind.INVARIANT, title="never use requests"),
        _memory(mid="a_require", kind=MemoryKind.DECISION, title="always use pathlib"),
    ]
    files = [("src/a.py", "import requests\n")]  # requests present, pathlib absent
    report = check_drift(mems, _provider(files))
    assert len(report.findings) == 2
    # strong forbid (0.75) should sort before weak require-absent (~0.25)
    assert report.findings[0].memory_id == "z_forbid"
    assert report.findings[1].memory_id == "a_require"


def test_extract_signal_ignores_non_checkable_kinds() -> None:
    mem = _memory(mid="m5", kind=MemoryKind.HOTSPOT, title="never use requests")
    assert extract_signal(mem) is None


def test_extract_signal_forbid_shape() -> None:
    mem = _memory(mid="m6", kind=MemoryKind.INVARIANT, title="do not use pickle")
    signal = extract_signal(mem)
    assert signal is not None
    assert signal.polarity == "forbid"
    forbidden = signal.token
    assert forbidden == "pickle"
