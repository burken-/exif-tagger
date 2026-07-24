#!/usr/bin/env bash
# git-push-pr.sh - Push to a feature branch and create a GitHub PR.
#
# Usage:  ./git-push-pr.sh [--no-prompt]
#
# Behavior:
#   • If you are on main, creates a new feature branch from the current HEAD of main.
#     Branch name pattern: feat/agent-YYYYMMDD-HHMMSS-<8-char short hash>
#   • Stages and commits any uncommitted working-tree changes (with an auto message).
#   • Pushes the branch to origin with upstream tracking (--force-safe).
#   • Opens a PR against main via `gh pr create` populated from local git metadata.

set -euo pipefail

# ── helpers ────────────────────────────────────────────────────────────
info()  { echo "[git-push-pr] $*"; }
warn()  { echo "[git-push-pr] WARNING: $*" >&2; }
die()   { echo "[git-push-pr] ERROR: $*" >&2; exit 1; }

# ── pre-flight checks ────────────────────────────────────────────────

if ! command -v git &>/dev/null; then
    die "git is not installed or not in PATH."
fi

if ! command -v gh &>/dev/null; then
    die "\`gh\` (GitHub CLI) is not installed or not in PATH. Install it from https://cli.github.com/"
fi

# Verify a remote named origin exists
if ! git remote get-url origin &>/dev/null 2>&1; then
    die "No remote named 'origin' found. Add one with: git remote add origin <url>"
fi

info "Remote 'origin' verified."

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# ── create feature branch if on main ────────────────────────────────
if [[ "$CURRENT_BRANCH" == "main" ]]; then
    SHORT_HASH="$(git rev-parse --short=8 HEAD)"
    TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
    FEATURE_BRANCH="feat/agent-${TIMESTAMP}-${SHORT_HASH}"

    info "On main. Creating feature branch: ${FEATURE_BRANCH}"
    git checkout -b "$FEATURE_BRANCH" || die "Failed to create branch '${FEATURE_BRANCH}'."
else
    # On an existing (non-main) branch — reuse it, but ensure a unique name if the user prefers fresh.
    FEATURE_BRANCH="$CURRENT_BRANCH"
fi

# ── stage uncommitted changes (optional convenience) ────────────────
STATUS="$(git status --porcelain 2>/dev/null || true)"
if [[ -n "$STATUS" ]]; then
    info "Uncommitted changes detected — staging and committing automatically."
    git add -A
    COMMIT_MSG="chore: auto-commit working tree before push ($(date +%Y-%m-%dT%H:%M:%S%z))"
    git commit --message="$COMMIT_MSG" || warn "Nothing to commit (working tree clean or stash-only changes)."
fi

# ── push the branch ────────────────────────────────────────────────
info "Pushing ${FEATURE_BRANCH} → origin …"
if ! git push -u origin "$FEATURE_BRANCH" --force-with-lease 2>&1; then
    warn "Initial push failed — attempting to create a unique branch name."

    # Try with an incremented suffix up to 5 times.
    for i in $(seq 1 5); do
        SUFFIXED="feat/agent-${FEATURE_BRANCH#feat/agent-}-try${i}"
        info "Trying alternative: ${SUFFIXED}"
        git checkout -b "$SUFFIXED" || { warn "Failed to create '${SUFFIXED}'; skipping."; continue; }

        # Cherry-pick all new commits from the old branch onto this one.
        COMMITS="$(git log --format=%H origin/main..HEAD 2>/dev/null || git rev-list HEAD ^origin/main)"
        if [[ -n "$COMMITS" ]]; then
            for sha in $COMMITS; do
                git cherry-pick "$sha" --no-commit && info "Cherry-picked $(git log -1 --pretty=%s "$sha")" \
                    || { warn "Cherry-pick conflict on ${sha}; aborting retry."; break 2; }
            done
        fi

        # Commit any leftover staged changes.
        if [[ -n "$(git status --porcelain)" ]]; then
            git commit --message="chore: cherry-picked commits (attempt $i)" || true
        fi

        if git push -u origin "$SUFFIXED" --force-with-lease 2>&1; then
            FEATURE_BRANCH="$SUFFIXED"
            info "Successfully pushed as ${FEATURE_BRANCH}."
            break
        else
            warn "Push of '${SUFFIXED}' failed — trying next suffix…"
        fi
    done

    if [[ "$FEATURE_BRANCH" != "$CURRENT_BRANCH" ]] && ! git rev-parse --verify "$FEATURE_BRANCH" &>/dev/null; then
        die "All push retries exhausted. Please resolve conflicts and try again."
    fi
fi

info "Pushed ${FEATURE_BRANCH} to origin successfully."

# ── gather PR metadata ───────────────────────────────────────────────

TITLE="$(git log -1 --pretty=%s)"
[[ -z "$TITLE" ]] && TITLE="Feature: $(basename "$FEATURE_BRANCH")"

if git rev-parse main &>/dev/null; then
    COMMITS_LIST="$(git log origin/main..HEAD --oneline 2>/dev/null || echo "  (no commits found)")"
else
    COMMITS_LIST="$(git log --oneline -10)"
fi

# Diff summary — prefer remote comparison, fall back to local.
if git rev-parse origin/main &>/dev/null; then
    DIFF_STAT="$(git diff --stat origin/main...HEAD 2>/dev/null || echo "  (diff unavailable)")"
else
    # Fallback: compare against the branch point if we can find it via merge-base.
    MERGE_BASE="$(git merge-base HEAD main 2>/dev/null || git rev-parse HEAD~1)"
    DIFF_STAT="$(git diff --stat "${MERGE_BASE}..HEAD" 2>/dev/null || echo "  (diff unavailable)")"
fi

FILES_CHANGED="$(echo "$DIFF_STAT" | grep -c 'file changed' || true)"
LINES_ADDED="$(echo "$DIFF_STAT" | sed -n 's/.*([0-9]* insertion.*)/\1/p')"
LINES_REMOVED="$(echo "$DIFF_STAT" | sed -n 's/.*([0-9]* deletion.*)/\1/p')"

# ── build PR body ────────────────────────────────────────────────────

BODY=$(cat <<EOF
## Summary
${TITLE}

### Commits
\`\`\`
${COMMITS_LIST}
\`\`\`

### Diff summary
- Files changed: ${FILES_CHANGED:-0}
$( [[ -n "${LINES_ADDED}" ]] && echo "- Lines added:   +${LINES_ADDED}")
$( [[ -n "${LINES_REMOVED}" ]] && echo "- Lines removed: -${LINES_REMOVED}")

---
*Generated by \`git-push-pr.sh\` on $(date -Iseconds)*
EOF
)

# ── create the PR ────────────────────────────────────────────────────
info "Creating pull request via GitHub CLI …"
PR_URL="$(gh pr create \
    --base main \
    --title "${TITLE}" \
    --body "$(echo "$BODY")" \
    2>&1)" || die "Failed to create PR. Ensure you are authenticated with \`gh auth login\`."

# gh outputs the URL on its own line; extract it cleanly.
ACTUAL_URL="$(echo "$PR_URL" | grep -o 'https://github.com/[^ ]*' | head -1 || echo "$PR_URL")"

info "Pull request created: ${ACTUAL_URL}"
echo ""
echo "${ACTUAL_URL}"
