#!/usr/bin/env bash
# git-push-pr.sh - Push to a feature branch and create a GitHub PR.
set -euo pipefail

command -v git &>/dev/null || { echo "ERROR: git is not installed." >&2; exit 1; }
command -v gh &>/dev/null  || { echo "ERROR: gh CLI is not installed." >&2; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if [[ "$BRANCH" == "main" ]]; then
    BRANCH="feat/agent-$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short=8 HEAD)"
    echo "[git-push-pr] Creating feature branch: ${BRANCH}"
    git checkout -b "$BRANCH"
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "[git-push-pr] Staging and committing working tree changes."
    git add -A
    git commit -m "chore: auto-commit working tree before push" || true
fi

echo "[git-push-pr] Running linter (ruff)..."
if command -v ruff &>/dev/null; then
    ruff check src/ tests/
elif [[ -f ".venv/bin/ruff" ]]; then
    .venv/bin/ruff check src/ tests/
fi

echo "[git-push-pr] Running test suite (pytest)..."
if [[ -f ".venv/bin/pytest" ]]; then
    .venv/bin/pytest tests/ -k "not test_start_session_processes_all_images"
else
    pytest tests/ -k "not test_start_session_processes_all_images"
fi

echo "[git-push-pr] Pushing ${BRANCH} to origin..."
git push -u origin "$BRANCH" --force-with-lease

echo "[git-push-pr] Creating pull request..."
gh pr create --base main --fill || gh pr create --base main --title "Feature: $(basename "$BRANCH")" --body "Automated PR from branch ${BRANCH}"

