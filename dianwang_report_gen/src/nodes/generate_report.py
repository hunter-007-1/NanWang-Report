import os
import base64
import mimetypes
from collections.abc import Sequence
from loguru import logger
import re

from src.llm import client_manager
from src.graph_state import State
from src.utils import (
    format_chart_code,
    execute_code_in_command_line,
    extract_markdown_code_blocks,
)
from src.skills.chart_generation.main import (
    ChartGenerationInput,
    render_prompt as render_chart_generation_prompt,
)
from src.skills.report_generation.main import (
    ReportGenerationInput,
    render_prompt as render_report_generation_prompt,
)
from src.nodes.retrieve_claims_for_insights import (
    ensure_retrieved_claims_within_limit,
    get_max_claims_chars,
)
from src.nodes.safety_recommendation import (
    analyze_safety_for_recommendation,
    enforce_safety_recommendation,
    load_derived_metrics_dict,
)
from src.skills.report_optimization.main import (
    ReportOptimizationInput,
    render_prompt as render_report_optimization_prompt,
)
from src.nodes.report_quality import (
    assess_report_structure,
    ensure_core_summary_tables,
    ensure_standard_chart_section,
    generate_standard_metric_chart,
    protect_verifiable_blocks,
    restore_verifiable_blocks,
)

CHART_STYLE_PROMPT = """
图表风格要求：
- 使用专业的配色方案，确保图表清晰易读
- 图表标题应简洁明了，使用中文
- 坐标轴标签使用中文
- 图例位置合理，不遮挡数据
- 网格线使用浅灰色，便于阅读数据
- 字体大小适中，确保可读性
"""

# 最大重试次数
MAX_CONTINUE_TRIES = 3


def _response_to_mapping(response):
    if response is None:
        return {}

    if isinstance(response, dict):
        return response

    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump()
        except Exception:
            pass

    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass

    result = {}
    for attr in ("choices", "output", "message", "content", "reasoning_content", "finish_reason"):
        try:
            value = getattr(response, attr, None)
        except Exception:
            value = None
        if value is not None:
            result[attr] = value
    return result


def _response_debug_summary(response) -> str:
    mapping = _response_to_mapping(response)
    if not mapping:
        return f"type={type(response).__name__}"

    keys = list(mapping.keys())
    summary = {"type": type(response).__name__, "keys": keys[:12]}

    choices = mapping.get("choices")
    if choices is not None:
        summary["choices_type"] = type(choices).__name__
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
            try:
                summary["choices_len"] = len(choices)
            except Exception:
                pass
        summary["choices_preview"] = repr(choices)[:240]

    output = mapping.get("output")
    if isinstance(output, dict):
        summary["output_keys"] = list(output.keys())[:12]
        output_choices = output.get("choices")
        if isinstance(output_choices, list):
            summary["output_choices_len"] = len(output_choices)

    return str(summary)


def _first_non_empty(*values):
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _coerce_choices(choices):
    if choices is None:
        return []

    if isinstance(choices, list):
        return choices

    if isinstance(choices, tuple):
        return list(choices)

    if isinstance(choices, dict):
        nested_choices = choices.get("choices")
        if nested_choices is not None:
            return _coerce_choices(nested_choices)
        return [choices]

    data = getattr(choices, "data", None)
    if data is not None:
        return _coerce_choices(data)

    if isinstance(choices, Sequence) and not isinstance(
        choices, (str, bytes, bytearray)
    ):
        try:
            return list(choices)
        except Exception:
            pass

    if hasattr(choices, "__iter__") and not isinstance(choices, (str, bytes, bytearray)):
        try:
            return list(choices)
        except Exception:
            pass

    return [choices]


def _flatten_message_content(content) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = _first_non_empty(
                    item.get("text"),
                    item.get("content"),
                    item.get("reasoning_content"),
                )
                if text:
                    parts.append(str(text))
                continue
            text = _first_non_empty(
                getattr(item, "text", None),
                getattr(item, "content", None),
                getattr(item, "reasoning_content", None),
            )
            if text:
                parts.append(str(text))
        return "".join(parts)

    return ""


