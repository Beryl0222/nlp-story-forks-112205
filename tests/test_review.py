"""审查、共用场景兼容性与编剧确认测试。"""
import unittest

from drama.loader import load_script
from drama.review import (
    SEVERITY_BLOCK,
    SEVERITY_NOTE,
    SEVERITY_QUESTION,
    apply_confirmations,
    review_script,
)

SOURCE = "data/records.json"


class ReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script(SOURCE)
        cls.report = review_script(cls.script)

    def test_ungrounded_key_action_is_blocked_with_choice_sequence(self):
        blocks = [
            item
            for item in self.report.findings
            if item.code == "ACTION-NO-KEY" and item.severity == SEVERITY_BLOCK
        ]
        self.assertTrue(blocks)
        for item in blocks:
            # 必须指出是哪一组选择让动作断了
            self.assertTrue(item.choice_sequence)
            self.assertIn("E10", item.choice_sequence)

    def test_shared_ending_presupposition_fails_on_no_handover_routes(self):
        l7 = next(c for c in self.report.compatibilities if c.line_id == "L7")
        self.assertFalse(l7.works_everywhere)
        # 断的是窗外/拒给等无交付来路
        broken_prefixes = {choices[0] for _, choices in l7.broken_routes}
        self.assertTrue(broken_prefixes)

    def test_neutral_shared_line_works_on_every_route(self):
        l8 = next(c for c in self.report.compatibilities if c.line_id == "L8")
        self.assertTrue(l8.works_everywhere)
        self.assertEqual(len(l8.broken_routes), 0)

    def test_ambiguous_trigger_creates_scoped_confirmation_question(self):
        questions = [
            item
            for item in self.report.findings
            if item.code == "TRIGGER-AMBIGUOUS"
        ]
        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question.edge_id, "E4")
        self.assertTrue(question.confirm_key.startswith("confirm:L4:"))
        self.assertIn("不能补出交付事实", question.message)

    def test_hearsay_note_keeps_basis_separate(self):
        notes = [
            item
            for item in self.report.findings
            if item.code == "HEARSAY-KEPT-SEPARATE"
        ]
        self.assertTrue(notes)
        self.assertEqual(notes[0].severity, SEVERITY_NOTE)


class ConfirmationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script(SOURCE)
        cls.report = review_script(cls.script)

    def test_accepted_confirmation_resolves_question_but_keeps_blocks(self):
        key = next(
            item.confirm_key
            for item in self.report.findings
            if item.confirm_key
        )
        updated = apply_confirmations(self.report, {key: "accepted"})
        self.assertEqual(updated.questions, ())
        # 读法确认不产生交付事实，原阻断项数量不减少
        before_blocks = sum(
            item.severity == SEVERITY_BLOCK for item in self.report.findings
        )
        after_blocks = sum(
            item.severity == SEVERITY_BLOCK for item in updated.findings
        )
        self.assertEqual(before_blocks, after_blocks)

    def test_rejected_confirmation_upgrades_to_block(self):
        key = next(
            item.confirm_key
            for item in self.report.findings
            if item.confirm_key
        )
        updated = apply_confirmations(self.report, {key: "rejected"})
        self.assertTrue(
            any(
                item.confirm_key == key and item.severity == SEVERITY_BLOCK
                for item in updated.findings
            )
        )

    def test_confirmation_key_is_context_bound_and_rejects_reuse(self):
        with self.assertRaises(KeyError):
            apply_confirmations(
                self.report, {"confirm:L4:belief_after_retraction@deadbeef": "accepted"}
            )


if __name__ == "__main__":
    unittest.main()
