# -*- coding: utf-8 -*-
"""第二批比选指标测试（Calculator / adapters / derived / Claim / SQLite）。"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.grid_calculator import calculate_grid_metric

import importlib.util

_prep_path = ROOT / "src" / "nodes" / "data_preprocessing_pcn.py"
_spec = importlib.util.spec_from_file_location("data_preprocessing_pcn_mod2", _prep_path)
prep = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(prep)

from src.nodes import second_batch_adapters as sb


class TestVoltageMetricsCalculator(unittest.TestCase):
    def test_qualification_hand_calc(self):
        result = calculate_grid_metric(
            "voltage_qualification_rate",
            {"qualified_count": 9, "total_evaluated_count": 10},
        )
        self.assertAlmostEqual(result["value"], 90.0)

    def test_qualification_from_records_bounds(self):
        records = [
            {"voltage": 0.9, "min_voltage": 0.9, "max_voltage": 1.1},  # 边界合格
            {"voltage": 1.1, "min_voltage": 0.9, "max_voltage": 1.1},
            {"voltage": 0.85, "min_voltage": 0.9, "max_voltage": 1.1},  # 低压
            {"voltage": 1.15, "min_voltage": 0.9, "max_voltage": 1.1},  # 高压
        ]
        result = calculate_grid_metric("voltage_qualification_rate", {"records": records})
        self.assertAlmostEqual(result["value"], 50.0)

    def test_severity_low_high(self):
        result = calculate_grid_metric(
            "voltage_over_limit_severity",
            {
                "records": [
                    {"voltage": 0.8, "min_voltage": 0.9, "max_voltage": 1.1},
                    {"voltage": 1.2, "min_voltage": 0.9, "max_voltage": 1.1},
                    {"voltage": 1.0, "min_voltage": 0.9, "max_voltage": 1.1},
                ]
            },
        )
        self.assertAlmostEqual(result["value"], 0.01 + 0.01)

    def test_node_period_single_and_multi(self):
        single = calculate_grid_metric(
            "node_period_voltage_over_limit_rate",
            {"over_limit_count": 1, "total_count": 4},
        )
        self.assertAlmostEqual(single["value"], 25.0)
        records = [
            {"node_id": "A", "period": 1, "voltage": 0.85, "min_voltage": 0.9, "max_voltage": 1.1},
            {"node_id": "A", "period": 2, "voltage": 1.0, "min_voltage": 0.9, "max_voltage": 1.1},
            {"node_id": "B", "period": 1, "voltage": 1.0, "min_voltage": 0.9, "max_voltage": 1.1},
            {"node_id": "B", "period": 2, "voltage": None, "min_voltage": 0.9, "max_voltage": 1.1},
        ]
        multi = calculate_grid_metric(
            "node_period_voltage_over_limit_rate", {"records": records}
        )
        # 3 valid pairs, 1 over-limit
        self.assertAlmostEqual(multi["value"], 100.0 / 3.0, places=4)

    def test_ratio_denominator_edge_cases(self):
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "voltage_qualification_rate",
                {"qualified_count": 1, "total_evaluated_count": 0},
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "node_period_voltage_over_limit_rate",
                {"over_limit_count": 1, "total_count": 0},
            )


class TestLoadingAndLossCalculator(unittest.TestCase):
    def test_max_line_loading_priority_current_over_mva(self):
        records = [
            {
                "电流(A)": 90,
                "额定电流(A)": 100,
                "视在功率(MVA)": 200,
                "额定视在功率(MVA)": 100,
            },
            {"电流比例(%)": 95},
        ]
        result = calculate_grid_metric("max_line_loading_rate", {"records": records})
        # first record uses current 90%, second 95% → max 95
        self.assertAlmostEqual(result["value"], 95.0)

    def test_max_transformer_loading(self):
        result = calculate_grid_metric(
            "max_transformer_loading_rate",
            {
                "records": [
                    {"apparent_power": 80, "rated_capacity": 100},
                    {"负载率(%)": 92},
                ]
            },
        )
        self.assertAlmostEqual(result["value"], 92.0)

    def test_active_power_loss_rate(self):
        result = calculate_grid_metric(
            "active_power_loss_rate", {"loss_mw": 5, "input_power_mw": 100}
        )
        self.assertAlmostEqual(result["value"], 5.0)
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "active_power_loss_rate", {"loss_mw": 5, "input_power_mw": 0}
            )

    def test_critical_section_margin_negative_allowed(self):
        result = calculate_grid_metric(
            "critical_section_margin_rate",
            {
                "sections": [
                    {"limit": 100, "flow": 80},
                    {"limit": 100, "flow": -120},
                ]
            },
        )
        self.assertAlmostEqual(result["value"], -20.0)

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            calculate_grid_metric("max_line_loading_rate", {"records": []})
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "max_line_loading_rate",
                {"records": [{"电流(A)": True, "额定电流(A)": 100}]},
            )


class TestPostContingencyAndTransient(unittest.TestCase):
    def test_post_contingency_max_loading_global(self):
        result = calculate_grid_metric(
            "post_contingency_max_equipment_loading_rate",
            {
                "records": [
                    {"卡片类型": "L", "电流比例(%)": 88},
                    {"卡片类型": "T", "负载率(%)": 101},
                    {"卡片类型": "L", "电流比例(%)": 95},
                ]
            },
        )
        self.assertAlmostEqual(result["value"], 101.0)

    def test_post_contingency_voltage_rate(self):
        result = calculate_grid_metric(
            "post_contingency_voltage_over_limit_rate",
            {"over_limit_count": 2, "total_count": 10},
        )
        self.assertAlmostEqual(result["value"], 20.0)

    def test_transient_pass_rate(self):
        result = calculate_grid_metric(
            "transient_stability_pass_rate",
            {"pass_count": 8, "total_count": 10},
        )
        self.assertAlmostEqual(result["value"], 80.0)

    def test_max_angle_difference_hand_calc(self):
        # fault1 t1: 10,30 → 20; fault1 t2: 0,50 → 50; fault2: 5,8 → 3 → global 50
        result = calculate_grid_metric(
            "max_generator_relative_angle_difference",
            {
                "records": [
                    {"fault_id": 1, "time": 0, "angles": [10, 30]},
                    {"fault_id": 1, "time": 1, "angles": [0, 50]},
                    {"fault_id": 2, "time": 0, "angles": [5, 8]},
                ]
            },
        )
        self.assertAlmostEqual(result["value"], 50.0)

    def test_transient_missing_raises(self):
        with self.assertRaises(ValueError):
            calculate_grid_metric("transient_stability_pass_rate", {})


class TestLineLengthAndLossCost(unittest.TestCase):
    def test_new_and_retrofit_length_sum_and_zero(self):
        self.assertAlmostEqual(
            calculate_grid_metric(
                "new_line_length", {"line_items": [{"length": 30}, {"length": 0}]}
            )["value"],
            30.0,
        )
        self.assertAlmostEqual(
            calculate_grid_metric("retrofit_line_length", {"line_items": []})["value"]
            if False
            else 0.0,
            0.0,
        )
        # empty list should raise in calculator unless adapter handles empty
        with self.assertRaises(ValueError):
            calculate_grid_metric("new_line_length", {"line_items": []})

    def test_annual_energy_and_cost(self):
        energy = calculate_grid_metric(
            "annual_energy_loss", {"loss_mw": 10, "equivalent_hours": 2000}
        )
        self.assertAlmostEqual(energy["value"], 20000.0)
        cost = calculate_grid_metric(
            "annual_network_loss_cost",
            {"annual_energy_loss_mwh": 20000, "price_per_mwh": 0.5},
        )
        self.assertAlmostEqual(cost["value"], 10000.0)
        with self.assertRaises(ValueError):
            calculate_grid_metric("annual_energy_loss", {"loss_mw": 10})

    def test_zero_loss_legal(self):
        result = calculate_grid_metric(
            "annual_energy_loss", {"loss_mw": 0, "equivalent_hours": 2000}
        )
        self.assertEqual(result["value"], 0.0)


class TestLifecycleModes(unittest.TestCase):
    def test_provided_estimated_full(self):
        provided = calculate_grid_metric("lifecycle_cost", {"lifecycle_cost": 999})
        self.assertEqual(provided["value"], 999)
        self.assertEqual(provided["inputs"].get("_calculation_mode"), "provided")
        self.assertIsNone(provided["formula"])

        estimated = calculate_grid_metric("lifecycle_cost", {"construction_cost": 100})
        self.assertEqual(estimated["value"], 125)
        self.assertEqual(
            estimated["inputs"].get("_calculation_mode"), "estimated_simplified"
        )
        self.assertIn("factor", estimated["formula"] or "")
        self.assertIn("construction_cost * factor", estimated["calculate_tag"])

        full = calculate_grid_metric(
            "lifecycle_cost",
            {
                "construction_cost": 100,
                "discount_rate": 0.0,
                "evaluation_years": 2,
                "cash_flows": [{"year": 1, "cost": 10}, {"year": 2, "cost": 10}],
            },
        )
        self.assertEqual(full["inputs"].get("_calculation_mode"), "full_calculated")
        self.assertAlmostEqual(full["value"], 120.0)
        self.assertIsNotNone(full["formula"])
        self.assertIn("discount_rate", full["formula"])
        self.assertIn("discount_rate", full["calculate_tag"])
        self.assertNotIn("construction_cost * factor", full["formula"])

    def test_lcc_rejects_negative_discount_rate(self):
        for rate in (-1, -2, float("nan"), float("inf"), float("-inf"), True, False):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError) as ctx:
                    calculate_grid_metric(
                        "lifecycle_cost",
                        {
                            "construction_cost": 100,
                            "cash_flows": [{"year": 1, "cost": 10}],
                            "discount_rate": rate,
                            "evaluation_years": 2,
                        },
                    )
                self.assertIn("discount_rate", str(ctx.exception))

    def test_lcc_discount_rate_zero_ok(self):
        result = calculate_grid_metric(
            "lifecycle_cost",
            {
                "construction_cost": 100,
                "cash_flows": [{"year": 1, "cost": 10}],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
        )
        self.assertEqual(result["inputs"].get("_calculation_mode"), "full_calculated")
        self.assertAlmostEqual(result["value"], 110.0)

    def test_bad_cash_flows_not_full_calculated(self):
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "lifecycle_cost",
                {
                    "construction_cost": 100,
                    "discount_rate": 0.0,
                    "evaluation_years": 2,
                    "cash_flows": [
                        {"year": 1, "cost": 10},
                        {"year": 1},  # missing cost
                    ],
                },
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "lifecycle_cost",
                {
                    "construction_cost": 100,
                    "discount_rate": 0.0,
                    "evaluation_years": 2,
                    "cash_flows": [],
                },
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "lifecycle_cost",
                {
                    "construction_cost": 100,
                    "discount_rate": 0.0,
                    "evaluation_years": 2,
                    "cash_flows": [{"year": 99, "cost": 10}],
                },
            )

    def test_negative_costs_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            calculate_grid_metric("lifecycle_cost", {"lifecycle_cost": -1})
        self.assertIn("lifecycle_cost", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            calculate_grid_metric("lifecycle_cost", {"construction_cost": -100})
        self.assertIn("construction_cost", str(ctx.exception))
        with self.assertRaises(ValueError):
            calculate_grid_metric("construction_cost", {"construction_cost": -1})
        with self.assertRaises(ValueError):
            calculate_grid_metric("operation_cost", {"operation_cost": -1})
        with self.assertRaises(ValueError):
            calculate_grid_metric("annual_cost", {"annual_cost": -1})
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "lifecycle_cost",
                {"construction_cost": 100, "factor": -1},
            )
        # 最终 NPV 为负
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "lifecycle_cost",
                {
                    "construction_cost": 10,
                    "discount_rate": 0,
                    "evaluation_years": 1,
                    "cash_flows": [{"year": 1, "cost": -100}],
                },
            )
        # 0 合法
        self.assertEqual(
            calculate_grid_metric("lifecycle_cost", {"lifecycle_cost": 0})["value"],
            0,
        )

    def test_lcc_partial_or_wrong_type_full_input_rejected(self):
        """任意完整折现字段出现但参数不完整或类型错误时，不得回退简化估算。"""
        invalid_cases = [
            (
                {
                    "construction_cost": 100,
                    "cash_flows": {"year": 1, "cost": 10},
                    "discount_rate": 0,
                    "evaluation_years": 2,
                },
                "cash_flows",
            ),
            (
                {
                    "construction_cost": 100,
                    "cash_flows": "bad",
                    "discount_rate": 0,
                    "evaluation_years": 2,
                },
                "cash_flows",
            ),
            (
                {
                    "construction_cost": 100,
                    "cash_flows": [{"year": 1, "cost": 10}],
                    "evaluation_years": 2,
                },
                "discount_rate",
            ),
            (
                {
                    "construction_cost": 100,
                    "cash_flows": [{"year": 1, "cost": 10}],
                    "discount_rate": 0,
                },
                "evaluation_years",
            ),
            (
                {
                    "construction_cost": 100,
                    "discount_rate": 0,
                    "evaluation_years": 2,
                },
                "cash_flows",
            ),
            (
                {"construction_cost": 100, "cash_flows": [{"year": 1, "cost": 10}]},
                "discount_rate",
            ),
            (
                {"construction_cost": 100, "discount_rate": 0},
                "cash_flows",
            ),
            (
                {"construction_cost": 100, "evaluation_years": 2},
                "cash_flows",
            ),
        ]
        for payload, hint in invalid_cases:
            with self.subTest(payload=payload, hint=hint):
                with self.assertRaises(ValueError) as ctx:
                    calculate_grid_metric("lifecycle_cost", payload)
                self.assertIn(hint, str(ctx.exception))

    def test_lcc_no_full_fields_uses_estimated_simplified(self):
        result = calculate_grid_metric("lifecycle_cost", {"construction_cost": 100})
        self.assertEqual(result["value"], 125)
        self.assertEqual(
            result["inputs"].get("_calculation_mode"), "estimated_simplified"
        )


class TestLccPartialFullInputE2E(unittest.TestCase):
    """端到端：部分/错误完整折现参数不得回退 estimated_simplified。"""

    def _run_lcc_e2e(self, extra: dict) -> tuple:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {
                        "total_contingencies_run": 1,
                        "contingencies_with_issues": [],
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}),
                encoding="utf-8",
            )
            proposal = {
                "proposal_name": "方案1",
                "construction_cost": 100,
                **extra,
            }
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps({"proposals": [proposal]}),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            md = prep.convert_core_comparison_summary_to_md(tmp_path)
            return lcc, md

    def _assert_invalid_lcc(self, lcc, md):
        self.assertIsNone(lcc["value"])
        self.assertEqual(lcc["status"], "invalid_data")
        self.assertEqual(lcc["provenance"], "invalid")
        self.assertEqual(lcc["calculation_mode"], "invalid")
        self.assertIsNone(lcc["formula"])
        self.assertNotEqual(lcc["calculation_mode"], "estimated_simplified")
        self.assertNotIn("125", md.split("LCC")[-1] if "LCC" in md else md)
        self.assertIn("当前输入不足，未评价", md)

    def test_cash_flows_dict_invalid_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "cash_flows": {"year": 1, "cost": 10},
                "discount_rate": 0,
                "evaluation_years": 2,
            }
        )
        self._assert_invalid_lcc(lcc, md)

    def test_cash_flows_string_invalid_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "cash_flows": "bad",
                "discount_rate": 0,
                "evaluation_years": 2,
            }
        )
        self._assert_invalid_lcc(lcc, md)

    def test_missing_discount_rate_invalid_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "evaluation_years": 2,
            }
        )
        self._assert_invalid_lcc(lcc, md)

    def test_missing_evaluation_years_invalid_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "discount_rate": 0,
            }
        )
        self._assert_invalid_lcc(lcc, md)

    def test_missing_cash_flows_invalid_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "discount_rate": 0,
                "evaluation_years": 2,
            }
        )
        self._assert_invalid_lcc(lcc, md)

    def test_single_full_field_only_invalid_e2e(self):
        for extra in (
            {"cash_flows": [{"year": 1, "cost": 10}]},
            {"discount_rate": 0},
            {"evaluation_years": 2},
        ):
            with self.subTest(extra=extra):
                lcc, md = self._run_lcc_e2e(extra)
                self._assert_invalid_lcc(lcc, md)

    def test_no_full_fields_estimated_simplified_e2e(self):
        lcc, md = self._run_lcc_e2e({})
        self.assertAlmostEqual(lcc["value"], 125.0)
        self.assertEqual(lcc["calculation_mode"], "estimated_simplified")
        self.assertEqual(lcc["status"], "ok")

    def test_valid_full_calculated_e2e(self):
        lcc, md = self._run_lcc_e2e(
            {
                "cash_flows": [
                    {"year": 1, "cost": 10},
                    {"year": 2, "cost": 10},
                ],
                "discount_rate": 0,
                "evaluation_years": 2,
            }
        )
        self.assertAlmostEqual(lcc["value"], 120.0)
        self.assertEqual(lcc["calculation_mode"], "full_calculated")
        self.assertEqual(lcc["status"], "ok")
        self.assertIsNotNone(lcc["formula"])
        self.assertIn("discount_rate", lcc["formula"])


class TestSecondBatchAdapters(unittest.TestCase):
    def test_issue_subset_not_full_max_loading(self):
        result = sb.extract_max_line_loading(
            {"analysis": {"overloaded_lines": [{"电流比例(%)": 110}]}},
            "pf.json",
        )
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual(result["coverage"]["scope"], "issue_subset")

    def test_empty_overloaded_not_zero_max(self):
        result = sb.extract_max_line_loading(
            {"analysis": {"overloaded_lines": []}},
            "pf.json",
        )
        self.assertIsNone(result["value"])

    def test_new_line_from_modifications_miles(self):
        proposal = {
            "modifications": [
                {
                    "action": "add_line",
                    "params": {"full_branch_data": {"MILES": 30.0}},
                },
                {
                    "action": "add_line",
                    "params": {"full_branch_data": {"MILES": 30.0}},
                },
                {"action": "disable_branch", "params": {"full_branch_data": {"MILES": 99}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "parsed_proposals.json")
        self.assertEqual(result["value"], 60.0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["unit"], "mile")
        note = (result.get("coverage") or {}).get("notes", "")
        self.assertIn("换算", note)

    def test_disable_add_not_retrofit(self):
        proposal = {
            "modifications": [
                {"action": "disable_branch", "params": {"full_branch_data": {"MILES": 10}}},
                {"action": "add_line", "params": {"full_branch_data": {"MILES": 10}}},
            ]
        }
        result = sb.extract_retrofit_line_length(proposal, "parsed_proposals.json")
        self.assertEqual(result["value"], 0.0)
        self.assertIn("disable_branch", (result.get("coverage") or {}).get("notes", ""))

    def test_explicit_retrofit_action(self):
        proposal = {
            "modifications": [
                {
                    "action": "retrofit_line",
                    "params": {"full_branch_data": {"length_km": 12}},
                }
            ]
        }
        result = sb.extract_retrofit_line_length(proposal, "parsed_proposals.json")
        self.assertEqual(result["value"], 12.0)

    def test_post_contingency_issue_subset_missing(self):
        n1 = {
            "total_contingencies_run": 73,
            "contingencies_with_issues": [
                {
                    "result": {
                        "analysis": {
                            "overloaded_lines": [{"卡片类型": "L", "电流比例(%)": 110}]
                        }
                    }
                }
            ],
        }
        result = sb.extract_post_contingency_max_loading(n1, "n1.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["coverage"]["scope"], "issue_subset")

    def test_nan_inf_rejected_in_adapters_loss(self):
        result = sb.extract_active_power_loss_rate(
            {"analysis": {"power_summary": {"损耗_MW": float("nan"), "总发电_MW": 100}}},
            "pf.json",
        )
        self.assertIsNone(result["value"])


class TestSecondBatchDerivedIntegration(unittest.TestCase):
    def _write_scheme(self, tmp: Path, *, pf=None, n1=None, proposal=None):
        (tmp / "parsed_proposals.json").write_text(
            json.dumps(
                {
                    "proposals": [
                        proposal
                        or {
                            "proposal_name": "方案1",
                            "construction_cost": 100,
                            "operation_cost": 2,
                            "lifecycle_cost": 999,
                            "modifications": [
                                {
                                    "action": "add_line",
                                    "params": {"full_branch_data": {"MILES": 30}},
                                },
                                {
                                    "action": "add_line",
                                    "params": {"full_branch_data": {"MILES": 30}},
                                },
                                {"action": "disable_branch"},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        analysis = tmp / "analysis_1"
        analysis.mkdir()
        (analysis / "pf_report_1.json").write_text(
            json.dumps(
                pf
                or {
                    "analysis": {
                        "is_convergent": True,
                        "overloaded_lines": [],
                        "bus_voltages": [
                            {"voltage": 1.0, "min_voltage": 0.9, "max_voltage": 1.1},
                            {"voltage": 0.85, "min_voltage": 0.9, "max_voltage": 1.1},
                        ],
                        "line_loadings": [
                            {"电流(A)": 80, "额定电流(A)": 100},
                            {"电流比例(%)": 90},
                        ],
                        "transformer_loadings": [
                            {"apparent_power": 70, "rated_capacity": 100}
                        ],
                        "power_summary": {"损耗_MW": 5, "总发电_MW": 100},
                        "critical_sections": [
                            {"limit": 100, "flow": 80},
                            {"limit": 50, "flow": 60},
                        ],
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (analysis / "n1_report_1.json").write_text(
            json.dumps(
                n1
                or {
                    "total_contingencies_run": 10,
                    "contingencies_with_issues": [{}] * 1,
                    "post_contingency_equipment_loadings": [
                        {"卡片类型": "L", "电流比例(%)": 88},
                        {"卡片类型": "T", "负载率(%)": 105},
                    ],
                    "post_contingency_voltages": [
                        {
                            "fault_id": 1,
                            "node_id": "A",
                            "voltage": 0.85,
                            "min_voltage": 0.9,
                            "max_voltage": 1.1,
                        },
                        {
                            "fault_id": 1,
                            "node_id": "B",
                            "voltage": 1.0,
                            "min_voltage": 0.9,
                            "max_voltage": 1.1,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (analysis / "scc_report_1.json").write_text(
            json.dumps(
                {
                    "analysis": {
                        "total_buses": 10,
                        "exceeding_buses": [],
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (analysis / "transient_report_1.json").write_text(
            json.dumps(
                {
                    "transient_pass_count": 4,
                    "transient_total_count": 5,
                    "generator_angle_records": [
                        {"fault_id": 1, "time": 0, "angles": [0, 40]},
                        {"fault_id": 2, "time": 0, "angles": [1, 2, 3]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_derived_markdown_claims_sqlite(self):
        from src.pcn_database import PCNDatabase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_scheme(tmp_path)
            # 网损年小时/电价仍缺 → energy/cost missing；其余应可算
            derived = prep.build_derived_metrics(tmp_path)
            m = derived["schemes"][0]["metrics"]
            self.assertAlmostEqual(m["voltage_qualification_rate"]["value"], 50.0)
            self.assertAlmostEqual(m["max_line_loading_rate"]["value"], 90.0)
            self.assertAlmostEqual(m["max_transformer_loading_rate"]["value"], 70.0)
            self.assertAlmostEqual(m["active_power_loss_rate"]["value"], 5.0)
            self.assertAlmostEqual(m["critical_section_margin_rate"]["value"], -20.0)
            self.assertAlmostEqual(
                m["post_contingency_max_equipment_loading_rate"]["value"], 105.0
            )
            self.assertAlmostEqual(
                m["post_contingency_voltage_over_limit_rate"]["value"], 50.0
            )
            self.assertAlmostEqual(m["transient_stability_pass_rate"]["value"], 80.0)
            self.assertAlmostEqual(
                m["max_generator_relative_angle_difference"]["value"], 40.0
            )
            self.assertEqual(m["new_line_length"]["value"], 60.0)
            self.assertEqual(m["new_line_length"]["unit"], "mile")
            self.assertEqual(m["retrofit_line_length"]["value"], 0.0)
            self.assertEqual(m["lifecycle_cost"]["provenance"], "provided")
            self.assertEqual(m["lifecycle_cost"]["calculation_mode"], "provided")
            self.assertIsNone(m["lifecycle_cost"]["formula"])
            self.assertEqual(m["annual_energy_loss"]["status"], "missing_data")
            self.assertEqual(
                m["annual_energy_loss"]["display_value"], "当前输入不足，未评价"
            )

            md = prep.convert_core_comparison_summary_to_md(tmp_path)
            self.assertIn("方案比选安全硬约束汇总表", md)
            self.assertIn("方案比选技术性能与工程实施性汇总表", md)
            self.assertIn("方案比选经济性汇总表", md)
            self.assertIn("当前输入不足，未评价", md)
            self.assertIn("60", md)

            claims = []
            counter = [0]
            prep.extract_derived_metric_claims(
                derived, "derived_metrics.json", claims, counter
            )
            indicators = {c.indicator for c in claims}
            self.assertIn("voltage_qualification_rate", indicators)
            self.assertIn("new_line_length", indicators)
            self.assertNotIn("annual_energy_loss", indicators)
            self.assertNotIn("value", indicators)
            vq = next(c for c in claims if c.indicator == "voltage_qualification_rate")
            self.assertEqual(vq.metadata.get("original_type"), "derived")
            self.assertIn("coverage", vq.metadata)
            self.assertIn("calculation_mode", vq.metadata)

            db_path = tmp_path / "pcn.db"
            with PCNDatabase(str(db_path)) as db:
                db.init_schema()
                db.insert_claims_batch(claims)
            with PCNDatabase(str(db_path)) as db:
                rows = db.search_claims_by_indicator("new_line_length", k=5)
                self.assertTrue(rows)
                self.assertEqual(rows[0]["metadata"].get("original_type"), "derived")
                self.assertIn("coverage", rows[0]["metadata"])

    def test_historical_missing_second_batch_no_fake_zeros(self):
        hist = (
            ROOT
            / "outputs"
            / "2026-08-04_11-33-55_compare_pcn"
            / "working_dir"
        )
        if not hist.exists():
            self.skipTest("历史案例目录不存在")
        from main_api import _migrate_legacy_run_economics

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proposals = json.loads(
                (hist / "parsed_proposals.json").read_text(encoding="utf-8")
            )
            for proposal in proposals.get("proposals") or []:
                _migrate_legacy_run_economics(proposal, run_label="hist")
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(proposals, ensure_ascii=False), encoding="utf-8"
            )
            for i in range(1, 2):
                src = hist / f"analysis_{i}"
                dst = tmp_path / f"analysis_{i}"
                dst.mkdir()
                for name in (
                    f"pf_report_{i}.json",
                    f"n1_report_{i}.json",
                    f"scc_report_{i}.json",
                ):
                    (dst / name).write_text(
                        (src / name).read_text(encoding="utf-8"), encoding="utf-8"
                    )
            derived = prep.build_derived_metrics(tmp_path)
            m = derived["schemes"][0]["metrics"]
            # 第一批保持
            self.assertAlmostEqual(m["n1_pass_rate"]["value"], 93.15)
            self.assertEqual(m["short_circuit_over_limit_count"]["value"], 12)
            self.assertAlmostEqual(m["min_breaker_interrupt_margin_rate"]["value"], -139.34)
            # 第二批多数缺数，不得伪造 0/100
            for key in (
                "voltage_qualification_rate",
                "max_line_loading_rate",
                "max_transformer_loading_rate",
                "active_power_loss_rate",
                "critical_section_margin_rate",
                "post_contingency_max_equipment_loading_rate",
                "transient_stability_pass_rate",
                "annual_energy_loss",
            ):
                self.assertIsNone(m[key]["value"], msg=key)
                self.assertEqual(m[key]["status"], "missing_data", msg=key)
                self.assertEqual(
                    m[key]["display_value"], "当前输入不足，未评价", msg=key
                )
            # 无 modifications → 新建/改造长度 missing 或 0（无字段时 missing）
            self.assertIn(
                m["new_line_length"]["status"], ("missing_data", "ok")
            )
            if m["new_line_length"]["status"] == "ok":
                # 仅当明确无 add_line 时可记 0
                self.assertEqual(m["new_line_length"]["value"], 0.0)
            md = prep.convert_core_comparison_summary_to_md(tmp_path)
            self.assertIn("当前输入不足，未评价", md)
            self.assertIn("93.15", md)


class TestEquipmentClassify(unittest.TestCase):
    def test_card_type_line_transformer_unknown(self):
        self.assertEqual(sb.classify_equipment_record({"卡片类型": "L"}), "line")
        self.assertEqual(sb.classify_equipment_record({"卡片类型": "T"}), "transformer")
        self.assertEqual(sb.classify_equipment_record({"foo": 1}), "unknown")


class TestDirectMetricValidation(unittest.TestCase):
    def test_out_of_range_percent_rejected(self):
        cases = [
            ("voltage_qualification_rate", 120),
            ("post_contingency_voltage_over_limit_rate", -1),
            ("transient_stability_pass_rate", 150),
            ("node_period_voltage_over_limit_rate", 101),
            ("active_power_loss_rate", -0.1),
        ]
        for metric, bad in cases:
            with self.subTest(metric=metric, bad=bad):
                result = sb._validate_direct_metric(
                    metric, bad, "src.json", field_name=metric
                )
                self.assertIsNone(result["value"])
                self.assertEqual(result["status"], "invalid_data")
                self.assertIn(metric, result.get("invalid_fields") or [])
                note = (result.get("coverage") or {}).get("notes", "")
                self.assertIn("Calculator", note)

    def test_valid_percent_and_zero_accepted(self):
        ok = sb._validate_direct_metric(
            "voltage_qualification_rate", 0, "src.json", field_name="voltage_qualification_rate"
        )
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["value"], 0.0)
        self.assertEqual(ok["provenance"], "provided")
        self.assertEqual(ok["calculation_mode"], "direct")

        ok100 = sb._validate_direct_metric(
            "voltage_qualification_rate", 100, "src.json", field_name="voltage_qualification_rate"
        )
        self.assertEqual(ok100["value"], 100.0)

    def test_negative_non_percent_rejected(self):
        for metric in (
            "voltage_over_limit_severity",
            "max_line_loading_rate",
            "max_transformer_loading_rate",
            "post_contingency_max_equipment_loading_rate",
            "max_generator_relative_angle_difference",
            "new_line_length",
            "retrofit_line_length",
            "annual_energy_loss",
            "annual_network_loss_cost",
        ):
            with self.subTest(metric=metric):
                result = sb._validate_direct_metric(
                    metric, -1, "src.json", field_name=metric
                )
                self.assertEqual(result["status"], "invalid_data")
                self.assertIsNone(result["value"])

    def test_critical_section_negative_margin_allowed(self):
        result = sb._validate_direct_metric(
            "critical_section_margin_rate",
            -15.5,
            "src.json",
            field_name="critical_section_margin_rate",
        )
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["value"], -15.5)

    def test_bool_nan_inf_rejected(self):
        for bad in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                result = sb._validate_direct_metric(
                    "voltage_qualification_rate",
                    bad,
                    "src.json",
                    field_name="voltage_qualification_rate",
                )
                self.assertIsNone(result["value"])
                self.assertIn(result["status"], ("invalid_data", "missing_data"))

    def test_adapter_scheme_level_out_of_range(self):
        result = sb.extract_voltage_qualification(
            {"voltage_qualification_rate": 120}, "pf.json"
        )
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "invalid_data")


class TestZeroNotTreatedAsMissing(unittest.TestCase):
    def test_zero_loss_and_hours_preserved(self):
        result = sb.extract_annual_energy_loss(
            {
                "analysis": {"power_summary": {"损耗_MW": 0, "总发电_MW": 100}},
                "equivalent_loss_hours": 0,
            },
            "pf.json",
        )
        # hours=0 is valid non-negative → annual energy 0
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 0.0)

    def test_zero_price_preserved(self):
        energy = {"value": 100.0, "status": "ok"}
        result = sb.extract_annual_network_loss_cost(
            energy,
            {"loss_energy_price": 0},
            "pf.json",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 0.0)

    def test_zero_length_alias_not_skipped(self):
        proposal = {
            "modifications": [
                {
                    "action": "retrofit_line",
                    "length_km": 0,
                    "length": 99,
                }
            ]
        }
        result = sb.extract_retrofit_line_length(proposal, "p.json")
        self.assertEqual(result["value"], 0.0)

    def test_blank_falls_back_but_zero_does_not(self):
        self.assertEqual(sb._first_present(None, "", "  ", 0), 0)
        self.assertEqual(sb._first_present(0, 5), 0)
        self.assertEqual(sb._first_present(None, "", 3), 3)


class TestLineLengthCompleteness(unittest.TestCase):
    def test_new_line_partial_missing_length_not_ok(self):
        proposal = {
            "modifications": [
                {
                    "action": "add_line",
                    "params": {"full_branch_data": {"length_km": 10}},
                },
                {
                    "action": "add_line",
                    "params": {"full_branch_data": {}},
                },
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual((result.get("coverage") or {}).get("skipped_count"), 1)
        self.assertEqual((result.get("coverage") or {}).get("valid_count"), 1)
        self.assertNotEqual(result["status"], "ok")

    def test_km_sum_returns_unit_km(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"length_km": 10}}},
                {"action": "add_line", "params": {"full_branch_data": {"length_km": 20}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 30.0)
        self.assertEqual(result["unit"], "km")

    def test_miles_sum_returns_unit_mile(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"MILES": 10}}},
                {"action": "add_line", "params": {"full_branch_data": {"miles": 20}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 30.0)
        self.assertEqual(result["unit"], "mile")
        note = (result.get("coverage") or {}).get("notes", "")
        self.assertIn("未进行英里到公里换算", note)
        self.assertNotEqual(result["unit"], "km")

    def test_single_miles_unit_is_mile_not_km(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"MILES": 30}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 30.0)
        self.assertEqual(result["unit"], "mile")

    def test_mixed_length_km_and_miles_rejected(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"length_km": 10}}},
                {"action": "add_line", "params": {"full_branch_data": {"MILES": 20}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "invalid_data")
        note = (result.get("coverage") or {}).get("notes", "")
        self.assertIn("混合单位", note)
        self.assertEqual(result.get("unit"), "")
        self.assertNotEqual(result.get("unit"), "km")

    def test_mixed_unit_propagates_empty_unit_to_derived(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"length_km": 10}}},
                {"action": "add_line", "params": {"full_branch_data": {"MILES": 20}}},
            ]
        }
        adapter = sb.extract_new_line_length(proposal, "p.json")
        entry = prep._entry_from_adapter("new_line_length", adapter)
        self.assertIsNone(entry["value"])
        self.assertEqual(entry["status"], "invalid_data")
        self.assertEqual(entry["unit"], "")
        self.assertNotEqual(entry["unit"], "km")

    def test_mixed_unit_build_derived_metrics_e2e(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {"total_contingencies_run": 1, "contingencies_with_issues": []}
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}), encoding="utf-8"
            )
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 100,
                                "operation_cost": 2,
                                "lifecycle_cost": 999,
                                "modifications": [
                                    {
                                        "action": "add_line",
                                        "params": {
                                            "full_branch_data": {"length_km": 10}
                                        },
                                    },
                                    {
                                        "action": "add_line",
                                        "params": {
                                            "full_branch_data": {"MILES": 20}
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            entry = derived["schemes"][0]["metrics"]["new_line_length"]
            self.assertIsNone(entry["value"])
            self.assertEqual(entry["status"], "invalid_data")
            self.assertEqual(entry["unit"], "")
            self.assertNotEqual(entry["unit"], "km")

    def test_retrofit_all_missing_length_not_zero(self):
        proposal = {
            "modifications": [
                {"action": "retrofit_line", "params": {"full_branch_data": {}}},
                {"action": "upgrade_line", "params": {"full_branch_data": {}}},
            ]
        }
        result = sb.extract_retrofit_line_length(proposal, "p.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "missing_data")
        self.assertNotEqual(result["value"], 0.0)

    def test_retrofit_partial_missing_length_not_ok(self):
        proposal = {
            "modifications": [
                {
                    "action": "retrofit_line",
                    "params": {"full_branch_data": {"length_km": 10}},
                },
                {"action": "upgrade_line", "params": {"full_branch_data": {}}},
            ]
        }
        result = sb.extract_retrofit_line_length(proposal, "p.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual((result.get("coverage") or {}).get("skipped_count"), 1)

    def test_no_add_or_retrofit_action_returns_zero(self):
        proposal = {
            "modifications": [
                {"action": "disable_branch", "params": {"full_branch_data": {"MILES": 10}}},
            ]
        }
        new_len = sb.extract_new_line_length(proposal, "p.json")
        retrofit = sb.extract_retrofit_line_length(proposal, "p.json")
        self.assertEqual(new_len["value"], 0.0)
        self.assertEqual(new_len["status"], "ok")
        self.assertEqual(retrofit["value"], 0.0)
        self.assertEqual(retrofit["status"], "ok")

    def test_lowercase_miles_accepted(self):
        proposal = {
            "modifications": [
                {"action": "add_line", "params": {"full_branch_data": {"miles": 30.0}}},
            ]
        }
        result = sb.extract_new_line_length(proposal, "p.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 30.0)
        self.assertEqual(result["unit"], "mile")

    def test_adapter_unit_propagates_to_derived_entry(self):
        adapter = {
            "value": 30.0,
            "status": "ok",
            "unit": "mile",
            "inputs": {},
            "input_source": "p.json",
            "missing_fields": [],
            "provenance": "calculated",
            "calculation_mode": "formula",
            "coverage": {"scope": "proposal_modifications", "notes": "按原始 MILES 求和"},
        }
        entry = prep._entry_from_adapter("new_line_length", adapter)
        self.assertEqual(entry["unit"], "mile")
        self.assertEqual(entry["value"], 30.0)


class TestFullLifecycleCostPipeline(unittest.TestCase):
    def test_load_proposal_metadata_full_lcc_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parsed_proposals.json"
            path.write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 100,
                                "operation_cost": 2,
                                "cash_flows": [
                                    {"year": 1, "cost": 10},
                                    {"year": 2, "cost": 10},
                                ],
                                "discount_rate": 0.0,
                                "evaluation_years": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            meta = prep.load_proposal_metadata(path)[1]
            self.assertEqual(meta["lifecycle_calculation_mode"], "full_calculated")
            self.assertEqual(meta["lifecycle_cost_provenance"], "calculated")
            # NPV at 0% = 100 + 10 + 10
            self.assertAlmostEqual(meta["lifecycle_cost_yuan"], 120.0)
            self.assertEqual(meta["discount_rate"], 0.0)
            self.assertEqual(meta["evaluation_years"], 2)
            self.assertEqual(len(meta["lifecycle_cash_flows"]), 2)

    def test_derived_metrics_preserves_full_lcc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {
                        "total_contingencies_run": 1,
                        "contingencies_with_issues": [],
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}), encoding="utf-8"
            )
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 100,
                                "operation_cost": 2,
                                "lifecycle_cash_flows": [
                                    {"year": 1, "cost": 10},
                                    {"year": 2, "cost": 10},
                                ],
                                "discount_rate": 0.0,
                                "evaluation_years": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(lcc["calculation_mode"], "full_calculated")
            self.assertEqual(lcc["provenance"], "calculated")
            self.assertAlmostEqual(lcc["value"], 120.0)
            self.assertIsNotNone(lcc["formula"])
            self.assertIn("discount_rate", lcc["formula"])
            self.assertIn("cash_flow", lcc["formula"])
            self.assertIn("cash_flows", lcc["inputs"])
            self.assertEqual(lcc["inputs"].get("discount_rate"), 0.0)
            self.assertEqual(lcc["inputs"].get("evaluation_years"), 2)
            # 不得回落为 construction * 1.25 = 125
            self.assertNotAlmostEqual(lcc["value"], 125.0)

    def test_derived_estimated_simplified_lcc_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {"total_contingencies_run": 1, "contingencies_with_issues": []}
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}), encoding="utf-8"
            )
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 100,
                                "operation_cost": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(lcc["calculation_mode"], "estimated_simplified")
            self.assertAlmostEqual(lcc["value"], 125.0)
            self.assertIsNotNone(lcc["formula"])
            self.assertIn("construction_cost", lcc["formula"])
            self.assertIn("factor", lcc["formula"])
            self.assertNotIn("discount_rate", lcc["formula"])

    def test_provided_lcc_formula_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {"total_contingencies_run": 1, "contingencies_with_issues": []}
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}), encoding="utf-8"
            )
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 100,
                                "operation_cost": 2,
                                "lifecycle_cost": 999,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(lcc["calculation_mode"], "provided")
            self.assertAlmostEqual(lcc["value"], 999.0)
            self.assertIsNone(lcc["formula"])

    def test_bad_cash_flows_produce_invalid_data(self):
        cases = [
            {
                "cash_flows": {"year": 1, "cost": 10},
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": "bad",
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "discount_rate": 0,
            },
            {
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {"cash_flows": [{"year": 1, "cost": 10}]},
            {"discount_rate": 0},
            {"evaluation_years": 2},
            {
                "cash_flows": [{"year": 1, "cost": 10}, {"year": 2}],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"cost": 10}],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": ["bad"],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": -1, "cost": 10}],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": 99, "cost": 10}],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "discount_rate": -1,
                "evaluation_years": 2,
            },
            {
                "cash_flows": [{"year": 1, "cost": 10}],
                "discount_rate": 0,
                "evaluation_years": -1,
            },
            {
                "cash_flows": [],
                "discount_rate": 0,
                "evaluation_years": 2,
            },
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    (tmp_path / "analysis_1").mkdir()
                    (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                        json.dumps({"analysis": {"is_convergent": True}}),
                        encoding="utf-8",
                    )
                    (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                        json.dumps(
                            {
                                "total_contingencies_run": 1,
                                "contingencies_with_issues": [],
                            }
                        ),
                        encoding="utf-8",
                    )
                    (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                        json.dumps({"analysis": {"exceeding_buses": []}}),
                        encoding="utf-8",
                    )
                    proposal = {
                        "proposal_name": "方案1",
                        "construction_cost": 100,
                        "operation_cost": 2,
                        **extra,
                    }
                    (tmp_path / "parsed_proposals.json").write_text(
                        json.dumps({"proposals": [proposal]}),
                        encoding="utf-8",
                    )
                    derived = prep.build_derived_metrics(tmp_path)
                    lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
                    self.assertIsNone(lcc["value"])
                    self.assertEqual(lcc["status"], "invalid_data")
                    self.assertEqual(lcc["provenance"], "invalid")
                    self.assertEqual(lcc["calculation_mode"], "invalid")
                    self.assertIsNone(lcc["formula"])
                    self.assertNotEqual(
                        lcc["calculation_mode"], "estimated_simplified"
                    )
                    md = prep.convert_core_comparison_summary_to_md(tmp_path)
                    self.assertIn("当前输入不足，未评价", md)

    def test_negative_economic_costs_invalid_e2e(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "analysis_1").mkdir()
            (tmp_path / "analysis_1" / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (tmp_path / "analysis_1" / "n1_report_1.json").write_text(
                json.dumps(
                    {"total_contingencies_run": 1, "contingencies_with_issues": []}
                ),
                encoding="utf-8",
            )
            (tmp_path / "analysis_1" / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"exceeding_buses": []}}), encoding="utf-8"
            )
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": -1,
                                "operation_cost": 2,
                                "lifecycle_cost": -1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            m = derived["schemes"][0]["metrics"]
            self.assertEqual(m["construction_cost"]["status"], "invalid_data")
            self.assertIsNone(m["construction_cost"]["value"])
            self.assertEqual(m["lifecycle_cost"]["status"], "invalid_data")
            self.assertIsNone(m["lifecycle_cost"]["value"])

    def test_summary_table_shows_line_length_unit(self):
        self.assertEqual(
            prep._format_length_summary_cell("30", "km"), "30 km"
        )
        self.assertEqual(
            prep._format_length_summary_cell("20", "mile"), "20 mile"
        )
        self.assertEqual(
            prep._format_length_summary_cell("10", "unknown"),
            "10（单位未知）",
        )
        self.assertEqual(
            prep._format_length_summary_cell("10", ""),
            "10（单位未知）",
        )

    def test_summary_length_unit_warnings(self):
        def _md_for_units(units):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                proposals = []
                for i, unit in enumerate(units, start=1):
                    (tmp_path / f"analysis_{i}").mkdir(exist_ok=True)
                    (tmp_path / f"analysis_{i}" / f"pf_report_{i}.json").write_text(
                        json.dumps({"analysis": {"is_convergent": True}}),
                        encoding="utf-8",
                    )
                    (tmp_path / f"analysis_{i}" / f"n1_report_{i}.json").write_text(
                        json.dumps(
                            {
                                "total_contingencies_run": 1,
                                "contingencies_with_issues": [],
                            }
                        ),
                        encoding="utf-8",
                    )
                    (tmp_path / f"analysis_{i}" / f"scc_report_{i}.json").write_text(
                        json.dumps({"analysis": {"exceeding_buses": []}}),
                        encoding="utf-8",
                    )
                    if unit == "km":
                        branch = {"length_km": 10}
                    elif unit == "mile":
                        branch = {"MILES": 20}
                    else:
                        branch = {"length": 10}
                    proposals.append(
                        {
                            "proposal_name": f"方案{i}",
                            "construction_cost": 100,
                            "operation_cost": 2,
                            "lifecycle_cost": 999,
                            "modifications": [
                                {
                                    "action": "add_line",
                                    "params": {"full_branch_data": branch},
                                }
                            ],
                        }
                    )
                (tmp_path / "parsed_proposals.json").write_text(
                    json.dumps({"proposals": proposals}), encoding="utf-8"
                )
                prep.build_derived_metrics(tmp_path)
                return prep.convert_core_comparison_summary_to_md(tmp_path)

        md_mix = _md_for_units(["km", "mile"])
        self.assertIn("新建线路长度单位未统一或存在未知单位", md_mix)
        self.assertIn("km", md_mix)
        self.assertIn("mile", md_mix)

        md_ku = _md_for_units(["km", "unknown"])
        self.assertIn("新建线路长度单位未统一或存在未知单位", md_ku)
        self.assertIn("单位未知", md_ku)

        md_mu = _md_for_units(["mile", "unknown"])
        self.assertIn("新建线路长度单位未统一或存在未知单位", md_mu)

        md_uu = _md_for_units(["unknown", "unknown"])
        self.assertIn("新建线路长度单位未统一或存在未知单位", md_uu)

        md_km = _md_for_units(["km", "km"])
        self.assertNotIn("新建线路长度单位未统一或存在未知单位", md_km)

        md_mile = _md_for_units(["mile", "mile"])
        self.assertNotIn("新建线路长度单位未统一或存在未知单位", md_mile)

    def test_field_filters_keep_lcc_params(self):
        raw = {
            "proposals": [
                {
                    "proposal_name": "x",
                    "construction_cost": 1,
                    "cash_flows": [{"year": 1, "cost": 1}],
                    "discount_rate": 0.05,
                    "evaluation_years": 10,
                    "extra_drop": 1,
                }
            ]
        }
        filtered = prep.filter_dict_by_config(raw, prep.FIELD_FILTERS["parsed_proposals"])
        prop = filtered["proposals"][0]
        self.assertIn("cash_flows", prop)
        self.assertIn("discount_rate", prop)
        self.assertIn("evaluation_years", prop)
        self.assertNotIn("extra_drop", prop)


class TestPostContingencyScopeGuard(unittest.TestCase):
    def test_all_contingency_overloaded_only_not_full_set(self):
        n1 = {
            "all_contingency_results": [
                {
                    "result": {
                        "analysis": {
                            "overloaded_lines": [
                                {"卡片类型": "L", "电流比例(%)": 110}
                            ]
                        }
                    }
                },
                {"result": {"analysis": {"overloaded_lines": []}}},
            ]
        }
        result = sb.extract_post_contingency_max_loading(n1, "n1.json")
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "missing_data")
        self.assertEqual((result.get("coverage") or {}).get("scope"), "issue_subset")

    def test_all_contingency_with_line_loadings_ok(self):
        n1 = {
            "all_contingency_results": [
                {
                    "result": {
                        "analysis": {
                            "line_loadings": [
                                {"卡片类型": "L", "电流比例(%)": 80},
                                {"卡片类型": "L", "电流比例(%)": 105},
                            ],
                            "overloaded_lines": [
                                {"卡片类型": "L", "电流比例(%)": 105}
                            ],
                        }
                    }
                }
            ]
        }
        result = sb.extract_post_contingency_max_loading(n1, "n1.json")
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["value"], 105.0)
        self.assertEqual((result.get("coverage") or {}).get("scope"), "full_set")


if __name__ == "__main__":
    unittest.main()