def _get_first_choice(response, context: str):
    mapping = _response_to_mapping(response)

    choices = _coerce_choices(mapping.get("choices"))
    if not choices:
        choices = _coerce_choices(getattr(response, "choices", None))

    if not choices:
        output = mapping.get("output")
        if isinstance(output, dict):
            choices = _coerce_choices(output.get("choices"))
        elif output is not None:
            choices = _coerce_choices(getattr(output, "choices", None))

    if not choices:
        raise ValueError(
            f"{context} 返回中缺少 choices；响应摘要: {_response_debug_summary(response)}"
        )
    return choices[0]


def _extract_response_text(response, context: str) -> str:
    choice = _get_first_choice(response, context)
    message = getattr(choice, "message", None)
    if message is None and isinstance(choice, dict):
        message = choice.get("message")
    if message is None:
        mapping = _response_to_mapping(choice)
        text = _first_non_empty(
            mapping.get("content"),
            mapping.get("reasoning_content"),
            mapping.get("text"),
            mapping.get("output_text"),
        )
        if text:
            return _flatten_message_content(text) or str(text)
        raise ValueError(
            f"{context} 返回中缺少 message；响应摘要: {_response_debug_summary(response)}"
        )

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    flattened_content = _flatten_message_content(content)
    if flattened_content:
        return flattened_content

    reasoning_content = getattr(message, "reasoning_content", None)
    if reasoning_content is None and isinstance(message, dict):
        reasoning_content = message.get("reasoning_content")
    if reasoning_content:
        return reasoning_content

    if isinstance(message, dict):
        text = _first_non_empty(message.get("text"), message.get("answer"))
        if text:
            return _flatten_message_content(text) or str(text)

    raise ValueError(
        f"{context} 返回中缺少可用文本内容；响应摘要: {_response_debug_summary(response)}"
    )


def _extract_finish_reason(response, context: str) -> str:
    choice = _get_first_choice(response, context)
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason is None and isinstance(choice, dict):
        finish_reason = choice.get("finish_reason")
    return finish_reason or "unknown"


def _get_prefix_param(model_name: str) -> dict:
    """
    根据模型类型返回正确的 prefix/partial 参数

    deepseek 模型使用 prefix 参数
    其他模型（如 OpenAI）使用 partial 参数
    """
    model_lower = model_name.lower()
    if "qwen3" in model_lower:
        return {}
    if "deepseek" in model_lower:
        return {"prefix": True}
    else:
        return {"partial": True}


def _build_chat_completion_kwargs(model_name: str, temperature: float, **kwargs) -> dict:
    params = {
        "model": model_name,
        "temperature": temperature,
        **kwargs,
    }
    if "qwen3" in model_name.lower():
        params["extra_body"] = {"enable_thinking": True}
    return params


