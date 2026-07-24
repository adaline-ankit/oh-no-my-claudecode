# Releasing oh-no-my-claudecode

This document is the authoritative guide for cutting a release. The pipeline uses
**PyPI trusted publishing (OIDC)** — no API token secrets are stored in GitHub.

---

## How the pipeline works

Pushing a `vX.Y.Z` tag triggers `.github/workflows/release.yml`, which runs these jobs:

```
release-contract  →  gate  →  build  →  pypi-readiness  →  publish  →  verify-pypi
                                      ╰→  github-release
```

| Job | `needs` | What it does |
|---|---|---|
| `release-contract` | — | Verifies `vX.Y.Z` matches `pyproject.toml` before release work starts |
| `gate` | `release-contract` | Full quality gate across Python 3.11–3.13: ruff, mypy, pytest (≥80% coverage) |
| `build` | `release-contract`, `gate` | `python -m build` (sdist + wheel) + `twine check`; uploads dist as workflow artifact |
| `pypi-readiness` | `build` | Fails explicitly if `PYPI_TRUSTED_PUBLISHING=true` is not set for a tag/release publish |
| `publish` | `build`, `pypi-readiness` | Uploads to PyPI via OIDC trusted publishing |
| `verify-pypi` | `publish` | Installs the exact released version from PyPI and checks the console entrypoint |
| `github-release` | `build` | Creates a GitHub Release with auto-generated notes + dist assets attached. Runs whenever the build passes on a tag push — **not** gated on `publish`. |

The `publish` and `github-release` jobs only fire on tag pushes or manually-published
GitHub Releases — `workflow_dispatch` alone does **not** publish to PyPI or create a
release.

**Key design principle:** the workflow must not look green when PyPI was silently
skipped. If the repository is publishing a tag/release and PyPI trusted publishing
is not enabled, `pypi-readiness` fails with setup instructions.

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

### 4. Validate release readiness (dry-run the contract)

Before tagging, run the offline release-contract check. It mirrors the CI
`release-contract` job — the `pyproject` version must be tag-able (no existing
`vX.Y.Z` tag, a matching `CHANGELOG.md` entry, no version regression) — and
prints the exact tag command when ready:

```bash
onmc release --check
```

Exit code `0` means ready to tag; non-zero means it is not (the output lists the
blocking issue, e.g. the version is already tagged or the CHANGELOG entry is
missing). This is also where version/tag **drift** shows up: when `main` is ahead
of the last tag, `--check` reports the pending `vX.Y.Z` and how to publish it.

### 5. Tag and push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The pipeline starts automatically. Monitor progress:

```bash
gh run watch --repo adaline-ankit/oh-no-my-claudecode
```

### 6. Confirm the release

- PyPI: https://pypi.org/project/oh-no-my-claudecode/
- GitHub Release: https://github.com/adaline-ankit/oh-no-my-claudecode/releases

Install the wheel in a fresh venv to smoke-test:

```bash
python -m venv /tmp/onmc-release-check
/tmp/onmc-release-check/bin/python -m pip install oh-no-my-claudecode==X.Y.Z
/tmp/onmc-release-check/bin/onmc --version
```

---

## PyPI trusted publishing (one-time setup)

The `publish` job uses OIDC trusted publishing — no API token is required or stored.
The job is **disabled by default** via a repository variable gate and must be enabled
once after the PyPI project side is configured. Follow these steps exactly once:

### Step 1 — Register the trusted publisher on PyPI

1. Go to https://pypi.org/manage/project/oh-no-my-claudecode/settings/publishing/
   (create the project first via https://pypi.org/manage/projects/ if it does not
   exist yet — PyPI requires at least one manual upload to create a project, or you
   can use the "pending publisher" feature to pre-register before any upload).
2. Under **Add a new pending publisher** (or **Trusted Publisher Management**), add:
   - **Publisher:** GitHub Actions
   - **Repository owner:** `adaline-ankit`
   - **Repository name:** `oh-no-my-claudecode`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`

### Step 2 — Configure the GitHub environment

In the repository at **Settings → Environments**, ensure an environment named `pypi`
exists and has a deployment branch rule matching `refs/tags/v*.*.*` (tag-only deploys).

### Step 3 — Enable the publish job

In **Settings → Variables → Actions**, add (or set) a repository variable:

```
PYPI_TRUSTED_PUBLISHING = true
```

Once this variable is set, every subsequent `vX.Y.Z` tag push will upload to PyPI
and verify that the uploaded package can be installed by `pip`.

### Until then

Until Step 3 is complete, pushing a `vX.Y.Z` tag still runs the quality gate and
builds the distributions, but `pypi-readiness` fails before publish. Fix the PyPI
setup, then rerun the release workflow.

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
