"""Deterministic playbook compiler — no LLM required.

Groups related high-signal memories into candidate playbooks by clustering on
shared tags and top-level directory prefixes.  Each playbook records provenance
(source memory ids + titles) so it can be audited and regenerated.

Optionally a best-effort LLM polish pass can sharpen the generated title and
trigger sentence when ``provider`` is supplied.  Errors in that pass are always
swallowed so the deterministic output is never blocked.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from oh_no_my_claudecode.models.memory import MemoryKind
from oh_no_my_claudecode.models.playbook import Playbook, PlaybookProvenanceItem
from oh_no_my_claudecode.utils.text import stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now

if TYPE_CHECKING:
    from pathlib import Path

    from oh_no_my_claudecode.llm.base import BaseLLMProvider
    from oh_no_my_claudecode.models.memory import MemoryEntry

# ── Constants ──────────────────────────────────────────────────────────────────

# Memory kinds that contribute actionable content to a playbook.
_SIGNAL_KINDS = {
    MemoryKind.DECISION,
    MemoryKind.INVARIANT,
    MemoryKind.VALIDATION_RULE,
    MemoryKind.FAILED_APPROACH,
    MemoryKind.DESIGN_CONFLICT,
    MemoryKind.GOTCHA,
}

# Minimum combined confidence+feedback score to be considered high-signal.
_MIN_SCORE = 0.5

# Maximum steps per playbook (token guard).
_MAX_STEPS = 10

# Minimum memories in a cluster to emit a playbook.
_MIN_CLUSTER_SIZE = 2

# Maximum playbooks returned.
_MAX_PLAYBOOKS = 20

# Step prefixes by kind — invariants become "always" rules, failed approaches
# become "avoid" entries, validation rules become "verify" entries.
_KIND_PREFIX: dict[MemoryKind, str] = {
    MemoryKind.INVARIANT: "Always",
    MemoryKind.FAILED_APPROACH: "Avoid",
    MemoryKind.VALIDATION_RULE: "Verify",
    MemoryKind.DECISION: "Apply",
    MemoryKind.DESIGN_CONFLICT: "Resolve",
    MemoryKind.GOTCHA: "Watch out for",
}


# ── Public entry point ─────────────────────────────────────────────────────────


def compile_playbooks(
    memories: list[MemoryEntry],
    *,
    provider: BaseLLMProvider | None = None,
    no_llm: bool = False,
    log_path: Path | None = None,
) -> list[Playbook]:
    """Synthesize playbooks from *memories*.

    1. Filter to high-signal memories.
    2. Cluster by shared tags and top-level source directory.
    3. For each cluster with >= _MIN_CLUSTER_SIZE members, build a Playbook.
    4. Optional LLM polish pass on title/trigger (best-effort, never raises).
    """
    candidates = _filter_high_signal(memories)
    clusters = _cluster(candidates)

    playbooks: list[Playbook] = []
    seen_ids: set[str] = set()
    for cluster_key, cluster_members in sorted(clusters.items()):
        if len(cluster_members) < _MIN_CLUSTER_SIZE:
            continue
        playbook = _build_playbook(cluster_key, cluster_members)
        if playbook.id in seen_ids:
            continue
        seen_ids.add(playbook.id)
        playbooks.append(playbook)

    # Sort by confidence (descending), then title (ascending) for determinism.
    playbooks.sort(key=lambda pb: (-pb.confidence, pb.title))
    playbooks = playbooks[:_MAX_PLAYBOOKS]

    if provider is not None and not no_llm and log_path is not None:
        playbooks = _polish_with_llm(playbooks, provider, log_path)

    return playbooks


# ── Internal helpers ───────────────────────────────────────────────────────────


def _signal_score(memory: MemoryEntry) -> float:
    """Combined relevance score; higher = more actionable."""
    return memory.confidence + memory.feedback_score * 0.3


def _filter_high_signal(memories: list[MemoryEntry]) -> list[MemoryEntry]:
    """Keep only actionable, sufficiently confident memories."""
    out: list[MemoryEntry] = []
    for memory in memories:
        if memory.kind not in _SIGNAL_KINDS:
            continue
        if _signal_score(memory) < _MIN_SCORE:
            continue
        if memory.feedback_score < -0.4:
            # Explicitly rejected — skip.
            continue
        out.append(memory)
    return out


def _top_level_dir(source_ref: str) -> str:
    """Extract the top-level directory from a source_ref like 'src/foo/bar.py'.

    Returns '' when the ref has no directory component (e.g. 'README.md').
    Handles pipe-separated source_refs by taking the first segment.
    """
    ref = source_ref.split("|")[0].strip()
    parts = ref.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0]:
        return parts[0]
    return ""


def _cluster(memories: list[MemoryEntry]) -> dict[str, list[MemoryEntry]]:
    """Assign each memory to one or more cluster keys.

    Cluster keys are either:
    - Shared tags (each tag produces a key like ``tag:testing``).
    - Top-level source directory (e.g. ``dir:src``).

    A memory can appear in multiple clusters; the _build_playbook step
    deduplicates by step text.
    """
    clusters: dict[str, list[MemoryEntry]] = defaultdict(list)
    for memory in memories:
        placed = False
        for tag in memory.tags:
            normalized = re.sub(r"\s+", "-", tag.strip().lower())
            if normalized:
                clusters[f"tag:{normalized}"].append(memory)
                placed = True
        top = _top_level_dir(memory.source_ref)
        if top:
            clusters[f"dir:{top}"].append(memory)
            placed = True
        if not placed:
            clusters["misc"].append(memory)
    return dict(clusters)


def _build_playbook(cluster_key: str, members: list[MemoryEntry]) -> Playbook:
    """Construct a Playbook from a cluster of memories."""
    # Deduplicate members by id while preserving order.
    seen_ids: set[str] = set()
    unique_members: list[MemoryEntry] = []
    for m in members:
        if m.id not in seen_ids:
            seen_ids.add(m.id)
            unique_members.append(m)
    members = unique_members

    # Title: derived from cluster key.
    if cluster_key.startswith("tag:"):
        label = cluster_key[4:].replace("-", " ").title()
        trigger = f"When working on {label.lower()} concerns."
    elif cluster_key.startswith("dir:"):
        label = cluster_key[4:].replace("-", " ").replace("_", " ").title()
        trigger = f"When editing files under the {label} area."
    else:
        label = "General"
        trigger = "When no specific area or tag applies."

    title = f"{label} Playbook"

    # Steps: derived from member memories, prefixed by kind.
    steps: list[str] = []
    seen_step_texts: set[str] = set()
    # Sort: signal kinds first, then by score desc.
    sorted_members = sorted(
        members,
        key=lambda m: (
            0 if m.kind in {MemoryKind.INVARIANT, MemoryKind.VALIDATION_RULE} else 1,
            -_signal_score(m),
        ),
    )
    for memory in sorted_members:
        prefix = _KIND_PREFIX.get(memory.kind, "Note")
        step_text = f"{prefix}: {memory.summary.rstrip('.')}"
        # Deduplicate by normalized text.
        norm = " ".join(tokenize(step_text))
        if norm and norm not in seen_step_texts:
            seen_step_texts.add(norm)
            steps.append(step_text)
        if len(steps) >= _MAX_STEPS:
            break

    # Provenance.
    grounded_in = [
        PlaybookProvenanceItem(
            memory_id=m.id,
            title=m.title,
            kind=m.kind.value,
        )
        for m in members
    ]

    # Tags: union of all member tags.
    all_tags: list[str] = []
    seen_tags: set[str] = set()
    for m in members:
        for tag in m.tags:
            if tag and tag not in seen_tags:
                seen_tags.add(tag)
                all_tags.append(tag)

    # Confidence: mean of member scores, clamped to [0, 1].
    scores = [min(1.0, max(0.0, _signal_score(m))) for m in members]
    confidence = round(sum(scores) / len(scores), 4) if scores else 0.5

    # Stable ID derived from cluster key + member ids (sorted for determinism).
    member_ids_str = ",".join(sorted(m.id for m in members))
    playbook_id = stable_id(cluster_key, member_ids_str, prefix="pb")

    return Playbook(
        id=playbook_id,
        title=title,
        trigger=trigger,
        steps=steps,
        grounded_in=grounded_in,
        tags=all_tags,
        confidence=confidence,
        created_at=utc_now(),
    )


def _polish_with_llm(
    playbooks: list[Playbook],
    provider: BaseLLMProvider,
    log_path: Path,
) -> list[Playbook]:
    """Best-effort LLM polish: sharpen title and trigger for each playbook.

    Errors are always swallowed — the caller gets the deterministic output
    on any failure.
    """
    from oh_no_my_claudecode.llm import MarkdownEnvelope, generate_structured_logged
    from oh_no_my_claudecode.models.llm import LLMGenerationRequest

    polished: list[Playbook] = []
    for pb in playbooks:
        try:
            steps_text = "\n".join(f"- {s}" for s in pb.steps[:5])
            prompt = (
                "You are given a draft playbook title, trigger, and steps. "
                "Return JSON with keys 'title' and 'trigger' only — do NOT change the steps. "
                "Make the title concise (max 8 words) and the trigger a single clear sentence.\n\n"
                f"Draft title: {pb.title}\n"
                f"Draft trigger: {pb.trigger}\n"
                f"Steps (sample):\n{steps_text}"
            )
            envelope = generate_structured_logged(
                provider,
                LLMGenerationRequest(
                    system_prompt="Return valid JSON with keys 'title' and 'trigger'.",
                    prompt=prompt,
                    temperature=0.0,
                    max_tokens=120,
                ),
                MarkdownEnvelope,
                log_path=log_path,
                operation="playbook.polish",
            )
            raw = envelope.markdown.strip()
            # Try to extract JSON from the response.
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                new_title = str(data.get("title", pb.title)).strip()
                new_trigger = str(data.get("trigger", pb.trigger)).strip()
                if new_title and new_trigger:
                    polished.append(
                        pb.model_copy(update={"title": new_title, "trigger": new_trigger})
                    )
                    continue
        except Exception:  # noqa: BLE001, S110 — polish is best-effort; fall back to draft
            pass
        polished.append(pb)
    return polished
