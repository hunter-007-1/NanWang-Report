# functional_tests/test_04_analysis.py

import os
import json
from powergrid_pipeline_v2.src.utils.config import load_config_as_dotdict
from powergrid_pipeline_v2.src.services.analysis_services2 import AnalysisService

def run_test():
    print("--- 运行分析服务功能测试 ---")
    config = load_config_as_dotdict()
    service = AnalysisService(config)

    # 定义输入输出路径
    dat_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.dat"
    swi_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.swi"
    scset_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.scset"
    lsd_file = "powergrid_pipeline_v2/data/base_models/test.lsd"
    msg_folder_path = "powergrid_pipeline_v2/data/base_models"

    pf_report_path = "runs/test_output/analysis/pf_report.json"
    n1_report_path = "runs/test_output/analysis/n1_report.json"
    n2_report_path = "runs/test_output/analysis/n2_report.json"
    scc_report_path = "runs/test_output/analysis/scc_report.json"
    sanyong_data_report_path = "runs/test_output/analysis/sanyong_data_report.json"
    sanyong_report_path = "runs/test_output/analysis/sanyong_report.json"


    run_dir_for_n1 = "runs/test_output/analysis/n1_intermediate"
    run_dir_for_n2 = "runs/test_output/analysis/n2_intermediate"
    run_dir_for_sanyong = "runs/test_output/analysis/sanyong_intermediate"

    # # --- 测试1: analyze_power_flow ---
    # print("\n[1/6] 测试 analyze_power_flow...")
    # report = service.analyze_power_flow(dat_file)
    # # assert "error" not in report, f"潮流分析失败: {report.get('error')}"
    # # assert report["execution_success"] is True, "潮流计算程序执行失败"
    # os.makedirs(os.path.dirname(pf_report_path), exist_ok=True)
    # with open(pf_report_path, 'w', encoding='utf-8') as f:
    #     json.dump(report, f, indent=2, ensure_ascii=False)
    # print("✅ 测试通过，潮流分析报告已生成。")

    # --- 测试2: analyze_n_security (n-1测试)---
    print("\n[2/6] 测试 analyze_n_security (n-1测试)...")
    n1_conditions = {
        "min_voltage_kv": 500.0,  # 最小电压等级 (kV)
        "ckt_id": "2"             # CKT ID 筛选条件
        }
    report = service.analyze_n_security(dat_file, n1_conditions, run_dir_for_n1)
    assert "error" not in report, f"N-1分析失败: {report.get('error')}"
    with open(n1_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("✅ 测试通过，N-1分析报告已生成。")

    # # --- 测试3: analyze_n2_security (n-2测试)---
    # print("\n[3/6] analyze_n_security (n-2测试)...")
    # n2_conditions = {
    #     "min_voltage_kv": 500.0,  # 最小电压等级 (kV)
    #     "ckt_id": "3"             # CKT ID 筛选条件
    #     }
    # report = service.analyze_n_security(dat_file, n2_conditions, run_dir_for_n2)
    # assert "error" not in report, f"N-2分析失败: {report.get('error')}"
    # with open(n2_report_path, 'w', encoding='utf-8') as f:
    #     json.dump(report, f, indent=2, ensure_ascii=False)
    # print("✅ 测试通过，N-2分析报告已生成。")

    # --- 测试4: analyze_short_circuit ---
    # print("\n[4/6] analyze_short_circuit...")
    # report = service.analyze_short_circuit(dat_file, swi_file, scset_file)
    # with open(scc_report_path, 'w', encoding='utf-8') as f:
    #     json.dump(report, f, indent=2, ensure_ascii=False)
    # print("✅ 测试通过，scc分析报告已生成。")

    # # --- 测试5: analyze_transient_stability ---
    # print("\n[5/6] analyze_transient_stability...")
    # report = service.analyze_transient_stability(dat_file, swi_file, lsd_file)
    # with open(sanyong_data_report_path, 'w', encoding='utf-8') as f:
    #     json.dump(report, f, indent=2, ensure_ascii=False)
    # print("✅ 测试通过，暂态n-1调用数据已完成。")

    # print("\n[6/6] analyze_stability_msg...")
    # report = service.analyze_stability_msg(msg_folder_path, sanyong_report_path)
    # with open(sanyong_report_path, 'w', encoding='utf-8') as f:
    #     json.dump(report, f, indent=2, ensure_ascii=False)
    # print("✅ 测试通过，暂态n-1分析报告已生成。")

    print("\n--- 所有分析服务测试完成 ---")

if __name__ == "__main__":
    run_test()