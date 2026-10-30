#!/usr/bin/env python3
"""Cross-model behavioral evaluation through Pi's isolated print-mode CLI.

Requires Python 3.9+ and pi on PATH, with authenticated requested providers.
Usage: python codetalk/evals/run-models.py --runs 3 --out codetalk/evals/runs/multimodel
The models are API evaluation subjects, not delegated coding workers.

No extensions, MCP, context files, prompt templates or discovered skills load.
The only tool is read. A neutral system prompt advertises the skill description;
a successful read of the exact staged SKILL.md counts as activation evidence.
This tests Pi-style loading, not Claude Code's Skill tool. Actual response quality
still needs judge review; automatic passes alone are not full release approval.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("codetalk_assertions", HERE / "run-evals.py")
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
MODELS = {"gpt-6.1-sol": "openai-codex", "gpt-6-astra": "openai-codex", "deepseek-flash": "deepseek"}


def pi_command():
    executable = shutil.which("pi")
    if os.name == "nt" and executable and executable.lower().endswith((".cmd", ".bat")):
        # Invoke Node directly: cmd.exe corrupts quoted multiline prompt arguments.
        package = Path(executable).parent / "node_modules/@earendil-works/pi-coding-agent"
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        return [shutil.which("node") or "node", str(package / metadata["bin"]["pi"])]
    return [executable]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_output(stdout, stderr, returncode, model, provider, skill_path, skill_text):
    events = []
    for line in stdout.split("\n"):
        try:
            events.append(json.loads(line.rstrip("\r")))
        except json.JSONDecodeError:
            continue
    messages = [e["message"] for e in events if e.get("type") == "message_end"
                and e.get("message", {}).get("role") == "assistant"]
    starts = {e["toolCallId"]: e for e in events if e.get("type") == "tool_execution_start"}
    loads = []
    unexpected = []
    for e in events:
        if e.get("type") != "tool_execution_end":
            continue
        start = starts.get(e.get("toolCallId"), {})
        path = start.get("args", {}).get("path", "")
        if start.get("toolName") != "read" or Path(path).resolve() != skill_path.resolve():
            unexpected.append(start.get("toolName", "unknown") + ": unexpected read/tool")
            continue
        text = "\n".join(c.get("text", "") for c in e.get("result", {}).get("content", []))
        if not e.get("isError") and checks.skill_body(skill_text) in checks.normalize(text):
            loads.append("codetalk")
        else:
            unexpected.append("skill read did not return complete expected content")
    error = None
    if returncode or not messages:
        error = f"API/CLI error (exit {returncode}): {stderr[-1000:]}"
    for m in messages:
        if m.get("model") != model or m.get("provider") != provider:
            error = "model/provider mismatch: " + str((m.get("provider"), m.get("model")))
        if m.get("stopReason") in ("error", "aborted"):
            error = m.get("errorMessage", "model aborted/errored")
    if unexpected:
        error = "isolation/evidence failure: " + "; ".join(unexpected)
    if not any(e.get("type") == "agent_settled" and not e.get("aborted") for e in events):
        error = error or "missing successful agent_settled event"
    final = messages[-1] if messages else {}
    response = "\n".join(c.get("text", "") for c in final.get("content", []) if c.get("type") == "text")
    return {"response": response, "skill_calls": loads,
            "models": sorted({m.get("model", "") for m in messages}),
            "provider": provider, "is_error": bool(error),
            "cost_usd": sum(m.get("usage", {}).get("cost", {}).get("total", 0) for m in messages),
            "usage": [m.get("usage", {}) for m in messages], "error": error}


def evaluate_model(args, data, model, skill_text, skill_source, env):
    provider = MODELS[model]
    model_out = Path(args.out).resolve() / model
    gradings = []
    save(model_out / "run-meta.json", {
        "model": model, "provider": provider, "started": datetime.datetime.now().astimezone().isoformat(),
        "skill_sha256": digest(skill_source), "evals_sha256": digest(HERE / "evals.json"),
        "runner_sha256": digest(Path(__file__)), "assertion_engine_sha256": digest(HERE / "run-evals.py"),
        "runs_per_eval": args.runs, "harness": "Pi print mode; read-only skill discovery",
        "activation_evidence": "successful read tool output contains exact staged skill body",
        "isolation": "fresh workspace and session per run; no context, extensions, MCP, templates or discovered skills",
        "limitations": ["different host/system prompt from Claude Code", "judge review required", "model identity is host-reported"]})
    description = " ".join(skill_text.split("description: >-", 1)[1].split("license:", 1)[0].split())
    for case in data["evals"]:
        for repetition in range(1, args.runs + 1):
            run_out = model_out / f"eval-{case['id']}" / f"run-{repetition}"
            turns, error = [], None
            with tempfile.TemporaryDirectory(prefix="codetalk-model-eval-") as directory:
                ws = Path(directory)
                skill_path = ws / "codetalk" / "SKILL.md"
                skill_path.parent.mkdir()
                skill_path.write_text(skill_text, encoding="utf-8")
                system = ("You are a helpful assistant. Answer the user's request.\n"
                    "Available skill (not active merely because it is listed):\n"
                    f"NAME: codetalk\nDESCRIPTION: {description}\nFILE: {skill_path.as_posix()}\n"
                    "When the skill applies, use the read tool to load its instructions before answering. "
                    "Do not read other files. Follow loaded instructions for subsequent messages until disabled.")
                for index, turn in enumerate(case["turns"], 1):
                    cmd = pi_command() + ["-p", "--mode", "json", "--offline", "--provider", provider,
                        "--model", model, "--no-extensions", "--no-skills", "--no-context-files", "--no-mcp",
                        "--no-prompt-templates", "--no-themes", "--tools", "read", "--thinking", "off",
                        "--session", str(ws / "session.jsonl"), "--system-prompt", system, "--", turn["user"]]
                    started = time.monotonic()
                    try:
                        proc = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=args.timeout)
                        run_out.mkdir(parents=True, exist_ok=True)
                        (run_out / f"turn-{index}.jsonl").write_text(proc.stdout, encoding="utf-8")
                        record = parse_output(proc.stdout, proc.stderr, proc.returncode, model,
                                              provider, skill_path, skill_text)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        error = f"T{index}: {type(exc).__name__}: {exc}"
                        break
                    record.update(user=turn["user"], duration_ms=round((time.monotonic() - started) * 1000))
                    turns.append(record)
                    if record["error"]:
                        error = f"T{index}: {record['error']}"
                        break
            transcript = {"eval_id": case["id"], "model": model, "turns": turns, "error": error}
            grading = checks.grade_transcript(case, transcript)
            gradings.append(grading)
            save(run_out / "transcript.json", transcript)
            save(run_out / "grading.json", grading)
            print(f"{model} eval {case['id']} run {repetition}: "
                  f"{grading['summary']['passed']}/{grading['summary']['total']} "
                  f"{'ERROR ' + error if error else ''}", flush=True)
    summary = checks.summarize(gradings)
    summary["judge_review"] = "pending"
    summary["method"] = "Pi host, read-tool skill loading; not Claude Code Skill-tool validation"
    save(model_out / "summary.json", summary)
    return model, summary


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--ids", help="comma-separated eval IDs; default all")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    args = p.parse_args()
    if args.runs < 1 or args.timeout < 1 or not shutil.which("pi"):
        p.error("positive runs/timeout and pi on PATH required")
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        p.error("output directory must be fresh")
    data = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))
    errors = checks.validate(data)
    if errors:
        p.error("; ".join(errors))
    if args.ids:
        selected, error = checks.parse_ids(args.ids, [case["id"] for case in data["evals"]])
        if error:
            p.error(error)
        data["evals"] = [case for case in data["evals"] if case["id"] in selected]
    skill_source = HERE.parent / "SKILL.md"
    skill_text = skill_source.read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("HERDR_", "PI_SESSION", "PI_MODEL", "PI_PROVIDER", "CLAUDE_"))
           and k.upper() not in ("CLAUDECODE", "PI_CODING_AGENT", "PI_REASONING_LEVEL")}
    env["PI_OFFLINE"] = "1"
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.models)) as pool:
        results = dict(pool.map(lambda model: evaluate_model(args, data, model, skill_text, skill_source, env), args.models))
    save(out / "summary.json", results)
    return int(any(s["runs_all_passed"] != s["runs"] for s in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
