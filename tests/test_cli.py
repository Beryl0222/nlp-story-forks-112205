"""命令行入口与变体选择解析测试。"""
import json
import subprocess
import sys
import unittest


class CliSmokeTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "drama", "--json", *args],
            cwd="/workspace",
            capture_output=True,
            text=True,
        )

    def test_check_emits_summary(self):
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("routes_walked", payload)
        self.assertGreater(payload["routes_walked"], 0)

    def test_trace_blocked_returns_exit_2(self):
        proc = self.run_cli("trace", "E2", "E4", "E6")
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["blocked_edge"], "E4")

    def test_visit_scoped_variant_uses_second_visit_choice(self):
        proc = self.run_cli(
            "trace",
            "E1", "E3", "E8", "E9", "E10", "E7",
            "--variant", "S2:2:L10@2",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        played = [line for step in payload["steps"] for line in step["lines_played"]]
        self.assertIn("L3", played)
        self.assertIn("L10", played)
        self.assertEqual(payload["steps"][-1]["key_holder"], "R1")

    def test_review_returns_1_when_blocks_exist(self):
        proc = self.run_cli("review")
        self.assertEqual(proc.returncode, 1)

    def test_questions_export_has_context_signature(self):
        proc = self.run_cli("questions")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload), 1)
        key = next(iter(payload))
        self.assertTrue(key.startswith("confirm:L4:"))
        self.assertIn("@", key)


if __name__ == "__main__":
    unittest.main()
