"""Pure, deterministic construction of an institutional-memory knowledge graph.

``orggraph`` turns onmc's provenanced memories into an entity/relationship graph
with lineage: every :class:`Entity` and :class:`Edge` records the memory id(s) it
was derived from, so any node or relationship can be traced back to the durable
memory that justified it.

This module is intentionally **offline, stdlib-only, and deterministic**: given
the same list of :class:`~oh_no_my_claudecode.models.memory.MemoryEntry` objects
it always yields byte-identical output (stable ordering everywhere). No storage,
no network, no LLM — the CLI layer in :mod:`oh_no_my_claudecode.orggraph.commands`
is the only thing that touches the database.

Extraction overview
--------------------
For each memory we extract:

- **file / path entities** — path-ish tokens (``src/foo/bar.py``) via a regex
  mirroring the mission path-token detector.
- **component entities** — capitalised / dotted identifier tokens that look like
  module or component names (e.g. ``SQLiteStorage``, ``command_registry``).
- **decision entities** — the title of every ``decision``-kind memory.
- **person / author entities** — ``author:``/``by:`` style tags and the author
  portion of a ``source_ref``.

And we infer **typed edges** from a memory's kind plus the co-occurrence of the
entities it mentions within that single entry:

- ``supersedes``  — ``failed_approach`` / ``design_conflict`` memories: the
  decision (or first component) supersedes the paths it touched.
- ``depends-on``  — components/files co-mentioned in ``invariant`` /
  ``validation_rule`` / ``doc_fact`` memories depend on one another.
- ``decided-by``  — a ``decision`` entity is decided-by its author entities.
- ``caused-by``   — ``gotcha`` / ``failed_approach`` memories: the file is
  caused-by the decision/component blamed in the same entry.
- ``relates-to``  — the generic fallback linking every pair of entities that
  co-occur in a memory with no more specific relation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypedDict

from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind

__all__ = [
    "Entity",
    "Edge",
    "OrgGraph",
    "EntityQuery",
    "DecisionLineage",
    "build_org_graph",
    "query_entity",
    "decision_lineage",
]

# A path-ish token, e.g. ``src/foo/bar.py`` — mirrors the mission detector.
# Written as ``/``-separated segments with non-overlapping quantifiers so it is
# linear-time (no catastrophic backtracking on adversarial input).
_PATH_TOKEN = re.compile(r"[\w.-]+(?:/[\w.-]+)+")

# A component / module identifier: CamelCase, snake_case, or dotted names that
# are clearly code symbols. Each alternative uses non-overlapping runs (a run
# never starts with a char its predecessor could also consume) so the regex is
# linear-time — CamelCase runs after the first capital are lower/digit only.
_COMPONENT_TOKEN = re.compile(
    r"\b(?:[A-Za-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+"  # CamelCase (incl. acronym prefix)
    r"|[a-z0-9]+(?:_[a-z0-9]+)+"  # snake_case
    r"|[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)+)\b"  # dotted.name
)

# Author markers in tags, e.g. ``author:ankit`` / ``by:codex`` / ``owner:sam``.
_AUTHOR_TAG = re.compile(r"^(?:author|by|owner|reviewer)[:=](.+)$", re.IGNORECASE)

# Author embedded in a source_ref: an explicit ``author=x`` / ``by:x`` marker
# anywhere in the ref, or the trailing name of a ``…pr/<n>/<author>`` ref
# (e.g. ``github:pr/123/ankit`` → ``ankit``).
_REF_AUTHOR = re.compile(r"(?:author|by|owner|reviewer)[:=]([\w.-]+)", re.IGNORECASE)
_REF_PR_AUTHOR = re.compile(r"\bpr/\d+/([\w.-]+)", re.IGNORECASE)

# Entity kind labels (stable, lower-case).
KIND_FILE = "file"
KIND_COMPONENT = "component"
KIND_DECISION = "decision"
KIND_PERSON = "person"

# Edge relation labels (stable, lower-case).
REL_SUPERSEDES = "supersedes"
REL_DEPENDS_ON = "depends-on"
REL_DECIDED_BY = "decided-by"
REL_CAUSED_BY = "caused-by"
REL_RELATES_TO = "relates-to"


@dataclass
class Entity:
    """A node in the org graph, with lineage back to its source memories."""

    name: str
    kind: str
    memory_ids: list[str] = field(default_factory=list)


@dataclass
class Edge:
    """A typed, directed relationship, with lineage back to source memories."""

    src: str
    dst: str
    rel: str
    memory_ids: list[str] = field(default_factory=list)


@dataclass
class OrgGraph:
    """A deterministic entity/relationship graph over institutional memory."""

    entities: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def entity(self, name: str) -> Entity | None:
        """Return the entity named *name*, or ``None`` if absent."""
        for ent in self.entities:
            if ent.name == name:
                return ent
        return None


class EntityQuery(TypedDict):
    """Result of :func:`query_entity`."""

    entity: Entity | None
    neighbors: list[tuple[Edge, Entity]]
    provenance: list[str]


class DecisionLineage(TypedDict):
    """Result of :func:`decision_lineage`."""

    decision: Entity | None
    chain: list[Edge]
    memory_ids: list[str]


class _Accumulator:
    """Mutable builder that dedupes entities/edges and records lineage."""

    def __init__(self) -> None:
        # name -> (kind, ordered-unique memory ids)
        self._entities: dict[str, tuple[str, list[str]]] = {}
        # (src, dst, rel) -> ordered-unique memory ids.
        # Both dicts preserve first-seen insertion order (Python 3.7+), which is
        # the stable tie-break ``build`` relies on — no separate order list.
        self._edges: dict[tuple[str, str, str], list[str]] = {}

    def add_entity(self, name: str, kind: str, memory_id: str) -> None:
        name = name.strip()
        if not name:
            return
        existing = self._entities.get(name)
        if existing is None:
            self._entities[name] = (kind, [memory_id])
            return
        prev_kind, ids = existing
        # Prefer the more specific kind if a later mention upgrades a generic one.
        resolved_kind = _prefer_kind(prev_kind, kind)
        if memory_id not in ids:
            ids.append(memory_id)
        self._entities[name] = (resolved_kind, ids)

    def add_edge(self, src: str, dst: str, rel: str, memory_id: str) -> None:
        src, dst = src.strip(), dst.strip()
        if not src or not dst or src == dst:
            return
        key = (src, dst, rel)
        ids = self._edges.get(key)
        if ids is None:
            self._edges[key] = [memory_id]
            return
        if memory_id not in ids:
            ids.append(memory_id)

    def build(self) -> OrgGraph:
        entities = [
            Entity(
                name=name,
                kind=self._entities[name][0],
                memory_ids=list(self._entities[name][1]),
            )
            for name in sorted(self._entities)
        ]
        edges = [
            Edge(src=src, dst=dst, rel=rel, memory_ids=list(self._edges[(src, dst, rel)]))
            for (src, dst, rel) in sorted(self._edges)
        ]
        return OrgGraph(entities=entities, edges=edges)


# Ranking used when the same name is seen as two kinds; more specific wins.
_KIND_RANK = {KIND_PERSON: 3, KIND_DECISION: 2, KIND_COMPONENT: 1, KIND_FILE: 1}


def _prefer_kind(a: str, b: str) -> str:
    """Return the more specific of two entity kinds (stable tie-break to *a*)."""
    if a == b:
        return a
    return a if _KIND_RANK.get(a, 0) >= _KIND_RANK.get(b, 0) else b


def _text_of(memory: MemoryEntry) -> str:
    """Concatenate the human text of a memory for token extraction."""
    return " ".join([memory.title, memory.summary, memory.details])


def _extract_paths(text: str) -> list[str]:
    """Ordered-unique path-ish tokens in *text*."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _PATH_TOKEN.finditer(text):
        token = match.group(0).strip("/")
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _extract_components(text: str, exclude: set[str]) -> list[str]:
    """Ordered-unique component identifiers in *text*, minus *exclude* (paths)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _COMPONENT_TOKEN.finditer(text):
        token = match.group(0)
        # Skip anything already claimed as a path fragment.
        if token in exclude or any(token in p.split("/") for p in exclude):
            continue
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _extract_people(memory: MemoryEntry) -> list[str]:
    """Ordered-unique person names from author tags and the source ref."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in memory.tags:
        m = _AUTHOR_TAG.match(tag.strip())
        if m:
            name = m.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    # source_ref like ``github:pr/123/ankit`` or ``commit:abc/author=sam``.
    ref = memory.source_ref or ""
    for rx in (_REF_AUTHOR, _REF_PR_AUTHOR):
        ref_author = rx.search(ref)
        if ref_author:
            name = ref_author.group(1).strip().rstrip("/")
            if name and name not in seen:
                seen.add(name)
                out.append(name)
            break
    return out


