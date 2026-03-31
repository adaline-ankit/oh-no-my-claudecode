from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field, RootModel

from oh_no_my_claudecode.llm import generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    MemoryEntry,
    MemoryKind,
    SourceType,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now


class GitHubPRFinding(BaseModel):
    kind: str
    title: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_pr: int


class GitHubPRFindingList(RootModel[list[GitHubPRFinding]]):
    pass


def get_github_remote(repo_root: Path) -> tuple[str, str] | None:
    """Parse the origin remote URL into a GitHub owner/repo tuple."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
    if match is None:
        return None
    owner, repo = match.group(1), match.group(2)
    return owner, repo


def fetch_prs(owner: str, repo: str, limit: int = 50) -> list[dict[str, object]]:
    """Fetch recent closed pull requests from the public GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=closed&per_page={limit}"
    payload = _fetch_json(url)
    return payload if isinstance(payload, list) else []


def fetch_pr_reviews(owner: str, repo: str, pr_number: int) -> list[dict[str, object]]:
    """Fetch review metadata for a pull request from the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    payload = _fetch_json(url)
    return payload if isinstance(payload, list) else []


def extract_github_pr_findings(
    *,
    provider: BaseLLMProvider,
    prs: list[dict[str, object]],
    log_path: Path,
    batch_index: int,
) -> list[GitHubPRFinding]:
    """Extract repo-specific decisions and review findings from pull requests."""
    try:
        payload = generate_structured_logged(
            provider,
            LLMGenerationRequest(
                system_prompt="Return only valid JSON. Do not include markdown fences.",
                prompt=_pr_prompt(prs),
                temperature=0.0,
                max_tokens=1800,
            ),
            GitHubPRFindingList,
            log_path=log_path,
            operation=f"mine.github_prs.batch_{batch_index}",
        )
    except LLMProviderError:
        return []
    return [item for item in payload.root if item.confidence >= 0.75]


def mine_github_prs(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
    limit: int = 50,
    dry_run: bool = False,
) -> dict[str, object]:
    """Mine GitHub pull requests for reusable repo knowledge."""
    remote = get_github_remote(repo_root)
    if remote is None:
        return {
            "message": "No GitHub remote found. Skipping GitHub PR mining.",
            "attempts": [],
            "memories": [],
            "artifacts": [],
            "memory_source": SourceType.GITHUB_PR.value,
        }
    owner, repo = remote
    prs = fetch_prs(owner, repo, limit=limit)
    if not prs:
        return {
            "message": (
                f"Detected GitHub remote: {owner}/{repo}\n"
                "Fetching last 50 PRs... no PR data found.\n"
                "If this is a private repo, set GITHUB_TOKEN for authenticated access."
            ),
            "attempts": [],
            "memories": [],
            "artifacts": [],
            "memory_source": SourceType.GITHUB_PR.value,
        }
    if provider is None or log_path is None:
        return {
            "message": (
                f"Detected GitHub remote: {owner}/{repo}\n"
                "GitHub PR mining requires a configured LLM provider."
            ),
            "attempts": [],
            "memories": [],
            "artifacts": [],
            "memory_source": SourceType.GITHUB_PR.value,
        }

    reviewed_prs = [_attach_reviews(owner, repo, pr) for pr in prs]
    findings: list[GitHubPRFinding] = []
    for index, batch in enumerate(_batched(reviewed_prs, size=10), start=1):
        findings.extend(
            extract_github_pr_findings(
                provider=provider,
                prs=batch,
                log_path=log_path,
                batch_index=index,
            )
        )

    memories = [_finding_to_memory(finding) for finding in findings]
    if not dry_run and memories:
        storage.upsert_memories(memories)

    counts = _count_kinds(memories)
    message = (
        f"Detected GitHub remote: {owner}/{repo}\n"
        f"Fetching last {limit} PRs... ✓ ({len(prs)} closed PRs found)\n"
        "Extracting knowledge from PR descriptions and review comments...\n"
        f"✓ Extracted {counts['decision']} decisions, "
        f"{counts['failed_approach']} did_not_work, "
        f"{counts['invariant']} invariants\n\n"
        "If this is a private repo, set GITHUB_TOKEN for authenticated access."
    )
    return {
        "message": message,
        "attempts": [],
        "memories": memories,
        "artifacts": [],
        "memory_source": SourceType.GITHUB_PR.value,
    }


def _fetch_json(url: str) -> object:
    headers = {"User-Agent": "onmc/0.3.0", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    request = urllib.request.Request(  # noqa: S310 - target is fixed to the GitHub API.
        url,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []


def _attach_reviews(owner: str, repo: str, pr: dict[str, object]) -> dict[str, object]:
    number = pr.get("number")
    if not isinstance(number, int):
        return pr
    combined = dict(pr)
    combined["reviews"] = fetch_pr_reviews(owner, repo, number)
    return combined


def _batched(items: list[dict[str, object]], *, size: int) -> list[list[dict[str, object]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _finding_to_memory(finding: GitHubPRFinding) -> MemoryEntry:
    kind = _memory_kind_for_finding(finding.kind)
    now = utc_now()
    source_ref = f"pr:{finding.source_pr}"
    return MemoryEntry(
        id=stable_id(source_ref, finding.title, prefix=kind.value),
        kind=kind,
        title=finding.title,
        summary=finding.summary,
        details=f"GitHub PR #{finding.source_pr}",
        source_type=SourceType.GITHUB_PR,
        source_ref=source_ref,
        tags=[f"pr:{finding.source_pr}", kind.value],
        confidence=finding.confidence,
        created_at=now,
        updated_at=now,
    )


def _memory_kind_for_finding(kind: str) -> MemoryKind:
    mapping = {
        "decision": MemoryKind.DECISION,
        "did_not_work": MemoryKind.FAILED_APPROACH,
        "invariant": MemoryKind.INVARIANT,
        "gotcha": MemoryKind.GOTCHA,
    }
    return mapping.get(kind, MemoryKind.GOTCHA)


def _count_kinds(memories: list[MemoryEntry]) -> dict[str, int]:
    counts = {item.value: 0 for item in MemoryKind}
    for memory in memories:
        counts[memory.kind.value] = counts.get(memory.kind.value, 0) + 1
    return counts


def _pr_prompt(prs: list[dict[str, object]]) -> str:
    return (
        "You are extracting engineering knowledge from GitHub pull request data.\n\n"
        "For each PR, look for:\n"
        "- decisions: choices made (from PR description rationale)\n"
        "- did_not_work: approaches rejected in review "
        '(from review comments saying "don\'t do X because Y")\n'
        "- invariants: rules enforced in review (reviewer insisting on a pattern)\n"
        "- gotchas: non-obvious issues caught in review\n\n"
        "Return ONLY a JSON array:\n"
        "{\n"
        '  "kind": "decision" | "did_not_work" | "invariant" | "gotcha",\n'
        '  "title": "under 60 chars",\n'
        '  "summary": "what was decided/rejected/discovered, 1-2 sentences",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "source_pr": 123\n'
        "}\n\n"
        "Only items with confidence >= 0.75.\n"
        "Only codebase-specific knowledge, not generic advice.\n\n"
        f"PRs:\n{json.dumps(prs, indent=2, sort_keys=True)}"
    )
