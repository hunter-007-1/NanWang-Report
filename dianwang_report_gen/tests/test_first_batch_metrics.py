# -*- coding: utf-8 -*-
"""第一批比选指标单元测试（含审查反例）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.grid_calculator import calculate_grid_metric, get_economic_defaults

# src.nodes.__init__ 会把同名函数绑定到包属性，遮蔽子模块；用 importlib 取真实模块。
import importlib.util

_prep_path = ROOT / "src" / "nodes" / "data_preprocessing_pcn.py"
_spec = importlib.util.spec_from_file_location("data_preprocessing_pcn_mod", _prep_path)
prep = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(prep)


class TestPfConvergence(unittest.TestCase):
    def test_bool_and_string_and_numeric(self):
        cases = [
            (True, 1.0),
            (False, 0.0),
            ("true", 1.0),
            ("false", 0.0),
            ("TRUE", 1.0),
            ("False", 0.0),
            (1, 1.0),
            (0, 0.0),
            ("是", 1.0),
            ("否", 0.0),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = calculate_grid_metric("pf_convergence", {"is_convergent": raw})
                self.assertEqual(result["value"], expected)
                self.assertTrue(result["constraint"])


class TestN1PassRate(unittest.TestCase):
    def test_zero_total_does_not_divide(self):
        total, issues, pass_rate, *_ = prep.summarize_n1(
            {"total_contingencies_run": 0, "contingencies_with_issues": []}
        )
        self.assertEqual(total, 0)
        self.assertEqual(issues, 0)
        self.assertIsNone(pass_rate)
        self.assertEqual(prep.format_summary_value(pass_rate), "当前输入不足，未评价")

    def test_pass_rate_matches_hand_calc(self):
        total, issues, pass_rate, *_ = prep.summarize_n1(
            {
                "total_contingencies_run": 73,
                "contingencies_with_issues": [{}] * 5,
            }
        )
        self.assertEqual(total, 73)
        self.assertEqual(issues, 5)
        self.assertAlmostEqual(pass_rate, round((73 - 5) / 73 * 100, 2))


class TestWeightedN1(unittest.TestCase):
    def test_weighted_with_loads(self):
        result = calculate_grid_metric(
            "weighted_n1_pass_rate",
            {"passed_load": 90.0, "total_load": 100.0},
        )
        self.assertAlmostEqual(result["value"], 90.0)

    def test_missing_load_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            calculate_grid_metric("weighted_n1_pass_rate", {})
        self.assertIn("数据不足", str(ctx.exception))
        self.assertIn("passed_load", str(ctx.exception))

    def test_summarize_missing_load_is_none(self):
        rate = prep.summarize_weighted_n1_pass_rate(
            {
                "total_contingencies_run": 73,
                "contingencies_with_issues": [
                    {"contingency_branch_uid": "a", "result": {"analysis": {}}}
                ],
            }
        )
        self.assertIsNone(rate)

    def test_direct_weighted_percent(self):
        self.assertAlmostEqual(
            prep.summarize_weighted_n1_pass_rate({"weighted_n1_pass_rate": 97.5}),
            97.5,
        )

    def test_direct_weighted_out_of_range_is_none(self):
        self.assertIsNone(
            prep.summarize_weighted_n1_pass_rate({"weighted_n1_pass_rate": 120})
        )
        self.assertIsNone(
            prep.summarize_weighted_n1_pass_rate({"weighted_n1_pass_rate": -1})
        )

    def test_direct_weighted_ambiguous_decimal_is_none(self):
        # 0.975 不自动换算为 97.5
        self.assertIsNone(
            prep.summarize_weighted_n1_pass_rate({"weighted_n1_pass_rate": 0.975})
        )

    def test_passed_load_total_load(self):
        self.assertAlmostEqual(
            prep.summarize_weighted_n1_pass_rate(
                {"passed_load": 90, "total_load": 100}
            ),
            90.0,
        )

    def test_passed_load_mw_must_not_be_subtracted(self):
        # 禁止 (100-90)/100=10%
        rate = prep.summarize_weighted_n1_pass_rate(
            {
                "total_load": 100,
                "contingencies_with_issues": [{"passed_load_mw": 90}],
            }
        )
        self.assertIsNone(rate)

    def test_lost_load_mode_explicit(self):
        rate = prep.summarize_weighted_n1_pass_rate(
            {
                "weighted_n1_mode": "lost_load",
                "total_load": 100,
                "contingencies_with_issues": [{"lost_load_mw": 10}],
            }
        )
        self.assertAlmostEqual(rate, 90.0)

    def test_mixed_semantics_without_mode_is_none(self):
        rate = prep.summarize_weighted_n1_pass_rate(
            {
                "total_load": 100,
                "contingencies_with_issues": [
                    {"lost_load_mw": 10},
                    {"passed_load_mw": 20},
                ],
            }
        )
        self.assertIsNone(rate)


class TestShortCircuitUniqueNodes(unittest.TestCase):
    def test_same_bus_name_counts_one(self):
        count = prep.count_unique_scc_over_limit_nodes(
            [
                {"bus_name": "A", "short_circuit_current_kA": 70, "breaker_current_kA": 63},
                {"bus_name": "A", "short_circuit_current_kA": 80, "breaker_current_kA": 63},
            ]
        )
        self.assertEqual(count, 1)

    def test_different_bus_name_counts_two(self):
        count = prep.count_unique_scc_over_limit_nodes(
            [{"bus_name": "A"}, {"bus_name": "B"}]
        )
        self.assertEqual(count, 2)

    def test_empty_bus_name_uses_node_id(self):
        count = prep.count_unique_scc_over_limit_nodes(
            [{"bus_name": "", "node_id": "1"}, {"bus_name": "", "node_id": "2"}]
        )
        self.assertEqual(count, 2)

    def test_missing_all_ids_not_merged(self):
        count = prep.count_unique_scc_over_limit_nodes(
            [
                {"short_circuit_current_kA": 70, "breaker_current_kA": 63},
                {"short_circuit_current_kA": 80, "breaker_current_kA": 63},
            ]
        )
        self.assertEqual(count, 2)

    def test_duplicate_node_keeps_worst_margin(self):
        scc_count, _, min_margin, *_ = prep.summarize_scc(
            {
                "analysis": {
                    "total_buses": 100,
                    "contingencies_with_issues": [
                        {
                            "bus_name": "A",
                            "short_circuit_current_kA": 50.0,
                            "breaker_current_kA": 63.0,
                        },
                        {
                            "bus_name": "A",
                            "short_circuit_current_kA": 150.783,
                            "breaker_current_kA": 63.0,
                        },
                    ],
                }
            }
        )
        self.assertEqual(scc_count, 1)
        expected = (63.0 - 150.783) / 63.0 * 100
        self.assertAlmostEqual(min_margin, round(expected, 2))


class TestShortCircuitRatio(unittest.TestCase):
    def test_ratio_uses_unique_nodes_and_total_buses(self):
        scc_count, ratio, min_margin, *_ = prep.summarize_scc(
            {
                "analysis": {
                    "total_buses": 464,
                    "contingencies_with_issues": [
                        {
                            "bus_name": "A",
                            "short_circuit_current_kA": 70.0,
                            "breaker_current_kA": 63.0,
                        }
                    ]
                    * 13,
                }
            }
        )
        self.assertEqual(scc_count, 1)
        self.assertAlmostEqual(ratio, round(1 / 464 * 100, 2))
        self.assertIsNotNone(min_margin)

    def test_missing_denominator_keeps_count_only(self):
        scc_count, ratio, *_ = prep.summarize_scc(
            {
                "analysis": {
                    "contingencies_with_issues": [
                        {
                            "bus_name": "A",
                            "short_circuit_current_kA": 70.0,
                            "breaker_current_kA": 63.0,
                        }
                    ]
                }
            }
        )
        self.assertEqual(scc_count, 1)
        self.assertIsNone(ratio)
        self.assertEqual(prep.format_summary_value(ratio), "当前输入不足，未评价")

    def test_denominator_field_priority(self):
        analysis = {
            "effective_check_count": 200,
            "check_count": 300,
            "total_buses": 464,
        }
        self.assertEqual(prep.get_scc_effective_check_count(analysis), 200.0)
        self.assertEqual(
            prep.get_scc_effective_check_count({"check_count": 300, "total_buses": 464}),
            300.0,
        )
        self.assertEqual(
            prep.get_scc_effective_check_count({"total_buses": 464}),
            464.0,
        )

    def test_each_denominator_field_works(self):
        for key in ("effective_check_count", "check_count", "total_buses"):
            with self.subTest(key=key):
                _, ratio, *_ = prep.summarize_scc(
                    {
                        "analysis": {
                            key: 50,
                            "contingencies_with_issues": [
                                {
                                    "bus_name": "A",
                                    "short_circuit_current_kA": 70,
                                    "breaker_current_kA": 63,
                                }
                            ],
                        }
                    }
                )
                self.assertAlmostEqual(ratio, 2.0)

    def test_invalid_denominators_return_none(self):
        for bad in (0, -1, "abc", True, False):
            with self.subTest(bad=bad):
                self.assertIsNone(
                    prep.get_scc_effective_check_count({"total_buses": bad})
                )

    def test_denominator_smaller_than_nodes_no_ratio(self):
        scc_count, ratio, *_ = prep.summarize_scc(
            {
                "analysis": {
                    "total_buses": 1,
                    "contingencies_with_issues": [
                        {"bus_name": "A"},
                        {"bus_name": "B"},
                    ],
                }
            }
        )
        self.assertEqual(scc_count, 2)
        self.assertIsNone(ratio)

    def test_field_filter_keeps_check_count_aliases(self):
        filtered = prep.filter_dict_by_config(
            {
                "analysis": {
                    "total_buses": 464,
                    "check_count": 400,
                    "effective_check_count": 390,
                    "contingencies_with_issues": [],
                }
            },
            prep.FIELD_FILTERS["scc_report"],
        )
        analysis = filtered["analysis"]
        self.assertEqual(analysis.get("total_buses"), 464)
        self.assertEqual(analysis.get("check_count"), 400)
        self.assertEqual(analysis.get("effective_check_count"), 390)


class TestMinBreakerMargin(unittest.TestCase):
    def test_pairwise_min_and_negative(self):
        result = calculate_grid_metric(
            "min_breaker_interrupt_margin_rate",
            {
                "records": [
                    {
                        "short_circuit_current_kA": 50.0,
                        "breaker_current_kA": 63.0,
                    },
                    {
                        "short_circuit_current_kA": 150.783,
                        "breaker_current_kA": 63.0,
                    },
                ]
            },
        )
        expected = (63.0 - 150.783) / 63.0 * 100
        self.assertAlmostEqual(result["value"], expected, places=4)
        self.assertLess(result["value"], 0)
        self.assertTrue(result["constraint"])

    def test_missing_records_raise_not_zero(self):
        with self.assertRaises(ValueError) as ctx:
            calculate_grid_metric(
                "min_breaker_interrupt_margin_rate",
                {"records": [{"short_circuit_current_kA": 10.0}]},
            )
        self.assertIn("数据不足", str(ctx.exception))


class TestEconomicFields(unittest.TestCase):
    def test_annual_and_lcc_not_mixed(self):
        construction = 240000000.0
        operation = 4800000.0
        annual = calculate_grid_metric(
            "annual_cost",
            {"construction_cost": construction, "operation_cost": operation},
        )
        lcc = calculate_grid_metric(
            "lifecycle_cost",
            {"construction_cost": construction},
        )
        self.assertAlmostEqual(annual["value"], 27454302.17838136, places=2)
        self.assertAlmostEqual(lcc["value"], 300000000.0)
        self.assertNotAlmostEqual(annual["value"], lcc["value"])
        self.assertEqual(annual["label"], "年费用")
        self.assertIn("全寿命", lcc["label"])

    def test_real_lcc_preserved_without_annual(self):
        from main_api import _economic_fields_from_proposal

        economics = _economic_fields_from_proposal(
            {
                "construction_cost": "100",
                "operation_cost": "2",
                "lifecycle_cost": "999",
            }
        )
        self.assertEqual(economics["lifecycle_cost"], "999")
        self.assertNotEqual(economics["annual_cost"], "")
        self.assertNotEqual(economics["annual_cost"], "999")

    def test_annual_preserved_lcc_filled(self):
        from main_api import _economic_fields_from_proposal

        economics = _economic_fields_from_proposal(
            {
                "construction_cost": "240000000",
                "operation_cost": "4800000",
                "annual_cost": "111",
            }
        )
        self.assertEqual(economics["annual_cost"], "111")
        self.assertAlmostEqual(float(economics["lifecycle_cost"]), 300000000.0, places=1)

    def test_both_preserved(self):
        from main_api import _economic_fields_from_proposal

        economics = _economic_fields_from_proposal(
            {
                "construction_cost": "240000000",
                "operation_cost": "4800000",
                "annual_cost": "111",
                "lifecycle_cost": "999",
            }
        )
        self.assertEqual(economics["annual_cost"], "111")
        self.assertEqual(economics["lifecycle_cost"], "999")

    def test_both_missing_filled_from_formula(self):
        from main_api import _economic_fields_from_proposal

        economics = _economic_fields_from_proposal(
            {
                "construction_cost": "240000000",
                "operation_cost": "4800000",
            }
        )
        self.assertAlmostEqual(float(economics["annual_cost"]), 27454302.18, places=1)
        self.assertAlmostEqual(float(economics["lifecycle_cost"]), 300000000.0, places=1)

    def test_load_proposal_metadata_preserves_real_lcc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parsed_proposals.json"
            path.write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": "100",
                                "operation_cost": "2",
                                "lifecycle_cost": "999",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            meta = prep.load_proposal_metadata(path)
            self.assertEqual(meta[1]["lifecycle_cost_yuan"], 999.0)
            self.assertIsNotNone(meta[1]["annual_cost_yuan"])
            self.assertNotEqual(meta[1]["annual_cost_yuan"], 999.0)

    def test_economic_defaults_from_yaml(self):
        eco = get_economic_defaults()
        self.assertAlmostEqual(eco["interest_rate"], 0.07)
        self.assertAlmostEqual(eco["years"], 20)
        self.assertAlmostEqual(eco["lifecycle_factor"], 1.25)


class TestCoreSummaryTable(unittest.TestCase):
    def _copy_hist_with_migrated_economics(self, hist: Path, tmp_path: Path, inject_buses=False):
        from main_api import _migrate_legacy_run_economics

        proposals = json.loads((hist / "parsed_proposals.json").read_text(encoding="utf-8"))
        for proposal in proposals.get("proposals") or []:
            _migrate_legacy_run_economics(proposal, run_label="hist_test")
        (tmp_path / "parsed_proposals.json").write_text(
            json.dumps(proposals, ensure_ascii=False), encoding="utf-8"
        )
        for i in range(1, 6):
            src = hist / f"analysis_{i}"
            dst = tmp_path / f"analysis_{i}"
            dst.mkdir()
            for name in (f"pf_report_{i}.json", f"n1_report_{i}.json"):
                (dst / name).write_text(
                    (src / name).read_text(encoding="utf-8"), encoding="utf-8"
                )
            scc = json.loads((src / f"scc_report_{i}.json").read_text(encoding="utf-8"))
            if inject_buses:
                scc.setdefault("analysis", {})["total_buses"] = 464
            (dst / f"scc_report_{i}.json").write_text(
                json.dumps(scc, ensure_ascii=False), encoding="utf-8"
            )

    def test_historical_case_without_denominator(self):
        hist = (
            ROOT
            / "outputs"
            / "2026-08-04_11-33-55_compare_pcn"
            / "working_dir"
        )
        if not hist.exists():
            self.skipTest("历史案例目录不存在")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._copy_hist_with_migrated_economics(hist, tmp_path, inject_buses=False)
            md = prep.convert_core_comparison_summary_to_md(tmp_path)

        self.assertIn("方案比选安全硬约束汇总表", md)
        self.assertIn("方案比选经济性汇总表", md)
        self.assertIn("方案比选技术性能与工程实施性汇总表", md)
        self.assertIn("| 12 | 当前输入不足，未评价 |", md)
        self.assertIn("93.15", md)
        self.assertIn("-139.34", md)
        self.assertIn("当前输入不足，未评价", md)
        self.assertIn("建设投资(元)", md)
        self.assertIn("年费用(元/年)", md)
        self.assertIn("全寿命周期成本LCC(元)", md)
        econ_row = next(
            line
            for line in md.splitlines()
            if line.startswith("| 方案1 |") and "240000000" in line.replace(",", "")
        )
        parts = [p.strip() for p in econ_row.strip("|").split("|")]
        self.assertEqual(parts[0], "方案1")
        # 建设投资/运维/年费用/LCC 以元展示，与 claim 一致
        self.assertEqual(parts[1].replace(",", ""), "240000000")
        self.assertEqual(parts[2].replace(",", ""), "4800000")
        annual = parts[3].replace(",", "")
        self.assertTrue(annual.startswith("274543"))
        self.assertEqual(parts[4].replace(",", "").rstrip("0").rstrip(".") or parts[4], "300000000".rstrip("0").rstrip(".") or "300000000")
        # LCC 与年费用不得相同
        self.assertNotEqual(parts[3], parts[4])
        safety_header = next(
            line for line in md.splitlines() if line.startswith("| 方案 | 基态潮流收敛性")
        )
        self.assertGreaterEqual(safety_header.count("|") - 1, 9)

    def test_historical_case_with_denominator_unique_nodes(self):
        hist = (
            ROOT
            / "outputs"
            / "2026-08-04_11-33-55_compare_pcn"
            / "working_dir"
        )
        if not hist.exists():
            self.skipTest("历史案例目录不存在")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._copy_hist_with_migrated_economics(hist, tmp_path, inject_buses=True)
            md = prep.convert_core_comparison_summary_to_md(tmp_path)

        self.assertIn("93.15", md)
        self.assertIn("| 12 |", md)
        self.assertIn(str(round(12 / 464 * 100, 2)), md)
        self.assertIn("-139.34", md)


class TestLegacyEconomicsMigration(unittest.TestCase):
    def test_legacy_miswritten_lifecycle_migrates(self):
        from main_api import _migrate_legacy_run_economics

        proposal = {
            "construction_cost": "240000000",
            "operation_cost": "4800000",
            "lifecycle_cost": "27454302.18",
        }
        self.assertTrue(_migrate_legacy_run_economics(proposal, run_label="run_legacy"))
        self.assertAlmostEqual(float(proposal["annual_cost"]), 27454302.18, places=1)
        self.assertAlmostEqual(float(proposal["lifecycle_cost"]), 300000000.0, places=1)
        self.assertEqual(proposal["_economic_provenance"]["annual_cost"], "migrated")
        self.assertEqual(
            proposal["_economic_provenance"]["annual_cost_source_field"],
            "legacy.lifecycle_cost",
        )
        self.assertEqual(proposal["_economic_provenance"]["lifecycle_cost"], "calculated")

    def test_real_lcc_not_migrated(self):
        from main_api import _migrate_legacy_run_economics, _economic_fields_from_proposal

        proposal = {
            "construction_cost": "100",
            "operation_cost": "2",
            "lifecycle_cost": "999",
        }
        self.assertFalse(_migrate_legacy_run_economics(proposal, run_label="run_real"))
        filled = _economic_fields_from_proposal(proposal)
        self.assertEqual(filled["lifecycle_cost"], "999")
        self.assertNotEqual(filled["annual_cost"], "")

    def test_both_present_not_migrated(self):
        from main_api import _migrate_legacy_run_economics

        proposal = {
            "construction_cost": "240000000",
            "operation_cost": "4800000",
            "annual_cost": "111",
            "lifecycle_cost": "999",
        }
        self.assertFalse(_migrate_legacy_run_economics(proposal, run_label="run_both"))
        self.assertEqual(proposal["annual_cost"], "111")
        self.assertEqual(proposal["lifecycle_cost"], "999")

    def test_unparsable_not_migrated(self):
        from main_api import _migrate_legacy_run_economics

        proposal = {
            "construction_cost": "abc",
            "operation_cost": "def",
            "lifecycle_cost": "xyz",
        }
        self.assertFalse(_migrate_legacy_run_economics(proposal, run_label="run_bad"))


class TestFilterPreservesFields(unittest.TestCase):
    def test_scc_node_id_survives_filter_and_dedupes(self):
        raw = {
            "analysis": {
                "total_buses": 10,
                "contingencies_with_issues": [
                    {
                        "node_id": "N1",
                        "short_circuit_current_kA": 70,
                        "breaker_current_kA": 63,
                    },
                    {
                        "node_id": "N1",
                        "short_circuit_current_kA": 80,
                        "breaker_current_kA": 63,
                    },
                ],
            }
        }
        filtered = prep.filter_dict_by_config(raw, prep.FIELD_FILTERS["scc_report"])
        issues = filtered["analysis"]["contingencies_with_issues"]
        self.assertEqual(issues[0].get("node_id"), "N1")
        scc_count, *_ = prep.summarize_scc(filtered)
        self.assertEqual(scc_count, 1)

    def test_weighted_n1_mode_survives_filter(self):
        raw = {
            "weighted_n1_mode": "lost_load",
            "total_load": 100,
            "total_contingencies_run": 1,
            "contingencies_with_issues": [{"lost_load_mw": 10}],
        }
        filtered = prep.filter_dict_by_config(raw, prep.FIELD_FILTERS["n1_report"])
        self.assertEqual(filtered.get("weighted_n1_mode"), "lost_load")
        rate = prep.summarize_weighted_n1_pass_rate(filtered)
        self.assertAlmostEqual(rate, 90.0)


class TestWeightedN1CalculatorValidation(unittest.TestCase):
    def test_direct_bounds(self):
        self.assertAlmostEqual(
            calculate_grid_metric("weighted_n1_pass_rate", {"direct_value": 0})["value"],
            0.0,
        )
        self.assertAlmostEqual(
            calculate_grid_metric("weighted_n1_pass_rate", {"direct_value": 100})["value"],
            100.0,
        )
        with self.assertRaises(ValueError):
            calculate_grid_metric("weighted_n1_pass_rate", {"direct_value": 120})
        with self.assertRaises(ValueError):
            calculate_grid_metric("weighted_n1_pass_rate", {"direct_value": -1})

    def test_passed_total_bounds(self):
        self.assertAlmostEqual(
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": 0, "total_load": 100}
            )["value"],
            0.0,
        )
        self.assertAlmostEqual(
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": 100, "total_load": 100}
            )["value"],
            100.0,
        )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": 110, "total_load": 100}
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": -1, "total_load": 100}
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": 0, "total_load": 0}
            )
        with self.assertRaises(ValueError):
            calculate_grid_metric(
                "weighted_n1_pass_rate", {"passed_load": True, "total_load": 100}
            )


class TestCapitalRecoveryFactor(unittest.TestCase):
    def test_zero_interest_rate(self):
        from src.tools.grid_calculator import calculate_capital_recovery_factor

        self.assertAlmostEqual(calculate_capital_recovery_factor(0, 20), 0.05)
        result = calculate_grid_metric(
            "annual_cost",
            {
                "construction_cost": 100,
                "operation_cost": 2,
                "interest_rate": 0,
                "years": 20,
            },
        )
        self.assertAlmostEqual(result["value"], 7.0)

    def test_invalid_rate_years(self):
        from src.tools.grid_calculator import calculate_capital_recovery_factor

        with self.assertRaises(ValueError):
            calculate_capital_recovery_factor(-0.01, 20)
        with self.assertRaises(ValueError):
            calculate_capital_recovery_factor(0.07, 0)
        with self.assertRaises(ValueError):
            calculate_capital_recovery_factor(0.07, -1)
        with self.assertRaises(ValueError):
            calculate_capital_recovery_factor(True, 20)


class TestDerivedMetricsAndClaims(unittest.TestCase):
    def test_derived_metrics_and_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": "240000000",
                                "operation_cost": "4800000",
                                "annual_cost": "27454302.18",
                                "lifecycle_cost": "300000000",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            analysis = tmp_path / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (analysis / "n1_report_1.json").write_text(
                json.dumps(
                    {
                        "total_contingencies_run": 73,
                        "contingencies_with_issues": [{}] * 5,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (analysis / "scc_report_1.json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "total_buses": 100,
                            "contingencies_with_issues": [
                                {
                                    "bus_name": "A",
                                    "short_circuit_current_kA": 150.783,
                                    "breaker_current_kA": 63.0,
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            derived = prep.build_derived_metrics(tmp_path)
            scheme = derived["schemes"][0]
            metrics = scheme["metrics"]
            self.assertEqual(metrics["pf_convergence"]["value"], 1.0)
            self.assertEqual(metrics["pf_convergence"]["display_value"], "是")
            self.assertAlmostEqual(metrics["n1_pass_rate"]["value"], 93.15)
            self.assertEqual(metrics["weighted_n1_pass_rate"]["value"], None)
            self.assertEqual(metrics["weighted_n1_pass_rate"]["status"], "missing_data")
            self.assertEqual(metrics["short_circuit_over_limit_count"]["value"], 1)
            self.assertIsNotNone(metrics["min_breaker_interrupt_margin_rate"]["value"])

            claims = []
            counter = [0]
            prep.extract_derived_metric_claims(
                derived, "derived_metrics.json", claims, counter
            )
            indicators = {c.indicator for c in claims}
            self.assertIn("pf_convergence", indicators)
            self.assertIn("n1_pass_rate", indicators)
            self.assertIn("short_circuit_over_limit_count", indicators)
            self.assertIn("min_breaker_interrupt_margin_rate", indicators)
            self.assertNotIn("weighted_n1_pass_rate", indicators)
            self.assertNotIn("value", indicators)
            pf_claim = next(c for c in claims if c.indicator == "pf_convergence")
            self.assertEqual(pf_claim.metadata.get("original_type"), "derived")
            self.assertEqual(pf_claim.metadata.get("proposal_index"), 1)
            self.assertIn("formula", pf_claim.metadata)
            self.assertEqual(metrics["annual_cost"]["provenance"], "provided")
            self.assertIsNone(metrics["annual_cost"]["formula"])
            self.assertEqual(metrics["lifecycle_cost"]["provenance"], "provided")
            self.assertIsNone(metrics["lifecycle_cost"]["formula"])


class TestN1MissingVsEmptyIssues(unittest.TestCase):
    def test_issues_field_missing_is_not_100_percent(self):
        total, issues, pass_rate, *_ = prep.summarize_n1(
            {"total_contingencies_run": 73}
        )
        self.assertEqual(total, 73)
        self.assertIsNone(issues)
        self.assertIsNone(pass_rate)
        self.assertEqual(prep.format_summary_value(pass_rate), "当前输入不足，未评价")

    def test_explicit_empty_issues_is_100_percent(self):
        total, issues, pass_rate, *_ = prep.summarize_n1(
            {"total_contingencies_run": 73, "contingencies_with_issues": []}
        )
        self.assertEqual(total, 73)
        self.assertEqual(issues, 0)
        self.assertAlmostEqual(pass_rate, 100.0)

    def test_issues_null_is_missing(self):
        _, issues, pass_rate, *_ = prep.summarize_n1(
            {"total_contingencies_run": 73, "contingencies_with_issues": None}
        )
        self.assertIsNone(issues)
        self.assertIsNone(pass_rate)

    def test_issues_dict_is_missing(self):
        _, issues, pass_rate, *_ = prep.summarize_n1(
            {"total_contingencies_run": 73, "contingencies_with_issues": {}}
        )
        self.assertIsNone(issues)
        self.assertIsNone(pass_rate)

    def test_issues_greater_than_total(self):
        total, issues, pass_rate, *_ = prep.summarize_n1(
            {
                "total_contingencies_run": 2,
                "contingencies_with_issues": [{}, {}, {}],
            }
        )
        self.assertEqual(total, 2)
        self.assertEqual(issues, 3)
        self.assertIsNone(pass_rate)
        self.assertEqual(prep.format_summary_value(pass_rate), "当前输入不足，未评价")

    def test_derived_and_markdown_follow_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps({"proposals": [{"proposal_name": "方案1"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            analysis = tmp_path / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text(
                json.dumps({"total_contingencies_run": 73}, ensure_ascii=False),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            n1 = derived["schemes"][0]["metrics"]["n1_pass_rate"]
            self.assertIsNone(n1["value"])
            self.assertEqual(n1["status"], "missing_data")
            self.assertIn("contingencies_with_issues", n1["missing_fields"])
            issues_m = derived["schemes"][0]["metrics"]["n1_issue_contingencies"]
            self.assertIsNone(issues_m["value"])
            self.assertEqual(issues_m["status"], "missing_data")
            md = prep.convert_core_comparison_summary_to_md(tmp_path)
            self.assertIn("当前输入不足，未评价", md)
            self.assertNotIn("100%", md.split("N-1")[1] if "N-1" in md else md)

            (analysis / "n1_report_1.json").write_text(
                json.dumps(
                    {"total_contingencies_run": 73, "contingencies_with_issues": []},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (tmp_path / "derived_metrics.json").unlink(missing_ok=True)
            derived2 = prep.build_derived_metrics(tmp_path)
            self.assertEqual(derived2["schemes"][0]["metrics"]["n1_issue_contingencies"]["value"], 0)
            self.assertEqual(derived2["schemes"][0]["metrics"]["n1_issue_contingencies"]["status"], "ok")
            self.assertAlmostEqual(derived2["schemes"][0]["metrics"]["n1_pass_rate"]["value"], 100.0)


class TestSccMissingVsEmptyIssues(unittest.TestCase):
    def test_exceeding_buses_missing(self):
        scc_count, ratio, min_margin, *_ = prep.summarize_scc(
            {"analysis": {"total_buses": 100}}
        )
        self.assertIsNone(scc_count)
        self.assertIsNone(ratio)
        self.assertIsNone(min_margin)
        self.assertEqual(prep.format_summary_value(scc_count), "当前输入不足，未评价")

    def test_exceeding_buses_empty_list(self):
        scc_count, ratio, min_margin, *_ = prep.summarize_scc(
            {"analysis": {"total_buses": 100, "exceeding_buses": []}}
        )
        self.assertEqual(scc_count, 0)
        self.assertAlmostEqual(ratio, 0.0)
        self.assertIsNone(min_margin)

    def test_exceeding_buses_null(self):
        scc_count, ratio, *_ = prep.summarize_scc(
            {"analysis": {"exceeding_buses": None}}
        )
        self.assertIsNone(scc_count)
        self.assertIsNone(ratio)

    def test_exceeding_buses_dict(self):
        scc_count, ratio, *_ = prep.summarize_scc(
            {"analysis": {"exceeding_buses": {}}}
        )
        self.assertIsNone(scc_count)
        self.assertIsNone(ratio)

    def test_empty_exceeding_does_not_fallback(self):
        """exceeding_buses=[] 优先，即使 contingencies_with_issues 有记录。"""
        info = prep.get_scc_issue_records(
            {
                "exceeding_buses": [],
                "contingencies_with_issues": [{"bus_name": "A"}],
            }
        )
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["source_field"], "exceeding_buses")
        self.assertEqual(info["records"], [])
        scc_count, ratio, min_margin, *_ = prep.summarize_scc(
            {
                "analysis": {
                    "total_buses": 100,
                    "exceeding_buses": [],
                    "contingencies_with_issues": [
                        {
                            "bus_name": "A",
                            "short_circuit_current_kA": 70,
                            "breaker_current_kA": 63,
                        }
                    ],
                }
            }
        )
        self.assertEqual(scc_count, 0)
        self.assertAlmostEqual(ratio, 0.0)
        self.assertIsNone(min_margin)

    def test_derived_missing_not_shown_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps({"proposals": [{"proposal_name": "方案1"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            analysis = tmp_path / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text(
                json.dumps({"analysis": {"total_buses": 100}}, ensure_ascii=False),
                encoding="utf-8",
            )
            derived = prep.build_derived_metrics(tmp_path)
            count_m = derived["schemes"][0]["metrics"]["short_circuit_over_limit_count"]
            ratio_m = derived["schemes"][0]["metrics"]["short_circuit_over_limit_ratio"]
            self.assertIsNone(count_m["value"])
            self.assertIsNone(ratio_m["value"])
            self.assertEqual(count_m["status"], "missing_data")
            self.assertIn("analysis.exceeding_buses", count_m["missing_fields"])
            md = prep.convert_core_comparison_summary_to_md(tmp_path)
            # 缺字段不得显示为越限节点数 0
            self.assertIn("当前输入不足，未评价", md)


class TestEconomicProvenance(unittest.TestCase):
    def test_provided_lcc(self):
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
                                "lifecycle_cost": 999,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            meta = prep.load_proposal_metadata(path)[1]
            self.assertEqual(meta["lifecycle_cost_yuan"], 999)
            self.assertEqual(meta["lifecycle_cost_provenance"], "provided")
            analysis = Path(tmp) / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(Path(tmp))
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(lcc["value"], 999)
            self.assertEqual(lcc["provenance"], "provided")
            self.assertIsNone(lcc["formula"])
            self.assertEqual(lcc["inputs"].get("lifecycle_cost"), 999)

    def test_calculated_lcc(self):
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
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            analysis = Path(tmp) / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(Path(tmp))
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(lcc["value"], 125)
            self.assertEqual(lcc["provenance"], "calculated")
            self.assertIsNotNone(lcc["formula"])
            self.assertEqual(lcc["inputs"].get("factor"), 1.25)

    def test_provided_annual(self):
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
                                "annual_cost": 11,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            analysis = Path(tmp) / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(Path(tmp))
            annual = derived["schemes"][0]["metrics"]["annual_cost"]
            self.assertEqual(annual["value"], 11)
            self.assertEqual(annual["provenance"], "provided")
            self.assertIsNone(annual["formula"])

    def test_calculated_annual(self):
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
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            analysis = Path(tmp) / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(Path(tmp))
            annual = derived["schemes"][0]["metrics"]["annual_cost"]
            self.assertEqual(annual["provenance"], "calculated")
            self.assertIsNotNone(annual["formula"])
            self.assertIn("interest_rate", annual["inputs"])
            self.assertIn("years", annual["inputs"])

    def test_migrated_provenance(self):
        from main_api import _migrate_legacy_run_economics

        with tempfile.TemporaryDirectory() as tmp:
            proposal = {
                "proposal_name": "方案1",
                "construction_cost": "240000000",
                "operation_cost": "4800000",
                "lifecycle_cost": "27454302.18",
            }
            self.assertTrue(_migrate_legacy_run_economics(proposal))
            path = Path(tmp) / "parsed_proposals.json"
            path.write_text(json.dumps({"proposals": [proposal]}), encoding="utf-8")
            analysis = Path(tmp) / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(Path(tmp))
            annual = derived["schemes"][0]["metrics"]["annual_cost"]
            lcc = derived["schemes"][0]["metrics"]["lifecycle_cost"]
            self.assertEqual(annual["provenance"], "migrated")
            self.assertEqual(annual["source_field"], "legacy.lifecycle_cost")
            self.assertIsNone(annual["formula"])
            self.assertEqual(lcc["provenance"], "calculated")
            self.assertIsNotNone(lcc["formula"])


class TestFiniteFloatValidation(unittest.TestCase):
    def test_nan_inf_rejected(self):
        cases = [
            ("weighted_n1_pass_rate", {"weighted_n1_pass_rate": "nan"}),
            ("weighted_n1_pass_rate", {"passed_load": "inf", "total_load": 100}),
            ("annual_cost", {"construction_cost": 100, "operation_cost": 2, "interest_rate": "nan"}),
            ("lifecycle_cost", {"construction_cost": "inf"}),
        ]
        for metric, inputs in cases:
            with self.subTest(metric=metric, inputs=inputs):
                with self.assertRaises(ValueError) as ctx:
                    calculate_grid_metric(metric, inputs)
                self.assertIn("finite", str(ctx.exception))


class TestClaimMetadataSqliteRoundTrip(unittest.TestCase):
    def test_derived_claims_metadata_survives_sqlite(self):
        from src.pcn_database import PCNDatabase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": "240000000",
                                "operation_cost": "4800000",
                                "annual_cost": "27454302.18",
                                "lifecycle_cost": "300000000",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            analysis = tmp_path / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text(
                json.dumps({"analysis": {"is_convergent": True}}), encoding="utf-8"
            )
            (analysis / "n1_report_1.json").write_text(
                json.dumps(
                    {
                        "total_contingencies_run": 73,
                        "contingencies_with_issues": [{}] * 5,
                    }
                ),
                encoding="utf-8",
            )
            (analysis / "scc_report_1.json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "total_buses": 100,
                            "exceeding_buses": [
                                {
                                    "bus_name": "A",
                                    "short_circuit_current_kA": 150.783,
                                    "breaker_current_kA": 63.0,
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            derived = prep.build_derived_metrics(tmp_path)
            claims = []
            counter = [0]
            prep.extract_derived_metric_claims(
                derived, "derived_metrics.json", claims, counter
            )
            self.assertNotIn(
                "weighted_n1_pass_rate",
                {c.indicator for c in claims},
            )

            db_path = tmp_path / "pcn_claims.db"
            with PCNDatabase(str(db_path)) as db:
                db.init_schema()
                db.insert_claims_batch(claims)

            with PCNDatabase(str(db_path)) as db:
                for indicator in (
                    "n1_pass_rate",
                    "pf_convergence",
                    "short_circuit_over_limit_count",
                    "min_breaker_interrupt_margin_rate",
                ):
                    rows = db.search_claims_by_indicator(indicator, k=5)
                    self.assertTrue(rows, msg=indicator)
                    meta = rows[0]["metadata"]
                    self.assertEqual(meta.get("original_type"), "derived")
                    self.assertEqual(meta.get("proposal_name"), "方案1")
                    self.assertIn("formula", meta)
                    self.assertIn("inputs", meta)
                    self.assertIn("input_source", meta)

                annual_rows = db.search_claims_by_indicator("annual_cost", k=5)
                self.assertTrue(annual_rows)
                self.assertEqual(annual_rows[0]["metadata"].get("provenance"), "provided")

    def test_old_database_metadata_json_migration(self):
        import sqlite3

        from src.pcn_database import PCNDatabase

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                """
                CREATE TABLE pcn_claims (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT UNIQUE NOT NULL,
                    indicator TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    entity TEXT,
                    time TEXT,
                    policy TEXT,
                    source_path TEXT NOT NULL,
                    path_to_value TEXT NOT NULL,
                    original_type TEXT NOT NULL,
                    context TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO pcn_claims
                (claim_id, indicator, value, unit, entity, time, policy,
                 source_path, path_to_value, original_type, context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "000001",
                    "legacy_metric",
                    1.0,
                    None,
                    None,
                    None,
                    None,
                    "a.json",
                    "path",
                    "float",
                    "ctx",
                ),
            )
            conn.commit()
            conn.close()

            with PCNDatabase(str(db_path)) as db:
                db.init_schema()
                db.init_schema()  # 幂等
                cursor = db.conn.cursor()
                cursor.execute("PRAGMA table_info(pcn_claims)")
                columns = {row[1] for row in cursor.fetchall()}
                self.assertIn("metadata_json", columns)
                rows = db.search_claims_by_indicator("legacy_metric", k=5)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["value"], 1.0)
                meta = rows[0]["metadata"]
                self.assertEqual(meta.get("source_path"), "a.json")
                self.assertEqual(meta.get("original_type"), "float")


