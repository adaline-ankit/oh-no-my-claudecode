"""Pure introspection of onmc's portable on-disk schemas.

onmc writes three durable, portable artifacts that other tools/agents can read
without going through onmc itself:

- The run **receipt** (:class:`~oh_no_my_claudecode.loop.receipt.RunReceipt`) —
  a tamper-evident record of one ``onmc loop``/``onmc swarm`` run, written to
  ``.agent-memory/receipts/*.json``.
- The **attestation** (:class:`~oh_no_my_claudecode.attest.attest.Attestation`)
  — a portable, optionally-signed envelope distilled from a receipt, shaped for
  ERC-8004-style agent-economy reputation flows.
- The exported **memory** record
  (:class:`~oh_no_my_claudecode.sync.schema.ExportedMemoryRecord`, wrapping
  :class:`~oh_no_my_claudecode.models.memory.MemoryEntry`) and the **federation
  manifest** (:class:`~oh_no_my_claudecode.sync.schema.SyncManifest`) written to
  ``.agent-memory/`` by ``onmc sync`` for cross-repo federation.

This module never hand-copies a field list. Every schema is derived by
importing the real dataclass/pydantic model and introspecting its fields
(:func:`dataclasses.fields` or ``model_fields``), so the emitted spec can never
silently drift from the code that actually writes these files. Only the
one-line human meaning per field, and the illustrative example values, are
hand-authored — everything else (names, types, required-ness) is read live
from the source of truth.

Pure and deterministic: no filesystem or network access, no clock reads. Field
order within each schema matches declaration order in the source dataclass.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, get_args, get_origin

#: Version of *this* spec document's shape (top-level ``spec_version`` key of
#: the ``--json`` output and the schemas it enumerates). Bump when a
#: backward-incompatible change is made to the spec document's own structure
#: (not when an underlying schema merely gains a field — that is visible via
#: each schema's own ``version``).
SPEC_DOCUMENT_VERSION = "1"

#: The three schema names ``--schema`` accepts, in the order they render.
SCHEMA_NAMES: tuple[str, ...] = ("receipt", "attestation", "memory")


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of a portable schema.

    Attributes
    ----------
    name:
        The field name exactly as it appears in the JSON on disk.
    type:
        A human-readable type string (e.g. ``"str | None"``, ``"list[str]"``).
    required:
        ``True`` iff the field has no default value / is not Optional-with-a-
        default — i.e. a conformant writer must always emit it.
    meaning:
        One-line, hand-authored description of what the field means.
    """

    name: str
    type: str
    required: bool
    meaning: str


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    """A single portable schema: its identity, fields, and one example.

    Attributes
    ----------
    name:
        Short machine key (``"receipt"``, ``"attestation"``, ``"memory"``).
    title:
        Human-readable title.
    version:
        The schema's own version marker as written on disk today (e.g. the
        receipt's ``schema_version`` value, or the manifest's ``version``).
        ``None`` when the underlying format carries no explicit version field
        (the value is still stable — just not self-describing on disk).
    source:
        Fully-qualified dotted path to the Python type this schema was
        introspected from.
    path_hint:
        Where a conformant writer places files of this shape, relative to a
        repo root.
    description:
        One-paragraph summary of the schema's purpose.
    fields:
        Ordered list of :class:`FieldSpec`, in declaration order.
    example:
        A minimal, illustrative JSON-safe example value (hand-authored, for
        readability — not derived from any real run).
    """

    name: str
    title: str
    version: str | None
    source: str
    path_hint: str
    description: str
    fields: tuple[FieldSpec, ...]
    example: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SpecDocument:
    """The full portable-schema spec: every :class:`SchemaSpec`, versioned.

    Attributes
    ----------
    spec_version:
        Version of this spec document's own shape — see
        :data:`SPEC_DOCUMENT_VERSION`.
    schemas:
        Ordered tuple of :class:`SchemaSpec`, in :data:`SCHEMA_NAMES` order.
    """

    spec_version: str
    schemas: tuple[SchemaSpec, ...]

    def get(self, name: str) -> SchemaSpec | None:
        """Return the schema named *name*, or ``None`` if absent."""
        for schema in self.schemas:
            if schema.name == name:
                return schema
        return None


# ---------------------------------------------------------------------------
# Type-string rendering (uniform across dataclasses and pydantic models)
# ---------------------------------------------------------------------------


