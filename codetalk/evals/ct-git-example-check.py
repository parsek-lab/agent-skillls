"""Executes the SKILL.md "Undo my last commit but keep the changes?" example as written.

Commands are parsed from SKILL.md (CHECK backtick commands, NOT PUSHED / PUSHED numbered
steps), so a later edit of the example is tested, not a stale copy.
Usage (repo root): python -I codetalk/evals/ct-git-example-check.py codetalk <new temp dir>   -> prints JSON, exit 1 on failure
"""
import json
import os
import re
import shlex
import subprocess
import sys

skill = open(os.path.join(sys.argv[1], "SKILL.md"), encoding="utf-8").read()
work = sys.argv[2]
block = re.search(r"> Undo my last commit but keep the changes\?\n(.*?)\n\n", skill, re.S).group(1)


def section(name):
    m = re.search(rf"^{name}:\n((?:\d+\. .*\n?)+)", block, re.M)
    return [re.sub(r"^\d+\.\s*", "", l).strip().strip("`") for l in m.group(1).splitlines()] if m else []


check_line = re.search(r"^CHECK: (.*)$", block, re.M).group(1)
check_cmds = re.findall(r"`([^`]+)`", check_line)
not_pushed, pushed = section("NOT PUSHED"), section("PUSHED")
results, fails = [], 0


def rec(name, ok, ev=""):
    global fails
    fails += not ok
    results.append({"check": name, "pass": bool(ok), "evidence": ev})


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def run(cwd, cmd):
    return subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True, text=True)


_n = [0]


def setup():
    _n[0] += 1
    d = os.path.join(work, f"s{_n[0]}")
    os.makedirs(d)  # fails if not empty: pass a fresh dir
    git(d, "init", "-q", "--bare", "remote.git")
    git(d, "clone", "-q", "remote.git", "w")
    w = os.path.join(d, "w")
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("core.autocrlf", "false")):
        git(w, "config", k, v)
    return w


def commit(w, text, msg):
    with open(os.path.join(w, "f"), "a") as fh:
        fh.write(text)
    git(w, "add", "f")
    git(w, "commit", "-qm", msg)
    return git(w, "rev-parse", "HEAD").stdout.strip()


def check_output(w):
    out = ""
    for c in check_cmds:
        out = run(w, c).stdout.strip()
    return out


rec("example parsed", check_cmds and not_pushed and pushed,
    f"CHECK={check_cmds}; NOT PUSHED={not_pushed}; PUSHED={pushed}")

# pushed path
w = setup()
commit(w, "a\n", "A")
b = commit(w, "b\n", "B")
git(w, "push", "-q", "origin", "HEAD:main")
rec("CHECK non-empty for pushed commit", check_output(w) != "")
diff_b = git(w, "show", b, "--format=").stdout
for c in pushed:
    if c != "git status":
        r = run(w, c)
        rec(f"pushed: `{c}` exit 0", r.returncode == 0, r.stderr.strip()[:200])
rec("pushed: undone changes staged", git(w, "diff", "--cached").stdout == diff_b)
rec("pushed: original commit stays ancestor", git(w, "merge-base", "--is-ancestor", b, "HEAD").returncode == 0)
r = git(w, "push", "-q", "origin", "HEAD:main")
rec("pushed: push fast-forwards without force", r.returncode == 0, r.stderr.strip()[:200])

# not pushed path
w = setup()
commit(w, "a\n", "A")
git(w, "push", "-q", "origin", "HEAD:main")
c_sha = commit(w, "c\n", "C")
rec("CHECK empty for unpushed commit", check_output(w) == "")
diff_c = git(w, "show", c_sha, "--format=").stdout
for c in not_pushed:
    if c != "git status":
        r = run(w, c)
        rec(f"not pushed: `{c}` exit 0", r.returncode == 0, r.stderr.strip()[:200])
rec("not pushed: changes staged", git(w, "diff", "--cached").stdout == diff_c)
rec("not pushed: commit removed", git(w, "rev-parse", "HEAD").stdout.strip() != c_sha)

# root-commit caveat stated in WARNING
w = setup()
commit(w, "x\n", "R")
r = run(w, not_pushed[0]) if not_pushed else None
rec("root commit: first NOT PUSHED step fails (caveat holds)", r is not None and r.returncode != 0,
    r.stderr.strip()[:120] if r else "")
rec("WARNING mentions root/merge caveat", re.search(r"^WARNING:.*root.*merge", block, re.M) is not None)

git_version = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
print(json.dumps({"git": git_version, "passed": len(results) - fails, "total": len(results),
                  "results": results}, indent=2))
sys.exit(1 if fails else 0)
