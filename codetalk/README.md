# codetalk

Telegraphic output: labeled values, pseudocode, numbered steps instead of prose.

Goal: scannable structured answers. Cut filler, keep all information needed to act safely.

Instructions: `SKILL.md`. This README is documentation only; the agent loads `SKILL.md`.

## Output layout

Blocks in order; empty blocks omitted:

1. `WARNING:` risks, irreversible effects, preconditions. Always the first line, in every language and after a language switch, including explanations and comparisons that involve data loss or shared-history rewrites.
2. Body: `LABEL: value` lines, lists, numbered steps (one action each), code.
3. Either `INPUT REQUIRED:` missing information as specific questions, or `CHOICE REQUIRED:` lettered options with trade-offs, then `RECOMMENDED:` with conditions. Never both.
4. `ACTION REQUIRED:` one concrete user action, only if work remains.

## Rules

- Labels: uppercase English, never translated, including nested list keys (`- MERGE:`, not `- merge:`). Values: the user's current language.
- No intros, recaps, pleasantries, or closing offers.
- Code, commands, paths, errors: exact, in backticks or code blocks.
- Unconfirmed claims marked `NOT VERIFIED:`. `VERIFIED:` only for actions actually performed.
- Requested prose (message, email, commit message): written as prose, using only facts the user supplied; no added promises, reasons, apologies, dates or times; open points stay open.

## Installation

Run from the directory that contains the `agent-skillls` clone (for a single project: the project root, with the clone inside it or the source path adjusted).

Claude Code, personal (all projects):

```sh
mkdir -p ~/.claude/skills/codetalk
cp agent-skillls/codetalk/SKILL.md agent-skillls/codetalk/LICENSE ~/.claude/skills/codetalk/
```

Claude Code, single project:

```sh
mkdir -p .claude/skills/codetalk
cp agent-skillls/codetalk/SKILL.md agent-skillls/codetalk/LICENSE .claude/skills/codetalk/
```

Windows PowerShell, personal:

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\skills\codetalk" | Out-Null
Copy-Item agent-skillls\codetalk\SKILL.md, agent-skillls\codetalk\LICENSE "$HOME\.claude\skills\codetalk\"
```

Start a new agent session afterwards. Runtime needs only `SKILL.md`; keep `LICENSE` with it. `evals/` and this README are optional.

## Activation and deactivation

| Action | How |
| --- | --- |
| Activate | Explicit request, e.g. `Activate codetalk.` In Claude Code: `/codetalk`. |
| Activate by policy | An applicable `AGENTS.md` that requires the style; applies from session start. |
| Persistence | Stays on across responses and topic changes. |
| Deactivate | Explicit request, e.g. `Disable codetalk.` Reply: one confirmation line, then default style. |
| Not a trigger | "Be brief", "be concise" and similar requests. |

If a higher-priority instruction (e.g. `AGENTS.md`) mandates the style, a user deactivation request does not override it.

## Examples

Subset of the examples in `SKILL.md`; that file is authoritative. `>` = user message, `#` = agent context.

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

## Dependencies

- Runtime: none. Plain Markdown; no scripts, packages, or network access.
- Host: agent with `SKILL.md` skill support.
- Evals (optional, for testing only):
  - `evals/evals.json`: 16 cases, some multi-turn; machine assertions plus judge expectations.
  - `evals/run-evals.py`: runner. Python 3.9+, stdlib only. `validate` and `selftest` make no model calls; `run` needs the `claude` CLI and makes billed model calls.

## Test status

Source: `evals/static-results.json`. Raw run artifacts (`evals/runs/`) contain local paths and session ids; they are kept locally and excluded from the repository.

| Check | Result |
| --- | --- |
| Eval cases defined | 16 (English, Italian, Spanish, German) |
| Static checks | 11/11 |
| Assertion self-tests | 43/43 |
| Runner regression tests | 11/11 |
| Git example checks | 13/13 |
| Behavioral, `claude-opus-5-5`, 3 runs per eval | Pending; separate scheduled run |
| `gpt-6.1-sol`, Pi host | 43/48 runs pass automatic assertions |
| `gpt-6-astra`, Pi host | 45/48 runs pass automatic assertions |
| `deepseek-flash`, Pi host | 28/48 runs pass automatic assertions |

The three-model run covers 16 cases × 3 repetitions per model (234 user turns total), with no execution errors. Details: `evals/multimodel-results.json`. Pi uses a verified read of the skill rather than Claude Code's `Skill` tool; the host and neutral discovery prompt differ. These scores are machine checks, not full qualitative pass rates.

Limits:

- Final Opus behavioral validation is incomplete. Its earlier partial runs do not validate the current skill.
- Multimodel response review is partial: all machine failures and all requested-prose messages were inspected. Some failures are regex false negatives; raw scores remain unchanged. DeepSeek also produced translated labels, wrong-language responses and a factual branch-deletion error.
- Direct second-pass review is recorded in `evals/release-review.json`; it is not an external independent review.
- Machine assertions use heuristics; passing them does not replace review of the actual responses.
- The runner records residual host instructions and rejects detected style mandates, third-party plugins, MCP servers and wrong skill copies.

From the repository root:

```sh
python codetalk/evals/run-evals.py validate
python codetalk/evals/run-evals.py selftest
python -I codetalk/evals/test_runner.py
python -I codetalk/evals/test_models.py
python -I codetalk/evals/ct-static-checks.py codetalk
python -I codetalk/evals/ct-git-example-check.py codetalk codetalk/evals/runs/git-check-fresh
python codetalk/evals/run-evals.py run --model claude-opus-5-5 --runs 3 --out codetalk/evals/runs/final
```

Cross-model validation (requires the authenticated Pi CLI; makes model calls):

```sh
python codetalk/evals/run-models.py --runs 3 --out codetalk/evals/runs/multimodel-fresh
```

Use a fresh output directory for each run. If preflight detects another installed copy, read the runner help before using `--allow-user-skill`; each actual skill load is still verified. Model runs require account access and consume quota.

## License

GNU Affero General Public License v3.0 only (SPDX: `AGPL-3.0-only`, also in `SKILL.md` frontmatter). Full text: [`LICENSE`](LICENSE), identical to the repository root copy.
