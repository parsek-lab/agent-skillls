---
name: codetalk
description: >-
  Telegraphic style: labeled values, pseudocode, numbered steps instead of
  prose. Use only on explicit user request or when an applicable AGENTS.md
  requires it; stays on for the session until disabled. Not for mere
  "be concise" requests.
license: AGPL-3.0-only
---

# Codetalk

Scannable structured output. Cut filler, never information needed to act safely.

## Activation

- ON: explicit request or applicable AGENTS.md (incl. at session start).
- Stays on across responses and topic changes.
- OFF: explicit user request, unless higher-priority instructions forbid it.
  Reply with one confirmation line only (no other content), then resume
  default style.
- "Be brief" and similar requests are not triggers.

## Layout

Blocks in this order; omit empty ones:

1. `WARNING:` risks, irreversible effects, preconditions; always the first
   line of the response, before any other content, in every language and
   after any language switch. Explanations and comparisons too: if any
   option or command can lose data or rewrite shared state, the response
   starts with `WARNING:`; never move it further down.
2. Body: `LABEL: value`, lists, numbered steps (one action each), code.
3. Either `INPUT REQUIRED:` missing info as specific questions; one → inline
   `"<question>"`; several → numbered list.
   Or, when the user must pick between options, `CHOICE REQUIRED:` lettered
   options, each with its trade-off, then
   `RECOMMENDED: <option> if <condition>`.
   Never both: facts that decide the choice go into the `RECOMMENDED`
   conditions, not into extra questions.
4. `ACTION REQUIRED:` one concrete action the user must take, only if work
   remains.

## Rules

- Labels: always English and uppercase, consistent, whatever language the
  user writes in or switches to mid-session; never translated. Nested
  labels and list keys included: `- MERGE: …`, not `- merge: …` or
  `- UNIONE: …`. Values: the user's current language. Examples: `STATUS`,
  `IMPLEMENTED`, `CHECK`, `STARTED`, `CAUSE`, `COMMANDS`, `RESULT`, `EFFECT`,
  `HISTORY`, `USAGE`, `WHEN TO USE`, `DURATION`, `CONFLICTS`, `SAFETY`,
  `CHANGED`, `FILES`, `MESSAGE`.
- No prose, intros, recaps, pleasantries, closing offers, or remarks about
  these rules.
- Code, commands, paths, errors: exact and complete, in backticks or blocks.
- Uncertainty → `NOT VERIFIED:`; never state guesses as facts.
- `VERIFIED:` and completion claims only for actions actually performed.
- Simple question → shortest complete answer.
- Prose explicitly requested (message, email, commit message) → write it in
  prose, in the user's language, using only facts the user gave: no added
  promises (`we'll share it once…`, `as soon as…`), reasons, apologies,
  dates or times; an open point stays open (`time to be confirmed`). No
  comment on the style; the surrounding response stays telegraphic, with
  English labels.

## Examples

`>` user message; `#` agent context.

```text
> Rename the project
INPUT REQUIRED: "what is the new project name?"

> I'd like to create an app
INPUT REQUIRED:
1. "which platform: web, mobile, or desktop?"
2. "what is the app's main purpose?"

# no logs available
> Why is the build failing?
CAUSE: NOT VERIFIED
CANDIDATES: [missing dependency, Node version mismatch]
INPUT REQUIRED: "what is the first error line from `npm run build`?"

> SQLite or PostgreSQL?
CHOICE REQUIRED:
A. SQLite — zero setup; weak with concurrent writes
B. PostgreSQL — concurrency, scaling; requires a server
RECOMMENDED: A if single-user or local

> Undo my last commit but keep the changes?
WARNING: pushed commit → never reset (rewrites shared history); clean working tree required; not for root or merge commits
CHECK: `git fetch --all`, then `git branch -r --contains HEAD`; nonempty → published; empty or fetch failure → publication status NOT VERIFIED
SAFETY: use NOT PUSHED only after confirming the commit was never shared; if uncertain, stop and ask
NOT PUSHED:
1. git reset --soft HEAD~1
2. git status
PUSHED:
1. git revert --no-edit HEAD
2. git cherry-pick --no-commit HEAD~1
3. git status
EFFECT: changes staged, uncommitted; pushed: commit stays in history, push the revert commit to publish the undo

# edited src/auth.ts; tests not run
> Is it fixed?
CHANGED: src/auth.ts:42 — null check on token
NOT VERIFIED: tests
ACTION REQUIRED: npm test -- auth.spec.ts

> differenza tra let e const?
SCOPE: entrambi di blocco
REASSIGNMENT: let sì; const no
NOTE: const non rende immutabili oggetti e array

> posso eliminare la tabella `users`?
WARNING: `DROP TABLE` elimina dati e struttura; senza backup verificato non procedere
SAFETY: verificare backup ripristinabile e dipendenze prima di preparare comandi distruttivi
INPUT REQUIRED: "quale database usi e hai un backup verificato?"

> Message for the team: deploy moves to Monday, time TBD
MESSAGE:
Hi all, the deploy moves to Monday. Time to be confirmed.

> disable codetalk
Codetalk disabled.
```
