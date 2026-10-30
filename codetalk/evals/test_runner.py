"""Offline regression tests. Run: python -I codetalk/evals/test_runner.py"""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("codetalk_runner", Path(__file__).with_name("run-evals.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def record(self):
        return {"returncode": 0, "is_error": False, "response": "STATUS: ready",
                "init": {"claude_code_version": "test", "plugins": [], "mcp_servers": []},
                "skill_calls": ["codetalk"],
                "skill_loads": [{"in_workspace": True, "matches_skill_under_test": True}],
                "models": ["claude-opus-5-5"], "assistant_models": ["claude-opus-5-5"]}

    def test_valid_record(self):
        self.assertIsNone(runner.turn_error(self.record(), True, "claude-opus-5-5"))

    def test_missing_skill_evidence(self):
        record = self.record()
        record["skill_loads"] = []
        self.assertIn("skill NOT VERIFIED", runner.turn_error(record, True, "claude-opus-5-5"))

    def test_missing_init(self):
        record = self.record()
        record["init"] = {}
        self.assertIn("isolation NOT VERIFIED", runner.turn_error(record, True, "claude-opus-5-5"))

    def test_wrong_model(self):
        record = self.record()
        record["assistant_models"] = ["another-model"]
        self.assertIn("model substitution", runner.turn_error(record, True, "claude-opus-5-5"))

    def test_plugins_rejected(self):
        record = self.record()
        record["init"]["plugins"] = [{"name": "external", "path": "/external"}]
        self.assertIn("non-builtin", runner.turn_error(record, True, "claude-opus-5-5"))

    def test_skill_copy_rejected(self):
        record = self.record()
        record["skill_loads"][0]["in_workspace"] = False
        self.assertIn("not the SKILL.md", runner.turn_error(record, True, "claude-opus-5-5"))

    def test_child_environment(self):
        with patch.dict(runner.os.environ, {"CLAUDE_CODE_PLUGIN_DIRS": "private", "CLAUDE_EFFORT": "max"}):
            env, report = runner.child_env(argparse.Namespace(config_dir=None))
        self.assertNotIn("CLAUDE_CODE_PLUGIN_DIRS", env)
        self.assertNotIn("CLAUDE_EFFORT", env)
        self.assertNotIn("private", json.dumps(report))

    def test_unknown_ids(self):
        self.assertIsNotNone(runner.parse_ids("999", [1, 2])[1])
        self.assertIsNotNone(runner.parse_ids("", [1, 2])[1])

    def test_missing_turns_never_pass(self):
        case = {"id": 1, "turns": [{"assertions": [{"type": "regex", "pattern": "ready"}]}]}
        grading = runner.grade_transcript(case, {"turns": [], "error": "quota"})
        self.assertEqual(grading["summary"]["not_run"], 1)
        self.assertFalse(runner.fully_passed(grading))

    def test_stale_grades_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run-meta.json").write_text('{"evals_sha256":"old"}', encoding="utf-8")
            args = argparse.Namespace(out_dir=directory, evals=str(runner.DEFAULT_EVALS))
            self.assertEqual(runner.cmd_grade(args, {"evals": []}), 2)
            self.assertFalse((root / "summary.json").exists())

    def test_existing_run_not_overwritten(self):
        data = json.loads(runner.DEFAULT_EVALS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "run-meta.json"
            sentinel.write_text("original", encoding="utf-8")
            args = argparse.Namespace(runs=1, timeout=1, ids="1", skill=str(runner.DEFAULT_SKILL),
                work_root=directory, dry_run=False, out=directory, model="claude-opus-5-5",
                evals=str(runner.DEFAULT_EVALS), tools="Skill", skill_mode="project", config_dir=None)
            with patch.object(runner, "preflight", return_value=([], {"instruction_files": []})), \
                 patch.object(runner.shutil, "which", return_value="claude"), \
                 patch.object(runner, "claude_version", return_value="test"), \
                 patch.object(runner, "run_case") as execute:
                self.assertEqual(runner.cmd_run(args, data), 2)
                execute.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
