"""背景资料接入比选报告生成的单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class BackgroundContextPromptTests(unittest.TestCase):
    def test_report_generation_prompt_includes_background_context(self):
        from src.skills.report_generation.main import (
            ReportGenerationInput,
            render_prompt,
        )

        prompt = render_prompt(
            ReportGenerationInput(
                data_tables="table-data",
                insights="insight-text",
                background_context="500kV曲靖变位于云南省曲靖市麒麟区茨营镇西侧。",
            )
        )
        self.assertIn("工程背景与接入方案原始资料", prompt)
        self.assertIn("500kV曲靖变", prompt)
        self.assertIn("背景资料使用规则", prompt)
        self.assertIn("周边500kV", prompt)
        self.assertIn("不得根据电气仿真结果推断或编造", prompt)
        self.assertIn("普通故障节点不得直接表述为已经确定的候选接入点", prompt)

    def test_report_generation_prompt_allows_empty_background(self):
        from src.skills.report_generation.main import (
            ReportGenerationInput,
            render_prompt,
        )

        prompt = render_prompt(
            ReportGenerationInput(
                data_tables="table-data",
                insights="insight-text",
                background_context="",
            )
        )
        self.assertIn("工程背景与接入方案原始资料", prompt)
        self.assertIn("<background_context>", prompt)
        self.assertIn("</background_context>", prompt)
        # 空背景时不得伪造曲靖变等内容
        self.assertNotIn("曲靖变位于", prompt)


class BackgroundContextFileHelpersTests(unittest.TestCase):
    def test_copy_background_from_generation_dir(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "input"
            out = Path(tmp) / "output"
            gen = base / "generation"
            gen.mkdir(parents=True)
            out.mkdir(parents=True)
            (gen / "background_context.md").write_text(
                "500kV曲靖变备用 1 个间隔。\n", encoding="utf-8"
            )

            content = main_api._copy_background_context_to_demo_input(base, out)
            dst = out / "generation" / "background_context.md"
            self.assertTrue(dst.exists())
            self.assertIn("500kV曲靖变", content)
            self.assertIn("500kV曲靖变", dst.read_text(encoding="utf-8"))

    def test_priority_background_over_reference_and_user_input(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "input"
            out = Path(tmp) / "output"
            gen = base / "generation"
            gen.mkdir(parents=True)
            out.mkdir(parents=True)
            (gen / "background_context.md").write_text("FROM_BACKGROUND", encoding="utf-8")
            (gen / "reference_document.md").write_text("FROM_REFERENCE", encoding="utf-8")
            (gen / "user_input.md").write_text("FROM_USER", encoding="utf-8")

            content = main_api._copy_background_context_to_demo_input(base, out)
            self.assertEqual(content, "FROM_BACKGROUND")

    def test_fallback_to_reference_document(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "input"
            out = Path(tmp) / "output"
            gen = base / "generation"
            gen.mkdir(parents=True)
            out.mkdir(parents=True)
            (gen / "reference_document.md").write_text("FROM_REFERENCE", encoding="utf-8")

            content = main_api._copy_background_context_to_demo_input(base, out)
            self.assertEqual(content, "FROM_REFERENCE")
            self.assertEqual(
                (out / "generation" / "background_context.md").read_text(encoding="utf-8"),
                "FROM_REFERENCE",
            )

    def test_missing_background_does_not_crash(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "input"
            out = Path(tmp) / "output"
            base.mkdir(parents=True)
            out.mkdir(parents=True)
            content = main_api._copy_background_context_to_demo_input(base, out)
            self.assertEqual(content, "")
            self.assertFalse((out / "generation" / "background_context.md").exists())

    def test_env_absolute_and_relative_paths(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            abs_file = Path(tmp) / "abs_bg.md"
            abs_file.write_text("ABS_CONTENT_曲靖变", encoding="utf-8")

            found = main_api._find_background_context_source(
                Path(tmp) / "missing_input",
                explicit_file=str(abs_file),
            )
            self.assertEqual(found, abs_file)

            rel_name = "rel_bg_for_test.md"
            rel_path = main_api.APP_DIR / rel_name
            try:
                rel_path.write_text("REL_CONTENT", encoding="utf-8")
                found_rel = main_api._find_background_context_source(
                    Path(tmp) / "missing_input",
                    explicit_file=rel_name,
                )
                self.assertEqual(found_rel.resolve(), rel_path.resolve())
            finally:
                if rel_path.exists():
                    rel_path.unlink()

    def test_env_report_background_context_file(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "env_bg.md"
            env_file.write_text("ENV_曲靖变", encoding="utf-8")
            out = Path(tmp) / "out"
            out.mkdir()
            with mock.patch.dict(os.environ, {"REPORT_BACKGROUND_CONTEXT_FILE": str(env_file)}):
                content = main_api._copy_background_context_to_demo_input(
                    Path(tmp) / "empty_input",
                    out,
                    explicit_file="",
                )
            self.assertIn("ENV_曲靖变", content)
            self.assertTrue((out / "generation" / "background_context.md").exists())

    def test_agent_instruction_env_falls_back_to_engineering_background(self):
        import main_api

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "input"
            out = Path(tmp) / "out"
            gen = base / "generation"
            gen.mkdir(parents=True)
            out.mkdir()

            bad = Path(tmp) / "shuifu_background_context.md"
            bad.write_text(
                "你是一个电力网架规划的专家。\n"
                "请严格遵循以下规则：\n"
                "1. 要求生成5个可行的方案\n"
                "2. 每个方案都需要输出对应的JSON数据\n"
                "3. 只需输出删除、修改和新增的部份。\n",
                encoding="utf-8",
            )
            (gen / "background_context.md").write_text(
                "#### 周边 500kV 电网接入点分析\n"
                "（1）500kV 曲靖变备用 1 个间隔，距离约 27km。\n"
                "（2）500kV 龙海变备用 1 个间隔。\n"
                "（3）鲁西换流站备用 1 个间隔。\n"
                "（4）罗平变因风景区暂不考虑。\n"
                "（5）圭山变可考虑作为接入点。\n"
                "#### 接入系统方案拟定\n"
                "A类方案：以π接方式接入现有网架。\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ, {"REPORT_BACKGROUND_CONTEXT_FILE": str(bad)}
            ):
                content = main_api._copy_background_context_to_demo_input(
                    base, out, explicit_file=""
                )

            self.assertIn("曲靖变", content)
            self.assertIn("接入点分析", content)
            self.assertNotIn("你是一个电力网架规划的专家", content)
            copied = (out / "generation" / "background_context.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("龙海变", copied)

    def test_looks_like_helpers(self):
        import main_api

        agent = (
            "你是一个电力网架规划的专家，请严格遵循以下规则："
            "要求生成5个可行的方案，每个方案都需要输出对应的JSON数据。"
        )
        engineering = (
            "周边500kV电网接入点分析：曲靖变备用1个间隔，龙海变、鲁西、"
            "罗平变、圭山变可考虑；接入系统方案拟定采用π接。"
        )
        self.assertTrue(main_api._looks_like_agent_instruction(agent))
        self.assertFalse(main_api._looks_like_engineering_background(agent))
        self.assertTrue(main_api._looks_like_engineering_background(engineering))
        self.assertFalse(main_api._looks_like_agent_instruction(engineering))

    def test_read_failure_does_not_crash(self):
        import main_api

        missing = Path("/path/does/not/exist/background_context.md")
        self.assertEqual(main_api._read_background_context_file(missing), "")


class ProposalDescriptionTests(unittest.TestCase):
    def test_description_includes_modifications_topology(self):
        import main_api

        proposal = {
            "modifications": [
                {
                    "action": "disable_branch",
                    "params": {
                        "full_branch_data": {
                            "NAME1": "滇溪右50",
                            "NAME2": "滇牛寨51",
                            "CKT ID": "1",
                        }
                    },
                },
                {
                    "action": "add_bus",
                    "params": {"full_bus_data": {"NAME": "滇水富51"}},
                },
                {
                    "action": "add_line",
                    "params": {
                        "full_branch_data": {
                            "NAME1": "滇溪右50",
                            "NAME2": "滇水富51",
                            "CKT ID": "1",
                            "MILES": 30.0,
                            "LINE NAME": "500kV溪水甲线",
                        }
                    },
                },
            ],
            "construction_cost": "100",
            "operation_cost": "10",
        }
        text = main_api._build_proposal_description(
            Path("run_3"), 0, 1, proposal
        )
        self.assertIn("新增节点：滇水富51", text)
        self.assertIn("滇溪右50-滇牛寨51", text)
        self.assertIn("滇溪右50-滇水富51", text)
        self.assertIn("CKT=1", text)
        self.assertIn("30.0 mile", text)
        self.assertIn("π接", text)
        self.assertIn("建设投资", text)
        # 不得编造不存在的站名
        self.assertNotIn("曲靖变", text)


class PreprocessBackgroundStateTests(unittest.TestCase):
    def test_preprocess_reads_background_into_state_fields(self):
        import asyncio
        from src.graph_state import State
        from src.nodes.data_preprocessing_pcn import data_preprocessing_pcn

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "demo_input"
            working_dir = Path(tmp) / "working"
            output_dir = Path(tmp) / "output"
            gen = input_dir / "generation"
            gen.mkdir(parents=True)
            working_dir.mkdir()
            output_dir.mkdir()
            # 最小可过滤输入：空 proposals + 无 analysis 也可走 filter 失败路径
            (gen / "parsed_proposals.json").write_text(
                '{"proposals": []}', encoding="utf-8"
            )
            (gen / "background_context.md").write_text(
                "500kV曲靖变位于测试站址附近。", encoding="utf-8"
            )

            state = State(
                input_dir=input_dir,
                output_dir=output_dir,
                working_dir=working_dir,
                debug=True,
            )

            # filter/claim 路径可能因缺 analysis 而变短，但背景读取应发生在最前面
            updates = asyncio.run(data_preprocessing_pcn(state))
            self.assertIn("500kV曲靖变", updates.get("background_context", ""))
            self.assertEqual(
                updates.get("background_context_source"),
                "generation/background_context.md",
            )

    def test_preprocess_without_background_keeps_empty(self):
        import asyncio
        from src.graph_state import State
        from src.nodes.data_preprocessing_pcn import data_preprocessing_pcn

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "demo_input"
            working_dir = Path(tmp) / "working"
            output_dir = Path(tmp) / "output"
            gen = input_dir / "generation"
            gen.mkdir(parents=True)
            working_dir.mkdir()
            output_dir.mkdir()
            (gen / "parsed_proposals.json").write_text(
                '{"proposals": []}', encoding="utf-8"
            )

            state = State(
                input_dir=input_dir,
                output_dir=output_dir,
                working_dir=working_dir,
                debug=True,
            )
            updates = asyncio.run(data_preprocessing_pcn(state))
            self.assertEqual(updates.get("background_context"), "")
            self.assertEqual(updates.get("background_context_source"), "")


class BridgeEnvForwardTests(unittest.TestCase):
    def test_bridge_server_reads_background_env(self):
        bridge = (ROOT.parent / "powergrid_pipeline" / "bridge_server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'REPORT_BACKGROUND_CONTEXT_FILE = os.environ.get("REPORT_BACKGROUND_CONTEXT_FILE"',
            bridge,
        )
        self.assertIn('payload["backgroundContextFile"]', bridge)


if __name__ == "__main__":
    unittest.main()
