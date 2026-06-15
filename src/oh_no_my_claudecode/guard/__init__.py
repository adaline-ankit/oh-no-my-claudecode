"""Guard module — surface recorded dead-ends so agents never repeat them."""

from __future__ import annotations

from oh_no_my_claudecode.guard.compiler import GuardEntry, GuardResult, compile_guard

__all__ = ["GuardEntry", "GuardResult", "compile_guard"]
