"""Write / list / remove onmc-generated Claude Code command files.

Scope is either the user's global command dir (``~/.claude/commands``) or a
project dir (``<repo>/.claude/commands``).  Only files carrying
:data:`~oh_no_my_claudecode.slash.generator.GENERATED_MARKER` are ever listed
or removed, so a user's hand-authored commands are never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.slash.generator import (
    GENERATED_MARKER,
    discover_slash_commands,
    render_command_file,
)


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an install/uninstall pass."""

    target_dir: Path
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def commands_dir(*, user: bool, repo_root: Path | None = None) -> Path:
    """Resolve the Claude Code commands dir for the chosen scope."""
    if user:
        return Path.home() / ".claude" / "commands"
    base = repo_root if repo_root is not None else Path.cwd()
    return base / ".claude" / "commands"


def _is_generated(path: Path) -> bool:
    try:
        return GENERATED_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def install_slash_commands(
    target_dir: Path,
    *,
    root_app: object | None = None,
    dry_run: bool = False,
) -> InstallResult:
    """Generate and write a command file per top-level onmc command.

    Overwrites onmc-generated files in place; refuses to clobber a file that
    exists WITHOUT the generated marker (a user's hand-authored command),
    recording it under ``skipped``.  ``dry_run`` reports without writing.
    """
    written: list[str] = []
    skipped: list[str] = []
    cmds = discover_slash_commands(root_app)  # type: ignore[arg-type]
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    for cmd in cmds:
        dest = target_dir / cmd.filename
        if dest.exists() and not _is_generated(dest):
            skipped.append(cmd.filename)
            continue
        if not dry_run:
            dest.write_text(render_command_file(cmd), encoding="utf-8")
        written.append(cmd.filename)
    return InstallResult(target_dir=target_dir, written=written, skipped=skipped)


def list_installed(target_dir: Path) -> list[str]:
    """Sorted filenames of onmc-generated command files in ``target_dir``."""
    if not target_dir.is_dir():
        return []
    return sorted(p.name for p in target_dir.glob("onmc-*.md") if _is_generated(p))


def uninstall_slash_commands(target_dir: Path, *, dry_run: bool = False) -> InstallResult:
    """Remove only onmc-generated command files; leave hand-authored ones."""
    removed: list[str] = []
    for name in list_installed(target_dir):
        if not dry_run:
            (target_dir / name).unlink(missing_ok=True)
        removed.append(name)
    return InstallResult(target_dir=target_dir, removed=removed)