async def generate_report(state: State):
    logger.info("=== 开始生成报告节点 ===")
    md_tables_str = state.md_tables_str
    insights = state.insights
    retrieved_claims = state.retrieved_claims
    output_dir = state.output_dir
    report_dir = os.path.join(output_dir, "report")
    os.makedirs(report_dir, exist_ok=True)

    background_context = getattr(state, "background_context", "") or ""
    background_context_source = getattr(state, "background_context_source", "") or ""

    logger.info(f"数据表长度: {len(md_tables_str) if md_tables_str else 0} 字符")
    logger.info(f"洞察长度: {len(insights) if insights else 0} 字符")
    logger.info(
        f"检索 claims 长度: {len(retrieved_claims) if retrieved_claims else 0} 字符"
    )
    logger.info(
        f"背景资料长度: {len(background_context)} 字符"
        + (f"（来源: {background_context_source}）" if background_context_source else "")
    )
    logger.info(f"报告目录: {report_dir}")

    max_claims_chars = get_max_claims_chars()
    if retrieved_claims and len(retrieved_claims) > max_claims_chars:
        logger.warning(
            f"retrieved_claims 长度 {len(retrieved_claims)} 超过上限 {max_claims_chars}，"
            "将在生成报告前重新压缩"
        )
        retrieved_claims = ensure_retrieved_claims_within_limit(
            retrieved_claims, max_chars=max_claims_chars
        )
        logger.info(f"压缩后 retrieved_claims 长度: {len(retrieved_claims)} 字符")

    # 获取 LLM 和 VLM 客户端
    llm_client, llm_model, llm_temperature = client_manager.get_llm_openai_client()
    vlm_client, vlm_model, vlm_temperature = client_manager.get_vlm_openai_client()

    error_message = ""

    # 准备初始报告生成提示
    report_generation_prompt = render_report_generation_prompt(
        ReportGenerationInput(
            data_tables=md_tables_str,
            insights=insights,
            retrieved_claims=retrieved_claims or "",
            background_context=background_context,
        )
    )
    logger.info(f"最终报告 Prompt 长度: {len(report_generation_prompt)} 字符")
    logger.debug(f"初始报告生成提示:\n{report_generation_prompt}")

    # 第一步：生成初始报告（以 # 开头）
    prefix_param = _get_prefix_param(llm_model)
    messages = [{"role": "user", "content": report_generation_prompt}]
    if prefix_param:
        messages.append({"role": "assistant", "content": "# ", **prefix_param})
    logger.debug(f"初始消息:\n{messages}")
    logger.info("开始生成初始报告...")

    # 默认使用程序化固定图表。旧版 LLM 绘图代码流程仅在显式开启时保留兼容性。
    llm_chart_code_enabled = (
        os.getenv("REPORT_ENABLE_LLM_CHART_CODE", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    generation_kwargs = _build_chat_completion_kwargs(
        llm_model,
        llm_temperature,
        messages=messages,
    )
    if llm_chart_code_enabled:
        generation_kwargs["stop"] = ["</visualization>"]
    response = llm_client.chat.completions.create(
        **generation_kwargs
    )
    initial_text = _extract_response_text(response, "初始报告生成")
    logger.debug(f"模型生成的初始报告内容:\n{initial_text}")

    # 检查 finish_reason
    finish_reason = _extract_finish_reason(response, "初始报告生成")
    logger.debug(f"初始生成 finish_reason: {finish_reason}")

    partial_report = initial_text
    # 如果包含不完整的一级标题，补全
    partial_report = _add_missing_level1_title(partial_report)
    all_report_content = ""

    # 第二步：如果包含可视化标签，进行迭代生成
    if (
        llm_chart_code_enabled
        and finish_reason == "stop"
        and "<visualization>" in partial_report
    ):
        logger.info("初始生成因可视化标签停止，开始迭代生成流程。")
        charts_base64_list = []
        chart_count = 0
        continue_tries = 0
        error_message = ""
        logger.info("进入可视化迭代生成循环...")

        while True:
            # 如果包含不完整的可视化标签，补全
            partial_report = _add_missing_visualization_tag(partial_report)

            logger.debug(f"补全后的初始报告内容:\n{partial_report}")
            # 提取可视化请求
            visualization_description = extract_visualization_tag_content(
                partial_report
            )

            if not visualization_description:
                raise ValueError("未能提取到可视化描述")

            chart_count += 1
            logger.info(f"处理第 {chart_count} 个可视化描述...")
            logger.debug(f"可视化描述内容:\n{visualization_description}")

            chart_code_generation_prompt = render_chart_generation_prompt(
                ChartGenerationInput(
                    visualization_description=visualization_description
                )
            )
            logger.debug(f"图表代码生成提示:\n{chart_code_generation_prompt}")

            # 生成图表
            messages = [
                {
                    "role": "user",
                    "content": chart_code_generation_prompt,
                },
            ]

            response = llm_client.chat.completions.create(
                model=llm_model,
                messages=messages,
                temperature=llm_temperature,
            )

            extracted_code_blocks = extract_markdown_code_blocks(
                _extract_response_text(response, "图表代码生成")
            )
            if (
                extracted_code_blocks
                and len(extracted_code_blocks) > 0
                and extracted_code_blocks[0].code
            ):
                chart_code = extracted_code_blocks[0].code
            else:
                chart_code = _extract_response_text(response, "图表代码生成")

            formatted_chart_code, chart_title, chart_filename = format_chart_code(
                chart_code, chart_count
            )

            logger.info(f"第 {chart_count} 个图表绘制中...")
            execute_result = await execute_code_in_command_line(
                formatted_chart_code, work_dir=report_dir
            )

            markdown_image = ""
            if (
                execute_result.exit_code == 0
                and f"Chart saved to {chart_filename}" in execute_result.output
            ):
                chart_generated = True
                logger.info(f"第 {chart_count} 个图表绘制成功，保存为 {chart_filename}")
                markdown_image = f"![{chart_title}]({chart_filename})"
            else:
                chart_generated = False
                error_message = f"Failed to execute chart code for visualization {chart_count}:\n{execute_result.output}"
                logger.error(error_message)
                markdown_image = "Failed to generate chart image."

            # 清理标题中的换行符
            chart_title = chart_title.replace("\n", " ").replace("\\n", " ")

            if chart_generated:
                chart_path = os.path.join(report_dir, chart_filename)
                logger.info(f"图表 {chart_count} 生成成功: {chart_filename}")

                # 将图表结果添加到报告中
                partial_report += f"\n<visualization_result>\n\n{markdown_image}\n\n</visualization_result>\n\n"

                # 编码图像用于后续的 VLM 调用
                image_base64, mime_type = encode_image(chart_path)
                charts_base64_list.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    }
                )

            else:
                # 图表生成失败
                continue_tries += 1
                logger.warning(f"图表 {chart_count} 生成失败:\n{error_message}")
                logger.warning(f"失败的代码:\n{chart_code}")

                # 移除失败的可视化标签
                partial_report = remove_last_visualization_tag(partial_report)

            # 去重：检查并去除重复内容
            partial_report = _remove_duplicate_prefix(partial_report, all_report_content)
            all_report_content += partial_report

            # 准备新的消息继续生成
            prefix_param = _get_prefix_param(vlm_model)
            new_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": report_generation_prompt},
                        charts_base64_list[-1] if charts_base64_list else {},
                    ],
                },
            ]
            if prefix_param:
                new_messages.append(
                    {"role": "assistant", "content": all_report_content, **prefix_param}
                )
            else:
                new_messages.append({"role": "assistant", "content": all_report_content})

            logger.debug(f"继续生成报告的消息列表:\n{new_messages[-2:]}")

            logger.info("调用 VLM 继续生成报告...")
            new_response = vlm_client.chat.completions.create(
                **_build_chat_completion_kwargs(
                    vlm_model,
                    vlm_temperature,
                    messages=new_messages,
                    max_tokens=16384,
                    stop=["</visualization>"],
                )
            )
            partial_report = _extract_response_text(new_response, "可视化续写生成")
            logger.debug(f"新生成的报告部分:\n{partial_report}")

            # 如果没有更多的可视化标签，退出循环
            if "<visualization>" not in partial_report:
                logger.info("报告生成完成，没有更多可视化标签。")
                partial_report = _remove_duplicate_prefix(partial_report, all_report_content)
                all_report_content += partial_report
                break

        logger.info(f"迭代生成完成。共处理 {chart_count} 个图表。")

    else:
        # 没有可视化标签，直接返回初始报告
        logger.info("初始报告中不包含可视化标签，无需迭代生成。")
        all_report_content = partial_report

    # 清理可能残留的 <visualization> 标签
    logger.info("清理可能残留的可视化标签...")
    final_report = remove_visualization_tags(all_report_content)

    # 核心表格和标准图表由程序稳定插入，不再依赖模型决定是否输出。
    final_report, missing_core_sources = ensure_core_summary_tables(
        final_report, md_tables_str or ""
    )
    if missing_core_sources:
        logger.warning("预处理数据中缺少核心汇总表: {}", missing_core_sources)

    working_dir = getattr(state, "working_dir", None)
    derived = load_derived_metrics_dict(working_dir)
    chart_markdown = generate_standard_metric_chart(derived, report_dir)
    final_report = ensure_standard_chart_section(final_report, chart_markdown)

    logger.debug(f"最终报告内容:\n{final_report}")
    logger.info(f"最终报告长度: {len(final_report)} 字符")

    logger.info("=== 开始优化报告 ===")
    optimized_report = await optimize_report(
        final_report, llm_client, llm_model, llm_temperature
    )
    optimized_report = _deduplicate_calculate_prefix_values(optimized_report)

    # 润色后再次执行幂等保底，防止模型遗漏程序化内容。
    optimized_report, missing_core_sources = ensure_core_summary_tables(
        optimized_report, md_tables_str or ""
    )
    optimized_report = ensure_standard_chart_section(optimized_report, chart_markdown)
    safety_analysis = analyze_safety_for_recommendation(derived)
    optimized_report = enforce_safety_recommendation(
        optimized_report, safety_analysis
    )
    quality_summary = assess_report_structure(optimized_report)
    if quality_summary["structure_passed"]:
        logger.info("报告结构检查通过: {}", quality_summary)
    else:
        logger.warning("报告结构检查存在缺项: {}", quality_summary)
    logger.info(f"优化后报告长度: {len(optimized_report)} 字符")

    logger.info("=== 生成报告节点完成 ===")
    return {
        "raw_report": optimized_report,
        "report_quality_result": quality_summary,
    }


