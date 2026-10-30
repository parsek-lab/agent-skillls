"""Mechanical static checks for codetalk/SKILL.md and evals/evals.json.

Usage (repo root): python codetalk/evals/ct-static-checks.py codetalk   -> prints JSON
"""
import json
import os
import re
import sys

ROOT = sys.argv[1]
skill = open(f"{ROOT}/SKILL.md", encoding="utf-8").read()
lines = skill.splitlines()
checks = {}


def rec(name, ok, evidence):
    checks[name] = {"pass": bool(ok), "evidence": evidence}


# frontmatter
m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
fm = m.group(1) if m else ""
keys = re.findall(r"^([a-z_-]+):", fm, re.M)
name = re.search(r"^name:\s*(\S+)", fm, re.M)
desc_m = re.search(r"^description:\s*>-?\n((?:  .*\n?)+)", fm + "\n", re.M)
desc = " ".join(l.strip() for l in desc_m.group(1).splitlines()) if desc_m else ""
rec("frontmatter",
    m and {"name", "description"} <= set(keys) <= {"name", "description", "license"} and name and name.group(1) == "codetalk"
    and 0 < len(desc) <= 1024 and "<" not in desc and ">" not in desc,
    f"keys={keys}; name={name.group(1) if name else None}; description_chars={len(desc)}")

lic = re.search(r"^license:\s*(\S+)", fm, re.M)
if lic:
    root_lic = os.path.join(ROOT, "..", "LICENSE")
    pkg_lic = os.path.join(ROOT, "LICENSE")
    same = os.path.isfile(pkg_lic) and os.path.isfile(root_lic) and open(pkg_lic, "rb").read() == open(root_lic, "rb").read()
    head = open(pkg_lic, encoding="utf-8").read(400) if os.path.isfile(pkg_lic) else ""
    spdx_ok = lic.group(1) in ("AGPL-3.0-only", "AGPL-3.0-or-later") and "GNU AFFERO GENERAL PUBLIC LICENSE" in head and "Version 3" in head
    rec("license", same and spdx_ok, f"frontmatter license={lic.group(1)}; codetalk/LICENSE byte-identical to root LICENSE={same}; AGPLv3 text header={spdx_ok}")
else:
    rec("license", False, "no license key in frontmatter")

act = re.search(r"## Activation\n(.*?)\n## ", skill, re.S).group(1)
rec("explicit_activation",
    "explicit user request" in desc and "Not for mere" in desc
    and "ON: explicit request" in act and "not triggers" in act,
    "description: 'Use only on explicit user request'; Activation: 'ON: explicit request', '\"Be brief\" ... not triggers'")
rec("persistence",
    "stays on for the session" in desc and "Stays on across responses and topic changes" in act,
    "description + Activation bullet 'Stays on across responses and topic changes.'")
ex = re.search(r"```text\n(.*?)```", skill, re.S).group(1)
off_ex = re.search(r"> disable codetalk\n(.*?)(?:\n\n|$)", ex, re.S)
rec("deactivation",
    "OFF: explicit user request" in act and "one confirmation line only" in act
    and off_ex and len(off_ex.group(1).strip().splitlines()) == 1,
    f"Activation OFF rule present; example reply lines={len(off_ex.group(1).strip().splitlines()) if off_ex else None}")
ch = re.search(r"CHOICE REQUIRED:\n((?:[A-Z]\. .*\n)+)RECOMMENDED: (\S+) if ", ex)
rec("choice_format",
    "`RECOMMENDED: <option> if <condition>`" in skill and ch
    and all(" — " in l and ";" in l for l in ch.group(1).splitlines()),
    f"example options={len(ch.group(1).splitlines()) if ch else 0}, each with '—' trade-off; RECOMMENDED '<opt> if'")

# example replies: every label uppercase English; WARNING first in its reply
blocks = [b for b in re.split(r"\n\s*\n", ex) if b.strip()]
bad_labels, warn_issues = [], []
for b in blocks:
    reply = [l for l in b.splitlines() if not l.startswith((">", "#"))]
    for l in reply:
        lm = re.match(r"^([A-Za-z][A-Za-z ]{0,30}):(\s|$)", l)
        if lm and lm.group(1) != lm.group(1).upper():
            if not (reply and reply[0] == "MESSAGE:" and l != "MESSAGE:"):
                bad_labels.append(l)
    if any(l.startswith("WARNING:") for l in reply) and not reply[0].startswith("WARNING:"):
        warn_issues.append(reply[0])
rec("examples_labels_uppercase", not bad_labels, f"example blocks={len(blocks)}; non-uppercase labels={bad_labels}")
rec("examples_warning_first", not warn_issues, f"blocks with WARNING not first={warn_issues}")
rec("examples_labels_not_translated",
    re.search(r"> differenza tra let e const\?\nSCOPE: .*\nREASSIGNMENT: ", ex) is not None,
    "Italian example keeps English labels SCOPE/REASSIGNMENT/NOTE with Italian values")
rec("size", len(lines) < 500, f"SKILL.md lines={len(lines)}")

# evals.json
try:
    ev = json.load(open(f"{ROOT}/evals/evals.json", encoding="utf-8"))
    ids = [e.get("id") for e in ev["evals"]]
    fields_ok = all(isinstance(e.get("prompt"), str) and e["prompt"].strip()
                    and isinstance(e.get("expected_output"), str) and e["expected_output"].strip()
                    and isinstance(e.get("files"), list) for e in ev["evals"])
    rec("evals_json_schema",
        ev.get("skill_name") == "codetalk" and ids == list(range(1, len(ids) + 1)) and fields_ok,
        f"valid JSON; skill_name={ev.get('skill_name')}; ids={ids}; required fields present={fields_ok}")
    eval_count = len(ids)
except Exception as e:  # noqa: BLE001
    rec("evals_json_schema", False, f"{type(e).__name__}: {e}")
    eval_count = None

print(json.dumps({"checks": checks, "eval_count": eval_count}, ensure_ascii=False, indent=2))
