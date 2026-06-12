## Summary

What problem does this PR solve?

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
- [ ] I kept the change focused and avoided unrelated formatting churn.

## Notes