def remove_visualization_tags(text: str) -> str:
    # 去除 <visualization>...</visualization> 标签及其内容
    pattern = r"<visualization>.*?</visualization>"
    cleaned_text = re.sub(pattern, "", text, flags=re.DOTALL)

    # 去除 <visualization_result> 和 </visualization_result> 标签本身，保留内容
    cleaned_text = re.sub(r"<visualization_result>", "", cleaned_text)
    cleaned_text = re.sub(r"</visualization_result>", "", cleaned_text)
    return cleaned_text


def _escape_markdown_inequality_markers(text: str) -> str:
    """Escape raw > after a list marker so Markdown does not parse it as a quote."""
    return re.sub(r"^(\s*[-*+]\s+)>(?=\d)", r"\1\\>", text, flags=re.MULTILINE)


def _unwrap_formula_code_fences(text: str) -> str:
    """Remove code fences around prose formulas so Markdown preview keeps rendering."""

    fence_pattern = re.compile(
        r"(^|\n)([ \t]{0,3})```(?:text|plain)?[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]{0,3}```[ \t]*(?=\n|$)",
        flags=re.IGNORECASE,
    )

    def replace(match: re.Match) -> str:
        prefix = match.group(1)
        content = match.group(3).strip()
        if not content:
            return match.group(0)

        looks_like_formula = bool(
            re.search(r"[=×÷]", content)
            or re.search(r"公式|年费用|建设投资|运维成本|折现率|通过率|网损|成本", content)
        )
        looks_like_code = bool(
            re.search(
                r"(^|\n)\s*(const|let|var|function|import|from|class|def|return|if|for|while)\b",
                content,
            )
            or re.search(r"[{};]", content)
        )

        if not looks_like_formula or looks_like_code:
            return match.group(0)

        return f"{prefix}{content}\n"

    return fence_pattern.sub(replace, text)


