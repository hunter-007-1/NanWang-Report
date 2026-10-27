from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class FrameReportEditorFeatureTests(unittest.TestCase):
    def test_integrated_report_editor_contains_ai_rewrite_and_history_ui(self):
        html = read_text("frame_fore-end_design/report_editor.html")
        css = read_text("frame_fore-end_design/report_editor.css")
        js = read_text("frame_fore-end_design/report_editor.js")

        self.assertIn('id="versions-btn"', html)
        self.assertIn('id="versions-panel"', html)
        self.assertIn('id="version-preview-modal"', html)
        self.assertIn('id="rewrite-selection-meta"', html)
        self.assertIn('id="rewrite-instruction"', html)
        self.assertIn('id="rewrite-generate-btn"', html)
        self.assertIn('id="rewrite-apply-btn"', html)
        self.assertIn('id="rewrite-result"', html)
        self.assertIn(".versions-card", css)
        self.assertIn(".rewrite-demo", css)
        self.assertIn("async function onGenerateRewriteSuggestion", js)
        self.assertIn("async function rollbackReportVersion", js)
        self.assertIn("async listReportVersions", js)
        self.assertIn("async rewriteSelection", js)
        self.assertIn('reason: "rewrite"', js)

    def test_bridge_server_proxies_report_editor_feature_routes(self):
        bridge = read_text("powergrid_pipeline/bridge_server.py")

        for route in [
            '"/api/reports/versions"',
            '"/api/reports/versions/read"',
            '"/api/reports/versions/rollback"',
            '"/api/reports/versions/delete"',
            '"/api/reports/rewrite"',
        ]:
            self.assertIn(route, bridge)

    def test_compare_report_input_dir_uses_task_result_unless_env_override_exists(self):
        bridge = read_text("powergrid_pipeline/bridge_server.py")

        self.assertIn('REPORT_TEST_INPUT_DIR = os.environ.get("REPORT_TEST_INPUT_DIR", "").strip()', bridge)
        self.assertNotIn('REPORT_TEST_INPUT_DIR = os.path.join(RESULT_ROOT, "20260506_140359")', bridge)
        self.assertIn('payload["inputDir"] = REPORT_TEST_INPUT_DIR', bridge)
        self.assertIn('payload["inputDir"] = task["resultRoot"]', bridge)
        self.assertIn('return jsonify({"error": "缺少 taskId 或任务结果目录，无法生成比选报告"}), 400', bridge)

    def test_compare_report_button_requires_completed_task_result_and_schemes(self):
        js = read_text("frame_fore-end_design/app.js")

        self.assertIn('const hasCompletedPlanningResult = Boolean(state.taskId) && Boolean(state.resultRoot) && state.schemes.length > 0;', js)
        self.assertIn('return (hasCompletedPlanningResult || isLocalCompareReportInputOverrideEnabled()) && !state.failed && !inCompareFlow;', js)
        self.assertIn('function isLocalCompareReportInputOverrideEnabled()', js)
        self.assertIn('dom.generateCompareReportBtn.textContent = "等待规划任务完成";', js)


if __name__ == "__main__":
    unittest.main()
