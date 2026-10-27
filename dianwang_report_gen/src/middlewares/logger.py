from langchain.agents.middleware import after_model, AgentState, wrap_tool_call
from langgraph.runtime import Runtime
from typing import Any
from loguru import logger
from langchain.tools.tool_node import ToolCallRequest
from langchain.messages import ToolMessage
from langgraph.types import Command
from typing import Callable


@wrap_tool_call
def log_tool_call(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    tool_name = request.tool_call.get("name", "unknown")
    tool_args = request.tool_call.get("args", {})
    tool_id = request.tool_call.get("id", "unknown")

    logger.info(f"工具调用: {tool_name}")
    logger.debug(f"\tID: {tool_id}")
    logger.info(f"\t参数: {tool_args}")

    try:
        result = handler(request)
        # 如果是 ToolMessage，记录结果摘要
        if isinstance(result, ToolMessage):
            result_content = result.content
            logger.info(f"\t结果: {result_content}")

        # 如果是 Command，记录相关信息
        elif isinstance(result, Command):
            logger.debug(f"\tCommand: {result}")

        return result

    except Exception as e:
        logger.error(f"工具调用失败:\n{e}")
        raise


@after_model
def log_model_response(state: AgentState, _: Runtime) -> dict[str, Any] | None:
    last_message = state["messages"][-1]

    # 记录模型返回的内容
    if hasattr(last_message, "content") and last_message.content:
        logger.debug(f"模型响应:\n{last_message.content}")

    # 记录工具调用信息
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return

    return None