class TestNonFiniteMetricValues(unittest.TestCase):
    def test_parse_weighted_rejects_nan_inf(self):
        self.assertIsNone(prep.parse_weighted_n1_direct_percent(float("nan")))
        self.assertIsNone(prep.parse_weighted_n1_direct_percent(float("inf")))
        self.assertIsNone(prep.parse_weighted_n1_direct_percent(float("-inf")))

    def test_parse_weighted_keeps_valid_bounds(self):
        self.assertEqual(prep.parse_weighted_n1_direct_percent(0), 0.0)
        self.assertEqual(prep.parse_weighted_n1_direct_percent(50), 50.0)
        self.assertEqual(prep.parse_weighted_n1_direct_percent(100), 100.0)

    def test_scc_denominator_rejects_nan_inf(self):
        self.assertIsNone(
            prep.get_scc_effective_check_count({"total_buses": float("nan")})
        )
        self.assertIsNone(
            prep.get_scc_effective_check_count({"total_buses": float("inf")})
        )
        self.assertIsNone(
            prep.get_scc_effective_check_count({"check_count": float("-inf")})
        )
        self.assertEqual(
            prep.get_scc_effective_check_count({"total_buses": 50}),
            50.0,
        )

    def test_derived_claims_skip_nan_inf(self):
        claims = []
        counter = [0]
        prep.extract_derived_metric_claims(
            {
                "schemes": [
                    {
                        "proposal_index": 1,
                        "proposal_name": "方案1",
                        "metrics": {
                            "n1_pass_rate": {
                                "value": float("nan"),
                                "unit": "%",
                                "status": "ok",
                            },
                            "short_circuit_over_limit_ratio": {
                                "value": float("inf"),
                                "unit": "%",
                                "status": "ok",
                            },
                            "pf_convergence": {
                                "value": 1.0,
                                "unit": "",
                                "status": "ok",
                            },
                        },
                    }
                ]
            },
            "derived_metrics.json",
            claims,
            counter,
        )
        indicators = {c.indicator for c in claims}
        self.assertNotIn("n1_pass_rate", indicators)
        self.assertNotIn("short_circuit_over_limit_ratio", indicators)
        self.assertIn("pf_convergence", indicators)


