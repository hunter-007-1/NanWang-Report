# main_cli.py

import argparse
from src.cli import commands

def main():
    """
    PowerGrid Pipeline - 主命令行接口 (CLI)
    """
    parser = argparse.ArgumentParser(
        description="一个用于电网规划方案生成、应用和分析的命令行工具集。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="可用的命令")

    # --- 命令 A: generate ---
    p_gen = subparsers.add_parser("generate", help="调用AI大模型生成规划方案。")
    p_gen.add_argument("--prompt-template", required=True, help="Prompt模板文件路径 (e.g., data/prompts/template.txt)")
    p_gen.add_argument("--context-json", required=True, help="包含填充模板所需上下文的JSON文件路径。")
    p_gen.add_argument("--output", required=True, help="保存解析后方案的输出JSON文件路径。")
    p_gen.set_defaults(func=commands.handle_generate)

    # --- 命令 B: apply ---
    p_apply = subparsers.add_parser("apply", help="将一个方案JSON应用到基础.dat模型上。")
    p_apply.add_argument("--proposal", required=True, help="包含规划方案的JSON文件路径。")
    p_apply.add_argument("--base-model", required=True, help="基础.dat模型的文件路径。")
    p_apply.add_argument("--output", required=True, help="保存修改后新.dat模型的输出路径。")
    p_apply.set_defaults(func=commands.handle_apply)

    # --- 命令 C: analyze ---
    p_analyze = subparsers.add_parser("analyze", help="执行一项或多项分析任务。")
    analyze_subparsers = p_analyze.add_subparsers(dest="analysis_type", required=True, help="选择分析类型")

    # 子命令 C.1: analyze power-flow
    p_pf = analyze_subparsers.add_parser("power-flow", help="执行基础潮流计算和分析。")
    p_pf.add_argument("--dat", required=True, help="要分析的.dat文件路径。")
    p_pf.add_argument("--report", required=True, help="保存分析报告的JSON文件路径。")
    p_pf.set_defaults(func=commands.handle_analyze_power_flow)
    
    # 子命令 C.2: analyze n1-security
    p_n1 = analyze_subparsers.add_parser("n1-security", help="执行N-1安全裕度分析。")
    p_n1.add_argument("--dat", required=True, help="要分析的.dat文件路径。")
    p_n1.add_argument("--min-voltage", type=float, default=500.0, help="执行N-1分析的最低电压等级 (kV)。")
    p_n1.add_argument("--report", required=True, help="保存分析报告的JSON文件路径。")
    p_n1.set_defaults(func=commands.handle_analyze_n1)
    
    # 子命令 C.3: analyze short-circuit
    p_scc = analyze_subparsers.add_parser("short-circuit", help="执行短路电流分析。")
    p_scc.add_argument("--dat", required=True, help="要分析的.dat文件路径。")
    p_scc.add_argument("--swi", required=True, help="对应的.swi文件路径。")
    p_scc.add_argument("--scset-template", required=True, help="用于生成计算配置的.scset模板文件路径。")
    p_scc.add_argument("--report", required=True, help="保存分析报告的JSON文件路径。")
    p_scc.set_defaults(func=commands.handle_analyze_scc) # 绑定新的处理函数

    # --- 命令 D: preprocess ---
    p_preprocess = subparsers.add_parser("preprocess", help="执行数据预处理任务。")
    preprocess_subparsers = p_preprocess.add_subparsers(dest="preprocess_type", required=True, help="选择预处理类型")

    # 子命令 D.1: preprocess dat2json
    p_d2j = preprocess_subparsers.add_parser("dat2json", help="将.dat文件转换为JSON格式。")
    p_d2j.add_argument("--dat", required=True, help="输入的.dat文件路径。")
    p_d2j.add_argument("--output", required=True, help="输出的JSON文件路径。")
    p_d2j.add_argument("--filter-kv", type=float, default=None, help="(可选) 仅保留高于此电压等级(kV)的设备。")
    p_d2j.set_defaults(func=commands.handle_preprocess_dat2json)

    # 子命令 D.2: preprocess context-builder
    p_cb = preprocess_subparsers.add_parser("context-builder", help="从多个源文件聚合生成一个AI上下文(context.json)文件。")
    p_cb.add_argument("--output", required=True, help="最终生成的 context.json 的输出路径。")
    p_cb.add_argument("--dat", default=None, help="(可选) 输入的 .dat 文件路径，将自动转换后写入 context。")
    p_cb.add_argument("--grid-json", default=None, help="(可选) 已转换好的网架结构JSON文件路径。")
    p_cb.add_argument("--base-context", default=None, help="(可选) 基础 context.json 模板路径。")
    p_cb.add_argument("--reference-content", default=None, help="(可选) 参考资料文本文件路径。")
    p_cb.add_argument("--reference-format", default=None, help="(可选) 方案输出格式JSON文件路径。")
    p_cb.add_argument("--task-description", default=None, help="(可选) 写入 context 的任务描述。")
    p_cb.add_argument("--filter-kv", type=float, default=None, help="(可选) 仅保留高于此电压等级(kV)的设备。")
    p_cb.set_defaults(func=commands.handle_preprocess_context_builder)
    
    # 解析参数并调用对应的处理函数
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
