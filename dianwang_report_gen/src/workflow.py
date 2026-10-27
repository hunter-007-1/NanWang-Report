"""
电网比选报告生成工作流构建模块

本模块使用 LangGraph 框架定义报告生成的完整流水线，包括：
- 数据预处理
- 洞察生成（AI 分析各方案优缺点）
- 证据检索（查找支撑洞察的数据）
- 报告生成（AI 撰写完整比选报告）
- 数值校验（验证报告中数据的准确性）
- 格式转换（导出为 PDF/DOCX）

工作流设计支持暂停机制：在洞察生成后等待人工确认，确认后再继续后续流程。
"""

from loguru import logger
from langgraph.graph import StateGraph, END

from src.graph_state import State
from src.nodes import (
    data_preprocessing_pcn,
    insights_generation_node,
    retrieve_claims_for_insights,
    generate_report,
    verify_pcn_claims,
    convert_report,
)


def build_dianwang_report_gen_workflow_with_pcn():
    """
    构建完整的 PCN（Proof-Carrying Numbers）报告生成工作流。

    流水线顺序：
        数据预处理 -> 洞察生成 -> 证据检索 -> 报告生成 -> 数值校验 -> 格式转换

    Returns:
        StateGraph: 编译后的 LangGraph 工作流对象
    """
    logger.info("构建 PCN 工作流...")
    workflow_builder = StateGraph(State)

    # 添加工作流节点（每个节点对应一个处理步骤）
    workflow_builder.add_node("data_preprocessing_pcn", data_preprocessing_pcn)
    workflow_builder.add_node("insights_generation_node", insights_generation_node)
    workflow_builder.add_node(
        "retrieve_claims_for_insights", retrieve_claims_for_insights
    )
    workflow_builder.add_node("generate_report", generate_report)
    workflow_builder.add_node("verify_pcn_claims", verify_pcn_claims)
    workflow_builder.add_node("convert_report", convert_report)

    # 设置工作流入口点（第一个执行的节点）
    workflow_builder.set_entry_point("data_preprocessing_pcn")

    logger.info("设置工作流边...")

    # 定义节点之间的执行顺序（流水线）
    workflow_builder.add_edge("data_preprocessing_pcn", "insights_generation_node")
    workflow_builder.add_edge(
        "insights_generation_node", "retrieve_claims_for_insights"
    )
    workflow_builder.add_edge("retrieve_claims_for_insights", "generate_report")
    workflow_builder.add_edge("generate_report", "verify_pcn_claims")
    workflow_builder.add_edge("verify_pcn_claims", "convert_report")
    workflow_builder.add_edge("convert_report", END)

    # 编译工作流并返回
    workflow = workflow_builder.compile()
    logger.info("工作流结构:\n" + workflow.get_graph().draw_ascii())
    logger.info("PCN 工作流构建完成")
    return workflow


def build_pcn_workflow_until_insights():
    """
    构建到洞察生成结束的工作流（用于人工确认前暂停）。

    当用户需要先确认 AI 生成的洞察结论时，使用此工作流。
    执行到洞察生成后暂停，等待用户确认后再继续。

    流水线顺序：
        数据预处理 -> 洞察生成 -> 结束（等待确认）

    Returns:
        StateGraph: 编译后的 LangGraph 工作流对象
    """
    logger.info("构建 PCN 前半段工作流（截至洞察生成）...")
    workflow_builder = StateGraph(State)

    workflow_builder.add_node("data_preprocessing_pcn", data_preprocessing_pcn)
    workflow_builder.add_node("insights_generation_node", insights_generation_node)

    workflow_builder.set_entry_point("data_preprocessing_pcn")
    workflow_builder.add_edge("data_preprocessing_pcn", "insights_generation_node")
    workflow_builder.add_edge("insights_generation_node", END)

    workflow = workflow_builder.compile()
    logger.info("前半段工作流构建完成")
    return workflow


def build_pcn_workflow_after_insights():
    """
    构建洞察确认后的工作流（从证据检索到报告转换）。

    当用户在 UI 上确认洞察后，调用此工作流继续执行后续步骤。

    流水线顺序：
        证据检索 -> 报告生成 -> 数值校验 -> 格式转换

    Returns:
        StateGraph: 编译后的 LangGraph 工作流对象
    """
    logger.info("构建 PCN 后半段工作流（洞察确认后继续）...")
    workflow_builder = StateGraph(State)

    workflow_builder.add_node(
        "retrieve_claims_for_insights", retrieve_claims_for_insights
    )
    workflow_builder.add_node("generate_report", generate_report)
    workflow_builder.add_node("verify_pcn_claims", verify_pcn_claims)
    workflow_builder.add_node("convert_report", convert_report)

    workflow_builder.set_entry_point("retrieve_claims_for_insights")
    workflow_builder.add_edge("retrieve_claims_for_insights", "generate_report")
    workflow_builder.add_edge("generate_report", "verify_pcn_claims")
    workflow_builder.add_edge("verify_pcn_claims", "convert_report")
    workflow_builder.add_edge("convert_report", END)

    workflow = workflow_builder.compile()
    logger.info("后半段工作流构建完成")
    return workflow