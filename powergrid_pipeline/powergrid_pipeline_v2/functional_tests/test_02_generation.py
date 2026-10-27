# functional_tests/test_02_generation.py

import os
import json
from powergrid_pipeline_v2.src.utils.config import load_config_as_dotdict
from powergrid_pipeline_v2.src.services.generation_services import GenerationService

def run_test():
    print("--- 运行AI生成服务功能测试 ---")
    config = load_config_as_dotdict()
    service = GenerationService(config)

    # 定义输入输出路径
    prompt_template = "powergrid_pipeline_v2/data/prompts/generate_shuifu_solution2_3.txt"
    context_file = "powergrid_pipeline_v2/data/context_DAS.json"
    raw_output = "runs/test_output_v2/generation/llm_raw_output.txt"
    parsed_output = "runs/test_output_v2/generation/parsed_proposals.json"

    # --- 测试1: generate_and_parse ---
    print("\n[1/1] 测试 generate_and_parse...")
    with open(context_file, 'r', encoding='utf-8') as f:
        context = json.load(f)
    
    try:
        proposals = service.generate_and_parse(
            prompt_template_path=prompt_template,
            context=context,
            save_raw_output_path=raw_output
        )
        assert isinstance(proposals, list), "返回的不是一个列表"
        assert len(proposals) > 0, "未能解析出任何方案"
        print(f"✅ 测试通过，成功解析出 {len(proposals)} 个方案。")
        
        # 保存解析结果
        with open(parsed_output, 'w', encoding='utf-8') as f:
            json.dump({"proposals": proposals}, f, indent=2, ensure_ascii=False)

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        assert False, "AI生成或解析过程中发生异常"

    print("\n--- 所有AI生成服务测试完成 ---")

if __name__ == "__main__":
    run_test()