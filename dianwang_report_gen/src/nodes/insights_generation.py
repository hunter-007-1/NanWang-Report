from loguru import logger

from src.llm import client_manager
from src.graph_state import State
from src.skills.insights_generation.main import (
    InsightsGenerationInput,
    create_agent as create_insights_generation_agent,
    load_comparing_principles,
    render_prompt as render_insights_generation_prompt,
)


import asyncio


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content).strip() if content else ""


def _is_substantive_ai_message(message) -> bool:
    message_type = getattr(message, "type", "")
    class_name = message.__class__.__name__
    if message_type in {"human", "system", "tool"} or class_name == "ToolMessage":
        return False
    text = _message_text(message)
    if not text or text.startswith("Updated todo list"):
        return False
    return True


def _looks_like_insight_section(text: str, marker: str) -> bool:
    stripped = text.lstrip()
    prefixes = (marker, f"### {marker}", f"#### {marker}")
    return stripped.startswith(prefixes)


def _looks_like_full_insights(text: str) -> bool:
    markers = ("阶段一", "阶段二", "阶段三", "综合推荐")
    if not all(marker in text for marker in markers):
        return False
    return len(text) > 800 or "### 阶段一" in text or "\n阶段一" in text


def _extract_insights_from_messages(messages) -> str:
    candidates = [_message_text(message) for message in messages if _is_substantive_ai_message(message)]
    candidates = [text for text in candidates if text]
    if not candidates:
        return _message_text(messages[-1]) if messages else ""

    full = [text for text in candidates if _looks_like_full_insights(text)]
    if full:
        return full[-1]

    markers = ("阶段一", "阶段二", "阶段三", "综合推荐")
    section_texts = []
    for marker in markers:
        matched = next(
            (text for text in reversed(candidates) if _looks_like_insight_section(text, marker)),
            "",
        )
        if matched and matched not in section_texts:
            section_texts.append(matched)
    if len(section_texts) >= 2:
        return "\n\n".join(section_texts)

    return candidates[-1]

async def insights_generation_node(state: State):
    logger.info("=== 开始洞察生成节点 ===")
    md_tables_str = state.md_tables_str
    working_dir = state.working_dir

    logger.info(f"工作目录: {working_dir}")

    llm_client = client_manager.get_langchain_chat_model()

    logger.info("创建洞察生成智能体...")
    agent = create_insights_generation_agent(
        comparing_principles=load_comparing_principles(),
        model=llm_client,
        working_dir=working_dir,
        debug=state.debug,
    )

    user_prompt = render_insights_generation_prompt(
        InsightsGenerationInput(data_tables=md_tables_str)
    )
    logger.debug(f"用户提示:\n{user_prompt}")

    msg = [
        {
            "role": "user",
            "content": user_prompt,
        },
    ]
    logger.info("正在调用洞察生成智能体...")
    result = await asyncio.to_thread(agent.invoke, {"messages": msg})
    insights = _extract_insights_from_messages(result.get("messages") or [])
    logger.debug(f"洞察生成智能体的生成的洞察:\n{insights}")
    logger.info(f"生成洞察长度: {len(insights)} 字符")

    logger.info("=== 洞察生成节点完成 ===")
    return {
        "first_insights": insights,
        "insights": insights,
    }
