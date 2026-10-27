"""报告生成方法优化的单元测试，不涉及指标公式和阈值。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.nodes.report_quality import (
    CORE_TABLE_HEADINGS,
    assess_report_structure,
    ensure_core_summary_tables,
    ensure_standard_chart_section,
    format_report_quality_review_message,
    generate_standard_metric_chart,
    protect_verifiable_blocks,
    restore_verifiable_blocks,
)
from src.nodes.safety_recommendation import (
    analyze_safety_for_recommendation,
    enforce_safety_recommendation,
)


def _core_tables() -> str:
    blocks = []
    for index, title in enumerate(CORE_TABLE_HEADINGS, start=1):
        blocks.append(
            f"### {title}\n\n"
            f"| 方案 | 指标{index} |\n"
            "|:---|---:|\n"
            f"| 方案1 | {index} |"
        )
    return "\n\n".join(blocks) + "\n\n## 方案 1 - 明细\n"


def _report() -> str:
    return """# 500kV输变电工程可行性研究报告

#### 报告摘要
摘要。

#### 周边500kV电网接入点分析
分析。

#### 接入系统方案拟定
拟定。

#### 比选原则与数据完整性
原则。

#### 安全硬约束校核
校核。

#### 技术性能比较
技术。

#### 经济性与全寿命周期比较
经济。

#### 工程实施与风险分析
风险。

#### 综合比较与结论
结论。
"""


class CoreSummaryTableTests(unittest.TestCase):
    def test_missing_core_tables_are_inserted_before_conclusion(self):
        updated, missing = ensure_core_summary_tables(_report(), _core_tables())
        self.assertEqual(missing, [])
        for title in CORE_TABLE_HEADINGS:
            self.assertEqual(updated.count(title), 1)
        self.assertLess(updated.index("核心指标汇总"), updated.index("综合比较与结论"))

    def test_insertion_is_idempotent(self):
        once, _ = ensure_core_summary_tables(_report(), _core_tables())
        twice, _ = ensure_core_summary_tables(once, _core_tables())
        self.assertEqual(once, twice)

    def test_missing_source_table_is_reported_without_fabrication(self):
        updated, missing = ensure_core_summary_tables(_report(), "")
        self.assertEqual(updated, _report())
        self.assertEqual(set(missing), set(CORE_TABLE_HEADINGS))

    def test_heading_without_table_does_not_suppress_programmatic_table(self):
        report = _report().replace(
            "#### 综合比较与结论",
            "###### 方案比选安全硬约束汇总表\n\n仅有标题。\n\n#### 综合比较与结论",
        )
        updated, missing = ensure_core_summary_tables(report, _core_tables())
        self.assertEqual(missing, [])
        self.assertIn("| 方案 | 指标1 |", updated)


class ProtectedBlockTests(unittest.TestCase):
    def test_claim_calculate_table_and_image_round_trip(self):
        report = """正文
<claim id="000001">12</claim>
<calculate> input: x=1; formula: x; output: 1 </calculate>

| A | B |
|---|---:|
| x | 1 |

![图](chart.png)
"""
        masked, blocks = protect_verifiable_blocks(report)
        self.assertNotIn("<claim", masked)
        self.assertNotIn("| A |", masked)
        restored, ok = restore_verifiable_blocks(masked, blocks)
        self.assertTrue(ok)
        self.assertEqual(restored, report)

    def test_changed_marker_rejects_restore(self):
        masked, blocks = protect_verifiable_blocks("<claim id=\"1\">2</claim>")
        changed = masked.replace("REPORT_PROTECTED", "CHANGED")
        _, ok = restore_verifiable_blocks(changed, blocks)
        self.assertFalse(ok)


class StandardChartTests(unittest.TestCase):
    def test_existing_metric_values_generate_chart(self):
        derived = {
            "schemes": [
                {
                    "proposal_name": "方案1",
                    "metrics": {
                        "n1_pass_rate": {"status": "ok", "value": 96.0},
                        "min_breaker_interrupt_margin_rate": {
                            "status": "ok",
                            "value": -10.0,
                        },
                        "annual_cost": {"status": "ok", "value": 20_000_000},
                    },
                },
                {
                    "proposal_name": "方案2",
                    "metrics": {
                        "n1_pass_rate": {"status": "ok", "value": 98.0},
                        "min_breaker_interrupt_margin_rate": {
                            "status": "ok",
                            "value": 5.0,
                        },
                        "annual_cost": {"status": "ok", "value": 18_000_000},
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            markdown = generate_standard_metric_chart(derived, tmp)
            chart = Path(tmp) / "standard_metric_comparison.png"
            self.assertTrue(chart.exists())
            self.assertGreater(chart.stat().st_size, 0)
            self.assertIn("standard_metric_comparison.png", markdown)

            report = ensure_standard_chart_section(_report(), markdown)
            self.assertEqual(report.count("standard_metric_comparison.png"), 1)
            self.assertLess(report.index("核心指标图示"), report.index("综合比较与结论"))


class ReportStructureTests(unittest.TestCase):
    def test_structure_passes_after_core_tables_and_chart(self):
        report, _ = ensure_core_summary_tables(_report(), _core_tables())
        report = ensure_standard_chart_section(report, "![图](chart.png)")
        quality = assess_report_structure(report)
        self.assertTrue(quality["structure_passed"])
        self.assertEqual(quality["image_count"], 1)

    def test_structure_failure_message_lists_missing_content(self):
        quality = assess_report_structure("# 报告\n")
        message = format_report_quality_review_message(quality)
        self.assertIn("结构质量检查需要人工复核", message)
        self.assertIn("缺少章节", message)
        self.assertIn("缺少核心表", message)

    def test_new_conclusion_heading_is_supported_by_safety_guard(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": {
                        "pf_convergence": {"status": "ok", "value": 1},
                        "min_breaker_interrupt_margin_rate": {
                            "status": "ok",
                            "value": -1.0,
                        },
                        "annual_cost": {"status": "ok", "value": 1.0},
                    },
                }
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        out = enforce_safety_recommendation(
            "# 报告\n\n#### 综合比较与结论\n\n最终推荐方案1。\n",
            analysis,
        )
        self.assertEqual(out.count("#### 综合比较与结论"), 1)
        self.assertNotIn("#### 综合比较推荐方案", out)
        self.assertIn("当前没有可直接推荐实施的方案", out)


class PromptMethodTests(unittest.TestCase):
    def test_report_prompt_uses_safety_first_plan_and_programmatic_charts(self):
        from src.skills.report_generation.main import ReportGenerationInput, render_prompt

        prompt = render_prompt(ReportGenerationInput(data_tables="TABLE", insights="INSIGHT"))
        self.assertIn("安全硬约束准入", prompt)
        self.assertIn("经济排序只在安全准入后", prompt)
        self.assertIn("三张核心汇总表和标准图表由程序自动插入", prompt)
        self.assertIn("不得输出 `<visualization>` 标签", prompt)
        self.assertNotIn("最终推荐主要参考阶段二经济排序", prompt)

    def test_insights_prompt_uses_three_stage_safety_first_method(self):
        from src.skills.insights_generation.main import render_system_prompt

        prompt = render_system_prompt()
        self.assertIn("阶段一：安全硬约束准入", prompt)
        self.assertIn("阶段二：技术性能比较", prompt)
        self.assertIn("阶段三：全寿命经济性与工程实施比较", prompt)
        self.assertIn("当前没有可直接推荐实施的方案", prompt)
        self.assertNotIn("最终推荐主要参考阶段二经济排序", prompt)


if __name__ == "__main__":
    unittest.main()
