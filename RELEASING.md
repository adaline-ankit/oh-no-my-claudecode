# Releasing

ONMC publishes Python distributions from GitHub Releases through PyPI trusted
publishing. Releases should be small, validated, and easy to audit.

## Pre-Release Checklist

1. Confirm `main` is green:

   ```bash
   gh run list --repo adaline-ankit/oh-no-my-claudecode --branch main --limit 5
   ```

2. Run the local gate from a clean checkout:

   ```bash
   ruff check .
   mypy src
   pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80
   python -m build
   python -m twine check dist/*
   python scripts/generate-cli-reference.py --check
   ```

3. Update release-facing files:

   - `pyproject.toml` version
   - `CHANGELOG.md`
   - `README.md` if commands, integrations, or install steps changed
   - `docs/cli-reference.md` if CLI help changed

4. Confirm package metadata locally:

   ```bash
   python -m venv /tmp/onmc-release
   /tmp/onmc-release/bin/python -m pip install dist/*.whl
   /tmp/onmc-release/bin/onmc --help
   ```

5. Create a GitHub Release tag in the form `vX.Y.Z`.

## Publishing

The `release` workflow runs when a GitHub Release is published. It:

- builds source and wheel distributions
- checks package metadata with Twine
- uploads built artifacts
- publishes to PyPI through trusted publishing

The GitHub environment must be named `pypi` and match the PyPI trusted publisher
configuration.

## Rollback

PyPI files are immutable. If a release is bad:

1. yank the affected version on PyPI
2. open a hotfix PR
3. publish a new patch version
4. document the issue in `CHANGELOG.md`
