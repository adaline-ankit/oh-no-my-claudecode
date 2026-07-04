# Branch Protection

Use this checklist for `main` in GitHub repository settings. These settings keep
outside contributions open while making sure only the maintainer can merge
unproven changes.

- Require a pull request before merging.
- Require review from Code Owners.
- Require status checks to pass before merging:
  - `quality (3.11)`
  - `quality (3.12)`
  - `quality (3.13)`
  - `windows smoke`
  - `package`
  - `security`
  - `priority, kind, size, and risk labels`
  - `codeql`
  - `scorecard`
- Require branches to be up to date before merging.
- Restrict who can push to matching branches: `@ankit-adaline`.
- Do not allow force pushes.
- Do not allow deletions.

The `CODEOWNERS` file routes every PR to `@ankit-adaline`; branch protection is
what turns that route into a merge gate.
