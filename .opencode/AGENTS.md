# AGENTS.md — Workflow Rules for Agent Behavior

This file defines the operational rules that guide agent behavior during development sessions. It covers branch discipline, commit workflow, PR creation, and automatic architectural review after each pull request. Treat these as non-negotiable constraints on your actions unless explicitly overridden by the user.

---

## 1. Branch Discipline

- **Never push to `main` directly.** Always create a feature branch from `main`.
- Work exclusively on short-lived feature branches named following this convention:
  - `feature/<short-description>` — new functionality
  - `fix/<short-description>` — bug fixes
  - `chore/<short-description>` — tooling, deps, config changes
  - `refactor/<short-description>` — code restructuring without behavior change
- Keep branches short-lived (merge within **1–3 days**). Long-lived branches are hidden costs that accumulate merge risk.
- Always sync with the latest `main` before starting work on a new feature branch to minimize drift.

---

## 2. Commit Workflow

### When to commit

Commit after every successful increment — each logical slice of work gets its own atomic commit:

```
Work pattern: Implement → Test passes? → Verify → Commit → Next slice
```

Commits are save points. If the next change breaks something, revert to HEAD and recover instantly.

### Atomic commits

Each commit does **one** thing. Never mix formatting changes with behavior changes, or refactors with features. Separate concerns into distinct commits:

```bash
# Good — separate commits for each concern
git commit -m "refactor: extract validation logic to shared utility"
git commit -m "feat: add phone number validation to registration endpoint"

# Bad — mixed concerns in one commit
git commit -m "fix auth, refactor utils, update deps, and tweak styles"
```

### Commit message format

Use **Conventional Commits** with a descriptive body explaining the *why*, not just the *what*:

```
<type>: <short description>

(optional body — explain intent, not what's obvious from the diff)
```

| Type      | Meaning                                        |
|-----------|-------------------------------------------------|
| `feat`    | New feature                                     |
| `fix`     | Bug fix                                         |
| `refactor`| Code change that neither fixes a bug nor adds a feature |
| `test`    | Adding or updating tests                        |
| `docs`    | Documentation only                              |
| `chore`   | Tooling, dependencies, config                   |

### Pre-commit checklist

Before every commit:

- [ ] Commit does one logical thing (atomic)
- [ ] Message explains the *why*, follows conventional format
- [ ] Tests pass (`npm test`)
- [ ] No secrets in the diff (API keys, passwords, tokens)
- [ ] No formatting-only changes mixed with behavior changes
- [ ] `git diff --staged` reviewed for unintended changes

---

## 3. Push / PR Workflow

### When to push and create a PR

When the user signals completion — using words like **"done"**, **"ready to commit"**, or similar — execute this sequence:

1. **Commit** all remaining work with descriptive messages (see Section 2).
2. Run `git-commit` skill for conventional, well-structured commits.
3. Push the branch and create a PR using `push-pr`.
4. After the PR is created, proceed to architectural review (Section 5).

### Commit workflow summary

```
User says "done" → Finalize all commits with git-commit skill
                  → Create PR with push-pr script
                  → Architect review dispatches automatically
                  → Fix any issues found
                  → Report: "PR #X created, architect reviewed — N issues fixed"
```

---

## 4. Architect Review Flow (Automatic)

After every PR is created, the agent **automatically** initiates an architectural review before considering the task complete. This ensures quality gate enforcement without manual intervention.

### Step-by-step process

1. **Fetch the diff.** Retrieve the full PR diff:
   ```bash
   gh pr diff <number> > /tmp/pr-diff.diff
   ```
   If `gh` is unavailable, read the local branch diff instead:
   ```bash
   git diff main...HEAD > /tmp/pr-diff.diff
   ```

2. **Dispatch a heavy subagent** (`@heavy`) with:
   - The full content of `/tmp/pr-diff.diff`
   - Context about what was changed and why (from the commit messages)
   - This review criteria checklist (Section 6) to evaluate against
   - Instruction: produce structured, actionable feedback organized by severity

3. **Receive and triage feedback.** Parse the heavy subagent's report into issues grouped by category from Section 6. Prioritize CRITICAL/HIGH findings first.

4. **Fix all identified issues.** For each finding:
   - Apply targeted fixes to address root causes, not symptoms
   - Commit changes on the same feature branch (PR auto-updates)
   - Keep fix commits atomic and descriptive (`fix: <what was wrong>` → `fix: why it's correct`)

5. **Report completion.** Notify with this exact format:
   ```
   PR #X created, architect reviewed — N issues fixed
   ```
   Where *N* is the count of distinct issues resolved (not sub-issues or follow-ups).

### Important rules for architectural review

- The agent must not skip or short-circuit this flow. Architectural review happens after **every** PR automatically.
- Do not ask the user to trigger manual review — it's built into the workflow.
- If the heavy model reports zero issues, still report: "PR #X created, architect reviewed — 0 issues found."

---

## 5. Review Criteria Checklist

The architectural reviewer evaluates changes against these five dimensions. Every finding must map to one of these categories and include severity (CRITICAL / HIGH / MEDIUM / LOW):

### Architecture & Design Consistency
- Does the change follow existing codebase patterns for structure, naming, module organization?
- Are new abstractions justified or is over-engineering introduced?
- Do interfaces align with established contracts in the project?

### Security Considerations
- Is user input validated and sanitized before use (database queries, file paths, API calls)?
- Are secrets handled properly — never hardcoded, logged, or exposed in diffs?
- Are there injection risks: SQL, command injection, template injection, XSS?
- Does the change introduce new attack surface without adequate protections?

### Edge Cases & Error Handling Gaps
- Are error paths tested and do they fail gracefully (not with unhandled exceptions)?
- Is null/undefined handling consistent across similar code patterns in the project?
- Are race conditions possible where concurrency exists?
- Does the change handle unexpected but plausible inputs at boundaries?

### Performance Implications
- Could this introduce N+1 queries, excessive allocations, or blocking I/O on a hot path?
- Are large data structures passed by value instead of reference unnecessarily?
- Is there an opportunity for caching, batching, or early returns that was missed?

### Code Quality
- Is the code readable and maintainable (clear naming, reasonable function length)?
- Is duplication introduced where shared abstractions already exist in the project?
- Are tests commensurate with change complexity — not over-engineered but adequate for coverage of critical paths?
- Does dead or unreachable code remain after refactoring?

---

## Quick Reference: Agent Action Triggers

| User says / situation | What to do |
|-----------------------|------------|
| "Let's build X"       | Brainstorm first, then implement on a feature branch |
| Work increment complete (test passes) | Commit with descriptive message — atomic commit only |
| Bug found             | Investigate → fix → test → commit; separate from other work |
| "Done" / "ready to commit" | Finalize commits (`git-commit` skill) → `push-pr` → auto architectural review → report result |
| PR created            | Architectural review dispatches automatically (Section 4) — do not skip |