def build_org_graph(memories: list[MemoryEntry]) -> OrgGraph:
    """Build a deterministic :class:`OrgGraph` from *memories*.

    Every entity and edge records the id(s) of the memory it was derived from —
    this is the lineage that lets :func:`query_entity` and
    :func:`decision_lineage` explain *why* a node or relationship exists.

    The function is pure and offline: no storage, network, or LLM access, and
    identical input always produces identical output (all collections are sorted
    before being returned).
    """
    acc = _Accumulator()

    # Process memories in a stable order (id) so lineage lists are deterministic
    # regardless of the caller's ordering.
    for memory in sorted(memories, key=lambda m: m.id):
        mid = memory.id
        text = _text_of(memory)

        paths = _extract_paths(text)
        path_set = set(paths)
        components = _extract_components(text, exclude=path_set)
        people = _extract_people(memory)

        for p in paths:
            acc.add_entity(p, KIND_FILE, mid)
        for c in components:
            acc.add_entity(c, KIND_COMPONENT, mid)
        for person in people:
            acc.add_entity(person, KIND_PERSON, mid)

        decision_name: str | None = None
        if memory.kind == MemoryKind.DECISION:
            decision_name = memory.title.strip()
            if decision_name:
                acc.add_entity(decision_name, KIND_DECISION, mid)

        _infer_edges(acc, memory, mid, paths, components, people, decision_name)

    return acc.build()


