"""文件和输入输出相关工具函数"""

import json
import inspect
from pathlib import Path
from loguru import logger
from typing import Any, Optional


def load_json(file_path: str) -> Any:
    """加载 JSON 文件

    Args:
        file_path: JSON 文件路径

    Returns:
        JSON 解析后的数据
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"JSON 文件加载成功: {file_path}")
    return data


def load_system_prompt_template(
    file_name: str = "system_prompt_template.md",
    dir_path: Optional[str] = None,
    encoding: str = "utf-8",
) -> str:
    """加载系统提示词模板

    Args:
        file_name: 模板文件名
        dir_path: 模板所在目录，默认为调用者所在目录
        encoding: 文件编码

    Returns:
        模板内容
    """
    if dir_path is None:
        caller_frame = inspect.currentframe().f_back
        if caller_frame is not None:
            caller_file = caller_frame.f_globals.get("__file__")
            if caller_file:
                dir_path = str(Path(caller_file).parent)
        path = Path(dir_path) / file_name
    else:
        path = Path(dir_path) / file_name

    if not path.exists():
        logger.error(f"提示词模板文件不存在: {path}")
        raise FileNotFoundError(f"提示词模板文件不存在: {path}")

    try:
        content = path.read_text(encoding=encoding)
        logger.info(f"成功加载提示词模板: {path}")
        return content
    except UnicodeDecodeError as e:
        logger.error(f"文件编码错误: {path}, 编码: {encoding}, 错误: {e}")
        raise
