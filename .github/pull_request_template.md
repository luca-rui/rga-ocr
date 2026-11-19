<!-- For anything larger than a fix, an issue first: see CONTRIBUTING.md -->

What changes, and why:

How it was checked (a test that fails without the change, a command and its output):

- [ ] `python -m pytest -q` and `ruff check .` pass
- [ ] a line under `[Unreleased]` in `CHANGELOG.md` for a user-visible change
- [ ] the adapter `version` is raised when an adapter's output changes
