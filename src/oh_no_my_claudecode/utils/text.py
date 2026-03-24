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


def stable_id(*parts: str, prefix: str) -> str:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
