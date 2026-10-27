from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from src.skills.base import read_resource, read_shared_resource, read_skill, render_template


@dataclass(frozen=True)
class InsightsGenerationInput:
    data_tables: str


def load_comparing_principles() -> str:
    return read_resource(__file__, "access_schemes_comparing_principles.md")


def render_system_prompt(comparing_principles: str | None = None) -> str:
    return render_template(
        read_skill(__file__),
        access_schemes_comparing_principles=(
            comparing_principles if comparing_principles is not None else load_comparing_principles()
        ),
        compare_rules=read_shared_resource("compare_rules.md"),
    )


def render_prompt(payload: InsightsGenerationInput) -> str:
    return f"请从下面的数据表中提取出关键影响规划方案选择的关键洞察:\n\n{payload.data_tables}"


def create_agent(
    model,
    comparing_principles: str | None = None,
    working_dir: str = ".",
    debug: bool = False,
):
    from deepagents import create_deep_agent

    from src.middlewares.logger import log_model_response, log_tool_call
    from src.tools import grid_calculator

    logger.info(f"创建洞察生成智能体，工作目录: {working_dir}")
    tools = [grid_calculator]
    logger.debug(f"洞察生成智能体工具: {tools}")
    system_prompt = render_system_prompt(comparing_principles)
    logger.debug(f"洞察生成智能体系统提示:\n{system_prompt}")
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[log_tool_call, log_model_response],
        debug=debug,
    )
    logger.info(f"洞察生成智能体创建完成，调试模式: {debug}")
    return agent

