"""Skills — named, reusable, self-improving units of know-how."""

from oh_no_my_claudecode.skill.export import export_skills, render_skill_md, skill_slug
from oh_no_my_claudecode.skill.promoter import (
    auto_promote_recurring,
    promote_playbook_to_skill,
    rank_skills,
)

__all__ = [
    "auto_promote_recurring",
    "export_skills",
    "promote_playbook_to_skill",
    "rank_skills",
    "render_skill_md",
    "skill_slug",
]
