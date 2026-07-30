#!/usr/bin/env bash
# git-commit.sh — Conventional commit helper for exif-tagger
set -euo pipefail

if ! git diff --cached --quiet; then
    :
elif [[ -n "$(git status --porcelain)" ]]; then
    git add -A
else
    echo "Error: No changes to commit." >&2
    exit 1
fi

MSG="${1:-}"

if [[ -z "$MSG" ]]; then
    # Generate simple commit message based on modified paths
    FILES="$(git diff --cached --name-only)"
    if echo "$FILES" | grep -q "^src/"; then
        MSG="feat(core): update source implementation"
    elif echo "$FILES" | grep -q "^tests/"; then
        MSG="test: update test suite"
    elif echo "$FILES" | grep -q "^webui/"; then
        MSG="feat(webui): update frontend interface"
    else
        MSG="chore: update project configuration"
    fi
fi

git commit -m "$MSG"
