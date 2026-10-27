"""PCN claim 规范化、单位换算与安全推荐后处理测试。"""

from __future__ import annotations

import math
import unittest

from src.nodes.normalize_claim_tags import normalize_claim_tags_in_report
from src.nodes.safety_recommendation import (
    analyze_safety_for_recommendation,
    classify_recommended_schemes,
    enforce_safety_recommendation,
    evaluate_scheme_hard_constraints,
    identify_recommended_schemes,
)
from src.nodes.verify_pcn_claims import compute_pcn_verification_passed, format_pcn_review_message
from src.pcn import Claim


def _claim(
    claim_id: str,
    indicator: str,
    value: float,
    *,
    unit: str = "元",
    path: str = "",
    source: str = "derived_metrics.json",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        indicator=indicator,
        value=value,
        unit=unit,
        metadata={
            "source_path": source,
            "path_to_value": path or f"schemes[0].metrics.{indicator}.value",
            "original_type": "number",
            "context": "",
        },
    )


def _safety_metrics(
    *,
    pf_value: float = 1,
    n1_rate: float = 96.0,
    margin: float = 10.0,
    over_count: float = 0,
    loading: float = 85.0,
    annual_cost: float = 1e7,
    construction_cost: float = 1e8,
) -> dict:
    return {
        "pf_convergence": {"status": "ok", "value": pf_value, "display_value": "是"},
        "n1_pass_rate": {"status": "ok", "value": n1_rate},
        "min_breaker_interrupt_margin_rate": {"status": "ok", "value": margin},
        "short_circuit_over_limit_count": {"status": "ok", "value": over_count},
        "post_contingency_max_equipment_loading_rate": {"status": "ok", "value": loading},
        "annual_cost": {"status": "ok", "value": annual_cost},
        "construction_cost": {"status": "ok", "value": construction_cost},
    }


class NormalizeClaimTagsTests(unittest.TestCase):
    def test_yuan_to_yi_becomes_calculate(self):
        claims = {
            "000006": _claim(
                "000006",
                "construction_cost",
                162000000,
                path="schemes[0].metrics.construction_cost.value",
            )
        }
        report = (
            '<claim id="000006" source_path="derived_metrics.json" '
            'path_to_value="schemes[0].metrics.construction_cost.value" '
            'policy="round(2)">1.62</claim>亿元'
        )
        out, stats = normalize_claim_tags_in_report(report, claims)
        self.assertIn("<calculate>", out)
        self.assertIn("/ 100000000", out)
        self.assertIn("output: 1.62", out)
        self.assertIn("construction_cost_yuan=claim_000006", out)
        self.assertNotIn('policy="round(2)">1.62</claim>', out)
        self.assertGreaterEqual(stats["converted_to_calculate"], 1)

    def test_wrong_claim_id_repaired_by_path_and_value(self):
        claims = {
            "000050": _claim(
                "000050",
                "n1_issue_contingencies",
                3,
                unit="个",
                path="schemes[3].metrics.n1_issue_contingencies.value",
            ),
            "000051": _claim(
                "000051",
                "new_line_length",
                201,
                unit="mile",
                path="schemes[3].metrics.new_line_length.value",
            ),
        }
        report = (
            '<claim id="000050" source_path="derived_metrics.json" '
            'path_to_value="schemes[3].metrics.new_line_length.value" '
            'policy="exact">201</claim>'
        )
        out, stats = normalize_claim_tags_in_report(report, claims)
        self.assertIn('id="000051"', out)
        self.assertIn(">201</claim>", out)
        self.assertNotIn('id="000050"', out)
        self.assertGreaterEqual(stats["rewritten"], 1)

    def test_consistent_claim_kept(self):
        claims = {
            "000012": _claim(
                "000012",
                "new_line_length",
                91,
                unit="mile",
                path="schemes[0].metrics.new_line_length.value",
            )
        }
        report = (
            '<claim id="000012" source_path="derived_metrics.json" '
            'path_to_value="schemes[0].metrics.new_line_length.value" '
            'policy="exact">91</claim>'
        )
        out, stats = normalize_claim_tags_in_report(report, claims)
        self.assertIn('id="000012"', out)
        self.assertIn(">91</claim>", out)
        self.assertEqual(stats["converted_to_calculate"], 0)
        self.assertEqual(stats["stripped"], 0)

    def test_unresolvable_claim_stripped(self):
        claims = {
            "000001": _claim(
                "000001",
                "n1_pass_rate",
                95.0,
                unit="%",
                path="schemes[0].metrics.n1_pass_rate.value",
            )
        }
        report = (
            '<claim id="999999" source_path="x.json" '
            'path_to_value="schemes[9].metrics.missing.value" '
            'policy="exact">12</claim>'
        )
        out, stats = normalize_claim_tags_in_report(report, claims)
        self.assertNotIn("<claim", out)
        self.assertIn("12", out)
        self.assertGreaterEqual(stats["stripped"], 1)


