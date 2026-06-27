"""Deterministic detection and rendering of repo coding conventions.

The detector parses ``pyproject.toml`` (``[tool.ruff]`` and ``[tool.mypy]``)
with the stdlib :mod:`tomllib` parser and attaches a fixed list of repo norms.
It never touches the network or an LLM, and it is graceful when a config key is
absent — missing values simply fall back to ``None``/``False``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONVENTIONS_FILE_NAME = "conventions.md"

# Repo norms that are not encoded in any config file but every agent must honour.
# Kept as a module-level constant so the rendered output is deterministic.
_FIXED_NORMS: tuple[str, ...] = (
    "tests offline + deterministic; never assert Rich --help text; exercise flags instead",
    "no schema migration unless forced",
    "Conventional Commits lowercase subject",
)


@dataclass
class Conventions:
    """A repository's captured coding conventions.

    Attributes
    ----------
    line_length:
        The configured ``[tool.ruff] line-length`` (``None`` when absent).
    ruff_rule_codes:
        The selected ``[tool.ruff.lint] select`` rule-code prefixes (e.g.
        ``["E", "F", "I"]``).  Empty when no selection is configured.
    target_version:
        The ``[tool.ruff] target-version`` string (e.g. ``"py311"``), or
        ``None`` when absent.
    type_checked:
        ``True`` when ``[tool.mypy] strict`` is enabled.
    norms:
        Fixed, repo-wide norms that agents must follow.  Defaults to the
        canonical list and is rarely overridden outside tests.
    """

    line_length: int | None = None
    ruff_rule_codes: list[str] = field(default_factory=list)
    target_version: str | None = None
    type_checked: bool = False
    norms: list[str] = field(default_factory=lambda: list(_FIXED_NORMS))


def conventions_path(repo_root: Path) -> Path:
    """Return the path to ``<repo_root>/.onmc/conventions.md``."""
    return repo_root / ".onmc" / CONVENTIONS_FILE_NAME


def _load_pyproject(repo_root: Path) -> dict[str, object]:
    """Parse ``pyproject.toml`` if present; return an empty mapping otherwise.

    Graceful by design: a missing or unparseable file yields ``{}`` so callers
    fall back to defaults instead of raising.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        with pyproject.open("rb") as handle:
            return tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _as_table(value: object) -> dict[str, object]:
    """Return *value* as a dict when it is one, else an empty dict."""
    return value if isinstance(value, dict) else {}


def detect_conventions(repo_root: Path) -> Conventions:
    """Detect coding conventions for the repository rooted at *repo_root*.

    Reads ``[tool.ruff]`` (``line-length``, ``target-version``) and
    ``[tool.ruff.lint]`` (``select``) plus ``[tool.mypy]`` (``strict``) from
    ``pyproject.toml``.  Each key is optional; absent keys leave the
    corresponding field at its default.  Always returns a valid
    :class:`Conventions` with the fixed norms attached.
    """
    data = _load_pyproject(repo_root)
    tool = _as_table(data.get("tool"))
    ruff = _as_table(tool.get("ruff"))
    ruff_lint = _as_table(ruff.get("lint"))
    mypy = _as_table(tool.get("mypy"))

    raw_line_length = ruff.get("line-length")
    line_length = raw_line_length if isinstance(raw_line_length, int) else None

    raw_target = ruff.get("target-version")
    target_version = raw_target if isinstance(raw_target, str) else None

    raw_select = ruff_lint.get("select")
    if isinstance(raw_select, list):
        ruff_rule_codes = [code for code in raw_select if isinstance(code, str)]
    else:
        ruff_rule_codes = []

    type_checked = mypy.get("strict") is True

    return Conventions(
        line_length=line_length,
        ruff_rule_codes=ruff_rule_codes,
        target_version=target_version,
        type_checked=type_checked,
        norms=list(_FIXED_NORMS),
    )


def render_conventions_markdown(conv: Conventions) -> str:
    """Render *conv* as a clean ``.onmc/conventions.md`` body.

    Deterministic: the same :class:`Conventions` always yields byte-identical
    markdown so the file is stable across idempotent re-captures.
    """
    line_length = str(conv.line_length) if conv.line_length is not None else "unset"
    target_version = conv.target_version or "unset"
    rule_codes = ", ".join(conv.ruff_rule_codes) if conv.ruff_rule_codes else "unset"
    type_checked = "yes (mypy --strict)" if conv.type_checked else "no"

    lines: list[str] = [
        "# Coding conventions",
        "",
        "Captured by `onmc conventions capture`. Spawned agents should read this",
        "file (or `onmc conventions show`) and follow it — do not re-derive these.",
        "",
        "## Tooling",
        "",
        f"- Line length: {line_length}",
        f"- Target Python version: {target_version}",
        f"- Ruff rule codes: {rule_codes}",
        f"- Type checked: {type_checked}",
        "",
        "## Repo norms",
        "",
    ]
    lines.extend(f"- {norm}" for norm in conv.norms)
    lines.append("")
    return "\n".join(lines)