def _infer_edges(
    acc: _Accumulator,
    memory: MemoryEntry,
    mid: str,
    paths: list[str],
    components: list[str],
    people: list[str],
    decision_name: str | None,
) -> None:
    """Infer typed edges from a single memory's kind + entity co-occurrence."""
    kind = memory.kind
    # The "actor" of the memory: an explicit decision, else the first component.
    actor = decision_name or (components[0] if components else None)

    if kind == MemoryKind.DECISION and decision_name is not None:
        # decision decided-by each author
        for person in people:
            acc.add_edge(decision_name, person, REL_DECIDED_BY, mid)
        # decision relates-to the files/components it names
        for target in paths + components:
            acc.add_edge(decision_name, target, REL_RELATES_TO, mid)

    elif kind in (MemoryKind.FAILED_APPROACH, MemoryKind.DESIGN_CONFLICT):
        # the actor supersedes the files/components it replaced
        if actor is not None:
            for target in paths + [c for c in components if c != actor]:
                acc.add_edge(actor, target, REL_SUPERSEDES, mid)

    elif kind == MemoryKind.GOTCHA:
        # each file is caused-by the actor (the component/decision to blame)
        if actor is not None:
            for p in paths:
                acc.add_edge(p, actor, REL_CAUSED_BY, mid)

    elif kind in (MemoryKind.INVARIANT, MemoryKind.VALIDATION_RULE, MemoryKind.DOC_FACT):
        # co-mentioned code entities depend on one another (chain, deterministic)
        code = paths + components
        for i in range(len(code) - 1):
            acc.add_edge(code[i], code[i + 1], REL_DEPENDS_ON, mid)

    # Generic fallback: every co-occurring pair relates-to each other so no
    # entity is ever orphaned. Deterministic upper-triangular enumeration.
    everything = paths + components + people
    if decision_name is not None and decision_name not in everything:
        everything = [decision_name, *everything]
    for i in range(len(everything)):
        for j in range(i + 1, len(everything)):
            acc.add_edge(everything[i], everything[j], REL_RELATES_TO, mid)


def query_entity(graph: OrgGraph, name: str) -> EntityQuery:
    """Return an entity, its neighbours, and its provenance memory ids.

    The result shape is::

        {
          "entity": Entity | None,
          "neighbors": list[tuple[Edge, Entity]],   # (edge, other-endpoint)
          "provenance": list[str],                  # sorted memory ids
        }

    ``neighbors`` covers both outgoing and incoming edges; ``other`` is the
    entity at the far end of each edge. Everything is deterministically ordered.
    """
    entity = graph.entity(name)
    neighbors: list[tuple[Edge, Entity]] = []
    provenance: set[str] = set()
    if entity is None:
        return {"entity": None, "neighbors": [], "provenance": []}

    provenance.update(entity.memory_ids)
    for edge in graph.edges:
        other_name: str | None = None
        if edge.src == name:
            other_name = edge.dst
        elif edge.dst == name:
            other_name = edge.src
        if other_name is None:
            continue
        other = graph.entity(other_name)
        if other is None:
            continue
        neighbors.append((edge, other))
        provenance.update(edge.memory_ids)

    neighbors.sort(key=lambda pair: (pair[0].rel, pair[1].name, pair[0].src, pair[0].dst))
    return {
        "entity": entity,
        "neighbors": neighbors,
        "provenance": sorted(provenance),
    }


def decision_lineage(graph: OrgGraph, decision_name: str) -> DecisionLineage:
    """Return the ordered chain of edges/memories behind a decision entity.

    The result shape is::

        {
          "decision": Entity | None,
          "chain": list[Edge],       # edges emanating from / naming the decision
          "memory_ids": list[str],   # sorted lineage across the whole chain
        }

    The chain is the set of edges incident to the decision, ordered by relation
    then endpoint so the lineage is stable. ``memory_ids`` is the deduped union
    of the decision entity's own provenance and every edge in the chain.
    """
    decision = graph.entity(decision_name)
    if decision is None:
        return {"decision": None, "chain": [], "memory_ids": []}

    chain: list[Edge] = [
        edge for edge in graph.edges if edge.src == decision_name or edge.dst == decision_name
    ]
    chain.sort(key=lambda e: (e.rel, e.dst, e.src))

    memory_ids: set[str] = set(decision.memory_ids)
    for edge in chain:
        memory_ids.update(edge.memory_ids)

    return {"decision": decision, "chain": chain, "memory_ids": sorted(memory_ids)}
