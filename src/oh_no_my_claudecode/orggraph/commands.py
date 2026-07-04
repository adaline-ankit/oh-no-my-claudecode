"""CLI surface for the ``orggraph`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Storage is opened directly, mirroring ``roast``'s
``_open_context`` (which itself mirrors the service's ``_load_context``) — no
shared service/rendering hub is touched, and ``storage`` is only *read*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.config import (
    config_exists,
    create_state_dirs,
    database_path,
    load_config,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.orggraph.graph import (
    Edge,
    Entity,
    OrgGraph,
    build_org_graph,
    decision_lineage,
    query_entity,
)
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

orggraph_app = typer.Typer(
    name="orggraph",
    help="Institutional-memory knowledge graph — entities, typed edges, lineage.",
    no_args_is_help=True,
)


def _open_context() -> tuple[Path, SQLiteStorage]:
    """Resolve the repo root and open an initialised (read-only use) storage handle.

    Mirrors ``roast._open_context`` so failure messages match the rest of the
    CLI, without routing through the service hub. We only ever *read* from the
    returned storage.
    """
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a git repository. Run `onmc orggraph` from your repo.", err=True)
        raise typer.Exit(code=1) from None
    if not config_exists(repo_root):
        typer.echo("ONMC is not initialized. Run `onmc init` first.", err=True)
        raise typer.Exit(code=1)
    config = load_config(repo_root)
    create_state_dirs(config, repo_root)
    storage = SQLiteStorage(database_path(config, repo_root))
    storage.initialize()
    return repo_root, storage


def _load_graph() -> OrgGraph:
    """Open storage, read all memories, and build the org graph."""
    _, storage = _open_context()
    memories = storage.list_memories()
    return build_org_graph(memories)


def _top_entities(graph: OrgGraph, limit: int = 10) -> list[Entity]:
    """Return the *limit* entities with the most incident edges (stable order)."""
    degree: dict[str, int] = {ent.name: 0 for ent in graph.entities}
    for edge in graph.edges:
        if edge.src in degree:
            degree[edge.src] += 1
        if edge.dst in degree:
            degree[edge.dst] += 1
    ordered = sorted(graph.entities, key=lambda e: (-degree[e.name], e.name))
    return ordered[:limit]


def _entity_dict(entity: Entity) -> dict[str, object]:
    return {"name": entity.name, "kind": entity.kind, "memory_ids": list(entity.memory_ids)}


def _edge_dict(edge: Edge) -> dict[str, object]:
    return {
        "src": edge.src,
        "dst": edge.dst,
        "rel": edge.rel,
        "memory_ids": list(edge.memory_ids),
    }


def register(app: typer.Typer) -> None:
    """Register the ``orggraph`` sub-app onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @orggraph_app.command("build")
    def build_command(
        as_json: Annotated[
            bool, typer.Option("--json", help="Emit the graph summary as JSON.")
        ] = False,
    ) -> None:
        """Build the knowledge graph from stored memories and summarise it.

        Deterministic and offline: same brain → same graph. Prints entity/edge
        counts, a per-relation breakdown, and the most-connected entities.
        """
        graph = _load_graph()
        top = _top_entities(graph)
        rel_counts: dict[str, int] = {}
        for edge in graph.edges:
            rel_counts[edge.rel] = rel_counts.get(edge.rel, 0) + 1

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "entity_count": len(graph.entities),
                        "edge_count": len(graph.edges),
                        "relations": dict(sorted(rel_counts.items())),
                        "top_entities": [
                            {**_entity_dict(e), "memory_count": len(e.memory_ids)} for e in top
                        ],
                    }
                )
            )
            return

        if not graph.entities:
            typer.echo(
                "\n  onmc orggraph — brain is empty; nothing to graph yet.\n"
                "  Accumulate memories (`onmc mine`, ingest, or `onmc record`) first.\n"
            )
            return

        lines = [
            "",
            "  onmc orggraph — institutional-memory knowledge graph",
            f"  entities: {len(graph.entities)}   edges: {len(graph.edges)}",
            "",
            "  edges by relation:",
        ]
        for rel, count in sorted(rel_counts.items()):
            lines.append(f"   • {rel}: {count}")
        lines.append("")
        lines.append("  most-connected entities:")
        for ent in top:
            lines.append(f"   • [{ent.kind}] {ent.name}  ({len(ent.memory_ids)} memories)")
        lines.append("")
        typer.echo("\n".join(lines))

    @orggraph_app.command("query")
    def query_command(
        entity: Annotated[str, typer.Argument(help="Entity name to inspect.")],
        as_json: Annotated[
            bool, typer.Option("--json", help="Emit the query result as JSON.")
        ] = False,
    ) -> None:
        """Show an entity's neighbours and the provenance (memory ids) behind it."""
        graph = _load_graph()
        result = query_entity(graph, entity)
        found: Entity | None = result["entity"]
        neighbors: list[tuple[Edge, Entity]] = result["neighbors"]
        provenance: list[str] = result["provenance"]

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "entity": _entity_dict(found) if found else None,
                        "neighbors": [
                            {"edge": _edge_dict(edge), "other": _entity_dict(other)}
                            for edge, other in neighbors
                        ],
                        "provenance": provenance,
                    }
                )
            )
            return

        if found is None:
            typer.echo(f"\n  No entity named {entity!r} in the graph.\n", err=True)
            raise typer.Exit(code=1)

        lines = [
            "",
            f"  onmc orggraph — {found.name}  [{found.kind}]",
            f"  provenance: {len(provenance)} memories",
            "",
        ]
        if neighbors:
            lines.append("  neighbours:")
            for edge, other in neighbors:
                direction = "→" if edge.src == found.name else "←"
                lines.append(f"   • {edge.rel} {direction} [{other.kind}] {other.name}")
        else:
            lines.append("  (no neighbours)")
        lines.append("")
        lines.append(f"  memory ids: {', '.join(provenance) if provenance else '(none)'}")
        lines.append("")
        typer.echo("\n".join(lines))

    @orggraph_app.command("why")
    def why_command(
        decision: Annotated[str, typer.Argument(help="Decision entity name.")],
        as_json: Annotated[
            bool, typer.Option("--json", help="Emit the lineage as JSON.")
        ] = False,
    ) -> None:
        """Explain a decision: the ordered chain of edges/memories behind it."""
        graph = _load_graph()
        result = decision_lineage(graph, decision)
        found: Entity | None = result["decision"]
        chain: list[Edge] = result["chain"]
        memory_ids: list[str] = result["memory_ids"]

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "decision": _entity_dict(found) if found else None,
                        "chain": [_edge_dict(edge) for edge in chain],
                        "memory_ids": memory_ids,
                    }
                )
            )
            return

        if found is None:
            typer.echo(f"\n  No decision named {decision!r} in the graph.\n", err=True)
            raise typer.Exit(code=1)

        lines = [
            "",
            f"  onmc orggraph — why: {found.name}",
            f"  lineage: {len(memory_ids)} memories across {len(chain)} relationships",
            "",
        ]
        if chain:
            for edge in chain:
                other = edge.dst if edge.src == found.name else edge.src
                lines.append(f"   • {edge.rel}: {other}  [{', '.join(edge.memory_ids)}]")
        else:
            lines.append("  (no relationships recorded for this decision)")
        lines.append("")
        typer.echo("\n".join(lines))

    app.add_typer(orggraph_app, name="orggraph")
