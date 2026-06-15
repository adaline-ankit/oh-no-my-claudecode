# Releasing oh-no-my-claudecode

This document is the authoritative guide for cutting a release. The pipeline uses
**PyPI trusted publishing (OIDC)** — no API token secrets are stored in GitHub.

---

## How the pipeline works

Pushing a `vX.Y.Z` tag triggers `.github/workflows/release.yml`, which runs four
sequential jobs:

```
gate  →  build  →  publish  →  github-release
```

| Job | What it does |
|---|---|
| `gate` | Full quality gate across Python 3.11–3.13: ruff, mypy, pytest (≥80% coverage) |
| `build` | `python -m build` (sdist + wheel) + `twine check` |
| `publish` | Uploads to PyPI via OIDC trusted publishing (no token needed) |
| `github-release` | Creates a GitHub Release with auto-generated notes + dist assets attached |

The `publish` and `github-release` jobs only run on tag pushes or manually-published
GitHub Releases — `workflow_dispatch` alone does **not** publish to PyPI.

---

## Cutting a release

### 1. Verify `main` is green

```bash
gh run list --repo adaline-ankit/oh-no-my-claudecode --branch main --limit 5
```

All CI jobs (quality, windows-smoke, package, security) must be passing.

### 2. Run the local gate

From a clean checkout on the commit you intend to tag:

```bash
ruff check .
mypy src
pytest --cov=oh_no_my_claudecode --cov-report=term-missing --cov-fail-under=80
python -m build
python -m twine check dist/*
python scripts/generate-cli-reference.py --check
```

### 3. Update release-facing files

Edit these in a single PR merged to `main` before tagging:

- **`pyproject.toml`** — bump `version = "X.Y.Z"`
- **`CHANGELOG.md`** — rename `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD`, add a fresh `[Unreleased]` stub at the top
- **`README.md`** — update if commands, install steps, or integrations changed
- **`docs/cli-reference.md`** — regenerate if CLI help changed (`python scripts/generate-cli-reference.py`)

### 4. Tag and push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The pipeline starts automatically. Monitor progress:

```bash
gh run watch --repo adaline-ankit/oh-no-my-claudecode
```

### 5. Confirm the release

- PyPI: https://pypi.org/project/oh-no-my-claudecode/
- GitHub Release: https://github.com/adaline-ankit/oh-no-my-claudecode/releases

Install the wheel in a fresh venv to smoke-test:

```bash
python -m venv /tmp/onmc-release-check
/tmp/onmc-release-check/bin/python -m pip install oh-no-my-claudecode==X.Y.Z
/tmp/onmc-release-check/bin/onmc --version
```

---

## Trusted publishing setup (one-time, already configured)

The PyPI trusted publisher is registered under the `pypi` GitHub Actions environment.
No API token is stored. If you ever need to reconfigure it:

1. Go to https://pypi.org/manage/project/oh-no-my-claudecode/settings/publishing/
2. Add a publisher: GitHub — repo `adaline-ankit/oh-no-my-claudecode`, workflow
   `release.yml`, environment `pypi`.
3. The GitHub environment `pypi` must exist in repo Settings → Environments with
   the deployment branch rule set to `refs/tags/v*.*.*`.

---

## Rollback

PyPI files are immutable. If a release is bad:

1. Yank the version on PyPI: `pip install twine && twine dist yank X.Y.Z`
   or via the PyPI web UI (Manage → Yank this release).
2. Open a hotfix PR targeting `main`.
3. Publish a new patch version (e.g. `X.Y.Z+1`) following this guide.
4. Document the incident in `CHANGELOG.md` under the new version.

---

## Version numbering

`oh-no-my-claudecode` follows [Semantic Versioning](https://semver.org/):

- **PATCH** (`Z`) — bug fixes, docs, CI, dependency bumps.
- **MINOR** (`Y`) — new features, backward-compatible changes.
- **MAJOR** (`X`) — breaking CLI or API changes. Increment sparingly.

Pre-release suffixes (`0.5.0a1`, `0.5.0rc1`) are allowed by PyPI and the pipeline.
