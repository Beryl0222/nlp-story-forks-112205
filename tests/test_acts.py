"""台词行为分类与依据分级测试。"""
import unittest

from drama.acts import Act, Basis, classify, classify_all
from drama.loader import load_script


SOURCE = "data/records.json"


class ClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script(SOURCE)
        cls.table = classify_all(cls.script)

    def test_each_dialogue_act_is_classified_with_unknown_guard(self):
        expected = {
            "L1": Act.CONDITIONAL_PROMISE,
            "L2": Act.ACCEPTANCE,
            "L3": Act.HANDOVER,
            "L4": Act.REPORT,
            "L5": Act.MISHEARD_RETRACTION,
            "L6": Act.ACTION_CLAIM,
            "L7": Act.CUSTODY_PRESUPPOSITION,
            "L8": Act.NEUTRAL,
            "L9": Act.TAKEBACK,
            "L10": Act.REFUSAL,
        }
        for line_id, act in expected.items():
            with self.subTest(line=line_id):
                self.assertEqual(self.table[line_id].act, act)

    def test_promise_is_not_handover_and_keeps_direct_basis(self):
        self.assertEqual(self.table["L1"].basis, Basis.DIRECT)
        self.assertNotEqual(self.table["L1"].act, Act.HANDOVER)

    def test_hearsay_and_retraction_use_distinct_basis_from_direct_handover(self):
        self.assertEqual(self.table["L3"].basis, Basis.DIRECT)
        self.assertEqual(self.table["L4"].basis, Basis.HEARSAY)
        self.assertEqual(self.table["L5"].basis, Basis.RETRACTED)

    def test_action_claim_using_key_is_not_misread_as_new_handover(self):
        # L6 “我用你刚交给我的钥匙开” 不得被当成第二次交付
        self.assertEqual(self.table["L6"].act, Act.ACTION_CLAIM)

    def test_unknown_quote_falls_back_to_unknown_instead_of_silent_guess(self):
        from drama.model import Line

        weird = Line(
            "LX", "S1", 9, "R1", ("R2",), "", "今天潮声很怪。"
        )
        result = classify(weird, self.script)
        self.assertEqual(result.act, Act.UNKNOWN)
        self.assertEqual(result.basis, Basis.NONE)


if __name__ == "__main__":
    unittest.main()
