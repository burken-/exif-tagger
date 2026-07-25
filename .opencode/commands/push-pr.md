---
description: Push current branch to remote and create PR against main
agent: coder
---

Push the current branch to origin and create a pull request against `main` using GitHub CLI.

```bash
bash scripts/git-push-pr.sh
```

This will:
1. If on `main`, create a new feature branch named `feat/agent-<timestamp>-<short-hash>`
2. Stage any uncommitted working tree changes with an auto-commit message
3. Push the branch to origin (with retry logic for name conflicts)
4. Generate a PR body containing:
   - The latest commit message as the PR title
   - A list of all commits on the branch
   - A diff summary (files changed, lines added/removed)
5. Create the PR via `gh pr create --base main`

Requires GitHub CLI (`gh`) to be authenticated with `gh auth login`.
