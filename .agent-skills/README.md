# Agent Skills — Unified Directory

This directory is the **single source of truth** for all AI agent skills in this project.

Both `opencode` and `antigravity` (agy) read skills from their own tool-specific paths,
which are symlinks pointing here:

| Tool | Path | → Resolves to |
|------|------|----------------|
| Antigravity (agy) | `.gemini/skills/` | `.agent-skills/` |
| opencode | `.opencode/skills/` | `.agent-skills/` |

## Adding a new skill

Create a folder here with a `SKILL.md` file using YAML frontmatter:

```yaml
---
name: my-skill-name
description: One-line description of when this skill should be invoked.
---

# My Skill

...skill instructions...
```

The skill will automatically be available to **both** CLI tools.

## Disabling a skill for one tool only

Skills are picked up by both tools. If you need a skill only for one tool, name it
`SKILL.md.disabled` (disabled) and document the reason in its frontmatter.

## Skills in this directory

| Skill | Status | Description |
|-------|--------|-------------|
| `exif-tagger-ui-patterns` | ✅ active | Design system, color tokens, Shadcn conventions, and custom hook patterns for the React web app |
| `delegate-context7` | 🔒 disabled | Delegate doc/library lookups to a context7 subagent |
| `delegate-github` | 🔒 disabled | Delegate GitHub PR/issue actions to a subagent |
| `github-actions-hardening` | 🔒 disabled | Security reviewer for GitHub Actions workflows |
