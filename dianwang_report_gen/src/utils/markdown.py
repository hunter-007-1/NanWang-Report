"""Markdown 和代码块处理相关工具函数"""

import re
from dataclasses import dataclass
from typing import List
from loguru import logger


@dataclass
class CodeBlock:
    """从 markdown 文本中提取的代码块"""

    code: str
    language: str


def extract_visualization_tags(text: str) -> List[str]:
    """从文本中提取可视化标签

    Args:
        text: 包含可视化标签的文本

    Returns:
        提取出的可视化标签列表
    """
    logger.info(f"提取可视化标签，文本长度: {len(text) if text else 0} 字符")
    pattern = r"(<visualization>.*?</visualization>)"
    results = re.findall(pattern, text, flags=re.DOTALL)
    logger.info(f"提取到 {len(results)} 个可视化标签")
    return results


def extract_markdown_code_blocks(markdown_text: str) -> List[CodeBlock]:
    """从 markdown 文本中提取代码块

    Args:
        markdown_text: markdown 格式的文本

    Returns:
        提取出的代码块列表
    """
    logger.info(
        f"提取代码块，文本长度: {len(markdown_text) if markdown_text else 0} 字符"
    )
    pattern = re.compile(r"```(?:\s*([\w\+\-]+))?\n([\s\S]*?)```")
    matches = pattern.findall(markdown_text)
    code_blocks: List[CodeBlock] = []
    for match in matches:
        language = match[0].strip() if match[0] else ""
        code_content = match[1]
        code_blocks.append(CodeBlock(code=code_content, language=language))
    logger.debug(f"提取到 {len(code_blocks)} 个代码块")
    return code_blocks


def extract_markdown_content(markdown_text: str) -> str:
    """从 markdown 文本中提取第一个代码块的内容

    如果没有代码块，则返回原始文本。

    Args:
        markdown_text: markdown 格式的文本

    Returns:
        提取出的代码或原始文本
    """
    extracted_code_blocks = extract_markdown_code_blocks(markdown_text)
    if (
        extracted_code_blocks
        and len(extracted_code_blocks) > 0
        and extracted_code_blocks[0].code
    ):
        return extracted_code_blocks[0].code
    else:
        return markdown_text


def extract_checklist(text: str) -> List[str]:
    """从文本中提取检查清单项目

    Args:
        text: 包含检查清单的文本

    Returns:
        提取出的检查清单项目列表
    """
    # 匹配以 '- ' 开头的项目，直到遇到下一个项目或文本结尾
    checklist_pattern = r"-\s*(.*?)(?=\n-|\Z)"
    raw_items = re.findall(checklist_pattern, text, re.DOTALL)
    cleaned_items = [item.strip() for item in raw_items]
    return cleaned_items


def remove_citations(text: str) -> str:
    """从文本中移除引用标记

    移除 [cite_start]...[cite_source: ..., formula: ...] 格式的引用。
    保留原始数值,移除引用元数据。

    Args:
        text: 包含引用标记的文本

    Returns:
        移除引用后的文本

    Examples:
        >>> text = "成本为 [cite_start]1000[cite_source: data/file.json, formula: sum] 万元"
        >>> remove_citations(text)
        '成本为 1000 万元'

        >>> text = "方案A[cite_start]方案A[cite_source: data/schemes.json, formula: name]是最优的"
        >>> remove_citations(text)
        '方案A方案A是最优的'

        >>> text = "数组为 [cite_start]arr[0][cite_source: data.json, formula: index] 值"
        >>> remove_citations(text)
        '数组为 arr[0] 值'

        >>> text = "值为 [cite_start]123[cite_source: data.json, formula: arr[0] + arr[1]]"
        >>> remove_citations(text)
        '值为 123'
    """
    logger.debug(f"移除引用标记，文本长度: {len(text) if text else 0} 字符")
    # 移除 [cite_start]value[cite_source: ..., formula: ...] 格式的引用
    # 只保留 value 部分
    # 使用精确的正则,正确处理 formula 中包含方括号的情况
    # 模式解释:
    # \[cite_start\] - 匹配起始标记
    # (.+?) - 捕获 value 部分(非贪婪)
    # \[cite_source: - 匹配 source 标记
    # (?:[^\[\]]|\[[^\[\]]*\])* - 匹配内容,允许嵌套的单层方括号
    # \] - 匹配结束的 ]
    pattern = r"\[cite_start\](.+?)\[cite_source:(?:[^\[\]]|\[[^\[\]]*\])*\]"

    def replace_citation(match):
        # 只保留引用标记内的原始值
        return match.group(1)

    result = re.sub(pattern, replace_citation, text)
    logger.debug(f"引用移除完成，结果长度: {len(result)} 字符")
    return result


def strip_markdown_fence_noise(text: str) -> str:
    """去除模型输出中误包裹的最外层 markdown 代码围栏。

    支持以下常见噪声：
    - ```markdown ... ```
    - ```md ... ```
    - # ```markdown ... ```（首行被错误写成标题）
    """
    if text is None:
        return ""

    out = str(text).replace("\r\n", "\n")
    open_pattern = re.compile(r"^(?:#{1,6}\s*)?```(?:markdown|md)?\s*$", re.IGNORECASE)
    close_pattern = re.compile(r"^(?:#{1,6}\s*)?```\s*$", re.IGNORECASE)

    # 最多剥离两层，兼容偶发双重包裹
    for _ in range(2):
        lines = out.split("\n")
        if not lines:
            break

        start = 0
        end = len(lines) - 1
        while start <= end and not lines[start].strip():
            start += 1
        while end >= start and not lines[end].strip():
            end -= 1

        if start >= end:
            break

        first = lines[start].strip()
        last = lines[end].strip()
        if not open_pattern.match(first) or not close_pattern.match(last):
            break

        out = "\n".join(lines[start + 1 : end]).strip("\n")

    return out