def encode_image(image_path: str) -> tuple[str, str]:
    logger.debug(f"编码图片路径: {image_path}")
    try:
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "image/png"  # 默认回退类型
            logger.warning(f"无法猜测图片MIME类型，使用默认值: {mime_type}")
        else:
            logger.debug(f"检测到MIME类型: {mime_type}")

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            encoded_string = base64.b64encode(image_data).decode("utf-8")
            logger.debug(
                f"图片编码完成，原始大小: {len(image_data)} 字节，编码后大小: {len(encoded_string)} 字符"
            )
            return encoded_string, mime_type
    except Exception as e:
        logger.error(f"编码图片失败: {e}")
        raise


def extract_visualization_tag_content(text: str) -> str:
    visualization_content = text.split("<visualization>")[-1]
    if "</visualization>" in visualization_content:
        visualization_content = visualization_content.split("</visualization>")[0]
    return visualization_content


def remove_last_visualization_tag(text: str) -> str:
    pattern = r"<visualization>.*?</visualization>"
    # 使用 finditer 找到所有匹配项
    matches = list(re.finditer(pattern, text, flags=re.DOTALL))

    if not matches:
        return text.strip()
    # 获取最后一个匹配项的位置
    last_match = matches[-1]
    start, end = last_match.span()

    # 通过切片移除最后一个匹配项
    return (text[:start] + text[end:]).strip()


def _add_missing_visualization_tag(content: str) -> str:
    if "<visualization>" in content and not content.endswith("</visualization>"):
        if content.count("<visualization>") > content.count("</visualization>"):
            logger.info("Adding missing </visualization> tag to content")
            content += "</visualization>"
    return content