def _type_name(annotation: Any) -> str:
    """Render *annotation* as a short, human-readable type string.

    Handles three shapes uniformly:
    - A ``str`` already (dataclasses defined with
      ``from __future__ import annotations`` report ``field.type`` as the
      literal source string) — returned as-is.
    - A real ``type`` object (as pydantic's ``model_fields[...].annotation``
      gives) — rendered via its ``__name__`` (falling back to ``str()``).
    - A ``typing`` generic (``list[str]``, ``X | None``,
      ``Optional[Literal[...]]``) — rendered by recursing over
      ``get_origin``/``get_args``.
    """
    if isinstance(annotation, str):
        return annotation
    if annotation is type(None):
        return "None"
    origin = get_origin(annotation)
    if origin is None:
        name = getattr(annotation, "__name__", None)
        return name if name is not None else str(annotation)
    args = get_args(annotation)
    if origin is type(int | str):  # typing.UnionType (X | Y) at runtime
        return " | ".join(_type_name(a) for a in args)
    origin_name = getattr(origin, "__name__", str(origin))
    if origin_name == "Union":
        return " | ".join(_type_name(a) for a in args)
    if origin_name == "Literal":
        return "Literal[" + ", ".join(repr(a) for a in args) + "]"
    if args:
        return f"{origin_name}[{', '.join(_type_name(a) for a in args)}]"
    return origin_name


def _dataclass_fields(cls: type) -> list[FieldSpec]:
    """Introspect a stdlib dataclass into ordered :class:`FieldSpec` values.

    ``required`` is ``False`` when the field declares a default or a
    default_factory; meanings are looked up from a per-class hand-authored
    table (never fabricated — falls back to an empty string).
    """
    meanings = _FIELD_MEANINGS.get(cls, {})
    specs: list[FieldSpec] = []
    for f in dataclasses.fields(cls):
        has_default = f.default is not dataclasses.MISSING
        has_factory = f.default_factory is not dataclasses.MISSING
        specs.append(
            FieldSpec(
                name=f.name,
                type=_type_name(f.type),
                required=not (has_default or has_factory),
                meaning=meanings.get(f.name, ""),
            )
        )
    return specs


