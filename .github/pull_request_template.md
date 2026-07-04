## Summary

What problem does this PR solve?

## Routing

- Priority expectation: `P0` / `P1` / `P2` / `P3`
- Risk areas touched: agent runtime / memory schema / MCP trust / CI-release / docs-only
- Issue link:

## Changes

-

## Validation

```bash
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing
python -m build && python -m twine check dist/*
```

## Agent Safety

- [ ] I did not commit secrets, tokens, private prompts, or proprietary repo content.
- [ ] I updated `CLAUDE.md`, `AGENTS.md`, or docs when agent-facing behavior changed.
- [ ] I added or updated tests for behavior changes.
- [ ] I regenerated `docs/cli-reference.md` when CLI help changed.
- [ ] I attached or referenced an ONMC receipt when an agent performed the work.
- [ ] I kept the change focused and avoided unrelated formatting churn.

## Notes
