#!/usr/bin/env bash
# start-feature.sh — Always starts a new feature branch synced with the latest origin/main
set -euo pipefail

NAME="${1:-}"
if [[ -z "$NAME" ]]; then
    echo "Usage: ./scripts/start-feature.sh <feature-name>" >&2
    exit 1
fi

echo "[start-feature] Fetching latest origin/main..."
git fetch origin main

BRANCH_NAME="feature/${NAME}"
echo "[start-feature] Creating and checking out branch '${BRANCH_NAME}' from origin/main..."
git checkout -b "$BRANCH_NAME" origin/main

echo "[start-feature] Successfully created '${BRANCH_NAME}' synced with latest origin/main!"
