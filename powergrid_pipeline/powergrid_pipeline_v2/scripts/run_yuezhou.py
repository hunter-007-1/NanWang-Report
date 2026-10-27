import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="运行越州专用案例。")
    parser.add_argument("--dat", default="powergrid_pipeline_v2/data/base_yuezhou/yunnan_base.dat", help="越州基础 .dat 模型路径。")
    parser.add_argument("--target-count", type=int, default=5, help="目标最终方案数量。")
    parser.add_argument("--output-root", default="fulfillment_yuezhou", help="运行输出根目录。")
    parser.add_argument("--success-n1-issues", type=int, default=0, help="判定成功的 N-1 问题数。")
    args = parser.parse_args()

    main_scc = PROJECT_ROOT / "functional_tests" / "main_scc.py"
    command = [
        sys.executable,
        str(main_scc),
        args.dat,
        str(args.target_count),
        "--context-json",
        "powergrid_pipeline_v2/data/context_yuezhou.json",
        "--n1-report",
        "fulfillment_yuezhou/analysis_1/n1_report_1.json",
        "--initial-prompt",
        "powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt",
        "--iteration-prompt",
        "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt",
        "--output-root",
        args.output_root,
        "--initial-scc-issues",
        "0",
        "--success-n1-issues",
        str(args.success_n1_issues),
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(command, cwd=str(PROJECT_ROOT.parent), env=env, check=True)


if __name__ == "__main__":
    main()
