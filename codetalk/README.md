# codetalk

Telegraphic answers for coding agents: labeled values, pseudocode and numbered steps. No filler; keep the information needed to act safely.

## Installation

Copy/paste into your CLI prompt:

```text
Install the codetalk skill from https://github.com/parsek-lab/agent-skills/tree/main/codetalk for my coding agent. Follow the agent's skill installation conventions and keep LICENSE with SKILL.md.
```

To enable codetalk permanently, add this line to your global `AGENTS.md` or `CLAUDE.md`:

```text
- Activate codetalk for every new session.
```

## Usage

- Activate: `Activate codetalk.` or `/codetalk` in Claude Code.
- Stays active across responses and topic changes.
- Deactivate: `Disable codetalk.` unless a higher-priority policy requires it.

## Examples

`>` = user message, `#` = agent context.

```text
> Rename the project
INPUT REQUIRED: "what is the new project name?"

> SQLite or PostgreSQL?
CHOICE REQUIRED:
A. SQLite — zero setup; weak with concurrent writes
B. PostgreSQL — concurrency, scaling; requires a server
RECOMMENDED: A if single-user or local

# edited src/auth.ts; tests not run
> Is it fixed?
CHANGED: src/auth.ts:42 — null check on token
NOT VERIFIED: tests
ACTION REQUIRED: npm test -- auth.spec.ts

> disable codetalk
Codetalk disabled.
```

Full rules: [SKILL.md](SKILL.md). No runtime dependencies.

## License

[AGPL-3.0-only](LICENSE).
