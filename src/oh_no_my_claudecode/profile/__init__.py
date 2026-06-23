"""User profile — derives a behavioral profile from accumulated user-scope memories.

The profile is computed from ~/.onmc/user.db memories using a purely deterministic
heuristic (no LLM calls, no network).  It is injected into every session boot digest
so every session starts knowing the user's coding style and known mistakes.
"""

from __future__ import annotations

from oh_no_my_claudecode.profile.compiler import UserProfile, compile_user_profile

__all__ = ["UserProfile", "compile_user_profile"]