def _add_missing_level1_title(content: str) -> str:
    if not content.startswith("# "):
        logger.warning("Adding missing level 1 title to content")
        content = "# " + content
    return content


async def optimize_report(
    report: str, llm_client, model: str, temperature: float
) -> str:
    """在保护可验证内容的前提下使用 LLM 润色报告。"""
    logger.info("开始优化报告...")

    protected_report, protected_blocks = protect_verifiable_blocks(report)

    optimization_prompt = render_report_optimization_prompt(
        ReportOptimizationInput(report_content=protected_report)
    )

    prefix_param = _get_prefix_param(model)
    optimize_messages = [{"role": "user", "content": optimization_prompt}]
    if prefix_param:
        optimize_messages.append({"role": "assistant", "content": "# ", **prefix_param})

    response = llm_client.chat.completions.create(
        **_build_chat_completion_kwargs(
            model,
            temperature,
            messages=optimize_messages,
        )
    )

    optimized_content = _extract_response_text(response, "报告优化")
    optimized_content = _add_missing_level1_title(optimized_content)
    optimized_content = _escape_markdown_inequality_markers(optimized_content)
    optimized_content = _unwrap_formula_code_fences(optimized_content)
    optimized_content, restored = restore_verifiable_blocks(
        optimized_content, protected_blocks
    )
    if not restored:
        logger.warning("润色模型改变了受保护块标记，本轮润色结果已丢弃")
        return report
    logger.info("报告优化完成")
    return optimized_content


def _remove_duplicate_prefix(new_content: str, existing_content: str) -> str:
    """
    如果 new_content 以 existing_content 的尾部内容开头，则去除重复部分

    示例:
    - existing="AB", new="BC" -> 返回 "BC" (无重复)
    - existing="AB", new="BCD" -> 返回 "CD" (去除重复B)
    - existing="AB", new="ABC" -> 返回 "C" (去除重复AB)
    """
    if not existing_content or not new_content:
        return new_content

    # 从长到短检查重复
    for i in range(min(len(existing_content), len(new_content)), 0, -1):
        if existing_content.endswith(new_content[:i]):
            return new_content[i:]

    return new_content


def _deduplicate_calculate_prefix_values(report_text: str) -> str:
    """去除 `<calculate>` 前紧邻且与 output 同值的重复数值片段。"""

    calc_pattern = re.compile(r"<calculate>(.*?)</calculate>", flags=re.DOTALL | re.IGNORECASE)

    def _extract_output(content: str) -> str:
        m = re.search(
            r"output\s*:\s*(.*?)(?=(?:input\s*:|input_source\s*:|input source\s*:|formula\s*:|$))",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return " ".join(m.group(1).strip().split()) if m else ""

    def _split_num_and_unit(s: str) -> tuple[str, str]:
        s = s.strip().replace(",", "")
        m = re.match(r"^(-?\d+(?:\.\d+)?)(.*)$", s)
        if not m:
            return "", ""
        return m.group(1), m.group(2).strip()

    def _norm_num(num: str) -> str:
        if not num:
            return ""
        try:
            return f"{float(num):.12g}"
        except ValueError:
            return ""

    parts = []
    last_end = 0

    for m in calc_pattern.finditer(report_text):
        before = report_text[last_end:m.start()]
        content = m.group(1).strip()
        output = _extract_output(content)
        output_num, output_unit = _split_num_and_unit(output)

        # 捕获 calculate 前最后一个“数字+可选单位”片段
        tail_match = re.search(r"(-?\d+(?:\.\d+)?\s*[^\d\s<，。；：,.!?\n]*)\s*$", before)
        if tail_match and output_num:
            prefix_token = tail_match.group(1)
            prefix_num, prefix_unit = _split_num_and_unit(prefix_token)

            if _norm_num(prefix_num) == _norm_num(output_num):
                # 删除前缀重复值
                trimmed_before = before[: tail_match.start()]
                parts.append(trimmed_before)
                parts.append(m.group(0))

                # output 无单位但前缀有单位时，把单位移到 calculate 后，避免语义丢失
                if prefix_unit and not output_unit:
                    parts.append(prefix_unit)

                last_end = m.end()
                continue

        parts.append(before)
        parts.append(m.group(0))
        last_end = m.end()

    parts.append(report_text[last_end:])
    return "".join(parts)
