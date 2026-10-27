"""配置、日志和客户端初始化相关工具函数"""

import os
import sys
from datetime import datetime
from pathlib import Path
from loguru import logger
from openai import OpenAI


def init_openai_client(model, api_key, base_url, args, args_attribute_name):
    """初始化 OpenAI 客户端

    Args:
        model: 模型名称
        api_key: API 密钥
        base_url: API 基础 URL
        args: 参数对象
        args_attribute_name: 参数属性名称

    Returns:
        tuple: (client, model, args)
    """
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    if model is None:
        models = client.models.list()
        model = models.data[0].id
        setattr(args, args_attribute_name, model)
    else:
        setattr(args, f"{args_attribute_name}_api_key", "sk-xxxx")
    return client, model, args


def setup_logger(
    output_dir: Path, console_level: str = "INFO", file_level: str = "DEBUG"
):
    """配置日志系统

    Args:
        output_dir: 日志输出目录（Path 对象）
        console_level: 控制台日志级别
        file_level: 文件日志级别
    """
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()  # 移除默认的日志处理器
    logger.add(sys.stderr, level=console_level, colorize=True)
    log_filename = output_dir / "out.log"
    logger.add(
        str(log_filename),
        level=file_level,
    )
    logger.info(f"日志将保存到文件: {log_filename}")


def generate_timestamped_output_directory(
    base_output_dir: Path, suffix: str = None, format_str: str = "%Y-%m-%d_%H-%M-%S"
) -> Path:
    """生成唯一的时间戳输出目录

    Args:
        base_output_dir: 基础输出目录（Path 对象）
        suffix: 目录名后缀（可选）
        format_str: 时间格式字符串

    Returns:
        新创建的时间戳输出目录路径（Path 对象）
    """
    timestamp = datetime.now().strftime(format_str)
    output_name = f"{timestamp}_{suffix}" if suffix else f"{timestamp}"
    output_path = base_output_dir / output_name

    # 创建目录
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path
