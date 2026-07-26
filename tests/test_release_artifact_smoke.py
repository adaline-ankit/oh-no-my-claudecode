from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = REPO_ROOT / "scripts" / "release_artifact_smoke.py"
    spec = importlib.util.spec_from_file_location("release_artifact_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_wheel_requires_exactly_one_artifact(tmp_path: Path) -> None:
    module = _load_script()
    with pytest.raises(ValueError, match="exactly one"):
        module.select_wheel(tmp_path)

    wheel = tmp_path / "oh_no_my_claudecode-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    assert module.select_wheel(tmp_path) == wheel


def test_fixture_smoke_requires_explicit_passing_fixture_evidence() -> None:
    module = _load_script()
    module.validate_fixture_payload(
        {
            "fixture": True,
            "total_tasks": 1,
            "comparisons": [
                {
                    "onmc": {
                        "passed": True,
                        "evidence_kind": "fixture",
                    }
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="fixture"):
        module.validate_fixture_payload(
            {
                "fixture": False,
                "total_tasks": 1,
                "comparisons": [],
            }
        )
