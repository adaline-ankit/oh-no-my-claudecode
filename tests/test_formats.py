"""Tests for `onmc formats` — the portable open-schema spec.

Covers:
- Pure `build_spec`/`to_json_dict`/`render_text` (no filesystem/network/clock).
- All three schemas (receipt, attestation, memory) are present with non-empty
  field lists derived from the real dataclasses/models.
- `--json` output has a stable shape and a top-level `spec_version`.
- `--schema` filters to a single schema; invalid values error cleanly.
- No collision with the pre-existing `onmc spec` command group.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.command_registry import detect_duplicate_commands
from oh_no_my_claudecode.formats.formats import (
    SCHEMA_NAMES,
    SPEC_DOCUMENT_VERSION,
    build_spec,
    render_text,
    to_json_dict,
)


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Pure core — build_spec
# ---------------------------------------------------------------------------


def test_spec_version_present() -> None:
    """The top-level spec_version constant is present and matches the document."""
    doc = build_spec()
    assert doc.spec_version == SPEC_DOCUMENT_VERSION
    assert doc.spec_version


def test_all_three_schemas_present_by_default() -> None:
    """build_spec() with no args includes receipt, attestation, and memory."""
    doc = build_spec()
    names = [s.name for s in doc.schemas]
    assert names == list(SCHEMA_NAMES)
    assert set(names) == {"receipt", "attestation", "memory"}


def test_each_schema_has_nonempty_fields() -> None:
    """Every schema's field list is derived from a real type and is non-empty."""
    doc = build_spec()
    for schema in doc.schemas:
        assert schema.fields, f"{schema.name} has no fields"
        for f in schema.fields:
            assert f.name
            assert f.type


def test_receipt_schema_fields_match_runreceipt_dataclass() -> None:
    """The receipt schema's field names match RunReceipt's real dataclass fields."""
    import dataclasses

    from oh_no_my_claudecode.loop.receipt import RunReceipt

    doc = build_spec(("receipt",))
    schema = doc.get("receipt")
    assert schema is not None

    expected = [f.name for f in dataclasses.fields(RunReceipt)]
    actual = [f.name for f in schema.fields]
    assert actual == expected


def test_attestation_schema_fields_match_attestation_dataclass() -> None:
    """The attestation schema's field names match Attestation's real dataclass fields."""
    import dataclasses

    from oh_no_my_claudecode.attest.attest import Attestation

    doc = build_spec(("attestation",))
    schema = doc.get("attestation")
    assert schema is not None

    expected = [f.name for f in dataclasses.fields(Attestation)]
    actual = [f.name for f in schema.fields]
    assert actual == expected


def test_memory_schema_includes_manifest_and_memory_entry_fields() -> None:
    """The memory schema covers both SyncManifest and MemoryEntry fields."""
    doc = build_spec(("memory",))
    schema = doc.get("memory")
    assert schema is not None

    field_names = {f.name for f in schema.fields}
    # SyncManifest fields.
    assert {"version", "repo_root", "exported_at", "onmc_version", "counts"} <= field_names
    # MemoryEntry fields.
    assert {"id", "kind", "title", "summary", "source_type", "confidence"} <= field_names


def test_build_spec_is_deterministic() -> None:
    """Two calls with the same args produce an identical JSON-safe document."""
    doc1 = to_json_dict(build_spec())
    doc2 = to_json_dict(build_spec())
    assert doc1 == doc2


def test_get_returns_none_for_unknown_schema() -> None:
    """SpecDocument.get returns None (never raises) for a name not included."""
    doc = build_spec(("receipt",))
    assert doc.get("memory") is None
    assert doc.get("receipt") is not None


# ---------------------------------------------------------------------------
# JSON shape stability
# ---------------------------------------------------------------------------


def test_json_dict_has_stable_top_level_shape() -> None:
    """to_json_dict's top-level keys are exactly spec_version + schemas."""
    d = to_json_dict(build_spec())
    assert set(d.keys()) == {"spec_version", "schemas"}
    assert isinstance(d["schemas"], list)
    for entry in d["schemas"]:
        assert set(entry.keys()) == {
            "name",
            "title",
            "version",
            "source",
            "path_hint",
            "description",
            "fields",
            "example",
        }
        for field_entry in entry["fields"]:
            assert set(field_entry.keys()) == {"name", "type", "required", "meaning"}


def test_json_dict_is_json_serialisable() -> None:
    """The whole document round-trips through json.dumps without error."""
    d = to_json_dict(build_spec())
    encoded = json.dumps(d)
    decoded = json.loads(encoded)
    assert decoded["spec_version"] == SPEC_DOCUMENT_VERSION


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------


def test_render_text_mentions_every_schema_title() -> None:
    """The plain-text rendering includes every schema's title."""
    doc = build_spec()
    text = render_text(doc)
    for schema in doc.schemas:
        assert schema.title in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_formats_json_exits_zero_and_parses() -> None:
    """`onmc formats --json` exits 0 and prints valid, complete JSON."""
    runner = _runner()
    result = runner.invoke(app, ["formats", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["spec_version"] == SPEC_DOCUMENT_VERSION
    assert {s["name"] for s in payload["schemas"]} == {"receipt", "attestation", "memory"}


def test_cli_formats_schema_filter_returns_one_schema() -> None:
    """`onmc formats --json --schema attestation` returns only that schema."""
    runner = _runner()
    result = runner.invoke(app, ["formats", "--json", "--schema", "attestation"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [s["name"] for s in payload["schemas"]] == ["attestation"]


def test_cli_formats_invalid_schema_errors_cleanly() -> None:
    """An unrecognised --schema value exits 1 with a clear message, not a traceback."""
    runner = _runner()
    result = runner.invoke(app, ["formats", "--schema", "bogus"])

    assert result.exit_code == 1
    assert "bogus" in (result.output + str(result.exception or ""))


def test_cli_formats_text_mode_exits_zero() -> None:
    """`onmc formats` with no flags exits 0 and prints the plain-text report."""
    runner = _runner()
    result = runner.invoke(app, ["formats"])

    assert result.exit_code == 0, result.output
    assert "spec_version=" in result.output


# ---------------------------------------------------------------------------
# No collision with the pre-existing `onmc spec` command group
# ---------------------------------------------------------------------------


def test_formats_does_not_collide_with_existing_commands() -> None:
    """Registering `formats` introduced no duplicate top-level command names."""
    assert detect_duplicate_commands(app) == []
