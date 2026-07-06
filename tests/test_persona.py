"""Offline unit tests for the ``persona`` module.

No filesystem, network, or LLM: the pure ``presets`` module is tested directly.
CLI persistence tests use a temporary directory.

Coverage goals (≥ 7 tests):
1.  ``list`` — PRESETS has presets; each has required keys.
2.  ``get_persona`` — known name returns correct spec.
3.  ``get_persona`` — unknown name raises UnknownPersonaError gracefully.
4.  ``line`` — deterministic per (persona, event, seed).
5.  ``line`` — distinct voices: same (event, seed) but different persona → diff lines.
6.  ``line`` — seed wraps modulo bank length (no IndexError).
7.  ``line`` — unknown event falls through to generic bank.
8.  JSON envelope shape via pure core (no CLI runner required).
9.  Default persona returned when no active.json present.
10. Persistence round-trip: set name → load name returns same.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.persona.presets import (
    PRESETS,
    PersonaSpec,
    UnknownPersonaError,
    get_persona,
    line,
)

# ---------------------------------------------------------------------------
# 1. PRESETS registry — structure
# ---------------------------------------------------------------------------


def test_presets_has_entries() -> None:
    """PRESETS is non-empty and contains known preset names."""
    assert len(PRESETS) >= 5
    known = {"drill-sergeant", "hype-beast", "zen-master", "pirate", "professional"}
    assert known.issubset(set(PRESETS))


def test_each_preset_has_required_fields() -> None:
    """Every preset exposes name, description, tone, sample_lines, line_banks."""
    for name, spec in PRESETS.items():
        assert isinstance(spec, PersonaSpec), f"{name}: not a PersonaSpec"
        assert spec.name == name, f"{name}: spec.name mismatch"
        assert spec.description, f"{name}: empty description"
        assert spec.tone, f"{name}: empty tone"
        assert len(spec.sample_lines) >= 1, f"{name}: no sample lines"
        assert isinstance(spec.line_banks, dict), f"{name}: line_banks not a dict"
        assert "generic" in spec.line_banks, f"{name}: missing 'generic' bank"


# ---------------------------------------------------------------------------
# 2. get_persona — known name
# ---------------------------------------------------------------------------


def test_get_persona_returns_correct_spec() -> None:
    spec = get_persona("zen-master")
    assert spec.name == "zen-master"
    assert spec.tone == "meditative"


# ---------------------------------------------------------------------------
# 3. get_persona — unknown name
# ---------------------------------------------------------------------------


def test_get_persona_unknown_raises_gracefully() -> None:
    with pytest.raises(UnknownPersonaError) as exc_info:
        get_persona("corporate-buzzword")
    assert "unknown persona" in str(exc_info.value).lower()
    assert "corporate-buzzword" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. line — deterministic per (persona, event, seed)
# ---------------------------------------------------------------------------


def test_line_is_deterministic_same_seed() -> None:
    """Same (persona, event, seed) always returns the same string."""
    spec = get_persona("pirate")
    a = line(spec, "test_pass", seed=0)
    b = line(spec, "test_pass", seed=0)
    assert a == b


def test_line_differs_by_seed() -> None:
    """Different seeds produce different lines when the bank has ≥ 2 entries."""
    spec = get_persona("drill-sergeant")
    l0 = line(spec, "test_pass", seed=0)
    l1 = line(spec, "test_pass", seed=1)
    assert l0 != l1


# ---------------------------------------------------------------------------
# 5. Distinct voices — different personas → different output
# ---------------------------------------------------------------------------


def test_distinct_voices_different_personas() -> None:
    """Same (event, seed) produces different lines for different personas."""
    event = "test_pass"
    seed = 0
    lines = {
        name: line(get_persona(name), event, seed=seed) for name in PRESETS
    }
    # All lines are non-empty
    for name, text in lines.items():
        assert text, f"{name}: empty line for test_pass seed=0"
    # Not all personas produce the same output
    unique = set(lines.values())
    assert len(unique) == len(PRESETS), (
        "All personas produced identical lines — something is wrong with the banks."
    )


# ---------------------------------------------------------------------------
# 6. line — seed wrap (no IndexError)
# ---------------------------------------------------------------------------


def test_line_seed_wraps_correctly() -> None:
    """Seed wraps modulo bank length — never raises IndexError."""
    spec = get_persona("hype-beast")
    bank = spec.line_banks["test_pass"]
    bank_len = len(bank)
    # seed = bank_len should wrap to index 0
    assert line(spec, "test_pass", seed=bank_len) == line(spec, "test_pass", seed=0)


def test_line_large_seed_no_error() -> None:
    """A large seed value wraps cleanly."""
    spec = get_persona("professional")
    result = line(spec, "commit", seed=999_999)
    assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# 7. line — unknown event falls through to generic
# ---------------------------------------------------------------------------


def test_line_unknown_event_falls_through_to_generic() -> None:
    """An unrecognised event key returns a line from the generic bank."""
    spec = get_persona("zen-master")
    result = line(spec, "galaxy_brain_moment", seed=0)
    # Must be a non-empty string drawn from the generic bank
    assert isinstance(result, str) and len(result) > 0
    assert result in spec.line_banks["generic"]


# ---------------------------------------------------------------------------
# 8. JSON envelope shape
# ---------------------------------------------------------------------------


def test_json_envelope_shape_persona_list() -> None:
    """persona_list envelope has expected keys."""
    presets_list = [spec.to_dict() for spec in PRESETS.values()]
    envelope = {"kind": "persona_list", "presets": presets_list}
    assert envelope["kind"] == "persona_list"
    assert isinstance(envelope["presets"], list)
    for entry in envelope["presets"]:
        assert "name" in entry
        assert "description" in entry
        assert "tone" in entry
        assert "sample_lines" in entry


def test_json_envelope_shape_persona_say() -> None:
    """persona_say envelope has expected keys."""
    spec = get_persona("drill-sergeant")
    result = line(spec, "build_pass", seed=2)
    envelope = {
        "kind": "persona_say",
        "persona": spec.name,
        "event": "build_pass",
        "seed": 2,
        "line": result,
    }
    assert envelope["kind"] == "persona_say"
    assert envelope["persona"] == "drill-sergeant"
    assert "line" in envelope
    assert isinstance(envelope["line"], str)


def test_json_envelope_shape_persona_show() -> None:
    """persona_show envelope has persona sub-dict."""
    spec = get_persona("pirate")
    envelope = {"kind": "persona_show", "persona": spec.to_dict()}
    assert envelope["kind"] == "persona_show"
    d = envelope["persona"]
    assert d["name"] == "pirate"
    assert "tone" in d
    assert "description" in d


# ---------------------------------------------------------------------------
# 9 & 10. Persistence helpers
# ---------------------------------------------------------------------------


def _load_active_name(repo_root: Path) -> str:
    """Mirror of the commands-module helper, inline for test isolation."""
    from oh_no_my_claudecode.persona.commands import _load_active_name as _cmd_load

    return _cmd_load(repo_root)


def _save_active_name(repo_root: Path, name: str) -> None:
    from oh_no_my_claudecode.persona.commands import _save_active_name as _cmd_save

    _cmd_save(repo_root, name)


def test_default_persona_when_no_file(tmp_path: Path) -> None:
    """When no active.json exists, the default persona name is returned."""
    from oh_no_my_claudecode.persona.commands import _DEFAULT_PERSONA_NAME

    result = _load_active_name(tmp_path)
    assert result == _DEFAULT_PERSONA_NAME


def test_set_and_load_roundtrip(tmp_path: Path) -> None:
    """set active name → load active name returns the same value."""
    _save_active_name(tmp_path, "pirate")
    loaded = _load_active_name(tmp_path)
    assert loaded == "pirate"


def test_set_and_load_all_presets(tmp_path: Path) -> None:
    """Every preset name can be persisted and loaded back."""
    for name in PRESETS:
        _save_active_name(tmp_path, name)
        assert _load_active_name(tmp_path) == name


def test_corrupt_active_json_returns_default(tmp_path: Path) -> None:
    """Corrupt active.json silently falls back to the default persona."""
    from oh_no_my_claudecode.persona.commands import _DEFAULT_PERSONA_NAME

    active_path = tmp_path / ".onmc" / "persona" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text("NOT_VALID_JSON{{}", encoding="utf-8")

    result = _load_active_name(tmp_path)
    assert result == _DEFAULT_PERSONA_NAME


def test_active_json_unknown_preset_returns_default(tmp_path: Path) -> None:
    """active.json with an unknown preset name falls back to default."""
    from oh_no_my_claudecode.persona.commands import _DEFAULT_PERSONA_NAME

    active_path = tmp_path / ".onmc" / "persona" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(json.dumps({"name": "nonexistent-persona"}), encoding="utf-8")

    result = _load_active_name(tmp_path)
    assert result == _DEFAULT_PERSONA_NAME


# ---------------------------------------------------------------------------
# to_dict — serialisation
# ---------------------------------------------------------------------------


def test_persona_spec_to_dict_keys() -> None:
    """to_dict includes name, description, tone, sample_lines."""
    spec = get_persona("professional")
    d = spec.to_dict()
    assert set(d.keys()) == {"name", "description", "tone", "sample_lines"}
    assert d["name"] == "professional"
    assert isinstance(d["sample_lines"], list)
    assert len(d["sample_lines"]) >= 1
