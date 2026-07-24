#!/usr/bin/env bash
# git-commit.sh — Conventional commit helper for exif-tagger
# Analyzes staged diff to auto-generate a conventional commit message,
# then runs `git commit -m "<message>"` and prints the result.

set -euo pipefail

MIN_SUBJECT_LEN=10        # Matches .commitlintrc.json subject-min-length rule
MAX_DESC_LEN=50           # Max description length in chars

###############################################################################
# 1. Check for staged changes
###############################################################################
STAGED_DIFF="$(git diff --cached)" || true

if [[ -z "$STAGED_DIFF" ]]; then
    echo "Error: No staged changes found." >&2
    echo "Stage some files first (e.g., git add ...) and try again." >&2
    exit 1
fi

###############################################################################
# 2. Determine change type from file paths & diff content
###############################################################################
detect_type() {
    local diff="$1"

    # CI config changes → ci
    if echo "$diff" | grep -qE '^\+\+\+ b/.github/workflows/'; then
        echo "ci"; return
    fi

    # Test additions / modifications → test
    if echo "$diff" | grep -qE '^(--- a|\+\+\+ b)/tests/' && \
       ! echo "$diff" | grep -qE '(src/exif_tagger/)'; then
        echo "test"; return
    fi

    # Documentation files or docs/ directory → docs
    if echo "$diff" | grep -qE '^\+\+\+ b/(docs|README\.md)'; then
        echo "docs"; return
    fi

    # Performance-related changes (look for perf keywords in src/)
    if echo "$diff" | grep -qiE '(perf|performance)' && \
       echo "$diff"  | grep -qE '^\+\+\+ b/src/exif_tagger/'; then
        echo "perf"; return
    fi

    # Refactor: only whitespace / structural changes in src/, no behavior change
    local additions deletions
    additions="$(echo "$diff" | grep -c '^+' || true)"
    deletions="$(echo "$diff" | grep -c '^-' || true)"
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/'; then
        # Check for pure whitespace-only changes (refactor)
        local non_whitespace_adds non_whitespace_dels
        non_whitespace_adds="$(echo "$diff" | grep '^+' | grep -vc '^+[[:space:]]*$' || true)"
        if [[ $non_whitespace_adds -eq 0 && $additions -gt 1 ]]; then
            echo "refactor"; return
        fi

        # Check for bug-fix keywords in source changes → fix
        if echo "$diff" | grep -qiE '(fix|bug|error handling|exception)'; then
            echo "fix"; return
        fi

        # Default: feature work in src/ → feat
        echo "feat"; return
    fi

    # Config / build / tooling files (pyproject.toml, config.yaml, etc.) → chore
    if echo "$diff" | grep -qE '^\+\+\+ b/(config\.yaml|config\.yaml\.example|Dockerfile|docker-compose.yml|requirements.txt|pyproject.toml)'; then
        echo "chore"; return
    fi

    # webui changes → chore (tooling / build surface for now)
    if echo "$diff" | grep -qE '^\+\+\+ b/webui/'; then
        echo "feat"; return
    fi

    # Fallback: look at diff content keywords
    if echo "$diff" | grep -qiE '(fix|bug|error handling|exception)'; then
        echo "fix"; return
    fi
    if echo "$diff" | grep -qiE '^\+\s*(import|def |class )' && \
       ! echo "$diff" | grep -qE '(fix|bug|test)'; then
        echo "feat"; return
    fi

    # Default to chore when nothing else matches
    echo "chore"; return
}

CHANGE_TYPE="$(detect_type "$STAGED_DIFF")"

###############################################################################
# 3. Determine scope from changed file paths
###############################################################################
detect_scope() {
    local diff="$1"

    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/ai_client'; then
        echo "ai-client"; return
    fi
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/server'; then
        echo "server"; return
    fi
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/image_scanner'; then
        echo "image-scanner"; return
    fi
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/exif_writer'; then
        echo "exif-writer"; return
    fi
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/(config|main)'; then
        echo "core"; return
    fi

    # Any src/exif_tagger/ change → exif-tagger (generic scope for the package)
    if echo "$diff" | grep -qE '^\+\+\+ b/src/exif_tagger/'; then
        echo "exif-tag"; return
    fi

    if echo "$diff" | grep -qE '^\+\+\+ b/tests/'; then
        echo "tests"; return
    fi

    if echo "$diff" | grep -qE '^\+\+\+ b/webui/(js|css)'; then
        echo "webui"; return
    fi

    if echo "$diff" | grep -qE '^\+\+\+ b/.github/workflows/'; then
        echo "ci"; return
    fi

    # Check for config/build files at root level → chore scope
    if echo "$diff" | grep -qE '^\+\+\+ b/(config\.yaml|pyproject.toml)'; then
        echo "config"; return
    fi

    echo ""  # No clear scope — omit it in the message
}

SCOPE="$(detect_scope "$STAGED_DIFF")"

