"""Write-approval staging queue for memory writes.

Proposed memory entries are staged for human review before hitting the store.
A human can then approve (persist to the memory store) or reject (drop with
an audit trail) each proposal.

Persistence layout::

    .onmc/memstage/
        pending/          — one JSON file per staged proposal
            <id>.json
        audit/            — one JSON file per approve/reject decision
            <seq>-<id>.json

Both directories are portable and git-friendly.
"""
