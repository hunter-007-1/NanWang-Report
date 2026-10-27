"""图表生成和代码执行相关工具函数"""

import re
from pathlib import Path
from loguru import logger
from autogen_core import CancellationToken
from autogen_core.code_executor import CodeBlock
from autogen_ext.code_executors.local import (
    LocalCommandLineCodeExecutor,
    CommandLineCodeResult,
)


def format_chart_code(chart_code: str, index: int):
    """格式化图表代码，添加必要的导入和配置

    Args:
        chart_code: 原始图表代码
        index: 图表索引

    Returns:
        tuple: (格式化后的代码, 图表标题, 图表文件名)
    """
    logger.info(f"格式化第 {index} 个图表代码")
    # Default chart title and filename
    chart_title = f"Generated Chart {index}"

    # Try to extract title from the code.
    # It could be chart_title = "...", plt.title("... "), or ax.set_title("... ")
    title_patterns = [
        r"chart_title\s*=\s*['\"](.*?)['\"]",
        r"plt.title\s*\(\s*['\"](.*?)['\"]\s*\)",
        r"ax.set_title\s*\(\s*['\"](.*?)['\"]\s*\)",
        r"plt.savefig\s*\(\s*['\"](.*?)['\"]\s*\)",  # plt.savefig('political_affiliation_covid_impact.png')
    ]

    for pattern in title_patterns:
        title_match = re.search(pattern, chart_code)
        if title_match:
            chart_title = title_match.group(1)
            break

    chart_filename_stem = re.sub(
        r"[^a-z0-9_]+", "", chart_title.lower().replace(" ", "_")
    )
    if chart_filename_stem:
        chart_filename = f"{chart_filename_stem}.png"
    else:
        chart_filename = f"chart_{index}.png"

    logger.debug(f"图表标题: {chart_title}")
    logger.debug(f"图表文件名: {chart_filename}")

    code_to_execute = f"""import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
plt.rcParams['font.sans-serif'] = ['SimSun']
plt.rcParams['axes.unicode_minus'] = False

{chart_code}

plt.savefig('{chart_filename}')
print(f"Chart saved to {chart_filename}")
"""
    return code_to_execute, chart_title, chart_filename


async def execute_code_in_command_line(
    chart_code: str, work_dir: str
) -> CommandLineCodeResult:
    """在命令行中执行 Python 代码

    Args:
        chart_code: 要执行的 Python 代码
        work_dir: 工作目录

    Returns:
        代码执行结果
    """
    logger.debug(f"在目录 {work_dir} 执行以下Python代码:\n{chart_code}")
    work_dir = Path(work_dir)
    work_dir.mkdir(exist_ok=True, parents=True)
    local_executor = LocalCommandLineCodeExecutor(work_dir=work_dir)
    code_blocks = [CodeBlock(language="python", code=chart_code)]
    logger.info(f"在目录 {work_dir} 执行代码块...")
    result = await local_executor.execute_code_blocks(
        code_blocks=code_blocks, cancellation_token=CancellationToken()
    )
    logger.debug(f"代码执行退出码: {result.exit_code}")
    logger.debug(f"代码执行输出长度: {len(result.output)} 字符")
    logger.info(f"代码执行结果:\n{result.output}")
    return result
