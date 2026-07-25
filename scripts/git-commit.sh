#!/usr/bin/env bash
# git-commit.sh — Conventional commit helper for exif-tagger
# Analyzes staged diff to auto-generate a conventional commit message,
# then runs `git commit -m "<message>"` and prints the result.

die() { echo "[git-commit] ERROR: $*" >&2; exit 1; }

MIN_SUBJECT_LEN=10        # Matches .commitlintrc.json subject-min-length rule
MAX_DESC_LEN=50           # Max description length in chars

TMPFILE="$(mktemp)" || die "Cannot create temp file"
trap 'rm -f "$TMPFILE"' EXIT

###############################################################################
# 1. Check for staged changes
###############################################################################
git diff --cached >"$TMPFILE" || true

if [[ ! -s "$TMPFILE" ]]; then
    echo "Error: No staged changes found." >&2
    echo "Stage some files first (e.g., git add ...) and try again." >&2
    exit 1
fi

###############################################################################
# 2. Determine change type from file paths & diff content
###############################################################################
detect_type() {
    local f="$1"

    # CI config changes → ci
    if grep -qE '^\+\+\+ b/.github/workflows/' "$f"; then
        echo "ci"; return
    fi

    # Test additions / modifications → test
    if grep -qE '^(--- a|\+\+\+ b)/tests/' "$f" && \
       ! grep -qE '(src/exif_tagger/)' "$f"; then
        echo "test"; return
    fi

    # Documentation files or docs/ directory → docs
    if grep -qE '^\+\+\+ b/(docs|README\.md)' "$f"; then
        echo "docs"; return
    fi

    # Performance-related changes (look for perf keywords in src/)
    if grep -qiE '(perf|performance)' "$f" && \
       grep -qE '^\+\+\+ b/src/exif_tagger/' "$f"; then
        echo "perf"; return
    fi

    # Refactor: only whitespace / structural changes in src/, no behavior change
    local additions deletions
    additions="$(grep -c '^+' "$f" || true)"
    deletions="$(grep -c '^-' "$f" || true)"
    if grep -qE '^\+\+\+ b/src/exif_tagger/' "$f"; then
        # Check for pure whitespace-only changes (refactor)
        local non_whitespace_adds
        non_whitespace_adds="$(grep '^+' "$f" | grep -vc '^+[[:space:]]*$' || true)"
        if [[ $non_whitespace_adds -eq 0 && $additions -gt 1 ]]; then
            echo "refactor"; return
        fi

        # Check for bug-fix keywords in source changes → fix
        if grep -qiE '(fix|bug|error handling|exception)' "$f"; then
            echo "fix"; return
        fi

        # Default: feature work in src/ → feat
        echo "feat"; return
    fi

    # Config / build / tooling files (pyproject.toml, config.yaml, etc.) → chore
    if grep -qE '^\+\+\+ b/(config\.yaml|config\.yaml\.example|Dockerfile|docker-compose.yml|requirements.txt|pyproject.toml)' "$f"; then
        echo "chore"; return
    fi

    # webui changes → chore (tooling / build surface for now)
    if grep -qE '^\+\+\+ b/webui/' "$f"; then
        echo "feat"; return
    fi

    # Fallback: look at diff content keywords
    if grep -qiE '(fix|bug|error handling|exception)' "$f"; then
        echo "fix"; return
    fi
    if grep -qiE '^\+\s*(import|def |class )' "$f" && \
       ! grep -qE '(fix|bug|test)' "$f"; then
        echo "feat"; return
    fi

    # Default to chore when nothing else matches
    echo "chore"; return
}

CHANGE_TYPE="$(detect_type "$TMPFILE")"

###############################################################################
# 3. Determine scope from changed file paths
###############################################################################
detect_scope() {
    local f="$1"

    if grep -qE '^\+\+\+ b/src/exif_tagger/ai_client' "$f"; then
        echo "ai-client"; return
    fi
    if grep -qE '^\+\+\+ b/src/exif_tagger/server' "$f"; then
        echo "server"; return
    fi
    if grep -qE '^\+\+\+ b/src/exif_tagger/image_scanner' "$f"; then
        echo "image-scanner"; return
    fi
    if grep -qE '^\+\+\+ b/src/exif_tagger/exif_writer' "$f"; then
        echo "exif-writer"; return
    fi
    if grep -qE '^\+\+\+ b/src/exif_tagger/(config|main)' "$f"; then
        echo "core"; return
    fi

    # Any src/exif_tagger/ change → exif-tagger (generic scope for the package)
    if grep -qE '^\+\+\+ b/src/exif_tagger/' "$f"; then
        echo "exif-tag"; return
    fi

    if grep -qE '^\+\+\+ b/tests/' "$f"; then
        echo "tests"; return
    fi

    if grep -qE '^\+\+\+ b/webui/(js|css)' "$f"; then
        echo "webui"; return
    fi

    if grep -qE '^\+\+\+ b/.github/workflows/' "$f"; then
        echo "ci"; return
    fi

    # Check for config/build files at root level → chore scope
    if grep -qE '^\+\+\+ b/(config\.yaml|pyproject.toml)' "$f"; then
        echo "config"; return
    fi

    echo ""  # No clear scope — omit it in the message
}

SCOPE="$(detect_scope "$TMPFILE")"

###############################################################################
# 4. Generate description from diff content
###############################################################################
generate_description() {
    local f="$1"
    local desc=""

    # Grab added lines (ignoring pure whitespace) and pick meaningful ones
    local first_adds
    first_adds="$(grep '^+' "$f" | grep -v '^\+\+$' | head -20)" || true

    if [[ -z "$first_adds" ]]; then
        # All deletions or renames — fall back to deleted lines
        local first_dels
        first_dels="$(grep '^-' "$f" | grep -v '^\-\+$' | head -20)" || true

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

echo "Commit: $(git commit -m "$COMMIT_MSG" 2>&1 | tail -1)" || true
# git-commit returns the hash via rev-parse on success; capture it separately.
HASH="$(git log -1 --format='%H' 2>/dev/null || echo 'unknown')"

echo "Message: $COMMIT_MSG"
if [[ "$HASH" != "unknown" ]]; then
    echo ""
    echo "Commit: $HASH"
fi