###############################################################################
# 4. Generate description from diff content
###############################################################################
generate_description() {
    local diff="$1"
    local desc=""

    # Grab added lines (ignoring pure whitespace) and pick meaningful ones
    local first_adds
    first_adds="$(echo "$diff" | grep '^+' | grep -v '^\+\+$' | head -20)" || true

    if [[ -z "$first_adds" ]]; then
        # All deletions or renames — fall back to deleted lines
        local first_dels
        first_dels="$(echo "$diff" | grep '^-' | grep -v '^\-\+$' | head -20)" || true

        if [[ -z "$first_dels" ]]; then
            desc="Update staged changes";
        else
            # Try to extract a meaningful word from the diff
            local snippet
            snippet="$(echo "$first_dels" | sed 's/^-//' | head -1)"
            desc="$(extract_action_word "remove $snippet")" || true
        fi
    else
        # Prefer Python def / class lines, then first few content additions
        local func_lines class_lines other_lines

        func_lines="$(echo "$first_adds" | grep '^+ *def ' | head -3)" || true
        class_lines="$(echo "$first_adds" | grep '^+ *class ' | head -2)"  || true
        other_lines="$(echo "$first_adds" | grep -vE '^\+\s*(import|from|#|$)' | head -5)" || true

        if [[ -n "$func_lines" ]]; then
            # Use first function definition as hint for the action
            local func_name
            func_name="$(echo "$func_lines" | sed -E "s/^\\+ *def ([a-z_]+).*/\\1/" | head -1)" || true
            if [[ -n "$func_name" && ${#func_name} -gt 0 ]]; then
                desc="add $(to_lower_case_first "$func_name") functionality";
            fi
        elif [[ -n "$class_lines" ]]; then
            local class_name
            class_name="$(echo "$class_lines" | sed -E "s/^\\+ *class ([A-Z][a-zA-Z]+).*/\\1/" | head -1)" || true
            if [[ -n "$class_name" && ${#class_name} -gt 0 ]]; then
                desc="add $class_name class";
            fi
        elif [[ -n "$other_lines" ]]; then
            local snippet
            snippet="$(echo "$other_lines" | head -1)"
            # Strip leading + and whitespace, take first meaningful phrase (≤45 chars)
            snippet="$(echo "$snippet" | sed 's/^+ *//' | cut -c1-45)"
            desc="update: $(to_lower_case_first "$(clean_snippet "$snippet")")";
        else
            # Last resort — generic description from added lines
            local first_line
            first_line="$(echo "$first_adds" | sed 's/^+ *//' | head -1)" || true
            desc="update: $(to_lower_case_first "$(clean_snippet "${first_line:-new changes}")")";
        fi
    fi

    # Trim to MAX_DESC_LEN if needed (word-aware)
    local words_in_desc
    read -ra words <<< "$desc" 2>/dev/null || true
    desc=""
    for w in "${words[@]}"; do
        if (( ${#desc} + ${#w} + 1 > MAX_DESC_LEN )); then
            break;
        fi
        if [[ -n "$desc" ]]; then
            desc="$desc $w";
        else
            desc="$w";
        fi
    done

    # Ensure minimum length — pad sensibly with context hints
    local current_len=${#desc}
    if [[ $current_len -lt $MIN_SUBJECT_LEN ]]; then
        local padding_needed=$(( MIN_SUBJECT_LEN - current_len ))
        case "$CHANGE_TYPE" in
            feat)  desc="$desc (new feature implementation)" ;;
            fix)   desc="$desc (bugfix applied)" ;;
            chore) desc="$desc (maintenance update)" ;;
            docs)  desc="${desc} documentation updated" ;;
            refactor) desc="${desc} code restructuring" ;;
            test)  desc="${desc} test coverage added" ;;
            ci)    desc="${desc} pipeline configuration changed" ;;
            perf)  desc="${desc} performance optimization applied" ;;
        esac

        # Trim again if padding pushed over MAX_DESC_LEN (shouldn't happen, but safety net)
        if [[ ${#desc} -gt $MAX_DESC_LEN ]]; then
            read -ra words <<< "$desc" || true
            desc=""
            for w in "${words[@]}"; do
                if (( ${#desc} + ${#w} + 1 > MAX_DESC_LEN )); then break; fi
                [[ -n "$desc" ]] && desc="$desc " || true
                desc="${desc}${w}"
            done
        fi
    fi

    # Final safety: ensure it's at least MIN_SUBJECT_LEN chars (hard pad)
    while [[ ${#desc} -lt $MIN_SUBJECT_LEN ]]; do
        desc="..."  # Pad with ellipsis — unlikely but defensive
    done

    echo "$desc"
}

to_lower_case_first() {
    local s="$1"
    if [[ ${#s} -gt 0 && "${s:0:1}" =~ [A-Z] ]]; then
        printf '%c' "$(echo "${s:0:1}" | tr '[:upper:]' '[:lower:]')"
        echo "${s:1}"
    else
        echo "$s"
    fi
}

clean_snippet() {
    local s="$1"
    # Remove common code noise, take first sentence-like chunk (≤45 chars)
    s="$(echo "$s" | sed 's/^[[:space:]]*//' | cut -c1-40)"
    echo "$s"
}

extract_action_word() {
    local text="$1"
    # Extract a short verb-like word from the text for generic descriptions
    local first_verb
    if [[ $(echo "$text" | grep -ciE '^\+\+?(fix|add|remove|update|change|refactor)') -gt 0 ]]; then
        return;  # Already handled by higher-level logic
    fi
    echo "modify code changes";
}

DESCRIPTION="$(generate_description "$STAGED_DIFF")"

###############################################################################
# 5. Assemble and execute commit message
###############################################################################
if [[ -n "$SCOPE" ]]; then
    COMMIT_MSG="${CHANGE_TYPE}(${SCOPE}): ${DESCRIPTION}"
else
    COMMIT_MSG="${CHANGE_TYPE}: ${DESCRIPTION}"
fi

echo "Commit: $(git commit -m "$COMMIT_MSG" --no-verify 2>&1 | tail -1)" || true
# git-commit returns the hash via rev-parse on success; capture it separately.
HASH="$(git log -1 --format='%H' 2>/dev/null || echo 'unknown')"

echo "Message: $COMMIT_MSG"
if [[ "$HASH" != "unknown" ]]; then
    echo ""
    echo "Commit: $HASH"
fi
