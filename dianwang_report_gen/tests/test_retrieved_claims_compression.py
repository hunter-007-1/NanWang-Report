"""retrieved_claims 压缩、去重与长度控制单元测试。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src.nodes.retrieve_claims_for_insights import (
    build_formatted_retrieved_claims,
    build_retrieved_claims_payload,
    claim_dedup_key,
    compact_claim_for_prompt,
    deduplicate_claim_buckets,
    ensure_retrieved_claims_within_limit,
    get_claims_per_insight,
    get_core_claims_per_indicator,
    get_max_claims_chars,
    retrieve_claims_for_insight,
)
from src.pcn import Claim
from src.pcn_database import PCNDatabase


def _sample_claim(
    claim_id: str = "c1",
    indicator: str = "annual_cost",
    value: float = 100.0,
    **extra,
) -> dict:
    claim = {
        "claim_id": claim_id,
        "indicator": indicator,
        "value": value,
        "unit": "万元",
        "entity": "方案A",
        "time": "2026",
        "policy": "default",
        "source_path": "/data/cost.json",
        "path_to_value": "cost.total",
        "original_type": "numeric",
        "context": "年度运行成本",
        "metadata": {
            "formula": "a+b",
            "inputs": {"a": 50, "b": 50},
            "calculation_status": "ok",
            "noise_field": "should_drop_if_empty",
        },
    }
    claim.update(extra)
    return claim


class EnvConfigTests(unittest.TestCase):
    def test_default_env_values(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_claims_per_insight(), 3)
            self.assertEqual(get_core_claims_per_indicator(), 3)
            self.assertEqual(get_max_claims_chars(), 60000)

    def test_custom_env_values(self):
        with mock.patch.dict(
            os.environ,
            {
                "REPORT_CLAIMS_PER_INSIGHT": "5",
                "REPORT_CORE_CLAIMS_PER_INDICATOR": "2",
                "REPORT_MAX_CLAIMS_CHARS": "12000",
            },
            clear=True,
        ):
            self.assertEqual(get_claims_per_insight(), 5)
            self.assertEqual(get_core_claims_per_indicator(), 2)
            self.assertEqual(get_max_claims_chars(), 12000)

    def test_invalid_env_falls_back_to_default(self):
        with mock.patch.dict(
            os.environ,
            {
                "REPORT_CLAIMS_PER_INSIGHT": "abc",
                "REPORT_CORE_CLAIMS_PER_INDICATOR": "0",
                "REPORT_MAX_CLAIMS_CHARS": "-10",
            },
            clear=True,
        ):
            self.assertEqual(get_claims_per_insight(), 3)
            self.assertEqual(get_core_claims_per_indicator(), 3)
            self.assertEqual(get_max_claims_chars(), 60000)


class CompactClaimTests(unittest.TestCase):
    def test_compact_keeps_derivation_metadata(self):
        compact = compact_claim_for_prompt(_sample_claim())
        self.assertEqual(compact["claim_id"], "c1")
        self.assertEqual(compact["indicator"], "annual_cost")
        self.assertIn("metadata", compact)
        self.assertEqual(compact["metadata"]["formula"], "a+b")
        self.assertIn("inputs", compact["metadata"])
        self.assertEqual(compact["metadata"]["calculation_status"], "ok")
        self.assertNotIn("noise_field", compact["metadata"])

    def test_compact_strips_empty_fields(self):
        claim = _sample_claim(unit="", entity=None, policy="")
        compact = compact_claim_for_prompt(claim)
        self.assertNotIn("unit", compact)
        self.assertNotIn("entity", compact)
        self.assertNotIn("policy", compact)

    def test_compact_truncates_long_context(self):
        claim = _sample_claim(context="长" * 1000)
        compact = compact_claim_for_prompt(claim)
        ctx = compact.get("context") or compact.get("metadata", {}).get("context", "")
        self.assertTrue(ctx)
        self.assertLessEqual(len(ctx), 501)

    def test_compact_does_not_mutate_original(self):
        claim = _sample_claim()
        original_context = claim["context"]
        compact_claim_for_prompt(claim)
        self.assertEqual(claim["context"], original_context)


class DedupTests(unittest.TestCase):
    def test_dedup_by_claim_id(self):
        c1 = _sample_claim("same-id", indicator="a")
        c2 = _sample_claim("same-id", indicator="b")
        buckets = {
            "insight_0": {"insight": "i0", "claims": [c1]},
            "insight_1": {"insight": "i1", "claims": [c2]},
        }
        deduped, before, after = deduplicate_claim_buckets(buckets)
        self.assertEqual(before, 2)
        self.assertEqual(after, 1)
        total = sum(len(b["claims"]) for b in deduped.values())
        self.assertEqual(total, 1)

    def test_dedup_by_composite_key_without_claim_id(self):
        c1 = _sample_claim(claim_id="", indicator="pf", value=0.95)
        c2 = dict(c1)
        c2.pop("claim_id", None)
        buckets = {
            "insight_0": {"insight": "i0", "claims": [c1]},
            "insight_1": {"insight": "i1", "claims": [c2]},
        }
        deduped, before, after = deduplicate_claim_buckets(buckets)
        self.assertEqual(before, 2)
        self.assertEqual(after, 1)

    def test_core_metrics_kept_when_duplicate_in_insight(self):
        shared = _sample_claim("shared", indicator="n1_pass_rate", value=1.0)
        buckets = {
            "core_metrics": {"insight": "core", "claims": [shared]},
            "insight_0": {"insight": "i0", "claims": [dict(shared)]},
        }
        deduped, _, after = deduplicate_claim_buckets(buckets)
        self.assertEqual(after, 1)
        self.assertEqual(len(deduped["core_metrics"]["claims"]), 1)
        self.assertEqual(len(deduped["insight_0"]["claims"]), 0)

    def test_claim_dedup_key_prefers_claim_id(self):
        c = _sample_claim("id-1")
        self.assertEqual(claim_dedup_key(c)[0], "id")


class LengthControlTests(unittest.TestCase):
    def test_payload_stays_within_max_chars(self):
        buckets = {
            "core_metrics": {
                "insight": "core",
                "claims": [_sample_claim(f"core-{i}", value=float(i)) for i in range(30)],
            },
            **{
                f"insight_{i}": {
                    "insight": f"洞察{i}",
                    "claims": [
                        _sample_claim(f"ins-{i}-{j}", indicator=f"m{i}", value=float(j))
                        for j in range(5)
                    ],
                }
                for i in range(10)
            },
        }
        payload, summary = build_retrieved_claims_payload(buckets, max_chars=8000)
        formatted = json.dumps(payload, ensure_ascii=False)
        self.assertLessEqual(len(formatted), 8000)
        self.assertIn("_retrieval_summary", payload)
        self.assertGreater(summary["total_included"], 0)
        self.assertTrue(summary["truncated"])

    def test_core_metrics_priority_over_insights(self):
        core = _sample_claim("core-1", indicator="lifecycle_cost", value=999)
        insight = _sample_claim("ins-1", indicator="other", value=1)
        buckets = {
            "core_metrics": {"insight": "core", "claims": [core]},
            "insight_0": {"insight": "i0", "claims": [insight]},
        }
        payload, _ = build_retrieved_claims_payload(buckets, max_chars=60000)
        self.assertEqual(len(payload["core_metrics"]["claims"]), 1)
        self.assertEqual(payload["core_metrics"]["claims"][0]["claim_id"], "core-1")

    def test_at_least_one_claim_per_insight_when_budget_allows(self):
        buckets = {
            f"insight_{i}": {
                "insight": f"洞察{i}",
                "claims": [
                    _sample_claim(f"i{i}-a", indicator=f"m{i}", value=1.0),
                    _sample_claim(f"i{i}-b", indicator=f"m{i}b", value=2.0),
                ],
            }
            for i in range(5)
        }
        payload, summary = build_retrieved_claims_payload(buckets, max_chars=60000)
        for i in range(5):
            self.assertGreaterEqual(len(payload[f"insight_{i}"]["claims"]), 1)
        self.assertEqual(summary["total_included"], 10)

    def test_retrieval_summary_fields(self):
        buckets = {
            "insight_0": {"insight": "i0", "claims": [_sample_claim("a"), _sample_claim("a")]},
        }
        payload, summary = build_retrieved_claims_payload(buckets, max_chars=60000)
        rs = payload["_retrieval_summary"]
        for key in (
            "total_before_dedup",
            "total_after_dedup",
            "total_included",
            "total_dropped",
            "max_chars",
            "truncated",
        ):
            self.assertIn(key, rs)
        self.assertEqual(rs["max_chars"], 60000)
        self.assertEqual(summary["total_before_dedup"], 2)
        self.assertEqual(summary["total_after_dedup"], 1)

    def test_build_formatted_retrieved_claims_valid_json(self):
        buckets = {
            "insight_0": {"insight": "test", "claims": [_sample_claim("x1")]},
        }
        formatted = build_formatted_retrieved_claims(buckets, max_chars=60000)
        parsed = json.loads(formatted)
        self.assertIn("insight_0", parsed)
        self.assertIn("_retrieval_summary", parsed)


class EnsureWithinLimitTests(unittest.TestCase):
    def test_ensure_within_limit_passes_through_small_payload(self):
        small = json.dumps({"insight_0": {"insight": "x", "claims": []}}, ensure_ascii=False)
        result = ensure_retrieved_claims_within_limit(small, max_chars=60000)
        self.assertEqual(result, small)

    def test_ensure_within_limit_recompresses_oversized_payload(self):
        huge_buckets = {
            "core_metrics": {
                "insight": "core",
                "claims": [
                    _sample_claim(f"h{i}", context="填充" * 200, value=float(i))
                    for i in range(200)
                ],
            },
        }
        oversized = build_formatted_retrieved_claims(huge_buckets, max_chars=999999)
        self.assertGreater(len(oversized), 60000)
        compressed = ensure_retrieved_claims_within_limit(oversized, max_chars=60000)
        self.assertLessEqual(len(compressed), 60000)
        parsed = json.loads(compressed)
        self.assertIn("_retrieval_summary", parsed)

    def test_ensure_within_limit_handles_empty_string(self):
        result = ensure_retrieved_claims_within_limit("", max_chars=60000)
        parsed = json.loads(result)
        self.assertIn("_retrieval_summary", parsed)


class GenerateReportIntegrationTests(unittest.TestCase):
    @staticmethod
    def _fake_llm_response(content: str = "# 测试报告\n\n正文"):
        class FakeMessage:
            pass

        class FakeChoice:
            pass

        class FakeResponse:
            pass

        msg = FakeMessage()
        msg.content = content
        choice = FakeChoice()
        choice.message = msg
        choice.finish_reason = "stop"
        resp = FakeResponse()
        resp.choices = [choice]
        return resp

    def test_generate_report_logs_prompt_length(self):
        import asyncio
        import importlib

        from src.graph_state import State

        gr = importlib.import_module("src.nodes.generate_report")

        log_messages: list[str] = []

        def capture_info(message, *args, **kwargs):
            log_messages.append(str(message))

        mock_llm = mock.Mock()
        mock_llm.chat.completions.create.return_value = self._fake_llm_response()

        async def fake_optimize(report, *_args, **_kwargs):
            return report

        with tempfile.TemporaryDirectory() as tmp:
            state = State(
                md_tables_str="tables",
                insights="insights",
                retrieved_claims=build_formatted_retrieved_claims(
                    {"insight_0": {"insight": "i", "claims": [_sample_claim("z")]}}
                ),
                background_context="500kV曲靖变背景",
                background_context_source="test.md",
                output_dir=tmp,
            )

            with mock.patch.object(gr.logger, "info", side_effect=capture_info):
                with mock.patch.object(
                    gr.client_manager,
                    "get_llm_openai_client",
                    return_value=(mock_llm, "test-model", 0.1),
                ):
                    with mock.patch.object(
                        gr.client_manager,
                        "get_vlm_openai_client",
                        return_value=(mock.Mock(), "vlm-model", 0.1),
                    ):
                        with mock.patch.object(gr, "optimize_report", side_effect=fake_optimize):
                            asyncio.run(gr.generate_report(state))

        prompt_logs = [m for m in log_messages if "最终报告 Prompt 长度" in m]
        self.assertTrue(prompt_logs, msg=f"未找到 Prompt 长度日志: {log_messages}")

    def test_generate_report_recompresses_oversized_claims(self):
        import asyncio
        import importlib

        from src.graph_state import State

        gr = importlib.import_module("src.nodes.generate_report")

        oversized_claims = json.dumps(
            {
                "insight_0": {
                    "insight": "i",
                    "claims": [
                        compact_claim_for_prompt(
                            _sample_claim(f"big-{i}", context="填充" * 300, value=float(i))
                        )
                        for i in range(500)
                    ],
                },
                "_retrieval_summary": {"truncated": False},
            },
            ensure_ascii=False,
        )
        self.assertGreater(len(oversized_claims), 60000)

        compressed_lengths: list[int] = []

        def capture_info(message, *args, **kwargs):
            text = str(message)
            if "压缩后 retrieved_claims 长度" in text:
                import re

                match = re.search(r"(\d+) 字符", text)
                if match:
                    compressed_lengths.append(int(match.group(1)))

        mock_llm = mock.Mock()
        mock_llm.chat.completions.create.return_value = self._fake_llm_response("# 测试报告")

        async def fake_optimize(report, *_args, **_kwargs):
            return report

        with tempfile.TemporaryDirectory() as tmp:
            state = State(
                md_tables_str="t",
                insights="i",
                retrieved_claims=oversized_claims,
                output_dir=tmp,
            )
            with mock.patch.object(gr.logger, "info", side_effect=capture_info):
                with mock.patch.object(
                    gr.client_manager,
                    "get_llm_openai_client",
                    return_value=(mock_llm, "test-model", 0.1),
                ):
                    with mock.patch.object(
                        gr.client_manager,
                        "get_vlm_openai_client",
                        return_value=(mock.Mock(), "vlm-model", 0.1),
                    ):
                        with mock.patch.object(gr, "optimize_report", side_effect=fake_optimize):
                            asyncio.run(gr.generate_report(state))

        self.assertTrue(compressed_lengths)
        self.assertLessEqual(compressed_lengths[0], 60000)

    def test_background_context_preserved_in_report_prompt(self):
        from src.skills.report_generation.main import (
            ReportGenerationInput,
            render_prompt,
        )

        claims = build_formatted_retrieved_claims(
            {"insight_0": {"insight": "i", "claims": [_sample_claim("bg-test")]}}
        )
        prompt = render_prompt(
            ReportGenerationInput(
                data_tables="t",
                insights="i",
                retrieved_claims=claims,
                background_context="500kV曲靖变位于曲靖市。",
            )
        )
        self.assertIn("500kV曲靖变", prompt)
        self.assertIn("retrieved_claims", prompt.lower())


class DatabaseRetrievalTests(unittest.TestCase):
    def _dict_to_claim(self, data: dict) -> Claim:
        metadata = {
            "source_path": data.get("source_path", ""),
            "path_to_value": data.get("path_to_value", ""),
            "original_type": data.get("original_type", ""),
            "context": data.get("context", ""),
        }
        if isinstance(data.get("metadata"), dict):
            metadata.update(data["metadata"])
        return Claim(
            claim_id=data["claim_id"],
            indicator=data["indicator"],
            value=float(data["value"]),
            unit=data.get("unit"),
            entity=data.get("entity"),
            time=data.get("time"),
            metadata=metadata,
        )

    def _make_db_with_claims(self, claims: list) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        with PCNDatabase(tmp.name) as db:
            db.init_schema()
            for claim in claims:
                db.insert_claim(self._dict_to_claim(claim))
        return tmp.name

    def test_empty_db_retrieval_does_not_crash(self):
        db_path = self._make_db_with_claims([])
        try:
            with PCNDatabase(db_path) as db:
                results = retrieve_claims_for_insight("N-1 通过率 100%", db, k=3)
            self.assertEqual(results, [])
        finally:
            os.unlink(db_path)

    def test_retrieve_claims_respects_k_limit(self):
        claims = [
            _sample_claim(f"c{i}", indicator="annual_cost", value=float(i), context=f"成本{i}")
            for i in range(10)
        ]
        db_path = self._make_db_with_claims(claims)
        try:
            with PCNDatabase(db_path) as db:
                results = retrieve_claims_for_insight("annual_cost 成本", db, k=3)
            self.assertLessEqual(len(results), 3)
        finally:
            os.unlink(db_path)

    def test_big_data_case_stays_under_60k(self):
        """模拟多洞察 + 多核心指标场景，输出应控制在 60k 以内。"""
        many_claims = [
            _sample_claim(
                f"bulk-{i}",
                indicator=f"metric_{i % 20}",
                value=float(i),
                context=f"上下文{i} " + ("详" * 50),
            )
            for i in range(300)
        ]
        buckets = {
            "core_metrics": {"insight": "core", "claims": many_claims[:80]},
            **{
                f"insight_{i}": {
                    "insight": f"洞察点{i} 涉及 annual_cost 与 n1_pass_rate",
                    "claims": many_claims[80 + i * 5 : 80 + i * 5 + 5],
                }
                for i in range(26)
            },
        }
        formatted = build_formatted_retrieved_claims(buckets, max_chars=60000)
        self.assertLessEqual(len(formatted), 60000)
        parsed = json.loads(formatted)
        self.assertTrue(parsed["_retrieval_summary"]["truncated"])


if __name__ == "__main__":
    unittest.main()
