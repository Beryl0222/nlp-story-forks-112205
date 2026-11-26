"""路线状态、依据分层与回头路语义测试。"""
import unittest

from drama.acts import Basis, classify_all
from drama.graph import trace, walk
from drama.loader import load_script
from drama.state import (
    HOLDER_YUZHOU,
    OWNER_AQIN,
    Verdict,
    enter_scene,
    initial_state,
)

SOURCE = "data/records.json"


class EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script(SOURCE)
        cls.classifications = classify_all(cls.script)

    def test_indoor_route_builds_direct_handover_and_fulfils_promise(self):
        report = trace(self.script, ["E1", "E3", "E6"])
        self.assertIsNone(report.blocked_edge)
        state = report.steps[-1].state
        verdict, anchor = state.promise_status()
        self.assertEqual(verdict, Verdict.FULFILLED)
        self.assertEqual(anchor.source_line, "L3")
        self.assertEqual(state.key_holder, HOLDER_YUZHOU)
        # 兑现证据第一次出现在 S2（交付），而不是共用结尾
        self.assertEqual(state.custody_evidence_scene(), "S2")

    def test_echo_route_keeps_hearsay_separate_and_has_no_handover(self):
        report = trace(self.script, ["E2", "E5", "E7"])
        state = report.steps[-1].state
        handovers = state.valid_facts("handover:building_key")
        self.assertEqual(handovers, ())
        reports = state.facts_of("report:handover:building_key")
        # L4 他人澄清保持有效；L5 自己的错误复述被改口失效
        self.assertTrue(any(f.source_line == "L4" and f.valid for f in reports))
        self.assertTrue(
            all(not f.valid for f in reports if f.source_line == "L5")
        )
        retractions = state.facts_of("retraction:handover_belief")
        self.assertTrue(retractions)
        self.assertEqual(state.key_holder, OWNER_AQIN)
        verdict, _ = state.promise_status()
        self.assertEqual(verdict, Verdict.OPEN)

    def test_misheard_belief_cannot_unlock_direct_open_edge(self):
        report = trace(self.script, ["E2", "E4", "E6"])
        self.assertEqual(report.blocked_edge, "E4")
        self.assertIn("听", report.reason)

    def test_takeback_returns_key_but_keeps_history(self):
        # 走到还钥匙处 S7：L9 收回，持有人回到阿芹，但历史交付不被清空
        report = trace(self.script, ["E1", "E3", "E8"])
        state = report.steps[-1].state
        self.assertTrue(
            any(
                f.fact_key == "handover:building_key" and f.source_line == "L3"
                for f in state.facts
            )
        )
        self.assertEqual(state.key_holder, OWNER_AQIN)
        verdict, _ = state.promise_status()
        self.assertEqual(verdict, Verdict.REVOKED)

    def test_refusal_variant_on_revisit_leaves_key_with_owner(self):
        # 第二次到访 S2 才选 L10 反向承诺；第一次到访仍走默认 L3 交付
        report = trace(
            self.script,
            ["E1", "E3", "E8", "E9", "E10", "E7"],
            variant_choices={("S2", 2, 2): "L10"},
        )
        state = report.steps[-1].state
        self.assertIn("L10", state.line_events)
        self.assertIn("L3", state.line_events)
        self.assertEqual(state.key_holder, OWNER_AQIN)
        self.assertTrue(
            any(f.fact_key == "refusal:second_visit" for f in state.facts)
        )

    def test_general_variant_key_only_affects_first_visit(self):
        # 二元通用键只作用于首次到访，不会被错误套用到回头路
        report = trace(
            self.script,
            ["E1", "E3", "E8", "E9", "E3", "E6"],
            variant_choices={("S2", 2): "L10"},
        )
        state = report.steps[-1].state
        # 首次被拒给，E3 在第一次就该走不通
        self.assertEqual(report.blocked_edge, "E3")
        self.assertNotIn("L3", state.line_events)

    def test_revisiting_room_does_not_clear_prior_statements(self):
        report = trace(
            self.script, ["E1", "E3", "E8", "E9", "E3", "E6"]
        )
        self.assertIsNone(report.blocked_edge)
        state = report.steps[-1].state
        # 第二次到访重新交付后，钥匙再次到余舟手里，第一次 L3 记录仍在
        self.assertEqual(state.key_holder, HOLDER_YUZHOU)
        self.assertGreaterEqual(
            sum(1 for f in state.facts if f.source_line == "L3"), 1
        )
        self.assertTrue(
            any(f.source_line == "L9" for f in state.facts)
        )

    def test_knowledge_matrix_records_who_knows_what_with_basis(self):
        report = trace(self.script, ["E2", "E5", "E7"])
        state = report.steps[-1].state
        # 花叔与余舟知道 S3 的转述；阿芹不在场，不应掌握该转述
        self.assertTrue(
            state.knows("R3", "report:handover:building_key")
        )
        self.assertFalse(
            state.knows("R1", "report:handover:building_key")
        )
        known = state.knows("R2", "retraction:handover_belief")
        self.assertTrue(known)
        self.assertEqual(known[0].basis, Basis.RETRACTED)


class LoopPruningTest(unittest.TestCase):
    def test_equivalent_loop_is_pruned_without_exploding_routes(self):
        script = load_script(SOURCE)
        result = walk(script)
        # 图含 S4->S7->S2->S4 回头环，但路线数必须有界
        self.assertLess(len(result.routes), 40)
        self.assertTrue(result.pruned)
        # 剪枝说明必须指向具体选择前缀，而不是静默丢路线
        for item in result.pruned:
            self.assertIn("choice_prefix", item)
            self.assertTrue(item["signature"])

    def test_different_incoming_paths_are_not_pruned_into_one(self):
        script = load_script(SOURCE)
        result = walk(script)
        # 室内路与窗外路是不同来路，必须各自保留
        edge_sets = {route.edges for route in result.routes}
        self.assertTrue(any(edges[:1] == ("E1",) for edges in edge_sets))
        self.assertTrue(any(edges[:1] == ("E2",) for edges in edge_sets))


if __name__ == "__main__":
    unittest.main()