def _pydantic_fields(model: Any) -> list[FieldSpec]:
    """Introspect a pydantic ``BaseModel`` subclass into :class:`FieldSpec` values."""
    meanings = _FIELD_MEANINGS.get(model, {})
    specs: list[FieldSpec] = []
    for name, info in model.model_fields.items():
        specs.append(
            FieldSpec(
                name=name,
                type=_type_name(info.annotation),
                required=info.is_required(),
                meaning=meanings.get(name, ""),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Hand-authored one-line field meanings (structure itself is never hand-authored)
# ---------------------------------------------------------------------------
#
# Keyed by the live class object (not a string) so a rename of the underlying
# field is immediately visible as a meaning-lookup miss (empty string) rather
# than silently pointing at a stale name.

_FIELD_MEANINGS: dict[type, dict[str, str]] = {}


def _register_meanings(cls: type, meanings: dict[str, str]) -> None:
    _FIELD_MEANINGS[cls] = meanings


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------


def _build_receipt_schema() -> SchemaSpec:
    from oh_no_my_claudecode.loop.receipt import RunReceipt

    _register_meanings(
        RunReceipt,
        {
            "schema_version": "Monotonic integer string for forward-compatible parsing.",
            "goal": "The loop goal text, truncated to 500 chars.",
            "agent": 'Agent selector used for the run (e.g. "claude", "codex", "dry-run").',
            "model": "Model name when the adapter surfaced one; None otherwise.",
            "verified": "True iff the loop converged AND the final iteration's verify passed.",
            "stop_reason": "Why the loop stopped (from LoopResult.stop_reason).",
            "iterations": "Number of iterations completed.",
            "tokens_used": "Total tokens consumed across all iterations.",
            "cost_usd": (
                "Total USD cost when reported by the adapter; None when not "
                "reported (never fabricated)."
            ),
            "wall_seconds": "Wall-clock seconds elapsed for the run.",
            "verifier_command": "The shell command used to verify each iteration.",
            "verifier_final_exit": (
                "Exit code of the final verify invocation; None when no iterations ran."
            ),
            "git_tree_sha": (
                "SHA of the current git tree (HEAD^{tree}); None when git is unavailable."
            ),
            "diff_sha": "SHA-256 of uncommitted `git diff` output; None when git is unavailable.",
            "loop_spec_sha": "SHA-256 of `goal + verify_command`; identifies this run's inputs.",
            "output_digest": (
                "SHA-256 of concatenated (truncated) verify outputs across iterations."
            ),
            "onmc_version": "Installed oh-no-my-claudecode version string (or \"unknown\").",
            "started_at": "ISO-8601 UTC timestamp when the run began; may be None.",
            "ended_at": "ISO-8601 UTC timestamp when the run ended; may be None.",
            "iteration_hashes": "Per-iteration SHA-256 hash chain links (64-char hex each).",
            "receipt_hash": (
                "SHA-256 hash chain head — changes if any iteration data changes "
                "(tamper evidence)."
            ),
            "model_version": (
                "Resolved model/version string passed to the agent adapter; never fabricated."
            ),
            "prompt_hash": (
                "SHA-256 of the run's goal text — identifies the exact prompt "
                "that seeded the run."
            ),
            "tool_defs_hash": (
                "SHA-256 of `verify_command:agent` — captures the tools surface of the run."
            ),
            "config_hash": "SHA-256 of the reproducibility-relevant LoopConfig knobs.",
            "python_version": '`sys.version_info` as "major.minor" (e.g. "3.12").',
            "platform": '`sys.platform` value (e.g. "darwin", "linux").',
        },
    )

    example = {
        "schema_version": "2",
        "goal": "Fix the cache invalidation regression",
        "agent": "claude",
        "model": "claude-opus-4-5",
        "verified": True,
        "stop_reason": "converged",
        "iterations": 3,
        "tokens_used": 48213,
        "cost_usd": 1.42,
        "wall_seconds": 187.5,
        "verifier_command": "pytest -q",
        "verifier_final_exit": 0,
        "git_tree_sha": "a1b2c3d4e5f6...",
        "diff_sha": "9f8e7d6c5b4a...",
        "loop_spec_sha": "1234abcd5678...",
        "output_digest": "deadbeefcafe...",
        "onmc_version": "0.77.0",
        "started_at": "2026-07-05T10:00:00+00:00",
        "ended_at": "2026-07-05T10:03:07+00:00",
        "iteration_hashes": ["aa11...", "bb22...", "cc33..."],
        "receipt_hash": "cc33...",
        "model_version": "claude-opus-4-5",
        "prompt_hash": "5566...",
        "tool_defs_hash": "7788...",
        "config_hash": "99aa...",
        "python_version": "3.12",
        "platform": "darwin",
    }

    return SchemaSpec(
        name="receipt",
        title="Run Receipt",
        version="2",
        source="oh_no_my_claudecode.loop.receipt.RunReceipt",
        path_hint=".agent-memory/receipts/run-<spec8>-<hash8>.json",
        description=(
            "Tamper-evident record of one `onmc loop` / `onmc swarm` run: a "
            "SHA-256 hash chain over every iteration, git tree/diff SHAs so "
            "external auditors can reproduce the exact repo state produced, the "
            "verifier command and exit code, and token/cost/wall-time "
            "accounting. Written once per completed run; never mutated."
        ),
        fields=tuple(_dataclass_fields(RunReceipt)),
        example=example,
    )


def _build_attestation_schema() -> SchemaSpec:
    from oh_no_my_claudecode.attest.attest import Attestation

    _register_meanings(
        Attestation,
        {
            "subject": 'Agent identity the work is credited to (falls back to "onmc").',
            "claim": (
                "The minimal verifiable claim distilled from a receipt: subject, "
                "goal, git_tree_sha, diff_sha, receipt_hash, verified, ts."
            ),
            "alg": '"HMAC-SHA256" when signed with a shared secret, "SHA256" when digest-only.',
            "signature": "Hex digest — a keyed HMAC (signed) or a bare SHA256 (unsigned).",
            "signed": (
                "True iff a shared secret produced an authenticity signature "
                "(vs. an integrity-only digest)."
            ),
        },
    )

    example = {
        "subject": "claude",
        "claim": {
            "subject": "claude",
            "goal": "Fix the cache invalidation regression",
            "git_tree_sha": "a1b2c3d4e5f6...",
            "diff_sha": "9f8e7d6c5b4a...",
            "receipt_hash": "cc33...",
            "verified": True,
            "ts": "2026-07-05T10:03:07+00:00",
        },
        "alg": "HMAC-SHA256",
        "signature": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d",
        "signed": True,
    }

    return SchemaSpec(
        name="attestation",
        title="Attestation",
        version=None,
        source="oh_no_my_claudecode.attest.attest.Attestation",
        path_hint="printed by `onmc attest sign`; not written to a fixed path by default",
        description=(
            "Portable, optionally-signed envelope distilled from a receipt via "
            "`canonical_claim` + `sign_claim`, shaped to slot into ERC-8004-style "
            "agent-economy identity/reputation/validation flows. A third party "
            "can verify it (`verify_attestation`) without trusting onmc, using "
            "constant-time HMAC comparison. Unsigned attestations (no shared "
            "secret) are integrity-only, not authenticity proofs — `signed` "
            "makes the distinction explicit rather than implying more trust "
            "than the data supports."
        ),
        fields=tuple(_dataclass_fields(Attestation)),
        example=example,
    )


def _build_memory_schema() -> SchemaSpec:
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.sync.schema import ExportedMemoryRecord, SyncManifest

    _register_meanings(
        MemoryEntry,
        {
            "id": "Stable unique identifier for this memory.",
            "kind": (
                "Category of durable knowledge (e.g. decision, invariant, "
                "gotcha, failed_approach)."
            ),
            "title": "Short human-readable title.",
            "summary": "One- to two-sentence summary.",
            "details": "Full detail text.",
            "source_type": (
                "Where this memory was derived from (git, doc, code, manual, "
                "llm_extracted, ...)."
            ),
            "source_ref": "Reference into the source (e.g. a commit SHA, file path, or PR URL).",
            "tags": "Free-form tags for filtering/search.",
            "confidence": "Confidence score in [0.0, 1.0] that this memory is accurate.",
            "feedback_score": "Running score adjusted by user feedback on usefulness.",
            "created_at": "UTC timestamp when the memory was first recorded.",
            "updated_at": "UTC timestamp when the memory was last modified.",
            "staleness": (
                '"fresh" | "stale" | "orphaned" | "unanchored" — recency/anchoring '
                "label, or None if unassessed."
            ),
            "last_verified_at": (
                "UTC timestamp the memory was last confirmed still accurate; "
                "None if never re-verified."
            ),
        },
    )
    _register_meanings(
        SyncManifest,
        {
            "version": "Export format version (currently \"1\").",
            "repo_root": "Absolute path to the repo root this export was produced from.",
            "exported_at": "UTC timestamp the export was written.",
            "onmc_version": (
                "Installed oh-no-my-claudecode version string that produced this export."
            ),
            "counts": (
                "Per-record-type counts included in this export "
                "(memories, tasks, attempts, artifacts, skills)."
            ),
        },
    )
    _register_meanings(
        ExportedMemoryRecord,
        {
            "memory": (
                "The exported MemoryEntry itself (see the `memory` schema's own field table)."
            ),
        },
    )

    memory_fields = _pydantic_fields(MemoryEntry)
    manifest_fields = _pydantic_fields(SyncManifest)

    example = {
        "manifest": {
            "version": "1",
            "repo_root": "/Users/dev/my-repo",
            "exported_at": "2026-07-05T10:00:00Z",
            "onmc_version": "0.77.0",
            "counts": {"memories": 12, "tasks": 3, "attempts": 5, "artifacts": 2, "skills": 0},
        },
        "memory_record": {
            "memory": {
                "id": "mem_01hf...",
                "kind": "invariant",
                "title": "Never fabricate cost when unreported",
                "summary": "cost_usd is None when the adapter didn't report it — never estimated.",
                "details": "See ledger/accounting.py honesty constraints.",
                "source_type": "code",
                "source_ref": "src/oh_no_my_claudecode/ledger/accounting.py",
                "tags": ["ledger", "honesty"],
                "confidence": 0.95,
                "feedback_score": 0.0,
                "created_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-01T00:00:00Z",
                "staleness": "fresh",
                "last_verified_at": None,
            }
        },
    }

    return SchemaSpec(
        name="memory",
        title="Exported Memory Record + Federation Manifest",
        version="1",
        source=(
            "oh_no_my_claudecode.sync.schema.SyncManifest, "
            "oh_no_my_claudecode.sync.schema.ExportedMemoryRecord, "
            "oh_no_my_claudecode.models.memory.MemoryEntry"
        ),
        path_hint=".agent-memory/manifest.json, .agent-memory/memories/<kind>/<id>.json",
        description=(
            "The federation-portable export written by `onmc sync`: a top-level "
            "`manifest.json` (SyncManifest — format version, provenance, and "
            "record counts) plus one JSON file per memory "
            "(ExportedMemoryRecord wrapping a MemoryEntry). Other onmc repos "
            "read this shape directly (`onmc federation pull` / `onmc "
            "crossrepo recall`) without any RPC — the directory tree itself is "
            "the interop contract, and `onmc spec validate` conformance-checks "
            "it."
        ),
        fields=tuple(manifest_fields) + tuple(memory_fields),
        example=example,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_BUILDERS = {
    "receipt": _build_receipt_schema,
    "attestation": _build_attestation_schema,
    "memory": _build_memory_schema,
}


def build_spec(names: tuple[str, ...] = SCHEMA_NAMES) -> SpecDocument:
    """Build the :class:`SpecDocument` for *names* (default: all three).

    Pure and deterministic — every call with the same *names* (and the same
    installed onmc version) produces an identical document. Schemas render in
    :data:`SCHEMA_NAMES` order regardless of the order *names* is given in.

    Parameters
    ----------
    names:
        Which schemas to include. Unknown names are silently ignored (callers
        validate against :data:`SCHEMA_NAMES` before calling, e.g. the CLI).
    """
    ordered = [n for n in SCHEMA_NAMES if n in names]
    schemas = tuple(_BUILDERS[n]() for n in ordered)
    return SpecDocument(spec_version=SPEC_DOCUMENT_VERSION, schemas=schemas)


def to_json_dict(doc: SpecDocument) -> dict[str, Any]:
    """Render *doc* into a stable, machine-readable JSON-safe dict.

    Shape::

        {
          "spec_version": "1",
          "schemas": [
            {
              "name": ..., "title": ..., "version": ..., "source": ...,
              "path_hint": ..., "description": ...,
              "fields": [{"name", "type", "required", "meaning"}, ...],
              "example": {...}
            },
            ...
          ]
        }

    Key order and shape are stable across calls (dict insertion order in
    Python is preserved, and this function always inserts in the same order),
    so callers may treat this as a versioned wire format keyed off
    ``spec_version``.
    """
    return {
        "spec_version": doc.spec_version,
        "schemas": [
            {
                "name": schema.name,
                "title": schema.title,
                "version": schema.version,
                "source": schema.source,
                "path_hint": schema.path_hint,
                "description": schema.description,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type,
                        "required": f.required,
                        "meaning": f.meaning,
                    }
                    for f in schema.fields
                ],
                "example": schema.example,
            }
            for schema in doc.schemas
        ],
    }


def render_text(doc: SpecDocument) -> str:
    """Render *doc* as a human-readable plain-text report.

    Deterministic, no Rich dependency — safe to print directly or use as the
    Rich-unavailable fallback.
    """
    import json

    lines: list[str] = [
        f"onmc portable schema spec  (spec_version={doc.spec_version})",
        "",
    ]
    for schema in doc.schemas:
        version_str = f"  version={schema.version}" if schema.version else ""
        lines.append(f"== {schema.title} ({schema.name}){version_str} ==")
        lines.append(f"source: {schema.source}")
        lines.append(f"path:   {schema.path_hint}")
        lines.append("")
        lines.append(schema.description)
        lines.append("")
        lines.append("Fields:")
        for f in schema.fields:
            req = "required" if f.required else "optional"
            lines.append(f"  - {f.name}: {f.type} ({req})")
            if f.meaning:
                lines.append(f"      {f.meaning}")
        lines.append("")
        lines.append("Example:")
        lines.append(json.dumps(schema.example, indent=2, default=str))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "SCHEMA_NAMES",
    "SPEC_DOCUMENT_VERSION",
    "FieldSpec",
    "SchemaSpec",
    "SpecDocument",
    "build_spec",
    "render_text",
    "to_json_dict",
]