class PcnVerificationPassedTests(unittest.TestCase):
    def test_stripped_claims_causes_pcn_failure(self):
        stats = {
            "total_claims": 5,
            "verified_claims": 5,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 1,
        }
        self.assertFalse(compute_pcn_verification_passed(stats))

    def test_zero_total_claims_causes_pcn_failure(self):
        stats = {
            "total_claims": 0,
            "verified_claims": 0,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 0,
        }
        self.assertFalse(compute_pcn_verification_passed(stats))

    def test_all_verified_without_stripped_passes(self):
        stats = {
            "total_claims": 3,
            "verified_claims": 3,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 0,
        }
        self.assertTrue(compute_pcn_verification_passed(stats))


class SafetyRecommendationTests(unittest.TestCase):
    def _derived_all_negative_margin(self):
        schemes = []
        for i, cost in enumerate([162e6, 245e6, 175e6], start=1):
            metrics = _safety_metrics(
                margin=-462.29,
                over_count=2,
                annual_cost=cost * 0.1,
                construction_cost=cost,
            )
            schemes.append(
                {
                    "proposal_index": i,
                    "proposal_name": f"方案{i}",
                    "metrics": metrics,
                }
            )
        return {"schemes": schemes}

    def test_all_failed_analysis(self):
        analysis = analyze_safety_for_recommendation(self._derived_all_negative_margin())
        self.assertTrue(analysis["all_failed"])
        self.assertTrue(analysis["no_proven_safe_scheme"])
        self.assertEqual(analysis["best_economy_among_all"]["label"], "方案1")

    def test_all_missing_metrics_not_evaluated(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": {},
                }
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        self.assertEqual(len(analysis["not_evaluated_schemes"]), 1)
        self.assertEqual(len(analysis["passed_schemes"]), 0)
        evaluation = evaluate_scheme_hard_constraints(derived["schemes"][0])
        self.assertEqual(evaluation["status"], "not_evaluated")
        self.assertTrue(evaluation["missing_metrics"])

    def test_nan_and_infinity_not_evaluated(self):
        scheme = {
            "proposal_index": 1,
            "proposal_name": "方案1",
            "metrics": {
                "pf_convergence": {"status": "ok", "value": 1, "display_value": "是"},
                "n1_pass_rate": {"status": "ok", "value": float("nan")},
                "min_breaker_interrupt_margin_rate": {"status": "ok", "value": 5},
                "short_circuit_over_limit_count": {"status": "ok", "value": 0},
                "post_contingency_max_equipment_loading_rate": {
                    "status": "ok",
                    "value": float("inf"),
                },
            },
        }
        evaluation = evaluate_scheme_hard_constraints(scheme)
        self.assertEqual(evaluation["status"], "not_evaluated")
        self.assertIn("n1_pass_rate", evaluation["missing_metrics"])
        self.assertIn("post_contingency_max_equipment_loading_rate", evaluation["missing_metrics"])

    def test_enforce_removes_direct_recommend(self):
        report = """#### 综合比较推荐方案

短路电流超标为共性问题，不影响相对排序；方案1经济最优。

综上所述，**本阶段推荐方案1**。建议优先实施。
"""
        analysis = analyze_safety_for_recommendation(self._derived_all_negative_margin())
        out = enforce_safety_recommendation(report, analysis)
        self.assertIn("当前没有可直接推荐实施的方案", out)
        self.assertIn("整改后的经济优先候选", out)
        self.assertNotIn("本阶段推荐方案1", out)
        self.assertNotIn("建议优先实施", out)
        self.assertNotIn("（已按安全硬约束调整，取消直接推荐）", out)

    def test_partial_pass_does_not_recommend_failed_scheme(self):
        derived = self._derived_all_negative_margin()
        derived["schemes"][0]["metrics"]["min_breaker_interrupt_margin_rate"]["value"] = 10
        derived["schemes"][0]["metrics"]["short_circuit_over_limit_count"]["value"] = 0
        analysis = analyze_safety_for_recommendation(derived)
        self.assertTrue(analysis["any_passed"])
        self.assertFalse(analysis["all_failed"])
        report = """#### 综合比较推荐方案

综上所述，**本阶段推荐方案2**。
"""
        out = enforce_safety_recommendation(report, analysis)
        self.assertNotIn("本阶段推荐方案2", out)
        self.assertIn("方案1", out)
        self.assertIn("安全硬约束", out)

    def test_not_evaluated_recommendation_removed_when_passed_exists(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(margin=10, over_count=0),
                },
                {
                    "proposal_index": 2,
                    "proposal_name": "方案2",
                    "metrics": {
                        "pf_convergence": {"status": "ok", "value": 1, "display_value": "是"},
                    },
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**推荐方案2**。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertNotIn("推荐方案2", out)
        self.assertIn("待补充数据方案", out)
        self.assertIn("方案1", out)

    def test_not_evaluated_switches_to_best_passed(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(
                        margin=10,
                        over_count=0,
                        annual_cost=2e7,
                        construction_cost=2e8,
                    ),
                },
                {
                    "proposal_index": 2,
                    "proposal_name": "方案2",
                    "metrics": {"pf_convergence": {"status": "ok", "value": 1, "display_value": "是"}},
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n建议优先实施方案2。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertIn("原推荐 **方案2**", out)
        self.assertIn("方案1", out)
        self.assertIn("可作为本阶段推荐方案", out)

    def test_no_passed_not_evaluated_only_pending_data(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": {"pf_convergence": {"status": "ok", "value": 1, "display_value": "是"}},
                }
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**推荐方案1**。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertIn("待补充数据方案", out)
        self.assertIn("当前没有可直接推荐实施的方案", out)
        self.assertNotIn("可作为本阶段推荐方案", out)

    def test_failed_and_not_evaluated_mixed_no_direct_implementation(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(margin=-1, over_count=1),
                },
                {
                    "proposal_index": 2,
                    "proposal_name": "方案2",
                    "metrics": {"pf_convergence": {"status": "ok", "value": 1, "display_value": "是"}},
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**最终推荐方案1**。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertIn("整改后的经济优先候选", out)
        self.assertIn("待补充数据方案", out)
        self.assertNotIn("最终推荐方案1", out)

    def test_original_recommendation_identified_before_cleaning(self):
        report = "#### 综合比较推荐方案\n\n**推荐方案2**。\n"
        derived = self._derived_all_negative_margin()
        derived["schemes"][0]["metrics"]["min_breaker_interrupt_margin_rate"]["value"] = 10
        derived["schemes"][0]["metrics"]["short_circuit_over_limit_count"]["value"] = 0
        analysis = analyze_safety_for_recommendation(derived)
        lookup = {
            "方案1": {"label": "方案1", "index": 1, "status": "passed"},
            "方案2": {"label": "方案2", "index": 2, "status": "failed", "reasons": ["x"]},
        }
        original = identify_recommended_schemes(report, lookup)
        self.assertEqual(original, ["方案2"])
        classified = classify_recommended_schemes(original, lookup)
        self.assertEqual(classified["failed_recommended"], ["方案2"])

    def test_chinese_numeral_scheme_matching(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(margin=10, over_count=0),
                },
                {
                    "proposal_index": 10,
                    "proposal_name": "方案10",
                    "metrics": _safety_metrics(margin=-5, over_count=1),
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n建议优先实施方案十。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertNotIn("方案十", out)
        self.assertIn("方案1", out)

    def test_n1_threshold_read_from_rules(self):
        from unittest import mock

        analysis_default = analyze_safety_for_recommendation(
            {
                "schemes": [
                    {
                        "proposal_index": 1,
                        "proposal_name": "方案1",
                        "metrics": _safety_metrics(n1_rate=89.0),
                    }
                ]
            }
        )
        self.assertEqual(analysis_default["passed_schemes"], [])

        with mock.patch(
            "src.nodes.safety_recommendation.get_n1_pass_rate_hard_threshold",
            return_value=(85.0, "compare_rules.yaml"),
        ):
            analysis_lower = analyze_safety_for_recommendation(
                {
                    "schemes": [
                        {
                            "proposal_index": 1,
                            "proposal_name": "方案1",
                            "metrics": _safety_metrics(n1_rate=89.0),
                        }
                    ]
                }
            )
        self.assertEqual(len(analysis_lower["passed_schemes"]), 1)
        self.assertEqual(
            analysis_lower["applied_thresholds"]["n1_pass_rate"],
            85.0,
        )
        self.assertEqual(analysis_lower["rules_source"], "compare_rules.yaml")

    def test_no_passed_schemes_no_direct_implementation_recommend(self):
        derived = self._derived_all_negative_margin()
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**最终推荐方案1**。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertIn("当前没有可直接推荐实施的方案", out)
        self.assertIn("整改后的经济优先候选", out)
        self.assertNotIn("最终推荐方案1", out)

    def test_scheme_1_and_10_distinct(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(margin=10, over_count=0),
                },
                {
                    "proposal_index": 10,
                    "proposal_name": "方案10",
                    "metrics": _safety_metrics(margin=-5, over_count=1),
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**推荐方案10**。\n"
        out = enforce_safety_recommendation(report, analysis)
        self.assertNotIn("推荐方案10", out)
        self.assertIn("方案1", out)

    def test_safety_postprocess_idempotent(self):
        report = """#### 综合比较推荐方案

**本阶段推荐方案1**。建议优先实施。
"""
        analysis = analyze_safety_for_recommendation(self._derived_all_negative_margin())
        once = enforce_safety_recommendation(report, analysis)
        twice = enforce_safety_recommendation(once, analysis)
        three_times = enforce_safety_recommendation(twice, analysis)
        self.assertEqual(once, twice)
        self.assertEqual(twice, three_times)
        self.assertEqual(once.count("当前没有可直接推荐实施的方案"), 1)
        self.assertEqual(once.count("#### 综合比较推荐方案"), 1)
        self.assertNotIn("或（已按安全硬约束调整", once)

    def test_passed_not_evaluated_correction_idempotent_three_runs(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(
                        margin=10,
                        over_count=0,
                        annual_cost=2e7,
                        construction_cost=2e8,
                    ),
                },
                {
                    "proposal_index": 2,
                    "proposal_name": "方案2",
                    "metrics": {"pf_convergence": {"status": "ok", "value": 1, "display_value": "是"}},
                },
            ]
        }
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n建议优先实施方案2。\n"
        once = enforce_safety_recommendation(report, analysis)
        twice = enforce_safety_recommendation(once, analysis)
        three_times = enforce_safety_recommendation(twice, analysis)
        self.assertEqual(once, twice)
        self.assertEqual(twice, three_times)
        self.assertIn("原推荐 **方案2**", once)
        self.assertIn("待补充数据方案", once)
        self.assertNotIn("在经济性排序中领先", once)

    def test_passed_failed_correction_idempotent_three_runs(self):
        derived = self._derived_all_negative_margin()
        derived["schemes"][0]["metrics"]["min_breaker_interrupt_margin_rate"]["value"] = 10
        derived["schemes"][0]["metrics"]["short_circuit_over_limit_count"]["value"] = 0
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**本阶段推荐方案2**。\n"
        once = enforce_safety_recommendation(report, analysis)
        twice = enforce_safety_recommendation(once, analysis)
        three_times = enforce_safety_recommendation(twice, analysis)
        self.assertEqual(once, twice)
        self.assertEqual(twice, three_times)
        self.assertIn("未通过安全硬约束校核", once)

    def test_safety_fingerprint_change_regenerates_conclusion(self):
        derived = {
            "schemes": [
                {
                    "proposal_index": 1,
                    "proposal_name": "方案1",
                    "metrics": _safety_metrics(margin=10, over_count=0, annual_cost=1e7),
                },
                {
                    "proposal_index": 2,
                    "proposal_name": "方案2",
                    "metrics": _safety_metrics(margin=-5, over_count=1, annual_cost=2e7),
                },
            ]
        }
        analysis_v1 = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**推荐方案2**。\n"
        out_v1 = enforce_safety_recommendation(report, analysis_v1)
        self.assertIn("fingerprint=", out_v1)

        derived["schemes"][1]["metrics"]["min_breaker_interrupt_margin_rate"]["value"] = 10
        derived["schemes"][1]["metrics"]["short_circuit_over_limit_count"]["value"] = 0
        analysis_v2 = analyze_safety_for_recommendation(derived)
        from src.nodes.safety_recommendation import _safety_analysis_fingerprint

        self.assertNotEqual(
            _safety_analysis_fingerprint(analysis_v1),
            _safety_analysis_fingerprint(analysis_v2),
        )
        out_v2 = enforce_safety_recommendation(out_v1, analysis_v2)
        self.assertNotEqual(out_v1, out_v2)

    def test_safety_marker_and_section_not_duplicated(self):
        derived = self._derived_all_negative_margin()
        analysis = analyze_safety_for_recommendation(derived)
        report = "#### 综合比较推荐方案\n\n**最终推荐方案1**。\n"
        once = enforce_safety_recommendation(report, analysis)
        twice = enforce_safety_recommendation(once, analysis)
        self.assertEqual(once.count("<!-- safety-hard-constraint-conclusion"), 1)
        self.assertEqual(once.count("#### 综合比较推荐方案"), 1)
        self.assertEqual(twice.count("<!-- safety-hard-constraint-conclusion"), 1)

    def test_safety_conclusion_not_damaged_by_regex(self):
        report = """#### 综合比较推荐方案

**最终推荐方案2**。建议优先实施。
"""
        analysis = analyze_safety_for_recommendation(self._derived_all_negative_margin())
        out = enforce_safety_recommendation(report, analysis)
        self.assertNotIn("（已按安全硬约束调整，取消直接推荐）", out)
        self.assertNotIn("不得称为最终推荐方案或（", out)


class PcnReviewMessageTests(unittest.TestCase):
    def test_review_message_includes_stripped_and_calculate_once(self):
        message = format_pcn_review_message(
            {
                "total_claims": 8,
                "verified_claims": 7,
                "mismatched_claims": 0,
                "not_found_claims": 0,
                "pending_claims": 0,
                "stripped_claims": 1,
                "total_calculates": 3,
                "verified_calculates": 2,
                "mismatched_calculates": 1,
                "pending_calculates": 0,
                "invalid_calculates": 0,
            }
        )
        self.assertIn("移除标签1", message)
        self.assertEqual(message.count("移除标签"), 1)
        self.assertIn("Calculate总数3", message)
        self.assertNotIn("移除定位不到证据", message)


class PromptUnitRuleTests(unittest.TestCase):
    def test_claim_protocol_has_unit_rules(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "skills"
            / "report_generation"
            / "resources"
            / "claim_protocol.md"
        ).read_text(encoding="utf-8")
        self.assertIn("100000000", text)
        self.assertIn("162000000", text)
        self.assertIn("整体来自同一条", text)

    def test_report_skill_has_safety_rules(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "skills"
            / "report_generation"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("安全硬约束与最终推荐", text)
        self.assertIn("元→万元/亿元", text)
        self.assertIn("禁止过度推断", text)


if __name__ == "__main__":
    unittest.main()
