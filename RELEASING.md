# Releasing

For the full maintainer guide — how to cut a release, how trusted publishing is
configured, and rollback procedures — see **[docs/RELEASING.md](docs/RELEASING.md)**.

## Quick reference

```bash
# 1. Merge a bump PR (version + CHANGELOG) to main, confirm CI is green.
# 2. Tag and push:
git tag vX.Y.Z
git push origin vX.Y.Z
# The release workflow runs automatically:
#   gate (quality 3.11/3.12/3.13) → build → github-release (always)
#                                         ↘ publish (PyPI OIDC — only when
#                                             repo variable PYPI_TRUSTED_PUBLISHING=true)
```

The GitHub Release is created independently of the PyPI publish — a missing or
failed publish will never block the release. See **[docs/RELEASING.md](docs/RELEASING.md)**
for the one-time PyPI trusted publishing setup instructions.
