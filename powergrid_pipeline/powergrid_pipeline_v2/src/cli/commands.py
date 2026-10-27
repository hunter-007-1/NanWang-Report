# src/cli/commands.py

import os
import json
from typing import Dict, Any

from ..utils.config import load_config_as_dotdict

def _get_run_dir(task_name: str) -> str:
    """创建一个带时间戳的任务运行目录。"""
    from datetime import datetime
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join("runs", f"task_{task_name}_{run_timestamp}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir

def _save_report(report: Dict[str, Any], report_path: str):
    """将报告字典保存为JSON文件。"""
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 报告已成功保存至: {os.path.abspath(report_path)}")

# --- 命令处理函数 ---

def handle_generate(args):
    """处理 'generate' 命令。"""
    from ..services.generation_services import GenerationService

    print("🚀 开始执行 [AI方案生成] 任务...")
    config = load_config_as_dotdict()
    service = GenerationService(config)
    
    try:
        with open(args.context_json, 'r', encoding='utf-8') as f:
            context = json.load(f)
    except Exception as e:
        print(f"❌ 错误: 无法读取或解析 context JSON 文件 '{args.context_json}': {e}")
        return

    proposals = service.generate_and_parse(args.prompt_template, context)
    
    # 将解析出的方案保存到文件
    if proposals:
        _save_report({"proposals": proposals}, args.output)
    else:
        print("🟡 未能从LLM响应中解析出任何有效方案。")


def handle_apply(args):
    """处理 'apply' 命令。"""
    from ..services.application_service import ApplicationService

    print("🚀 开始执行 [应用规划方案] 任务...")
    config = load_config_as_dotdict()
    service = ApplicationService()

    try:
        with open(args.proposal, 'r', encoding='utf-8') as f:
            proposal = json.load(f)
    except Exception as e:
        print(f"❌ 错误: 无法读取或解析 proposal JSON 文件 '{args.proposal}': {e}")
        return
        
    service.apply(proposal, args.base_model, args.output)


def handle_analyze_power_flow(args):
    """处理 'analyze power-flow' 命令。"""
    from ..services.analysis_services import AnalysisService

    print("🚀 开始执行 [潮流分析] 任务...")
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    
    report = service.analyze_power_flow(args.dat)
    _save_report(report, args.report)


def handle_analyze_n1(args):
    """处理 'analyze n1-security' 命令。"""
    from ..services.analysis_services import AnalysisService

    print("🚀 开始执行 [N-1安全分析] 任务...")
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    
    run_dir = _get_run_dir("n1_security")
    print(f" intermediate files will be saved in: {run_dir}")

    conditions = {"min_voltage_kv": args.min_voltage}
    report = service.analyze_n1_security(args.dat, conditions, run_dir)
    _save_report(report, args.report)


def handle_analyze_scc(args):
    """处理 'analyze short-circuit' 命令。"""
    from ..services.analysis_services import AnalysisService

    print("🚀 开始执行 [短路电流分析] 任务...")
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    
    report = service.analyze_short_circuit(args.dat, args.swi, args.scset_template)
    _save_report(report, args.report)

def handle_preprocess_dat2json(args):
    """处理 'preprocess dat2json' 命令。"""
    from ..services.preprocessing_service import PreprocessingService

    print("🚀 开始执行 [DAT转JSON] 预处理任务...")
    service = PreprocessingService()
    service.dat_to_json(args.dat, args.output, args.filter_kv)

def handle_preprocess_context_builder(args):
    """处理 'preprocess context-builder' 命令。"""
    from ..services.preprocessing_service import PreprocessingService

    print("🚀 开始执行 [构建AI上下文] 预处理任务...")
    service = PreprocessingService()
    service.build_context(
        output_path=args.output,
        dat_path=args.dat,
        grid_structure_json_path=args.grid_json,
        base_context_path=args.base_context,
        reference_content_path=args.reference_content,
        reference_format_path=args.reference_format,
        task_description=args.task_description,
        filter_kv=args.filter_kv,
    )
