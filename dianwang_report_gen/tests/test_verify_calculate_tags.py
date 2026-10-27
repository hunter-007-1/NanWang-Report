"""Calculate 标签验证与 PCN 集成测试。"""

from __future__ import annotations

import unittest
from unittest import mock

from src.nodes.verify_calculate_tags import (
    normalize_formula_power_syntax,
    verify_calculate_tags_in_report,
    verify_single_calculate,
)
from src.nodes.verify_pcn_claims import compute_pcn_verification_passed, format_pcn_review_message
from src.pcn import Claim


def _claim(
    claim_id: str,
    value: float,
    *,
    indicator: str = "construction_cost",
    unit: str = "元",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        indicator=indicator,
        value=value,
        unit=unit,
        metadata={
            "source_path": "derived_metrics.json",
            "path_to_value": f"schemes[0].metrics.{indicator}.value",
            "original_type": "number",
            "context": "",
        },
    )


class CalculateVerificationTests(unittest.TestCase):
    def test_fake_variable_with_real_claim_not_verified(self):
        fields = {
            "input": "real_cost=162000000; fake_cost=999",
            "input_source": "real_cost=claim_000006",
            "formula": "result = fake_cost",
            "output": "999",
        }
        claims = {"000006": _claim("000006", 162000000)}
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertNotEqual(status, "verified")
        self.assertEqual(status, "pending")
        self.assertIn("fake_cost", reason)

    def test_empty_input_source_with_variables_is_pending(self):
        fields = {
            "input": "fake_cost=999",
            "input_source": "",
            "formula": "result = fake_cost",
            "output": "999",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "pending")
        self.assertIn("input_source", reason)

    def test_legacy_single_claim_single_variable_verified(self):
        fields = {
            "input": "construction_cost_yuan=162000000",
            "input_source": "claim_000006",
            "formula": "construction_cost_yi_yuan = construction_cost_yuan / 100000000",
            "output": "1.62",
        }
        claims = {"000006": _claim("000006", 162000000)}
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "verified", msg=reason)

    def test_legacy_ambiguous_multiple_variables_pending(self):
        fields = {
            "input": "real_cost=162000000; fake_cost=999",
            "input_source": "claim_000006",
            "formula": "result = real_cost + fake_cost",
            "output": "162000999",
        }
        claims = {"000006": _claim("000006", 162000000)}
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "pending")
        self.assertIn("无法唯一确定", reason)

    def test_legacy_multiple_claims_pending(self):
        fields = {
            "input": "a=1; b=2",
            "input_source": "claim_000001, claim_000002",
            "formula": "a + b",
            "output": "3",
        }
        status, reason, _ = verify_single_calculate(fields, {"000001": _claim("000001", 1), "000002": _claim("000002", 2)})
        self.assertEqual(status, "pending")

    def test_variable_level_claim_mapping_verified(self):
        fields = {
            "input": "construction_cost_yuan=162000000",
            "input_source": "construction_cost_yuan=claim_000006",
            "formula": "construction_cost_yi_yuan = construction_cost_yuan / 100000000",
            "output": "1.62",
        }
        claims = {"000006": _claim("000006", 162000000)}
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "verified", msg=reason)

    def test_variable_level_claim_mapping_mismatch_invalid(self):
        fields = {
            "input": "construction_cost_yuan=162000000",
            "input_source": "construction_cost_yuan=claim_000006",
            "formula": "construction_cost_yuan / 100000000",
            "output": "9.99",
        }
        claims = {"000006": _claim("000006", 999999)}
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "invalid")
        self.assertIn("不一致", reason)

    def test_compare_rules_mapping_verified(self):
        fields = {
            "input": "i=0.07",
            "input_source": "i=compare_rules.metrics.annual_cost.default_inputs.interest_rate",
            "formula": "i",
            "output": "0.07",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "verified", msg=reason)

    def test_compare_rules_missing_path_pending(self):
        fields = {
            "input": "x=1",
            "input_source": "x=compare_rules.metrics.not_exists.value",
            "formula": "x",
            "output": "1",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "pending")
        self.assertIn("不存在", reason)

    def test_compare_rules_value_mismatch_invalid(self):
        fields = {
            "input": "i=0.08",
            "input_source": "i=compare_rules.metrics.annual_cost.default_inputs.interest_rate",
            "formula": "i",
            "output": "0.08",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "invalid")
        self.assertIn("不一致", reason)

    def test_caret_annual_cost_formula_verified(self):
        construction_cost = 100000000.0
        operation_cost = 5000000.0
        i = 0.07
        n = 20.0
        expected = construction_cost * i * (1 + i) ** n / ((1 + i) ** n - 1) + operation_cost
        fields = {
            "input": (
                f"construction_cost={construction_cost}; operation_cost={operation_cost}; "
                f"i={i}; n={n}"
            ),
            "input_source": (
                f"construction_cost=claim_000001; operation_cost=claim_000002; "
                f"i=compare_rules.metrics.annual_cost.default_inputs.interest_rate; "
                f"n=compare_rules.metrics.annual_cost.default_inputs.years"
            ),
            "formula": "construction_cost * i*(1+i)^n / ((1+i)^n - 1) + operation_cost",
            "output": str(expected),
        }
        claims = {
            "000001": _claim("000001", construction_cost),
            "000002": _claim("000002", operation_cost, indicator="operation_cost"),
        }
        status, reason, meta = verify_single_calculate(fields, claims)
        self.assertEqual(status, "verified", msg=reason)
        self.assertTrue(meta.get("formula_normalized"))

    def test_double_star_annual_cost_formula_verified(self):
        construction_cost = 100000000.0
        operation_cost = 5000000.0
        i = 0.07
        n = 20.0
        expected = construction_cost * i * (1 + i) ** n / ((1 + i) ** n - 1) + operation_cost
        fields = {
            "input": (
                f"construction_cost={construction_cost}; operation_cost={operation_cost}; "
                f"i={i}; n={n}"
            ),
            "input_source": (
                f"construction_cost=claim_000001; operation_cost=claim_000002; "
                f"i=compare_rules.metrics.annual_cost.default_inputs.interest_rate; "
                f"n=compare_rules.metrics.annual_cost.default_inputs.years"
            ),
            "formula": "construction_cost * i*(1+i)**n / ((1+i)**n - 1) + operation_cost",
            "output": str(expected),
        }
        claims = {
            "000001": _claim("000001", construction_cost),
            "000002": _claim("000002", operation_cost, indicator="operation_cost"),
        }
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "verified", msg=reason)

    def test_formula_normalized_records_original(self):
        normalized, changed, original = normalize_formula_power_syntax("(1+i)^n")
        self.assertTrue(changed)
        self.assertIn("^", original)
        self.assertIn("**", normalized)

    def test_constant_formula_without_variables_verified(self):
        fields = {
            "input": "",
            "input_source": "",
            "formula": "100000000 / 100000000",
            "output": "1",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "verified", msg=reason)

    def test_calculate_function_call_not_verified(self):
        fields = {
            "input": "x=2",
            "input_source": "x=compare_rules.metrics.annual_cost.default_inputs.interest_rate",
            "formula": "sin(x)",
            "output": "1",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertIn(status, ("pending", "invalid"))

    def test_calculate_attribute_access_not_verified(self):
        fields = {
            "input": "x=2",
            "input_source": "",
            "formula": "x.__class__",
            "output": "1",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertIn(status, ("pending", "invalid"))

    def test_calculate_division_by_zero_invalid(self):
        fields = {
            "input": "a=1; b=0",
            "input_source": "a=claim_000001; b=claim_000002",
            "formula": "a / b",
            "output": "1",
        }
        claims = {
            "000001": _claim("000001", 1),
            "000002": _claim("000002", 0, indicator="dummy"),
        }
        status, reason, _ = verify_single_calculate(fields, claims)
        self.assertEqual(status, "invalid")
        self.assertIn("除数为0", reason)

    def test_calculate_missing_claim_pending(self):
        fields = {
            "input": "construction_cost_yuan=162000000",
            "input_source": "construction_cost_yuan=claim_999999",
            "formula": "construction_cost_yuan / 100000000",
            "output": "1.62",
        }
        status, reason, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "pending")
        self.assertIn("999999", reason)

    def test_report_without_calculate_does_not_block_pcn(self):
        stats = {
            "total_claims": 2,
            "verified_claims": 2,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 0,
            "total_calculates": 0,
            "verified_calculates": 0,
            "mismatched_calculates": 0,
            "pending_calculates": 0,
            "invalid_calculates": 0,
        }
        self.assertTrue(compute_pcn_verification_passed(stats))

    def test_calculate_binding_failure_blocks_pcn(self):
        stats = {
            "total_claims": 2,
            "verified_claims": 2,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 0,
            "total_calculates": 1,
            "verified_calculates": 0,
            "pending_calculates": 1,
            "mismatched_calculates": 0,
            "invalid_calculates": 0,
        }
        self.assertFalse(compute_pcn_verification_passed(stats))

    def test_verify_calculate_tags_in_report(self):
        report = (
            "<calculate> "
            "input: construction_cost_yuan=162000000; "
            "input_source: construction_cost_yuan=claim_000006; "
            "formula: construction_cost_yuan / 100000000; "
            "output: 1.62 "
            "</calculate>"
        )
        claims = {"000006": _claim("000006", 162000000)}
        out, stats = verify_calculate_tags_in_report(report, claims)
        self.assertEqual(stats["total_calculates"], 1)
        self.assertEqual(stats["verified_calculates"], 1)
        self.assertIn("✓", out)


class PcnReviewMessageFormatTests(unittest.TestCase):
    def test_review_message_no_duplicate_stripped(self):
        message = format_pcn_review_message(
            {
                "total_claims": 42,
                "verified_claims": 40,
                "mismatched_claims": 1,
                "not_found_claims": 0,
                "stripped_claims": 1,
                "total_calculates": 8,
                "verified_calculates": 7,
                "mismatched_calculates": 1,
                "pending_calculates": 0,
                "invalid_calculates": 0,
            }
        )
        self.assertEqual(message.count("移除标签"), 1)
        self.assertIn("Claim总数42", message)
        self.assertIn("Calculate总数8", message)
        self.assertNotIn("移除定位不到证据", message)


class StrictCalculateParsingTests(unittest.TestCase):
    def _fields(self, **kwargs):
        base = {
            "input": "x=1",
            "input_source": "x=claim_000006",
            "formula": "result=x",
            "output": "1",
        }
        base.update(kwargs)
        return base

    def test_input_x_1oops_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(input="x=1oops"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")
        self.assertIn("input", reason)

    def test_input_x_1_yuan_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(input="x=1元"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")

    def test_input_fake_text_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(input="x=1; fake text"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")
        self.assertIn("fake text", reason)

    def test_input_empty_variable_name_invalid(self):
        status, _, _ = verify_single_calculate(self._fields(input="=1"), {})
        self.assertEqual(status, "invalid")

    def test_input_nan_and_infinity_invalid(self):
        for bad in ("x=NaN", "x=Infinity", "x=-Infinity"):
            status, _, _ = verify_single_calculate(self._fields(input=bad), {})
            self.assertEqual(status, "invalid", msg=bad)

    def test_input_duplicate_variable_different_values_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(input="x=1; x=2"),
            {"000006": _claim("000006", 1)},
        )
        self.assertEqual(status, "invalid")
        self.assertIn("重复冲突", reason)

    def test_input_duplicate_variable_same_value_warning(self):
        status, _, meta = verify_single_calculate(
            self._fields(input="x=1; x=1"),
            {"000006": _claim("000006", 1)},
        )
        self.assertEqual(status, "verified")
        self.assertTrue(meta.get("input_warnings"))

    def test_output_with_garbage_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(output="1 garbage"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")
        self.assertIn("output", reason)

    def test_output_result_equals_invalid(self):
        status, _, _ = verify_single_calculate(
            self._fields(output="result=1"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")

    def test_output_yuan_suffix_invalid(self):
        status, _, _ = verify_single_calculate(
            self._fields(output="1元"), {"000006": _claim("000006", 1)}
        )
        self.assertEqual(status, "invalid")

    def test_output_percent_parsed(self):
        status, _, _ = verify_single_calculate(
            {
                "input": "x=93.15",
                "input_source": "x=claim_000006",
                "formula": "x",
                "output": "93.15%",
            },
            {"000006": _claim("000006", 93.15, indicator="n1_pass_rate", unit="%")},
        )
        self.assertEqual(status, "verified")

    def test_output_thousand_separator_valid(self):
        status, _, _ = verify_single_calculate(
            self._fields(input="x=1620.5", output="1,620.50"),
            {"000006": _claim("000006", 1620.5)},
        )
        self.assertEqual(status, "verified")

    def test_output_invalid_thousand_separator(self):
        for bad in ("16,20.50", "1,62,000"):
            status, reason, _ = verify_single_calculate(
                self._fields(output=bad), {"000006": _claim("000006", 1)}
            )
            self.assertEqual(status, "invalid", msg=bad)
            self.assertIn("千分位", reason)

    def test_input_source_claim_suffix_not_recognized(self):
        status, reason, _ = verify_single_calculate(
            self._fields(input_source="x=claim_000006_NOTREAL"),
            {"000006": _claim("000006", 1)},
        )
        self.assertNotEqual(status, "verified")
        self.assertEqual(status, "invalid")
        self.assertIn("input_source", reason)

    def test_input_source_prefix_claim_not_recognized(self):
        status, _, _ = verify_single_calculate(
            self._fields(input_source="prefix_claim_000006"), {}
        )
        self.assertEqual(status, "invalid")

    def test_input_source_unparsed_segment_not_verified(self):
        status, _, _ = verify_single_calculate(
            self._fields(input_source="x=claim_000006; fake text"),
            {"000006": _claim("000006", 1)},
        )
        self.assertNotEqual(status, "verified")
        self.assertEqual(status, "invalid")

    def test_input_source_duplicate_variable_different_source_invalid(self):
        status, reason, _ = verify_single_calculate(
            self._fields(
                input_source=(
                    "x=claim_000006; x=compare_rules.metrics.annual_cost.default_inputs.interest_rate"
                )
            ),
            {"000006": _claim("000006", 1)},
        )
        self.assertEqual(status, "invalid")
        self.assertIn("重复冲突", reason)

    def test_formula_result_x_not_normalized(self):
        _, _, meta = verify_single_calculate(
            self._fields(formula="result=x"), {"000006": _claim("000006", 1)}
        )
        self.assertFalse(meta.get("formula_normalized"))

    def test_formula_caret_normalized(self):
        normalized, changed, original = normalize_formula_power_syntax("result=(1+i)^n")
        self.assertTrue(changed)
        self.assertIn("**", normalized)
        self.assertIn("^", original)

    def test_formula_double_star_not_normalized(self):
        normalized, changed, _ = normalize_formula_power_syntax("result=(1+i)**n")
        self.assertFalse(changed)
        self.assertEqual(normalized, "result=(1+i)**n")

    def test_title_html_escape(self):
        report = (
            "<calculate> "
            'input: x=1; bad"seg>; '
            "input_source: x=claim_000006; "
            "formula: x; "
            "output: 1 "
            "</calculate>"
        )
        out, stats = verify_calculate_tags_in_report(report, {"000006": _claim("000006", 1)})
        self.assertEqual(stats["invalid_calculates"], 1)
        self.assertIn("&quot;", out)
        self.assertIn("&gt;", out)
        self.assertNotIn('bad"seg>', out.split("<sup")[1] if "<sup" in out else out)

    def test_strict_parse_failure_blocks_pcn(self):
        fields = {
            "input": "x=1oops",
            "input_source": "x=claim_000006",
            "formula": "x",
            "output": "1",
        }
        status, _, _ = verify_single_calculate(fields, {})
        self.assertEqual(status, "invalid")
        stats = {
            "total_claims": 1,
            "verified_claims": 1,
            "mismatched_claims": 0,
            "not_found_claims": 0,
            "pending_claims": 0,
            "stripped_claims": 0,
            "total_calculates": 1,
            "verified_calculates": 0,
            "invalid_calculates": 1,
            "pending_calculates": 0,
            "mismatched_calculates": 0,
        }
        self.assertFalse(compute_pcn_verification_passed(stats))

    def test_minimal_repro_cases_not_verified(self):
        claims = {"000006": _claim("000006", 1)}
        cases = [
            {"input": "x=1oops", "input_source": "x=claim_000006", "formula": "result=x", "output": "1"},
            {"input": "x=1", "input_source": "x=claim_000006", "formula": "result=x", "output": "1 garbage"},
            {"input": "x=1", "input_source": "x=claim_000006_NOTREAL", "formula": "result=x", "output": "1"},
            {"input": "x=1; fake text", "input_source": "x=claim_000006", "formula": "result=x", "output": "1"},
        ]
        for fields in cases:
            status, _, _ = verify_single_calculate(fields, claims)
            self.assertNotEqual(status, "verified", msg=fields)


if __name__ == "__main__":
    unittest.main()
