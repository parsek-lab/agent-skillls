"""Offline parser regression tests: python -I codetalk/evals/test_models.py"""
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("models_runner", Path(__file__).with_name("run-models.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ModelParserTests(unittest.TestCase):
    def events(self):
        path = str(Path("SKILL.md").resolve())
        return [
            {"type": "tool_execution_start", "toolCallId": "1", "toolName": "read", "args": {"path": path}},
            {"type": "tool_execution_end", "toolCallId": "1", "isError": False,
             "result": {"content": [{"type": "text", "text": "# Codetalk\nTest instructions."}]}},
            {"type": "message_end", "message": {"role": "assistant", "model": "deepseek-flash",
              "provider": "deepseek", "stopReason": "stop", "content": [{"type": "text", "text": "STATUS: ready"}]}},
            {"type": "agent_settled", "aborted": False}]

    def parse(self, events):
        return runner.parse_output("\n".join(json.dumps(e) for e in events), "", 0,
            "deepseek-flash", "deepseek", Path("SKILL.md"), "# Codetalk\nTest instructions.")

    def test_verified_load(self):
        r = self.parse(self.events())
        self.assertIsNone(r["error"])
        self.assertEqual(r["skill_calls"], ["codetalk"])

    def test_no_load_is_not_fabricated(self):
        r = self.parse(self.events()[2:])
        self.assertEqual(r["skill_calls"], [])

    def test_wrong_skill_content(self):
        events = self.events()
        events[1]["result"]["content"][0]["text"] = "different skill"
        self.assertIn("evidence failure", self.parse(events)["error"])

    def test_model_mismatch(self):
        events = self.events()
        events[2]["message"]["model"] = "substitute"
        self.assertIn("mismatch", self.parse(events)["error"])

    def test_missing_settled(self):
        self.assertIn("agent_settled", self.parse(self.events()[:-1])["error"])

    def test_provider_error(self):
        events = self.events()
        events[2]["message"].update(stopReason="error", errorMessage="account quota")
        self.assertEqual(self.parse(events)["error"], "account quota")


if __name__ == "__main__":
    unittest.main()
