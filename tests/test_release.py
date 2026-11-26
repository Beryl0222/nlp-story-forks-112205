"""交片评估：授权语言、音轨就绪与按钮一致性测试。"""
import unittest

from drama.loader import load_script
from drama.release import assess_all, assess_release, line_status
from drama.review import review_script

SOURCE = "data/records.json"


class ReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script(SOURCE)
        cls.review = review_script(cls.script)
        cls.reports = {
            release.id: assess_release(cls.script, release, cls.review)
            for release in cls.script.releases
        }

    def test_only_authorized_languages_are_assessed(self):
        p1 = self.reports["P1"]
        self.assertEqual(p1.authorized_languages, ("zh",))
        # en 是计划语言但未授权，单独标注且不进交付判定
        self.assertEqual(p1.unauthorized_planned, ("en",))
        self.assertTrue(
            all(verdict.language == "zh" for verdict in p1.route_verdicts)
        )

    def test_ready_track_does_not_grant_script_validity(self):
        # L7 中文音轨就绪，但无交付来路仍因依据断裂不可交付
        status = line_status(self.script, "L7", "zh")
        self.assertTrue(status.ready)
        p1 = self.reports["P1"]
        ungrounded = [
            verdict
            for verdict in p1.route_verdicts
            if any(finding.code == "PRESUPPOSITION-FAILS" for finding in verdict.blocking_findings)
        ]
        self.assertTrue(ungrounded)
        self.assertTrue(all(not v.deliverable for v in ungrounded))

    def test_unrecorded_line_blocks_only_routes_depending_on_it(self):
        # L8 英文未录好（T6 ready=false），但已制片的 L7 路线不受影响
        p2 = self.reports["P2"]
        l8_missing = [
            verdict
            for verdict in p2.route_verdicts
            if any(status.line_id == "L8" for status in verdict.missing_tracks)
        ]
        self.assertTrue(l8_missing)
        # 存在一条不依赖 L8 且依据成立的可交付路线
        self.assertTrue(any(verdict.deliverable for verdict in p2.route_verdicts))

    def test_re_record_list_is_separate_from_ready_tracks(self):
        p2 = self.reports["P2"]
        re_record = {(t.line_id, t.language) for t in p2.re_record}
        ready = {(t.line_id, t.language) for t in p2.ready_tracks}
        self.assertIn(("L8", "en"), re_record)
        self.assertIn(("L7", "en"), ready)
        self.assertTrue(re_record.isdisjoint(ready))

    def test_ungrounded_option_is_closed_not_left_as_empty_button(self):
        p2 = self.reports["P2"]
        closed = {opt.edge_id: opt for opt in p2.options if not opt.keep_open}
        # E4 信念依据断裂、E6 开门依据断裂，必须关闭
        self.assertIn("E4", closed)
        self.assertIn("E6", closed)

    def test_grounded_but_unrecorded_option_is_not_silently_muted(self):
        # E2/E5 走窗外依据成立，仅候选用句待录，按钮保留但标明补录义务
        p2 = self.reports["P2"]
        kept = {opt.edge_id: opt for opt in p2.options if opt.keep_open}
        self.assertIn("E2", kept)
        self.assertIn("E5", kept)
        self.assertIn("重录", kept["E2"].reason)

    def test_zh_release_has_deliverable_routes(self):
        p1 = self.reports["P1"]
        self.assertGreater(p1.deliverable_route_count, 0)


class LoaderGuardTest(unittest.TestCase):
    def test_dangling_reference_is_rejected(self):
        from drama.loader import ScriptError
        from drama.model import Script, Track

        broken = Script(
            roles=self._roles(),
            scenes=self._scenes(),
            edges=(),
            lines=self._lines(),
            tracks=(Track("TBAD", "NOPE", "zh", True),),
            releases=(),
        )
        with self.assertRaises(ScriptError):
            from drama.loader import validate_references

            validate_references(broken)

    def _roles(self):
        from drama.model import Role

        return (Role("R1", "阿芹", ("阿芹",)),)

    def _scenes(self):
        from drama.model import Scene

        return (Scene("S1", "房", ""),)

    def _lines(self):
        from drama.model import Line

        return (Line("L1", "S1", 1, "R1", (), "", "x"),)


if __name__ == "__main__":
    unittest.main()
