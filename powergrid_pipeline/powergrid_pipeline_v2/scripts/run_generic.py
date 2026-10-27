import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="运行通用电网规划案例。")
    parser.add_argument("--dat", required=True, help="输入 .dat 文件路径。")
    parser.add_argument("--swi", required=True, help="输入 .swi 文件路径。")
    parser.add_argument("--scset", required=True, help="输入 .scset 文件路径。")
    parser.add_argument("--target-count", type=int, default=5, help="目标最终方案数量。")
    parser.add_argument("--task-description", default=None, help="写入 context.json 的任务描述。")
    parser.add_argument("--context-output", default="data/contexts/context_generic.json", help="生成的 context.json 路径。")
    parser.add_argument("--filter-kv", type=float, default=None, help="可选：只保留指定电压等级以上的网架数据。")
    parser.add_argument("--output-root", default="fulfillment_generic", help="运行输出根目录。")
    parser.add_argument("--success-n1-issues", type=int, default=0, help="判定成功的 N-1 问题数。")
    parser.add_argument("--initial-scc-issues", type=int, default=0, help="初始 SCC 问题数默认值。")
    args = parser.parse_args()

    dat_path = Path(args.dat).resolve()
    swi_path = Path(args.swi).resolve()
    scset_path = Path(args.scset).resolve()
    for path in [dat_path, swi_path, scset_path]:
        if not path.exists():
            raise FileNotFoundError(f"输入文件不存在: {path}")

    input_dir = PROJECT_ROOT / "data" / "generic_input"
    input_dir.mkdir(parents=True, exist_ok=True)
    model_stem = dat_path.stem
    runtime_dat = input_dir / f"{model_stem}.dat"
    runtime_swi = input_dir / f"{model_stem}.swi"
    runtime_scset = input_dir / f"{model_stem}.scset"
    shutil.copy2(dat_path, runtime_dat)
    shutil.copy2(swi_path, runtime_swi)
    shutil.copy2(scset_path, runtime_scset)

    context_output = Path(args.context_output)
    if not context_output.is_absolute():
        context_output = PROJECT_ROOT / context_output

    task_description = args.task_description or (
        "请基于用户输入的通用网架模型，生成五个可行的接入系统方案，"
        "重点解决目标 N-1 过载问题，并兼顾短路电流约束。"
    )

    from src.services.preprocessing_service import PreprocessingService

    service = PreprocessingService()
    success, message = service.build_context_from_dat(
        dat_path=str(runtime_dat),
        output_path=str(context_output),
        task_description=task_description,
        filter_kv=args.filter_kv,
    )
    if not success:
        raise RuntimeError(message)

    main_scc = PROJECT_ROOT / "functional_tests" / "main_scc.py"
    command = [
        sys.executable,
        str(main_scc),
        str(runtime_dat),
        str(args.target_count),
        "--context-json",
        str(context_output),
        "--initial-prompt",
        "powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt",
        "--iteration-prompt",
        "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt",
        "--output-root",
        args.output_root,
        "--initial-scc-issues",
        str(args.initial_scc_issues),
        "--success-n1-issues",
        str(args.success_n1_issues),
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(command, cwd=str(PROJECT_ROOT.parent), env=env, check=True)


if __name__ == "__main__":
    main()
