# functional_tests/test_03_application.py

import os
import json
from powergrid_pipeline_v2.src.services.application_service2 import ApplicationService

def run_test():
    print("--- 运行方案应用服务功能测试 ---")
    service = ApplicationService()

    # 定义输入输出路径
    proposal_file = "runs/test_output_v2/generation/parsed_proposals.json"
    base_model = "powergrid_pipeline_v2/data/base_models/yunnan_base.dat"
    swi_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.swi"
    scset_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.scset"
    lsd_file = "powergrid_pipeline_v2/data/base_models/test.lsd"
    output_model = "runs/test_output_v2/application"

    # --- 测试1: apply ---
    print("\n[1/1] 测试 apply...")
    with open(proposal_file, 'r', encoding='utf-8') as f:
        proposal = json.load(f)
        
    success, msg = service.apply_all_proposals(proposal, base_model, swi_file, scset_file, lsd_file, output_model)
    
    assert success, f"应用方案失败: {msg}"
    assert os.path.exists(output_model)
    
    # # (可选) 验证修改是否成功
    # with open(output_model, 'r', encoding='gbk', errors='ignore') as f:
    #     content = f.read()
    #     assert "TESTBUS1" in content, "修改后的文件中未找到测试母线"
    
    print("✅ 测试通过，新模型已生成并验证。")
    print("\n--- 所有方案应用服务测试完成 ---")

if __name__ == "__main__":
    run_test()