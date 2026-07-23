# exif-tagger — Versioning, Branching & CI/CD Design

**Date:** 2026-07-23
**Status:** Approved

---

## 1. Versioning Strategy

### Scheme: Semantic Versioning (SemVer)

Format: `MAJOR.MINOR.PATCH` (e.g., `0.1.0`, `0.2.0`, `0.1.1`)

- **Pre-1.0:** The project is at `0.1.0`. Minor bumps for new features, patch bumps for bugfixes. Breaking changes are allowed and will bump the minor version.
- **Version source of truth:** `version` field in `pyproject.toml`
- **Git tags:** Every stable release gets a git tag prefixed with `v` (e.g., `v0.1.0`, `v0.2.0`)

### Version Bump Rules

| Change type | Bump | Example |
|-------------|------|---------|
| New feature | Minor | `0.1.0` → `0.2.0` |
| Bugfix | Patch | `0.1.0` → `0.1.1` |
| Breaking change (pre-1.0) | Minor | `0.1.0` → `0.2.0` |

### Automated Version Bumping

On PR merge to `main`, CI determines the next version by scanning all commits in the PR:
- If any commit is `feat(...)` or higher → minor bump (e.g., `0.1.x` → `0.2.0`)
- Else if any commit is `fix(...)` → patch bump (e.g., `0.1.0` → `0.1.1`)
- Else → no version change (docs, chore, refactor, etc.)

The bumped version is written to `pyproject.toml`, committed as part of the merge, and used for the git tag and Docker image tags. If multiple PRs are merged close together, the version bump uses the current `pyproject.toml` value at merge time (no conflict resolution needed — each merge reads the latest).

---

## 2. Branching Strategy — GitHub Flow

### Branch Model

```
main (protected, always deployable)
├── feat/add-exif-export    ← feature branches
├── fix/handle-corrupt-image
└── chore/update-deps
```

- **Single branch:** `main` is the only long-lived branch. It must always be buildable and testable.
- **Feature branches:** Short-lived, named with a type prefix:
  - `feat/<description>` — new features
  - `fix/<description>` — bugfixes
  - `docs/<description>` — documentation changes
  - `chore/<description>` — maintenance tasks
  - `refactor/<description>` — code refactoring
- **All work via PRs:** No direct pushes to `main`. Every change goes through a pull request.

### Branch Lifecycle

1. Create branch from `main`: `git checkout -b feat/my-feature main`
2. Make commits (following Conventional Commits)
3. Push and open PR to `main`
4. CI runs (lint + tests)
5. Review and approve PR
6. Merge to `main` — delete branch

### Protected Branch Rules for `main`

- Require status checks to pass before merging (CI lint + tests)
- Require at least 1 approval (human or agent reviewer)
- Dismiss stale pull request approvals when new commits are pushed
- Include administrators in restrictions (optional, configurable)

---

## 3. Docker Image Tagging — Hybrid Strategy

### Trigger Matrix

| Event | Docker tags produced |
|-------|---------------------|
| Push to `main` (not via PR merge) | `latest-beta`, `<sha-short>` |
| PR merged to `main` | `v<version>`, `latest`, `<sha-short>` |
| Git tag pushed (`v*`) | `v<tag>`, `<sha-short>` |
| Feature branch push | `<branch-name>-<sha-short>` (no `latest` or `beta` tags) |

### Tag Naming Convention

- **Stable releases:** `v0.1.0`, `v0.2.0` — matches git tag and pyproject.toml version
- **Beta builds:** `latest-beta` — always points to the latest push to main
- **Latest stable:** `latest` — updated only on PR merges (not direct pushes)
- **Commit reference:** `<sha-short>` (e.g., `a3f2b1c`) — always included for traceability
- **Branch builds:** `<branch-slug>-<sha-short>` (e.g., `feat-add-export-a3f2b1c`)

### Docker Build Flow

```
Push to main ──→ CI passes ──→ Build image → Push as latest-beta + <sha>
PR merge ─────→ CI passes ──→ Bump version in pyproject.toml
                              Create git tag v<version>
                              Build image → Push as v<version>, latest, <sha>
Tag push (v*) ────────────────→ Build image → Push as v<tag>, <sha>
Feature branch ───────────────→ Build image → Push as <branch>-<sha>
```

---

## 4. Commit Message Convention — Conventional Commits

### Format

```
type(scope): description

[optional body]

[optional footer(s)]
```

### Allowed Types

| Type | Purpose | Triggers version bump? |
|------|---------|----------------------|
| `feat` | New feature | Yes (minor) |
| `fix` | Bugfix | Yes (patch) |
| `docs` | Documentation only | No |
| `style` | Formatting, semicolons, etc. | No |
| `refactor` | Code change that neither fixes nor adds features | No |
| `perf` | Performance improvement | No |
| `test` | Adding or updating tests | No |
| `build` | Build system or dependency changes | No |
| `ci` | CI configuration changes | No |
| `chore` | Other changes (tooling, config) | No |
| `revert` | Reverting a previous commit | Yes (reverse bump) |

### Rules

- Scope is **optional** but encouraged for clarity: `feat(server): ...`, `fix(scanner): ...`
- Description must be lowercase, imperative mood: `add endpoint` not `added endpoint` or `adds endpoint`
- No period at the end of the description line
- Body and footer are optional

### Examples

```
feat(server): add image preview endpoint with thumbnail support

fix(exif-writer): handle missing orientation tag gracefully

ci: add Docker build workflow for multi-arch images

chore(deps): bump fastapi to 0.115.0

refactor(scanner): extract batch scanning logic into separate module
```

### Enforcement

- **Local:** Husky `commit-msg` hook using `commitlint` runs before every commit, rejecting non-conforming messages
- **CI:** A CI check validates commit messages on PRs to `main`, failing if any commit violates the convention

---

## 5. Files to Create/Modify

### New files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Lint and test checks on PRs and pushes |
| `.github/workflows/release.yml` | Docker build, tagging, and publishing |
| `.husky/commit-msg` | Local commit message validation hook |

### Modified files

| File | Change |
|------|--------|
| `pyproject.toml` | Add `auto_bump_version` script reference (no version change needed) |
| Repository settings | Enable branch protection for `main` (via GitHub UI or API) |

---

## 6. CI/CD Pipeline Details

### CI Workflow (`ci.yml`) — triggers on: PRs, push to main, feature branches

1. **Checkout code**
2. **Set up Python** (3.12+)
3. **Install dependencies** from `pyproject.toml` and `requirements.txt`
4. **Lint:** Run `ruff check` for style/linting
5. **Test:** Run `pytest tests/` with coverage report
6. **Docker build (no push):** Build image to verify Dockerfile works

### Release Workflow (`release.yml`) — triggers on: PR merge to main, tag push

1. **Checkout code**
2. **Set up Python and QEMU** (for multi-arch builds)
3. **Docker metadata:** Extract version from `pyproject.toml`, generate tags
4. **Build & push Docker image:** Multi-platform (linux/amd64, linux/arm64)
5. **Tag routing:** Apply correct tags based on trigger type (see Section 3)

---

## 7. Workflow Summary — Agent Example

```
Agent workflow:
1. git checkout -b feat/add-video-support main
2. Make changes, commit with conventional commits
3. git push origin feat/add-video-support
4. Open PR to main → CI runs (lint + tests)
5. If CI passes → merge PR
6. Release workflow triggers → version bumped, Docker image tagged v0.2.0 + latest
```
