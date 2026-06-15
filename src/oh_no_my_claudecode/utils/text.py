from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "up",
    "with",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        for part in re.split(r"[/_.-]+", raw):
            cleaned = part.strip()
            if len(cleaned) <= 1 or cleaned in STOPWORDS:
                continue
            tokens.append(cleaned)
    return tokens


def unique_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def slugify(value: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        slug = "task"
    return slug[:max_length].strip("-") or "task"


def shorten(value: str, *, max_length: int = 160) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def shorten_to_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* at a sentence or word boundary, never mid-word.

    Priority: last sentence end (``[.!?]``) within *max_chars*, then last
    word boundary, then hard cut.  Appends ``...`` only when truncated.
    Collapses runs of whitespace before measuring.
    """
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    # Search for a sentence boundary (. ! ?) followed by whitespace or end-of-string.
    sentence_end = re.compile(r"[.!?](?=\s|$)")
    best_sentence = -1
    for match in sentence_end.finditer(collapsed, 0, max_chars):
        best_sentence = match.end()
    if best_sentence > 0:
        return collapsed[:best_sentence].rstrip()
    # Fall back to last whitespace boundary.
    truncated = collapsed[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space].rstrip() + "..."
    # Hard cut (single very-long token).
    return truncated.rstrip() + "..."


def strip_markdown_noise(text: str) -> str:
    """Remove code fences and stray backtick runs from *text*.

    Handles both multi-line fences (triple-backtick blocks with newlines) and
    collapsed single-line fences (``` ... ```) that result from whitespace
    normalisation at ingest time.  Fenced content is replaced with a short
    breadcrumb like ``[bash code]`` so the caller gets clean prose.  Inline
    code spans (single backtick pairs) are unwrapped.  Resulting whitespace is
    normalised to a single space.
    """
    # Match triple-backtick fences in both forms:
    #   multi-line:  ```lang\n...\n```
    #   collapsed:   ```lang ... ```  (all on one line, as stored after shorten())
    def _replace_fence(match: re.Match[str]) -> str:
        lang = (match.group(1) or "").strip()
        return f"[{lang} code]" if lang else "[code]"

    # Multi-line form first (DOTALL so . matches newlines).
    stripped = re.sub(
        r"```([\w.-]*)\s[\s\S]*?```",
        _replace_fence,
        text,
    )
    # Same for tilde fences.
    stripped = re.sub(
        r"~~~([\w.-]*)\s[\s\S]*?~~~",
        _replace_fence,
        stripped,
    )
    # Remove inline code spans (single backtick pairs).
    stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
    # Strip stray lone backticks.
    stripped = stripped.replace("`", "")
    # Collapse whitespace.
    return re.sub(r"\s+", " ", stripped).strip()


def limit_markdown_tokens(markdown: str, max_tokens: int) -> str:
    """Trim markdown by whitespace token budget while preserving line order."""
    if max_tokens <= 0:
        msg = "max_tokens must be greater than 0"
        raise ValueError(msg)
    used = 0
    lines_out: list[str] = []
    for line in markdown.splitlines():
        tokens = line.split()
        if not tokens:
            lines_out.append(line)
            continue
        remaining = max_tokens - used
        if remaining <= 0:
            break
        if len(tokens) <= remaining:
            lines_out.append(line)
            used += len(tokens)
            continue
        lines_out.append(" ".join(tokens[:remaining]) + " ...")
        used = max_tokens
        break
    if used >= max_tokens:
        lines_out.extend(["", f"[trimmed to {max_tokens} tokens]"])
    return "\n".join(lines_out)


def stable_id(*parts: str, prefix: str) -> str:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
