# Obsidian Vault Export

ONMC can turn repository memory into a local Obsidian knowledge graph.

```bash
onmc wiki --format obsidian
```

Open `.onmc/obsidian/` as an Obsidian vault. Start at `Home.md`, then open Graph View to browse
connections between decisions, invariants, gotchas, validation rules, and failed approaches.

## Vault Layout

- `Home.md`: repository overview, subsystem links, and recently updated memory
- `Graph.md`: readable list of recorded memory relationships
- `Memories/`: one provenance-tracked note per memory record
- `Subsystems/`: indexes grouped from each memory's source path

Memory notes include YAML properties for ID, kind, source, confidence, and tags. Relationship edges
become wikilinks, so Obsidian Graph View renders ONMC's memory graph without a plugin.

## Output And Privacy

Default output is `.onmc/obsidian/`, inside ONMC's gitignored local state:

```bash
onmc wiki --format obsidian
```

Choose an explicit directory only when you intend to commit or share the vault:

```bash
onmc wiki --format obsidian --output docs/repo-brain
```

Vault notes may contain repository decisions, failed approaches, source paths, and session-derived
knowledge. Review generated files before publishing them.

## Refresh

Regeneration is deterministic for the same memory store:

```bash
onmc ingest
onmc consolidate
onmc wiki --format obsidian
```

`onmc consolidate` is optional. It creates or refreshes relationship edges, producing a richer
Obsidian graph.
