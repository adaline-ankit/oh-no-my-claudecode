from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from oh_no_my_claudecode.brief.compiler import compile_brief
from oh_no_my_claudecode.codegraph import build_codegraph, context_files
from oh_no_my_claudecode.conventions import detect_conventions
from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.models import ProjectConfig
from oh_no_my_claudecode.reuse import find_reuse
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten, unique_preserve

DEFAULT_BUDGET_CHARS = 6000


@dataclass(frozen=True, slots=True)
class ContextPack:
    goal: str
    budget_chars: int
    markdown: str
    files: list[str] = field(default_factory=list)
    reuse_hits: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    conventions: list[str] = field(default_factory=list)
    suggested_verify: str = ""
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["chars"] = len(self.markdown)
        return data


@dataclass(frozen=True, slots=True)
class _Section:
    title: str
    lines: list[str]

    def render(self) -> str:
        body = "\n".join(self.lines).rstrip()
        return f"## {self.title}\n\n{body}\n" if body else f"## {self.title}\n"


def compile_context_pack(
    repo_root: Path,
    config: ProjectConfig,
    storage: SQLiteStorage,
    goal: str,
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> ContextPack:
    """Build a compact, offline, deterministic context pack for an agent."""
    effective_budget = max(500, budget_chars)
    graph = build_codegraph(repo_root)
    selection = context_files(graph, goal, budget=8)
    reuse_hits = find_reuse(repo_root, goal, limit=5)
    guard = compile_guard(storage, goal, limit=5)
    conventions = detect_conventions(repo_root)
    brief = compile_brief(repo_root, config, storage, goal, provider=None)

    files = unique_preserve([*selection.files, *brief.files_to_inspect[:8]])
    dead_ends = [entry.title for entry in guard.entries]
    reuse_labels = [f"{hit.symbol} ({hit.file}:{hit.lineno})" for hit in reuse_hits]
    convention_lines = _convention_lines(conventions)
    verify = _suggest_verify(repo_root, files)

    sections = [
        _Section("Goal", [goal.strip()]),
        _Section(
            "Files",
            [f"- `{path}`" for path in files[:12]] or ["- No matching files found."],
        ),
        _Section(
            "Symbols",
            _symbol_lines(graph, files) or ["- No matching symbols found."],
        ),
        _Section(
            "Reuse",
            [
                f"- `{hit.signature}` in `{hit.file}:{hit.lineno}`"
                + (f" — {shorten(hit.doc_excerpt, max_length=100)}" if hit.doc_excerpt else "")
                for hit in reuse_hits
            ]
            or ["- No reuse hits found."],
        ),
        _Section("Conventions", [f"- {line}" for line in convention_lines]),
        _Section(
            "Known Dead Ends",
            [
                f"- {entry.title}: {shorten(entry.why_it_failed, max_length=140)}"
                for entry in guard.entries
            ]
            or ["- None recorded for this goal."],
        ),
        _Section(
            "Risks",
            [f"- {risk}" for risk in brief.risk_notes[:8]]
            or ["- No stored risks surfaced."],
        ),
        _Section("Verify", [f"`{verify}`"]),
        _Section(
            "Do Not Touch",
            [
                "- Stay inside files needed for this goal.",
                "- Do not rewrite generated lockfiles unless dependencies change.",
            ],
        ),
    ]
    markdown, truncated = _fit_markdown(sections, effective_budget)
    return ContextPack(
        goal=goal,
        budget_chars=effective_budget,
        markdown=markdown,
        files=files,
        reuse_hits=reuse_labels,
        dead_ends=dead_ends,
        conventions=convention_lines,
        suggested_verify=verify,
        truncated=truncated,
    )


def _symbol_lines(graph: object, files: list[str]) -> list[str]:
    lines: list[str] = []
    nodes = getattr(graph, "nodes", {})
    for path in files[:8]:
        node = nodes.get(path)
        if node is None:
            continue
        symbols = getattr(node, "symbols", [])[:6]
        if symbols:
            names = ", ".join(f"`{sym.name}`" for sym in symbols)
            lines.append(f"- `{path}`: {names}")
    return lines


def _convention_lines(conventions: object) -> list[str]:
    lines: list[str] = []
    line_length = getattr(conventions, "line_length", None)
    if line_length is not None:
        lines.append(f"line length {line_length}")
    target_version = getattr(conventions, "target_version", None)
    if target_version:
        lines.append(f"target Python {target_version}")
    if getattr(conventions, "type_checked", False):
        lines.append("mypy strict")
    lines.extend(getattr(conventions, "norms", [])[:5])
    return lines or ["follow existing style"]


def _suggest_verify(repo_root: Path, files: list[str]) -> str:
    base = (
        "uv run --python 3.12 python -m pytest"
        if (repo_root / "uv.lock").exists()
        else "python -m pytest"
    )
    tests = [path for path in files if path.startswith("tests/")]
    if tests:
        return f"{base} {' '.join(tests[:3])} -q"
    if (repo_root / "tests").exists():
        return f"{base} -q"
    return "run project test command"


def _fit_markdown(sections: list[_Section], budget: int) -> tuple[str, bool]:
    parts: list[str] = ["# ONMC Context Pack\n"]
    truncated = False
    for section in sections:
        rendered = section.render()
        candidate = "\n".join([*parts, rendered]).rstrip() + "\n"
        if len(candidate) <= budget:
            parts.append(rendered)
            continue
        truncated = True
        remaining = budget - len(("\n".join(parts)).rstrip() + "\n")
        if remaining > 80:
            trimmed = _trim_section(section, remaining)
            if trimmed:
                parts.append(trimmed)
        break
    markdown = ("\n".join(parts)).rstrip() + "\n"
    if len(markdown) > budget:
        suffix = "\n\n[truncated]\n"
        markdown = markdown[: max(0, budget - len(suffix))].rstrip() + suffix
    elif truncated:
        marker = "\n[truncated]\n"
        if len(markdown) + len(marker) <= budget:
            markdown = markdown.rstrip() + marker
    return markdown, truncated


def _trim_section(section: _Section, budget: int) -> str:
    lines: list[str] = []
    for line in section.lines:
        trial = _Section(section.title, [*lines, line, "- [truncated]"]).render()
        if len(trial) > budget:
            break
        lines.append(line)
    if not lines:
        return ""
    return _Section(section.title, [*lines, "- [truncated]"]).render()
