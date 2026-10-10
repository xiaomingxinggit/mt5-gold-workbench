# Branch workflow

- Perform all development, fixes, and commits on `dev`. Do not create additional development branches unless the user explicitly requests one.
- `main` is the stable release branch. Promote tested changes from `dev` to `main` for a release; do not develop directly on `main`.
- Create version tags from `main`; the tag must match `mt5_workbench.__version__` (for example, `v0.2.0`).
- Keep the local working checkout on `dev` after publishing a release.
- Never commit `state/`, account records, screenshots containing account data, or generated build artifacts.
