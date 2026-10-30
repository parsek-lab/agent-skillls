#!/usr/bin/env python3
"""Runner for codetalk/evals/evals.json (schema_version 2).

Commands (paths relative to the repo root; Python 3.9+, stdlib only):

  python codetalk/evals/run-evals.py validate
      Check evals.json structure and regexes. No model calls.
  python codetalk/evals/run-evals.py selftest
      Check the assertion engine and the eval assertions on built-in samples. No model calls.
  python codetalk/evals/run-evals.py run --model claude-opus-5-5 [--ids 1,9] [--runs 3]
                                         [--out DIR] [--work-root DIR] [--config-dir DIR]
                                         [--skill-mode project|system-prompt] [--dry-run]
      Execute every turn with `claude -p` (one session per eval run), grade, write results.
      --dry-run: preflight and print the commands only. No model calls.
  python codetalk/evals/run-evals.py grade OUT_DIR
      Re-grade saved transcripts (OUT_DIR/eval-<id>/run-<n>/transcript.json) offline.

Format compatibility:
  - evals.json stays a superset of the skill-creator v1 schema: `skill_name`, `evals[].id`,
    `prompt`, `expected_output`, `files`, `expectations` keep their meaning.
  - `prompt` == turns[0].user. A single-prompt runner only covers turns[0]; evals with
    `multi_turn: true` must be skipped or reported as not run by such runners.
  - Output per run: transcript.json and grading.json. grading.json follows skill-creator's
    grading.json (`expectations[{text, passed, evidence}]`, `summary{passed, failed, total,
    pass_rate}`) and adds `status` per expectation (passed | failed | not_verified | not_run)
    and `summary.not_verified` / `summary.not_run`. Only machine assertions are graded here;
    `expectations` from evals.json are copied to `judge_expectations` for a human/LLM grader
    and are not counted.

Isolation (enforced by `run`; preflight violations exit 2, per-run violations fail the run):
  - Each eval run gets a fresh workspace with no instruction files. Instruction files in the
    workspace's ancestors and the user config (AGENTS.md, CLAUDE.md, ...) that mention
    codetalk/telegraphic style abort the run; others are recorded in run-meta.json.
  - claude is launched with --setting-sources project,local (no user settings or hooks),
    --strict-mcp-config (no MCP servers) and an environment without the parent Claude Code
    session's variables (CLAUDE_CODE_PLUGIN_DIRS, CLAUDE_EFFORT, session ids, sockets; see
    LEAKED_ENV). The child's init event is recorded per turn; a non-builtin plugin or an MCP
    server fails the run.
  - Every Skill load is checked: a codetalk skill loaded from outside the run's workspace, or
    whose text differs from the SKILL.md under test, fails the run. A user-level `codetalk`
    skill that differs aborts preflight unless --allow-user-skill (the per-load check then
    proves which copy was used).
  - The model is never substituted: no --fallback-model; a turn whose reported modelUsage is
    empty or lacks the requested model, or whose assistant messages come from another model,
    fails the run.

Exit codes: 0 all assertions passed; 1 some failed, were not verified, or a run errored;
2 invalid config/preflight.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_EVALS = HERE / "evals.json"
DEFAULT_SKILL = HERE.parent / "SKILL.md"
LEGACY_IDS = range(1, 9)

INSTRUCTION_FILES = ["AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md",
                     ".claude/CLAUDE.md", "GEMINI.md"]
STYLE_MANDATE = re.compile(r"codetalk|telegraphic|labeled values", re.IGNORECASE)

# Variables a parent Claude Code session exports to its tools; a child `claude -p` would
# inherit plugin dirs, effort and session identity from them.
LEAKED_ENV = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID",
              "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
              "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
              "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_SSE_PORT",
              "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT"]

STOPWORDS = {
    "en": "the and of to is are with without your before after this that it not be".split(),
    "it": ("il lo gli di che non per con una un del della delle dei nel nella sono è si "
           "anche più come questo questa da").split(),
    "es": "el los las que para por sin una del es está pero con como al lo se y".split(),
    "de": ("der die das und nicht mit für ist ein eine bei wenn kein keine oder auf zu den "
           "dem sich wird sind").split(),
}

# Words that mark a label as translated, checked by every `labels` assertion. Words that are
# also English (NOTE, FILE, STATUS, LOCALE, COME...) are deliberately absent.
TRANSLATED_LABEL_WORDS = {
    "it": ("ATTENZIONE AVVISO AVVERTENZA AVVERTIMENTO COMANDI COMANDO PASSI PASSAGGI NOTA "
           "EFFETTO EFFETTI RISULTATO RISULTATI VERIFICA VERIFICATO CONTROLLO CONTROLLA STORIA "
           "CRONOLOGIA CONFLITTI SICUREZZA RISCHIO RISCHI USO UTILIZZO QUANDO USARE DIFFERENZA "
           "DIFFERENZE CAUSA CAUSE STATO MODIFICATO MODIFICHE DURATA AMBITO RIASSEGNAZIONE "
           "RICHIESTO RICHIESTA RICHIESTE RICHIESTI DATI DOMANDE INFORMAZIONI SCELTA CONSIGLIATO "
           "RACCOMANDATO RACCOMANDAZIONE AZIONE VANTAGGI SVANTAGGI ESEMPIO ESEMPI PREREQUISITI "
           "RECUPERO REMOTO UNIONE SINTASSI COMPORTAMENTO PRESTAZIONI MESSAGGIO FORZATO SICURO "
           "ELIMINAZIONE CANCELLAZIONE").split(),
    "es": ("ADVERTENCIA AVISO PASOS COMANDOS EFECTO EFECTOS RESULTADO VERIFICAR COMPROBAR "
           "ENVIADO PUBLICADO HISTORIAL CONFLICTOS SEGURIDAD RIESGO CUANDO USAR DIFERENCIA "
           "DIFERENCIAS ESTADO CAMBIOS CAMBIADO ARCHIVOS DURACION ENTRADA REQUERIDA REQUERIDO "
           "ELECCION RECOMENDADO RECOMENDACION ACCION VERIFICADO EJEMPLO VENTAJAS DESVENTAJAS "
           "MENSAJE REMOTA REMOTO").split(),
    "de": ("WARNUNG HINWEIS BEFEHLE BEFEHL SCHRITTE ERGEBNIS WIRKUNG PRUEFUNG PRUEFEN AUSWAHL "
           "ENTSCHEIDUNG WAHL ERFORDERLICH EMPFOHLEN EMPFEHLUNG VERLAUF GESCHICHTE KONFLIKTE "
           "SICHERHEIT VERWENDUNG NUTZUNG WANN UNTERSCHIED UNTERSCHIEDE URSACHE GEAENDERT "
           "DATEIEN DAUER EINGABE AKTION VORTEILE NACHTEILE RISIKO BEISPIEL NACHRICHT LOESCHEN "
           "ERZWINGEN SICHER GEPUSHT ENTFERNT").split(),
}

LABEL_LINE = re.compile(r"^\s*(?:[-*]\s+)?([^\W\d_][\w &/-]{0,39}?)\s*:(?!//)(?:\s|$)")
VALID_LABEL = re.compile(r"[A-Z][A-Z0-9 _&/-]*")
SKILL_BASE = re.compile(r"Base directory for this skill: ([^\r\n]+)")

ASSERTION_PARAMS = {
    "first_line": {"pattern"},
    "head": {"lines", "pattern"},
    "regex": {"pattern"},
    "ordered": {"patterns"},
    "nonempty_lines": set(),
    "labels": set(),
    "language": {"lang"},
    "skill": {"invoked"},
}


# ---------------------------------------------------------------- text helpers

def nonempty_lines(text):
    return [line for line in text.splitlines() if line.strip()]


def outside_fences(text):
    lines, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line.replace("**", ""))  # `**LABEL:**` is still a label
    return lines


def find_labels(text):
    labels = []
    for line in outside_fences(text):
        m = LABEL_LINE.match(line)
        if m and len(m.group(1).split()) <= 5:
            labels.append(m.group(1).strip())
    return labels


def translated(label):
    words = set(re.split(r"[ _&/-]+", label.upper()))
    return sorted(lang for lang, vocab in TRANSLATED_LABEL_WORDS.items() if words & set(vocab))


def value_text(text):
    out = []
    for line in outside_fences(text):
        m = LABEL_LINE.match(line)
        if m and len(m.group(1).split()) <= 5:
            line = line[m.end():]
        out.append(re.sub(r"`[^`]*`", " ", line))
    return "\n".join(out)


def in_range(n, lo, hi):
    return n >= (lo or 0) and (hi is None or n <= hi)


def range_str(lo, hi):
    return f"[{lo or 0}, {'inf' if hi is None else hi}]"


def normalize(text):
    return text.replace("\r\n", "\n").strip()


def skill_body(skill_text):
    """SKILL.md without frontmatter: the part Claude Code injects when the skill loads."""
    return normalize(re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", skill_text, count=1, flags=re.S))


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- assertions

def check(a, text, turn=None):
    """Return (passed, evidence) for one assertion; passed is None when not verifiable."""
    t = a["type"]
    flags = re.MULTILINE | (re.IGNORECASE if a.get("ignore_case") else 0)
    lines = nonempty_lines(text)
    if t == "first_line":
        first = lines[0] if lines else ""
        return bool(re.search(a["pattern"], first, flags)), f"first line: {first[:120]!r}"
    if t == "head":
        head = "\n".join(lines[:a["lines"]])
        ok = bool(re.search(a["pattern"], head, flags))
        return ok, f"{'found' if ok else 'not found'} in first {a['lines']} lines"
    if t == "regex":
        hits = [m.group(0) for m in re.finditer(a["pattern"], text, flags)]
        hi = a.get("max")
        lo = a.get("min", 1 if hi is None else 0)
        shown = f" {hits[:3]!r}" if hits and hi is not None else ""
        return in_range(len(hits), lo, hi), f"{len(hits)} matches{shown}, expected {range_str(lo, hi)}"
    if t == "ordered":
        pos = 0
        for p in a["patterns"]:
            m = re.compile(p, flags).search(text, pos)
            if not m:
                return False, f"missing after offset {pos}: {p!r}"
            pos = m.end()
        return True, "all patterns in order"
    if t == "nonempty_lines":
        lo, hi = a.get("min", 0), a.get("max")
        return in_range(len(lines), lo, hi), f"{len(lines)} lines, expected {range_str(lo, hi)}"
    if t == "labels":
        labels = find_labels(text)
        forbidden = {f.upper() for f in a.get("forbidden", [])}
        bad = [l for l in labels if not VALID_LABEL.fullmatch(l) or l.upper() in forbidden]
        foreign = [l for l in labels if l not in bad and translated(l)]
        lo, hi = a.get("min", 0), a.get("max")
        ok = not bad and not foreign and in_range(len(labels), lo, hi)
        return ok, (f"labels={labels} invalid={bad} translated={foreign} "
                    f"count expected {range_str(lo, hi)}")
    if t == "language":
        words = re.findall(r"[^\W\d_]+", value_text(text).lower())
        stop = set(STOPWORDS[a["lang"]])
        n = sum(w in stop for w in words)
        lo, hi = a.get("min", 0), a.get("max")
        return in_range(n, lo, hi), f"{n} '{a['lang']}' stopwords, expected {range_str(lo, hi)}"
    if t == "skill":
        name = a.get("name", "codetalk")
        if turn is None or "skill_calls" not in turn:
            return None, "NOT VERIFIED: transcript has no Skill tool data"
        n = turn["skill_calls"].count(name)
        want = a["invoked"]
        return (n > 0) == want, f"{name} invoked {n}x in this turn, expected {'>= 1' if want else 0}"
    raise ValueError(f"unknown assertion type {t}")


def grade(case, turns):
    """turns: per-turn transcript records (dict with `response`), None for turns not run."""
    results = []
    for i, (spec, turn) in enumerate(zip(case["turns"], turns), 1):
        for a in spec.get("assertions", []):
            text = f"T{i}: {a.get('desc', a['type'])}"
            if turn is None:
                results.append({"text": text, "passed": False, "status": "not_run",
                                "evidence": "turn not executed"})
                continue
            ok, ev = check(a, turn["response"], turn)
            status = "not_verified" if ok is None else "passed" if ok else "failed"
            results.append({"text": text, "passed": ok is True, "status": status, "evidence": ev})
    count = {s: sum(r["status"] == s for r in results)
             for s in ("passed", "failed", "not_verified", "not_run")}
    total = len(results)
    return {
        "eval_id": case["id"],
        "expectations": results,
        "summary": {**count, "total": total,
                    "pass_rate": round(count["passed"] / total, 2) if total else 1.0},
        "judge_expectations": case.get("expectations", []),
    }


# ---------------------------------------------------------------- validation

def validate(data):
    errors = []
    if data.get("skill_name") != "codetalk":
        errors.append("skill_name must be 'codetalk'")
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        return errors + ["evals must be a non-empty list"]
    ids = [e.get("id") for e in evals]
    if (len(ids) != len(set(ids))
            or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids)):
        errors.append(f"ids must be unique positive integers: {ids}")
    missing = [i for i in LEGACY_IDS if i not in ids]
    if missing:
        errors.append(f"legacy ids missing: {missing}")
    for e in evals:
        where = f"eval {e.get('id')}"
        for key, typ in (("intent", str), ("prompt", str), ("expected_output", str),
                         ("files", list), ("turns", list), ("multi_turn", bool),
                         ("expectations", list)):
            if not isinstance(e.get(key), typ):
                errors.append(f"{where}: `{key}` must be {typ.__name__}")
        if isinstance(e.get("intent"), str) and not e["intent"].strip():
            errors.append(f"{where}: `intent` must not be empty")
        turns = e.get("turns") or []
        if not turns:
            errors.append(f"{where}: turns empty")
            continue
        if e.get("prompt") != turns[0].get("user"):
            errors.append(f"{where}: prompt must equal turns[0].user")
        if e.get("multi_turn") != (len(turns) > 1):
            errors.append(f"{where}: multi_turn must be {len(turns) > 1}")
        if re.search(r"\bTurn \d+:", e.get("prompt", "")):
            errors.append(f"{where}: pseudo multi-turn text in prompt")
        if not any(t.get("assertions") for t in turns):
            errors.append(f"{where}: no assertions")
        for ti, t in enumerate(turns, 1):
            if not isinstance(t.get("user"), str) or not t["user"].strip():
                errors.append(f"{where} T{ti}: `user` must be a non-empty string")
            for a in t.get("assertions", []):
                typ = a.get("type")
                if typ not in ASSERTION_PARAMS:
                    errors.append(f"{where} T{ti}: unknown assertion type {typ!r}")
                    continue
                if not ASSERTION_PARAMS[typ] <= a.keys():
                    errors.append(f"{where} T{ti}: {typ} needs {sorted(ASSERTION_PARAMS[typ])}")
                    continue
                if typ == "language" and a["lang"] not in STOPWORDS:
                    errors.append(f"{where} T{ti}: unsupported lang {a['lang']!r}")
                if typ == "skill" and not isinstance(a["invoked"], bool):
                    errors.append(f"{where} T{ti}: skill.invoked must be true or false")
                lo, hi = a.get("min"), a.get("max")
                for v in (lo, hi, a.get("lines")):
                    if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                        errors.append(f"{where} T{ti}: min/max/lines must be integers >= 0")
                if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
                    errors.append(f"{where} T{ti}: min > max")
                for p in a.get("patterns", []) + ([a["pattern"]] if "pattern" in a else []):
                    try:
                        re.compile(p)
                    except re.error as exc:
                        errors.append(f"{where} T{ti}: bad regex {p!r}: {exc}")
    return errors


# ---------------------------------------------------------------- selftest

SELFTEST = [
    # (assertion, response, expected[, turn record])
    ({"type": "first_line", "pattern": "^WARNING:"},
     "\nWARNING: -D deletes unmerged work\nCOMMANDS:\n1. git branch -d x", True),
    ({"type": "first_line", "pattern": "^WARNING:"}, "ATTENZIONE: -D elimina", False),
    ({"type": "head", "lines": 1, "pattern": "-D\\b"}, "WARNING: x\n-D later", False),
    ({"type": "regex", "pattern": "^\\s*\\d+\\.\\s", "max": 0}, "INPUT REQUIRED: \"name?\"", True),
    ({"type": "regex", "pattern": "^\\s*\\d+\\.\\s", "min": 2}, "INPUT REQUIRED:\n1. \"a?\"", False),
    ({"type": "ordered", "patterns": ["^CHOICE REQUIRED:", "^A\\.", "^B\\.", "^RECOMMENDED:"]},
     "CHOICE REQUIRED:\nA. SQLite — x\nB. PostgreSQL — y\nRECOMMENDED: A if local", True),
    ({"type": "ordered", "patterns": ["^CHOICE REQUIRED:", "^RECOMMENDED:"]},
     "RECOMMENDED: A\nCHOICE REQUIRED:", False),
    ({"type": "nonempty_lines", "max": 1}, "Codetalk disabled.\n", True),
    ({"type": "nonempty_lines", "max": 1}, "Codetalk disabled.\nAnything else?", False),
    ({"type": "labels", "min": 3},
     "WARNING: rebase rewrites history\nMERGE:\n- HISTORY: preserved\n- CONFLICTS: once\n"
     "```\nnote: inside code is ignored\n```\nA. option without colon", True),
    ({"type": "labels"}, "WARNING: x\n- History: preserved", False),
    ({"type": "labels", "forbidden": ["ATTENZIONE"]}, "ATTENZIONE: -D elimina", False),
    ({"type": "labels"}, "Fonte: https://example.com\nOK: yes", False),
    ({"type": "labels"}, "URL: https://example.com", True),
    # translated labels are caught without a per-eval list; English look-alikes are not
    ({"type": "labels"}, "MERGE: unisce\nSICUREZZA: merge sicuro", False),
    ({"type": "labels"}, "WARNING: x\nHISTORY:\n- STORIA: lineare", False),
    ({"type": "labels"}, "WARNING: x\nNOT MERGED: rifiuta\nREMOTE: non toccato\nNOTE: y", True),
    ({"type": "labels"}, "**Storia:** lineare", False),
    ({"type": "labels"}, "**HISTORY:** lineare", True),
    ({"type": "labels"}, "HISTORY:\n- merge: ramificata\n- rebase: lineare", False),
    ({"type": "language", "lang": "it", "min": 3},
     "WARNING: `-D` elimina il branch anche se non è unito\nEFFECT: il branch non esiste più", True),
    ({"type": "language", "lang": "en", "max": 2},
     "WHEN TO USE: per rami locali\nHISTORY: lineare con rebase", True),
    ({"type": "language", "lang": "en", "max": 2},
     "HISTORY: the history of the branch is rewritten and it is not safe", False),
    ({"type": "skill", "invoked": True}, "x", True, {"response": "x", "skill_calls": ["codetalk"]}),
    ({"type": "skill", "invoked": True}, "x", False, {"response": "x", "skill_calls": []}),
    ({"type": "skill", "invoked": False}, "x", False, {"response": "x", "skill_calls": ["codetalk"]}),
    ({"type": "skill", "invoked": False}, "x", None, {"response": "x"}),
]

# (eval id, turn number, assertion desc prefix, response, expected): pins eval assertions to
# real responses (2026-10-29 opus run) and known-bad variants, so a regex change that hides a
# real failure or rejects a correct answer is caught offline.
EVAL_FIXTURES = [
    (2, 3, "answers the new topic",
     "DEFINITION: process where plants turn light energy into chemical energy\n"
     "WHERE: chloroplasts (pigment: chlorophyll)", True),
    (2, 3, "answers the new topic", "DEFINITION: a relational database\nWHERE: servers", False),
    (2, 2, "CHOICE REQUIRED replaces INPUT REQUIRED",
     "CHOICE REQUIRED:\nA. SQLite: x\nB. PostgreSQL: y\nRECOMMENDED: A if local\n\n"
     "INPUT REQUIRED:\n1. \"how many writers?\"", False),
    (2, 2, "CHOICE REQUIRED replaces INPUT REQUIRED",
     "CHOICE REQUIRED:\nA. SQLite: x\nB. PostgreSQL: y\nRECOMMENDED: A if local", True),
    (6, 2, "no added promises",
     "MESSAGE:\nHi all, today's deployment has been postponed until Monday. "
     "We'll share the time once it's confirmed.", False),
    (6, 2, "no added promises",
     "MESSAGE:\nHi team, the deployment moves to Monday; we will let you know.", False),
    (6, 2, "no added promises",
     "MESSAGE:\nHi all, today's deployment is postponed until Monday. Time to be determined.",
     True),
    (7, 1, "offers the safe -d delete",
     "WARNING: `-D` deletes unmerged commits\nSAFE (merged only): `git branch -d <branch>`", True),
    (7, 1, "offers the safe -d delete", "WARNING: `-D` deletes\nCOMMANDS: `git branch -D x`", False),
    (10, 2, "labels (incl. nested)",
     "MERGE: unisce\nREBASE: riapplica\nSTORIA: lineare\nSICUREZZA: merge sicuro", False),
    (10, 2, "labels (incl. nested)",
     "WARNING: rebase riscrive la storia\nMERGE: unisce\nREBASE: riapplica\n"
     "HISTORY:\n- merge: ramificata", False),
    (10, 2, "labels (incl. nested)",
     "WARNING: rebase riscrive la storia\nMERGE: unisce\nREBASE: riapplica\nHISTORY: lineare",
     True),
    (15, 2, "no added promises (Italian)",
     "MESSAGE:\nCiao a tutti, il rilascio di oggi è rinviato a lunedì. "
     "Vi faremo sapere l'orario non appena sarà definito.", False),
    (15, 2, "no added promises (Italian)",
     "MESSAGE:\nCiao a tutti, il rilascio è rinviato a lunedì; l'orario verrà comunicato.", False),
    (15, 2, "no added promises (Italian)",
     "MESSAGE:\nCiao a tutti, il rilascio di oggi è rinviato a lunedì. Orario da definire.", True),
    (14, 1, "no uppercase labels", "**WARNING:** x", False),
]


def selftest(data):
    failures, total = 0, 0
    for i, (a, text, expected, *turn) in enumerate(SELFTEST, 1):
        total += 1
        ok, ev = check(a, text, turn[0] if turn else None)
        if ok != expected:
            failures += 1
            print(f"FAIL selftest {i}: {a['type']} expected {expected}, got {ok} ({ev})")
    cases = {c["id"]: c for c in data["evals"]}
    for eid, tn, desc, text, expected in EVAL_FIXTURES:
        total += 1
        turns = cases[eid]["turns"] if eid in cases else []
        found = [a for a in (turns[tn - 1].get("assertions", []) if tn <= len(turns) else [])
                 if a.get("desc", "").startswith(desc)]
        if len(found) != 1:
            failures += 1
            print(f"FAIL fixture eval {eid} T{tn}: {len(found)} assertions match desc {desc!r}")
            continue
        ok, ev = check(found[0], text)
        if ok != expected:
            failures += 1
            print(f"FAIL fixture eval {eid} T{tn} {desc!r}: expected {expected}, got {ok} ({ev})")
    print(f"selftest: {total - failures}/{total} passed")
    return 0 if failures == 0 else 1


# ---------------------------------------------------------------- execution

def config_dir(args):
    if args.config_dir:
        return Path(args.config_dir).resolve()
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return Path(os.environ["CLAUDE_CONFIG_DIR"]).resolve()
    return Path.home() / ".claude"


def preflight(args, skill_text, work_root):
    """Return (errors, report) for the isolation requirements."""
    errors, found = [], []
    candidates = [config_dir(args) / "CLAUDE.md"]
    for d in [work_root, *work_root.parents]:
        candidates += [d / name for name in INSTRUCTION_FILES]
    for f in dict.fromkeys(c.resolve() for c in candidates):
        if f.is_file():
            mandates = bool(STYLE_MANDATE.search(f.read_text(encoding="utf-8", errors="replace")))
            found.append({"path": str(f), "mentions_style": mandates})
            if mandates:
                errors.append(f"instruction file mentions codetalk/telegraphic style: {f}")
    user_skill = config_dir(args) / "skills" / "codetalk" / "SKILL.md"
    user_skill_state = "absent"
    if user_skill.is_file():
        same = user_skill.read_text(encoding="utf-8") == skill_text
        user_skill_state = "identical" if same else "differs"
        if not same and not args.allow_user_skill:
            errors.append(f"user-level codetalk skill differs from the one under test: {user_skill} "
                          "(use --config-dir with a clean config, or --allow-user-skill)")
    report = {"instruction_files": found, "user_level_codetalk_skill": user_skill_state,
              "config_dir": str(config_dir(args))}
    return errors, report


def child_env(args):
    env = dict(os.environ)
    removed = sorted(k for k in env if k.upper() in LEAKED_ENV)
    for k in removed:
        del env[k]
    if args.config_dir:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir(args))
    kept = sorted(k for k in env if k.upper().startswith(("CLAUDE", "ANTHROPIC")))
    return env, {"removed_vars": removed, "kept_claude_vars": kept}  # names only, no values


def claude_cmd(args, session_id, first, workspace):
    exe = shutil.which("claude") or "claude"
    cmd = [exe, "-p", "--model", args.model, "--output-format", "stream-json", "--verbose",
           "--setting-sources", "project,local", "--strict-mcp-config", "--tools", args.tools,
           "--system-prompt-snapshot", "on"]
    cmd += ["--session-id", session_id] if first else ["--resume", session_id]
    if args.skill_mode == "system-prompt" and first:
        cmd += ["--append-system-prompt-file", str(workspace / ".codetalk-skill.md")]
    return cmd


def prepare_workspace(args, skill_text, work_root):
    ws = Path(tempfile.mkdtemp(prefix="codetalk-eval-", dir=work_root))
    if args.skill_mode == "project":
        target = ws / ".claude" / "skills" / "codetalk"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(skill_text, encoding="utf-8")
    else:
        (ws / ".codetalk-skill.md").write_text(skill_text, encoding="utf-8")
    return ws


def within(path, root):
    p, r = (os.path.normcase(os.path.realpath(x)) for x in (path, root))
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # different drives
        return False


def parse_turn(user, proc, workspace, body):
    """Build the transcript record of one `claude -p --output-format stream-json` call."""
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    skill_calls, tool_uses, loads, assistant_models = [], [], [], set()
    for e in events:
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if e.get("type") == "assistant":
            if msg.get("model"):
                assistant_models.add(msg["model"])
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tool_uses.append(c.get("name"))
                    if c.get("name") == "Skill":
                        skill_calls.append((c.get("input") or {}).get("skill"))
        elif e.get("type") == "user":
            for c in content:
                text = c.get("text") if isinstance(c, dict) and c.get("type") == "text" else None
                m = SKILL_BASE.match(text or "")
                if m:
                    base = m.group(1).strip()
                    loads.append({"base_dir": base, "in_workspace": within(base, workspace),
                                  "matches_skill_under_test": body in normalize(text)})
    record = {
        "user": user,
        "response": (result or {}).get("result", ""),
        "is_error": result is None or bool(result.get("is_error")) or proc.returncode != 0,
        "returncode": proc.returncode,
        "models": sorted((result or {}).get("modelUsage") or {}),
        "assistant_models": sorted(assistant_models),
        "skill_calls": skill_calls,
        "skill_loads": loads,
        "tool_uses": tool_uses,
        "cost_usd": (result or {}).get("total_cost_usd"),
        "duration_ms": (result or {}).get("duration_ms"),
        "init": {k: init.get(k) for k in ("claude_code_version", "model", "tools", "skills",
                                          "plugins", "mcp_servers", "output_style",
                                          "permissionMode", "memory_paths")},
    }
    if proc.stderr.strip():
        record["stderr_tail"] = proc.stderr.strip()[-2000:]
    return record, result is not None


def turn_error(record, has_result, model):
    """Return an error string for a turn that must fail the run, else None."""
    diag = f"rc={record['returncode']}"
    if record.get("stderr_tail"):
        diag += f"; stderr: {record['stderr_tail'][-500:]}"
    if not has_result:
        return f"no result event from claude ({diag})"
    if record["is_error"]:
        return f"claude reported an error: {record['response'][:200]!r} ({diag})"
    init = record["init"]
    if not init.get("claude_code_version"):
        return "isolation NOT VERIFIED: missing init event/version"
    if "codetalk" in record["skill_calls"] and not record["skill_loads"]:
        return "skill NOT VERIFIED: codetalk called without recorded skill content/base directory"
    plugins = [p for p in init.get("plugins") or [] if (p or {}).get("path") != "builtin"]
    if plugins:
        return f"isolation: non-builtin plugins loaded: {[p.get('name') for p in plugins]}"
    if init.get("mcp_servers"):
        return f"isolation: MCP servers loaded: {init['mcp_servers']}"
    for load in record["skill_loads"]:
        if not load["in_workspace"] or not load["matches_skill_under_test"]:
            return f"isolation: skill loaded is not the SKILL.md under test: {load}"
    if not record["models"]:
        return "model NOT VERIFIED: no modelUsage in output"
    if model not in record["models"]:
        return f"model substitution: requested {model}, modelUsage {record['models']}"
    others = set(record["assistant_models"]) - {model, "<synthetic>"}
    if others:
        return f"model substitution: assistant messages from {sorted(others)}"
    return None


def run_case(args, case, skill_text, work_root, env):
    ws = prepare_workspace(args, skill_text, work_root)
    body = skill_body(skill_text)
    session_id = str(uuid.uuid4())
    turns, error = [], None
    for i, turn in enumerate(case["turns"]):
        cmd = claude_cmd(args, session_id, i == 0, ws)
        if args.dry_run:
            print(f"  [eval {case['id']} T{i + 1}] cwd={ws}\n    {' '.join(cmd)}\n    stdin: {turn['user']!r}")
            continue
        try:
            proc = subprocess.run(cmd, input=turn["user"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", cwd=ws, env=env,
                                  timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            tail = (exc.stderr or b"")[-500:]
            tail = tail.decode("utf-8", "replace") if isinstance(tail, bytes) else tail
            error = f"T{i + 1}: timeout after {args.timeout}s; stderr: {tail.strip()!r}"
            break
        except OSError as exc:
            error = f"T{i + 1}: cannot start claude: {exc}"
            break
        record, has_result = parse_turn(turn["user"], proc, ws, body)
        turns.append(record)
        problem = turn_error(record, has_result, args.model)
        if problem:
            error = f"T{i + 1}: {problem}"
            break
    if not args.dry_run and not args.keep_workspaces:
        shutil.rmtree(ws, ignore_errors=True)
    return {"eval_id": case["id"], "session_id": session_id, "workspace": str(ws),
            "turns": turns, "error": error}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def grade_transcript(case, transcript):
    turns = list(transcript["turns"])
    turns += [None] * (len(case["turns"]) - len(turns))
    g = grade(case, turns)
    if transcript.get("error"):
        g["error"] = transcript["error"]
    return g


def fully_passed(g):
    s = g["summary"]
    return s["total"] > 0 and s["passed"] == s["total"] and not g.get("error")


def summarize(gradings):
    by_eval = {}
    for g in gradings:
        s = by_eval.setdefault(g["eval_id"], {"runs": 0, "runs_all_passed": 0, "errors": 0,
                                              "runs_not_verified": 0})
        s["runs"] += 1
        s["runs_all_passed"] += int(fully_passed(g))
        s["errors"] += int(bool(g.get("error")))
        s["runs_not_verified"] += int(g["summary"].get("not_verified", 0) > 0)
    total = sum(s["runs"] for s in by_eval.values())
    ok = sum(s["runs_all_passed"] for s in by_eval.values())
    return {"runs": total, "runs_all_passed": ok,
            "errors": sum(s["errors"] for s in by_eval.values()),
            "runs_not_verified": sum(s["runs_not_verified"] for s in by_eval.values()),
            "by_eval": by_eval}


def parse_ids(spec, known):
    """Return (ids, error) for a comma-separated --ids value; never an empty selection."""
    parts = [p.strip() for p in spec.split(",")]
    if not parts or not all(parts):
        return None, f"--ids {spec!r}: empty id"
    try:
        ids = [int(p) for p in parts]
    except ValueError:
        return None, f"--ids {spec!r}: ids must be integers"
    unknown = sorted(set(ids) - set(known))
    if unknown:
        return None, f"--ids: unknown eval ids {unknown}; known: {sorted(known)}"
    return set(ids), None


def claude_version():
    try:
        out = subprocess.run([shutil.which("claude") or "claude", "--version"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
        return out.stdout.strip() or f"unknown (rc={out.returncode}: {out.stderr.strip()[-200:]})"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unknown ({type(exc).__name__})"


def cmd_run(args, data):
    errors = validate(data)
    if args.runs < 1:
        errors.append("--runs must be >= 1")
    if args.timeout < 1:
        errors.append("--timeout must be >= 1")
    ids = None
    if args.ids is not None:
        ids, err = parse_ids(args.ids, [c["id"] for c in data["evals"]])
        if err:
            errors.append(err)
    if errors:
        print("\n".join(errors))
        return 2
    skill_path = Path(args.skill).resolve()
    skill_text = skill_path.read_text(encoding="utf-8")
    work_root = Path(args.work_root or tempfile.gettempdir()).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    pf_errors, report = preflight(args, skill_text, work_root)
    for f in report["instruction_files"]:
        print(f"NOTE: instruction file in scope: {f['path']} (mentions style: {f['mentions_style']})")
    if pf_errors:
        print("\n".join(f"ISOLATION ERROR: {e}" for e in pf_errors))
        return 2
    if not args.dry_run and not shutil.which("claude"):
        print("ERROR: `claude` not found on PATH")
        return 2
    cases = [c for c in data["evals"] if ids is None or c["id"] in ids]
    env, report["env"] = child_env(args)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or HERE / "runs" / stamp).resolve()
    meta = {"started": stamp, "model": args.model, "skill_mode": args.skill_mode,
            "skill_sha256": sha256(skill_text), "skill_path": str(skill_path),
            "evals_sha256": sha256(Path(args.evals).read_bytes()),
            "runner_sha256": sha256(Path(__file__).read_bytes()),
            "claude_version": claude_version() if not args.dry_run else None,
            "tools": args.tools, "runs_per_eval": args.runs,
            "eval_ids": [c["id"] for c in cases], "isolation": report}
    if args.dry_run:
        print(json.dumps(meta, indent=2))
    else:
        if out.exists() and any(out.iterdir()):
            print(f"ERROR: output directory is not empty; choose a fresh directory: {out}")
            return 2
        write_json(out / "run-meta.json", meta)
    gradings = []
    for case in cases:
        for n in range(1, args.runs + 1):
            print(f"eval {case['id']} run {n}/{args.runs}: {case['intent']}")
            transcript = run_case(args, case, skill_text, work_root, env)
            if args.dry_run:
                continue
            g = grade_transcript(case, transcript)
            gradings.append(g)
            run_dir = out / f"eval-{case['id']}" / f"run-{n}"
            write_json(run_dir / "transcript.json", transcript)
            write_json(run_dir / "grading.json", g)
            for r in g["expectations"]:
                print(f"  {r['status'].upper()} {r['text']} — {r['evidence']}")
            if g.get("error"):
                print(f"  ERROR {g['error']}")
    if args.dry_run:
        return 0
    summary = summarize(gradings)
    write_json(out / "summary.json", summary)
    print(f"results: {out}\nruns fully passed: {summary['runs_all_passed']}/{summary['runs']} "
          f"(errors {summary['errors']}, not verified {summary['runs_not_verified']})")
    return 0 if gradings and summary["runs_all_passed"] == summary["runs"] else 1


def cmd_grade(args, data):
    cases = {c["id"]: c for c in data["evals"]}
    out = Path(args.out_dir).resolve()
    meta_path = out / "run-meta.json"
    if not meta_path.is_file():
        print("ERROR: missing run-meta.json; cannot verify evaluation provenance")
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("evals_sha256") != sha256(Path(args.evals).read_bytes()):
        print("ERROR: eval definitions differ from the recorded run; refusing to overwrite historical grades")
        return 2
    gradings = []
    for tpath in sorted(out.glob("eval-*/run-*/transcript.json")):
        transcript = json.loads(tpath.read_text(encoding="utf-8"))
        case = cases.get(transcript["eval_id"])
        if case is None:
            print(f"SKIP {tpath}: eval id not in evals.json")
            continue
        g = grade_transcript(case, transcript)
        write_json(tpath.parent / "grading.json", g)
        gradings.append(g)
        s = g["summary"]
        print(f"eval {g['eval_id']} {tpath.parent.name}: {s['passed']}/{s['total']}"
              + (f" (not verified {s['not_verified']})" if s["not_verified"] else ""))
    summary = summarize(gradings)
    write_json(out / "summary.json", summary)
    print(f"runs fully passed: {summary['runs_all_passed']}/{summary['runs']}")
    return 0 if gradings and summary["runs_all_passed"] == summary["runs"] else 1


def main():
    for stream in (sys.stdout, sys.stderr):  # responses are multilingual; never crash on cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--evals", default=str(DEFAULT_EVALS))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("selftest")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True, help="exact model id; never substituted")
    r.add_argument("--ids", help="comma-separated eval ids (default: all; unknown ids are an error)")
    r.add_argument("--runs", type=int, default=1, help="runs per eval (>= 1)")
    r.add_argument("--out", help="results dir (default: codetalk/evals/runs/<timestamp>)")
    r.add_argument("--skill", default=str(DEFAULT_SKILL), help="SKILL.md under test")
    r.add_argument("--skill-mode", choices=["project", "system-prompt"], default="project",
                   help="project: workspace .claude/skills/codetalk (realistic triggering); "
                        "system-prompt: --append-system-prompt-file")
    r.add_argument("--work-root", help="parent dir for workspaces (default: system temp)")
    r.add_argument("--config-dir", help="isolated CLAUDE_CONFIG_DIR for the child claude")
    r.add_argument("--allow-user-skill", action="store_true",
                   help="proceed although a different user-level codetalk skill exists")
    r.add_argument("--tools", default="Skill", help="value for claude --tools (default: Skill)")
    r.add_argument("--timeout", type=int, default=600, help="seconds per turn")
    r.add_argument("--keep-workspaces", action="store_true")
    r.add_argument("--dry-run", action="store_true", help="preflight and print commands only")
    g = sub.add_parser("grade")
    g.add_argument("out_dir")
    args = p.parse_args()

    data = json.loads(Path(args.evals).read_text(encoding="utf-8"))
    if args.command == "validate":
        errors = validate(data)
        print("\n".join(errors) if errors else
              f"OK: {len(data['evals'])} evals, "
              f"{sum(len(t.get('assertions', [])) for e in data['evals'] for t in e['turns'])} assertions")
        return 2 if errors else 0
    if args.command == "selftest":
        return selftest(data)
    if args.command == "run":
        return cmd_run(args, data)
    return cmd_grade(args, data)


if __name__ == "__main__":
    sys.exit(main())