class TestEconomicZeroValues(unittest.TestCase):
    def test_seed_and_fields_preserve_numeric_zero(self):
        from main_api import (
            _economic_fields_from_proposal,
            _seed_economic_fields_from_mapping,
        )

        seeded = _seed_economic_fields_from_mapping(
            {
                "construction_cost": 0,
                "operation_cost": 0.0,
                "annual_cost": 0,
                "lifecycle_cost": 0,
            }
        )
        self.assertEqual(seeded["construction_cost"], "0")
        self.assertEqual(seeded["operation_cost"], "0.0")
        self.assertEqual(seeded["annual_cost"], "0")
        self.assertEqual(seeded["lifecycle_cost"], "0")

        filled = _economic_fields_from_proposal(
            {
                "construction_cost": 0,
                "operation_cost": 0,
                "annual_cost": 0,
                "lifecycle_cost": 0,
            }
        )
        self.assertEqual(filled["construction_cost"], "0")
        self.assertEqual(filled["operation_cost"], "0")
        self.assertEqual(filled["annual_cost"], "0")
        self.assertEqual(filled["lifecycle_cost"], "0")

    def test_zero_annual_and_lcc_not_overwritten(self):
        from main_api import _economic_fields_from_proposal

        filled = _economic_fields_from_proposal(
            {
                "construction_cost": 100,
                "operation_cost": 2,
                "annual_cost": 0,
                "lifecycle_cost": 0,
            }
        )
        self.assertEqual(filled["annual_cost"], "0")
        self.assertEqual(filled["lifecycle_cost"], "0")

    def test_zero_operation_allows_annual_calc_when_annual_missing(self):
        from main_api import _economic_fields_from_proposal

        filled = _economic_fields_from_proposal(
            {
                "construction_cost": 100,
                "operation_cost": 0,
            }
        )
        self.assertEqual(filled["operation_cost"], "0")
        self.assertNotEqual(filled["annual_cost"], "")
        # CRF(0.07,20)*100 + 0 ≈ 9.439
        self.assertAlmostEqual(float(filled["annual_cost"]), 9.44, places=1)

    def test_blank_falls_back_to_alias(self):
        from main_api import _seed_economic_fields_from_mapping

        seeded = _seed_economic_fields_from_mapping(
            {
                "operation_cost": None,
                "maintenance_cost_estimate": "",
                "运维成本": "   ",
                "维护成本": 0,
            }
        )
        self.assertEqual(seeded["operation_cost"], "0")

    def test_zero_provenance_provided_in_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "parsed_proposals.json").write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "proposal_name": "方案1",
                                "construction_cost": 0,
                                "operation_cost": 0,
                                "annual_cost": 0,
                                "lifecycle_cost": 0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            analysis = tmp_path / "analysis_1"
            analysis.mkdir()
            (analysis / "pf_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "n1_report_1.json").write_text("{}", encoding="utf-8")
            (analysis / "scc_report_1.json").write_text("{}", encoding="utf-8")
            derived = prep.build_derived_metrics(tmp_path)
            metrics = derived["schemes"][0]["metrics"]
            self.assertEqual(metrics["construction_cost"]["value"], 0.0)
            self.assertEqual(metrics["operation_cost"]["value"], 0.0)
            self.assertEqual(metrics["annual_cost"]["value"], 0.0)
            self.assertEqual(metrics["lifecycle_cost"]["value"], 0.0)
            self.assertEqual(metrics["annual_cost"]["provenance"], "provided")
            self.assertEqual(metrics["lifecycle_cost"]["provenance"], "provided")
            self.assertIsNone(metrics["annual_cost"]["formula"])
            self.assertIsNone(metrics["lifecycle_cost"]["formula"])


if __name__ == "__main__":
    unittest.main()
