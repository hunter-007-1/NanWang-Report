from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))
from loguru import logger
import json
import argparse
import asyncio
from langchain_openai import ChatOpenAI
import os

from src.workflow import build_dianwang_report_gen_workflow_with_pcn
from src.graph_state import State
from src.utils import (
    setup_logger,
    generate_timestamped_output_directory,
    init_openai_client,
)
from src.llm import client_manager
from src.utils.modelscope_embeddings import ModelScopeEmbeddings


def parse_arguments():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="运行一个带有调试模式的脚本。 ")
    parser.add_argument("--input_dir", type=str, default="data")
    parser.add_argument("--output_dir", type=str, default="outputs")
    parser.add_argument(
        "--llm",
        type=str,
        default=os.getenv("LLM_MODEL", "Qwen/Qwen3-235B-A22B")
        # default="Qwen/Qwen3-30B-A3B-Instruct-2507",  # 魔搭
        # default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        # default="Qwen/Qwen3-Coder-480B-A35B-Instruct",
        # default="deepseek-ai/DeepSeek-V3.2",
        # default="qwen3-235b-a22b-instruct-2507",  # 百炼
        # default="qwen3-30b-a3b-instruct-2507",
        # default="glm-4.7",  # 智谱
        # default="GLM-4.7-FlashX",
    )
    parser.add_argument("--llm_api_key", type=str, default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument(
        "--llm_base_url",
        type=str,
        default=os.getenv("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1")
        # default="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 百炼
        # default="https://api-inference.modelscope.cn/v1",  # 魔搭社区平台
        # default="http://127.0.0.1:8888/v1",  # vllm部署的模型地址
        # default="https://open.bigmodel.cn/api/paas/v4", # 智谱
    )
    parser.add_argument("--llm_temperature", type=float, default=0.6)

    parser.add_argument(
        "--vlm",
        type=str,
        # default="Qwen/Qwen3-VL-32B-Instruct",  # 魔搭
        # default="Qwen/Qwen3-VL-30B-A3B-Instruct",
        default=os.getenv("VLM_MODEL", "Qwen/Qwen3-235B-A22B"),
    )
    parser.add_argument("--vlm_api_key", type=str, default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument(
        "--vlm_base_url",
        type=str,
        default=os.getenv("VLM_BASE_URL", "https://api-inference.modelscope.cn/v1")
        # default="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 百炼
        # default="https://api-inference.modelscope.cn/v1",  # 魔搭社区平台
        # default="http://127.0.0.1:8888/v1",  # vllm部署的模型地址
    )

    parser.add_argument("--vlm_temperature", type=float, default=0.6)
    parser.add_argument("--max_completion_tokens", type=int, default=32768)



    parser.add_argument(
        "--embedding_model",
        type=str,
        default=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"),
        help="Embedding API 模型名称",
    )
    parser.add_argument(
        "--embedding_api_key",
        type=str,
        default=os.getenv("EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY")),
        help="Embedding API Key",
    )
    parser.add_argument(
        "--embedding_base_url",
        type=str,
        default=os.getenv("EMBEDDING_BASE_URL", "https://api-inference.modelscope.cn/v1"),
        help="Embedding API Base URL",
    )

    return parser.parse_args()


async def main():
    logger.info("=== 启动 PCN 工作流 ===")
    args = parse_arguments()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    # 参数初始化
    llm = args.llm
    llm_api_key = args.llm_api_key
    llm_base_url = args.llm_base_url
    llm_temperature = args.llm_temperature

    vlm = args.vlm
    vlm_api_key = args.vlm_api_key
    vlm_base_url = args.vlm_base_url
    vlm_temperature = args.vlm_temperature

    max_completion_tokens = args.max_completion_tokens
    embedding_model = args.embedding_model
    embedding_api_key = args.embedding_api_key
    embedding_base_url = args.embedding_base_url

    logger.info(f"输入目录: {input_dir}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"LLM 模型: {llm}")
    logger.info(f"LLM Base URL: {llm_base_url}")
    logger.info(f"LLM Temperature: {llm_temperature}")
    logger.info(f"最大完成 tokens: {max_completion_tokens}")
    logger.info(f"VLM 模型: {vlm}")
    logger.info(f"VLM Base URL: {vlm_base_url}")
    logger.info(f"Embedding 模型: {embedding_model}")
    logger.info(f"Embedding Base URL: {embedding_base_url}")

    logger.info("初始化 OpenAI 客户端...")
    llm_openai_client, llm, args = init_openai_client(
        llm, llm_api_key, llm_base_url, args, "llm"
    )
    vlm_openai_client, vlm, args = init_openai_client(
        vlm, vlm_api_key, vlm_base_url, args, "vlm"
    )

    output_dir = generate_timestamped_output_directory(output_dir, suffix="main_pcn")
    result_file = output_dir / "result.json"
    logger.info(f"时间戳输出目录: {output_dir}")

    setup_logger(output_dir)
    logger.info(f"启动参数: {vars(args)}")

    working_dir = output_dir / "working_dir"
    working_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"工作目录: {working_dir}")

    logger.info("初始化 LangChain ChatOpenAI 客户端...")
    llm_langchain_client = ChatOpenAI(
        model=llm,
        api_key=llm_api_key,
        base_url=llm_base_url,
        temperature=llm_temperature,
        max_completion_tokens=max_completion_tokens,
    )
    logger.info(f"大模型初始化完成，模型名称：{llm}")

    logger.info(f"初始化 Embedding API 客户端: {embedding_model}")
    embedding_client = ModelScopeEmbeddings(
        model=embedding_model,
        api_key=embedding_api_key,
        base_url=embedding_base_url,
    )

    logger.info("设置客户端管理器...")
    client_manager.setup_llm_openai_client(
        llm_openai_client, llm, llm_temperature, max_completion_tokens
    )
    client_manager.setup_vlm_openai_client(
        vlm_openai_client, vlm, vlm_temperature, max_completion_tokens
    )
    client_manager.setup_embedding_model(
        embedding_model_name_or_path=embedding_model,
        embedding_model=embedding_client,
    )
    client_manager.setup_langchain_chat_model(llm_langchain_client)
    logger.info("客户端管理器设置完成")

    logger.info("构建 PCN 工作流...")
    workflow = build_dianwang_report_gen_workflow_with_pcn()

    logger.info("开始执行工作流...")
    state_dict = await workflow.ainvoke(
        State(
            input_dir=input_dir,
            output_dir=output_dir,
            working_dir=working_dir,
            report_dir=output_dir / "report",
            debug=True,
        )
    )
    logger.info("工作流执行完成")

    logger.info(f"保存执行结果到 {result_file}...")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "md_tables_str": state_dict.get("md_tables_str"),
                "first_insights": state_dict.get("first_insights"),
                "raw_report": state_dict.get("raw_report"),
                "md_report": state_dict.get("md_report"),
                "pcn_claims_count": len(state_dict.get("pcn_claims", {})),
                "pcn_verification_result": state_dict.get("pcn_verification_result"),
                "pcn_verification_passed": state_dict.get("pcn_verification_passed"),
                "pcn_verification_report_path": state_dict.get(
                    "pcn_verification_report_path"
                ),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("执行结果已保存")
    logger.info("=== PCN 工作流执行结束 ===")


if __name__ == "__main__":
    asyncio.run(main())
