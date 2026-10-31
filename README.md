# agent-skills

Agent skills in the `SKILL.md` format (YAML frontmatter + Markdown instructions).

## Skills

| Skill | Purpose | Docs |
| --- | --- | --- |
| `codetalk` | Telegraphic output: labeled values, pseudocode, numbered steps instead of prose. | [`codetalk/README.md`](codetalk/README.md) |

Each skill folder holds its own `SKILL.md`, `LICENSE`, README (usage, examples, test status) and optional `evals/`.

## Installation

Requirement: an agent that loads skills from `SKILL.md` folders (e.g. Claude Code).

1. Clone:

   ```sh
   git clone https://github.com/parsek-lab/agent-skills.git
   ```

2. From the directory that contains the clone, copy a skill folder into a skills directory.

   | Agent | Scope | Directory |
   | --- | --- | --- |
   | Claude Code | personal (all projects) | `~/.claude/skills/<skill>/` |
   | Claude Code | single project | `.claude/skills/<skill>/` |
   | Other | — | that agent's skills directory |

3. Start a new agent session so the skill is loaded.

Per-skill commands: see each skill's README.

## Dependencies

None at repository level. Per-skill requirements: see each skill's README.

## License

GNU Affero General Public License v3.0 only (SPDX: `AGPL-3.0-only`). Full text: [`LICENSE`](LICENSE). Each skill folder includes an identical copy, so a copied skill keeps its license.
