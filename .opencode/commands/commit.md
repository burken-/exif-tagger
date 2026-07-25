---
description: Generate conventional commit message from staged changes and commit
agent: coder
---

Run the conventional commit helper script to automatically generate a commit message from staged changes.

```bash
bash scripts/git-commit.sh
```

This will:
1. Detect the change type (feat, fix, chore, docs, refactor, test, ci, perf) from file paths and diff content
2. Generate an appropriate scope from the first directory component of changed files
3. Create a meaningful description by analyzing added/removed lines
4. Execute `git commit -m "<type>(<scope>): <description>"` or `git commit -m "<type>: <description>"` if no scope is detected

The script enforces conventional commit format with subject length between 10 and 50 characters, following the project's `.commitlintrc.json` rules.
