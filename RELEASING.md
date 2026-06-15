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
#   gate (quality 3.11/3.12/3.13) → build → publish (PyPI OIDC) → GitHub Release
```

The GitHub environment must be named `pypi` and match the PyPI trusted publisher
configuration. No API token is required or stored.
