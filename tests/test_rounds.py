"""多轮稿合并与加载校验测试。"""
import json
import tempfile
import unittest
from pathlib import Path

from drama.loader import ScriptError, load_rounds


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(Path("data/records.json").read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, payload):
        path = self.dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_later_round_replaces_dialogue_and_appends_edge(self):
        round2 = {
            "roles": self.base["roles"],
            "scenes": self.base["scenes"],
            "edges": self.base["edges"]
            + [
                {
                    "id": "E11",
                    "origin": "S7",
                    "target": "S5",
                    "option": "绕窗",
                    "trigger": "任何时候",
                }
            ],
            "dialogue": [
                {
                    **next(l for l in self.base["dialogue"] if l["id"] == "L3"),
                    "quote": "那就托给你了，钥匙现在归你拿着。",
                }
            ],
            "tracks": [],
            "releases": [],
        }
        paths = [
            self._write("r1.json", self.base),
            self._write("r2.json", round2),
        ]
        script = load_rounds(paths)
        self.assertEqual(script.line("L3").quote, "那就托给你了，钥匙现在归你拿着。")
        self.assertEqual(script.edge("E11").option, "绕窗")
        # 未被替换的台词仍在
        self.assertEqual(script.line("L1").quote, self.base["dialogue"][0]["quote"])

    def test_role_identity_conflict_is_rejected(self):
        round2 = {
            "roles": [
                {"id": "R1", "name": "改名了", "aliases": ["阿芹"]}
            ],
            "scenes": self.base["scenes"],
            "edges": [],
            "dialogue": [],
            "tracks": [],
            "releases": [],
        }
        paths = [
            self._write("r1.json", self.base),
            self._write("r2.json", round2),
        ]
        with self.assertRaises(ScriptError):
            load_rounds(paths)

    def test_duplicate_variant_in_same_group_is_rejected(self):
        bad = {
            **self.base,
            "dialogue": [
                *self.base["dialogue"],
                {
                    "id": "L99",
                    "scene": "S6",
                    "line_no": 1,
                    "speaker": "R1",
                    "listeners": ["R2"],
                    "variant": "a",
                    "quote": "重复变体",
                },
            ],
        }
        with self.assertRaises(ScriptError):
            load_rounds([self._write("bad.json", bad)])


if __name__ == "__main__":
    unittest.main()
