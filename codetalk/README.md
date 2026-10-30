# codetalk

Telegraphic answers for coding agents: labeled values, pseudocode and numbered steps. No filler; keep the information needed to act safely.

## Installation

Copy/paste into your CLI prompt:

```text
Install the codetalk skill from https://github.com/parsek-lab/agent-skillls/tree/main/codetalk for my coding agent. Follow the agent's skill installation conventions and keep LICENSE with SKILL.md.
```

## Usage

- Activate: `Activate codetalk.` or `/codetalk` in Claude Code.
- Stays active across responses and topic changes.
- Deactivate: `Disable codetalk.` unless a higher-priority policy requires it.

## Example

```text
CHOICE REQUIRED:
A. SQLite — zero setup; limited concurrent writes
B. PostgreSQL — concurrency and scaling; requires a server
RECOMMENDED: A if single-user or local
```

Full rules: [SKILL.md](SKILL.md). No runtime dependencies.

## License

[AGPL-3.0-only](LICENSE).
